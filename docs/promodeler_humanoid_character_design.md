# ProModeler 人型モデル生成再設計書
## AI生成GLB参照 + Canonical Character Base + Recipe駆動キャラクターメイキング

---

## 1. 目的

`C:\task\develop\promodeler` において、人型モデルの生成方式を見直す。

従来は「コードで人型メッシュそのものを生成する」方針だったが、以下の課題があった。

- 人体の比率・顔形状・髪型・衣服の自然さをコードのみで作るのが難しい
- MakeHuman はやや不気味で、今回のゲームのテイストと合いにくい
- VRoid は逆にアニメ調が強すぎる
- AI生成GLBは見た目の参考として有効だが、トポロジーやリグがバラバラでそのまま量産基盤には向かない

そのため、人型モデルについては以下の方針へ変更する。

> **AI生成GLBやVRoid等を「参考モデル」として使い、最終的には統一された Canonical Base Mesh を中心に CharacterRecipe で制御する方式へ移行する。**

---

## 2. 目標

### 2.1 見た目の目標

目指す方向性は以下。

- VRoidより少し写実寄り
- MakeHumanより自然で綺麗
- セミリアル / スタイライズド寄り
- アニメ調すぎず、不気味でもない
- ゲーム向けに量産しやすい

### 2.2 技術目標

以下を実現する。

- 人型モデルを **Recipeベース** で生成・保存できる
- **GUIキャラメイク** と **コード生成** の両方に対応する
- AI生成GLBを **参考モデル / 形状サンプル / ShapeKey生成元** として活用できる
- Unityでリアルタイムに表示・編集できる
- Blenderでバッチ変換・自動処理できる
- 将来的に NPC量産、プリセット生成、AIによるRecipe生成へ拡張できる

---

## 3. 基本方針

人型モデルについては、以下の3層構造とする。

```text
[Reference Layer]
  AI生成GLB / VRoid / 手作業モデル / 画像参照

[Canonical Asset Layer]
  Canonical Base Mesh
  Canonical Skeleton
  ShapeKeys
  Hair / Clothes / Materials
  Presets

[Runtime Layer]
  CharacterRecipe
  Unity Character Creator
  Runtime Generator
  Exporter
```

ポイントは次の通り。

1. **AI生成GLBは最終モデルとして使わない**
2. **AI生成GLBは参考・学習・フィッティング元として使う**
3. **実際の量産は Canonical Base + Recipe で行う**
4. **コードはメッシュを作るのではなく、Recipeを作る**
5. **GUIとバッチ生成は同じRecipe基盤を使う**

---

## 4. 全体アーキテクチャ

```text
                         +--------------------+
                         |   ProModeler CLI   |
                         +--------------------+
                                   |
                                   v
                      +---------------------------+
                      | ModelGenerationRouter     |
                      +---------------------------+
                          |                   |
             non-humanoid |                   | humanoid
                          v                   v
              +------------------+   +------------------------+
              | Procedural Mesh  |   | CharacterRecipe Gen    |
              | Generator        |   | / Prompt Parser        |
              +------------------+   +------------------------+
                                                |
                                                v
                                    +------------------------+
                                    | CharacterRecipe (JSON) |
                                    +------------------------+
                                                |
                                                v
                                +---------------------------------+
                                | Unity Character Creator Runtime |
                                +---------------------------------+
                                   |          |           |
                                   v          v           v
                              BlendShape    Bones     Modular Assets
                                   |          |           |
                                   +----------+-----------+
                                              |
                                              v
                                   +----------------------+
                                   | Canonical Character  |
                                   +----------------------+
                                              |
                                              v
                                   GLB / VRM / Prefab / NPC
```

---

## 5. 重要な設計思想

### 5.1 人型は「直接モデリング」しない

禁止対象の思想:

- `create_head_mesh()`
- `create_eye_mesh()`
- `generate_human_topology()`

採用する思想:

- `generate_character_recipe()`

### 5.2 見た目の品質は「ベース資産」で決まる

コードは美しい人型をゼロから生み出さない。  
コードが扱うのは、**既に綺麗なベースモデルのパラメータ空間** である。

### 5.3 生成の正本は Recipe

