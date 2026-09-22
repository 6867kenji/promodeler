# ProModeler 人型キャラクター生成統合設計書

## 1. 概要

対象プロジェクト：

```text
C:\task\develop\promodeler
```

現在のProModelerは、コードから3Dモデルを生成することを目的としている。

建物、家具、小物、機械、背景オブジェクト等については、従来通りBlender/Python等を利用したProcedural Modelingを継続する。

一方、人間の身体・顔・髪・衣服については、コードによる直接モデリングを廃止する。

人型モデルについては、

```text
CharacterRecipe
        ↓
Unity Character Creator
        ↓
UMA
        ↓
Human Character
```

という専用生成パイプラインへ移行する。

---

# 2. 基本方針

ProModelerを以下の2系統に分割する。

```text
                        ProModeler
                            │
                  ModelGenerationRouter
                            │
             ┌──────────────┴──────────────┐
             │                             │
      Procedural Model                Humanoid Model
             │                             │
             ▼                             ▼
      Blender/Python                CharacterRecipe
             │                             │
             ▼                             ▼
       Mesh Generator               Unity Character
             │                       Generator
             │                             │
             │                             ▼
             │                            UMA
             │                             │
             └──────────────┬──────────────┘
                            ▼
                     Generated Asset
```

対象モデルによって生成方式を切り替える。

| Model Type   | Generator         |
| ------------ | ----------------- |
| furniture    | Procedural        |
| architecture | Procedural        |
| vehicle      | Procedural        |
| prop         | Procedural        |
| environment  | Procedural        |
| weapon       | Procedural        |
| humanoid     | Character Creator |
| human_npc    | Character Creator |
| human_player | Character Creator |

---

# 3. 最重要変更

従来：

```text
HumanDefinition
      ↓
Python
      ↓
Blender Mesh API
      ↓
人体を頂点から生成
```

新方式：

```text
HumanDefinition
      ↓
CharacterRecipeGenerator
      ↓
CharacterRecipe.json
      ↓
Unity Character Creator
      ↓
UMA
      ↓
Skinned Human
```

ProModelerは人間のポリゴンを生成しない。

代わりに、

```text
身長
体格
筋肉
顔型
目
鼻
口
肌
髪
衣服
```

などの意味的なパラメータを生成する。

---

# 4. システム境界

UnityとProModelerを直接依存させない。

境界を

```text
CharacterRecipe
```

とする。

```text
┌──────────────────────────┐
│       ProModeler         │
│                          │
│ AI / Code / Random       │
│          ↓               │
│ CharacterRecipeGenerator │
└────────────┬─────────────┘
             │
             │ JSON
             ▼
┌──────────────────────────┐
│ Unity Character Creator  │
│                          │
│ Recipe Loader            │
│      ↓                   │
│ Parameter Resolver       │
│      ↓                   │
│ UMA                      │
└──────────────────────────┘
```

この構成にすると、将来的にUMAを別システムへ交換してもProModeler側への影響を最小化できる。

---

# 5. 推奨ディレクトリ構成

既存ProModelerへ以下を追加する。

```text
C:\task\develop\promodeler
│
├─ src/
│  │
│  ├─ core/
│  │
│  │   model_definition.py
│  │   model_router.py
│  │
│  ├─ generators/
│  │  │
│  │  ├─ procedural/
│  │  │   furniture/
│  │  │   architecture/
│  │  │   props/
│  │  │
│  │  └─ humanoid/
│  │      character_generator.py
│  │      recipe_generator.py
│  │      preset_resolver.py
│  │      randomizer.py
│  │      validator.py
│  │
│  ├─ bridges/
│  │   unity_character_bridge.py
│  │
│  └─ exporters/
│
├─ schemas/
│   character_recipe.schema.json
│
├─ character/
│  │
│  ├─ presets/
│  │  ├─ face/
│  │  ├─ body/
│  │  └─ style/
│  │
│  ├─ recipes/
│  │
│  └─ catalog/
│      hair.json
│      clothes.json
│      accessories.json
│
├─ unity/
│  │
│  └─ ProModelerCharacterCreator/
│      └─ Assets/
│          └─ ProModeler/
│
├─ work/
│   character/
│
└─ dist/
    characters/
```

