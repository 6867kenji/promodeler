"""Material compilation: constants straight to Principled, procedural graphs baked to textures."""

from __future__ import annotations

import os
import time
import warnings
from dataclasses import dataclass, field

import bpy

from promodeler.core.diagnostics import ModelingError

from .fields import FieldCompiler, sock

COLOR_CHANNELS = ("base_color", "emission_color")
SCALAR_CHANNELS = ("roughness", "metallic", "emission_strength")


def ensure_node_tree(block) -> bpy.types.NodeTree:
    """Blender 5 creates node trees by default; older builds need ``use_nodes``."""
    if getattr(block, "node_tree", None) is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            block.use_nodes = True
    if block.node_tree is None:
        raise ModelingError("material.nodes", f"Could not create a node tree for {block.name!r}.")
    return block.node_tree


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_rgba(color: list[float]) -> tuple[float, float, float, float]:
    r, g, b, a = color
    return (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b), a)


def _is_const(spec: dict | None) -> bool:
    return spec is None or spec["kind"] in ("const", "color")


def channel_is_constant(spec: dict, channel: str) -> bool:
    """A channel is constant when its base value is constant and no layer touches it."""
    return _is_const(spec[channel]) and all(layer[channel] is None for layer in spec["layers"])


def _fresh_material(name: str) -> tuple[bpy.types.Material, bpy.types.NodeTree, bpy.types.Node]:
    mat = bpy.data.materials.new(name)
    tree = ensure_node_tree(mat)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)
    return mat, tree, output


def _apply_surface_settings(mat: bpy.types.Material, spec: dict) -> None:
    mat.surface_render_method = "BLENDED" if spec["alpha_mode"] == "blend" else "DITHERED"
    mat.use_backface_culling = not spec["double_sided"]


def build_constant_material(spec: dict) -> bpy.types.Material:
    mat, tree, output = _fresh_material(spec["id"])
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base = linear_rgba(spec["base_color"]["value"])
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Roughness"].default_value = spec["roughness"]["value"]
    bsdf.inputs["Metallic"].default_value = spec["metallic"]["value"]
    bsdf.inputs["Emission Color"].default_value = linear_rgba(spec["emission_color"]["value"])
    bsdf.inputs["Emission Strength"].default_value = spec["emission_strength"]["value"]
    bsdf.inputs["Alpha"].default_value = base[3]
    _apply_surface_settings(mat, spec)
    return mat


@dataclass
class ProceduralMaterial:
    material: bpy.types.Material
    tree: bpy.types.NodeTree
    output: bpy.types.Node
    bsdf: bpy.types.Node
    sockets: dict = field(default_factory=dict)  # channel -> socket or constant
    has_height: bool = False


def build_procedural_material(spec: dict) -> ProceduralMaterial:
    """One node graph whose composited channels feed a Principled BSDF."""
    mat, tree, output = _fresh_material(spec["id"])
    fc = FieldCompiler(tree)
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    current: dict = {}
    for name in COLOR_CHANNELS:
        current[name] = fc.color(spec[name])
    for name in SCALAR_CHANNELS:
        current[name] = fc.scalar(spec[name])
    current["height"] = None if spec["height"] is None else fc.scalar(spec["height"])

    for layer in spec["layers"]:
        mask = fc.scalar(layer["mask"])
        for name in COLOR_CHANNELS:
            if layer[name] is not None:
                current[name] = fc.mix_color(current[name], fc.color(layer[name]), mask)
        for name in SCALAR_CHANNELS:
            if layer[name] is not None:
                current[name] = fc.mix_scalar(current[name], fc.scalar(layer[name]), mask)
        if layer["height"] is not None:
            below = 0.0 if current["height"] is None else current["height"]
            current["height"] = fc.mix_scalar(below, fc.scalar(layer["height"]), mask)

    fc._value(bsdf.inputs["Base Color"], current["base_color"])
    fc._value(bsdf.inputs["Roughness"], current["roughness"])
    fc._value(bsdf.inputs["Metallic"], current["metallic"])
    fc._value(bsdf.inputs["Emission Color"], current["emission_color"])
    fc._value(bsdf.inputs["Emission Strength"], current["emission_strength"])

    has_height = current["height"] is not None and not isinstance(current["height"], float)
    if has_height:
        bump = tree.nodes.new("ShaderNodeBump")
        sock(bump, "Strength").default_value = spec["bump_strength"]
        sock(bump, "Distance").default_value = 1.0
        tree.links.new(current["height"], sock(bump, "Height"))
        tree.links.new(sock(bump, "Normal", output=True), bsdf.inputs["Normal"])

    _apply_surface_settings(mat, spec)
    return ProceduralMaterial(mat, tree, output, bsdf, current, has_height)


