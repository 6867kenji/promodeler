"""Copy the verified warehouse and city into the existing local model gallery."""

import json
import shutil
import sys
from pathlib import Path

warehouse, city, gallery = (Path(a).resolve() for a in sys.argv[1:])
for source, slug, design in ((city, "city", "01-city"), (warehouse, "warehouse", "24-warehouse")):
    receipt = json.loads((source/"import-validation.json").read_text(encoding="utf-8"))
    if receipt["status"] != "ok" or not receipt["blenderReimport"] or not receipt["embeddedImages"]:
        raise ValueError("Only verified builds can enter the review gallery")
    target = gallery/slug/source.name
    if target.exists():
        if (target/"model.glb").stat().st_size != (source/"model.glb").stat().st_size:
            raise FileExistsError(target)
    else:
        shutil.copytree(source, target)

    def relocate(value):
        if isinstance(value, str):
            return value.replace(str(source), str(target)).replace(source.as_posix(), target.as_posix())
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, dict):
            return {key: relocate(v) for key, v in value.items()}
        return value

    for name in ("report.json", "import-validation.json", "provenance.json"):
        path = target/name
        if path.is_file():
            path.write_text(json.dumps(relocate(json.loads(path.read_text(encoding="utf-8"))),
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    logs = gallery/"build-logs"
    logs.mkdir(exist_ok=True)
    (logs/(design+".txt")).write_text("out: "+str(target)+"\n", encoding="utf-8")
project = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project))
from promodeler.gallery import create
entries = create(gallery)
print("GALLERY_UPDATED", len(entries), "models", gallery)
