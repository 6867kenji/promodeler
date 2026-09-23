from __future__ import annotations

import json

import math
from dataclasses import dataclass, field
from typing import Any

from .diagnostics import ModelingError, finite_vector, is_finite
from .material import Material
from .modifiers import Modifier
from .rig import Clip, Pose, Rig
from .shapes import GENERATED_KINDS, Shape
from .transform import Transform

EXPORT_FORMATS = ("glb", "usdz")

RENDER_ENGINES = ("eevee", "cycles")
RENDER_VIEWS = ("perspective", "front", "back", "side", "top")
RENDER_PASSES = ("shaded", "clay", "wireframe", "normals", "uv")
RENDER_ENVIRONMENTS = ("studio", "overcast", "sunny", "sunset")


@dataclass(frozen=True)
class QualityProfile:
    """Tessellation defaults and budgets. Lower values regenerate the same recipe as a coarser LOD."""

    curve_segments: int = 32
    surface_segments: int = 16
    max_triangles: int = 2_000_000
    texture_resolution: int = 1024
    bake_samples: int = 32

    def validate(self) -> None:
        for name, minimum in (("curve_segments", 3), ("surface_segments", 2), ("max_triangles", 1),
                              ("texture_resolution", 16), ("bake_samples", 1)):
            value = getattr(self, name)
            if not isinstance(value, int) or value < minimum:
                raise ModelingError("quality.range", f"quality.{name} must be an integer >= {minimum}.")
        if self.texture_resolution > 8192 or self.bake_samples > 4096:
            raise ModelingError("quality.range", "quality.texture_resolution <= 8192 and bake_samples <= 4096.")

    def to_recipe(self) -> dict:
        return {
            "curve_segments": self.curve_segments,
            "surface_segments": self.surface_segments,
            "max_triangles": self.max_triangles,
            "texture_resolution": self.texture_resolution,
            "bake_samples": self.bake_samples,
        }


@dataclass(frozen=True)
class Camera:
    """A named verification camera in authoring space.

    Perspective by default; ``orthographic`` with ``ortho_scale`` (the
    visible width in meters) gives drawing-like views. Placing an
    orthographic camera on a section plane with a tiny ``clip_start`` cuts
    the model there, because everything behind the camera is dropped.
    ``hide_parts`` removes parts for this camera only, for dollhouse views.
    """

    id: str
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    fov: float = math.radians(60)
    orthographic: bool = False
    ortho_scale: float = 5.0
    clip_start: float = 0.01
    hide_parts: tuple[str, ...] = ()

    def validate(self, label: str) -> None:
        if not isinstance(self.id, str) or not self.id or self.id in RENDER_VIEWS:
            raise ModelingError("camera.id", f"{label}.id must be a nonempty string other than the built-in view names.")
        position = finite_vector(self.position, 3, "camera.position", f"{label}.position")
        target = finite_vector(self.target, 3, "camera.target", f"{label}.target")
        if sum((a - b) ** 2 for a, b in zip(position, target)) < 1e-12:
            raise ModelingError("camera.target", f"{label} position and target coincide.")
        if not 0.01 < self.fov < math.pi:
            raise ModelingError("camera.fov", f"{label}.fov must be within (0, pi) radians.")
        if self.ortho_scale <= 0.0 or self.clip_start <= 0.0:
            raise ModelingError("camera.range", f"{label} ortho_scale and clip_start must be positive.")

    def to_recipe(self) -> dict:
        return {
            "id": self.id, "position": [float(c) for c in self.position], "target": [float(c) for c in self.target],
            "fov": float(self.fov), "orthographic": bool(self.orthographic), "ortho_scale": float(self.ortho_scale),
            "clip_start": float(self.clip_start), "hide_parts": list(self.hide_parts),
        }


@dataclass(frozen=True)
class Light:
    """A downward-facing area light for verification renders of interiors. ``energy`` is watts."""

    id: str
    position: tuple[float, float, float]
    energy: float = 100.0
    size: float = 0.5
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def validate(self, label: str) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ModelingError("light.id", f"{label}.id must be a nonempty string.")
        finite_vector(self.position, 3, "light.position", f"{label}.position")
        if not is_finite(self.energy) or self.energy <= 0.0 or self.size <= 0.0:
            raise ModelingError("light.energy", f"{label} energy and size must be positive.")
        if len(self.color) != 3 or any(not is_finite(c) or not 0.0 <= c <= 1.0 for c in self.color):
            raise ModelingError("light.color", f"{label}.color must be three values in 0...1.")

    def to_recipe(self) -> dict:
        return {"id": self.id, "position": [float(c) for c in self.position], "energy": float(self.energy),
                "size": float(self.size), "color": [float(c) for c in self.color]}


