"""``promodeler character random``: seed-deterministic CharacterRecipes from anthropometric priors (docs/03 M13).

The priors live in ``character/presets/anthropometry.json`` (population means and spreads, hair and iris palettes,
wardrobe styles as catalog ids). Every draw comes from one ``random.Random(seed)`` in a fixed order, so the same
seed, presets and catalog give the same recipe; ``source`` records all three. The recipe goes through the ordinary
``validate`` and the static measurement checks, so a bad prior fails loudly instead of producing an impossible body.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

from ..core.diagnostics import ModelingError
from . import consistency
from .catalog import Catalog
from .recipe import (
    FACE_SHAPE_KEYS, SCHEMA, Accessory, AccessorySource, Animation, Appearance, Base, Body, CharacterRecipe, CrossSection, Eyebrows, Eyes,
    FacialHair, Face, Garment, GarmentMaterial, Hair, Identity, Measurements, RecipeWarning, Skin, Source, Teeth,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PRESETS = PROJECT_ROOT / "character" / "presets" / "anthropometry.json"
PRESETS_SCHEMA = "promodeler-anthropometry/1.0"
SAMPLER_VERSION = 1
DEFAULT_SCLERA = "#ECE8E4"
FOOTWEAR_SOLE_M = {"pumps_low_01": (0.012, 0.035), "boots_short_leather_01": (0.02, 0.035), "sneaker_low_01": (0.025, 0.028),
                   "running_shoe_01": (0.028, 0.032), "walking_shoe_01": (0.025, 0.028), "work_shoe_01": (0.02, 0.025)}


def load_presets(path: str | Path = DEFAULT_PRESETS) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != PRESETS_SCHEMA:
        raise ModelingError("presets.schema", f"{path} is not a {PRESETS_SCHEMA} document.")
    for sex in ("male", "female"):
        if sex not in data.get("populations", {}):
            raise ModelingError("presets.population", f"{path} has no population for {sex}.")
    data["_path"] = str(Path(path))
    data["_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return data


# --- draws ------------------------------------------------------------------------------------

def _gauss(rng: random.Random, spec: dict, lo: float | None = None, hi: float | None = None) -> float:
    value = rng.gauss(float(spec["mean"]), float(spec["sd"]))
    lo = spec.get("min", lo)
    hi = spec.get("max", hi)
    if lo is not None:
        value = max(float(lo), value)
    if hi is not None:
        value = min(float(hi), value)
    return value


def _weighted(rng: random.Random, items: list, weight=lambda item: item.get("weight", 1.0)):
    total = sum(float(weight(i)) for i in items)
    pick = rng.uniform(0.0, total)
    running = 0.0
    for item in items:
        running += float(weight(item))
        if pick <= running:
            return item
    return items[-1]


def _clamp_ratio(value: float, bounds: tuple[float, float] | None, margin: float = 0.005) -> float:
    if bounds is None:
        return value
    lo, hi = bounds
    return min(hi - margin, max(lo + margin, value))


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


# --- body -------------------------------------------------------------------------------------

def sample_measurements(rng: random.Random, population: dict, overrides: dict | None = None) -> tuple[Measurements, dict]:
    """Height, the ratio-based lengths, the girth model and the body shape sliders for one population.

    ``overrides`` (``height_m``, ``body_fat``, ``muscle``, ``posture``) replace the corresponding draw; the draw is
    still made so the other values of the seed do not shift."""
    overrides = overrides or {}
    height = _gauss(rng, population["height"])
    if overrides.get("height_m") is not None:
        height = min(float(population["height"].get("max", 2.2)), max(float(population["height"].get("min", 1.3)), float(overrides["height_m"])))
    # Ratios and girth/height ratios are clamped just inside the adult ranges of consistency.static_checks, so a
    # 3-sigma tail never produces a recipe the checks reject (about 1 percent of draws touch the clamps).
    ratios = {name: _clamp_ratio(_gauss(rng, spec), consistency.RATIO_RANGES.get(name)) for name, spec in population["ratios"].items()}
    fat_spec = population["body_fat"]
    body_fat = rng.betavariate(float(fat_spec["alpha"]), float(fat_spec["beta"]))
    if overrides.get("body_fat") is not None:
        body_fat = min(1.0, max(0.0, float(overrides["body_fat"])))
    muscle = _gauss(rng, population["muscle"], 0.0, 1.0)
    if overrides.get("muscle") is not None:
        muscle = min(1.0, max(0.0, float(overrides["muscle"])))
    girths: dict[str, float] = {}
    for name, spec in population["girths"].items():
        value = (float(spec["mean"]) + float(spec["height_slope"]) * (height - float(population["height"]["mean"]))
                 + float(spec["fat_slope"]) * (body_fat - 0.45) + rng.gauss(0.0, float(spec["residual_sd"])))
        girths[name] = value
    for name in list(girths):
        girths[name] = height * _clamp_ratio(girths[name] / height, consistency.GIRTH_RANGES.get(name))
    # Keep the girths in anatomical order (waist below hip and chest by at least the stated margins).
    for smaller, larger, margin in population.get("girth_order", []):
        if smaller in girths and larger in girths and girths[larger] < girths[smaller] + margin:
            girths[larger] = girths[smaller] + margin
    # Cross sections carry the landmark height and the girth only: extents derived from a girth would be fabricated
    # (docs/03 18.7: circumferences lead, extents are report-only).
    fractions = population.get("landmark_fractions", {})
    sections = []
    for landmark, value in girths.items():
        fraction = fractions.get(landmark) or (fractions.get("chest") if landmark == "bust" else None)
        if fraction is None:
            continue
        sections.append(CrossSection(landmark=landmark, height=_round(height * float(fraction)), circumference=_round(value)))
    sections = tuple(sections)
    measurements = Measurements(
        barefoot_height=_round(height), inseam=_round(height * ratios["inseam"]), shoulder_width=_round(height * ratios["shoulder_width"]),
        foot_length=_round(height * ratios["foot_length"]), head_height=_round(height * ratios["head_height"]),
        circumferences={k: _round(v) for k, v in girths.items()}, cross_sections=sections,
    )
    posture = rng.gauss(0.5, 0.06)
    if overrides.get("posture") is not None:
        posture = float(overrides["posture"])
    shape = {"muscle": _round(muscle), "body_fat": _round(body_fat), "posture": _round(min(0.8, max(0.2, posture)))}
    return measurements, shape


def sample_face(rng: random.Random, presets: dict, face_shape: dict | None = None, descriptors: tuple[str, ...] = ()) -> Face:
    sd = float(presets.get("face_shape_sd", 0.09))
    shape = {k: _round(min(0.85, max(0.15, rng.gauss(0.5, sd)))) for k in FACE_SHAPE_KEYS}
    for key, value in (face_shape or {}).items():
        if key in shape:
            shape[key] = _round(min(1.0, max(0.0, float(value))))
    return Face(shape=shape, descriptors=tuple(descriptors))


# --- appearance -------------------------------------------------------------------------------

def sample_appearance(rng: random.Random, presets: dict, sex: str, race: str, catalog: Catalog, population: dict, warnings: list[RecipeWarning],
                      overrides: dict | None = None) -> Appearance:
    overrides = overrides or {}
    skins = [e for e in catalog.find("skin", race=race)]
    weights = presets.get("skin_weights", {})
    skin = _weighted(rng, skins, lambda e: weights.get(e.id, 1.0)) if skins else None
    if overrides.get("skin_preset") in catalog.entries:
        skin = catalog.entries[overrides["skin_preset"]]
    hair_color = _weighted(rng, presets["hair_colors"])["srgb"]
    if overrides.get("hair_color_srgb"):
        hair_color = str(overrides["hair_color_srgb"]).upper()
    tags = set(presets.get("hair_tags", {}).get(sex, []))
    hairs = [e for e in catalog.find("hair", race=race) if not tags or tags & set(e.tags)]
    if not hairs:
        hairs = catalog.find("hair", race=race)
    hair = rng.choice(hairs) if hairs else None
    if overrides.get("hair_style"):
        wanted = catalog.entries.get(overrides["hair_style"])
        if wanted is not None and wanted.category == "hair" and race in wanted.compatibility.races:
            hair = wanted
        else:
            warnings.append(RecipeWarning("appearance.hair", f"hair style {overrides['hair_style']!r} is not a catalog hair for {race}; a seeded style stands in."))
    if hair is None:
        warnings.append(RecipeWarning("appearance.hair", f"the catalog has no hair for {race}."))
    iris = _weighted(rng, presets["iris_colors"])
    if overrides.get("iris_color_srgb"):
        iris = {"srgb": str(overrides["iris_color_srgb"]).upper()}
    facial_hair = None
    beard_roll = rng.random()
    wants_beard = overrides.get("facial_hair")
    if sex == "male" and (wants_beard if wants_beard is not None else beard_roll < float(population.get("facial_hair_probability", 0.0))):
        beards = catalog.find("facial_hair", race=race)
        if beards:
            facial_hair = FacialHair(style=rng.choice(beards).id, color_srgb=hair_color)
    brows = catalog.find("eyebrows", race=race)
    teeth = catalog.find("teeth")
    return Appearance(
        skin=Skin(preset=skin.id if skin else None, base_color_srgb=skin.base_color_srgb if skin else "#DFC1AD", roughness=(0.45, 0.6)),
        hair=Hair(style=hair.id if hair else None, base_color_srgb=hair_color),
        eyebrows=Eyebrows(style=brows[0].id if brows else None, color_srgb=hair_color),
        eyes=Eyes(iris_color_srgb=iris["srgb"], sclera_color_srgb=DEFAULT_SCLERA),
        facial_hair=facial_hair,
        teeth=Teeth(preset=teeth[0].id if teeth else None, base_color_srgb=teeth[0].base_color_srgb if teeth and teeth[0].base_color_srgb else "#DCD4C3"),
    )


# --- wardrobe ---------------------------------------------------------------------------------

def sample_wardrobe(rng: random.Random, style: dict, sex: str, race: str, catalog: Catalog, warnings: list[RecipeWarning],
                    garment_ids: list[str] | None = None, garment_colors: dict | None = None) -> tuple[Garment, ...]:
    """The style's slots, each drawn from its list; ``garment_ids`` (catalog ids from a prompt) replace the draw of the
    slot they fit and add slots the style does not cover."""
    slots = dict(style["wardrobe"].get(sex) or {})
    colors = style.get("colors", {})
    garment_colors = garment_colors or {}
    requested: dict[str, str] = {}
    for catalog_id in garment_ids or []:
        entry = catalog.entries.get(catalog_id)
        if entry is None or entry.category not in ("wardrobe", "footwear"):
            warnings.append(RecipeWarning("wardrobe.unknown", f"{catalog_id!r} is not a wardrobe catalog id; ignored."))
            continue
        if race not in entry.compatibility.races:
            warnings.append(RecipeWarning("wardrobe.incompatible", f"{catalog_id} is not made for {race}; ignored."))
            continue
        fits = [s for s in entry.slots if s in slots] or list(entry.slots[:1])
        requested[fits[0]] = catalog_id
    for slot in requested:
        slots.setdefault(slot, [requested[slot]])
    if "dress" in requested:   # a dress replaces the upper and lower garments
        slots.pop("upper", None); slots.pop("lower", None); slots.pop("inner", None)
    garments = []
    for slot, choices in slots.items():
        catalog_id = rng.choice(list(choices))
        color = rng.choice(colors.get(slot, ["#808080"]))
        if slot in requested:
            catalog_id = requested[slot]
        if garment_colors.get(slot):
            color = str(garment_colors[slot])
        if catalog_id is None:
            continue
        if catalog_id not in catalog.entries:
            warnings.append(RecipeWarning("wardrobe.unknown", f"style lists {catalog_id!r} for {slot}, which is not in the catalog; skipped."))
            continue
        entry = catalog.entries[catalog_id]
        if slot not in entry.slots or race not in entry.compatibility.races:
            warnings.append(RecipeWarning("wardrobe.incompatible", f"{catalog_id} does not fit {slot} on {race}; skipped."))
            continue
        kwargs: dict = {}
        if slot == "footwear":
            sole, heel = FOOTWEAR_SOLE_M.get(catalog_id, (0.02, 0.03))
            kwargs = {"sole_height_m": sole, "heel_height_m": heel, "deformation": "rigid_skinned"}
        else:
            kwargs = {"deformation": "cloth"}
        roughness = (0.55, 0.8) if "leather" not in entry.tags else (0.35, 0.55)
        garments.append(Garment(slot=slot, catalog_id=catalog_id, name=entry.name or catalog_id,
                                material=GarmentMaterial(base_color_srgb=color.upper(), roughness=roughness, metallic=0.0), **kwargs))
    return tuple(garments)


ACCESSORY_SOCKETS = {
    "glasses": "face", "watch": "wrist_l", "sports-watch": "wrist_l", "badge": "chest", "phone": "hand_l", "briefcase": "hand_r",
    "backpack": "back", "tote": "shoulder_l", "shoulder-bag": "shoulder_l", "messenger": "shoulder_l", "eco-bag": "hand_l",
}


def sample_accessories(rng: random.Random, style: dict, sex: str, accessory_ids: list[str] | None = None,
                       warnings: list[RecipeWarning] | None = None) -> tuple[Accessory, ...]:
    """The style's optional props by probability; ``accessory_ids`` (from a prompt) are attached for certain."""
    out = []
    chosen: dict[str, str] = {}
    for spec in style.get("accessories", []):
        if spec.get("sex") and spec["sex"] != sex:
            continue
        roll = rng.random()
        if accessory_ids is None and roll < float(spec.get("probability", 0.0)):
            chosen[spec["id"]] = spec["socket"]
    for accessory_id in accessory_ids or []:
        socket = ACCESSORY_SOCKETS.get(accessory_id)
        if socket is None or not (PROJECT_ROOT / "assets" / "props" / f"{accessory_id.replace('-', '_')}.py").is_file():
            if warnings is not None:
                warnings.append(RecipeWarning("accessory.unknown", f"no promodeler prop for accessory {accessory_id!r}; ignored."))
            continue
        chosen[accessory_id] = socket
    for accessory_id, socket in chosen.items():
        prop = accessory_id.replace("-", "_")
        out.append(Accessory(id=accessory_id, source=AccessorySource(kind="promodeler_asset", path=f"assets/props/{prop}.py"), socket=socket))
    return tuple(out)


