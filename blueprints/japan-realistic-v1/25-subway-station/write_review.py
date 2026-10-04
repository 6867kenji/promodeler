"""Package verified subway builds, photographs and the conventional gallery."""
import hashlib
import html
from html.parser import HTMLParser
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

root,city,station,entry,concourse,platform,gallery = [Path(a).resolve() for a in sys.argv[1:]]
project = Path(__file__).resolve().parents[3]
builds = [(city,'city','01-city','地下鉄を配置した町'),(station,'subwaystation','25-subway-station','入口からホームまでの統合駅'),
          (entry,'subway-entrance','17-subway-entrance','地下鉄入口'),(concourse,'subway-concourse','18-subway-concourse','B1 コンコース'),
          (platform,'subway-platform','19-subway-platform','B2 ホーム')]
labels = {'subway_street':'町の歩道から見た入口','subway_approach':'歩道から入口への接続',
          'station_section':'駅全体の断面','entrance_to_b1':'地上からB1へ','b1_connection':'入口とB1の接続',
          'gates_open':'開いた幅広改札','b1_to_b2':'B1からB2へ','platform_arrival':'ホームの到着通路',
          'walkthrough':'入口階段','escalator_close':'エスカレーター','glass_side':'入口の側面','stair_detail':'階段・手すり・壁タイル',
          'gate_full_width':'改札と両側の仕切り','staff_room':'ガラス張りの駅員室','floor_detail':'床タイルの質感',
          'tactile_detail':'点字ブロック','floor_entrance':'床と入口','floor_platform':'ホームの床','district_oblique':'町の全景'}
