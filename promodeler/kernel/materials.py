from __future__ import annotations

import warnings

import bpy

from promodeler.core.diagnostics import ModelingError


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


def build_material(spec: dict) -> bpy.types.Material:
    mat = bpy.data.materials.new(spec["id"])
    tree = ensure_node_tree(mat)
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None) or tree.nodes.new(
            "ShaderNodeOutputMaterial"
        )
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    base = linear_rgba(spec["base_color"])
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Roughness"].default_value = spec["roughness"]
    bsdf.inputs["Metallic"].default_value = spec["metallic"]
    bsdf.inputs["Emission Color"].default_value = linear_rgba(spec["emission_color"])
    bsdf.inputs["Emission Strength"].default_value = spec["emission_strength"]
    bsdf.inputs["Alpha"].default_value = base[3]
    if spec["alpha_mode"] == "blend":
        mat.surface_render_method = "BLENDED"
    else:
        mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = not spec["double_sided"]
    return mat