Unityは独立したサブプロジェクトとして扱う。

---

# 6. ModelDefinition

既存モデル定義に、

```text
model_type
```

を持たせる。

例：

```json
{
  "id": "npc_0001",

  "model_type": "humanoid",

  "description": "30代の男性、細身、短い黒髪、ビジネスカジュアル"
}
```

Router：

```python
def generate_model(definition):

    if definition.model_type == "humanoid":
        return humanoid_generator.generate(definition)

    return procedural_generator.generate(definition)
```

これにより既存Procedural Generatorを変更する必要がない。

---

# 7. CharacterRecipe

人型モデルの中心データ。

```json
{
  "schemaVersion": "1.0",

  "id": "npc_0001",

  "seed": 128421,

  "base": {
    "race": "human",
    "body": "human_base_v1"
  },

  "body": {
    "height": 0.63,
    "weight": 0.38,
    "muscle": 0.42,

    "shoulderWidth": 0.54,
    "chest": 0.46,
    "waist": 0.41,
    "hip": 0.45,

    "armLength": 0.51,
    "legLength": 0.56
  },

  "face": {
    "headWidth": 0.46,
    "headHeight": 0.54,

    "jaw": {
      "width": 0.43,
      "height": 0.52,
      "angle": 0.48
    },

    "eyes": {
      "size": 0.51,
      "width": 0.54,
      "height": 0.47,
      "spacing": 0.45,
      "angle": 0.48
    },

    "nose": {
      "width": 0.43,
      "height": 0.54,
      "bridge": 0.51,
      "tip": 0.47
    },

    "mouth": {
      "width": 0.48,
      "upperLip": 0.45,
      "lowerLip": 0.50
    }
  },

  "appearance": {
    "skin": "skin_004",
    "hair": "hair_short_012",
    "eyebrow": "eyebrow_003",
    "eyes": "eye_brown_002"
  },

  "wardrobe": {
    "top": "business_shirt_003",
    "bottom": "slacks_002",
    "shoes": "leather_001"
  }
}
```

---

# 8. パラメータは意味ベースにする

UMA固有名をRecipeへ保存しない。

悪い例：

```json
{
  "umaDnaUpperMuscle": 0.73,
  "umaDnaHeadSize": 0.42
}
```

良い例：

```json
{
  "muscle": 0.73,
  "headSize": 0.42
}
```

Unity側で、

```text
ProModeler Parameter

muscle
    ↓
SemanticParameterResolver
    ↓
UMA DNA
    ↓
Bone / BlendShape
```

へ変換する。

---

# 9. Character Creator側

Unity側の構成：

```text
ProModelerCharacterCreator
│
├─ CharacterCreator
│
│   ├─ CharacterController
│
├─ Recipe
│
│   ├─ CharacterRecipe
│   ├─ CharacterRecipeLoader
│   └─ CharacterRecipeWriter
│
├─ Parameters
│
│   ├─ BodyParameterResolver
│   ├─ FaceParameterResolver
│   └─ MaterialParameterResolver
│
├─ Runtime
│
│   └─ UMACharacterAdapter
│
├─ Assets
│
│   ├─ CharacterAssetCatalog
│   ├─ HairCatalog
│   ├─ WardrobeCatalog
│   └─ MaterialCatalog
│
├─ UI
│
│   ├─ FaceEditor
│   ├─ BodyEditor
│   ├─ HairEditor
│   ├─ SkinEditor
│   └─ WardrobeEditor
│
└─ Batch
    └─ CharacterBatchGenerator
```

---

# 10. UMAの役割

UMAは、

```text
Recipe Parameter
      ↓
DNA
      ↓
Skeleton
      ↓
Morph
      ↓
Wardrobe
      ↓
Material
      ↓
SkinnedMesh
```

を担当する。

ProModelerからUMA APIを直接操作しない。

必ず、

```text
UMACharacterAdapter
```

経由とする。

UMAはMITライセンスで提供されるため、独自Character Creatorの基盤として利用しやすい。

---

# 11. Adapter設計