保存対象は完成メッシュではなく `CharacterRecipe` とする。

---

## 6. AI生成GLBの位置づけ

### 6.1 AI生成GLBでできること

AI生成GLBは以下に使う。

- 理想の雰囲気探索
- 顔・体型・衣服の方向性確認
- Canonical Base作成の参考
- ShapeKey作成の元データ
- プリセット作成の元データ
- Vision/LLMからの自動パラメータ推定の教師データ

### 6.2 AI生成GLBを直接使わない理由

AI生成GLBは以下の問題を持ちやすい。

- トポロジーが毎回違う
- 頂点数が違う
- UVが違う
- 左右非対称
- ボーン構造が不統一
- 髪や服が一体化している
- 量産やMorph制御に不向き

そのため、AI生成GLBは以下のように扱う。

```text
AI生成GLB
   ↓
参照・選別
   ↓
Blenderで正規化
   ↓
Canonical Baseにフィット
   ↓
ShapeKey / Preset / Material へ変換
```

---

## 7. Canonical Character Base

### 7.1 定義

全キャラクター生成の基準となる統一モデルを `Canonical Character Base` と呼ぶ。

構成は以下。

- Base Body Mesh
- Base Face Mesh
- Eyes / Teeth / Tongue
- Canonical Skeleton
- ShapeKeys
- UV
- Material Slots
- Hair Attach Points
- Clothing Compatibility Rules

### 7.2 初期構成

まずは以下の2体または1体から開始する。

- `SemiRealBase_Female_v1`
- `SemiRealBase_Male_v1`

もしくは簡易的には:

- `SemiRealBase_v1`

---

## 8. Canonical Base の品質要件

### 8.1 見た目

- セミリアル
- 大きすぎない目
- 過度に平坦でない鼻
- アニメより少し現実寄りの頭身
- 髪はトゥーンとリアルの中間
- 肌は軽い写実感を持つ

### 8.2 技術要件

- すべての量産キャラが同じトポロジーを共有
- 左右対称
- Unity Humanoid互換
- BlendShape運用可能
- モジュラー衣服対応
- Material制御可能
- LOD対応可能

---

## 9. キャラクター差分の表現方法

キャラクター差分は以下の4要素で表現する。

| 要素 | 用途 |
|---|---|
| BlendShape / ShapeKey | 顔、体型、局所形状 |
| Bone Transform | 身長、脚長、腕長、肩幅など |
| Modular Assets | 髪、衣服、靴、アクセサリー |
| Material Parameters | 肌色、瞳色、髪色、メイク、質感 |

### 9.1 ShapeKeyで扱うもの

- 顔形状
- 目
- 鼻
- 口
- 顎
- 頬
- 耳
- 胴体の肉付き
- 胸郭・腰回りの微調整

### 9.2 Boneで扱うもの

- 身長
- 脚の長さ
- 腕の長さ
- 肩幅
- 首の長さ
- 手足の大きさ

### 9.3 Modular Assetで扱うもの

- 髪
- 眉
- まつ毛
- トップス
- ボトムス
- 靴
- アクセサリ
- 装備

### 9.4 Materialで扱うもの

- 肌色
- 唇色
- 目の虹彩色
- 髪色
- そばかす
- 赤み
- メイク
- 質感パラメータ

---

## 10. CharacterRecipe 設計

### 10.1 基本思想

Recipeは人型モデルのソースコードに相当する。

### 10.2 サンプルJSON