@dataclass(frozen=True)
class RenderSettings:
    """Verification render options. They never affect the exported asset.

    ``views`` are the built-in auto-framed views; ``cameras`` are authored
    cameras rendered in addition to them (pass an empty ``views`` tuple to
    render only cameras). ``lights`` add area lights for interiors.
    """

    resolution: int = 512
    engine: str = "eevee"
    views: tuple[str, ...] = ("perspective",)
    passes: tuple[str, ...] = ("shaded",)
    environment: str = "studio"
    samples: int = 16
    background: tuple[float, float, float] = (0.35, 0.35, 0.35)
    pose: str | None = None
    cameras: tuple[Camera, ...] = ()
    lights: tuple[Light, ...] = ()
    clip: str | None = None  # render this clip as a video (one .mp4 per view/camera, shaded pass) instead of stills
    clip_fps: int = 24
    aspect_ratio: float = 1.0  # output width / height; resolution is the height

    def validate(self) -> None:
        if self.pose is not None and (not isinstance(self.pose, str) or not self.pose):
            raise ModelingError("render.pose", "render.pose must be a pose id or None.")
        if self.clip is not None and (not isinstance(self.clip, str) or not self.clip):
            raise ModelingError("render.clip", "render.clip must be a clip id or None.")
        if not isinstance(self.clip_fps, int) or not 1 <= self.clip_fps <= 120:
            raise ModelingError("render.clipFps", "render.clip_fps must be an integer in 1...120.")
        ids: set[str] = set()
        for index, camera in enumerate(self.cameras):
            camera.validate(f"render.cameras[{index}]")
            if camera.id in ids:
                raise ModelingError("camera.id", f"Camera id {camera.id!r} is defined twice.")
            ids.add(camera.id)
        for index, light in enumerate(self.lights):
            light.validate(f"render.lights[{index}]")
        if not self.views and not self.cameras:
            raise ModelingError("render.views", "render needs at least one view or camera.")
        if not self.passes or any(p not in RENDER_PASSES for p in self.passes):
            raise ModelingError("render.passes", f"render.passes must be nonempty and within {RENDER_PASSES}.")
        if self.environment not in RENDER_ENVIRONMENTS and not self.environment.lower().endswith((".hdr", ".exr")):
            raise ModelingError("render.environment", f"render.environment must be one of {RENDER_ENVIRONMENTS} or an .hdr/.exr path.")
        if not isinstance(self.resolution, int) or not 64 <= self.resolution <= 4096:
            raise ModelingError("render.resolution", "render.resolution must be an integer in 64...4096.")
        if not is_finite(self.aspect_ratio) or not 0.5 <= self.aspect_ratio <= 3.0:
            raise ModelingError("render.aspectRatio", "render.aspect_ratio must be within 0.5...3.0.")
        if self.engine not in RENDER_ENGINES:
            raise ModelingError("render.engine", f"render.engine must be one of {RENDER_ENGINES}.")
        if any(v not in RENDER_VIEWS for v in self.views):
            raise ModelingError("render.views", f"render.views must be within {RENDER_VIEWS}.")
        if not isinstance(self.samples, int) or not 1 <= self.samples <= 4096:
            raise ModelingError("render.samples", "render.samples must be an integer in 1...4096.")
        if len(self.background) != 3 or any(not is_finite(v) or not 0 <= v <= 1 for v in self.background):
            raise ModelingError("render.background", "render.background must be three values in 0...1.")

    def to_recipe(self) -> dict:
        return {
            "resolution": self.resolution,
            "aspect_ratio": float(self.aspect_ratio),
            "engine": self.engine,
            "views": list(self.views),
            "passes": list(self.passes),
            "environment": self.environment,
            "pose": self.pose,
            "cameras": [c.to_recipe() for c in self.cameras],
            "lights": [l.to_recipe() for l in self.lights],
            "samples": self.samples,
            "background": [float(v) for v in self.background],
            "clip": self.clip,
            "clip_fps": self.clip_fps,
        }


@dataclass(frozen=True)
class ExportSettings:
    """Which files to write. glTF is always the primary format; USDZ is optional."""

    formats: tuple[str, ...] = ("glb",)

    def validate(self) -> None:
        if not self.formats or any(f not in EXPORT_FORMATS for f in self.formats) or "glb" not in self.formats:
            raise ModelingError("export.formats", f"export.formats must include 'glb' and only use {EXPORT_FORMATS}.")

    def to_recipe(self) -> dict:
        return {"formats": list(dict.fromkeys(self.formats))}


