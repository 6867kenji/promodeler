"""Build the city review page and record local generation provenance."""

import hashlib
import html
import json
import sys
from pathlib import Path


output = Path(sys.argv[1]).resolve()
root = output.parents[1]
report = json.loads((output / "report.json").read_text(encoding="utf-8"))
validation = json.loads((output / "import-validation.json").read_text(encoding="utf-8"))
layout_validation = json.loads((output / "layout-validation.json").read_text(encoding="utf-8"))
project = Path(__file__).resolve().parents[3]
from write_density_plan import write_plan
layout = json.loads((output / "recipe.json").read_text(encoding="utf-8"))["asset"]["extras"]["city_layout"]
write_plan(output, layout)


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


sources = [project / "assets/city.py", project / "assets/city_layout.py",
           project / "assets/city_facilities.py", project / "assets/warehouse.py",
           project / "promodeler/kernel/tiled.py", project / "promodeler/kernel/compile.py",
           Path(__file__).parent / "density_layout.json",
           Path(__file__).parent / "facility_layout.json",
           Path(__file__).parent.parent / "24-warehouse/blueprint.json",
           Path(__file__).parent / "reference_models.json"]
metadata = {"name": "Shiomi city with warehouse", "version": 4,
            "generation": "local procedural geometry and PBR maps", "buildHash": report["hash"],
            "license": "private local use; distribution not configured", "build": str(output),
            "sources": [{"path": str(path), "sha256": digest(path)} for path in sources],
            "reference": json.loads(sources[-1].read_text(encoding="utf-8")),
            "validation": validation, "blueprintQA": report["blueprint_qa"],
            "layoutValidation": layout_validation, "generationWarnings": report.get("warnings", []),
            "reviewCameraOverrides": report.get("reviewCameraOverrides", {}),
            "imagesReviewedSeparately": True}