# --- recipe -----------------------------------------------------------------------------------

def sample_character(seed: int, catalog: Catalog, presets: dict | None = None, sex: str | None = None, style: str | None = None,
                     recipe_id: str | None = None, overrides: dict | None = None) -> tuple[CharacterRecipe, list[RecipeWarning]]:
    """One recipe for ``seed``. ``sex`` / ``style`` fix a draw instead of sampling it (the remaining draws stay seeded).

    ``overrides`` come from a prompt (``prompt.PromptSpec.to_overrides``): body (``height_m``, ``body_fat``, ``muscle``,
    ``posture``, ``age``), face (``face_shape``, ``face_descriptors``), appearance (``hair_style``, ``hair_color_srgb``,
    ``iris_color_srgb``, ``skin_preset``, ``facial_hair``), wardrobe (``garments``, ``garment_colors``), ``accessories``,
    ``name``, ``descriptors``, ``source``."""
    presets = presets or load_presets()
    overrides = dict(overrides or {})
    rng = random.Random(seed)
    warnings: list[RecipeWarning] = []
    drawn_sex = rng.choice(("male", "female"))
    sex = sex or overrides.get("sex") or drawn_sex
    population = presets["populations"][sex]
    race = population["race"]
    styles = presets["styles"]
    drawn_style = _weighted(rng, [dict(v, name=k) for k, v in styles.items()])["name"]
    style_name = style or overrides.get("style") or drawn_style
    if style_name not in styles:
        raise ModelingError("presets.style", f"unknown style {style_name!r}; presets define {sorted(styles)}.")
    age = rng.randint(int(population["age"]["min"]), int(population["age"]["max"]))
    if overrides.get("age") is not None:
        age = int(min(100, max(18, int(overrides["age"]))))
    measurements, shape = sample_measurements(rng, population, overrides)
    face = sample_face(rng, presets, overrides.get("face_shape"), tuple(overrides.get("face_descriptors") or ()))
    appearance = sample_appearance(rng, presets, sex, race, catalog, population, warnings, overrides)
    wardrobe = sample_wardrobe(rng, styles[style_name], sex, race, catalog, warnings, overrides.get("garments"), overrides.get("garment_colors"))
    accessories = sample_accessories(rng, styles[style_name], sex, overrides.get("accessories"), warnings)
    recipe_id = recipe_id or f"random-{seed:08x}"
    default_source = Source(kind="random", path=str(Path(presets["_path"]).relative_to(PROJECT_ROOT)) if str(presets["_path"]).startswith(str(PROJECT_ROOT)) else presets["_path"],
                            sha256=presets["_sha256"], generator_version=SAMPLER_VERSION, catalog_version=catalog.version)
    descriptors = (f"style:{style_name}",) + tuple(overrides.get("descriptors") or ())
    recipe = CharacterRecipe(
        schema=SCHEMA, id=recipe_id, seed=seed,
        name=overrides.get("name") or f"ランダム {seed:08x}（{'男性' if sex == 'male' else '女性'} {age} 歳、{style_name}）",
        source=overrides.get("source") or default_source,
        identity=Identity(fictional=True, sex=sex, age=age, descriptors=descriptors),
        base=Base(race=race),
        body=Body(measurements_m=measurements, shape=shape),
        face=face, appearance=appearance, wardrobe=wardrobe, accessories=accessories,
        animation=Animation(face_shapes=("blink_l", "blink_r", "smile", "jaw_open")),
        target={"engine": "unity_hdrp"},
    )
    warnings += consistency.static_checks(measurements)
    return recipe, warnings


def sample_many(seed: int, count: int, catalog: Catalog, presets: dict | None = None, **kwargs) -> list[tuple[CharacterRecipe, list[RecipeWarning]]]:
    """``count`` recipes for seeds ``seed, seed + 1, ...``."""
    presets = presets or load_presets()
    return [sample_character(seed + i, catalog, presets, **kwargs) for i in range(count)]