@dataclass(frozen=True)
class LOD:
    """A decimated copy used beyond ``distance`` meters; ``ratio`` keeps that fraction of the faces."""

    distance: float
    ratio: float

    def validate(self, label: str) -> None:
        if not is_finite(self.distance) or self.distance <= 0.0:
            raise ModelingError("lod.distance", f"{label}.distance must be positive.")
        if not is_finite(self.ratio) or not 0.01 <= self.ratio < 1.0:
            raise ModelingError("lod.ratio", f"{label}.ratio must be in 0.01...1.")

    def to_recipe(self) -> dict:
        return {"distance": float(self.distance), "ratio": float(self.ratio)}


@dataclass(frozen=True)
class Part:
    """A semantic, independently addressable piece of the asset.

    ``smooth_angle`` of ``None`` keeps flat shading. Otherwise faces meeting
    at an angle below it are shaded smooth and sharper edges stay hard.
    ``skinned`` binds the part to the asset rig with automatic distance
    weights; ``parent_joint`` attaches it rigidly to one joint instead.
    """

    id: str
    shape: Shape
    material: str
    transform: Transform = Transform()
    modifiers: tuple[Modifier, ...] = ()
    parent: str | None = None
    smooth_angle: float | None = None
    skinned: bool = False
    parent_joint: str | None = None
    lods: tuple[LOD, ...] = ()
    texture_resolution: int | None = None

    def validate(self) -> None:
        if self.skinned and self.parent_joint is not None:
            raise ModelingError("part.binding", f"part[{self.id!r}] cannot be both skinned and attached to a joint.")
        last = 0.0
        for index, lod in enumerate(self.lods):
            lod.validate(f"part[{self.id!r}].lods[{index}]")
            if lod.distance <= last:
                raise ModelingError("lod.distance", f"part[{self.id!r}].lods distances must ascend.")
            last = lod.distance
        if self.lods and self.shape.kind in GENERATED_KINDS:
            raise ModelingError("lod.generated", f"part[{self.id!r}]: generated parts cannot have LODs.")
        if self.texture_resolution is not None and (
            not isinstance(self.texture_resolution, int) or isinstance(self.texture_resolution, bool)
            or self.texture_resolution < 16 or self.texture_resolution > 8192
            or self.texture_resolution & (self.texture_resolution - 1)
        ):
            raise ModelingError("part.textureResolution", f"part[{self.id!r}].texture_resolution must be a power of two from 16 to 8192.")
        label = f"part[{self.id!r}]"
        if not isinstance(self.id, str) or not self.id or any(c.isspace() for c in self.id):
            raise ModelingError("part.id", f"{label}.id must be a nonempty string without whitespace.")
        if self.id == "root":
            raise ModelingError("part.id", "'root' is reserved for the asset root.")
        self.shape.validate(f"{label}.shape")
        self.transform.validate(f"{label}.transform")
        for index, modifier in enumerate(self.modifiers):
            modifier.validate(f"{label}.modifiers[{index}]")
        if self.smooth_angle is not None:
            if not is_finite(self.smooth_angle) or not 0.0 <= self.smooth_angle <= math.pi:
                raise ModelingError("part.smoothAngle", f"{label}.smooth_angle must be in 0...pi radians.")

    def to_recipe(self) -> dict:
        return {
            "id": self.id,
            "shape": self.shape.to_recipe(),
            "material": self.material,
            "transform": self.transform.to_recipe(),
            "modifiers": [m.to_recipe() for m in self.modifiers],
            "parent": self.parent,
            "smooth_angle": None if self.smooth_angle is None else float(self.smooth_angle),
            "skinned": bool(self.skinned),
            "parent_joint": self.parent_joint,
            "lods": [lod.to_recipe() for lod in self.lods],
            "texture_resolution": self.texture_resolution,
        }


