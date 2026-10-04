# Canonical Base モード

人型には二つのビルド経路がある。既定の `uma` は従来の `promodeler-character/1.0` Recipe を Unity + UMA で組み立てる。`canonical` は作者が用意した GLB、Blend または FBX を素体とし、`promodeler-canonical-character/2.0` Recipe を Blender で適用する。既存のRecipe、カタログ、Unityプロジェクトは変更しない。

```powershell
# 従来どおり（--mode uma は省略可能）
python -m promodeler character recipe blueprints/japan-realistic-v1/05-woman/blueprint.json
python -m promodeler character build woman

# 設計書から新しい意味パラメータのRecipeを作る
python -m promodeler character recipe blueprints/japan-realistic-v1/05-woman/blueprint.json --mode canonical --base SemiRealBase_Female_v1
python -m promodeler character validate woman --mode canonical --base-manifest character/bases/SemiRealBase_Female_v1/manifest.json
python -m promodeler character build woman --mode canonical --base-manifest character/bases/SemiRealBase_Female_v1/manifest.json --strict-base
# 既存のkind別ルータからもモードを選べる
python -m promodeler generate blueprints/japan-realistic-v1/05-woman/blueprint.json --mode canonical --no-build
python -m promodeler character random --mode canonical --count 10 --out build/canonical-random
python -m promodeler character prompt "20代の女性、黒髪ボブ" --mode canonical --out build/canonical-prompt.json
```

新しいRecipeは `character/canonical_recipes/<id>.json` に保存する。ビルド結果は `build/character/canonical/<id>/<hash>/` に置き、`recipe.json`、`manifest.json`、`model.glb`、`build.json`、`preview.png` を含む。`--no-render` はプレビューだけを省く。`--strict-base` は素体に割り当てられていないパラメータや部品IDをエラーにする。通常のビルドはそれらを `build.json.unresolved` と標準出力に警告として残す。

## Canonical Base の登録

参照モデルの例として `character/references/blue-hiar-girl.json` に `blue-hiar-girl.glb` の所在、SHA-256、検査結果を記録している。このGLBは1メッシュ・約104万頂点で、skin・ボーン・アニメーション・ShapeKeyがない。したがって外観と形状の参考には使えるが、そのままRecipeで変形するCanonical Baseとしては登録しない。ベースに利用するには、共通トポロジーの素体を制作し、リグ・ウェイト・ShapeKeyを追加してからmanifestに対応付ける。参照元のライセンスは未確認である。

素体そのものはユーザーが制作・選定する。各ベースの `manifest.json` で、Recipeの意味パラメータを、実際に存在するShapeKey・ボーン・メッシュ・マテリアルへ対応付ける。`model` はmanifestからの相対パスまたは絶対パスで指定できる。`id` はRecipeの `base` と一致させる。

```powershell
python -m promodeler character inspect-base C:/path/to/base.glb --out character/bases/SemiRealBase_Female_v1/inventory.json
```

この一覧でShapeKey・ボーン・マテリアルの実名を確認してからmanifestを記述する。

### 登録済みのリグ付き女性素体

`character/bases/RiggedWoman_v1/manifest.json` は、ローカルの `3d/キャラクター/Base_woman_Blender/Blender/blender.Fbx` を参照する。`character/canonical_recipes/rigged-woman-smoke.json` で書き出しを確認できる。

```powershell
python -m promodeler character build rigged-woman-smoke --mode canonical --strict-base
```

元FBXには初期アニメーションの片脚を上げたポーズが付いているため、CanonicalビルドではFBXのアニメーションとShapeKey値を解除してバインドポーズから開始する。GLBにはリグ、ShapeKey、画像テクスチャを含める。肩幅・腕長・脚長のみボーンへ割り当てた初期段階であり、顔形状のスライダーに適したShapeKey、髪型・衣装モジュールはまだない。元FBXのShapeKeyは主に表情用なので、顔の比率変更には流用しない。外部テクスチャを変更した場合は `--force` で再ビルドする。

### 青銀髪と顔形状の試作ベース

