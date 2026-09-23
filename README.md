# promodeler

コードから写実的な 3D モデルを決定的に生成するツールキット。
Python のソースコードがアセットの唯一の正であり、ヘッドレス Blender を
コンパイラのバックエンドとして使う。設計の背景は
[docs/01-realitizer-analysis-and-design.md](docs/01-realitizer-analysis-and-design.md)。

## 使い方

```sh
python -m promodeler doctor                    # Blender / Pillow / anthropic の検出
python -m promodeler new assets/lamp.py        # 雛形からアセットファイルを作る
python -m promodeler recipe assets/mug.py      # 検証してレシピ JSON を表示 (Blender 不要)
python -m promodeler build assets/mug.py       # 生成 + 数値 QA + ベイク + レンダ + glTF 書き出し
python -m promodeler build assets/rusty_can.py --texture-resolution 256 --bake-samples 4   # 反復用
python -m promodeler build assets/rusty_can.py --passes shaded,clay,wireframe --engine cycles  # 最終確認
python -m promodeler critique assets/rusty_can.py --reference photo.jpg --goal "錆びた缶"  # Claude による批評
python -m promodeler clean --keep 2            # 古いビルドを削除
```

出力は `build/<asset>/<asset-hash>/` に置かれる:

| ファイル | 内容 |
| --- | --- |
| `recipe.json` | kernel に渡した正規化レシピ |
| `report.json` | 数値 QA、UV、ベイク、レンダ、書き出し、失敗時は `error`。`critique.json` は批評結果 |
| `renders/<render-key>/` | 検証レンダと `contact_sheet.png`。レンダ設定ごとにサブフォルダ |
| `textures/*.png` | ベイク済み PBR テクスチャセット |
| `model.glb` | モディファイア適用済み、Y-up、ノード名 = パーツ ID、メッシュ名 = `mesh:<id>` |
| `blender.log` | Blender の標準出力 |

キャッシュ鍵は 2 段階。形状・マテリアル・品質のハッシュがディレクトリ名になり、レンダ設定（ビュー・パス・環境・エンジン）は
`renders/` のサブフォルダ名になる。レンダ設定だけを変えた再ビルドはベイク済みテクスチャを再利用する。`--force` で全て作り直す。

## エージェント向けの作業契約

`Skill/SKILL.md` に、編集 → `recipe` → `build` → `report.json` とコンタクトシートを読む → 編集、という反復手順と
API 早見表、無駄なビルドを避ける規則、検証と報告の契約をまとめている。Claude Code では `.claude/skills/promodeler/`
から自動で参照される。`promodeler critique` は `anthropic` パッケージと API 認証があるときに使え、
コンタクトシートと QA 要約（任意で参照写真）を Claude に渡して構造化された批評（点数、問題点、次の一手）を返す。

## アセットファイルの書き方

`assets/crate.py`（プリミティブと階層）、`assets/mug.py`（回転体 + スイープ + Union）、
`assets/wrench.py`（穴あき押出 + Bevel + 配列カッターの Difference）、`assets/rusty_can.py` /
`assets/leather_journal.py`（手続きマテリアルのベイク）を参照。
モジュールは `asset` に `AssetGenerator` か `Asset` を置く。任意で `render = RenderSettings(...)` を置ける。

- 座標系: メートル、右手系、**+Y が上**、+Z が手前 (glTF と同じ)。角度はラジアン。
- 色: sRGB 非乗算 + 線形アルファ。`alpha_mode="opaque"` のとき alpha < 1 は検証エラー。
- 範囲外の値は黙って丸めず `ModelingError(code, message)` を投げる。

### 形状

| 形状 | 内容 |
| --- | --- |
| `Box`, `Plane`, `Cylinder`, `Cone`, `Sphere` | 原点中心のプリミティブ。高さは局所 Y |
| `Extrude(profile, depth, axis)` | 穴あり 2D プロファイルを軸方向に押し出す。`axis="y"` で地面に描いた形を上へ押し出す |
| `Revolve(profile, segments, angle, cap_ends)` | (半径, 高さ) 列を Y 軸周りに回転。端点の半径 0 は極で閉じる。巻き方向は自動正規化 |
| `Sweep(profile, path, scales, twist, capped, up)` | 穴なしプロファイルを 3D 折れ線に沿って回転最小フレームで掃引。`up` は最初の断面の向きの基準（面法線を渡すと平たい断面が面に沿う） |
| `Strands(strands=(Sweep, ...))` | 多数の掃引をブーリアンなしで 1 メッシュに束ねる（髪の束、靴紐、ケーブル）。殻の重なりは前提なので自己交差チェックは省く（`report.parts.<id>.overlapping`） |
| `Loft(sections, capped)` | 同じ点数の断面（各断面は `LoftSection(points, transform)`）を張る |

