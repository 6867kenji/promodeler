"""Canonical-base character recipes and the Blender build boundary.

This is deliberately separate from the existing UMA recipe and bridge.  A
canonical build consumes an authored base asset; it never synthesizes a human
mesh.  The manifest is the explicit mapping from semantic sliders to that
asset's shape keys, bones, modules and materials.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from ..build import blender_version, find_blender
from ..core import ModelingError

SCHEMA = "promodeler-canonical-character/2.0"
FACE = (
    "headSize", "faceRoundness", "jawWidth", "jawLength", "eyeSize", "eyeWidth",
    "eyeHeight", "eyeSpacing", "eyeAngle", "noseSize", "noseWidth", "noseHeight",
    "noseBridge", "mouthWidth", "mouthHeight", "upperLip", "lowerLip", "cheekVolume",
)
BODY = (
    "height", "headRatio", "shoulderWidth", "chest", "waist", "hip", "armLength",
    "legLength", "armThickness", "legThickness", "muscle",
)
APPEARANCE = ("skinPreset", "eyePreset", "hairStyle", "eyebrowStyle")
MATERIAL_COLORS = ("skinTone", "lipColor", "hairColor", "eyeColor")
MATERIAL_SLIDERS = ("blushStrength", "roughnessSkin", "toonBlend")
WARDROBE = ("top", "bottom", "shoes", "outer", "dress")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")
COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\Z")


def _number(value, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ModelingError("canonical.range", f"{path} must be a number from 0 to 1.")
    return float(value)


def _object(value, path: str, allowed: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        raise ModelingError("canonical.type", f"{path} must be an object.")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ModelingError("canonical.field", f"Unknown {path} fields: {', '.join(unknown)}")
    return value


def validate(recipe: dict) -> None:
    """Validate the portable recipe without requiring Blender or a base file."""
    root = _object(recipe, "recipe", (
        "schema", "id", "name", "base", "seed", "source", "face", "body",
        "appearance", "material", "wardrobe", "accessories", "underwear",
    ))
    if root.get("schema") != SCHEMA:
        raise ModelingError("canonical.schema", f"schema must be {SCHEMA}.")
    if not isinstance(root.get("id"), str) or not ID_RE.fullmatch(root["id"]):
        raise ModelingError("canonical.id", "id must use lowercase letters, digits, hyphen or underscore.")
    for key in ("name", "base"):
        if not isinstance(root.get(key), str) or not root[key].strip():
            raise ModelingError("canonical.field", f"{key} must be a nonempty string.")
    if isinstance(root.get("seed"), bool) or not isinstance(root.get("seed"), int):
        raise ModelingError("canonical.seed", "seed must be an integer.")
    if "source" in root and not isinstance(root["source"], dict):
        raise ModelingError("canonical.type", "source must be an object.")
    for group, keys in (("face", FACE), ("body", BODY)):
        values = _object(root.get(group), group, keys)
        for key, value in values.items():
            _number(value, f"{group}.{key}")
    appearance = _object(root.get("appearance"), "appearance", APPEARANCE)
    wardrobe = _object(root.get("wardrobe"), "wardrobe", WARDROBE)
    for group, values in (("appearance", appearance), ("wardrobe", wardrobe)):
        for key, value in values.items():
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ModelingError("canonical.type", f"{group}.{key} must be a nonempty ID or null.")
    accessories = root.get("accessories", [])
    if not isinstance(accessories, list) or any(not isinstance(item, str) or not item for item in accessories):
        raise ModelingError("canonical.type", "accessories must be a list of unique nonempty IDs.")
    if len(accessories) != len(set(accessories)):
        raise ModelingError("canonical.type", "accessories must not contain duplicate IDs.")
    underwear = _object(root.get("underwear", {}), "underwear", ("top", "bottom"))
    if any(type(value) is not bool for value in underwear.values()):
        raise ModelingError("canonical.type", "underwear.top and underwear.bottom must be booleans.")
    material = _object(root.get("material"), "material", MATERIAL_COLORS + MATERIAL_SLIDERS)
    for key, value in material.items():
        if key in MATERIAL_COLORS:
            if not isinstance(value, str) or not COLOR_RE.fullmatch(value):
                raise ModelingError("canonical.color", f"material.{key} must be #RRGGBB.")
        else:
            _number(value, f"material.{key}")


def _normalize(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 0.5
    return max(0.0, min(1.0, (value - low) / (high - low)))


def from_uma(legacy, *, base: str | None = None) -> dict:
    """Migrate a 1.0 recipe without changing or discarding its UMA source."""
    item = legacy.to_json()
    sex = item["identity"]["sex"]
    face = item["face"]["shape"]
    body = item["body"]
    measures = body["measurements_m"]
    colors = item["appearance"]
    garments = {g["slot"]: g.get("catalog_id") for g in item["wardrobe"]}
    migrated = {
        "schema": SCHEMA, "id": item["id"], "name": item["name"],
        "base": base or f"SemiRealBase_{sex.title()}_v1", "seed": item["seed"],
        "source": {"kind": "uma_recipe", "id": item["id"], "schema": item["schema"],
                   "blueprint": item.get("source", {}).get("path"),
                   "blueprint_sha256": item.get("source", {}).get("sha256")},
        "face": {
            "faceRoundness": 1 - face.get("face_length", 0.5),
            "jawWidth": face.get("jaw_width", 0.5),
            "eyeSize": face.get("eye_size", 0.5),
            "eyeSpacing": face.get("eye_spacing", 0.5),
            "eyeAngle": face.get("eye_tilt", 0.5),
            "noseWidth": face.get("nose_width", 0.5),
            "noseBridge": face.get("nose_bridge", 0.5),
            "mouthWidth": face.get("mouth_width", 0.5),
        },
        "body": {
            "height": _normalize(measures["barefoot_height"], 1.4, 2.1),
            "shoulderWidth": _normalize(measures.get("shoulder_width"), 0.30, 0.52),
            "waist": _normalize(measures["circumferences"].get("waist"), 0.55, 1.15),
            "hip": _normalize(measures["circumferences"].get("hip"), 0.75, 1.25),
            "muscle": body["shape"].get("muscle", 0.5),
        },
        "appearance": {
            "skinPreset": colors["skin"].get("preset"),
            "eyePreset": None,
            "hairStyle": colors["hair"].get("style"),
            "eyebrowStyle": colors["eyebrows"].get("style"),
        },
        "material": {
            "skinTone": colors["skin"]["base_color_srgb"],
            "hairColor": colors["hair"]["base_color_srgb"],
            "eyeColor": colors["eyes"]["iris_color_srgb"],
            "roughnessSkin": sum(colors["skin"].get("roughness", [0.5, 0.5])) / 2,
        },
        "wardrobe": {
            "top": garments.get("upper") or garments.get("inner"),
            "bottom": garments.get("lower"),
            "shoes": garments.get("footwear"),
            "outer": garments.get("outer"),
            "dress": garments.get("dress"),
        },
        "accessories": [accessory["id"] for accessory in item.get("accessories", [])],
    }
    validate(migrated)
    return migrated


def load_manifest(path: str | Path) -> tuple[dict, Path]:
    manifest_path = Path(path).resolve()
    if not manifest_path.is_file():
        raise ModelingError("canonical.base", f"Canonical manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("id"), str):
        raise ModelingError("canonical.base", "Canonical manifest needs an id.")
    model = manifest.get("model")
    if not isinstance(model, str) or not model:
        raise ModelingError("canonical.base", "Canonical manifest needs a model path.")
    model_path = (manifest_path.parent / model).resolve()
    if model_path.suffix.lower() not in (".glb", ".blend", ".fbx") or not model_path.is_file():
        raise ModelingError("canonical.base", f"Canonical GLB, Blend or FBX file not found: {model_path}")
    for key in ("parameters", "modules", "materials", "bodyMasks", "bodyMeshMasks", "accessories"):
        if not isinstance(manifest.get(key, {}), dict):
            raise ModelingError("canonical.base", f"manifest.{key} must be an object.")
    excluded = manifest.get("excludeObjects", [])
    if not isinstance(excluded, list) or any(not isinstance(name, str) or not name for name in excluded):
        raise ModelingError("canonical.base", "manifest.excludeObjects must list object names.")
    texture_max = manifest.get("textureMaxSize")
    if texture_max is not None and (isinstance(texture_max, bool) or not isinstance(texture_max, int)
                                    or not 256 <= texture_max <= 8192):
        raise ModelingError("canonical.base", "manifest.textureMaxSize must be an integer from 256 to 8192.")
    if not isinstance(manifest.get("exportMorphs", True), bool):
        raise ModelingError("canonical.base", "manifest.exportMorphs must be a boolean.")
    if not isinstance(manifest.get("requireSkin", False), bool):
        raise ModelingError("canonical.base", "manifest.requireSkin must be a boolean.")
    for path, mapping in manifest.get("parameters", {}).items():
        group, _, key = path.partition(".")
        if group not in ("face", "body") or key not in (FACE if group == "face" else BODY):
            raise ModelingError("canonical.base", f"Unknown semantic parameter in manifest: {path}")
        if not isinstance(mapping, dict) or not (mapping.get("shapeKeys") or mapping.get("bones")):
            raise ModelingError("canonical.base", f"manifest.parameters.{path} needs shapeKeys or bones.")
        for shape in mapping.get("shapeKeys", []):
            if not isinstance(shape, dict) or not isinstance(shape.get("name"), str) or shape.get("side", "positive") not in ("positive", "negative"):
                raise ModelingError("canonical.base", f"Invalid ShapeKey mapping for {path}.")
        for bone in mapping.get("bones", []):
            if not isinstance(bone, dict) or not isinstance(bone.get("name"), str) or bone.get("axis", "Y").upper() not in "XYZ":
                raise ModelingError("canonical.base", f"Invalid bone mapping for {path}.")
            scale = bone.get("scale", [0.9, 1.1])
            if not isinstance(scale, list) or len(scale) != 2 or not all(isinstance(v, (int, float)) and v > 0 for v in scale):
                raise ModelingError("canonical.base", f"Bone scale for {path} must have two positive numbers.")
    for path, choices in manifest.get("modules", {}).items():
        if not isinstance(choices, dict) or any(not isinstance(objects, list) or not objects or
                                                  any(not isinstance(name, str) or not name for name in objects)
                                                  for objects in choices.values()):
            raise ModelingError("canonical.base", f"manifest.modules.{path} must map IDs to object-name lists.")
    for role, names in manifest.get("materials", {}).items():
        if not isinstance(names, list) or not names or any(not isinstance(name, str) or not name for name in names):
            raise ModelingError("canonical.base", f"manifest.materials.{role} must list material names.")
    for accessory, names in manifest.get("accessories", {}).items():
        if not isinstance(names, list) or not names or any(not isinstance(name, str) or not name for name in names):
            raise ModelingError("canonical.base", f"manifest.accessories.{accessory} must list object names.")
    for path, choices in manifest.get("bodyMasks", {}).items():
        if path not in (f"wardrobe.{key}" for key in WARDROBE) or not isinstance(choices, dict) or any(
            not isinstance(names, list) or any(not isinstance(name, str) for name in names)
            for names in choices.values()
        ):
            raise ModelingError("canonical.base", f"manifest.bodyMasks.{path} must map garment IDs to body-object lists.")
    for path, choices in manifest.get("bodyMeshMasks", {}).items():
        if path not in (f"wardrobe.{key}" for key in WARDROBE) or not isinstance(choices, dict):
            raise ModelingError("canonical.base", f"Invalid mesh coverage path: {path}")
        for garment, masks in choices.items():
            if not isinstance(masks, list) or not masks or any(
                not isinstance(mask, dict) or any(not isinstance(mask.get(key), str) or not mask[key]
                                                  for key in ("object", "vertexGroup")) for mask in masks
            ):
                raise ModelingError("canonical.base", f"Invalid mesh coverage for {path}.{garment}")
    return manifest, model_path


def compatibility(recipe: dict, manifest: dict) -> list[str]:
    """List unresolved selections/changed sliders; never silently change their meaning."""
    validate(recipe)
    if recipe["base"] != manifest["id"]:
        raise ModelingError("canonical.base", f"Recipe requests {recipe['base']}, manifest provides {manifest['id']}.")
    unresolved = []
    parameters = manifest.get("parameters", {})
    for group in ("face", "body"):
        for key, value in recipe[group].items():
            if value != 0.5 and f"{group}.{key}" not in parameters:
                unresolved.append(f"{group}.{key}")
    modules = manifest.get("modules", {})
    for group, keys in (("appearance", ("hairStyle", "eyebrowStyle")), ("wardrobe", WARDROBE)):
        for key in keys:
            choice = recipe[group].get(key)
            if choice and choice not in modules.get(f"{group}.{key}", {}):
                unresolved.append(f"{group}.{key}={choice}")
    for accessory in recipe.get("accessories", []):
        if accessory not in manifest.get("accessories", {}):
            unresolved.append(f"accessories.{accessory}")
    for key in ("skinPreset", "eyePreset"):
        choice = recipe["appearance"].get(key)
        if choice:
            unresolved.append(f"appearance.{key}={choice}")
    roles = {"skinTone": "skin", "roughnessSkin": "skin", "lipColor": "lips",
             "hairColor": "hair", "eyeColor": "eyes"}
    for key, role in roles.items():
        if key in recipe["material"] and role not in manifest.get("materials", {}):
            unresolved.append(f"material.{key}")
    for key in ("blushStrength", "toonBlend"):
        value = recipe["material"].get(key)
        if value is not None and value != 0.5 and f"material.{key}" not in manifest.get("shaderInputs", {}):
            unresolved.append(f"material.{key}")
    return unresolved


def build(recipe: dict, manifest_path: str | Path, out_root: str | Path,
          *, force: bool = False, render: bool = True, strict: bool = False) -> tuple[Path, dict]:
    """Apply a canonical base in Blender and export an embedded GLB."""
    manifest, model = load_manifest(manifest_path)
    unresolved = compatibility(recipe, manifest)
    if strict and unresolved:
        raise ModelingError("canonical.mapping", "Unresolved canonical mappings: " + ", ".join(unresolved))
    blender = find_blender()
    version = blender_version(blender)
    canonical = json.dumps(recipe, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    manifest_text = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    compiler = Path(__file__).with_name("canonical_blender.py")
    hasher = hashlib.sha256((canonical + manifest_text + version + str(render)).encode("utf-8"))
    hasher.update(compiler.read_bytes())
    with model.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()[:12]
    out_dir = Path(out_root) / recipe["id"] / digest
    report_path = out_dir / "build.json"
    if report_path.is_file() and not force:
        cached = json.loads(report_path.read_text(encoding="utf-8"))
        if cached.get("status") == "ok" and (out_dir / "model.glb").is_file():
            return out_dir, cached
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recipe.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = [blender, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "23",
               "--python", str(compiler), "--",
               str(model), str(out_dir), "1" if render else "0"]
    with (out_dir / "blender.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    if not report_path.is_file():
        report = {"status": "failed", "error": {"code": "canonical.blender",
                  "message": f"Blender exited {process.returncode}; see blender.log"}}
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    report["unresolved"] = unresolved
    report["mode"] = "canonical"
    report["blender_version"] = version
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_dir, report


def inspect_base(model: str | Path, output: str | Path) -> dict:
    """Inventory an existing GLB/Blend/FBX/OBJ before authoring its resolver manifest."""
    model = Path(model).resolve()
    if not model.is_file() or model.suffix.lower() not in (".glb", ".blend", ".fbx", ".obj"):
        raise ModelingError("canonical.base", f"Expected an existing GLB, Blend, FBX or OBJ file: {model}")
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [find_blender(), "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "23",
               "--python", str(Path(__file__).with_name("canonical_inspect.py")), "--",
               str(model), str(output)]
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False)
    if process.returncode or not output.is_file():
        raise ModelingError("canonical.inspect", f"Could not inspect {model}: {process.stderr or process.stdout}")
    return json.loads(output.read_text(encoding="utf-8"))