`character/bases/RiggedWoman_v2/prepare_base.py` は上記FBXを読み、元のリグと画像テクスチャを保ちながら、頭ボーンに追従する青銀髪の独立メッシュと顔比率用ShapeKeyを加える。顔の丸さ、顎幅、目の大きさ、鼻の大きさ、頬のボリュームをRecipeに対応付けた。`RiggedWoman_v1` とUMAモードは引き続き利用できる。

```powershell
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' -b --factory-startup --python character/bases/RiggedWoman_v2/prepare_base.py -- `
  C:/Users/kuwano/develop/3d/キャラクター/Base_woman_Blender/Blender/blender.Fbx `
  C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-rigged-woman/base/RiggedWoman_v2.blend
python -m promodeler character build blue-silver-woman --mode canonical --strict-base
```

準備済みBlendはローカルの `OneDrive/画像/モデル生成/promodeler-rigged-woman/base/` に置き、`RiggedWoman_v2/manifest.json` がそこを参照する。青髪GLBは見た目の参考として使用し、メッシュやリグは取り込まない。v2の髪は交換可能な1モジュールで、未選択なら書き出しから除外する。髪は造形と色の試作であり、参照モデルの衣装はまだ再現していない。元素体が写実寄りなので、顔もセミリアルな範囲で調整する。

```json
{
  "id": "SemiRealBase_Female_v1",
  "model": "SemiRealBase_Female_v1.blend",
  "parameters": {
    "face.eyeSize": {
      "shapeKeys": [
        {"name": "Eye_Large", "side": "positive"},
        {"name": "Eye_Small", "side": "negative"}
      ]
    },
    "body.legLength": {
      "bones": [{"name": "UpperLeg_L", "axis": "Y", "scale": [0.9, 1.1]},
                {"name": "UpperLeg_R", "axis": "Y", "scale": [0.9, 1.1]}]
    }
  },
  "modules": {
    "appearance.hairStyle": {
      "hair_bob_003": ["Hair_Bob_003"],
      "hair_long_001": ["Hair_Long_001"]
    },
    "wardrobe.top": {"top_casual_013": ["Top_Casual_013"]},
    "wardrobe.bottom": {"bottom_skirt_007": ["Skirt_007"]},
    "wardrobe.shoes": {"shoes_shortboots_003": ["Boot_L", "Boot_R"]},
    "wardrobe.dress": {"dress_casual_001": ["Dress_Casual_001"]}
  },
  "accessories": {"watch_001": ["Watch_001"]},
  "bodyMasks": {
    "wardrobe.top": {"top_casual_013": ["Body_Torso_Under_Top"]}
  },
  "materials": {
    "skin": ["Skin"], "hair": ["Hair"],
    "eyes": ["Iris"], "lips": ["Lips"]
  }
}
```

ShapeKeyの中立値は `0.5`。`positive` は `0.5→1`、`negative` は `0.5→0` をそれぞれ `0→1` のShapeKey値へ変換する。骨の `scale` はRecipe値 `0→1` に対する両端のローカル軸倍率。モジュールは素体内の同じリグに合わせて制作したメッシュで、未選択候補をGLBから除外する。`bodyMasks` は衣服の下で隠す専用の身体オブジェクトを指定する。服の体型追従は素体側のShapeKey・メッシュ設計が必要。

GLB出力はBlenderのglTFエクスポータを使い、ShapeKeyと材質を含む。ベースの色テクスチャが接続されていれば、模様を残してRecipeの色へ寄せる。新モードの仕上がりはCanonical Baseの品質に依存する。AI生成GLBから自動で共通トポロジー、リグ、衣服互換性を作る工程はここには含まれない。`skinPreset` と `eyePreset` はまだ形状へ適用されず、未解決として表示する。Unityの既存GUIとバッチビルドは現在UMAモード用であり、CanonicalモードはCLIとBlenderビルドで利用する。

## 固定ポーズのKnight Recipe