`promodeler.core.curves` に `circle`, `regular_polygon`, `rect`, `rounded_rect`, `arc`, `bezier`,
`symmetric`, `join` などの点列ヘルパーがある。穴ありプロファイルのキャップは制約付きドロネー分割で
三角形化してから四角形へ結合する。

### モディファイア（順に適用）

| モディファイア | 内容 |
| --- | --- |
| `Bevel(width, segments, angle_limit)` | 角度しきい値を超える辺を丸める。幅はメートル |
| `Subdivision(levels, smooth)` | Catmull-Clark。`smooth=False` で滑らかにせず面を分割（変位用の密度追加） |
| `Displace(height)` | 頂点を法線方向にフィールド分（メートル）動かす。Geometry Nodes で評価。ノイズ・Voronoi・位置・向きと演算のみ使用可（曲率など光線追跡系は不可） |
| `SimpleDeform(method, angle, factor, axis)` | bend / twist（ラジアン）または taper |
| `Solidify(thickness, offset)` | 開いた面に厚みを付ける |
| `Mirror(axes, merge_distance)` | 局所平面でミラー。平面上に面がある閉じた形状には使わず、`curves.symmetric` で全輪郭を作る |
| `Array(count, offset)` | 定数オフセットで複製 |
| `Boolean(operation, cutter, solver)` | `Cutter(shape, transform, modifiers)` を相手に Exact CSG。カッターは書き出されない |

順序の指針: Bevel は輪郭の辺に対して行い、Boolean による溝や穴はその後に切る。
Boolean の後に Bevel を掛けると切り口の細かい面で幅が収まらず退化面が出る。
カッターの頂点が対象の面と同一平面に乗らないよう、半セグメント回転などでずらす。

### 不完全さ（M3）

`promodeler.core.imperfections` の `wobble`（大域的なゆがみ）、`dents`（まばらなへこみ）、`grain`（微細な粗さ）、
`ripples`（方向性のある波）は `Displace` に渡す高さフィールドを返す。均一すぎる CG 感を消すのに最も効く。
`assets/rusty_can.py` は壁の点列を細かくし `Subdivision(smooth=False)` を挟んでから `dents + wobble` で変形している。

### マテリアル（M2）

`Material` の各チャンネル（`base_color`, `roughness`, `metallic`, `emission_color`, `emission_strength`, `height`）は
定数か **フィールド** を取る。フィールドは表面上の関数で、3D オブジェクト座標で評価されるため UV の継ぎ目が出ない。

| フィールド | 内容 |
| --- | --- |
| `Noise(size, detail, roughness, seed)` | fBm ノイズ 0..1。`size` はメートル単位の特徴サイズ（タプルで異方性） |
| `Voronoi(size, feature, randomness, seed)` | セルノイズ。`f1` / `smooth_f1` / `distance_to_edge` |
| `Curvature(radius)` | 凸エッジのマスク。半径は幾何ベベル幅の約 3 倍にする |
| `Cavity(distance)`, `AmbientOcclusion(distance)`, `Thickness(distance)` | レイトレースによる凹み・遮蔽・薄さ |
| `Facing(direction)` | 法線と方向の内積（上向き面の埃など） |
| `Position(axis, start, end)` | 座標を 0..1 に正規化 |
| `Bricks(width, height, mortar, offset, axis)` | レンガ・タイル・床板の目地マスク（目地で 1）。`axis` はパターンを置く面の法線 |
| 演算 | `+ - * /`, `.pow()`, `.clamp()`, `.smoothstep(lo, hi)`, `.ramp(stops)`, `ColorRamp(field, stops)`, `.mix()` |