```json
{
  "schemaVersion": "2.0",
  "id": "npc_0001",
  "base": "SemiRealBase_Female_v1",
  "seed": 10342,

  "face": {
    "headSize": 0.52,
    "faceRoundness": 0.61,
    "jawWidth": 0.41,
    "jawLength": 0.46,

    "eyeSize": 0.66,
    "eyeWidth": 0.58,
    "eyeHeight": 0.54,
    "eyeSpacing": 0.47,
    "eyeAngle": 0.42,

    "noseSize": 0.35,
    "noseWidth": 0.39,
    "noseHeight": 0.44,
    "noseBridge": 0.48,

    "mouthWidth": 0.46,
    "mouthHeight": 0.43,
    "upperLip": 0.45,
    "lowerLip": 0.48,

    "cheekVolume": 0.57
  },

  "body": {
    "height": 0.58,
    "headRatio": 0.56,
    "shoulderWidth": 0.45,
    "chest": 0.44,
    "waist": 0.38,
    "hip": 0.47,
    "armLength": 0.52,
    "legLength": 0.60,
    "armThickness": 0.39,
    "legThickness": 0.42,
    "muscle": 0.31
  },

  "appearance": {
    "skinPreset": "skin_soft_03",
    "eyePreset": "eye_natural_02",
    "hairStyle": "hair_medium_012",
    "eyebrowStyle": "eyebrow_soft_003"
  },

  "material": {
    "skinTone": "#F1C6B4",
    "blushStrength": 0.18,
    "lipColor": "#C68984",
    "hairColor": "#45373A",
    "eyeColor": "#607D8B",
    "roughnessSkin": 0.36,
    "toonBlend": 0.42
  },

  "wardrobe": {
    "top": "top_casual_013",
    "bottom": "bottom_skirt_007",
    "shoes": "shoes_shortboots_003"
  }
}
```

---

## 11. パラメータ設計方針

### 11.1 全パラメータを 0.0～1.0 に正規化

UI・保存・生成のすべてで共通化する。

### 11.2 Semantic Parameter を採用

Recipeに `BlendShape名` を直接書かない。

悪い例:

```json
{
  "bs_face_eye_size": 0.72
}
```

良い例:

```json
{
  "eyeSize": 0.72
}
```

内部で以下のように解決する。

```text
eyeSize
  ↓
FaceParameterResolver
  ↓
BlendShape(Eye_Size)
```

---

## 12. Parameter Resolver

### 12.1 概要

Recipeの意味的パラメータを、実際のBlendShape / Bone / Material / Assetへ変換するコンポーネント。

### 12.2 種類

- `FaceParameterResolver`
- `BodyParameterResolver`
- `MaterialParameterResolver`
- `WardrobeResolver`

### 12.3 例

`height = 0.58` は内部的には以下に展開される。

```text
height
  ↓
BodyParameterResolver
  ├─ Hips Y scale
  ├─ Spine length
  ├─ UpperLeg length
  └─ LowerLeg length
```

`muscle = 0.31` は以下に展開される。

```text
muscle
  ↓
BodyParameterResolver
  ├─ ArmThickness
  ├─ ShoulderWidth
  ├─ ChestVolume
  ├─ ThighThickness
  └─ CalfThickness
```

---

## 13. Preset 設計

### 13.1 Presetの種類

- Face Preset
- Body Preset
- Style Preset
- Hair Preset
- Wardrobe Preset

### 13.2 目的

- UIでの初期選択
- NPC大量生成
- AI生成結果の丸め込み
- デザイン統一

### 13.3 サンプル

- `face_soft_01`
- `face_cool_02`
- `face_mature_01`
- `body_slim_01`
- `style_citycasual_02`

### 13.4 Mix対応

Presetは補間できるようにする。

```text
face_soft_01 70%
face_cool_02 30%
```

これにより中間表現を量産できる。

---

## 14. AI生成GLBの変換パイプライン

### 14.1 目的

AI生成GLBから、Canonical Baseで使える形状差分・Preset・Texture情報を抽出する。

### 14.2 手順

```text
1. AI生成GLBを収集
2. 有望モデルを選別
3. Blenderへインポート
4. 不要メッシュ除去
5. 左右対称化
6. スケール統一
7. リグ確認 / 再リグ
8. Canonical Baseへラップ
9. Shape差分抽出
10. Material / 色情報抽出
11. PresetまたはShapeKeyへ登録
```

### 14.3 変換結果

- `PresetRecipe`
- `ShapeKeyCandidate`
- `MaterialPreset`
- `WardrobeReference`

---

## 15. Blender の役割

### 15.1 位置づけ

Blenderは「人型生成エンジン」ではなく、**アセット加工・正規化・ShapeKey制作ツール** とする。

### 15.2 主な用途

