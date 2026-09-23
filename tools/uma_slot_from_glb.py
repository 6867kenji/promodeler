"""promodeler garment GLB -> UMA 3 slot, overlay and wardrobe recipe (docs/03 chapter 12, 18.8).

    python tools/uma_slot_from_glb.py build/white_shirt/<hash>/model.glb --race human_female --name white_shirt_f --slot TopUnderlayer
    python tools/uma_slot_from_glb.py --asset assets/wardrobe/white_shirt.py --race human_female --name white_shirt_f --slot TopUnderlayer

With --asset the garment is built (or reused from the build cache) first. The conversion itself runs inside the
Unity character creator (ProModeler.Editor.WardrobeSlotImporter): closest-surface weight transfer from the race's
neutral body, SlotDataAsset + OverlayDataAsset with flat textures, UMAWardrobeRecipe in the requested wardrobe slot,
all registered in UMA's global library. Afterwards point the catalog entry's runtime.uma_wardrobe_recipe_by_race at
"<name>_Wardrobe" and rebuild the character.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promodeler.character import bridge  # noqa: E402
from promodeler.character.recipe import RACES  # noqa: E402
from promodeler.core import ModelingError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("glb", nargs="?", help="Built garment GLB (omit with --asset).")
    parser.add_argument("--asset", help="Garment generator to build first (assets/wardrobe/<name>.py).")
    parser.add_argument("--manifest", nargs="?", const=str(bridge.GARMENTS_MANIFEST), help="Build and import every garment of character/garments.json.")
    parser.add_argument("--race", choices=sorted(RACES))
    parser.add_argument("--name", help="Asset name; the UMA recipe becomes <name>_Wardrobe (with --manifest: only this garment).")
    parser.add_argument("--slot", choices=bridge.WARDROBE_SLOTS)
    parser.add_argument("--color", help="Flat diffuse color #RRGGBB.")
    parser.add_argument("--material-from-recipe", help="Reuse the UMAMaterial of this UMA wardrobe recipe.")
    parser.add_argument("--material", help="UMAMaterial asset name fallback.")
    parser.add_argument("--force", action="store_true", help="Rebuild the asset even when cached.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    glb = args.glb
    try:
        if args.manifest:
            reports = bridge.import_garment_manifest(args.manifest, force=args.force, only=args.name, log=print if args.verbose else None)
            print(json.dumps(reports, ensure_ascii=False, indent=2))
            return 0 if all(r.get("ok") for r in reports) else 1
        if not (args.race and args.name and args.slot):
            parser.error("--race, --name and --slot are required without --manifest")
        if args.asset:
            from promodeler import build as asset_build

            result = asset_build.build(args.asset, force=args.force, render={"views": ("perspective",), "passes": ("shaded",), "resolution": 384})
            if not result.ok:
                print(f"asset build failed: {result.report.get('error')}", file=sys.stderr)
                return 1
            glb = result.report.get("export", {}).get("path")
            print(f"asset:    {args.asset} -> {glb} ({'cached' if result.cached else 'built'})")
        if not glb:
            parser.error("give a GLB path or --asset")
        report = bridge.import_wardrobe_slot(glb, args.race, args.name, args.slot, color=args.color,
                                             material_from_recipe=args.material_from_recipe, material=args.material,
                                             log=print if args.verbose else None)
    except (ModelingError, bridge.UnityNotFound) as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
