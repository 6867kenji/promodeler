"""Field DSL: scalar and color functions over a surface, evaluated in object space at bake time.

A field is a closed, serializable expression tree. Procedural fields sample
3D object coordinates, so they are seamless without UVs. Mesh-derived
fields (curvature, cavity, ambient occlusion, thickness, facing) are
ray-traced by the renderer while baking. Arithmetic on fields builds new
nodes; numbers are promoted to constants.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields
from typing import ClassVar

from .color import Color
from .diagnostics import ModelingError, is_finite

MAX_DEPTH = 48
MAX_NODES = 4000
VORONOI_FEATURES = ("f1", "smooth_f1", "distance_to_edge")
MATH_OPERATIONS = ("add", "subtract", "multiply", "divide", "minimum", "maximum", "power")
AXES = ("x", "y", "z")


def _recipe_value(value):
    if isinstance(value, (Field, ColorField)):
        return value.to_recipe()
    if isinstance(value, Color):
        return value.to_recipe()
    if isinstance(value, tuple):
        return [_recipe_value(v) for v in value]
    return value


class _Node:
    kind: ClassVar[str] = ""

    def to_recipe(self) -> dict:
        out: dict = {"kind": self.kind}
        for f in dc_fields(self):
            out[f.name] = _recipe_value(getattr(self, f.name))
        return out

    def children(self):
        for f in dc_fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (Field, ColorField)):
                yield value

    def validate(self, label: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise ModelingError("field.depth", f"{label} nests deeper than {MAX_DEPTH} levels.")
        for f in dc_fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not is_finite(value):
                raise ModelingError("field.nonFinite", f"{label}.{f.name} must be finite.")
        self.check(label)
        for child in self.children():
            child.validate(label, depth + 1)

    def check(self, label: str) -> None:
        pass

    def node_count(self) -> int:
        return 1 + sum(c.node_count() for c in self.children())


class Field(_Node):
    """Scalar field. Overloaded operators build ``Math`` nodes."""

    def __add__(self, other):
        return Math("add", self, as_field(other))

    def __radd__(self, other):
        return Math("add", as_field(other), self)

    def __sub__(self, other):
        return Math("subtract", self, as_field(other))

    def __rsub__(self, other):
        return Math("subtract", as_field(other), self)

    def __mul__(self, other):
        return Math("multiply", self, as_field(other))

    def __rmul__(self, other):
        return Math("multiply", as_field(other), self)

    def __truediv__(self, other):
        return Math("divide", self, as_field(other))

    def __neg__(self):
        return Math("multiply", self, Const(-1.0))

    def pow(self, exponent):
        return Math("power", self, as_field(exponent))

    def min(self, other):
        return Math("minimum", self, as_field(other))

    def max(self, other):
        return Math("maximum", self, as_field(other))

    def clamp(self, low: float = 0.0, high: float = 1.0) -> "Clamp":
        return Clamp(self, low, high)

    def smoothstep(self, low: float, high: float) -> "Smoothstep":
        return Smoothstep(self, low, high)

    def ramp(self, stops) -> "Ramp":
        return Ramp(self, tuple((float(p), float(v)) for p, v in stops))

    def invert(self) -> "Math":
        return 1.0 - self


class ColorField(_Node):
    """Color field. Multiply by a scalar with ``*``; blend with ``mix``."""

    def __mul__(self, other):
        return Tint(self, as_field(other))

    def __rmul__(self, other):
        return Tint(self, as_field(other))

    def mix(self, other, factor) -> "ColorMix":
        return ColorMix(self, as_color_field(other), as_field(factor))


def as_field(value) -> Field:
    if isinstance(value, Field):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelingError("field.type", f"Expected a scalar field or number, got {type(value).__name__}.")
    return Const(float(value))


def as_color_field(value) -> ColorField:
    if isinstance(value, ColorField):
        return value
    if isinstance(value, Color):
        return ColorConst(value)
    raise ModelingError("field.type", f"Expected a color field or Color, got {type(value).__name__}.")


def is_constant(value) -> bool:
    return isinstance(value, (int, float, Color)) and not isinstance(value, bool)


# --- scalar sources -------------------------------------------------------


@dataclass(frozen=True)
class Const(Field):
    kind: ClassVar[str] = "const"
    value: float = 0.0


@dataclass(frozen=True)
class Noise(Field):
    """Fractal (fBm) noise in 0...1. ``size`` is the feature size in meters, per axis when a tuple."""

    kind: ClassVar[str] = "noise"
    size: float | tuple[float, float, float] = 0.01
    detail: float = 4.0
    roughness: float = 0.5
    lacunarity: float = 2.0
    distortion: float = 0.0
    seed: int = 0

    def check(self, label: str) -> None:
        _check_size(self.size, label)
        if not 0.0 <= self.detail <= 15.0:
            raise ModelingError("noise.detail", f"{label}.detail must be in 0...15.")
        if not 0.0 <= self.roughness <= 1.0:
            raise ModelingError("noise.roughness", f"{label}.roughness must be in 0...1.")
        if not 1.0 <= self.lacunarity <= 8.0:
            raise ModelingError("noise.lacunarity", f"{label}.lacunarity must be in 1...8.")
        if not isinstance(self.seed, int):
            raise ModelingError("noise.seed", f"{label}.seed must be an integer.")


@dataclass(frozen=True)
class Voronoi(Field):
    """Cellular noise in 0...1. ``feature`` selects distance to the nearest point, a smoothed version, or distance to cell edges."""

    kind: ClassVar[str] = "voronoi"
    size: float | tuple[float, float, float] = 0.01
    feature: str = "f1"
    randomness: float = 1.0
    seed: int = 0

    def check(self, label: str) -> None:
        _check_size(self.size, label)
        if self.feature not in VORONOI_FEATURES:
            raise ModelingError("voronoi.feature", f"{label}.feature must be one of {VORONOI_FEATURES}.")
        if not 0.0 <= self.randomness <= 1.0:
            raise ModelingError("voronoi.randomness", f"{label}.randomness must be in 0...1.")
        if not isinstance(self.seed, int):
            raise ModelingError("voronoi.seed", f"{label}.seed must be an integer.")


@dataclass(frozen=True)
class Bricks(Field):
    """Mortar mask of a running-bond brick, tile or plank pattern: 1 in the joints, 0 on the units.

    ``width`` and ``height`` are unit sizes in meters along the pattern's
    U and V axes, ``mortar`` the joint width. ``axis`` is the surface normal
    the pattern lies on: ``"y"`` for floors (U along X, V along Z), ``"z"``
    for walls facing the viewer, ``"x"`` for side walls. ``offset`` shifts
    every ``offset_frequency``-th row by that fraction; 0 gives a grid.
    """

    kind: ClassVar[str] = "bricks"
    width: float = 0.2
    height: float = 0.06
    mortar: float = 0.005
    offset: float = 0.5
    offset_frequency: int = 2
    axis: str = "y"

    def check(self, label: str) -> None:
        for name in ("width", "height", "mortar"):
            value = getattr(self, name)
            if not is_finite(value) or value <= 0.0 or value > 100.0:
                raise ModelingError("bricks.size", f"{label}.{name} must be in (0, 100] meters.")
        if self.mortar >= min(self.width, self.height):
            raise ModelingError("bricks.size", f"{label}.mortar must be smaller than the unit size.")
        if not 0.0 <= self.offset <= 1.0:
            raise ModelingError("bricks.offset", f"{label}.offset must be in 0...1.")
        if not isinstance(self.offset_frequency, int) or not 1 <= self.offset_frequency <= 99:
            raise ModelingError("bricks.offset", f"{label}.offset_frequency must be in 1...99.")
        if self.axis not in AXES:
            raise ModelingError("bricks.axis", f"{label}.axis must be one of {AXES}.")


@dataclass(frozen=True)
class Curvature(Field):
    """Convex edge mask: 1 on sharp edges within ``radius`` meters, 0 on flat areas.

    The probe compares the surface normal with an average over ``radius``.
    Edges that are already rounded by a geometric bevel look flat to a probe
    of similar size, so choose a radius about three times the bevel width.
    """

    kind: ClassVar[str] = "curvature"
    radius: float = 0.002
    strength: float = 1.0

    def check(self, label: str) -> None:
        if self.radius <= 0.0:
            raise ModelingError("curvature.radius", f"{label}.radius must be positive.")


@dataclass(frozen=True)
class Cavity(Field):
    """Concave crevice mask from short-range occlusion: 1 deep in creases. Other parts occlude too."""

    kind: ClassVar[str] = "cavity"
    distance: float = 0.01

    def check(self, label: str) -> None:
        if self.distance <= 0.0:
            raise ModelingError("cavity.distance", f"{label}.distance must be positive.")


@dataclass(frozen=True)
class AmbientOcclusion(Field):
    """Openness: 1 fully exposed, 0 fully occluded within ``distance``."""

    kind: ClassVar[str] = "ao"
    distance: float = 0.1

    def check(self, label: str) -> None:
        if self.distance <= 0.0:
            raise ModelingError("ao.distance", f"{label}.distance must be positive.")


@dataclass(frozen=True)
class Thickness(Field):
    """1 where the object is thicker than ``distance``, 0 on thin shells."""

    kind: ClassVar[str] = "thickness"
    distance: float = 0.02

    def check(self, label: str) -> None:
        if self.distance <= 0.0:
            raise ModelingError("thickness.distance", f"{label}.distance must be positive.")


@dataclass(frozen=True)
class Facing(Field):
    """Clamped dot product between the surface normal and ``direction`` in authoring space (Y up)."""

    kind: ClassVar[str] = "facing"
    direction: tuple[float, float, float] = (0.0, 1.0, 0.0)

    def check(self, label: str) -> None:
        if len(self.direction) != 3 or sum(c * c for c in self.direction) == 0.0:
            raise ModelingError("facing.direction", f"{label}.direction must be a nonzero 3-vector.")


@dataclass(frozen=True)
class Position(Field):
    """Object-space coordinate along ``axis`` mapped from ``start``...``end`` to 0...1 and clamped."""

    kind: ClassVar[str] = "position"
    axis: str = "y"
    start: float = 0.0
    end: float = 1.0

    def check(self, label: str) -> None:
        if self.axis not in AXES:
            raise ModelingError("position.axis", f"{label}.axis must be one of {AXES}.")
        if self.start == self.end:
            raise ModelingError("position.range", f"{label} start and end must differ.")


# --- scalar operators -----------------------------------------------------


@dataclass(frozen=True)
class Math(Field):
    kind: ClassVar[str] = "math"
    operation: str = "add"
    a: Field = Const(0.0)
    b: Field = Const(0.0)

    def check(self, label: str) -> None:
        if self.operation not in MATH_OPERATIONS:
            raise ModelingError("math.operation", f"{label}.operation must be one of {MATH_OPERATIONS}.")


@dataclass(frozen=True)
class Clamp(Field):
    kind: ClassVar[str] = "clamp"
    field: Field = Const(0.0)
    low: float = 0.0
    high: float = 1.0

    def check(self, label: str) -> None:
        if self.low >= self.high:
            raise ModelingError("clamp.range", f"{label} low must be below high.")


@dataclass(frozen=True)
class Smoothstep(Field):
    """Smooth 0...1 transition as the input goes from ``low`` to ``high``."""

    kind: ClassVar[str] = "smoothstep"
    field: Field = Const(0.0)
    low: float = 0.0
    high: float = 1.0

    def check(self, label: str) -> None:
        if self.low >= self.high:
            raise ModelingError("smoothstep.range", f"{label} low must be below high.")


@dataclass(frozen=True)
class Ramp(Field):
    """Piecewise-linear remap through (position, value) stops with positions in 0...1."""

    kind: ClassVar[str] = "ramp"
    field: Field = Const(0.0)
    stops: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 1.0))

    def check(self, label: str) -> None:
        _check_stops(self.stops, label)


@dataclass(frozen=True)
class Mix(Field):
    """Linear blend ``a`` to ``b`` by ``factor``."""

    kind: ClassVar[str] = "mix"
    a: Field = Const(0.0)
    b: Field = Const(1.0)
    factor: Field = Const(0.5)


# --- color fields ---------------------------------------------------------


@dataclass(frozen=True)
class ColorConst(ColorField):
    kind: ClassVar[str] = "color"
    value: Color = Color(1.0, 1.0, 1.0)

    def check(self, label: str) -> None:
        self.value.validate(label)


@dataclass(frozen=True)
class ColorRamp(ColorField):
    """Map a scalar through color stops, interpolating in linear light."""

    kind: ClassVar[str] = "color_ramp"
    field: Field = Const(0.0)
    stops: tuple[tuple[float, Color], ...] = ((0.0, Color(0.0, 0.0, 0.0)), (1.0, Color(1.0, 1.0, 1.0)))

    def check(self, label: str) -> None:
        _check_stops(self.stops, label, color=True)


@dataclass(frozen=True)
class ColorMix(ColorField):
    kind: ClassVar[str] = "color_mix"
    a: ColorField = ColorConst(Color(0.0, 0.0, 0.0))
    b: ColorField = ColorConst(Color(1.0, 1.0, 1.0))
    factor: Field = Const(0.5)


@dataclass(frozen=True)
class Tint(ColorField):
    """Multiply a color by a scalar in linear light."""

    kind: ClassVar[str] = "tint"
    color: ColorField = ColorConst(Color(1.0, 1.0, 1.0))
    factor: Field = Const(1.0)


def _check_size(size, label: str) -> None:
    sizes = size if isinstance(size, tuple) else (size,)
    if isinstance(size, tuple) and len(size) != 3:
        raise ModelingError("field.size", f"{label}.size must be a number or a 3-tuple.")
    for s in sizes:
        if not is_finite(s) or s <= 0.0 or s > 1000.0:
            raise ModelingError("field.size", f"{label}.size must be in (0, 1000] meters.")


def _check_stops(stops, label: str, color: bool = False) -> None:
    if len(stops) < 1 or len(stops) > 32:
        raise ModelingError("ramp.stops", f"{label}.stops needs 1...32 entries.")
    last = -1.0
    for position, value in stops:
        if not is_finite(position) or not 0.0 <= position <= 1.0 or position < last:
            raise ModelingError("ramp.stops", f"{label}.stops positions must ascend within 0...1.")
        last = position
        if color:
            if not isinstance(value, Color):
                raise ModelingError("ramp.stops", f"{label}.stops values must be Colors.")
            value.validate(label)
        elif not is_finite(value):
            raise ModelingError("ramp.stops", f"{label}.stops values must be finite.")


def validate_field(value, label: str) -> None:
    """Validate a channel value: a number, Color, Field or ColorField."""
    if isinstance(value, (Field, ColorField)):
        value.validate(label)
        if value.node_count() > MAX_NODES:
            raise ModelingError("field.size", f"{label} has more than {MAX_NODES} nodes.")
    elif isinstance(value, Color):
        value.validate(label)
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not is_finite(value):
        raise ModelingError("field.type", f"{label} must be a finite number, Color or field.")


GEOMETRY_FIELD_KINDS = ("const", "noise", "voronoi", "bricks", "position", "facing", "math", "clamp", "smoothstep", "ramp", "mix")


def validate_geometry_field(field, label: str) -> None:
    """Fields evaluated per vertex in Geometry Nodes cannot use ray-traced probes."""
    if not isinstance(field, Field):
        raise ModelingError("field.geometryOnly", f"{label} must be a scalar Field.")
    validate_field(field, label)
    pending = [field]
    while pending:
        node = pending.pop()
        if node.kind not in GEOMETRY_FIELD_KINDS:
            raise ModelingError(
                "displace.field",
                f"{label} uses {node.kind!r}, which needs ray tracing; geometry fields may only use {GEOMETRY_FIELD_KINDS}.",
            )
        pending.extend(node.children())


def scalar_recipe(value) -> dict:
    return as_field(value).to_recipe()


def color_recipe(value) -> dict:
    return as_color_field(value).to_recipe()