Unity側：

```csharp
public interface ICharacterRuntime
{
    void LoadRecipe(CharacterRecipe recipe);

    void SetParameter(
        string parameter,
        float value);

    void SetAsset(
        string category,
        string assetId);

    CharacterRecipe GetRecipe();

    Task BuildCharacter();
}
```

実装：

```csharp
public class UMACharacterRuntime
    : ICharacterRuntime
{
    ...
}
```

将来的には、

```text
ICharacterRuntime
       │
       ├─ UMACharacterRuntime
       │
       ├─ CustomCharacterRuntime
       │
       └─ FutureRuntime
```

と交換可能。

---

# 12. ProModelerからUnityを呼び出す

通常利用：

```text
promodeler
    ↓
character.json
    ↓
Unity
```

対話キャラメイクの場合：

```text
ProModeler
     │
     │ recipe.json
     ▼
Character Creator
     │
     │ ユーザー編集
     ▼
recipe.json 更新
     │
     ▼
ProModeler
```

つまりUnity Editorの状態そのものを保存しない。

常にRecipeが正となる。

---

# 13. CLI

最終的には次のようなCLIを提供する。

```text
promodeler generate npc.yaml
```

または：

```text
promodeler character generate npc.yaml
```

結果：

```text
work/
  character/
    npc_0001/
      definition.yaml
      recipe.json
      build.json
```

---

# 14. GUIキャラメイク

人間が調整したい場合：

```text
promodeler character edit npc_0001
```

↓

```text
Unity Character Creator起動
```

↓

```text
┌───────────────────────────────────┐
│                                   │
│              Human                │
│                                   │
│                                   │
├─────────────┬─────────────────────┤
│ Face        │ Eye size      ━●━━ │
│ Body        │ Nose width    ━━●━ │
│ Hair        │ Jaw width     ━●━━ │
│ Skin        │ Height        ━━●━ │
│ Clothes     │                     │
└─────────────┴─────────────────────┘
```

Saveすると、

```text
character/recipes/npc_0001.json
```

のみ更新する。

---

# 15. 自動生成モード

ProModelerの強みであるコード生成も維持する。

例えば：

```yaml
type: humanoid

style:
  age: 35
  build: slim
  hair: short
  clothing: business-casual
```

↓

```text
CharacterRecipeGenerator
```

↓

```json
{
  "body": {
    "weight": 0.38,
    "muscle": 0.35
  }
}
```

↓

```text
Unity
```

↓

```text
Human Character
```

とする。

---

# 16. AI連携

将来的には、

```text
「30代男性。
少し細身。
黒髪短髪。
エンジニアらしい服装。」
```

↓

```text
LLM
```

↓

```text
CharacterRecipe
```

とする。

LLMにはBlender Pythonを書かせない。

人体については、

**LLM → Recipe**

までを責務とする。

これは非常に重要。

AIが毎回人体Topologyそのものを生成すると品質が安定しないためである。

---

# 17. Random NPC Generator

同じ仕組みからNPCを大量生成可能。

```python
for i in range(1000):

    recipe = generator.randomize(
        seed=i
    )

    repository.save(recipe)
```

キャラクターごとの差は、

```text
Recipe
```

のみ。

Base Meshや衣服Meshをコピーしない。

---

# 18. Seed

再現性を保証するため、

```json
{
  "seed": 12345678
}
```

を保持する。

同じ

```text
generatorVersion
+
assetVersion
+
seed
```

なら、原則同じキャラクターを生成できるようにする。

これはProModeler全体の再現可能な生成思想とも相性が良い。

---

# 19. Version管理

Recipeに、

```json
{
  "schemaVersion": "1.0",
  "generatorVersion": "1.2.0",
  "characterAssetsVersion": "2026.09"
}
```

を保存する。

Character Assetを更新しても、既存Characterを追跡できるようにする。

---

# 20. Asset Catalog

Hairや衣服はIDで参照する。

```json
{
  "id": "hair_short_012",

  "category": "hair",

  "genderCompatibility": [
    "male",
    "female"
  ],

  "bodyCompatibility": [
    "human_base_v1"
  ],

  "addressable": "character/hair/short_012",

  "license": {
    "type": "CC0",
    "source": "..."
  }
}
```