`character/canonical_recipes/knight-female.json` は `character/bases/Knight_Static_v1/manifest.json` を参照する。元の `female knight 5.0.blend` はボーンもShapeKeyも持たないため、固定ポーズのキャラクターとして登録した。髪、兜、盾、剣は別メッシュで、Recipeから選択できる。地面、ドーム、頭蓋骨の小道具は `excludeObjects` で出力から除く。

```powershell
python -m promodeler character build knight-female --mode canonical --strict-base
```

このmanifestの `textureMaxSize: 4096` は、出力時だけ使用中の画像を最大4,096 pxに縮小する。元のBlendとテクスチャは変更しない。GLBには画像を埋め込み、Blenderで再読み込みできる。固定ポーズのため、顔・体型のスライダーやアニメーションには対応しない。

## 衣装付き女性ベース

`RiggedWoman_v3` はv2の素体とリグを残し、`3d/服装` の4種類を交換可能な衣装として追加する。元データは変更せず、`character/bases/RiggedWoman_v3/prepare_outfits.py` が縮尺・座標軸・画像パスを揃えて、素体から衣装へボーンウェイトを転写する。中世風衣装のFBXには画像の接続がなかったため、付属のBaseColor、Normal、Roughness、Metallicを接続する。準備済みBlendは `OneDrive/画像/モデル生成/promodeler-clothing/base/RiggedWoman_v3.blend` に保存する。

| Recipe | 衣装スロット | 元データ |
| --- | --- | --- |
| `sports-bra-woman` | `wardrobe.top = sports_bra` | `SportsBRA/BLENDER/AFJ00004.blend` |
| `medieval-thin-woman` | `wardrobe.dress = medieval_thin` | `medieval-girl-outfit/fbx-thin.fbx` |
| `medieval-thick-woman` | `wardrobe.dress = medieval_thick` | `medieval-girl-outfit/fbx-thick.fbx` |
| `lingerie-woman` | `wardrobe.dress = lingerie_set` | `Lingerie-skc-02_obj/Lingerie-skc-02_obj.obj` |

```powershell
python -m promodeler character build medieval-thin-woman --mode canonical --strict-base
python -m promodeler character build lingerie-woman --mode canonical --strict-base
```

4種類とも衣装メッシュが元の104ボーンのリグに追従する。`body.chest` は衣装とのフィット用ShapeKeyへ対応付け、中世風衣装は `0.25`、ランジェリーは `0.0` を指定する。選択していない衣装はGLBから除外し、衣装の下にある元のブラと下着は必要に応じて除外する。転写ウェイトとフィット用ShapeKeyは静止ポーズで調整した初期値であり、大きな動作には追加のウェイト修正が必要になる場合がある。

## 追加キャラクター7件

### 2026-09-29: 新しい骨入りモデルの検査

`character/references/rigged-candidates-20260929.json` にKnight、Ayane、Cute Girl free版の骨入りBlendを検査候補として記録した。生成Rigifyリグは918/919/918ボーンを持ち、それぞれ変形用ボーンは171本だが、3件とも `body` の変形ウェイトは0頂点だった。rootコントロールを動かしても身体は追従せず、通常の自動ウェイト再試行では3件ともBone Heatが失敗した。

Knightの鎧・付属品とCute Girl free版の衣装などはアーマチュアへの接続もない。Ayaneでは腕・目などの一部は追従する。これらはウェイトと接続の修復後に動作を検証する必要があり、稼働するRigged Baseとしては未登録である。既存の静的ベースが参照している旧Blendも現在のフォルダーで見つからないため、修復時には参照先を更新する。

`character inspect-base` は `weightedVertices`、`weightCoverage`、`bindingStatus`、`bindingIssues` を出力する。アーマチュアモディファイアが存在するという従来の `skinned` 判定だけでは、実際にメッシュが動くことを保証できない。`complete` は全頂点への変形ウェイト割当を意味し、関節の変形品質は別途確認する。エンベロープ方式は `envelope_binding` として区別する。

`3d/キャラクター` に置かれたモデルを、外見を保持した個別のCanonical BaseとRecipeとして登録した。Recipe IDは次のとおり。