receipts = {}
for source,slug,design,title in builds:
    receipt = json.loads((source/'import-validation.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256((source/'model.glb').read_bytes()).hexdigest()
    assert receipt['status']=='ok' and receipt['blenderReimport'] and receipt['embeddedImages'] and receipt['sha256']==digest
    receipts[design] = receipt
    if design == '25-subway-station': assert receipt['access']['status']=='ok'

audit = json.loads((root.parent/'promodeler-rig-review-20260929/subway-passage.audit.json').read_text(encoding='utf-8'))
assert hashlib.sha256(Path(audit['source']).read_bytes()).hexdigest()==audit['sha256'], 'Reference source changed'
provenance = {'referenceSource':audit['source'],'sha256':audit['sha256'],'originalUnmodified':True,
              'method':'Reference appearance only. Generated geometry and BaseColor/Normal/Roughness maps.',
              'generatorFiles':{str(project/name):hashlib.sha256((project/name).read_bytes()).hexdigest() for name in
                ('assets/subway_details.py','assets/subway_station.py','assets/blueprint_spaces.py','assets/city_facilities.py','assets/city.py','promodeler/kernel/tiled.py')},
              'designFiles':{str(project/name):hashlib.sha256((project/name).read_bytes()).hexdigest() for name in
                ('blueprints/japan-realistic-v1/01-city/facility_layout.json','blueprints/japan-realistic-v1/subway-assembly.json')},
              'builds':{design: {'directory':str(source),'glbSha256':receipts[design]['sha256']} for source,slug,design,title in builds}}
(root/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')

style = '<style>body{margin:0;background:#111923;color:#edf2f8;font:16px/1.65 system-ui,"Yu Gothic",sans-serif}main{max-width:1400px;margin:auto;padding:36px}h1{font-size:32px}h2{margin-top:40px}p{color:#bbcad9}a{color:#8ad5ff}nav{display:flex;gap:22px;flex-wrap:wrap}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:20px}figure{margin:0;background:#1d2935;border-radius:12px;overflow:hidden}img{display:block;width:100%;height:260px;object-fit:contain;background:#303f4d}figcaption{padding:14px}.info{border:1px solid #44566a;padding:18px;border-radius:12px}a:hover{color:white}</style>'
def rel(path): return Path(path).relative_to(root).as_posix()
def nav(source):
    return '<nav>'+''.join(f'<a href="{html.escape(rel(source/name))}">{label}</a>' for name,label in
        (('model.blend','Blenderファイル'),('model.glb','GLB'),('report.json','生成検査'),('import-validation.json','読込検査')))+ '</nav>'
def photos(source, selected=None):
    report = json.loads((source/'report.json').read_text(encoding='utf-8'))
    renders = [r for r in report['renders'] if r.get('written')]
    if selected: renders = [r for name in selected for r in renders if r['view']==name]
    result = '<div class="grid">'
    for r in renders:
        link = html.escape(rel(r['path']))
        label = html.escape(labels.get(r['view'],r['view']))
        result += f'<figure><a href="{link}"><img src="{link}" loading="lazy" alt="{label}"></a><figcaption>{label}</figcaption></figure>'
    return result+'</div>'
def page(title,body): return f'<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{style}<main><h1>{title}</h1>{body}</main></html>'
body = '<p>SubwayPassageを参考に、階段・踊り場・手すり・配管とタイルの質感を整えました。町の専用敷地に入口を配置し、歩道・B1・B2ホームをつなぎました。</p>'
body += '<div class="info">建物321棟 + 地下鉄施設1か所。町では地上0.15m、B1 -5.85m、B2 -11.85m。<br>全5ファイルをBlenderへ再読み込み済み、テクスチャはGLBに内蔵。統合駅は幅広改札を開いた固定状態です。<br>階段と通路の床・頭上1.85m・改札を実メッシュで検査しました。ゲームの衝突設定とEVの昇降制御は別途実装が必要です。</div>'
body += '<p>GLBはBlenderの「ファイル → インポート → glTF 2.0」で読み込みます。「Blenderファイル」は通常の「開く」で確認できます。</p>'
body += f'<p>町全体のGLBは約{(city/"model.glb").stat().st_size/1024/1024:.0f}MBです。町の確認には、読み込み準備済みのBlenderファイルを利用できます。</p>'
body += f'<nav><a href="{rel(city/"density-plan.svg")}">町の配置図</a><a href="city.html">町の全画像</a><a href="provenance.json">参考モデルと生成記録</a></nav>'
selections = {'01-city':('subway_street','subway_approach'), '25-subway-station':None,
              '17-subway-entrance':('glass_side','escalator_close','stair_detail'),
              '18-subway-concourse':('gate_full_width','staff_room','tactile_detail'),
              '19-subway-platform':('walkthrough','floor_detail')}
for source,slug,design,title in builds:
    body += f'<h2>{title}</h2>'+nav(source)+f'<p><a href="{slug}.html">このモデルの全画像</a></p>'+photos(source,selections[design])
    report = json.loads((source/'report.json').read_text(encoding='utf-8'))
    detail = f'<p><a href="index.html">一覧へ戻る</a> · {len(report["parts"]):,}パーツ / {report["totals"]["triangles"]:,}三角形</p>'+nav(source)+photos(source)
    (root/(slug+'.html')).write_text(page(title,detail),encoding='utf-8')
(root/'index.html').write_text(page('汐見駅と町 — 接続・質感の更新',body),encoding='utf-8')
preview = root/'station-preview.html'
if preview.exists():
    preview.write_text(preview.read_text(encoding='utf-8').replace('町全体のモデルは更新・読み込み確認中です。',
        '<a href="index.html">町を含む最終一覧はこちら</a>'),encoding='utf-8')

for source,slug,design,title in builds:
    target = gallery/slug/source.name
    if not target.exists(): shutil.copytree(source,target)
    assert hashlib.sha256((target/'model.glb').read_bytes()).hexdigest()==receipts[design]['sha256']
    def relocate(value):
        if isinstance(value,str): return value.replace(str(source),str(target)).replace(source.as_posix(),target.as_posix())
        if isinstance(value,list): return [relocate(v) for v in value]
        if isinstance(value,dict): return {k:relocate(v) for k,v in value.items()}
        return value
    for name in ('report.json','import-validation.json'):
        path = target/name
        path.write_text(json.dumps(relocate(json.loads(path.read_text(encoding='utf-8'))),ensure_ascii=False,indent=2),encoding='utf-8')
    (gallery/'build-logs').mkdir(exist_ok=True)
    (gallery/'build-logs'/(design+'.txt')).write_text('out: '+str(target)+'\n',encoding='utf-8')
sys.path.insert(0,str(project))
from promodeler.gallery import create
entries = create(gallery)
class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        self.links.extend(value for key,value in attrs if key in ('href','src') and value)
count = 0
for directory in (root,gallery):
    for path in directory.glob('*.html'):
        parser = Links(); parser.feed(path.read_text(encoding='utf-8'))
        for value in parser.links:
            url=urlsplit(value)
            if not url.scheme and url.path:
                assert (path.parent/unquote(url.path)).is_file(), f'Missing link: {path} {value}'
                count+=1
result = {'status':'ok','review':str(root/'index.html'),'localLinksChecked':count,'galleryModels':len(entries),
          'verifiedGlbCopies':5,'referenceUnmodified':True,'builds':provenance['builds']}
(root/'delivery-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUBWAY_REVIEW_READY',str(root/'index.html'),'links',count,'gallery',len(entries))