def build_material(spec: dict) -> tuple[bpy.types.Material, ProceduralMaterial | None]:
    if not spec["needs_bake"]:
        return build_constant_material(spec), None
    procedural = build_procedural_material(spec)
    return procedural.material, procedural


# --- baking -----------------------------------------------------------------


def _select_only(obj: bpy.types.Object) -> None:
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _configure_bake(samples: int) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 0
    scene.render.bake.use_selected_to_active = False
    scene.render.bake.use_clear = False  # images are pre-filled with a sentinel; see _fill_unbaked


SENTINEL = (1.0, 0.0, 1.0, 1.0)  # magenta: never a plausible baked value


def _new_image(name: str, resolution: int, color: bool) -> bpy.types.Image:
    image = bpy.data.images.new(name, resolution, resolution, alpha=False, float_buffer=False)
    image.colorspace_settings.name = "sRGB" if color else "Non-Color"
    import numpy as np

    count = image.size[0] * image.size[1]
    image.pixels.foreach_set(np.tile(np.array(SENTINEL, dtype=np.float32), count))
    return image


def _fill_unbaked(image: bpy.types.Image) -> int:
    """Replace texels the bake never wrote (tiny UV islands between texel centers, far from any
    island margin) with the mean of the baked texels, so they sample the material's average
    instead of black. Returns the number of texels filled."""
    import numpy as np

    count = image.size[0] * image.size[1]
    buffer = np.empty(count * 4, dtype=np.float32)
    image.pixels.foreach_get(buffer)
    px = buffer.reshape(-1, 4)
    unbaked = (px[:, 0] > 0.999) & (px[:, 1] < 0.001) & (px[:, 2] > 0.999)
    filled = int(unbaked.sum())
    if filled and filled < count:
        px[unbaked] = px[~unbaked].mean(axis=0)
        image.pixels.foreach_set(px.ravel())
    return filled


def _bake_into(proc: ProceduralMaterial, image: bpy.types.Image, bake_type: str, source=None, margin: int = 8) -> None:
    tree = proc.tree
    target = tree.nodes.new("ShaderNodeTexImage")
    target.image = image
    tree.nodes.active = target
    temp = [target]
    surface = proc.output.inputs["Surface"]
    for link in list(surface.links):
        tree.links.remove(link)
    if bake_type == "EMIT":
        emission = tree.nodes.new("ShaderNodeEmission")
        temp.append(emission)
        if isinstance(source, float):
            emission.inputs["Color"].default_value = (source, source, source, 1.0)
        else:
            tree.links.new(source, emission.inputs["Color"])
        emission.inputs["Strength"].default_value = 1.0
        tree.links.new(emission.outputs["Emission"], surface)
    else:
        tree.links.new(proc.bsdf.outputs["BSDF"], surface)
    try:
        result = bpy.ops.object.bake(
            type=bake_type, margin=margin, use_clear=False, normal_space="TANGENT",
            target="IMAGE_TEXTURES", save_mode="INTERNAL",
        )
        if "FINISHED" not in result:
            raise ModelingError("bake.failed", f"Bake {bake_type} did not finish: {result}.")
        _fill_unbaked(image)
    finally:
        for node in temp:
            tree.nodes.remove(node)
        for link in list(surface.links):
            tree.links.remove(link)
        tree.links.new(proc.bsdf.outputs["BSDF"], surface)


def _save(image: bpy.types.Image, path: str) -> None:
    image.filepath_raw = path
    image.file_format = "PNG"
    image.save()


def bake_plan(spec: dict, proc: ProceduralMaterial) -> list[tuple[str, str, bool]]:
    """(channel, bake type, is color) for every channel that is not a constant."""
    plan = []
    for channel in ("base_color", "roughness", "metallic", "emission_color"):
        if not channel_is_constant(spec, channel):
            plan.append((channel, "EMIT", channel in ("base_color", "emission_color")))
    if not channel_is_constant(spec, "emission_strength") and "emission_color" not in [p[0] for p in plan]:
        plan.append(("emission_color", "EMIT", True))
    if proc.has_height:
        plan.append(("normal", "NORMAL", False))
    return plan