(output / "provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
names = {"district_oblique": ("街全体", f'{layout["buildingCount"]}棟の外観と高さのバランス'),
         "district_plan": ("平面配置", "道路と街区の配置"),
         "main_street": ("幹線道路", "歩道・道路と建物の関係"),
         "neighborhood_walk": ("建物の近景", "窓台・外壁・入口の仕上がり"),
         "rooftop_detail": ("屋上の近景", "空調・換気設備・給水タンク"),
         "sidewalk_detail": ("歩道の近景", "レンガの目地・路面の質感"),
         "reserved_sites": ("交差点と施設敷地", "地下鉄用空き地と倉庫敷地"),
         "warehouse_street": ("街から見た倉庫", "歩道・荷捌き場・搬入口"),
         "warehouse_site": ("倉庫の敷地", "北側の車両入口、西側の歩行通路、周囲の建物")}


def relative(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return html.escape(path.relative_to(root).as_posix(), quote=True)


cards = []
plan = relative(output / "density-plan.svg")
cards.append(f'<article><a href="{plan}" data-caption="密集配置図"><img src="{plan}" alt="密集配置図"></a><div><h2>密集配置図</h2><p>各区画20棟、追加倉庫と地下鉄用敷地</p></div></article>')
for image in report["renders"]:
    if not image.get("written"):
        raise ValueError("Missing city review image")
    title, detail = names.get(image["view"], (image["view"], "確認画像"))
    path = relative(image["path"])
    cards.append(f'<article><a href="{path}" data-caption="{title}"><img src="{path}" alt="{title}" loading="lazy"></a><div><h2>{title}</h2><p>{detail}</p></div></article>')
page = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>汐見町 — 建物と街路の仕上げ</title><style>
*{box-sizing:border-box}body{margin:0;background:#f1f4f5;color:#26343b;font:15px/1.6 system-ui,"Yu Gothic",sans-serif}main{max-width:1500px;margin:auto;padding:36px}h1{font-size:36px;margin:6px 0 12px}h2{font-size:18px;margin:0}p{color:#5f7079}.eyebrow{font-size:12px;letter-spacing:.14em;color:#286773}.links{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0 30px}.links a{background:#23616e;color:white;padding:10px 18px;border-radius:7px;text-decoration:none}.links a.secondary{background:white;color:#23616e;border:1px solid #adc0c5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:20px}article{background:white;border:1px solid #d5dfe3;border-radius:12px;overflow:hidden}article img{width:100%;display:block;aspect-ratio:1.6;object-fit:contain;background:#c3ced3}article div{padding:16px}article p{margin:4px 0 0}a{color:#23616e}.facts{padding:18px 22px;background:white;border:1px solid #d5dfe3;border-radius:10px;margin:24px 0}.facts p{margin:6px 0}dialog{border:0;border-radius:10px;padding:12px;max-width:96vw;background:#f1f4f5}dialog::backdrop{background:#000b}dialog img{max-width:92vw;max-height:82vh;display:block}dialog .bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}dialog button{padding:6px 14px;border:1px solid #adc0c5;border-radius:5px;cursor:pointer}footer{margin-top:28px;font-size:13px}@media(max-width:600px){main{padding:20px}h1{font-size:28px}.grid{grid-template-columns:1fr}}
</style></head><body><main><div class="eyebrow">PROMODELER / SHIOMI TOWN</div><h1>汐見町 — 建物と街路の仕上げ</h1><p>建築物の参考モデルをもとに、屋上設備・外壁・歩道の細部を追加しました。画像をクリックすると拡大できます。</p>
<div class="links"><a href="__GLB__" download>GLBを保存</a><a href="__BLEND__">Blenderファイル</a><a class="secondary" href="__QA__">生成・設計確認結果</a><a class="secondary" href="__IMPORT__">GLB読み込み確認</a></div>
<div class="grid">__CARDS__</div><div class="facts"><p><strong>144棟</strong> · 屋上の空調・換気設備と雨樋を追加。一部に給水タンクを配置。</p><p>外壁タイル・レンガの目地を法線マップへ反映し、歩道と屋上には色むらと粗さの使用感を追加。</p><p>道路に補修跡・排水口・マンホール、歩道に凹凸のある警告パネルを配置。</p><p>GLBをBlenderで再読み込みし、PBR画像の埋め込みを確認。全建物の屋内動線とUnityでの描画性能は今回の確認範囲に含まれません。</p><p>Blenderでは .blend を［ファイルを開く］、GLBを［ファイル → インポート → glTF 2.0］で読み込みます。</p></div><footer><a href="__PROVENANCE__">制作元と検証記録</a> · <a href="../promodeler-wardrobe/index.html">衣装の画像一覧</a></footer></main>
<dialog id="zoom"><div class="bar"><span></span><button>閉じる</button></div><img alt=""></dialog><script>const zoom=document.querySelector('#zoom');document.querySelectorAll('[data-caption]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();zoom.querySelector('img').src=a.href;zoom.querySelector('img').alt=a.dataset.caption;zoom.querySelector('span').textContent=a.dataset.caption;zoom.showModal()}));zoom.querySelector('button').onclick=()=>zoom.close();zoom.addEventListener('click',e=>{if(e.target===zoom)zoom.close()});</script></body></html>'''
for key, value in {"__GLB__": relative(output / "model.glb"), "__BLEND__": relative(output / "model.blend"),
                   "__QA__": relative(output / "report.json"), "__IMPORT__": relative(output / "import-validation.json"),
                   "__PROVENANCE__": relative(output / "provenance.json"), "__CARDS__": "\n".join(cards)}.items():
    page = page.replace(key, value)
page = page.replace("汐見町 — 建物と街路の仕上げ", "汐見町 — 320棟の密集配置")
page = page.replace("建築物の参考モデルをもとに、屋上設備・外壁・歩道の細部を追加しました。", "各区画を20棟に増やし、歩道に近づけました。小さいビルの左右を詰め、別の建物や地下鉄入口を追加する敷地を残しています。")
page = page.replace("<strong>144棟</strong>", f'<strong>既存320棟＋倉庫1棟＝{layout["buildingCount"]}棟</strong>')
page = page.replace("汐見町 — 320棟の密集配置", "汐見町 — 倉庫の追加")
page = page.replace("各区画を20棟に増やし、歩道に近づけました。小さいビルの左右を詰め、別の建物や地下鉄入口を追加する敷地を残しています。", "各区画20棟の街に物流倉庫を追加しました。波板屋根・天窓・搬入口・レンガ外壁を作り、歩道と荷捌き場を接続しています。地下鉄用敷地は残しています。")
reserve_text = " · ".join(f'{r["use"]}用 {r["size_m"][0]:.1f}×{r["size_m"][1]:.1f}m' for r in layout["reservedSites"])
page = page.replace('<div class="facts">', f'<div class="facts"><p>歩道端から1.4m／建物間1–12m／小さいビルの左右1–2.4m。</p><p>{reserve_text}</p>')
triangles = sum(part["triangles"] for part in report["parts"].values())
size_mb = (output / "model.glb").stat().st_size / 1_000_000
budget_note = f'GLB {size_mb:.1f}MB／{triangles:,}三角形。'
if any(w["code"] == "budget.triangles" for w in report.get("warnings", [])):
    budget_note += '設計の街全体上限8,000,000以内ですが、同時表示の目安2,000,000を超えています。ゲーム利用時は区画ごとの表示制御が必要です。'
page = page.replace('<div class="facts">', f'<div class="facts"><p>{budget_note}</p>', 1)
page = page.replace('<a class="secondary" href="', f'<a class="secondary" href="{relative(output / "layout.json")}">配置の寸法・座標</a><a class="secondary" href="{relative(output / "layout-validation.json")}">空き地・配置の検証</a><a class="secondary" href="', 1)
(root / "index.html").write_text(page, encoding="utf-8")
print("CITY_REVIEW_PAGE", root / "index.html")