`layers=(Layer(base_color=..., roughness=..., height=..., mask=field), ...)` で下から順に合成する。
フィールドを含むマテリアルは凍結後に自動で UV 展開され、Cycles で基本色 / 粗さ / 金属 / 法線 / 発光を
`textures/<part>_<channel>.png` に焼く。レンダと glTF はその PBR テクスチャセットを使う。
`quality.texture_resolution`（既定 1024）と `quality.bake_samples`（既定 32）、CLI の
`--texture-resolution` / `--bake-samples` で品質を変えられる（反復時は 256 / 4 が速い）。

プリセット: `worn_leather(color, seed, wear, edge_radius)`, `rusty_iron(seed, rust, edge_radius)`,
`painted_metal(color, seed, wear, edge_radius)`, `brushed_metal(color, seed, edge_radius)`,
`old_wood(color, seed, weathering)`, `ceramic_glaze(color, seed, crazing)`, `concrete(color, seed, staining)`。
`assets/rusty_can.py` と `assets/leather_journal.py` を参照。

### リグとアニメーション（M5）

`Asset(rig=Rig(id, joints=(Joint(id, head, tail, parent), ...)), poses=(Pose(id, {joint: JointTransform(rotation, translation)}), ...),
clips=(Clip(id, duration, keyframes=(Keyframe(time, pose_id_or_None), ...), loop, interpolation), ...))`。
`Part(skinned=True)` は距離ベースの自動ウェイト（最大 4 影響）でリグに結合し、`Part(parent_joint="j")` は関節に剛体で追従する。
ポーズの回転は既定では各関節のローカル座標系（Y が head → tail、ロール依存）で指定する。検証ポーズには `JointTransform(..., space="world")` で作者座標系の軸（Z 回りで腕を横に上げる、X 回りで前後に振る）を使うと迷わない。クリップは NLA トラックとして glTF の
アニメーションに書き出され、ランタイムのステートマシンはエンジン側に任せる。`RenderSettings(pose=...)` または
`--pose` でポーズ付きの検証レンダができる。`RenderSettings(clip="walk", clip_fps=24)` または `--clip walk [--clip-fps 60]`
でクリップを各ビュー/カメラの動画にする（shaded のみ）。kernel は PNG 連番を書き、ホストが `ffmpeg` があれば H.264 mp4、
なければ Pillow でアニメーション WebP に符号化する（この環境の Blender は FFmpeg 出力を持たない）。
`report.renders[].video` に fps・フレーム数・エンコーダが入る。関節 ID とパーツ ID は書き出し先で同じノード名空間になるので別名にする。
`assets/desk_lamp.py`（剛体アタッチ）と `assets/tentacle.py`（スキン）を参照。

### 人体素体: Meta MHR（M6）

写実的な人体はプリミティブから手続き生成しない。素体は Meta の Momentum Human Rig
(MHR, Apache 2.0) を設計書の寸法にフィットさせて取り込み、衣服・髪・マテリアル・ポーズはコードで書く。

- `promodeler.human.mhr.fitted_body(targets)` が骨格スケール（背骨・首・肩幅・上腕・大腿・下腿・足首・足長）と
  体型係数 20 個を Adam で最適化し、身長・股下・肩幅・足長・頭高とバスト/アンダー/ウエスト/ヒップ周を
  微分可能な計測（水平断面の周長は腕を除いた胴体エッジで計算）で合わせる。結果は `build/human/<name>-<hash>/`
  に `body.npz`（頂点・三角形・UV・スキンウェイト）と `rig.json`（126 関節）として出力・キャッシュされる。
- アセット側は `Part(shape=MeshFile(path), skinned=True)` と `rig_from_file(path)` で読む。`MeshFile` は
  ファイルの sha256 をレシピに含めるので、フィットが変われば再ビルドされる。ウェイトがファイルにあれば
  距離ウェイトの代わりにそれを使う（MHR のツイストボーン込み）。
- ポーズ・クリップは MHR の関節名（`l_uparm`, `r_upleg`, `c_spine3`, `c_head` ...）で書く。休止姿勢は
  腕を 40° 下げた A ポーズ。