@dataclass(frozen=True)
class Asset:
    name: str
    materials: tuple[Material, ...]
    parts: tuple[Part, ...]
    rig: Rig | None = None
    poses: tuple[Pose, ...] = ()
    clips: tuple[Clip, ...] = ()
    extras: dict | None = None  # JSON-serializable metadata written to extras.json and the glTF root extras

    def validate(self) -> None:
        self._validate_rig()
        if not isinstance(self.name, str) or not self.name.strip():
            raise ModelingError("asset.name", "asset.name must be a nonempty string.")
        if self.extras is not None:
            if not isinstance(self.extras, dict) or not all(isinstance(k, str) and k for k in self.extras):
                raise ModelingError("asset.extras", "asset.extras must be a dict with string keys.")
            try:
                json.dumps(self.extras, ensure_ascii=False)
            except (TypeError, ValueError) as error:
                raise ModelingError("asset.extras", f"asset.extras must be JSON-serializable: {error}") from None
        if not self.parts:
            raise ModelingError("asset.parts", "An asset needs at least one part.")
        material_ids: set[str] = set()
        for material in self.materials:
            material.validate()
            if material.id in material_ids:
                raise ModelingError("material.duplicateID", f"Material id {material.id!r} is defined twice.")
            material_ids.add(material.id)
        part_ids: set[str] = set()
        for part in self.parts:
            part.validate()
            if part.id in part_ids:
                raise ModelingError("part.duplicateID", f"Part id {part.id!r} is defined twice.")
            part_ids.add(part.id)
            if part.material not in material_ids:
                raise ModelingError("part.material", f"Part {part.id!r} references unknown material {part.material!r}.")
        parents = {part.id: part.parent for part in self.parts}
        for part in self.parts:
            if part.parent is not None and part.parent not in part_ids:
                raise ModelingError("part.parent", f"Part {part.id!r} references unknown parent {part.parent!r}.")
            seen = {part.id}
            current = part.parent
            while current is not None:
                if current in seen:
                    raise ModelingError("part.parentCycle", f"Part {part.id!r} has a parent cycle.")
                seen.add(current)
                current = parents[current]

        shapes = {part.id: part.shape for part in self.parts}
        for part in self.parts:
            if part.shape.kind in GENERATED_KINDS:
                surface = part.shape.surface
                if surface not in shapes:
                    raise ModelingError("scatter.surface", f"Part {part.id!r} references unknown surface part {surface!r}.")
                if surface == part.id or shapes[surface].kind in GENERATED_KINDS:
                    raise ModelingError("scatter.surface", f"Part {part.id!r} must scatter over a regular part, not {surface!r}.")
                if part.modifiers:
                    raise ModelingError("scatter.modifiers", f"Generated part {part.id!r} cannot have modifiers.")

    def _validate_rig(self) -> None:
        joint_ids: set[str] = set()
        if self.rig is not None:
            self.rig.validate()
            joint_ids = self.rig.joint_ids()
        pose_ids: set[str] = set()
        for index, pose in enumerate(self.poses):
            if self.rig is None:
                raise ModelingError("pose.rig", "Poses require a rig.")
            pose.validate(f"poses[{index}]", joint_ids)
            if pose.id in pose_ids:
                raise ModelingError("pose.duplicateID", f"Pose id {pose.id!r} is defined twice.")
            pose_ids.add(pose.id)
        clip_ids: set[str] = set()
        for index, clip in enumerate(self.clips):
            if self.rig is None:
                raise ModelingError("clip.rig", "Clips require a rig.")
            clip.validate(f"clips[{index}]", pose_ids)
            if clip.id in clip_ids:
                raise ModelingError("clip.duplicateID", f"Clip id {clip.id!r} is defined twice.")
            clip_ids.add(clip.id)
        for part in self.parts:
            if (part.skinned or part.parent_joint is not None) and self.rig is None:
                raise ModelingError("part.binding", f"Part {part.id!r} binds to a joint but the asset has no rig.")
            if part.parent_joint is not None and part.parent_joint not in joint_ids:
                raise ModelingError("part.binding", f"Part {part.id!r} references unknown joint {part.parent_joint!r}.")

    def pose_ids(self) -> set[str]:
        return {p.id for p in self.poses}

    def part(self, part_id: str) -> Part:
        for part in self.parts:
            if part.id == part_id:
                return part
        raise KeyError(part_id)

    def to_recipe(self) -> dict:
        return {
            "name": self.name,
            "materials": [m.to_recipe() for m in self.materials],
            "parts": [p.to_recipe() for p in self.parts],
            "rig": None if self.rig is None else self.rig.to_recipe(),
            "poses": [p.to_recipe() for p in self.poses],
            "clips": [c.to_recipe() for c in self.clips],
            "extras": self.extras,
        }


@dataclass(frozen=True)
class GenerationInput:
    parameters: Any
    seed: int = 0
    quality: QualityProfile = field(default_factory=QualityProfile)
