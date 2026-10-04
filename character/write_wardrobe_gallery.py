"""Write a local gallery from verified wardrobe exports: -- OUTPUT_ROOT."""

import html
import json
import sys
from pathlib import Path


root = Path(sys.argv[1]).resolve()
catalog = json.loads((Path(__file__).parent / "wardrobe_catalog.json").read_text(encoding="utf-8"))
records = {item["id"]: item for item in json.loads((root / "validation.json").read_text(encoding="utf-8"))}
looks = [
    ("shared-amber-woman", "レザージャケット × ジーンズ", "Amberの4部品を共通素体に装着", "common"),
    ("shared-amber-casual-woman", "Tシャツ × ジーンズ", "ジャケットを外した組み合わせ", "common"),
    ("shared-blouse-jeans-woman", "ブラウス × ジーンズ", "異なる元モデルの衣装を組み合わせ", "common"),
    ("shared-megane-uniform-woman", "Méganeの制服", "上下セットを共通素体に装着", "common"),
    ("shared-female-casual-woman", "ジャケット × カーゴパンツ", "全身衣装を3部品に分離して装着", "common"),
    ("female-outfit-ponytail-woman", "全身衣装・フィット調整", "袖・胸・パンツを素体に合わせて調整", "common"),
    ("blouse-ponytail-woman", "ブラウス・フィット調整", "袖と胸周りを調整したv4の衣装", "common"),
    ("amber-wardrobe", "Amber", "Tシャツ・ジーンズ・ブーツ・レザージャケット", "native"),
    ("matt-wardrobe", "Matt", "シャツ・ジーンズ・キャンバスシューズ", "native"),
    ("megane-wardrobe", "Mégane", "制服上下セット・ハイヒール", "native"),
    ("cute-girl-wardrobe", "Cute Girl", "シャツ・ジーンズ", "native"),
    ("rainy-wardrobe", "Rainy", "シャツ・パンツ・ブーツ", "native"),
    ("cute-girl-free-wardrobe", "Cute Girl free", "シャツ・パンツ・靴とソックス・恐竜フード", "native"),
]