def texture_path(out_dir: str, part_id: str, channel: str) -> str:
    return os.path.join(out_dir, f"{part_id}_{channel}.png")


def load_textures(spec: dict, proc: ProceduralMaterial, quality: dict, out_dir: str, part_id: str) -> dict | None:
    """Load a previously baked texture set; ``None`` when any file is missing."""
    resolution = quality["texture_resolution"]
    textures: dict = {}
    for channel, _, is_color in bake_plan(spec, proc):
        path = texture_path(out_dir, part_id, channel)
        if not os.path.isfile(path):
            return None
        image = bpy.data.images.load(path)
        image.name = f"{part_id}:{channel}"
        image.colorspace_settings.name = "sRGB" if is_color else "Non-Color"
        if image.size[0] != resolution:
            return None
        textures[channel] = {
            "path": path, "resolution": resolution, "colorspace": "sRGB" if is_color else "Non-Color",
            "seconds": 0.0, "cached": True, "image": image.name,
        }
    return textures


def bake_part(obj: bpy.types.Object, spec: dict, proc: ProceduralMaterial, quality: dict, out_dir: str, part_id: str) -> dict:
    """Bake every non-constant channel of ``proc`` for ``obj`` and return texture metadata."""
    resolution = quality["texture_resolution"]
    samples = quality["bake_samples"]
    margin = max(2, resolution // 128)
    os.makedirs(out_dir, exist_ok=True)
    _select_only(obj)
    _configure_bake(samples)
    textures: dict = {}
    for channel, bake_type, is_color in bake_plan(spec, proc):
        started = time.perf_counter()
        image = _new_image(f"{part_id}:{channel}", resolution, is_color)
        if bake_type == "EMIT":
            source = proc.sockets[channel]
            if channel == "emission_color":
                strength = proc.sockets["emission_strength"]
                if not (isinstance(strength, float) and strength == 1.0):
                    if isinstance(source, float):
                        fc = FieldCompiler(proc.tree)
                        source = fc._c_color({"value": [source, source, source, 1.0]})
                    source = _scale_color(proc.tree, source, strength)
            _bake_into(proc, image, "EMIT", source, margin)
        else:
            _bake_into(proc, image, "NORMAL", None, margin)
        path = texture_path(out_dir, part_id, channel)
        _save(image, path)
        textures[channel] = {
            "path": path, "resolution": resolution, "colorspace": "sRGB" if is_color else "Non-Color",
            "seconds": round(time.perf_counter() - started, 3), "cached": False, "image": image.name,
        }
    return textures


def _scale_color(tree, color_socket, strength):
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type = "RGBA"
    node.blend_type = "MULTIPLY"
    sock(node, "Factor_Float").default_value = 1.0
    tree.links.new(color_socket, sock(node, "A_Color"))
    if isinstance(strength, float):
        sock(node, "B_Color").default_value = (strength, strength, strength, 1.0)
    else:
        tree.links.new(strength, sock(node, "B_Color"))
    return sock(node, "Result_Color", output=True)


def build_baked_material(spec: dict, textures: dict, part_id: str) -> bpy.types.Material:
    """A renderer-agnostic Principled material reading the baked texture set."""
    mat, tree, output = _fresh_material(f"{spec['id']}:{part_id}")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def image_node(channel: str):
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images[textures[channel]["image"]]
        node.interpolation = "Linear"
        return node

    if "base_color" in textures:
        tree.links.new(image_node("base_color").outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = linear_rgba(spec["base_color"]["value"])
    for channel, input_name in (("roughness", "Roughness"), ("metallic", "Metallic")):
        if channel in textures:
            tree.links.new(image_node(channel).outputs["Color"], bsdf.inputs[input_name])
        else:
            bsdf.inputs[input_name].default_value = spec[channel]["value"]
    if "emission_color" in textures:
        tree.links.new(image_node("emission_color").outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
    else:
        bsdf.inputs["Emission Color"].default_value = linear_rgba(spec["emission_color"]["value"])
        bsdf.inputs["Emission Strength"].default_value = spec["emission_strength"]["value"]
    if "normal" in textures:
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        normal_map.space = "TANGENT"
        tree.links.new(image_node("normal").outputs["Color"], normal_map.inputs["Color"])
        tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    _apply_surface_settings(mat, spec)
    return mat