| Recipe ID | ベース | リグ | 元モデル |
| --- | --- | --- | --- |
| `amber` | `Amber_Rigged_v1` | 101ボーン | `Amber/Amber.Fbx` |
| `ayane` | `Ayane_Static_v1` | なし | `Ayane/Ayane 4.5+.blend` |
| `cute-girl` | `CuteGirl_Rigged_v1` | 559ボーン | `cute girl/cute girl 5.0.blend` |
| `cute-girl-free` | `CuteGirl_Free_Static_v1` | なし | `Cute+Girl+freeversion/Cute girl 5.2.blend` |
| `matt` | `Matt_Rigged_v1` | 101ボーン | `Matt/Matt.Fbx` |
| `megane` | `Megane_Rigged_v1` | 101ボーン | `Mégane/Mégane_Blender.Fbx` |
| `rainy` | `Rainy_Rigged_v1` | 559ボーン | `Rainy/Rainny 5.0.blend` |

```powershell
python -m promodeler character build amber --mode canonical --strict-base
python -m promodeler character build rainy --mode canonical --strict-base
```

`cute-girl` と `rainy` は `character/prepare_imported_character.py` でBlender操作用の制御メッシュを除外したBlendを作り、`OneDrive/画像/モデル生成/promodeler-new-characters/base/` に保存する。Rainyに欠けていた歯の画像4枚は、同じモデル系統の `Cute+Girl+freeversion/textures/` の画像へ接続する。元のBlendは変更しない。

AmberとMattは非常に高密度のメッシュに多数の表情ShapeKeyが付いている。確認用GLBのサイズと書き出しメモリを抑えるため、manifestの `exportMorphs: false` で表情ShapeKeyのGLB出力を省く。元FBXには残る。顔形状スライダーは、これらの表情ShapeKeyを顔比率用ShapeKeyとして誤用しないため未割当。Amber、Matt、Méganeは肩幅・腕長・脚長を骨に割り当てている。固定モデルのAyaneとCute Girl free版にはポーズ・体型変更を適用できない。

## 追加衣装・髪型: RiggedWoman_v4

`RiggedWoman_v4` は v3 を残したまま、ユーザー提供のブラウス、全身衣装、ヘアバンド型の髪、ポニーテールを追加したベースです。新規モデルは `character/bases/RiggedWoman_v4/prepare_modules.py` で再生成できます。元のアセットや v3 のベースは変更しません。

レシピでは `base` に `RiggedWoman_v4` を指定し、次の値を選択できます。

| パス | 値 | 元アセット |
|---|---|---|
| `wardrobe.top` | `blouse_a` | `3d/服装/BlouseA/BlouseA.blend` |
| `wardrobe.dress` | `female_outfit` | `3d/服装/FemaleOutfit/Free fbx.fbx` |
| `appearance.hairStyle` | `hair_headband_black` | `3d/髪型/ヘアバンド/Fbx/Mesh.fbx` |
| `appearance.hairStyle` | `hair_ponytail_brown` | `3d/髪型/女性ポニーテール/hair.fbx` |

服のウェイトは RiggedWoman の素体から転写し、髪は頭ボーンに結びます。衣装の袖は素体の A ポーズに合わせて補正しています。例は `blouse-headband-woman.json` と `female-outfit-ponytail-woman.json` です。各枠は同じ v4 ベース上で独立に選択できるため、レシピの値を入れ替えて組み合わせられます。

袖とパンツは `character/garment_fit.py` で素体の断面に合わせて調整しました。生地のしわとUVを保持し、胸周りの標準値は `body.chest: 0.25` としています。服に覆われる身体の面を除外することで、肌の突き抜けを抑えます。全身衣装とブラウスは、GLBを再読み込みした後の腕上げ・膝曲げポーズでも確認しました。

## サンプルキャラクターの衣装を再利用する

`character/wardrobe_sources.json` が元モデルの部品と衣装IDを定義し、`character/register_native_wardrobe.py` が追加のv2ベースとレシピを登録します。元のv1ベースとレシピはそのまま使えます。次の6体から17種類を登録しました。