- 準備: `external/mhr/assets/` に MHR 配布物（`mhr_model.pt`, `lod1.fbx`, `compact_v6_1.model`）を置き、
  `blender -b --python tools/mhr_dump_lod1.py -- external/mhr` で FBX からトポロジ・ウェイト・ボーン階層を
  `cache/` に書き出す。`pip install torch numpy`（`pip install -e .[human]`）。Blender 側に torch は不要。
- `assets/haruka.py`（05-woman 設計書）が実例。設計値との差は身長 +2 mm、股下 +15 mm、肩幅（肩先の外幅）−6 mm、
  足長 0 mm、バスト +17 mm（幅 −1 mm・奥行 −18 mm）、ウエスト +4 mm、ヒップ −3 mm、アンダーバスト +20 mm。
  周長だけを合わせると MHR は胸を横に広げて平らな胸・広い肩になったので、肩幅は関節間距離ではなく肩先の断面幅
  (1.34 m) を目標にし、バストは幅・奥行きも目標に入れ、MHR の体型係数では出ない奥行きを幾何的な膨らみ
  （`bust_field`、約 3 cm）で補っている。ヒップの断面寸法は周長と両立しないため計測・報告のみ
  （`tools/blueprint_check.py`）。
- 素体以外は設計書からコードで作る: 実測した胴の断面に沿わせたワンピース（前下がりの U ネック、胸元中央
  120 mm に 12 本のギャザーを断面形状で作り、クロスで凍結）、頭蓋の楕円体に沿う `Strands` の髪束
  （前髪 13 束・顔周り 4 束・後ろ 3 層 64 束、毛先 0.66 m）、足の実測外形から作る白スニーカー
  （底 25 mm・アッパー・5 穴の靴紐、`parent_joint` で足関節に追従、身体は底の上に立つので靴込み 1.625 m）、
  頬・目の下・唇・鼻の位置マスク付きの肌、設計書の全クリップ（idle/walk/turn/sit/raise-arms/physics-settle）と
  可動域確認ポーズ `range_check`。`Camera("face"/"neckline"/"sneaker")` で設計書の QA 静止画を出す。
- 目: MHR LOD1 は瞼のある閉じた殻なので、目関節の位置に楕円体の `Boolean("difference")` で眼窩を開け、
  眼球パーツ（直径 24 mm、虹彩 11.5 mm、瞳孔 3.5 mm を `Position` マスクで描く）を `parent_joint="l_eye"` で
  載せる（視線ポーズ `gaze_left`）。ブーリアン後も `MeshFile` のウェイトは最近傍頂点で転写される。
- 手: 指関節をジョイント座標で丸めた `hands` を全ポーズにマージ（`rest` ポーズが休止姿勢）。
- 頭部: MHR 頭部係数 20 個を首・頭の断面幅/奥行きにフィット（胴の係数とは別ステージ。同時に最適化すると
  首を太くするために胴の周長が犠牲になった）。
- `Asset(extras={...})`: GLB に入らない納品物（設計書の physics ブロック、エンジン目標、フィット結果）を
  `extras.json` と glTF ルート extras (`promodeler_extras`) に書き出す。
- 設計書との照合: `python tools/blueprint_check.py blueprints/japan-realistic-v1/05-woman/blueprint.json` が
  最新ビルドの寸法・部位ボックス・三角形予算・警告を設計値と並べる。
- 髪の動力学ガイド（後ろ 8 本・左右 2 本ずつ・前髪 2 本、各 4–6 節）を束メッシュとは別に `extras.hair_guides` へ出す。
- 表情: MHR の表情パラメータ 72 個を頂点変位で探索し、瞬き（左右）、口開け、笑顔、横開き、すぼめ、母音 a/i/u/e/o を
  `promodeler.human.mhr.FACE_SHAPES` として定義。フィット済み素体で差分を計算し `body.npz` の `shape:<名前>` として
  書き出す。kernel は凍結後にシェイプキーとして付け（ブーリアン後は最近傍頂点で転写、面から 2 mm 以上離れた
  空洞頂点には付けない）、glTF のモーフターゲットになる。`Pose(shapes={"blink_l": 1.0})` で静止画（`--pose blink`）、
  クリップのキーフレームからモーフウェイトのアニメーションとして書き出す（idle の瞬き、`speak` の母音列）。
- クリップ動画: `python -m promodeler build assets/haruka.py --clip walk --views front,side --resolution 384`。
  歯（口は閉じている）、ランタイム物理そのもの、髪のカーブ書き出しは未着手。