def relative(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return html.escape(path.relative_to(root).as_posix(), quote=True)


cards = []
for asset_id, title, detail, kind in looks:
    record = records[asset_id]
    source = Path(record["glb"])
    preview = relative(source.parent / "preview.png")
    badge = f"リグあり · {record['bones']}ボーン" if record["bones"] else "固定ポーズ · リグなし"
    cards.append(f'''<article class="card" data-kind="{kind}">
      <button class="image-button" data-image="{preview}" data-title="{html.escape(title, quote=True)}" aria-label="{html.escape(title)}を拡大">
        <img src="{preview}" alt="{html.escape(title)}" loading="lazy"></button>
      <div class="card-body"><span class="badge">{badge}</span><h3>{html.escape(title)}</h3>
        <p>{html.escape(detail)}</p><code>{asset_id}</code>
        <div class="links"><a href="{relative(source)}" download>GLBを保存</a>
        <a href="{relative(source.parent / 'recipe.json')}">レシピ</a></div></div></article>''')

poses = []
for directory, title in [("female-outfit", "全身衣装"), ("shared-amber", "Amberの衣装"), ("shared-blouse-jeans", "ブラウス＋ジーンズ")]:
    for pose_id, pose_title in [("arms-raised", "腕上げ"), ("bent-knee", "膝曲げ")]:
        src = relative(root / "poses" / directory / (pose_id + ".png"))
        label = title + " · " + pose_title
        poses.append(f'<figure><button class="image-button" data-image="{src}" data-title="{label}" aria-label="{label}を拡大"><img src="{src}" alt="{label}" loading="lazy"></button><figcaption>{label}</figcaption></figure>')

rows = []
for item in catalog["items"]:
    bases = "、".join(item["compatibleBases"])
    rows.append(f'<tr><td>{html.escape(item.get("name", item["id"]))}<br><code>{item["id"]}</code></td><td>{html.escape(item["slot"])}</td><td>{html.escape(bases)}</td></tr>')

page = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>衣装・共通素体の画像一覧 | ProModeler</title><style>
:root{color-scheme:light;--ink:#1d2937;--muted:#647183;--line:#dbe1e7;--accent:#1c5968}
*{box-sizing:border-box}body{margin:0;background:#f4f6f7;color:var(--ink);font:15px/1.65 system-ui,"Yu Gothic",sans-serif}
header,main{max-width:1440px;margin:auto;padding:32px}header{padding-top:50px;padding-bottom:12px}
.eyebrow{font-size:12px;letter-spacing:.16em;color:var(--accent);font-weight:700}h1{font-size:clamp(28px,4vw,42px);margin:8px 0}h2{font-size:25px;margin:0 0 14px}h3{font-size:18px;margin:10px 0 4px}
.lead{color:var(--muted);max-width:850px}.stats{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.stats span{background:white;border:1px solid var(--line);padding:10px 18px;border-radius:10px}.stats b{font-size:22px;margin-right:6px}
nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px}nav button{border:1px solid var(--line);border-radius:24px;padding:9px 20px;background:white;color:var(--ink);cursor:pointer}nav button[aria-pressed=true]{background:var(--accent);color:white;border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:20px}.card{background:white;border:1px solid var(--line);border-radius:14px;overflow:hidden}.card[hidden]{display:none}
.image-button{display:block;padding:0;border:0;width:100%;background:#4f4f4f;cursor:zoom-in}.image-button img{display:block;width:100%;aspect-ratio:2/3;object-fit:contain}.card-body{padding:18px}.badge{font-size:11px;color:var(--accent);background:#e8f2f2;padding:4px 8px;border-radius:5px}.card p{color:var(--muted);font-size:13px;margin:0 0 10px;min-height:42px}code{font-size:11px;word-break:break-all}.links{display:flex;gap:18px;margin-top:14px}a{color:var(--accent);text-underline-offset:3px}
section{margin-bottom:46px}.note{padding:16px 20px;background:#e9eff2;border-radius:10px;color:#455969;margin:18px 0}.pose-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}figure{margin:0;background:white;border:1px solid var(--line);border-radius:10px;overflow:hidden}figcaption{padding:12px;font-size:13px}
details{background:white;border:1px solid var(--line);border-radius:10px;padding:18px}summary{cursor:pointer;font-weight:600}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin-top:18px}th,td{padding:12px;text-align:left;border-bottom:1px solid var(--line)}th{color:var(--muted)}
dialog{padding:14px;border:0;border-radius:12px;max-width:94vw;background:#f4f6f7}dialog::backdrop{background:#111b}dialog img{display:block;max-width:86vw;max-height:80vh;object-fit:contain}dialog .bar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:10px}dialog button{padding:6px 12px;cursor:pointer;border:1px solid var(--line);border-radius:5px;background:white}footer{font-size:12px;color:var(--muted);margin-top:28px}
@media(max-width:600px){header,main{padding:20px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card-body{padding:12px}h3{font-size:15px}.links{gap:10px;font-size:12px}}
</style></head><body><header><div class="eyebrow">PROMODELER / WARDROBE</div><h1>衣装と共通素体の画像一覧</h1>
<p class="lead">元のキャラクターが着用していた衣装と、共通素体に合わせた組み合わせです。画像をクリックして拡大し、GLBを保存してBlenderで確認できます。</p>
<div class="stats"><span><b>17</b>元モデルの衣装</span><span><b>5</b>共通素体に移した衣装</span><span><b>3</b>全身衣装から分離した部品</span><span><b>13</b>確認用モデル</span></div></header>
<main><section aria-label="衣装モデル"><nav aria-label="表示するモデル"><button data-filter="all" aria-pressed="true">すべて</button><button data-filter="common" aria-pressed="false">共通素体</button><button data-filter="native" aria-pressed="false">元キャラクター</button></nav>
<div class="grid">__CARDS__</div><p class="note">衣装ごとに使える素体が異なります。Cute Girl free版は固定ポーズです。すべてのGLBでBlenderへの再読み込みと画像の埋め込みを確認しました。</p></section>
<section><h2>動かしたときの確認</h2><p class="lead">GLBを読み込んで腕と膝のボーンを動かした画像です。衣装の追従と肌の突き抜けを確認しています。</p><div class="pose-grid">__POSES__</div></section>
<section><details><summary>登録した衣装と対応する素体を見る</summary><div class="table-wrap"><table><thead><tr><th>衣装</th><th>スロット</th><th>対応する素体</th></tr></thead><tbody>__ROWS__</tbody></table></div></details></section>
<footer><a href="validation.json">GLB確認結果</a> · <a href="../promodeler-new-reference/index.html">衣装・髪型・建築物の参考一覧</a></footer></main>
<dialog id="zoom"><div class="bar"><span id="zoom-title"></span><button id="close">閉じる</button></div><img id="zoom-image" alt=""></dialog>
<script>
const zoom=document.querySelector('#zoom');
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
document.querySelectorAll('[data-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
document.querySelectorAll('.card').forEach(card=>card.hidden=button.dataset.filter!=='all'&&card.dataset.kind!==button.dataset.filter);
}));
document.querySelectorAll('[data-image]').forEach(button=>button.addEventListener('click',()=>{
document.querySelector('#zoom-image').src=button.dataset.image;document.querySelector('#zoom-image').alt=button.dataset.title;
document.querySelector('#zoom-title').textContent=button.dataset.title;zoom.showModal();
}));document.querySelector('#close').addEventListener('click',()=>zoom.close());
zoom.addEventListener('click',event=>{if(event.target===zoom)zoom.close();});
</script></body></html>'''
page = page.replace("__CARDS__", "\n".join(cards)).replace("__POSES__", "\n".join(poses)).replace("__ROWS__", "\n".join(rows))
(root / "index.html").write_text(page, encoding="utf-8")
print("WARDROBE_GALLERY", root / "index.html", len(cards), "models", len(poses), "poses")
