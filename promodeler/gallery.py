"""Write an offline gallery for a batch of blueprint builds."""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path


def create(root: Path) -> list[dict]:
    entries = []
    for log_path in sorted((root / "build-logs").glob("*.txt")):
        output = next((line.split("out:", 1)[1].strip() for line in
                       log_path.read_text(encoding="utf-8").splitlines()
                       if line.startswith("out:")), None)
        if not output:
            continue
        directory = Path(output)
        report_path = directory / "report.json"
        model_path = directory / "model.glb"
        blend_path = directory / "model.blend"
        if not report_path.is_file() or not model_path.is_file():
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        renders = {render["view"]: Path(render["path"]) for render in report.get("renders", [])
                   if render.get("written")}
        preview = next((renders[view] for view in ("cutaway", "walkthrough", "perspective")
                        if view in renders), None)
        relative = lambda path: path.relative_to(root).as_posix()
        entries.append({
            "design": log_path.stem, "asset": report["asset"],
            "status": report["status"],
            "blueprint_status": report.get("blueprint_qa", {}).get("status"),
            "issues": report.get("blueprint_qa", {}).get("issues", []),
            "parts": len(report.get("parts", {})),
            "triangles": report.get("totals", {}).get("triangles", 0),
            "glb_bytes": model_path.stat().st_size,
            "model": relative(model_path), "report": relative(report_path),
            "blend": relative(blend_path) if blend_path.is_file() else None,
            "preview": relative(preview) if preview else None,
        })
    (root / "manifest.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    cards = []
    for entry in entries:
        name = html.escape(entry["design"])
        status = html.escape(entry["blueprint_status"] or "unknown")
        preview = entry["preview"]
        image = f'<img src="{html.escape(preview)}" alt="{name}">' if preview else ""
        issue = (f'<p class="issue">{html.escape(entry["issues"][0]["message"])}</p>'
                 if entry["issues"] else "")
        blend = (f'<a href="{html.escape(entry["blend"])}">Blender (.blend)</a>'
                 if entry["blend"] else "")
        cards.append(f'<article>{image}<div><h2>{name}</h2>'
                     f'<p>{entry["parts"]} parts · {entry["triangles"]:,} tris · QA {status}</p>'
                     f'{issue}<nav><a href="{html.escape(entry["model"])}">GLB</a>'
                     f'{blend}<a href="{html.escape(entry["report"])}">QA report</a></nav></div></article>')
    page = """<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>promodeler 非人体モデル</title><style>
body{margin:0;padding:32px;background:#151a20;color:#e6edf3;font:16px/1.5 system-ui,sans-serif}
main{max-width:1400px;margin:auto}h1{font-size:30px}p{color:#aebbc7}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}
article{background:#222a33;border:1px solid #34414d;border-radius:14px;overflow:hidden}
img{width:100%;height:190px;object-fit:contain;background:#69747b;display:block}
article div{padding:18px}h2{font-size:18px;margin:0 0 8px}article p{margin:0 0 12px;font-size:13px}
.issue{color:#ffd58a}nav{display:flex;gap:14px}a{color:#8cd4ff;text-decoration:none}a:hover{text-decoration:underline}
</style><main><h1>非人体モデル / 3D assets</h1><p>設計書から生成したGLB、確認画像、数値QA。</p>
<p>Blenderでは「Blender (.blend)」を［ファイルを開く］で開けます。GLBは［ファイル → インポート → glTF 2.0］から読み込みます。</p>
<div class="grid">""" + "".join(cards) + "</div></main></html>"
    (root / "index.html").write_text(page, encoding="utf-8")
    return entries


if __name__ == "__main__":
    items = create(Path(sys.argv[1]))
    print(f"Indexed {len(items)} GLBs")