- AI生成GLBの整形
- Canonical Baseの編集
- ShapeKey作成
- 衣服モデリング
- 髪モデリング
- Rig調整
- Weight Paint修正
- UV調整
- Textureベイク
- LOD生成
- VRM / GLB出力

### 15.3 自動化対象

- 参照モデル取り込み
- 正規化
- Canonical Baseへのフィット
- ShapeKey生成
- エクスポート

---

## 16. Unity の役割

### 16.1 位置づけ

Unityは **キャラクターメイキングアプリ本体** と **Runtime Character Generator** を担当する。

### 16.2 主な機能

- Recipeロード
- Recipe編集
- GUIキャラメイク
- BlendShape適用
- Bone調整
- Hair/Clothes差し替え
- Material調整
- Characterプレビュー
- Character保存
- NPCバッチ生成
- Prefab / GLB / VRMエクスポート補助

---

## 17. Unity Runtime 構成

```text
CharacterCreator
│
├─ CharacterController
├─ Recipe
│   ├─ CharacterRecipe
│   ├─ RecipeLoader
│   └─ RecipeWriter
├─ Resolver
│   ├─ FaceParameterResolver
│   ├─ BodyParameterResolver
│   ├─ MaterialParameterResolver
│   └─ WardrobeResolver
├─ Runtime
│   ├─ BlendShapeApplicator
│   ├─ BoneApplicator
│   ├─ MaterialApplicator
│   └─ AssetAttachService
├─ Catalog
│   ├─ HairCatalog
│   ├─ WardrobeCatalog
│   ├─ MaterialCatalog
│   └─ PresetCatalog
└─ UI
    ├─ FaceEditor
    ├─ BodyEditor
    ├─ HairEditor
    ├─ MaterialEditor
    └─ WardrobeEditor
```

---

## 18. ディレクトリ構成案

### 18.1 ProModeler 側

```text
C:\task\develop\promodeler
│
├─ src/
│  ├─ core/
│  │   ├─ model_definition.py
│  │   ├─ model_router.py
│  │   └─ generation_context.py
│  │
│  ├─ generators/
│  │   ├─ procedural/
│  │   └─ humanoid/
│  │       ├─ recipe_generator.py
│  │       ├─ prompt_parser.py
│  │       ├─ preset_mixer.py
│  │       ├─ randomizer.py
│  │       └─ validator.py
│  │
│  ├─ bridges/
│  │   ├─ unity_character_bridge.py
│  │   └─ blender_character_bridge.py
│  │
│  └─ exporters/
│
├─ schemas/
│  └─ character_recipe.schema.json
│
├─ character/
│  ├─ recipes/
│  ├─ presets/
│  ├─ catalogs/
│  └─ references/
│
├─ work/
│  └─ character/
│
└─ unity/
   └─ ProModelerCharacterCreator/
```

### 18.2 Unity 側

```text
Assets/
  ProModeler/
    Runtime/
    Editor/
    UI/
    Data/
    Characters/
      Base/
      Hair/
      Wardrobe/
      Materials/
      Presets/
```

---

## 19. CLI 設計

### 19.1 基本コマンド

```bash
promodeler generate npc.yaml
```

### 19.2 人型専用

```bash
promodeler character generate npc.yaml
promodeler character edit npc_0001
promodeler character build npc_0001
promodeler character export npc_0001 --format glb
promodeler character random --count 100
```

### 19.3 期待結果

```text
work/character/npc_0001/
  definition.yaml
  recipe.json
  preview.png
  build.log
  exports/
    npc_0001.glb
```

---

## 20. GUI キャラメイク設計

### 20.1 画面構成

```text
+-------------------------------------------------------------+
|                         Character Preview                   |
|                                                             |
|                                                             |
+-------------------------------------------------------------+
| Face | Body | Hair | Skin | Clothes | Preset | Export      |
+-------------------------------------------------------------+
| Parameter Controls                                          |
|  Eye Size      [-----●------]                              |
|  Nose Height   [----●-------]                              |
|  Jaw Width     [------●-----]                              |
|  Height        [--------●---]                              |
+-------------------------------------------------------------+
```

### 20.2 機能

- スライダー編集
- プリセット適用
- Undo / Redo
- Random生成
- 保存 / 読込
- エクスポート

---

