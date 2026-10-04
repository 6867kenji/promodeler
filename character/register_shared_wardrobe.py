"""Register a prepared common wardrobe and its reproducible example recipes."""

import copy
import json
import sys
from pathlib import Path


root = Path(__file__).resolve().parent
model = Path(sys.argv[1]).resolve()
descriptor = json.loads(model.with_suffix(".modules.json").read_text(encoding="utf-8"))
manifest = copy.deepcopy(json.loads((root / "bases/RiggedWoman_v4/manifest.json").read_text(encoding="utf-8")))
manifest["id"] = "RiggedWoman_v5"
manifest["model"] = str(model).replace("\\", "/")
for field in ("modules", "bodyMasks", "bodyMeshMasks"):
    for path, choices in descriptor[field].items():
        manifest.setdefault(field, {}).setdefault(path, {}).update(choices)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


save(root / "bases/RiggedWoman_v5/manifest.json", manifest)
samples = (
    ("shared-amber-woman", "Amber Outfit on Rigged Woman", {"top": "amber_crop_tshirt", "bottom": "amber_jeans", "shoes": "amber_boots", "outer": "amber_leather_jacket"}),
    ("shared-amber-casual-woman", "Amber Casual Outfit on Rigged Woman", {"top": "amber_crop_tshirt", "bottom": "amber_jeans", "shoes": "amber_boots"}),
    ("shared-megane-uniform-woman", "Megane Uniform on Rigged Woman", {"dress": "megane_uniform"}),
    ("shared-female-casual-woman", "Separated Female Outfit on Rigged Woman", {"top": "female_tank_top", "bottom": "female_cargo_pants", "outer": "female_jacket"}),
    ("shared-blouse-jeans-woman", "Blouse with Amber Jeans on Rigged Woman", {"top": "blouse_a", "bottom": "amber_jeans", "shoes": "amber_boots"}),
)
for asset_id, name, wardrobe in samples:
    recipe = {"schema": "promodeler-canonical-character/2.0", "id": asset_id, "name": name,
              "base": manifest["id"], "seed": 1, "source": {"kind": "shared_wardrobe"},
              "face": {}, "body": {"chest": .25}, "appearance": {"hairStyle": "hair_ponytail_brown"},
              "material": {}, "wardrobe": wardrobe, "accessories": []}
    save(root / "canonical_recipes" / (asset_id + ".json"), recipe)
catalog_path = root / "wardrobe_catalog.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
split_names = {"female_cargo_pants": "カーゴパンツ", "female_tank_top": "タンクトップ", "female_jacket": "ジャケット"}
for original in descriptor["items"]:
    shared = copy.deepcopy(original)
    if shared["id"] in split_names:
        shared["name"] = split_names[shared["id"]]
        shared["fit"] = "section_fit_material_split"
    existing = next((item for item in catalog["items"] if item["id"] == shared["id"]), None)
    if existing:
        if shared["id"] in split_names:
            existing.update(shared)
            continue
        native_base = existing["compatibleBases"][0]
        fits = existing.setdefault("fits", {native_base: {"objects": existing["objects"], "fit": "native"}})
        fits[manifest["id"]] = {"objects": shared["objects"], "fit": shared["fit"], "model": manifest["model"]}
        if manifest["id"] not in existing["compatibleBases"]:
            existing["compatibleBases"].append(manifest["id"])
    else:
        catalog["items"].append(shared)
save(catalog_path, catalog)
print("REGISTERED_SHARED_WARDROBE", len(descriptor["items"]), "selections", len(samples), "recipes")