| Recipe | 衣装 | 対応する素体 |
| --- | --- | --- |
| `amber-wardrobe` | クロップTシャツ、ジーンズ、ブーツ、レザージャケット | `Amber_Wardrobe_v2` |
| `matt-wardrobe` | シャツ、ジーンズ、シューズ | `Matt_Wardrobe_v2` |
| `megane-wardrobe` | 制服上下セット、ハイヒール | `Megane_Wardrobe_v2` |
| `cute-girl-wardrobe` | シャツ、ジーンズ | `CuteGirl_Wardrobe_v2` |
| `cute-girl-free-wardrobe` | シャツ、パンツ、靴・ソックス | `CuteGirl_Free_Wardrobe_v2`（固定ポーズ） |
| `rainy-wardrobe` | シャツ、パンツ、ブーツ | `Rainy_Wardrobe_v2` |

衣装の元テクスチャとリグを保持します。Cute Girl free版の恐竜フードはアクセサリーとして選択できます。AmberとMattのv2は、検証済みGLBをベースにすることで、高密度の身体と多数の表情ShapeKeyの再変換を避けます。

### 共通素体: RiggedWoman_v5

`RiggedWoman_v5` はv4の衣装・髪型を継承します。さらにAmberの4種類とMéganeの制服を、同じ名前の骨のバインド座標を使って共通素体へ合わせました。全身衣装のタンクトップ、カーゴパンツ、ジャケットは別々の部品として選択できます。

| Recipe | 組み合わせ |
| --- | --- |
| `shared-amber-woman` | AmberのTシャツ、ジーンズ、ブーツ、レザージャケット |
| `shared-amber-casual-woman` | 上記のジャケットなし |
| `shared-megane-uniform-woman` | Méganeの制服 |
| `shared-female-casual-woman` | タンクトップ、カーゴパンツ、ジャケット |
| `shared-blouse-jeans-woman` | ブラウス、Amberのジーンズ、ブーツ |

```powershell
python -m promodeler character build amber-wardrobe --mode canonical --strict-base
python -m promodeler character build shared-blouse-jeans-woman --mode canonical --strict-base
```

準備済みの共通素体は `OneDrive/画像/モデル生成/promodeler-wardrobe/base/RiggedWoman_v5.blend`、衣装の対応表は `character/wardrobe_catalog.json` です。`compatibleBases` に記載された素体で使用します。他の素体への転用は、形状とボーンウェイトの調整が必要です。登録処理を再実行する場合は、nativeの登録後に `register_shared_wardrobe.py` で共通素体の対応を追加します。

Ayaneの衣装には肌や手足が含まれます。FantasyGirlとWhiteWeddingDressGirlは人体・衣装・髪が統合されています。これらの衣装分離と、リグのないKnightの鎧へのボーン設定は、今回の再利用対象には含めていません。

### 衣装の下の身体を面単位で隠す

`bodyMeshMasks` は、選択した衣装に応じて頂点グループ内の面を除外します。既存の `bodyMasks` は身体オブジェクト全体の除外に引き続き使用できます。

```json
{
  "bodyMeshMasks": {
    "wardrobe.top": {
      "blouse_a": [
        {"object": "CC_Base_Body", "vertexGroup": "PM_Cover_Blouse"}
      ]
    }
  }
}
```

頂点グループのウェイトが0.5より大きい頂点だけで構成される面を削除し、頂点とShapeKeyを保持します。衣装と身体の輪郭に合わせたグループを、準備工程で作成します。

### 検証と画像一覧

`character/validate_wardrobe.py` は生成したGLBをBlenderで再読み込みし、衣装メッシュ、スキン、画像埋め込みを確認します。`character/review_wardrobe.py` は共通素体の腕上げ・膝曲げ画像とウェイト確認結果を出力します。確認済みの13例とポーズ画像は `OneDrive/画像/モデル生成/promodeler-wardrobe/index.html` にまとめています。今回のポーズ確認はスキニングの確認で、布の物理シミュレーションは含みません。
