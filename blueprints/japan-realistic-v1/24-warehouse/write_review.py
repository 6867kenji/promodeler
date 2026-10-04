"""Write the combined warehouse / city review after both import checks pass."""

import hashlib
import html
import json
import sys
from pathlib import Path

warehouse, city = (Path(a).resolve() for a in sys.argv[1:])
root = warehouse.parents[1]
if city.parents[1] != root:
    raise ValueError("Review builds must share an artifact root")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    return html.escape(path.relative_to(root).as_posix(), quote=True)


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


reports = {"warehouse": read(warehouse/"report.json"), "city": read(city/"report.json")}
validation = {"warehouse": read(warehouse/"import-validation.json"), "city": read(city/"import-validation.json")}
layout = read(city/"layout.json")
layout_validation = read(city/"layout-validation.json")
if any(r["status"] != "ok" or r["blueprint_qa"]["status"] != "pass" for r in reports.values()):
    raise ValueError("Blueprint or generation check failed")
if any(v["status"] != "ok" or not v["blenderReimport"] or not v["embeddedImages"] for v in validation.values()):
    raise ValueError("Actual GLB import check failed")
reference = Path("C:/Users/kuwano/develop/3d/建築物/Warehouse/WSE_11.blend")
source_digest = file_hash(reference)
if source_digest != "c10106d5e0d141e355d335523025b0f6544753e9080fe80b590c4afaaa8ec07a":
    raise ValueError("Warehouse source changed since audit")
project = Path(__file__).resolve().parents[3]
sources = [project/"assets/warehouse.py", project/"assets/24-warehouse.py", project/"assets/city.py",
           project/"assets/city_facilities.py", project/"assets/city_layout.py", project/"promodeler/kernel/tiled.py",
           Path(__file__).parent/"blueprint.json", Path(__file__).parent.parent/"01-city/facility_layout.json"]
provenance = {"version": 1, "generation": "local code-generated geometry and PBR maps",
              "sourceReference": {"path": str(reference), "sha256": source_digest, "unchanged": True},
              "sources": [{"path": str(p), "sha256": file_hash(p)} for p in sources],
              "builds": {key: {"directory": str(directory), "hash": reports[key]["hash"],
                                 "blueprintQA": reports[key]["blueprint_qa"], "import": validation[key]}
                         for key, directory in (("warehouse", warehouse), ("city", city))},
              "layoutValidation": layout_validation,
              "reviewedViews": [r["view"] for report in reports.values() for r in report["renders"]],
              "license": "Private local review; public distribution not configured"}
(root/"provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")


def card(path, title, description):
    uri = relative(path)
    return f'<article><a href="{uri}" data-caption="{html.escape(title)}"><img src="{uri}" alt="{html.escape(title)}" loading="lazy"></a><div><h3>{html.escape(title)}</h3><p>{html.escape(description)}</p></div></article>'


def links(directory):
    return (f'<a href="{relative(directory/"model.glb")}" download>GLBを保存</a>'
            f'<a href="{relative(directory/"model.blend")}">Blenderファイル</a>'
            f'<a class="secondary" href="{relative(directory/"report.json")}">生成・寸法確認</a>'
            f'<a class="secondary" href="{relative(directory/"import-validation.json")}">GLB読み込み確認</a>')


warehouse_names = {"warehouse_oblique": ("倉庫全体", "波板屋根、12枚の天窓、レンガ腰壁、3つの搬入口"),
                   "loading_front": ("正面", "中央の搬入口を開き、両端には窓つきシャッターを配置"),
                   "roof_detail": ("屋根と天窓", "実際の開口にガラスを設け、波板の法線・粗さ・雨筋を反映"),
                   "loading_bay": ("搬入口と内部", "鋼製トラス、パレット、窓。中央搬入口の有効幅約4.45m"),
                   "wall_detail": ("外壁の質感", "縦波板、赤茶レンガの目地、窓枠、雨樋、職員扉")}
city_names = {"warehouse_street": ("街から見た倉庫", "北向きの搬入口と荷捌き場。西側歩道から職員扉へ通路を接続"),
              "warehouse_site": ("倉庫の配置", "道路から幅9mの車両入口。歩道の縁石を切り欠き、段差をスロープで接続"),
              "district_oblique": ("街全体", "既存320棟に倉庫1棟を追加。地下鉄用敷地を確保"),
              "district_plan": ("街の平面", "500m街区の道路、建物、倉庫敷地")}