### 人型キャラクター: CharacterRecipe（M9〜）

人型はもうコードで髪・服・靴を組み立てない。設計書（`blueprints/japan-realistic-v1/*/blueprint.json` の `kind: humanoid` / `wearable`）を
**Recipe JSON**（`character/recipes/<id>.json`, `character/outfits/<id>.json`、schema `promodeler-character/1.0`）へ変換し、
Unity + UMA のキャラクタークリエイター（M10 以降、`unity/ProModelerCharacterCreator/`）がそれを組み立てる。設計は
[docs/03-character-recipe-pipeline.md](docs/03-character-recipe-pipeline.md)。人型に限り **Recipe が正**（GUI 編集と往復するため）で、
`source` に設計書のパスと sha256 を残し `character diff` で再生成との差分を追う。

```sh
python -m promodeler generate blueprints/japan-realistic-v1/22-businessman/blueprint.json   # kind で振り分け（人型は Recipe 経路）
python -m promodeler character recipe <blueprint.json> [--force]      # 設計書 → Recipe（既存は上書きしない）
python -m promodeler character validate <id> [--mhr] [--strict]       # スキーマ・カタログ・ライセンス・寸法整合性。--mhr で MHR 参照フィット
python -m promodeler character check <id> [--build <dir>]             # 設計書目標 × Recipe × Unity build.json の照合表
python -m promodeler character diff <id>                              # Recipe と設計書再生成の差分
python -m promodeler character catalog list [--category wardrobe --slot upper --race human_male]
python -m promodeler character schema [--write]                       # dataclass から schemas/*.json を生成・照合
python -m promodeler character setup [--no-unity]                     # external/uma を Assets/UMA へ接続し、Unity 側の初期化（HDRP 取込・UMA 索引）
python -m promodeler character build <id> [--outfit <id>] [--views front,side] [--no-render]   # Unity + UMA バッチビルド → build/character/<id>/<hash>/build.json
python -m promodeler character build --all                            # 15 体を順にビルド（Unity はプロジェクトを排他ロックするため逐次）
python -m promodeler character build <id> --probe                     # 各パラメータを 0/1 にした計測差分 calibration.json（校正表）
python -m promodeler character report [--write docs/x.md]             # 最新ビルドの残差を 1 表に（mm、* は許容超え）
python -m promodeler character edit <id>                              # Unity の GUI エディタ（スライダー・プレビュー・Save は Recipe のみ）
```

装備品は `assets/props/*.py`（`promodeler.props` の部品で組む通常の Blender アセット）。Recipe の `accessories[].size_xyz_m` が
`size` を上書きして生成され、`extras.promodeler_socket` の把持点で Unity 側のソケットに装着される。

Unity 側は `unity/ProModelerCharacterCreator/`（Unity 6000.3.21f1、HDRP 17.3、UMA 3.05 を `external/uma` から接続）。エディタのライセンスが
有効でないと `build` は `unity.license` で失敗する。M10 の状況は docs/03 の 18.1 節。

- Recipe の身体寸法はメートルの絶対値（`body.measurements_m`、設計書と同じ語彙）。0..1 のスライダーは寸法のない項目だけ（`body.shape`, `face.shape`）。
- 髪・肌・衣服・靴はカタログ ID（`character/catalog/*.json`、Unity と共有）。現在の 65 項目は **すべてプレースホルダ**（中身なし）で、参照ごとに `catalog.placeholder` 警告が出る。
- `validate` は設計書内の矛盾を Unity 前に出す（05-woman のヒップ断面楕円 0.775 m vs 周長 0.87 m など）。`--mhr` は `promodeler.human.mhr` で参照フィットを取り `body.reference_fit` に残差を書く（torch 必須、初回約 40 s）。
- `assets/haruka.py` の Blender 人型経路は参照用に凍結。新しい人型 `.py` は書かない。装備品（鞄・眼鏡・時計）は従来どおり `assets/props/*.py` で作り、Recipe の `accessories[].source` から参照する。

### シェイプキー（M8）