## 21. Material / Shader 方針

### 21.1 目標

- トゥーンすぎない
- リアルすぎない
- セミリアルな肌感
- 自然な髪の質感
- やりすぎない陰影

### 21.2 方針

- 肌はソフトなトゥーン + 軽いPBR
- 髪はトゥーン寄りだがハイライトは自然
- 目は記号的すぎない自然な虹彩
- 服は材質に応じて粗さ・反射を分ける

### 21.3 Recipeで制御する項目

- `toonBlend`
- `skinRoughness`
- `hairSpecular`
- `shadowSoftness`
- `rimLightStrength`

---

## 22. 髪と衣服の方針

### 22.1 髪

- Modular Hair
- 髪型ごとにMesh差し替え
- 色はRecipe制御
- 必要に応じて前髪/後髪分割も可能

### 22.2 衣服

- Top / Bottom / Shoes を基本カテゴリとする
- 将来的に Accessory / Outer / Gear を追加
- 服ごとに体型追従のための補助BlendShapeを持てる設計にする

### 22.3 Body Mask

衣服で隠れる身体部位は描画しない。

---

## 23. Character Asset Catalog

すべての髪・衣服・マテリアル・プリセットはCatalogで管理する。

### 23.1 例

```json
{
  "id": "hair_medium_012",
  "category": "hair",
  "base": "SemiRealBase_Female_v1",
  "mesh": "Hair_Medium_012",
  "materials": ["Hair_Default"],
  "thumbnail": "hair_medium_012.png",
  "tags": ["casual", "medium", "soft"],
  "license": {
    "type": "internal",
    "source": "generated_from_ai_reference"
  }
}
```

### 23.2 管理項目

- Asset ID
- Category
- Base Compatibility
- Mesh
- Material
- Thumbnail
- Tags
- Source
- License
- Version

---

## 24. Random Character Generation

### 24.1 目的

- NPC量産
- バリエーション拡張
- テストデータ作成

### 24.2 方針

完全ランダムではなく、**分布 + 制約 + Preset** を使う。

### 24.3 例

- 年齢層
- 体型傾向
- 髪型カテゴリ
- 服装カテゴリ
- 世界観タグ

### 24.4 出力

Recipeのみ保存する。

---

## 25. AI連携方針

### 25.1 AIの役割

AIにメッシュを作らせない。  
AIは以下を担当する。

- キャラクター設定文の解釈
- CharacterRecipeの草案作成
- Preset候補の選定
- 画像参照からのパラメータ推定
- 髪色 / 肌色 / 服装タグの提案

### 25.2 例

入力:

> 20代後半、細身、落ち着いた都会的な女性、黒髪ボブ、少し大人っぽい雰囲気

出力:

```json
{
  "body": {
    "height": 0.55,
    "waist": 0.37,
    "hip": 0.46
  },
  "facePreset": "face_mature_01",
  "hairStyle": "hair_bob_003",
  "hairColor": "#2E2A2B",
  "stylePreset": "style_citycasual_01"
}
```

---

## 26. 参照画像・参照モデルからの推定

### 26.1 可能なこと

- AI画像 → 色・雰囲気・顔傾向を抽出
- AI生成GLB → 形状傾向を抽出
- 手作業モデル → Preset化

### 26.2 目的

「この雰囲気のキャラを作りたい」を Recipe に変換すること。

---

## 27. 開発フェーズ

### Phase 1: MVP

最小限のE2Eを完成させる。

#### 範囲

- Canonical Base 1体
- Face/Body 15～20パラメータ
- 髪 5種類
- 衣服 5セット
- Recipe保存/読込
- Unity GUI
- ProModeler連携

### Phase 2: Canonical化強化

- AI生成GLBの取り込み
- Blender自動正規化
- ShapeKey追加
- Material強化

### Phase 3: Character Creator拡張

- 50～80パラメータ
- Preset
- Random生成
- Undo / Redo
- Export

### Phase 4: NPC量産

- 100～1000体のRecipe生成
- タグベース生成
- バッチ出力

### Phase 5: AI連携

- Prompt → Recipe
- 画像 → Recipe
- GLB参照 → Preset化

---

## 28. MVP対象パラメータ

