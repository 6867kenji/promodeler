"""Copy a verified city build into the existing model gallery, keeping old builds."""

import json
import shutil
import sys
from pathlib import Path


source, gallery = map(lambda value: Path(value).resolve(), sys.argv[1:])
target = gallery / "city" / source.name
if target.exists():
    raise FileExistsError(target)
shutil.copytree(source, target)


def relocate(value):
    if isinstance(value, str):
        return value.replace(str(source), str(target)).replace(source.as_posix(), target.as_posix())
    if isinstance(value, list):
        return [relocate(item) for item in value]
    if isinstance(value, dict):
        return {key: relocate(item) for key, item in value.items()}
    return value


for name in ("report.json", "import-validation.json", "provenance.json"):
    path = target / name
    path.write_text(json.dumps(relocate(json.loads(path.read_text(encoding="utf-8"))),
                               ensure_ascii=False, indent=2), encoding="utf-8")
logs = gallery / "build-logs"
logs.mkdir(exist_ok=True)
(logs / "01-city.txt").write_text("out: " + str(target) + "\n", encoding="utf-8")
project = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project))
from promodeler.gallery import create
entries = create(gallery)
print("UPDATED_MODEL_GALLERY", len(entries), "models", target)