`MeshFile` の npz に `shape_names` と `shape:<name>` [V, 3] の差分を入れると、パーツにシェイプキーが付き glTF の
モーフターゲット（`targetNames`）になる。`Pose(id, joints, shapes={name: 0...1})` はジョイントなしでもよく、
未指定のキーは 0 に戻る。クリップは各キーフレームで全シェイプ値もキーし、Key データブロックの NLA トラックとして
書き出す（`report.shape_keys` にパーツ別の名前一覧）。

### 散布・毛・クロス・LOD・USDZ（M5）

| 機能 | 内容 |
| --- | --- |
| `Scatter(surface, instance, density, seed, scale, min_distance, mask)` | 他パーツの表面にインスタンスを散布（法線に整列、ランダム回転・スケール）。`mask` は密度係数 |
| `Fur(surface, density, length, thickness, segments, sides, droop, curl, mask)` | 先細りの細い筒として毛を生やす。三角形数 = 本数 × segments × sides × 2 なので密度は控えめに |
| `ClothDrape(frames, mass, stiffness, bending, damping, pin, collide, thickness)` | クロスシミュレーションを `frames` フレーム進めて凍結。他パーツは衝突体になる。`pin` フィールドで固定 |
| `Part(lods=(LOD(distance, ratio), ...))` | デシメートした `<id>:lod<n>` ノードを親子付けして書き出す（`lod_distance` を extras に記録、レンダには出ない） |
| `ExportSettings(formats=("glb", "usdz"))` / `--formats glb,usdz` | glTF に加えて USDZ を書き出す |

散布・毛のパーツは自己交差と非マニフォールドの警告対象外（`report.parts.<id>.generated`）。
`report.stages` に工程別の秒数が入る。`assets/mossy_rock.py` と `assets/draped_cloth.py` を参照。

### 検証レンダ（M3）

`RenderSettings(views, passes, environment, engine)`:

| 項目 | 選択肢 |
| --- | --- |
| `views` | `perspective`, `front`, `back`, `side`, `top` |
| `passes` | `shaded`（ベイク済みマテリアル）, `clay`（無彩色の粘土）, `wireframe`（粘土 + 辺）, `normals`（ワールド法線）, `uv`（チェッカー） |
| `environment` | `studio`（勾配環境 + エリアライト）, `overcast`, `sunny` / `sunset`（物理空 + 太陽）, または `.hdr` / `.exr` のパス |
| `pose` | リグのポーズ ID。指定時はクリップを無効にしてそのポーズで描く |
| `cameras` | `Camera(id, position, target, fov, orthographic, ortho_scale, clip_start, hide_parts)`。任意位置のカメラ。正投影カメラを断面位置に置き `clip_start` を小さくすると断面図になる。`hide_parts` で天井などをそのカメラだけ外す |
| `lights` | `Light(id, position, energy, size)`。室内検証用の下向きエリアライト（W） |
| `engine` | `eevee`（反復用）, `cycles`（最終確認。CPU、デノイズあり） |

パス × ビューの全レンダを `renders/contact_sheet.png` に並べる（ホスト側、Pillow がある場合）。
CLI では `--views`, `--passes`, `--environment`, `--engine` で上書きできる。
環境は手続き的に生成するのでビルドは自己完結し、HDRI ファイルは任意で指定する。

## 数値 QA (`report.json` の `parts.<id>`)

`vertices`, `faces`, `triangles`, `non_manifold_edges`, `boundary_edges`, `loose_vertices`,
`inconsistent_winding_edges`, `degenerate_faces`, `watertight`, `volume`（符号付き。負なら裏返り）,
`self_intersections`（頂点を共有しない三角形対の交差数）。ベイクしたパーツには `uv`（アトラス使用率、テクセル密度）と
`textures`（チャンネル別のパス・解像度・所要秒）が付く。問題は `warnings` にコード付きで並ぶ。
レンダが出たことは正しさの証明ではない。数値 QA と目視を分けて判断する。

## テスト

```sh
python -m unittest discover -s tests -v
```

`tests/test_build.py` は実際に Blender を起動する。`PROMODELER_SKIP_BLENDER=1` でスキップ。

## 環境

- Python 3.13 以上 (core は標準ライブラリのみ)。kernel は Blender 同梱 Python で動く。
- Blender 4.2 以上を想定、5.1.2 で確認。`PROMODELER_BLENDER` で実行ファイルを指定できる。
