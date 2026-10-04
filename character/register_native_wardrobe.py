"""Register separated clothing meshes without editing the source characters.

The old v1 manifests and recipes remain intact. Run with regular Python.
"""

import copy
import json
from pathlib import Path


root = Path(__file__).resolve().parent
config = json.loads((root / "wardrobe_sources.json").read_text(encoding="utf-8"))
catalog = {"schema": "promodeler-wardrobe-catalog/1.0", "items": [], "deferred": config["deferred"]}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


for character in config["characters"]:
    old_path = root / "bases" / character["sourceBase"] / "manifest.json"
    manifest = copy.deepcopy(json.loads(old_path.read_text(encoding="utf-8")))
    manifest["id"] = character["base"]
    source_model = str((old_path.parent / manifest["model"]).resolve()).replace("\\", "/")
    manifest["model"] = character.get("preparedModel", source_model)
    if not Path(manifest["model"]).is_file():
        raise FileNotFoundError(manifest["model"])
    modules = manifest.setdefault("modules", {})
    masks = manifest.setdefault("bodyMasks", {})
    wardrobe = {}
    for item in character["items"]:
        path = "wardrobe." + item["slot"]
        modules.setdefault(path, {})[item["id"]] = item["objects"]
        wardrobe[item["slot"]] = item["id"]
        if item.get("masks"):
            masks.setdefault(path, {})[item["id"]] = item["masks"]
        catalog["items"].append({
            **item, "sourceBase": character["sourceBase"], "sourceModel": source_model,
            "compatibleBases": [character["base"]], "rig": "static" if "Static" in character["sourceBase"] else "native",
            "fit": "native", "materials": "source_textures_preserved"
        })
    if character.get("accessories"):
        manifest["accessories"] = character["accessories"]
    save(root / "bases" / manifest["id"] / "manifest.json", manifest)
    recipe = {
        "schema": "promodeler-canonical-character/2.0", "id": character["recipe"],
        "name": character["name"] + " Selectable Wardrobe", "base": manifest["id"], "seed": 1,
        "source": {"kind": "native_wardrobe", "base": character["sourceBase"]},
        "face": {}, "body": {}, "appearance": {}, "material": {}, "wardrobe": wardrobe,
        "accessories": list(character.get("accessories", {}))
    }
    save(root / "canonical_recipes" / (recipe["id"] + ".json"), recipe)
save(root / "wardrobe_catalog.json", catalog)
print("REGISTERED_NATIVE_WARDROBE", len(config["characters"]), "bases", len(catalog["items"]), "garments")