Unity側ではAddressablesを利用して、

```text
hair_short_012
```

から実際のAssetをロードする。

UnityのAddressablesはアドレス経由でローカルまたはリモートのAssetと依存関係を非同期ロードできるため、この用途に適している。

---

# 21. MakeHumanの位置付け

MakeHumanをRuntimeとしてProModelerへ組み込まない。

利用するのは主に、

```text
Base Mesh
Targets
Textures
Clothes
Pose
Expression
```

などのグラフィックAsset。

MakeHumanのbundled core assetsはCC0。

一方、

```text
MakeHuman source code
MPFB source code
```

は別ライセンスなので、Runtime依存しない設計とする。

MakeHuman Communityから入手した追加Assetについては、個別ライセンスをAsset Catalogに登録する。

---

# 22. Blenderの役割を変更する

人体では、

```text
Blender = 人間を一から生成
```

をやめる。

新しい役割：

```text
Blender
 │
 ├─ Asset Cleanup
 ├─ Hair加工
 ├─ Clothes加工
 ├─ Weight修正
 ├─ Morph追加
 ├─ LOD生成
 ├─ Material調整
 └─ Asset Validation
```

つまり、

**GeneratorではなくAsset Production Tool**

として使用する。

---

# 23. ProModelerで引き続き生成するもの

Character Creatorへ全部移行する必要はない。

例えば、

```text
剣
盾
杖
銃
バッグ
眼鏡
アクセサリー
ヘルメット
装飾品
```

などはProModelerで生成可能。

生成結果をCharacter Creator側へ、

```text
Accessory
Equipment
```

として登録する。

これにより、

```text
人体
   ↓
Character Creator

装備
   ↓
ProModeler
```

という役割分担ができる。

---

# 24. 最終的な生成構成

```text
                        Model Definition
                               │
                               ▼
                      ModelGenerationRouter
                               │
               ┌───────────────┴────────────────┐
               │                                │
          Non Humanoid                       Humanoid
               │                                │
               ▼                                ▼
       ProceduralGenerator              RecipeGenerator
               │                                │
               ▼                                ▼
         Blender Python                 CharacterRecipe
               │                                │
               │                                ▼
               │                    Unity Character Creator
               │                                │
               │                                ▼
               │                               UMA
               │                                │
               │                                ▼
               │                        Skinned Character
               │                                │
               └───────────────┬────────────────┘
                               ▼
                           Validator
                               │
                               ▼
                         Asset Exporter
                               │
                  ┌────────────┼─────────────┐
                  ▼            ▼             ▼
                 GLB          FBX          Unity
```

---

# 25. Character Generator Interface

ProModeler側では、

```python
class ModelGenerator:

    def generate(self, definition):
        raise NotImplementedError
```

を基本interfaceとする。

```python
class ProceduralModelGenerator(ModelGenerator):

    def generate(self, definition):
        ...
```

```python
class HumanoidModelGenerator(ModelGenerator):

    def generate(self, definition):

        recipe = self.recipe_generator.generate(
            definition
        )

        self.validator.validate(recipe)

        return self.unity_bridge.generate(
            recipe
        )
```

Router：

```python
GENERATORS = {
    "humanoid": HumanoidModelGenerator(),
    "human_npc": HumanoidModelGenerator(),

    "prop": ProceduralModelGenerator(),
    "furniture": ProceduralModelGenerator(),
    "architecture": ProceduralModelGenerator()
}
```

---

# 26. Unity Bridge

ProModelerからUnityへは、

```python
class UnityCharacterBridge:

    def generate(self, recipe):

        recipe_path = self.save_recipe(recipe)

        result = self.invoke_unity(
            recipe_path
        )

        return result
```

とする。

詳細なUnity呼び出し方法は実装フェーズで決定するが、境界は必ずJSON Recipeとする。

---

# 27. InteractiveとBatchを共通化

キャラメイクアプリと自動生成は別実装にしない。

