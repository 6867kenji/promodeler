"""japan-realistic-v1 blueprint (``promodeler-blueprint/1.0``) -> CharacterRecipe / OutfitRecipe.

The mapping is deterministic and documented in
docs/03-character-recipe-pipeline.md chapter 5. Numbers are copied;
free text is matched against catalog ``match`` fragments and small
vocabularies below, and every guess that could not be made becomes a
``RecipeWarning`` instead of a silent default.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..core.diagnostics import ModelingError
from .catalog import Catalog
from .recipe import (
    DEFAULT_LIMITS_DEG, DEFAULT_TOLERANCES_M, FACE_METRIC_KEYS, FACE_SHAPE_KEYS, GENERATOR_VERSION, LANDMARKS, OUTFIT_SCHEMA,
    SCHEMA, Accessory, AccessorySource, Animation, Appearance, Base, Body, CharacterRecipe, ClipSpec, CrossSection, Eyebrows,
    Eyes, Face, FacialHair, Garment, GarmentMaterial, Hair, Identity, Measurements, OutfitRecipe, RecipeWarning, Skin, Source,
    Teeth,
)

BLUEPRINT_SCHEMA = "promodeler-blueprint/1.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# blueprint garments[].id -> wardrobe slot
GARMENT_SLOTS = {
    "upper": "upper", "jacket": "upper", "gi-jacket": "upper", "lower": "lower", "pants": "lower", "gi-pants": "lower",
    "skirt": "lower", "inner": "inner", "support": "inner", "tie": "neck", "apron": "waist", "belt": "waist",
    "gloves": "hands", "boots": "footwear", "dress": "dress",
}
# blueprint accessories[].id -> socket; the attachment text is the same boilerplate for every blueprint
ACCESSORY_SOCKETS = {
    "glasses": "face", "watch": "wrist_l", "sports-watch": "wrist_l", "badge": "chest", "phone": "hand_l",
    "briefcase": "hand_r", "backpack": "back", "tote": "shoulder_l", "shoulder-bag": "shoulder_l", "messenger": "shoulder_l",
    "eco-bag": "hand_l",
}
SOCKET_WORDS = (("眼鏡", "face"), ("時計", "wrist_l"), ("名札", "chest"), ("リュック", "back"), ("ショルダー", "shoulder_l"),
                ("肩", "shoulder_l"), ("スマートフォン", "hand_l"), ("バッグ", "hand_r"))
# free-text face traits -> 0...1 slider offsets from the neutral 0.5 face
FACE_VOCAB = {
    "面長": {"face_length": 0.7}, "細長い顔": {"face_length": 0.7, "cheek_width": 0.4}, "長めの卵型": {"face_length": 0.62},
    "卵型": {"face_length": 0.55, "jaw_width": 0.45}, "丸顔": {"face_length": 0.38, "cheek_width": 0.6, "jaw_width": 0.45},
    "丸みのある顔": {"face_length": 0.42, "cheek_width": 0.58}, "丸い頬": {"cheek_width": 0.62}, "幅広の顔": {"cheek_width": 0.68, "jaw_width": 0.62},
    "角張った顔": {"jaw_width": 0.68, "chin_size": 0.6}, "角のある": {"jaw_width": 0.6}, "小顔": {"face_length": 0.45, "cheek_width": 0.45},
    "大きな目": {"eye_size": 0.65}, "つり目": {"eye_tilt": 0.65}, "たれ目": {"eye_tilt": 0.35}, "厚い唇": {"lip_thickness": 0.65},
    "薄い唇": {"lip_thickness": 0.38}, "高い鼻": {"nose_bridge": 0.65}, "低い鼻": {"nose_bridge": 0.38}, "しわ": {},
}
FACE_WORDS = ("顔", "頬", "顎", "目", "鼻", "口", "唇", "額", "しわ", "ひげ", "眉", "肌")
HAIR_WORDS = ("髪", "ヘア", "ボブ", "ポニーテール", "シニヨン", "マッシュ", "分け", "結び", "ウェーブ", "束ね")
# body traits -> 0...1 shape sliders
BODY_VOCAB = {
    "鍛えた": {"muscle": 0.72}, "引き締まった": {"muscle": 0.62, "body_fat": 0.3}, "がっしり": {"muscle": 0.62, "body_fat": 0.6},
    "スレンダー": {"body_fat": 0.28}, "細身": {"body_fat": 0.3}, "小柄": {}, "腹部の丸み": {"body_fat": 0.68},
    "丸い肩": {"posture": 0.4}, "スポーティー": {"muscle": 0.6},
}
EYE_COLOR_WORDS = (("ブラウンの瞳", "#574335"), ("茶の瞳", "#574335"), ("黒い瞳", "#3E2C22"))
STANDARD_CLIP_IDS = ("idle", "walk", "turn", "sit", "raise-arms", "physics-settle")
DEFAULT_SCLERA = "#ECE8E4"


def load_blueprint(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ModelingError("blueprint.file", f"Blueprint not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != BLUEPRINT_SCHEMA:
        raise ModelingError("blueprint.schema", f"{path} has schema {data.get('schema')!r}; expected {BLUEPRINT_SCHEMA}.")
    data["_path"] = str(path)
    return data


def blueprint_seed(blueprint: dict) -> int:
    match = re.match(r"(\d+)", blueprint.get("folder") or Path(blueprint["_path"]).parent.name)
    return int(match.group(1)) if match else 0


def _source(blueprint: dict, catalog: Catalog) -> Source:
    path = Path(blueprint["_path"]).resolve()
    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = path.as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return Source(kind="blueprint", path=rel, sha256=digest, generator_version=GENERATOR_VERSION, catalog_version=catalog.version)


def _color(materials: dict, *ids: str) -> str | None:
    for material_id in ids:
        material = materials.get(material_id)
        if material and material.get("base_color_srgb"):
            return material["base_color_srgb"].upper()
    return None


def _roughness(materials: dict, *ids: str):
    for material_id in ids:
        material = materials.get(material_id)
        if material and material.get("roughness"):
            lo, hi = material["roughness"]
            return (float(lo), float(hi))
    return None


def _split(text: str | None) -> list[str]:
    if not text:
        return []
    return [t.strip() for t in re.split(r"[、。,]", text) if t.strip()]


def _sex(blueprint: dict) -> str:
    identity = blueprint.get("identity") or {}
    if identity.get("sex") in ("male", "female"):
        return identity["sex"]
    category = blueprint.get("category", "")
    if "female" in category or "女性" in (blueprint.get("summary") or ""):
        return "female"
    if "male" in category or "男性" in (blueprint.get("summary") or ""):
        return "male"
    raise ModelingError("blueprint.sex", f"{blueprint['id']}: cannot determine sex from identity, category or summary.")


def _measurements(dims: dict, blueprint: dict) -> Measurements:
    sections = []
    for section in dims.get("cross_sections") or blueprint.get("cross_sections") or []:
        landmark = section.get("landmark")
        if landmark not in LANDMARKS:
            continue
        sections.append(CrossSection(landmark=landmark, height=float(section["height_m"]), width=section.get("width_m"),
                                     depth=section.get("depth_m"), circumference=section.get("circumference_m")))
    circumferences = {k: float(v) for k, v in (dims.get("body_circumferences_m") or {}).items()}
    return Measurements(
        barefoot_height=float(dims["barefoot_height_m"]), inseam=dims.get("inseam_m"), shoulder_width=dims.get("shoulder_width_m"),
        foot_length=dims.get("foot_length_m"), head_height=dims.get("head_height_m"), circumferences=circumferences,
        cross_sections=tuple(sections),
    )


def _body_shape(sex: str, measurements: Measurements, descriptors: list[str]) -> dict:
    shape = {"muscle": 0.45 if sex == "male" else 0.35, "body_fat": 0.45, "posture": 0.5}
    waist = measurements.circumferences.get("waist")
    if waist:  # waist/height 0.37 -> lean 0.25, 0.47 -> 0.44, 0.61 -> 0.7 (initial value, editable in the GUI)
        ratio = waist / measurements.barefoot_height
        shape["body_fat"] = round(min(1.0, max(0.0, 0.25 + (ratio - 0.37) * 1.875)), 3)
    for text in descriptors:
        for word, values in BODY_VOCAB.items():
            if word in text:
                shape.update(values)
    return shape


def _tolerances(qa: list[str]) -> dict:
    tolerances = dict(DEFAULT_TOLERANCES_M)
    text = " ".join(qa)
    height = re.search(r"身長\s*±\s*(\d+(?:\.\d+)?)\s*mm", text)
    circumference = re.search(r"円周\s*±\s*(\d+(?:\.\d+)?)\s*mm", text)
    if height:
        tolerances["barefoot_height"] = float(height.group(1)) / 1000.0
    if circumference:
        tolerances["circumference"] = float(circumference.group(1)) / 1000.0
    return tolerances


def _face(blueprint: dict, descriptors: list[str]) -> Face:
    details = " ".join(blueprint.get("details") or [])
    metrics: dict[str, float | None] = {k: None for k in FACE_METRIC_KEYS}
    for key, pattern in (("eyeball_diameter", r"眼球径\s*([\d.]+)\s*mm"), ("iris_diameter", r"虹彩径\s*([\d.]+)\s*mm"),
                         ("mouth_width", r"口幅\s*([\d.]+)\s*mm"), ("nose_width", r"鼻幅\s*([\d.]+)\s*mm")):
        match = re.search(pattern, details)
        if match:
            metrics[key] = float(match.group(1)) / 1000.0
    shape = {k: 0.5 for k in FACE_SHAPE_KEYS}
    face_descriptors = [d for d in descriptors if any(w in d for w in FACE_WORDS) and not any(w in d for w in HAIR_WORDS)]
    for text in descriptors:
        for word, values in FACE_VOCAB.items():
            if word in text:
                shape.update(values)
    return Face(metrics_m=metrics, shape=shape, descriptors=tuple(face_descriptors))


def _appearance(blueprint: dict, sex: str, race: str, descriptors: list[str], catalog: Catalog, warnings: list[RecipeWarning]) -> Appearance:
    materials = {m["id"]: m for m in blueprint.get("materials") or []}
    text = " ".join(descriptors + [blueprint.get("summary") or ""])
    skin_color = _color(materials, "skin") or "#DFC1AD"
    skin_preset = catalog.nearest_color("skin", skin_color)
    hair_entry = catalog.match_text(text, "hair", race=race)
    if hair_entry is None:
        warnings.append(RecipeWarning("appearance.hair", f"no hair style matched {text!r}."))
    hair_color = _color(materials, "hair") or "#30201B"
    eye_color = _color(materials, "eye")
    if eye_color is None:
        for word, color in EYE_COLOR_WORDS:
            if word in text:
                eye_color = color
                break
    facial_hair = None
    if sex == "male":
        beard = catalog.match_text(text, "facial_hair", race=race)
        if beard is not None:
            facial_hair = FacialHair(style=beard.id, color_srgb=hair_color)
    brows = catalog.find("eyebrows", race=race)
    dims = blueprint.get("dimensions") or {}
    return Appearance(
        skin=Skin(preset=skin_preset.id if skin_preset else None, base_color_srgb=skin_color, roughness=_roughness(materials, "skin")),
        hair=Hair(style=hair_entry.id if hair_entry else None, base_color_srgb=hair_color, length_m=dims.get("hair_length_m")),
        eyebrows=Eyebrows(style=brows[0].id if brows else None, color_srgb=hair_color),
        eyes=Eyes(iris_color_srgb=eye_color or "#4A3628", sclera_color_srgb=DEFAULT_SCLERA),
        facial_hair=facial_hair,
        teeth=Teeth(preset=(catalog.find("teeth") or [None])[0].id if catalog.find("teeth") else None, base_color_srgb=_color(materials, "teeth") or "#DCD4C3"),
    )


def _garment_material(materials: dict, material_id: str | None) -> GarmentMaterial | None:
    material = materials.get(material_id or "")
    if not material:
        return None
    roughness = material.get("roughness")
    return GarmentMaterial(base_color_srgb=(material.get("base_color_srgb") or "").upper() or None,
                           roughness=(float(roughness[0]), float(roughness[1])) if roughness else None,
                           metallic=material.get("metallic"))


def _garments(blueprint: dict, race: str | None, catalog: Catalog, warnings: list[RecipeWarning]) -> list[Garment]:
    materials = {m["id"]: m for m in blueprint.get("materials") or []}
    out: list[Garment] = []
    for garment in blueprint.get("garments") or []:
        slot = GARMENT_SLOTS.get(garment["id"])
        if slot is None:
            warnings.append(RecipeWarning("wardrobe.slot", f"garment {garment['id']!r} has no slot mapping; skipped."))
            continue
        entry = catalog.match_text(garment.get("name", ""), ("wardrobe", "footwear"), slot=slot, race=race)
        finished = {k: float(v) for k, v in (garment.get("finished_measurements_m") or {}).items()}
        kwargs = {}
        if slot == "footwear":
            kwargs = {"sole_height_m": finished.pop("sole_height", None), "internal_length_m": finished.pop("internal_length", None)}
        out.append(Garment(slot=slot, catalog_id=entry.id if entry else None, blueprint_garment=garment["id"], name=garment.get("name"),
                           material=_garment_material(materials, garment.get("material")), finished_measurements_m=finished,
                           deformation=garment.get("deformation"), construction=garment.get("construction"), **kwargs))
    # 05-woman describes its dress as a part, not a garment.
    if not blueprint.get("garments"):
        for part in blueprint.get("parts") or []:
            if part["id"] in GARMENT_SLOTS and part["id"] != "body":
                slot = GARMENT_SLOTS[part["id"]]
                entry = catalog.match_text(part.get("name", ""), "wardrobe", slot=slot, race=race)
                dims = blueprint.get("dimensions") or {}
                finished = {"hem_height": float(dims["dress_hem_height_m"])} if slot == "dress" and dims.get("dress_hem_height_m") else {}
                out.append(Garment(slot=slot, catalog_id=entry.id if entry else None, blueprint_garment=part["id"], name=part.get("name"),
                                   material=_garment_material(materials, part.get("material")), finished_measurements_m=finished,
                                   deformation="cloth", construction=part.get("note")))
    return out


def _footwear(blueprint: dict, race: str | None, catalog: Catalog, warnings: list[RecipeWarning]) -> Garment | None:
    footwear = blueprint.get("footwear")
    dims = blueprint.get("dimensions") or {}
    materials = {m["id"]: m for m in blueprint.get("materials") or []}
    if footwear is None:
        if not dims.get("shoe_sole_m"):
            return None
        text = " ".join([blueprint.get("summary") or ""] + (blueprint.get("details") or []))
        entry = catalog.match_text(text, "footwear", slot="footwear", race=race)
        if entry is None:
            warnings.append(RecipeWarning("wardrobe.unresolved", "shoe_sole_m is set but no footwear type matched the text."))
        material = _garment_material(materials, "leather" if "革" in text else "rubber")
        return Garment(slot="footwear", catalog_id=entry.id if entry else None, name=entry.name if entry else None, material=material,
                       sole_height_m=float(dims["shoe_sole_m"]), heel_height_m=float(dims["shoe_sole_m"]), deformation="rigid_skinned")
    if footwear.get("barefoot"):
        return None
    text = footwear.get("color_and_type") or ""  # construction is boilerplate shared by every blueprint (it mentions pumps)
    entry = catalog.match_text(text, "footwear", slot="footwear", race=race)
    material = _garment_material(materials, "leather" if ("革" in text or "パンプス" in text or "ローファー" in text) else "rubber")
    return Garment(slot="footwear", catalog_id=entry.id if entry else None, name=entry.name if entry else None, material=material,
                   sole_height_m=footwear.get("sole_height_m", footwear.get("forefoot_sole_m")), heel_height_m=footwear.get("heel_height_m"),
                   internal_length_m=footwear.get("internal_length_m"), construction=footwear.get("construction"), deformation="rigid_skinned")


def _accessories(blueprint: dict, warnings: list[RecipeWarning]) -> list[Accessory]:
    physics = (blueprint.get("physics") or {}).get("accessories") or {}
    out = []
    for accessory in blueprint.get("accessories") or []:
        socket = ACCESSORY_SOCKETS.get(accessory["id"])
        if socket is None:
            for word, candidate in SOCKET_WORDS:
                if word in (accessory.get("detail") or "") or word in accessory["id"]:
                    socket = candidate
                    break
        if socket is None:
            warnings.append(RecipeWarning("accessory.socket", f"accessory {accessory['id']!r}: no socket vocabulary matched."))
        size = accessory.get("size_xyz_m")
        out.append(Accessory(
            id=accessory["id"], source=AccessorySource(kind="promodeler_asset", path=f"assets/props/{accessory['id'].replace('-', '_')}.py"),
            socket=socket, size_xyz_m=tuple(float(v) for v in size) if size else None, detail=accessory.get("detail"), physics=dict(physics),
        ))
    return out


def _animation(blueprint: dict) -> Animation:
    rig = blueprint.get("rig") or {}
    limits = {k: (float(v[0]), float(v[1])) for k, v in (rig.get("limits_deg") or {}).items()} or dict(DEFAULT_LIMITS_DEG)
    face_text = rig.get("face") or ""
    shapes: list[str] = []
    if "瞬き" in face_text:
        shapes += ["blink_l", "blink_r"]
    if "笑顔" in face_text:
        shapes.append("smile")
    if "口開" in face_text:
        shapes.append("jaw_open")
    if "母音" in face_text:
        shapes += ["vowel_a", "vowel_i", "vowel_u", "vowel_e", "vowel_o"]
    clips = tuple(ClipSpec(id=c["id"], duration_s=float(c["duration_s"]), loop=bool(c.get("loop", False)), description=c.get("description"))
                  for c in blueprint.get("clips") or [])
    return Animation(limits_deg=limits, face_shapes=tuple(shapes), clips=clips)


def _target(blueprint: dict) -> dict:
    target = dict(blueprint.get("target") or {})
    note = target.get("engine")
    if isinstance(note, str):
        target["engine"] = "unity_hdrp" if "HDRP" in note else ("unity_urp" if "URP" in note else "unity")
        target["engine_note"] = note
    return target


def character_from_blueprint(blueprint: dict, catalog: Catalog, seed: int | None = None) -> tuple[CharacterRecipe, list[RecipeWarning]]:
    if blueprint.get("kind") != "humanoid":
        raise ModelingError("character.kind", f"{blueprint.get('id')}: kind {blueprint.get('kind')!r} is not humanoid.")
    warnings: list[RecipeWarning] = []
    dims = blueprint["dimensions"]
    sex = _sex(blueprint)
    race = "human_male" if sex == "male" else "human_female"
    identity = blueprint.get("identity") or {}
    descriptors = _split(identity.get("face_shape_hair")) or _split(blueprint.get("summary"))
    measurements = _measurements(dims, blueprint)
    wardrobe = _garments(blueprint, race, catalog, warnings)
    footwear = _footwear(blueprint, race, catalog, warnings)
    if footwear is not None and not any(g.slot == "footwear" for g in wardrobe):
        wardrobe.append(footwear)
    recipe = CharacterRecipe(
        schema=SCHEMA, id=blueprint["id"], name=blueprint.get("name", blueprint["id"]),
        seed=blueprint_seed(blueprint) if seed is None else seed,
        source=_source(blueprint, catalog),
        identity=Identity(fictional=bool(identity.get("fictional", True)), sex=sex, age=identity.get("age") or dims.get("age"), descriptors=tuple(descriptors)),
        base=Base(race=race),
        body=Body(measurements_m=measurements, shape=_body_shape(sex, measurements, descriptors), tolerances_m=_tolerances(blueprint.get("qa") or [])),
        face=_face(blueprint, descriptors),
        appearance=_appearance(blueprint, sex, race, descriptors, catalog, warnings),
        wardrobe=tuple(wardrobe), accessories=tuple(_accessories(blueprint, warnings)),
        animation=_animation(blueprint), physics=dict(blueprint.get("physics") or {}), target=_target(blueprint),
        acceptance=tuple(blueprint.get("qa") or []),
    )
    return recipe, warnings


def outfit_from_blueprint(blueprint: dict, catalog: Catalog, base_race: str | None = None) -> tuple[OutfitRecipe, list[RecipeWarning]]:
    if blueprint.get("kind") != "wearable":
        raise ModelingError("character.kind", f"{blueprint.get('id')}: kind {blueprint.get('kind')!r} is not wearable.")
    warnings: list[RecipeWarning] = []
    fit = blueprint.get("fit") or {}
    base_id = fit.get("base_id")
    if not base_id:
        raise ModelingError("outfit.base", f"{blueprint['id']}: fit.base_id is required.")
    base_clip_ids: set[str] = set(STANDARD_CLIP_IDS)
    base_path = Path(blueprint["_path"]).parent / (fit.get("base_character") or "")
    if base_path.is_file():
        base_blueprint = json.loads(base_path.read_text(encoding="utf-8"))
        base_clip_ids = {c["id"] for c in base_blueprint.get("clips") or []}
        if base_race is None:
            base_race = "human_female" if "female" in base_blueprint.get("category", "") else "human_male"
    wardrobe = _garments(blueprint, base_race, catalog, warnings)
    dims = blueprint.get("dimensions") or {}
    barefoot = not dims.get("shoe_sole_m") and not any(g.slot == "footwear" for g in wardrobe)
    hair = None
    variant = fit.get("hair_variant")
    if variant:
        entry = catalog.match_text(variant, "hair", race=base_race)
        if entry is None:
            warnings.append(RecipeWarning("appearance.hair", f"hair_variant {variant!r} matched no catalog style."))
        hair = Hair(style=entry.id if entry else None)
    clips_extra = tuple(ClipSpec(id=c["id"], duration_s=float(c["duration_s"]), loop=bool(c.get("loop", False)), description=c.get("description"))
                        for c in blueprint.get("clips") or [] if c["id"] not in base_clip_ids)
    outfit = OutfitRecipe(
        schema=OUTFIT_SCHEMA, id=blueprint["id"], base_character=base_id, name=blueprint.get("name", blueprint["id"]),
        source=_source(blueprint, catalog), barefoot=barefoot, wardrobe=tuple(wardrobe), hair_override=hair,
        extra_bones=tuple((blueprint.get("rig") or {}).get("extra_bones") or []), controls=dict(blueprint.get("garment_controls") or {}),
        clips_extra=clips_extra, physics=dict(blueprint.get("physics") or {}), target=_target(blueprint), acceptance=tuple(blueprint.get("qa") or []),
    )
    return outfit, warnings
