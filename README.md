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
| `Sweep(profile, path, scales, twist, capped)` | 穴なしプロファイルを 3D 折れ線に沿って回転最小フレームで掃引 |
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
`--pose` でポーズ付きの検証レンダができる。関節 ID とパーツ ID は書き出し先で同じノード名空間になるので別名にする。
`assets/desk_lamp.py`（剛体アタッチ）と `assets/tentacle.py`（スキン）を参照。

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