wh_cards = "".join(card(Path(r["path"]), *warehouse_names[r["view"]]) for r in reports["warehouse"]["renders"])
city_cards = "".join(card(Path(r["path"]), *city_names[r["view"]]) for r in reports["city"]["renders"] if r["view"] in city_names)
city_cards += card(city/"density-plan.svg", "配置と動線の図", "青灰色＝倉庫、灰色＝荷捌き場、レンガ色＝歩行通路、点線の敷地＝地下鉄用")
wh = reports["warehouse"]["totals"]["triangles"]
ct = reports["city"]["totals"]["triangles"]
wh_mb, ct_mb = (directory.joinpath("model.glb").stat().st_size/1e6 for directory in (warehouse,city))
page = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>汐見物流倉庫と街への配置</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#edf2f3;color:#263740;font:15px/1.6 system-ui,"Yu Gothic",sans-serif}}main{{max-width:1500px;margin:auto;padding:32px}}h1{{font-size:34px;margin:8px 0}}h2{{font-size:24px;margin:36px 0 4px}}h3{{font-size:18px;margin:0}}p{{color:#5c6e77;margin:6px 0 12px}}.eyebrow{{font-size:12px;letter-spacing:.12em;color:#286774}}.facts{{padding:16px 22px;background:white;border:1px solid #cad8de;border-radius:10px;margin:20px 0}}.links{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 22px}}a{{color:#226a79}}.links a{{background:#286774;color:white;text-decoration:none;padding:9px 16px;border-radius:6px}}.links a.secondary{{background:white;color:#286774;border:1px solid #aebfc8}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:20px}}article{{background:white;border:1px solid #cad8de;border-radius:10px;overflow:hidden}}article img{{width:100%;aspect-ratio:1.6;object-fit:contain;display:block;background:#a1aeb7}}article div{{padding:14px 18px}}article p{{margin:4px 0 0;font-size:14px}}dialog{{border:0;border-radius:10px;padding:12px;max-width:96vw}}dialog::backdrop{{background:#000b}}dialog img{{max-width:92vw;max-height:82vh;display:block}}dialog .bar{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}button{{padding:7px 16px;border:1px solid #aebfc8;border-radius:6px;cursor:pointer}}footer{{margin:30px 0}}@media(max-width:600px){{main{{padding:18px}}h1{{font-size:27px}}.grid{{grid-template-columns:1fr}}}}</style></head><body><main>
<div class="eyebrow">PROMODELER / SHIOMI LOGISTICS</div><h1>汐見物流倉庫と街への配置</h1><p>提供されたWarehouseを外観参考に、形状とテクスチャをコードで生成しました。画像をクリックすると拡大できます。</p>
<div class="facts"><p><strong>25×26.5m、高さ8.55m</strong> · 波板切妻屋根／透明天窓12枚／レンガ腰壁／搬入口3か所。</p><p><strong>既存320棟＋倉庫1棟＝321棟</strong> · 北側に荷捌き場、西側に1.8m幅の歩行通路。地下鉄用の約29.4×52.7mの空き地を残しています。</p><p>両方のGLBをBlenderで再読み込み済み。PBR画像はGLBへ埋め込み、編集用.blendにも同梱しています。</p></div>
<h2>倉庫単体</h2><p>{wh:,}三角形 · GLB {wh_mb:.1f}MB · 設計寸法・天窓・搬入口・画像の埋め込みを確認。</p><div class="links">{links(warehouse)}</div><div class="grid">{wh_cards}</div>
<h2>街への配置</h2><p>{ct:,}三角形 · GLB {ct_mb:.1f}MB · 既存建物との干渉と地下鉄用敷地の確保を実GLBの座標で確認。</p><div class="links">{links(city)}<a class="secondary" href="{relative(city/'layout-validation.json')}">配置の検証</a><a class="secondary" href="{relative(city/'layout.json')}">配置の寸法と座標</a><a class="secondary" href="city.html">街の全画像</a></div><div class="grid">{city_cards}</div>
<div class="facts"><p>Blenderでは .blend を［ファイルを開く］、GLBは［ファイル → インポート → glTF 2.0］で読み込みます。</p><p>倉庫は固定形状です。開閉アニメーションとゲーム用コリジョン・LODは未設定。街全体は同時表示の目安200万三角形を超えるため、ゲーム利用時は区画ごとの表示制御が必要です。</p></div>
<footer><a href="provenance.json">制作元と検証記録</a> · <a href="../promodeler-rig-review-20260929/index.html">参考モデルとリグの確認</a></footer></main>
<dialog id="zoom"><div class="bar"><span></span><button>閉じる</button></div><img alt=""></dialog><script>const zoom=document.querySelector('#zoom');document.querySelectorAll('[data-caption]').forEach(a=>a.addEventListener('click',e=>{{e.preventDefault();zoom.querySelector('img').src=a.href;zoom.querySelector('img').alt=a.dataset.caption;zoom.querySelector('span').textContent=a.dataset.caption;zoom.showModal()}}));zoom.querySelector('button').onclick=()=>zoom.close();zoom.addEventListener('click',e=>{{if(e.target===zoom)zoom.close()}});</script></body></html>'''
(root/"index.html").write_text(page, encoding="utf-8")
print("WAREHOUSE_REVIEW", root/"index.html", "321 buildings", wh, "warehouse triangles")