```text
              CharacterRecipe
                     │
         ┌───────────┴───────────┐
         │                       │
         ▼                       ▼
 Interactive UI             Batch Generator
         │                       │
         └───────────┬───────────┘
                     ▼
              CharacterRuntime
                     │
                     ▼
                    UMA
```

UIで作っても、AIで作っても、Pythonから作っても同じ結果になる設計とする。

---

# 28. 保存するもの

Git管理：

```text
CharacterRecipe
CharacterPreset
CharacterSchema
AssetCatalog
ParameterMapping
```

大容量Asset：

```text
Body
Hair
Clothes
Texture
Animation
```

についてはUnity Addressables等で管理する。

生成済みNPCについて、完成Meshを大量にGitへ入れない。

---

# 29. 人型生成で禁止する処理

以下のような既存コードが存在する場合、人型モデルでは呼び出さない。

```text
create_head_mesh()
create_eye_mesh()
create_nose_mesh()
create_mouth_mesh()
create_arm_mesh()
create_leg_mesh()
generate_human_topology()
```

人型については、

```text
generate_character_recipe()
```

へ置き換える。

---

# 30. 例外

Procedural Modelingを完全禁止するわけではない。

以下は利用可能。

```text
Character
 │
 ├─ Body               Character Creator
 ├─ Face               Character Creator
 ├─ Hair               Character Creator Asset
 ├─ Clothes            Character Creator Asset
 │
 ├─ Sword              ProModeler
 ├─ Staff              ProModeler
 ├─ Glasses            ProModeler
 ├─ Backpack           ProModeler
 └─ Special Equipment  ProModeler
```

人間そのものと、人間が装備する物を分離する。

---

# 31. MVP

最初の実装範囲は小さくする。

```text
ProModeler
    ↓
humanoid判定
    ↓
CharacterRecipe生成
    ↓
Unityへ読込
    ↓
UMA Human生成
```

対応Parameter：

```text
Height
Weight
Muscle

HeadWidth

EyeSize
EyeSpacing

NoseWidth
NoseHeight

MouthWidth

JawWidth

Skin
Hair
Top
Bottom
Shoes
```

まず15～20項目でEnd-to-Endを完成させる。

---

# 32. Phase 2

その後、

```text
Face 50～80 Parameter
Body 20～30 Parameter

Hair
Beard
Eyebrow

Skin
Eye
Makeup

Clothing
Accessory
```

へ拡大する。

---

# 33. Phase 3

ProModelerとの完全統合。

例えば、

```text
promodeler generate character.yaml
```

だけで、

```text
Definition
   ↓
Recipe
   ↓
Character
   ↓
Validation
   ↓
Preview
   ↓
Export
```

まで実行する。

---

# 34. Phase 4

キャラクターメイキングGUIを導入。

```text
CharacterRecipe
      ↓
Unity UI

顔
体
髪
肌
衣服

      ↓

Save

      ↓
CharacterRecipe
```

手動編集結果もProModelerの生成結果として扱う。

---

# 35. Phase 5

AI Character Generatorへ拡張。

```text
Prompt

「20代女性冒険者。
小柄で細身。
肩までの黒髪。
軽装の魔法使い。」

             ↓

       Recipe Generator

             ↓

      CharacterRecipe

             ↓

     Character Creator
```

AIはMeshを作らない。

**AIはキャラクター設計値を作る。**

これをProModelerの人型生成の基本思想とする。

---

# 36. 採用アーキテクチャ

最終採用案：

```text
ProModeler
    │
    ├─ Procedural Modeling
    │      │
    │      └─ Blender/Python
    │
    └─ Humanoid Modeling
           │
           └─ CharacterRecipe
                   │
                   ▼
          Unity Character Creator
                   │
                   ▼
                  UMA
                   │
          ┌────────┼─────────┐
          ▼        ▼         ▼
        Body      Hair     Clothes
                   │
                   ▼
              Character
```

ProModelerを、

「すべてをコードでモデリングするツール」

から、

**「モデル種別ごとに最適な生成エンジンを使い分ける3Dアセット生成プラットフォーム」**

へ変更する。

その中で人型だけは、Procedural Mesh Generationではなく、

**Parametric Character Generation**

として扱う。
