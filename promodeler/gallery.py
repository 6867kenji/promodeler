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
        preview = next((renders[view] for view in ("cutaway", "escalator_close", "gate_full_width",
                                                  "floor_detail",
                                                  "gate_oblique",
                                                  "walkthrough", "perspective",
                                                  "district_oblique", "main_street", "front")
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
            "images": [{"view": view, "path": relative(path)} for view, path in renders.items()],
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
    names = {
        "01-city": "町", "02-apartment": "集合住宅", "03-convenience": "コンビニ",
        "04-office": "オフィス", "07-bed": "ベッド", "08-sofa": "ソファ",
        "09-ceiling-light": "天井照明", "10-table-chair": "テーブル・椅子",
        "11-pc-desk": "PCデスク", "12-pc-set": "PCセット",
        "13-refrigerator": "冷蔵庫", "14-microwave": "電子レンジ",
        "15-gaming-pc-white": "白いゲーミングPC",
        "16-gaming-pc-pink": "ピンクのゲーミングPC",
        "17-subway-entrance": "地下鉄入口", "18-subway-concourse": "地下鉄コンコース",
        "19-subway-platform": "地下鉄ホーム", "20-cafe": "カフェ",
        "21-karate-dojo": "空手道場",
    }
    image_cards = []
    for entry in entries:
        title = html.escape(names.get(entry["design"], entry["design"]))
        design = html.escape(entry["design"])
        preview = entry["preview"]
        if not preview:
            continue
        links = "".join(
            f'<a href="{html.escape(item["path"])}" data-caption="{title} · {html.escape(item["view"])}">'
            f'{html.escape(item["view"])}</a>' for item in entry["images"])
        image_cards.append(
            f'<article><a class="hero" href="{html.escape(preview)}" data-caption="{title}">'
            f'<img src="{html.escape(preview)}" alt="{title}" loading="lazy"></a>'
            f'<div class="body"><h2>{title}</h2><p>{design}</p><nav>{links}</nav></div></article>')
    image_page = """<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>モデル画像一覧</title><style>
*{box-sizing:border-box}body{margin:0;background:#111820;color:#f2f5f8;font:16px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:#111820ed;border-bottom:1px solid #33404e;padding:18px 28px}
header div{max-width:1540px;margin:auto;display:flex;align-items:baseline;justify-content:space-between;gap:16px}
h1{font-size:24px;margin:0}header a,nav a{color:#96d8ff;text-decoration:none}header a:hover,nav a:hover{text-decoration:underline}
main{max-width:1540px;margin:auto;padding:24px 28px 56px}.intro{color:#b3c0cc;margin:0 0 22px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:18px}
article{background:#202a34;border:1px solid #354453;border-radius:12px;overflow:hidden}
.hero{display:block;background:#596775}.hero img{display:block;width:100%;height:230px;object-fit:contain}
.body{padding:15px 16px 17px}h2{font-size:19px;margin:0}.body p{font-size:13px;color:#a8b6c3;margin:2px 0 12px}
nav{display:flex;flex-wrap:wrap;gap:7px}nav a{font-size:13px;border:1px solid #4c6476;border-radius:20px;padding:3px 9px}
dialog{padding:0;border:0;background:#10151b;color:white;max-width:96vw;max-height:96vh;box-shadow:0 22px 80px #000b}
dialog::backdrop{background:#000d}.viewer{position:relative;display:grid;place-items:center}
.viewer img{display:block;max-width:95vw;max-height:88vh;object-fit:contain}
.viewer p{position:absolute;left:0;bottom:0;margin:0;padding:7px 14px;background:#10151bcc}
.close{position:absolute;right:8px;top:8px;background:#18232ddd;color:white;border:1px solid #789;border-radius:30px;width:38px;height:38px;font-size:24px;cursor:pointer}
</style><header><div><h1>モデル画像一覧</h1><a href="index.html">GLB・Blenderファイル一覧 ↗</a></div></header>
<main><p class="intro">全19モデルの確認画像です。画像または視点名をクリックすると拡大できます。</p><div class="grid">""" + "".join(image_cards) + """</div></main>
<dialog id="lightbox"><div class="viewer"><img alt=""><p></p><button class="close" aria-label="閉じる">×</button></div></dialog>
<script>
const box=document.querySelector('#lightbox');
document.querySelectorAll('a[data-caption]').forEach(a=>a.addEventListener('click',e=>{
  e.preventDefault();box.querySelector('img').src=a.href;
  box.querySelector('p').textContent=a.dataset.caption;box.showModal();
}));
box.querySelector('.close').onclick=()=>box.close();
box.addEventListener('click',e=>{if(e.target===box)box.close()});
box.addEventListener('close',()=>{box.querySelector('img').src=''});
</script></html>"""
    (root / "images.html").write_text(image_page, encoding="utf-8")
    return entries


if __name__ == "__main__":
    items = create(Path(sys.argv[1]))
    print(f"Indexed {len(items)} GLBs")
