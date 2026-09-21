"""Compile field recipes into Cycles shader nodes."""

from __future__ import annotations

import bpy
from mathutils import Vector

from promodeler.core.diagnostics import ModelingError

from . import space

AXIS_SOCKET_BLENDER = {"x": "X", "y": "Z", "z": "Y"}


def sock(node, identifier: str, output: bool = False):
    for s in node.outputs if output else node.inputs:
        if s.identifier == identifier or s.name == identifier:
            return s
    raise ModelingError("field.socket", f"Node {node.bl_idname} has no socket {identifier!r}.")


def _linear(color: list[float]) -> tuple[float, float, float, float]:
    def d(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (d(color[0]), d(color[1]), d(color[2]), color[3])


class FieldCompiler:
    """Builds nodes in ``tree``. Scalar results are float sockets; color results are color sockets."""

    def __init__(self, tree: bpy.types.NodeTree) -> None:
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links
        self.coords = self.nodes.new("ShaderNodeTexCoord")
        self.geometry = self.nodes.new("ShaderNodeNewGeometry")
        self._x = 0

    def _new(self, idname: str):
        node = self.nodes.new(idname)
        self._x += 1
        node.location = (-200.0 * (self._x % 40), -160.0 * (self._x // 40))
        return node

    def _link(self, from_socket, to_socket) -> None:
        self.links.new(from_socket, to_socket)

    def _value(self, socket, value) -> None:
        """Connect a compiled socket or set a default constant."""
        if isinstance(value, (int, float)):
            socket.default_value = value
        else:
            self._link(value, socket)

    def _mapped_coords(self, size):
        sizes = size if isinstance(size, list) else [size, size, size]
        mapping = self._new("ShaderNodeMapping")
        mapping.vector_type = "POINT"
        self._link(sock(self.coords, "Object", output=True), sock(mapping, "Vector"))
        # Authoring axes (x, y, z) become Blender (x, z, y); scale magnitudes only.
        sock(mapping, "Scale").default_value = (1.0 / sizes[0], 1.0 / sizes[2], 1.0 / sizes[1])
        return sock(mapping, "Vector", output=True)

    def scalar(self, spec: dict):
        kind = spec["kind"]
        if kind == "const":
            return float(spec["value"])
        handler = getattr(self, f"_s_{kind}", None)
        if handler is None:
            raise ModelingError("field.kind", f"Unknown scalar field kind {kind!r}.")
        return handler(spec)

    def color(self, spec: dict):
        kind = spec["kind"]
        handler = getattr(self, f"_c_{kind}", None)
        if handler is None:
            raise ModelingError("field.kind", f"Unknown color field kind {kind!r}.")
        return handler(spec)

    # --- scalar sources ---

    def _s_noise(self, spec):
        node = self._new("ShaderNodeTexNoise")
        node.noise_dimensions = "4D"
        node.normalize = True
        self._link(self._mapped_coords(spec["size"]), sock(node, "Vector"))
        sock(node, "W").default_value = float(spec["seed"]) * 7.31
        sock(node, "Scale").default_value = 1.0
        sock(node, "Detail").default_value = spec["detail"]
        sock(node, "Roughness").default_value = spec["roughness"]
        sock(node, "Lacunarity").default_value = spec["lacunarity"]
        sock(node, "Distortion").default_value = spec["distortion"]
        return sock(node, "Fac", output=True)

    def _s_voronoi(self, spec):
        node = self._new("ShaderNodeTexVoronoi")
        node.voronoi_dimensions = "4D"
        node.feature = spec["feature"].upper()
        node.normalize = True
        self._link(self._mapped_coords(spec["size"]), sock(node, "Vector"))
        sock(node, "W").default_value = float(spec["seed"]) * 7.31
        sock(node, "Scale").default_value = 1.0
        sock(node, "Randomness").default_value = spec["randomness"]
        return sock(node, "Distance", output=True)

    def _s_curvature(self, spec):
        bevel = self._new("ShaderNodeBevel")
        bevel.samples = 8
        sock(bevel, "Radius").default_value = spec["radius"]
        dot = self._new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        self._link(sock(bevel, "Normal", output=True), dot.inputs[0])
        self._link(sock(self.geometry, "Normal", output=True), dot.inputs[1])
        # A 90 degree edge averages to about 45 degrees: 1 - cos(45) = 0.29 maps to 1.
        return self._math("SUBTRACT", 1.0, sock(dot, "Value", output=True), then=("MULTIPLY", 3.4 * spec["strength"]), clamp=True)

    def _ao(self, distance: float, inside: bool):
        node = self._new("ShaderNodeAmbientOcclusion")
        node.samples = 8
        node.inside = inside
        node.only_local = False
        sock(node, "Distance").default_value = distance
        return sock(node, "AO", output=True)

    def _s_cavity(self, spec):
        return self._math("SUBTRACT", 1.0, self._ao(spec["distance"], False), clamp=True)

    def _s_ao(self, spec):
        return self._ao(spec["distance"], False)

    def _s_thickness(self, spec):
        return self._math("SUBTRACT", 1.0, self._ao(spec["distance"], True), clamp=True)

    def _s_facing(self, spec):
        direction = (space.A2B.to_3x3() @ Vector(spec["direction"])).normalized()
        dot = self._new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        self._link(sock(self.geometry, "Normal", output=True), dot.inputs[0])
        dot.inputs[1].default_value = direction
        return self._math("MAXIMUM", sock(dot, "Value", output=True), 0.0, clamp=True)

    def _s_position(self, spec):
        separate = self._new("ShaderNodeSeparateXYZ")
        self._link(sock(self.coords, "Object", output=True), sock(separate, "Vector"))
        component = sock(separate, AXIS_SOCKET_BLENDER[spec["axis"]], output=True)
        if spec["axis"] == "z":
            component = self._math("MULTIPLY", component, -1.0)
        node = self._new("ShaderNodeMapRange")
        node.interpolation_type = "LINEAR"
        node.clamp = True
        self._link(component, sock(node, "Value"))
        sock(node, "From Min").default_value = spec["start"]
        sock(node, "From Max").default_value = spec["end"]
        return sock(node, "Result", output=True)

    # --- scalar operators ---

    def _math(self, operation: str, a, b, then=None, clamp: bool = False):
        node = self._new("ShaderNodeMath")
        node.operation = operation
        self._value(node.inputs[0], a)
        self._value(node.inputs[1], b)
        node.use_clamp = clamp and then is None
        result = node.outputs[0]
        if then is not None:
            return self._math(then[0], result, then[1], clamp=clamp)
        return result

    def _s_math(self, spec):
        return self._math(spec["operation"].upper(), self.scalar(spec["a"]), self.scalar(spec["b"]))

    def _s_clamp(self, spec):
        node = self._new("ShaderNodeMapRange")
        node.interpolation_type = "LINEAR"
        node.clamp = True
        self._value(sock(node, "Value"), self.scalar(spec["field"]))
        sock(node, "From Min").default_value = spec["low"]
        sock(node, "From Max").default_value = spec["high"]
        sock(node, "To Min").default_value = spec["low"]
        sock(node, "To Max").default_value = spec["high"]
        return sock(node, "Result", output=True)

    def _s_smoothstep(self, spec):
        node = self._new("ShaderNodeMapRange")
        node.interpolation_type = "SMOOTHSTEP"
        node.clamp = True
        self._value(sock(node, "Value"), self.scalar(spec["field"]))
        sock(node, "From Min").default_value = spec["low"]
        sock(node, "From Max").default_value = spec["high"]
        return sock(node, "Result", output=True)

    def _ramp_node(self, stops_linear):
        node = self._new("ShaderNodeValToRGB")
        ramp = node.color_ramp
        ramp.interpolation = "LINEAR"
        while len(ramp.elements) > 1:
            ramp.elements.remove(ramp.elements[-1])
        first = True
        for position, rgba in stops_linear:
            element = ramp.elements[0] if first else ramp.elements.new(position)
            element.position = position
            element.color = rgba
            first = False
        return node

    def _s_ramp(self, spec):
        node = self._ramp_node([(p, (v, v, v, 1.0)) for p, v in spec["stops"]])
        self._value(sock(node, "Fac"), self.scalar(spec["field"]))
        return sock(node, "Color", output=True)

    def _s_mix(self, spec):
        node = self._new("ShaderNodeMix")
        node.data_type = "FLOAT"
        self._value(sock(node, "Factor_Float"), self.scalar(spec["factor"]))
        self._value(sock(node, "A_Float"), self.scalar(spec["a"]))
        self._value(sock(node, "B_Float"), self.scalar(spec["b"]))
        return sock(node, "Result_Float", output=True)

    # --- color fields ---

    def _c_color(self, spec):
        node = self._new("ShaderNodeRGB")
        node.outputs[0].default_value = _linear(spec["value"])
        return node.outputs[0]

    def _c_color_ramp(self, spec):
        node = self._ramp_node([(p, _linear(c)) for p, c in spec["stops"]])
        self._value(sock(node, "Fac"), self.scalar(spec["field"]))
        return sock(node, "Color", output=True)

    def _c_color_mix(self, spec):
        node = self._new("ShaderNodeMix")
        node.data_type = "RGBA"
        node.blend_type = "MIX"
        self._value(sock(node, "Factor_Float"), self.scalar(spec["factor"]))
        self._link(self.color(spec["a"]), sock(node, "A_Color"))
        self._link(self.color(spec["b"]), sock(node, "B_Color"))
        return sock(node, "Result_Color", output=True)

    def _c_tint(self, spec):
        node = self._new("ShaderNodeMix")
        node.data_type = "RGBA"
        node.blend_type = "MULTIPLY"
        sock(node, "Factor_Float").default_value = 1.0
        self._link(self.color(spec["color"]), sock(node, "A_Color"))
        self._value(sock(node, "B_Color"), self.scalar(spec["factor"]))
        return sock(node, "Result_Color", output=True)

    # --- composition ---

    def mix_scalar(self, below, above, mask):
        node = self._new("ShaderNodeMix")
        node.data_type = "FLOAT"
        self._value(sock(node, "Factor_Float"), mask)
        self._value(sock(node, "A_Float"), below)
        self._value(sock(node, "B_Float"), above)
        return sock(node, "Result_Float", output=True)

    def mix_color(self, below, above, mask):
        node = self._new("ShaderNodeMix")
        node.data_type = "RGBA"
        node.blend_type = "MIX"
        self._value(sock(node, "Factor_Float"), mask)
        self._link(below, sock(node, "A_Color"))
        self._link(above, sock(node, "B_Color"))
        return sock(node, "Result_Color", output=True)
