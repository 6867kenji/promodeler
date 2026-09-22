"""CharacterRecipe and OutfitRecipe: the JSON boundary between promodeler and the Unity character creator.

Conventions (docs/03-character-recipe-pipeline.md, chapter 4):

- snake_case keys, meters, degrees, sRGB hex colors, same vocabulary as
  the japan-realistic-v1 blueprints (``barefoot_height``, ``inseam`` ...).
- No UMA names. Hair, skin, wardrobe and accessories are catalog IDs.
- 0...1 semantic sliders only where no metric exists (``body.shape``,
  ``face.shape``); 0.5 is the neutral base body.
- Provenance (``source``) and versions are part of the document so an
  edited recipe can still be diffed against its regenerated form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.diagnostics import ModelingError, is_finite
from ..core.recipe import dump_recipe
from ..core.recipe import recipe_hash as _recipe_hash
from . import serialize

SCHEMA = "promodeler-character/1.0"
OUTFIT_SCHEMA = "promodeler-outfit/1.0"
GENERATOR_VERSION = 1

ID_PATTERN = r"[a-z0-9][a-z0-9_-]*"
HEX_COLOR = r"#[0-9A-Fa-f]{6}"

SEXES = ("male", "female")
RACES = ("human_male", "human_female")
SKELETONS = ("humanoid_a_pose",)
REST_POSES = ("a_pose_35deg",)
SOURCE_KINDS = ("blueprint", "prompt", "random", "manual", "gui")
LANDMARKS = ("chest", "bust", "underbust", "waist", "hip", "shoulders", "neck", "head")
CIRCUMFERENCE_KEYS = ("chest", "bust", "underbust", "waist", "hip")
BODY_SHAPE_KEYS = ("muscle", "body_fat", "posture")
FACE_METRIC_KEYS = ("eyeball_diameter", "iris_diameter", "mouth_width", "nose_width")
FACE_SHAPE_KEYS = (
    "face_length", "jaw_width", "chin_size", "cheek_width", "nose_width", "nose_length", "nose_bridge",
    "eye_size", "eye_spacing", "eye_tilt", "mouth_width", "lip_thickness", "brow_height", "forehead_height",
)
SLOTS = ("inner", "upper", "lower", "dress", "outer", "neck", "waist", "hands", "footwear", "headwear", "socks")
SOCKETS = ("hand_l", "hand_r", "wrist_l", "wrist_r", "shoulder_l", "shoulder_r", "back", "waist", "head", "face", "chest")
DEFORMATIONS = ("cloth", "pinned_cloth", "skinned", "skinned_with_correctives", "skinned_with_secondary_cloth", "rigid", "rigid_skinned")
ACCESSORY_SOURCE_KINDS = ("catalog", "promodeler_asset")
BODY_POLICIES = ("keep",)
FACE_SHAPES = ("blink_l", "blink_r", "jaw_open", "smile", "mouth_wide", "pucker", "vowel_a", "vowel_i", "vowel_u", "vowel_e", "vowel_o")
DEFAULT_TOLERANCES_M = {"barefoot_height": 0.002, "circumference": 0.005, "length": 0.005}
DEFAULT_LIMITS_DEG = {
    "elbow_flexion": (0.0, 135.0), "knee_flexion": (0.0, 130.0), "hip_flexion": (0.0, 115.0),
    "shoulder_raise": (0.0, 160.0), "neck_yaw": (-65.0, 65.0), "finger_curl": (0.0, 90.0),
}


@dataclass(frozen=True)
class RecipeWarning:
    """A non-fatal finding, reported like ``report.json`` warnings (``code``, ``message``)."""

    code: str
    message: str


# --- provenance and identity ------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """Where the recipe came from, so it can be regenerated and diffed."""

    kind: str = field(default="blueprint", metadata={"enum": SOURCE_KINDS})
    path: str | None = field(default=None, metadata={"description": "Repository-relative path of the blueprint or prompt file."})
    sha256: str | None = None
    generator_version: int = GENERATOR_VERSION
    catalog_version: str | None = None


@dataclass(frozen=True)
class Identity:
    fictional: bool = True
    sex: str = field(default="female", metadata={"enum": SEXES})
    age: int | None = field(default=None, metadata={"minimum": 18, "maximum": 100})
    descriptors: tuple[str, ...] = field(default=(), metadata={"description": "Free-text traits from the blueprint, kept for humans and LLMs."})


@dataclass(frozen=True)
class Base:
    skeleton: str = field(default="humanoid_a_pose", metadata={"enum": SKELETONS})
    race: str = field(default="human_female", metadata={"enum": RACES})


# --- body ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class CrossSection:
    """A horizontal torso/head section at an absolute barefoot height (meters)."""

    landmark: str = field(metadata={"enum": LANDMARKS})
    height: float = field(metadata={"minimum": 0.0, "maximum": 2.5})
    width: float | None = field(default=None, metadata={"minimum": 0.0})
    depth: float | None = field(default=None, metadata={"minimum": 0.0})
    circumference: float | None = field(default=None, metadata={"minimum": 0.0})


@dataclass(frozen=True)
class Measurements:
    """Metric body targets, same vocabulary as the blueprint ``dimensions`` block. Meters."""

    barefoot_height: float = field(metadata={"minimum": 1.0, "maximum": 2.5})
    inseam: float | None = field(default=None, metadata={"minimum": 0.0})
    shoulder_width: float | None = field(default=None, metadata={"minimum": 0.0, "description": "Outer (acromion) torso slice width at the shoulder landmark, not the joint distance."})
    foot_length: float | None = field(default=None, metadata={"minimum": 0.0})
    head_height: float | None = field(default=None, metadata={"minimum": 0.0})
    circumferences: dict[str, float] = field(default_factory=dict, metadata={"description": "Keys: chest, bust, underbust, waist, hip."})
    cross_sections: tuple[CrossSection, ...] = ()


@dataclass(frozen=True)
class ReferenceFit:
    """Result of the optional MHR reference fit: proves the measurement set describes a possible body."""

    solver: str
    fit_version: int
    measured_m: dict[str, float]
    residuals_m: dict[str, float]
    seconds: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class Body:
    measurements_m: Measurements
    shape: dict[str, float] = field(default_factory=lambda: {"muscle": 0.5, "body_fat": 0.5, "posture": 0.5},
                                    metadata={"description": "0...1 semantic sliders without a metric: muscle, body_fat, posture."})
    tolerances_m: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TOLERANCES_M))
    reference_fit: ReferenceFit | None = None


# --- face -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Face:
    metrics_m: dict[str, float | None] = field(default_factory=lambda: {k: None for k in FACE_METRIC_KEYS},
                                               metadata={"description": "Metric face targets where the blueprint gives numbers."})
    shape: dict[str, float] = field(default_factory=lambda: {k: 0.5 for k in FACE_SHAPE_KEYS},
                                    metadata={"description": "0...1 anatomical sliders; 0.5 is the neutral race face."})
    descriptors: tuple[str, ...] = ()


# --- appearance -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Skin:
    preset: str | None = field(default=None, metadata={"description": "Catalog id (category skin)."})
    base_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    roughness: tuple[float, float] | None = None


@dataclass(frozen=True)
class Hair:
    style: str | None = field(default=None, metadata={"description": "Catalog id (category hair)."})
    base_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    length_m: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 2.0})


@dataclass(frozen=True)
class Eyebrows:
    style: str | None = None
    color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})


@dataclass(frozen=True)
class Eyes:
    iris_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    sclera_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})


@dataclass(frozen=True)
class FacialHair:
    style: str | None = None
    color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})


@dataclass(frozen=True)
class Teeth:
    preset: str | None = None
    base_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})


@dataclass(frozen=True)
class Appearance:
    skin: Skin = field(default_factory=Skin)
    hair: Hair = field(default_factory=Hair)
    eyebrows: Eyebrows = field(default_factory=Eyebrows)
    eyes: Eyes = field(default_factory=Eyes)
    facial_hair: FacialHair | None = None
    teeth: Teeth = field(default_factory=Teeth)


# --- wardrobe and accessories ------------------------------------------------------------------

@dataclass(frozen=True)
class GarmentMaterial:
    base_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    roughness: tuple[float, float] | None = None
    metallic: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 1.0})


@dataclass(frozen=True)
class Garment:
    """One wardrobe slot. ``catalog_id`` null means unresolved (warning) unless the outfit says barefoot."""

    slot: str = field(metadata={"enum": SLOTS})
    catalog_id: str | None = None
    blueprint_garment: str | None = field(default=None, metadata={"description": "The blueprint garments[].id this came from."})
    name: str | None = None
    material: GarmentMaterial | None = None
    finished_measurements_m: dict[str, float] = field(default_factory=dict, metadata={"description": "Verification targets measured on the dressed body; never used for generation."})
    deformation: str | None = field(default=None, metadata={"enum": DEFORMATIONS})
    construction: str | None = None
    sole_height_m: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 0.2})
    heel_height_m: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 0.2})
    internal_length_m: float | None = field(default=None, metadata={"minimum": 0.0})
    controls: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AccessorySource:
    kind: str = field(default="promodeler_asset", metadata={"enum": ACCESSORY_SOURCE_KINDS})
    catalog_id: str | None = None
    path: str | None = field(default=None, metadata={"description": "assets/props/<name>.py for a promodeler-built GLB."})
    build_hash: str | None = None


@dataclass(frozen=True)
class Accessory:
    id: str = field(metadata={"pattern": ID_PATTERN})
    source: AccessorySource = field(default_factory=AccessorySource)
    socket: str | None = field(default=None, metadata={"enum": SOCKETS})
    size_xyz_m: tuple[float, float, float] | None = None
    detail: str | None = None
    physics: dict = field(default_factory=dict)


# --- animation -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ClipSpec:
    id: str = field(metadata={"pattern": ID_PATTERN})
    duration_s: float = field(metadata={"minimum": 0.0, "maximum": 3600.0})
    loop: bool = False
    description: str | None = None


@dataclass(frozen=True)
class Animation:
    rest_pose: str = field(default="a_pose_35deg", metadata={"enum": REST_POSES})
    limits_deg: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(DEFAULT_LIMITS_DEG))
    face_shapes: tuple[str, ...] = ()
    clips: tuple[ClipSpec, ...] = ()


# --- recipes -------------------------------------------------------------------------------

@dataclass(frozen=True)
class CharacterRecipe:
    """A complete humanoid character description for the Unity character creator."""

    schema: str = field(metadata={"enum": (SCHEMA,)})
    id: str = field(metadata={"pattern": ID_PATTERN})
    name: str = ""
    seed: int = 0
    source: Source = field(default_factory=Source)
    identity: Identity = field(default_factory=Identity)
    base: Base = field(default_factory=Base)
    body: Body = field(default_factory=lambda: Body(Measurements(barefoot_height=1.65)))
    face: Face = field(default_factory=Face)
    appearance: Appearance = field(default_factory=Appearance)
    wardrobe: tuple[Garment, ...] = ()
    accessories: tuple[Accessory, ...] = ()
    animation: Animation = field(default_factory=Animation)
    physics: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    acceptance: tuple[str, ...] = ()

    # -- serialization --
    def to_json(self) -> dict:
        return serialize.encode(self)

    @classmethod
    def from_json(cls, data: dict) -> "CharacterRecipe":
        return serialize.decode(cls, data, "recipe")

    # -- validation --
    def validate(self, catalog=None) -> list[RecipeWarning]:
        """Raise ``ModelingError`` on hard errors; return soft findings."""
        serialize.check_metadata(self, "recipe")
        warnings: list[RecipeWarning] = []
        if self.identity.sex == "male" and self.base.race != "human_male" or self.identity.sex == "female" and self.base.race != "human_female":
            warnings.append(RecipeWarning("identity.race", f"identity.sex {self.identity.sex!r} and base.race {self.base.race!r} disagree."))
        _validate_body(self.body)
        _validate_face(self.face)
        _validate_wardrobe(self.wardrobe, catalog, self.base.race, warnings)
        _validate_accessories(self.accessories, catalog, warnings)
        _validate_animation(self.animation)
        _validate_appearance(self.appearance, catalog, self.base.race, warnings)
        if self.appearance.hair.style is None:
            warnings.append(RecipeWarning("appearance.unresolved", "appearance.hair.style is null; no catalog hair matched the blueprint text."))
        return warnings

    # -- hashing --
    def canonical(self) -> str:
        return canonical_dump(self.to_json())

    def hash(self, **environment) -> str:
        return recipe_hash(self.to_json(), **environment)


@dataclass(frozen=True)
class OutfitRecipe:
    """A wardrobe set that dresses an existing character without changing its body (blueprint kind ``wearable``)."""

    schema: str = field(metadata={"enum": (OUTFIT_SCHEMA,)})
    id: str = field(metadata={"pattern": ID_PATTERN})
    base_character: str = field(metadata={"pattern": ID_PATTERN})
    name: str = ""
    source: Source = field(default_factory=Source)
    body_policy: str = field(default="keep", metadata={"enum": BODY_POLICIES})
    barefoot: bool = False
    wardrobe: tuple[Garment, ...] = ()
    hair_override: Hair | None = None
    extra_bones: tuple[str, ...] = ()
    controls: dict = field(default_factory=dict)
    clips_extra: tuple[ClipSpec, ...] = ()
    physics: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    acceptance: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return serialize.encode(self)

    @classmethod
    def from_json(cls, data: dict) -> "OutfitRecipe":
        return serialize.decode(cls, data, "outfit")

    def validate(self, catalog=None, base: CharacterRecipe | None = None) -> list[RecipeWarning]:
        serialize.check_metadata(self, "outfit")
        warnings: list[RecipeWarning] = []
        race = base.base.race if base is not None else None
        if base is not None and base.id != self.base_character:
            raise ModelingError("outfit.base", f"outfit.base_character {self.base_character!r} does not match recipe {base.id!r}.")
        _validate_wardrobe(self.wardrobe, catalog, race, warnings)
        if self.barefoot and any(g.slot == "footwear" and g.catalog_id for g in self.wardrobe):
            raise ModelingError("outfit.barefoot", "outfit.barefoot is true but the wardrobe has footwear.")
        ids = [c.id for c in self.clips_extra]
        if len(ids) != len(set(ids)):
            raise ModelingError("clip.duplicateID", "outfit.clips_extra ids must be unique.")
        if self.hair_override is not None and catalog is not None and self.hair_override.style is not None:
            _check_catalog_reference(catalog, self.hair_override.style, "hair", None, race, "outfit.hair_override.style", warnings)
        return warnings

    def canonical(self) -> str:
        return canonical_dump(self.to_json())

    def hash(self, **environment) -> str:
        return recipe_hash(self.to_json(), **environment)


# --- helpers -----------------------------------------------------------------------------

def canonical_dump(data: dict) -> str:
    """Same canonical JSON as asset recipes: sorted keys, no whitespace, ASCII, no NaN."""
    return dump_recipe(data)


def recipe_hash(data: dict, **environment) -> str:
    return _recipe_hash(data, **environment)


def _validate_body(body: Body) -> None:
    m = body.measurements_m
    for key, value in m.circumferences.items():
        if key not in CIRCUMFERENCE_KEYS:
            raise ModelingError("measurements.key", f"body.measurements_m.circumferences has unknown key {key!r} (allowed {list(CIRCUMFERENCE_KEYS)}).")
        if not is_finite(value) or not 0.2 <= value <= 2.5:
            raise ModelingError("measurements.range", f"circumference {key} must be 0.2...2.5 m, got {value!r}.")
    for name in ("inseam", "shoulder_width", "foot_length", "head_height"):
        value = getattr(m, name)
        if value is not None and value >= m.barefoot_height:
            raise ModelingError("measurements.range", f"body.measurements_m.{name} must be smaller than the height.")
    landmarks = [s.landmark for s in m.cross_sections]
    if len(landmarks) != len(set(landmarks)):
        raise ModelingError("measurements.section", "body.measurements_m.cross_sections landmarks must be unique.")
    for section in m.cross_sections:
        if section.height >= m.barefoot_height:
            raise ModelingError("measurements.section", f"cross section {section.landmark} is above the head.")
    for key, value in body.shape.items():
        if key not in BODY_SHAPE_KEYS:
            raise ModelingError("body.shape", f"body.shape has unknown key {key!r} (allowed {list(BODY_SHAPE_KEYS)}).")
        if not is_finite(value) or not 0.0 <= value <= 1.0:
            raise ModelingError("body.shape", f"body.shape.{key} must be in 0...1.")
    for key, value in body.tolerances_m.items():
        if key not in DEFAULT_TOLERANCES_M:
            raise ModelingError("body.tolerances", f"body.tolerances_m has unknown key {key!r}.")
        if not is_finite(value) or value <= 0.0:
            raise ModelingError("body.tolerances", f"body.tolerances_m.{key} must be positive.")


def _validate_face(face: Face) -> None:
    for key, value in face.metrics_m.items():
        if key not in FACE_METRIC_KEYS:
            raise ModelingError("face.metrics", f"face.metrics_m has unknown key {key!r}.")
        if value is not None and (not is_finite(value) or not 0.0 < value < 0.2):
            raise ModelingError("face.metrics", f"face.metrics_m.{key} must be 0...0.2 m.")
    for key, value in face.shape.items():
        if key not in FACE_SHAPE_KEYS:
            raise ModelingError("face.shape", f"face.shape has unknown key {key!r}.")
        if not is_finite(value) or not 0.0 <= value <= 1.0:
            raise ModelingError("face.shape", f"face.shape.{key} must be in 0...1.")


def _validate_roughness(value, label: str) -> None:
    if value is None:
        return
    lo, hi = value
    if not (0.0 <= lo <= hi <= 1.0):
        raise ModelingError("material.roughness", f"{label}.roughness must be [min, max] within 0...1 with min <= max.")


def _validate_wardrobe(wardrobe, catalog, race, warnings: list[RecipeWarning]) -> None:
    slots = [g.slot for g in wardrobe]
    duplicates = sorted({s for s in slots if slots.count(s) > 1})
    if duplicates:
        raise ModelingError("wardrobe.slot", f"wardrobe slots must be unique; duplicated: {duplicates}.")
    if "dress" in slots and ("upper" in slots or "lower" in slots):
        warnings.append(RecipeWarning("wardrobe.layers", "a dress together with upper/lower garments; check the layering."))
    for garment in wardrobe:
        label = f"wardrobe[{garment.slot}]"
        if garment.material is not None:
            _validate_roughness(garment.material.roughness, label)
        for key, value in garment.finished_measurements_m.items():
            if not is_finite(value) or value <= 0.0:
                raise ModelingError("wardrobe.measurement", f"{label}.finished_measurements_m.{key} must be positive.")
        if garment.catalog_id is None:
            warnings.append(RecipeWarning("wardrobe.unresolved", f"{label}: no catalog entry matched {garment.name or garment.blueprint_garment!r}; slot will be empty."))
        elif catalog is not None:
            _check_catalog_reference(catalog, garment.catalog_id, ("wardrobe", "footwear"), garment.slot, race, label, warnings)


def _validate_accessories(accessories, catalog, warnings: list[RecipeWarning]) -> None:
    import os

    ids = [a.id for a in accessories]
    if len(ids) != len(set(ids)):
        raise ModelingError("accessory.duplicateID", "accessory ids must be unique.")
    for accessory in accessories:
        label = f"accessories[{accessory.id}]"
        source = accessory.source
        if source.kind == "promodeler_asset":
            if not source.path or not source.path.endswith(".py"):
                raise ModelingError("accessory.source", f"{label}.source.path must be an asset .py file.")
            if not os.path.isfile(source.path):
                warnings.append(RecipeWarning("accessory.missingAsset", f"{label}: {source.path} does not exist yet; build it with `promodeler build` before `character build`."))
        elif source.kind == "catalog":
            if not source.catalog_id:
                raise ModelingError("accessory.source", f"{label}.source.catalog_id is required for kind 'catalog'.")
            if catalog is not None:
                _check_catalog_reference(catalog, source.catalog_id, "accessories", None, None, label, warnings)
        if accessory.socket is None:
            warnings.append(RecipeWarning("accessory.socket", f"{label}: socket is null; the blueprint attachment text could not be mapped."))
        if accessory.size_xyz_m is not None and any(not is_finite(v) or v <= 0.0 for v in accessory.size_xyz_m):
            raise ModelingError("accessory.size", f"{label}.size_xyz_m must be positive.")


def _validate_animation(animation: Animation) -> None:
    ids = [c.id for c in animation.clips]
    if len(ids) != len(set(ids)):
        raise ModelingError("clip.duplicateID", "animation.clips ids must be unique.")
    for name, (lo, hi) in animation.limits_deg.items():
        if not is_finite(lo) or not is_finite(hi) or lo >= hi:
            raise ModelingError("animation.limits", f"animation.limits_deg.{name} must be [min, max] with min < max.")
    for shape in animation.face_shapes:
        if shape not in FACE_SHAPES:
            raise ModelingError("animation.faceShape", f"animation.face_shapes has unknown shape {shape!r} (allowed {list(FACE_SHAPES)}).")


def _validate_appearance(appearance: Appearance, catalog, race, warnings: list[RecipeWarning]) -> None:
    _validate_roughness(appearance.skin.roughness, "appearance.skin")
    if catalog is None:
        return
    refs = (
        (appearance.skin.preset, "skin", "appearance.skin.preset"),
        (appearance.hair.style, "hair", "appearance.hair.style"),
        (appearance.eyebrows.style, "eyebrows", "appearance.eyebrows.style"),
        (appearance.facial_hair.style if appearance.facial_hair else None, "facial_hair", "appearance.facial_hair.style"),
        (appearance.teeth.preset, "teeth", "appearance.teeth.preset"),
    )
    for catalog_id, category, label in refs:
        if catalog_id is not None:
            _check_catalog_reference(catalog, catalog_id, category, None, race, label, warnings)


def _check_catalog_reference(catalog, catalog_id: str, categories, slot, race, label: str, warnings: list[RecipeWarning]) -> None:
    entry = catalog.get(catalog_id)  # raises catalog.unknown
    allowed = (categories,) if isinstance(categories, str) else tuple(categories)
    if entry.category not in allowed:
        raise ModelingError("catalog.category", f"{label}: {catalog_id!r} is a {entry.category} entry, expected {list(allowed)}.")
    warnings.extend(catalog.check(entry, slot=slot, race=race, label=label))


def is_valid_id(value: str) -> bool:
    return bool(re.fullmatch(ID_PATTERN, value or ""))