### Face

- Eye Size
- Eye Width
- Eye Height
- Eye Spacing
- Eye Angle
- Nose Size
- Nose Width
- Nose Height
- Mouth Width
- Jaw Width
- Face Roundness

### Body

- Height
- Shoulder Width
- Waist
- Hip
- Leg Length
- Arm Length
- Body Thickness
- Muscle

### Appearance

- Skin Tone
- Hair Color
- Eye Color

### Assets

- Hair Style
- Top
- Bottom
- Shoes

---

## 29. クラス設計（Python側）

```python
class ModelGenerator:
    def generate(self, definition):
        raise NotImplementedError


class HumanoidModelGenerator(ModelGenerator):
    def __init__(self, recipe_generator, unity_bridge, validator):
        self.recipe_generator = recipe_generator
        self.unity_bridge = unity_bridge
        self.validator = validator

    def generate(self, definition):
        recipe = self.recipe_generator.generate(definition)
        self.validator.validate(recipe)
        return self.unity_bridge.generate(recipe)
```

### 主要コンポーネント

- `CharacterRecipeGenerator`
- `PromptParser`
- `PresetResolver`
- `RecipeValidator`
- `UnityCharacterBridge`
- `BlenderCharacterBridge`

---

## 30. クラス設計（Unity側）

```csharp
public class CharacterController : MonoBehaviour
{
    public void LoadRecipe(CharacterRecipe recipe);
    public CharacterRecipe ExportRecipe();
    public void ApplyFaceParameters(FaceParameters face);
    public void ApplyBodyParameters(BodyParameters body);
    public void ApplyMaterialParameters(MaterialParameters material);
    public void ApplyWardrobe(WardrobeParameters wardrobe);
}
```

### 補助クラス

- `FaceParameterResolver`
- `BodyParameterResolver`
- `BlendShapeApplicator`
- `BoneApplicator`
- `MaterialApplicator`
- `AssetAttachService`

---

## 31. エクスポート方針

### 出力形式

- GLB
- VRM
- Unity Prefab
- PNG Preview

### 使い分け

- `GLB`: 汎用3D出力
- `VRM`: アバター用途
- `Prefab`: Unityゲーム実装用

---

## 32. 今回の最終方針

今回の人型モデル生成の中核方針は以下。

### 不採用

- MakeHumanをそのまま基盤にする
- VRoidをそのままキャラメイク基盤にする
- AI生成GLBをそのまま量産に使う
- コードで人体Topologyを毎回生成する

### 採用

- AI生成GLBを参考モデルにする
- Canonical Baseを自前で持つ
- CharacterRecipeで制御する
- Unityでキャラメイクアプリを作る
- Blenderで正規化・ShapeKey生成を自動化する
- ProModelerは「人型 = Recipe生成」に責務変更する

---

## 33. 結論

`promodeler` における人型モデル生成は、今後以下の設計へ移行する。

> **AI生成GLBやVRoid等を参考にしつつ、最終的には Canonical Character Base + CharacterRecipe + Unity Character Creator で統一管理する。**

これにより、

- 綺麗なセミリアルキャラを作れる
- GUIでもコードでも生成できる
- NPC量産に強い
- AI連携しやすい
- 今後の拡張に耐えられる

という構成になる。

---

## 34. 次の実装タスク

次に具体化すべき内容は以下。

1. `SemiRealBase_v1` の要件定義
2. `CharacterRecipe JSON Schema` の確定
3. `MVPパラメータ20項目` の一覧化
4. `Unity Character Creator` のクラス設計詳細化
5. `AI生成GLB → Canonical Base変換` の Blender 手順定義
6. `promodeler character generate/edit/build/export` の CLI 仕様化

---

## 35. 推奨次ステップ

次はこの設計をもとに、以下のどちらかへ進めるのがよい。

### A. 実装寄り

- `CharacterRecipe schema`
- `Pythonクラス構成`
- `Unity C# クラス構成`
- `CLI仕様`

### B. アート寄り

- `SemiRealBase_v1 要件書`
- `ShapeKey一覧 80項目`
- `髪 / 衣服 / Material仕様`
- `見た目ガイドライン`
