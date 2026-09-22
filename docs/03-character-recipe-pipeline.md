# 人型キャラクター生成の再設計: CharacterRecipe パイプラインの promodeler 統合

作成日: 2026-09-22
入力: [docs/02-human-generator.md](02-human-generator.md)（原案）、[docs/01-realitizer-analysis-and-design.md](01-realitizer-analysis-and-design.md)（既存設計、M0–M8）、
`promodeler/` の現行コード、`blueprints/japan-realistic-v1/`（人物 15 体・衣装 2 点の設計書）

この文書は原案の方針（人体のポリゴンを promodeler で生成せず、意味的な `CharacterRecipe` を境界にして
Unity Character Creator + UMA に生成を委ねる）を採用したうえで、原案が参照していなかった既存コード・
既存設計書・既存の成果物に合わせて構成・スキーマ・CLI・工程を再設計する。原案の節番号を参照する箇所は「原案 §n」と書く。

---

## 0. 結論（先に読む）

| 項目 | 決定 |
| --- | --- |
| 人型の生成方式 | 原案どおり **Parametric Character Generation**。promodeler は人体・髪・衣服のメッシュを生成しない。生成するのは `CharacterRecipe`（JSON）と、装備品・小物の GLB |
| 境界 | `character/recipes/<id>.json`（schema `promodeler-character/1.0`）。Unity 側はこの JSON だけを読む。UMA 固有名は入れない（原案 §8） |
| 寸法の扱い | **原案から変更**。Recipe の身体寸法は 0..1 ではなく **メートルの絶対値**（設計書 `dimensions` と同じ語彙）。0..1 の意味スライダーは寸法が定義できない項目（筋肉量、顔の造形）だけに使う。Unity 側の `BodyResolver` が寸法 → UMA DNA を数値解法で解き、ビルド後に実メッシュを計測して残差を `build.json` に出す |
| 既存 MHR フィット | 捨てない。`promodeler/human/mhr.py` は **寸法の整合性検証と参照計測のオラクル** として残す（設計書の周長と断面寸法の矛盾を Unity より前に検出する）。`assets/haruka.py` の髪・服・靴の手続き生成は凍結し、拡張しない |
| コード配置 | 新規パッケージ **`promodeler/character/`**（純 Python、bpy・torch 非依存）と CLI サブコマンド **`promodeler character …`**。原案 §5 の `src/core/model_router.py` 等は作らない（既存の `assets/*.py` → Blender の流儀を壊さない） |
| ルーティング | 原案 §6 の `model_type` は既存設計書の `kind`（`humanoid` / `wearable` / それ以外）で代替。ルータは CLI レベルの振り分け `promodeler generate <blueprint.json>` に留め、core に新抽象は足さない |
| Unity 側 | `unity/ProModelerCharacterCreator/`（独立サブプロジェクト、Unity 6 LTS + HDRP + UMA 2.13 系）。バッチ実行で `build/character/<id>/<hash>/build.json` を書き、既存の `report.json` と同じ思想（status / measured / parts / renders / exports / warnings）で返す |
| ソース・オブ・トゥルース | 人型に限り **Recipe JSON が正**（GUI 編集と往復するため）。ただし Recipe には生成元（設計書のパスと sha256、generator_version、seed）を必ず残し、再生成との差分を取れるようにする。これは既存の「Python が唯一の正」への明示的な例外として README に書く |

---

## 1. 現状の整理: なぜ結果が良くないのか

### 1.1 既存資産（維持するもの）

| 資産 | 場所 | 状態 |
| --- | --- | --- |
| 宣言型アセット定義・検証・レシピ・キャッシュ鍵 | `promodeler/core/` | 完成。小物・家具・建築で機能している |
| ヘッドレス Blender カーネル（形状・ベイク・レンダ・glTF/USDZ・リグ・クリップ・シェイプキー） | `promodeler/kernel/` | 完成 |
| CLI `doctor / new / recipe / build / critique / clean` | `promodeler/cli.py`, `build.py` | 完成。`build/<asset>/<hash>/` に `recipe.json`, `report.json`, `renders/`, `model.glb` |
| MHR 人体フィット（寸法 → 骨格スケール + 体型係数、差分可能計測、表情 11 種のシェイプキー） | `promodeler/human/mhr.py` (FIT_VERSION 18) | 完成。05-woman で身長 +2 mm、周長 ±2 cm |
| 設計書 37 点（独自スキーマ `promodeler-blueprint/1.0`） | `blueprints/japan-realistic-v1/` | 人物 15 体（`kind: humanoid`）、衣装 2 点（`kind: wearable`）は **未実装・未検証** |
| 設計書照合ツール | `tools/blueprint_check.py` | Blender ビルドの `report.json` と MHR フィットを設計書と並べる |
| エージェント作業契約 | `Skill/SKILL.md` | 「Human bodies」節が現行の Blender 人型手順を記述 |

### 1.2 品質が出ていない箇所（最新ビルド `build/haruka/94daf5093991` の目視）

- **髪**: `Strands` の 96 束は「平たいリボン」に見える。写実の髪は数万本のカードまたはストランドと異方性シェーダが必要で、手続き的な束の掃引では届かない。
- **顔**: MHR の頭部係数 20 個は設計書に数値がないため平均顔。眼窩をブーリアンで開けた目は「はめ込み」に見える。眉・まつ毛・歯がない。
- **肌**: 位置マスクで頬・唇を色分けしているが、SSS・マイクロ法線・毛穴のテクスチャがなく陶器状。
- **衣服**: `Loft + ClothDrape` の一枚布は形は合うが縫製・厚み・生地感がない。
- **身体**: 寸法は合っている（唯一うまくいっている部分）。

つまり失敗しているのは **「人体そのもの」ではなく「人体の上に載せる外観要素をコードで手続き生成すること」** である。
原案 §3 の「人体をコードで生成しない」は、本プロジェクトではより正確には
**「髪・衣服・肌・顔の個体差を、作り込まれたアセット（カタログ）とパラメトリック素体で表現する」** と読み替える。

### 1.3 原案が既存と噛み合わない点

| 原案 | 既存の実態 | 再設計での扱い |
| --- | --- | --- |
| `src/core/model_definition.py`, `model_router.py`, `generators/procedural/…`（§5, §25） | パッケージは `promodeler/{core,kernel,human}`、アセットは `assets/*.py`。「Procedural Generator」に当たる抽象クラスはなく、Python ファイルそのものが生成器 | 新設は `promodeler/character/` のみ。既存構造は変更しない |
| `ModelDefinition.model_type`（§6） | 設計書 `blueprint.json` に `kind` がある。非人型の生成は自動ではなく人が `.py` を書く | `kind` を使い、CLI で振り分ける |
| Recipe の身体値は 0..1（§7） | 設計書は `barefoot_height_m: 1.76`, `body_circumferences_m`, `cross_sections` と絶対寸法。MHR フィットも絶対寸法で動く | 寸法はメートル。0..1 は寸法のない項目のみ |
| camelCase JSON（§7, §19） | 既存 JSON は全て snake_case（`recipe_version`, `non_manifold_edges`, `barefoot_height_m`） | snake_case に統一 |
| `promodeler generate npc.yaml`（§13） | 入力は `.py`（アセット）と `blueprint.json`（設計書）。YAML は使っていない | 入力は `blueprint.json` か `recipe.json`。YAML は導入しない |
| `work/character/`, `dist/characters/`（§5, §13） | 出力は `build/<asset>/<hash>/`（gitignore） | `build/character/<id>/<hash>/` に揃える |
| MakeHuman 資産の位置付け（§21） | 既に MHR（Apache 2.0）を採用済み | MHR は計測オラクルとして継続。MakeHuman の CC0 アセットは **カタログの供給源候補** として扱う |
| Blender はアセット加工ツール（§22） | Blender は現在も小物・家具・建築の生成カーネル | 非人型は従来どおり生成カーネル。人型に関してのみ「加工ツール（カタログ用アセットの変換・LOD・検証）」 |

---

## 2. 全体アーキテクチャ

```
blueprints/japan-realistic-v1/<n>-<id>/blueprint.json        設計書（kind: humanoid / wearable / その他）
            │
            │ promodeler generate <blueprint.json>   … kind で振り分け
            ├──────────────────────────────┐
            │ kind ≠ humanoid/wearable      │ kind = humanoid / wearable
            ▼                              ▼
   assets/<id>.py を人が書く          promodeler character recipe <blueprint.json>
   (従来の code-first)                      │  promodeler/character/from_blueprint.py
            │                              ▼
   promodeler build assets/<id>.py    character/recipes/<id>.json  (Git 管理、GUI 編集と往復、Recipe が正)
            │                              │
            ▼                              │ promodeler character build <id>
   promodeler.kernel (Blender)             │  promodeler/character/bridge.py が Unity をバッチ起動
            │                              ▼
   build/<id>/<hash>/                unity/ProModelerCharacterCreator (Unity 6 + HDRP + UMA)
     report.json, model.glb,           RecipeLoader → BodyResolver(寸法→DNA) → FaceResolver
     renders/, textures/               → WardrobeResolver(catalog_id→UMA recipe) → UMACharacterRuntime
            │                          → BodyMeasurer(実メッシュ計測) → VerificationRenderer → Exporter
            │                              │
            │                              ▼
            │                        build/character/<id>/<hash>/
            │                          build.json, model.fbx, model.glb, prefab, renders/, unity.log
            │                              │
            └───────────┬──────────────────┘
                        ▼
        promodeler character check <id>   … 設計書 × Recipe × build.json の照合（tools/blueprint_check.py を一般化）
        contact_sheet.png                 … 既存 promodeler/contact_sheet.py を再利用
```

装備品（鞄・眼鏡・時計・スマホ・名札・バックパック）は従来どおり `assets/props/*.py` → Blender → GLB で作り、
Recipe の `accessories[].source` から参照し、Unity 側がソケットに装着する（原案 §23, §30）。

### 2.1 責務分担

| 責務 | 担当 | 根拠 |
| --- | --- | --- |
| 設計書 → Recipe 変換、Recipe 検証、寸法整合性検証、カタログ ID・ライセンス検証、seed 付きランダム生成、LLM 生成 | `promodeler/character/`（Python） | Unity なしで単体テストできる。既存の `ModelingError(code, message)` 流儀で失敗を明示 |
| 寸法 → DNA 解法、素体・髪・衣服の組み立て、実メッシュ計測、検証レンダ、FBX/GLB/prefab 書き出し、GUI 編集 | Unity プロジェクト（C#） | UMA の API に触るのはここだけ（原案 §10, §11） |
| 装備品・小物・部屋・建築の生成 | 従来の `assets/*.py` + Blender | 既存の強み |
| カタログ用アセットの変換（MakeHuman CC0 → UMA スロット、LOD、法線・UV 検証） | Blender（`tools/`） | 原案 §22 |
| 参照人体の計測、設計書寸法の矛盾検出 | `promodeler/human/mhr.py` | 既に差分可能計測がある |

---

## 3. リポジトリ構成（差分）

```
promodeler/
  character/                     # 新規。純 Python。bpy / torch を import しない
    __init__.py
    recipe.py                    # dataclass 群（CharacterRecipe, Body, Face, Appearance, Garment, Accessory, ...）
                                 #   validate(), to_json(), from_json(), canonical_dump(), recipe_hash()
    schema.py                    # JSON Schema の生成（dataclass → schema）。schemas/character_recipe.schema.json を出力・照合
    from_blueprint.py            # promodeler-blueprint/1.0 (humanoid / wearable) → CharacterRecipe / OutfitRecipe
    catalog.py                   # character/catalog/*.json の読込、ID 解決、slot/race 互換性、ライセンス許可判定
    presets.py                   # character/presets/*.json の適用（部分 Recipe のマージ）
    randomize.py                 # seed 決定的なランダム Recipe（人体計測の事前分布 × カタログ）
    prompt.py                    # LLM → Recipe（anthropic、JSON Schema 制約付き）。既存 critique.py の認証を共用
    consistency.py               # 寸法整合性（楕円周長 vs 周長、身長比の範囲）。任意で MHR フィットを呼び参照計測を付与
    bridge.py                    # Unity のバッチ起動、build.json の回収、キャッシュ鍵、コンタクトシート
    check.py                     # 設計書 × Recipe × build.json の照合表（tools/blueprint_check.py の一般化）
  human/mhr.py                   # 既存。consistency.py から任意で呼ぶ。API 変更なし
  cli.py                         # `character` サブコマンド群と `generate` を追加。doctor に Unity 検出を追加
  contact_sheet.py               # 既存。build.json の renders を読めるようにする（キー名を report.json と同じにする）

schemas/
  character_recipe.schema.json   # Recipe の JSON Schema（Python と C# の共通契約、CI で dataclass と一致を検査）
  character_build.schema.json    # build.json のスキーマ
  asset_catalog.schema.json

character/                       # Git 管理のデータ。大容量バイナリは置かない
  catalog/
    skin.json  hair.json  eyes.json  eyebrows.json  facial_hair.json
    wardrobe.json  footwear.json  accessories.json
  presets/
    jp_adult_male.json  jp_adult_female.json  office.json  karate.json ...
  recipes/
    woman.json  businessman.json  businesswoman.json ... passerby-g.json      # 設計書 15 体
  outfits/
    haruka-karate-uniform.json  haruka-riding-suit.json                      # 設計書 36, 37

unity/ProModelerCharacterCreator/   # Unity サブプロジェクト（Library/ Temp/ Logs/ は gitignore）
  Packages/manifest.json
  Assets/ProModeler/ ...            # 9 章

assets/props/                     # 装備品（briefcase_slim.py, tote.py, glasses.py, ...）。従来の Blender 生成
assets/haruka.py                  # 凍結。Blender 参照経路として残す（15 章）

build/character/<id>/<hash>/      # Unity ビルド出力（gitignore 済みの build/ 配下）
  recipe.json  build.json  unity.log  model.fbx  model.glb  renders/<render-key>/*.png  contact_sheet.png

tools/
  blueprint_check.py              # 既存。内部を promodeler/character/check.py に委譲
  uma_slot_from_glb.py            # Blender: GLB/FBX 衣服・髪 → UMA スロット向け FBX（トポロジ・ウェイト検証込み）
  mhr_dump_lod1.py                # 既存
```

`pyproject.toml` の optional-dependencies に `character = ["jsonschema"]` を追加する（それ以外は標準ライブラリ）。
LLM 生成は既存の `critique = ["anthropic"]` を共用する。

---

## 4. CharacterRecipe スキーマ（`promodeler-character/1.0`）

設計原則:

1. **語彙は設計書と同じ**。`barefoot_height_m` のように単位接尾辞を付け、値はメートル・度・sRGB 16 進。設計書から機械変換できることを保証する。
2. **UMA 固有名を持たない**（原案 §8）。DNA 名・スロット名・オーバーレイ名は Unity 側の解決表に閉じる。
3. **カタログ参照は ID**（原案 §20）。ID の存在・スロット互換・ライセンスは Python 側で検証する。
4. **生成元と版を残す**（原案 §18, §19）。`source`, `seed`, `schema`, `generator_version`, `catalog_version`。
5. **設計書の非構造情報も捨てない**。`descriptors`（文）を保持し、LLM・人の判断・将来の顔生成に使う。
6. **検証目標を Recipe に含める**。`acceptance`, `target`, `tolerances_m` はビルド結果の判定基準として Unity 側と `check` が読む。

### 4.1 例: 22-businessman から生成した Recipe（抜粋。`…` は設計書からの転記省略）

```json
{
  "schema": "promodeler-character/1.0",
  "id": "businessman",
  "name": "高橋直人・ビジネスマン",
  "seed": 22,
  "source": {
    "kind": "blueprint",
    "path": "blueprints/japan-realistic-v1/22-businessman/blueprint.json",
    "sha256": "…",
    "generator_version": 1,
    "catalog_version": "2026.09"
  },
  "identity": {
    "fictional": true,
    "sex": "male",
    "age": 35,
    "descriptors": ["短い黒髪", "左分け", "面長", "薄いひげ跡"]
  },
  "base": { "skeleton": "humanoid_a_pose", "race": "human_male" },
  "body": {
    "measurements_m": {
      "barefoot_height": 1.76,
      "inseam": 0.80,
      "shoulder_width": 0.44,
      "foot_length": 0.265,
      "head_height": null,
      "circumferences": { "chest": 0.96, "waist": 0.83, "hip": 0.95 },
      "cross_sections": [
        { "landmark": "chest", "height": 1.375, "width": 0.3264, "depth": 0.284 },
        { "landmark": "waist", "height": 1.166, "width": 0.2822, "depth": 0.2456 },
        { "landmark": "hip",   "height": 1.045, "width": 0.323,  "depth": 0.2811 }
      ]
    },
    "shape": { "muscle": 0.45, "body_fat": 0.40, "posture": 0.50 },
    "tolerances_m": { "barefoot_height": 0.002, "circumference": 0.005, "length": 0.005 },
    "reference_fit": null
  },
  "face": {
    "metrics_m": { "eyeball_diameter": 0.024, "iris_diameter": 0.0115, "mouth_width": null, "nose_width": null },
    "shape": {
      "face_length": 0.70, "jaw_width": 0.45, "chin_size": 0.50, "cheek_width": 0.50,
      "nose_width": 0.50, "nose_length": 0.50, "nose_bridge": 0.50,
      "eye_size": 0.50, "eye_spacing": 0.50, "eye_tilt": 0.50,
      "mouth_width": 0.50, "lip_thickness": 0.45, "brow_height": 0.50, "forehead_height": 0.55
    },
    "descriptors": ["面長", "薄いひげ跡"]
  },
  "appearance": {
    "skin": { "preset": "skin_jp_light_02", "base_color_srgb": "#DFC1AD", "roughness": [0.35, 0.58] },
    "hair": { "style": "hair_short_side_part_l_01", "base_color_srgb": "#28201D", "length_m": null },
    "eyebrows": { "style": "brow_natural_m_01", "color_srgb": "#28201D" },
    "eyes": { "iris_color_srgb": "#574335", "sclera_color_srgb": "#ECE8E4" },
    "facial_hair": { "style": "stubble_light_01", "color_srgb": "#28201D" },
    "teeth": { "preset": "teeth_natural_01", "base_color_srgb": "#DCD4C3" }
  },
  "wardrobe": [
    { "slot": "inner",    "catalog_id": "shirt_dress_white_01",  "blueprint_garment": "inner",
      "material": { "base_color_srgb": "#ECE9E0", "roughness": [0.65, 0.85] },
      "finished_measurements_m": { "chest_circumference": 1.06, "back_length": 0.64, "thickness": 0.0006 },
      "deformation": "cloth", "construction": "…" },
    { "slot": "upper",    "catalog_id": "suit_jacket_2button_01", "blueprint_garment": "upper",
      "material": { "base_color_srgb": "#243247", "roughness": [0.65, 0.85] },
      "finished_measurements_m": { "back_length": 0.73, "chest_circumference": 1.08, "shoulder_width": 0.465, "sleeve_length": 0.61 },
      "deformation": "cloth", "construction": "…" },
    { "slot": "lower",    "catalog_id": "slacks_01", "blueprint_garment": "lower",
      "material": { "base_color_srgb": "#243247", "roughness": [0.65, 0.85] },
      "finished_measurements_m": { "waist_circumference": 0.86, "hip_circumference": 1.03, "inseam": 0.775, "hem_circumference": 0.34 },
      "deformation": "cloth", "construction": "…" },
    { "slot": "neck",     "catalog_id": "necktie_01", "blueprint_garment": "tie",
      "material": { "base_color_srgb": "#244839", "roughness": [0.6, 0.85] },
      "finished_measurements_m": { "length_visible": 0.47, "blade_width": 0.075, "thickness": 0.001 },
      "deformation": "pinned_cloth", "construction": "…" },
    { "slot": "footwear", "catalog_id": "oxford_lace_black_01",
      "material": { "base_color_srgb": "#302C29", "roughness": [0.28, 0.52] },
      "sole_height_m": 0.025, "heel_height_m": 0.025, "internal_length_m": 0.277, "deformation": "rigid_skinned" }
  ],
  "accessories": [
    { "id": "briefcase",
      "source": { "kind": "promodeler_asset", "path": "assets/props/briefcase_slim.py", "build_hash": null },
      "socket": "hand_r", "size_xyz_m": [0.40, 0.29, 0.07],
      "physics": { "method": "…", "max_swing_deg": 15 }, "detail": "黒革、持ち手高さ100mm、ファスナー2本" }
  ],
  "animation": {
    "rest_pose": "a_pose_35deg",
    "limits_deg": { "elbow_flexion": [0, 135], "knee_flexion": [0, 130], "hip_flexion": [0, 115],
                    "shoulder_raise": [0, 160], "neck_yaw": [-65, 65], "finger_curl": [0, 90] },
    "face_shapes": ["blink_l", "blink_r", "jaw_open", "smile", "vowel_a", "vowel_i", "vowel_u", "vowel_e", "vowel_o"],
    "clips": [
      { "id": "idle", "duration_s": 4, "loop": true, "description": "呼吸、瞬き、視線" },
      { "id": "walk", "duration_s": 1.2, "loop": true, "description": "左右足接地、1周期の移動1.1m、腕振り" },
      { "id": "sit",  "duration_s": 3, "loop": false, "description": "座面高0.43mへ着座。靴底の高さを接地IKに含める。" }
    ]
  },
  "physics": { "common": "…", "clothing": "…", "breast": "…", "hair": "…", "accessories": "…", "solve_order": ["…"] },
  "target": { "engine": "unity_hdrp", "triangles_lod0_max": 110000, "texture_resolution_max": 4096,
              "texel_density_px_per_m": 1024, "lod_ratios": [1, 0.5, 0.2, 0.08],
              "triangles_by_part": { "body": 35000, "hair": 20000, "clothing": 35000, "shoes_accessories_eyes": 20000 },
              "texture_resident_budget_mib": 160 },
  "acceptance": ["裸足身長±2mm、指定円周±5mmを実メッシュで計測。", "…"]
}
```

### 4.2 ブロック別の規約

| ブロック | 規約 |
| --- | --- |
| `base.skeleton` | `humanoid_a_pose` 固定（Unity Humanoid 互換、A ポーズ 35°、+Y 上、+Z 正面、解剖学的右 = −X。設計書と同じ）。`race` は `human_male` / `human_female` / 将来 `mhr_female` 等。UMA の RaceData 名は Unity 側の表で対応付ける |
| `body.measurements_m` | 設計書 `dimensions` からの機械転記。欠けは `null`。`cross_sections` は `landmark` に `chest/bust/underbust/waist/hip/shoulders/neck/head` |
| `body.shape` | 寸法で表現できない意味値 0..1。既定は `presets`（性別・年齢）から。GUI で編集する主対象 |
| `body.tolerances_m` | 受入判定の許容差。設計書の QA 文（身長 ±2 mm、周長 ±5 mm）から抽出。未記載なら既定 |
| `body.reference_fit` | 任意。`character consistency --mhr` が書く MHR フィット結果 `{ "solver": "mhr", "fit_version": 18, "measured_m": {...}, "residuals_m": {...} }`。Unity は無視し、`check` が参照する |
| `face.metrics_m` | 設計書に数値があるもののみ（眼球径・虹彩径・口幅・鼻幅）。UMA の DNA が直接表現できない値は Unity 側で近似し残差を報告 |
| `face.shape` | 0..1、0.5 が素体中立。項目名は解剖学の意味名で固定（表は 10 章）。設計書の文（面長 → `face_length` 0.7）は `from_blueprint` の語彙表で初期値化し、根拠として `descriptors` を残す |
| `appearance.*` | `preset`/`style` はカタログ ID、色は sRGB 16 進（設計書 `materials[].base_color_srgb` から）。`roughness` は範囲 [min, max]（設計書と同じ） |
| `wardrobe[]` | `slot` は固定列挙 `inner / upper / lower / dress / outer / neck / waist / hands / footwear / headwear / socks`。`catalog_id` はカタログの `slot` と一致必須。`finished_measurements_m` は Unity では **検証目標**（着せた衣服の実測周長と比較）で、生成には使わない |
| `accessories[].source` | `{"kind": "catalog", "catalog_id": ...}` または `{"kind": "promodeler_asset", "path": "assets/props/x.py", "build_hash": ...}`。後者は `character build` が先に `promodeler build` を走らせて GLB を用意する。`socket` は `hand_l / hand_r / wrist_l / wrist_r / shoulder_l / shoulder_r / back / waist / head / face / chest` |
| `animation.clips` | 設計書 `clips` の転記。Unity 側は同 ID の汎用クリップ（Humanoid 互換）を割り当て、`description` は検証者向け。ここでクリップの中身は定義しない（アニメグラフはエンジン側、既存設計 §8.3 と同じ） |
| `physics`, `target`, `acceptance` | 設計書からの透過転記。既存 `Asset.extras` と同じ「GLB に入らない納品情報」 |

### 4.3 OutfitRecipe（`kind: wearable` 設計書 36・37）

```json
{
  "schema": "promodeler-outfit/1.0",
  "id": "haruka-karate-uniform",
  "base_character": "woman",
  "body_policy": "keep",
  "wardrobe": [ { "slot": "inner", "catalog_id": "sports_inner_white_01", "…": "…" },
                { "slot": "upper", "catalog_id": "karate_gi_jacket_01", "…": "…" },
                { "slot": "lower", "catalog_id": "karate_gi_pants_01", "…": "…" },
                { "slot": "waist", "catalog_id": "karate_belt_black_01", "controls": { "belt_tails_m": [0.3, 0.3], "waist_wraps": 2 } },
                { "slot": "footwear", "catalog_id": null } ],
  "hair_override": { "style": "hair_long_braided_back_01" },
  "extra_bones": ["belt-end.L", "belt-end.R"],
  "clips_extra": [ { "id": "karate", "duration_s": 8, "loop": false, "description": "…" } ],
  "physics": "…", "target": "…", "acceptance": "…"
}
```

`promodeler character build woman --outfit haruka-karate-uniform` は、基底 Recipe の `wardrobe` を丸ごと置換し、
`hair.style` のみ上書きし、`body` には触れない（設計書 `fit.body_morph_policy`「衣服に合わせて胸や腰を縮小しない」）。
結果のハッシュは基底 Recipe と Outfit の両方から取る。

### 4.4 JSON Schema と C# の同期

`schemas/character_recipe.schema.json` を Python の dataclass から生成し、CI で「生成結果 == コミット済みスキーマ」を検査する。
Unity 側の DTO（`CharacterRecipe.cs`）は Newtonsoft.Json の SnakeCase 命名で同じ構造を持ち、
`Assets/ProModeler/Tests/RecipeRoundTripTests.cs` が `character/recipes/*.json` を全件読み書きして差分ゼロを確認する。
これが「Unity と promodeler を直接依存させない」（原案 §4）の実体である。

---

## 5. 設計書 → Recipe 変換（`from_blueprint.py`）

| 設計書 (`promodeler-blueprint/1.0`) | Recipe | 備考 |
| --- | --- | --- |
| `id`, `name`, `kind` | `id`, `name`; `kind` で Character / Outfit を選択 | `kind` がそれ以外なら `ModelingError("character.kind")` |
| `identity` (`sex`, `age`, `fictional`, `face_shape_hair`, `outfit_palette`) | `identity`; `face_shape_hair` は「、」分割で `descriptors` | 05-woman は `identity` を持たないので `summary`/`dimensions.age` から補う |
| `dimensions.barefoot_height_m` 等、`body_circumferences_m`, `cross_sections` | `body.measurements_m` | `bust` と `chest` は別キーのまま保持（女性設計書は bust/underbust、男性は chest） |
| `dimensions.shoe_sole_m`, `footwear` | `wardrobe[slot=footwear]` の `sole_height_m` 等、`barefoot: true` なら footwear なし | 靴込み身長は Unity 側が「身体ごと持ち上げる」（設計書 CHARACTER-IMPLEMENTATION の規則） |
| `materials[]` (`skin`, `hair`, `eye`, `teeth`, `top`, `bottom`, `inner`, `accent`, `leather`, `rubber`, `metal`) | `appearance.*.base_color_srgb` / `wardrobe[].material` | `garments[].material` が `materials[].id` を指すので結合できる |
| `garments[]` (`id`, `material`, `finished_measurements_m`, `construction`, `deformation`) | `wardrobe[]` | `slot` は `id` の語彙表（`upper→upper`, `lower→lower`, `inner→inner`, `tie→neck`, `apron→waist`, `skirt→lower`, `belt→waist`, `gi-jacket→upper`, `gi-pants→lower`, `gloves→hands`, `boots→footwear`, `support→inner`）。`catalog_id` は **語彙表 + 設計書の name の一致検索** で仮決めし、見つからなければ `null` にして `warnings` に出す |
| `accessories[]` (`id`, `size_xyz_m`, `detail`, `attachment`) | `accessories[]` | `attachment` の文から `socket` を推定（「手」→`hand_r`、「肩」→`shoulder_l`、「手首」→`wrist_l`、「頭」→`head`、「顔」→`face`）。推定できなければ `null` + warning |
| `rig.limits_deg`, `rig.basis`, `rig.face` | `animation.limits_deg`, `animation.rest_pose`, `animation.face_shapes` | 設計書 `rig.joints`（29 関節）は Unity Humanoid リグには使わない。骨位置は素体側が決める |
| `clips[]` | `animation.clips` | そのまま |
| `physics`, `target`, `qa`, `details` | `physics`, `target`, `acceptance`（`qa`）、`face.descriptors` へ `details` の顔記述 | 透過 |
| `checks` | 転記しない | 検証状態は `build.json` と `check` の出力が持つ |
| （wearable）`fit.base_id`, `fit.hair_variant`, `garment_controls`, `rig.extra_bones` | `base_character`, `hair_override`, `wardrobe[].controls`, `extra_bones` | |

変換は決定的で、同じ設計書からは同じ Recipe を出す（seed は設計書番号）。
`character/recipes/<id>.json` が既に存在する場合は上書きせず、`--force` か `--out` を要求する（Recipe が正であるため）。
`promodeler character diff <id>` が「現在の Recipe」と「設計書から再生成した Recipe」の差分を出し、GUI 編集の追跡に使う（原案 §12）。

---

## 6. 寸法の整合性検証（`consistency.py`）

Unity を起動する前に Python だけで落とせる失敗を落とす。既存の MHR フィットで判明した「設計書の周長と断面寸法は両立しない」
（05-woman のヒップ: 楕円 0.285×0.205 の周長 0.78 m に対し周長目標 0.87 m）を、全 15 体で機械的に検出する。

1. **静的検査**: 各 `cross_sections` の楕円近似周長と `circumferences` の差を出す。差が 3% を超えたら `warnings` に `measurements.sectionVsCircumference`。身長比（股下/身長、肩幅/身長、足長/身長）が成人の範囲外なら警告。
2. **MHR 参照フィット（任意、`--mhr`）**: `promodeler.human.mhr.fitted_body(targets)` を Recipe の寸法で呼び、`measured_m` と残差を `body.reference_fit` に書く。これは「そのような人体が存在しうるか」の物理的な確認で、UMA の表現力とは独立。torch がなければスキップし、その旨を出す。
3. **優先規則の明文化**: 周長 > 断面寸法 > 文。断面寸法は Unity 側でも **計測・報告のみ** で解法の目標に入れない（memory: blueprint-05-woman-conflicts と同じ判断）。

---

## 7. Python 側モジュール API

```python
# promodeler/character/recipe.py
@dataclass(frozen=True)
class CharacterRecipe:
    schema: str; id: str; name: str; seed: int
    source: Source; identity: Identity; base: Base; body: Body; face: Face
    appearance: Appearance; wardrobe: tuple[Garment, ...]; accessories: tuple[Accessory, ...]
    animation: Animation; physics: dict; target: dict; acceptance: tuple[str, ...]
    def validate(self, catalog: Catalog | None = None) -> list[Warning]   # ModelingError で失敗、Warning は返す
    def to_json(self) -> dict
    @classmethod
    def from_json(cls, data: dict) -> "CharacterRecipe"

def canonical_dump(recipe: dict) -> str          # core.recipe.dump_recipe と同じ規約（sort_keys, ASCII, no NaN）
def recipe_hash(recipe: dict, **environment) -> str   # core.recipe.recipe_hash を再利用。environment = unity, uma, hdrp, catalog_version

# promodeler/character/from_blueprint.py
def load_blueprint(path) -> dict                                   # schema を確認
def character_from_blueprint(blueprint: dict, catalog: Catalog, seed: int | None = None) -> tuple[CharacterRecipe, list[Warning]]
def outfit_from_blueprint(blueprint: dict, catalog: Catalog) -> tuple[OutfitRecipe, list[Warning]]

# promodeler/character/catalog.py
class Catalog:
    def __init__(self, root: Path = "character/catalog")            # 全カテゴリを読む。version を持つ
    def get(self, catalog_id: str) -> CatalogEntry                  # なければ ModelingError("catalog.unknown")
    def find(self, category: str, slot: str | None, tags: set[str], race: str) -> list[CatalogEntry]
    def check(self, entry: CatalogEntry, slot: str, race: str, license_policy: str) -> list[Warning]

# promodeler/character/bridge.py
def find_unity() -> str                                             # PROMODELER_UNITY > Unity Hub の既定パス（Editor バージョンは ProjectVersion.txt に従う）
def build(recipe_path, outfit_path=None, out_root="build/character", force=False, render=None, timeout=1800) -> CharacterBuildResult
    # 1) accessories の promodeler_asset を promodeler.build.build() で先にビルドし GLB パスと hash を解決
    # 2) recipe.json（解決済み）を out_dir に書く  3) Unity をバッチ起動  4) build.json を読む
    # 5) renders があれば contact_sheet.make_contact_sheet(build_json, out_dir / "contact_sheet.png")

# promodeler/character/check.py
def compare(blueprint: dict | None, recipe: CharacterRecipe, build_json: dict | None) -> CheckTable   # 行 = 項目, 目標, 実測, 差, 許容判定
```

`bridge.build` の出力先は `build/character/<id>/<hash12>/`、`hash = recipe_hash(recipe + outfit, unity=, uma=, hdrp=, catalog_version=)`。
既存の `promodeler.build.build` と同じく、成功済み `build.json` があれば `cached=True` で返す。

---

## 8. CLI

既存のサブコマンドは変更しない。追加は次のとおり。

```sh
python -m promodeler doctor                                # 追加: unity: <path> / version、uma: <version>（manifest.json から）、catalog: <version>
python -m promodeler generate blueprints/japan-realistic-v1/22-businessman/blueprint.json
                                                           # kind=humanoid → character recipe + character build
                                                           # kind=wearable → outfit recipe（基底が必要なので build はしない）
                                                           # それ以外 → 「assets/<id>.py を書いて promodeler build」と案内して終了コード 2

python -m promodeler character recipe <blueprint.json> [--out character/recipes/<id>.json] [--force] [--seed N]
python -m promodeler character validate <recipe.json|id> [--mhr]      # スキーマ、カタログ、ライセンス、寸法整合性
python -m promodeler character build <id> [--outfit <outfit-id>] [--force] [--views front,side,back,face] [--no-render] [--formats fbx,glb]
python -m promodeler character check <id> [--build <dir>]             # 設計書 × Recipe × build.json の照合表
python -m promodeler character diff <id>                              # Recipe と設計書再生成との差分
python -m promodeler character random --preset jp_adult_female --count 20 --seed 100 --out character/recipes/generated/
python -m promodeler character prompt "20代女性冒険者。小柄で細身。肩までの黒髪。" --preset jp_adult_female --out character/recipes/adventurer.json
python -m promodeler character edit <id>                              # Unity Editor を GUI で起動し Recipe を開く（原案 §14）
python -m promodeler character catalog list [--category wardrobe --slot upper --race human_male]
```

終了コードは既存と同じ（0 成功、1 ビルド失敗、2 `ModelingError`、3 実行環境なし）。Unity が見つからない場合は
`UnityNotFound`（3）で、`PROMODELER_UNITY` の設定方法を出す。

---

## 9. Unity 側（`unity/ProModelerCharacterCreator/`）

### 9.1 前提と選定

| 項目 | 決定 | 理由・注意 |
| --- | --- | --- |
| Unity | 6000.x LTS（バージョンは初回セットアップ時に `ProjectVersion.txt` で固定） | 設計書 `target.engine` は Unity / HDRP |
| レンダーパイプライン | HDRP | 設計書指定。UMA の HDRP 対応シェーダ（UMA HDRP Shader パック）を導入する。**検証レンダは Intel iGPU で HDRP が動くかを M10 の最初に実測**し、動かなければ検証レンダのみ URP プロジェクトに分ける |
| キャラクタ基盤 | UMA 2.13 系（MIT） | 原案 §10。素体 = UMA の `HumanMale` / `HumanFemale` レース。DNA は骨スケール（DynamicDNA skeleton modifier）で衣服にも自動追従する点が、MHR 体型係数（ブレンドシェイプ）より衣装カタログと相性が良い |
| JSON | `com.unity.nuget.newtonsoft-json`、SnakeCase 命名 | `JsonUtility` は snake_case と null を扱いにくい |
| 書き出し | FBX: `com.unity.formats.fbx`。GLB: UnityGLTF（書き出し対応）。加えて Addressables 登録済み prefab | 設計書の納品物「GLB（形状・PBR・ベイクした骨アニメ）」に対応。glTFast は読込専用なので選ばない |
| アセット配信 | Addressables（原案 §20） | カタログ `runtime.addressable` キーで解決 |
| 物理 | Recipe の `physics` を **設定アセット（ScriptableObject）として書き出す** に留め、クロス/髪/胸の実装（Magica Cloth 2 等、有償）は本設計の範囲外 | 設計書 CHARACTER-IMPLEMENTATION と同じ「GLB 単体で物理は動かない」 |

### 9.2 構成

```
Assets/ProModeler/
  Runtime/
    Recipe/        CharacterRecipe.cs  OutfitRecipe.cs  RecipeLoader.cs  RecipeWriter.cs  RecipeValidator.cs
    Runtime/       ICharacterRuntime.cs  UMACharacterRuntime.cs            # 原案 §11 のインターフェース
    Resolve/       BodyResolver.cs（寸法→DNA、10 章）  FaceResolver.cs（face.shape→DNA 表）
                   AppearanceResolver.cs（色→オーバーレイ tint / テクスチャ選択）  WardrobeResolver.cs（catalog_id→UMA wardrobe recipe）
                   AccessoryResolver.cs（GLB 読込 → ソケット装着）
    Measure/       BodyMeasurer.cs（10.2）  GarmentMeasurer.cs（着衣後の周長）  TriangleBudget.cs
    Catalog/       AssetCatalog.cs（character/catalog/*.json を読む。Python と同じファイル）  LicensePolicy.cs
    Sockets/       HumanoidSockets.cs（Humanoid ボーン → ソケット位置・向きの表）
  Editor/
    Batch/         CharacterBatchBuilder.cs（-executeMethod のエントリ。build.json を必ず書く）
    Calibration/   DnaCalibrationTool.cs（10.1）
    Render/        VerificationRenderer.cs（front/side/back/perspective/face/hand の固定カメラ。shaded と clay）
    Export/        CharacterExporter.cs（FBX、GLB、prefab、PhysicsSettings.asset）
    UI/            CharacterEditorWindow.cs（Face/Body/Hair/Skin/Wardrobe タブ、Save で Recipe のみ更新。原案 §14）
  Tests/
    EditMode/      RecipeRoundTripTests.cs  BodyMeasurerTests.cs  BodyResolverTests.cs
  Generated/       （gitignore）ビルドが作る prefab / material
```

### 9.3 バッチ実行契約

```
Unity.exe -batchmode -projectPath unity/ProModelerCharacterCreator
          -executeMethod ProModeler.Editor.CharacterBatchBuilder.Build
          -recipe <abs path>/recipe.json [-outfit <abs>/outfit.json] -out <abs>/build/character/<id>/<hash>
          -views front,side,back,face -passes shaded,clay -logFile <out>/unity.log -quit
```

- `-nographics` は付けない（検証レンダに GPU が必要）。`--no-render` のときだけ付ける。
- 例外時も `build.json` を `status: failed`, `error: {code, message, stack}` で必ず書き、非ゼロで終了する（既存 kernel `entry.py` と同じ契約）。
- 1 プロセス 1 Recipe。並列化は promodeler 側でプロセスを並べる。

### 9.4 `build.json`（`schemas/character_build.schema.json`）

```json
{
  "status": "ok",
  "recipe_hash": "…",
  "environment": { "unity": "6000.0.xx", "hdrp": "17.x", "uma": "2.13.x", "catalog_version": "2026.09" },
  "resolved": {
    "race": "HumanMale",
    "dna": { "height": 0.63, "legsSize": 0.55, "…": "…" },
    "iterations": 6,
    "residuals_m": { "barefoot_height": 0.001, "inseam": -0.004, "shoulder_width": -0.011, "chest": 0.006, "waist": -0.003, "hip": 0.004 }
  },
  "measured_m": { "barefoot_height": 1.761, "inseam": 0.796, "shoulder_width": 0.429, "foot_length": 0.268,
                  "chest": 0.966, "waist": 0.827, "hip": 0.954,
                  "chest_width": 0.331, "chest_depth": 0.262, "…": "…",
                  "garments": { "upper": { "chest_circumference": 1.07 }, "lower": { "hem_circumference": 0.35 } } },
  "parts": { "body": { "triangles": 31200 }, "hair": { "triangles": 18400 }, "upper": { "triangles": 14100 }, "…": "…" },
  "totals": { "triangles": 96300, "materials": 9, "texture_resident_mib": 142 },
  "wardrobe": [ { "slot": "upper", "catalog_id": "suit_jacket_2button_01", "resolved": "character/wardrobe/suit_jacket_2button_01", "fitted": true } ],
  "accessories": [ { "id": "briefcase", "source": "assets/props/briefcase_slim.py", "socket": "hand_r", "attached": true } ],
  "renders": [ { "view": "front", "pass": "shaded", "path": "…/renders/ab12cd34/front.png", "written": true, "seconds": 1.2 } ],
  "exports": { "fbx": { "path": "…/model.fbx", "written": true, "bytes": 0 }, "glb": { "…": "…" }, "prefab": "Assets/ProModeler/Generated/businessman.prefab",
               "physics_settings": "Assets/ProModeler/Generated/businessman.physics.asset" },
  "warnings": [ { "code": "resolve.residual", "message": "shoulder_width residual -11 mm exceeds tolerance 5 mm (no independent DNA; see calibration)" },
                { "code": "wardrobe.missing", "message": "slot neck: necktie_01 not in catalog; slot left empty" } ],
  "seconds": 41.8
}
```

`renders` と `warnings` のキー名は既存 `report.json` と同じにし、`promodeler/contact_sheet.py` と `cli.print_report` の
ロジックを再利用する。

---

## 10. 寸法 → DNA の解法と実メッシュ計測

原案は「SemanticParameterResolver が意味値を DNA に変換する」（§8）としか書いていない。本プロジェクトの「正確に」を満たすため、
解法を **計測に基づく閉ループ** にする。

### 10.1 校正（`DnaCalibrationTool`、レースごとに一度）

1. レースの中立体（全 DNA 0.5）を組み、`BodyMeasurer` で全計測を取る。
2. 各 DNA を 0.0 / 0.25 / 0.75 / 1.0 に振って計測差分を記録し、`character/calibration/<race>.json` に保存
   （計測 × DNA の区分線形ヤコビアン）。UMA の既定 DNA のうち身体寸法に効くもの: `height`, `legsSize`, `armLength`, `forearmLength`,
   `upperWeight`, `lowerWeight`, `upperMuscle`, `lowerMuscle`, `waist`, `belly`, `gluteusSize`, `breastSize`, `feetSize`, `headSize`, `neckThickness`。
3. **独立 DNA がない寸法**（肩幅、胴の長さ、頭高）には UMA の DynamicDNA に **骨スケール修飾子を追加した独自 DNA**
   （`shoulder_width` → 左右 Clavicle の X スケール、`torso_length` → Spine 群の Y スケール、`head_height` → Head の Y）を定義し、
   同じ手順で校正する。これは UMA 標準の拡張手段で C# 変更なしに設定できる。

### 10.2 計測（`BodyMeasurer`、`promodeler/human/mhr.py::MHRModel.measure` と同じ定義）

| 計測 | 定義（両実装で同一にする） |
| --- | --- |
| `barefoot_height` | 素体メッシュの y 最大 − y 最小（靴なし、A ポーズ） |
| `inseam` | 正中線 (|x| < 2 cm) の 40–65% 高さ帯で最も低い頂点の高さ − 床 |
| `shoulder_width` | 肩ランドマーク高さ（身長 × 1.34/1.6）の **腕を除いた胴断面の x 幅**（関節間距離ではない。memory: blueprint-05-woman-conflicts） |
| `foot_length` | 足首より下の頂点の z 幅 |
| `chest/bust/underbust/waist/hip` | ランドマーク高さの水平面と胴エッジの交点を角度順に結んだ折れ線長。腕・手のボーンウェイトが支配的な頂点を含むエッジは除外 |
| `*_width`, `*_depth` | 同断面の x / z 幅（報告のみ） |
| `head_height` | 頭頂 − Head ボーン位置 + 3 cm（MHR と同じ補正） |

ランドマーク高さは設計書に `cross_sections[].height_m` があればそれを使い、なければ身長比で置く。

### 10.3 解法（`BodyResolver`）

1. 初期値: 校正ヤコビアンの線形解（最小二乗、DNA を [0, 1] にクランプ）。
2. UMA でメッシュを再構築（`UMAData` 更新、約 50–100 ms）→ `BodyMeasurer` で計測 → 残差 → ヤコビアンで更新。3–8 反復で収束させ、
   `resolved.iterations` と `residuals_m` を出す。
3. 身長は最後に **ルートの一様スケール** で ±2 mm に合わせてよい（設計書の受入基準が身長 ±2 mm で最も厳しく、UMA の `height` DNA だけでは粒度が粗い）。
   ただし他の寸法比が崩れるので、スケールは 0.98–1.02 に制限し、超える場合は警告。
4. 靴: `footwear.sole_height_m` があれば **身体ごと** 持ち上げ、`standing_shod_height` を報告する。
5. 断面幅・奥行きは目標に入れず計測のみ（6 章）。
6. 収束後も許容差を超える残差は `resolve.residual` 警告として残し、**黙って通さない**（既存の「範囲外はエラー、黙って丸めない」の精神）。

### 10.4 顔（`FaceResolver`）

`face.shape` の意味名 → UMA DNA の固定表（`face_length→headHeight/foreheadSize`, `jaw_width→mandibleSize/jawsSize`, `chin_size→chinSize`,
`cheek_width→cheekSize`, `nose_width→noseWidth`, `nose_length→noseSize`, `nose_bridge→noseCurve`, `eye_size→eyeSize`, `eye_spacing→eyeSpacing`,
`eye_tilt→eyeRotation`, `mouth_width→mouthSize`, `lip_thickness→lipsSize`, `brow_height→foreheadPosition`）。
`face.metrics_m`（眼球径・虹彩径）は眼球オーバーレイ/メッシュの実寸として適用し、`mouth_width` / `nose_width` は
ビルド後に頂点群から計測して残差報告する。UMA の骨ベース顔 DNA は表現力に限りがあるので、
**顔の写実性はカタログ側（肌テクスチャ、眉・まつ毛・髭のメッシュ、眼球）が担う** と割り切る。将来の顔ブレンドシェイプ集は
`race` ごとの拡張として設計上の余地を残す。

---

## 11. アセットカタログとライセンス

`character/catalog/<category>.json`（配列）。Python と Unity が同じファイルを読む。

```json
{
  "id": "suit_jacket_2button_01",
  "category": "wardrobe",
  "slot": "upper",
  "name": "2ボタン・シングルスーツ上着",
  "compatibility": { "races": ["human_male"], "layers_over": ["inner"], "hides": ["torso", "upper_arms"] },
  "runtime": { "uma_wardrobe_recipe": "ProModeler/Wardrobe/SuitJacket2Button01", "addressable": "character/wardrobe/suit_jacket_2button_01" },
  "materials": { "tintable": ["top"], "texture_resolution": 2048 },
  "neutral_measurements_m": { "chest_circumference": 1.06, "back_length": 0.72 },
  "triangles": 13800,
  "license": { "type": "CC0", "source": "https://…", "attribution": null, "redistribution": true },
  "provenance": { "origin": "makehuman_community", "converted_by": "tools/uma_slot_from_glb.py", "converted_at": "2026-10-01" },
  "version": "2026.09",
  "tags": ["business", "jacket", "navy"]
}
```

- **ライセンス方針**は `character/catalog/policy.json` に置く（許可: CC0, Apache-2.0, MIT, 自作。要確認: CC-BY（attribution 必須）。禁止: NC/ND、参照商品の商標）。
  `Catalog.check` が Recipe 検証時に判定し、禁止なら `ModelingError("catalog.license")`。設計書 `references.json` の商品名はカタログに転記しない
  （設計書 README「参照商品のライセンスを成果物へ転記しない」）。
- **供給源**: UMA 同梱（少量・ゲーム品質）、MakeHuman コア資産（CC0、`tools/uma_slot_from_glb.py` で Blender 経由変換）、自作（Blender で作って同ツールで登録）、
  購入資産（`redistribution: false` として Git に入れず Addressables のローカルビルドのみ）。**写実性の上限はこのカタログの品質で決まる**（17 章のリスク 1）。
- **カタログ変換ツール**（Blender、原案 §22 の「Asset Production Tool」）: GLB/FBX 読込 → スケール（m）・+Y 上・A ポーズの確認 → 非マニフォールド・自己交差・UV の数値 QA（既存 `kernel/report.py` を流用）→ UMA レース骨格へのウェイト転写（最近傍、既存 `skin_part_from_file` と同じ手法）→ LOD → FBX 書き出し → カタログ項目の雛形出力。
- `catalog_version` は全カタログファイルの sha256 から計算し、Recipe とビルドキャッシュ鍵に入れる。

---

## 12. 装備品と promodeler の分業（原案 §23, §30）

| 種類 | 作り方 | Recipe 参照 |
| --- | --- | --- |
| 鞄・バックパック・トート・メッセンジャー・ブリーフケース、眼鏡、時計、スマホ、名札、ヘルメット、武器 | `assets/props/<name>.py`（従来の code-first。実寸・PBR・剛体） | `accessories[].source = {"kind": "promodeler_asset", "path": ...}` |
| 身体・顔・髪・衣服・靴・眉・まつ毛・歯 | カタログ + UMA | `appearance.*`, `wardrobe[]` |

`character build` は `promodeler_asset` を先に `promodeler.build.build(path)` でビルドし、`model.glb` のパスと `hash` を解決済み `recipe.json` に埋めて Unity に渡す。
Unity は GLB を読み（UnityGLTF）、`socket` の Humanoid ボーン相対に配置する。装備品の寸法は既に Blender 側の `report.json` で検証済みなので、Unity 側は装着位置と貫通のみ確認する。
既存の `Asset.extras` に `promodeler_socket: {"socket": "hand_r", "grip_offset_m": [...]}` を持たせ、持ち手位置を装備品側が宣言できるようにする（小さな core 拡張、破壊的変更なし）。

---

## 13. 決定性・キャッシュ・バージョン（原案 §18, §19）

| 要素 | 実装 |
| --- | --- |
| Recipe の正規形 | `canonical_dump`（sort_keys、ASCII、NaN 禁止）。既存 `core.recipe.dump_recipe` と同一規約 |
| ビルド鍵 | `recipe_hash(recipe [+ outfit], unity=, hdrp=, uma=, catalog_version=)`。`build/character/<id>/<hash12>/` |
| レンダ鍵 | views / passes / 解像度のみのハッシュで `renders/<key>/`。既存の 2 段キャッシュと同じ |
| seed | `randomize` と `prompt` の乱数は `seed` 派生のみ。UMA 側の乱数は使わない（`resolved.dna` は Recipe と校正表から決まる） |
| 版 | `schema`（Recipe 契約）、`source.generator_version`（変換器）、`catalog_version`（内容）、`environment.*`（Unity/UMA/HDRP）。どれが変わっても再ビルド |
| Git に入れるもの | Recipe、Outfit、Preset、Catalog JSON、Calibration JSON、Unity の Assets/ProModeler と Packages、スキーマ。**入れないもの**: `build/`, Unity `Library/`, 生成 prefab、大容量テクスチャ・メッシュ（Addressables のローカルビルドか LFS の別リポジトリ）（原案 §28） |

---

## 14. 検証（設計書の受入基準に対応）

| 設計書の QA 項目 | 検証手段 | 出力 |
| --- | --- | --- |
| 裸足身長 ±2 mm、周長 ±5 mm を実メッシュで計測 | `BodyMeasurer`（10.2）→ `build.json.measured_m` → `character check` | 照合表の `ok / OVER` |
| 正面・側面・背面で髪型・顔・服・付属品が同一 | `VerificationRenderer`（front/side/back/perspective/face/hand、shaded と clay） | `renders/`, `contact_sheet.png`（既存コードで合成） |
| 指・関節体積・ウェイト | `range_check` 相当のポーズを Humanoid で適用して `--pose` レンダ | 同上 |
| 各 clip を正面/側面で記録 | Unity Recorder で汎用クリップを再生し PNG 連番 → 既存 `promodeler/video.py` で mp4/webp | `renders/<key>/clip_<id>_<view>.mp4` |
| 貫通 0、収束時間 | 物理は範囲外。`physics_settings` の書き出しと「未検証」表示に留める | `check` の該当行は `not_verified` |
| LOD0 三角形予算、テクセル密度、常駐テクスチャ | `TriangleBudget` と `AssetCatalog.materials` から集計 | `build.json.totals`、照合表 |
| 衣服の完成寸法 | `GarmentMeasurer` が着衣後の周長を測り `finished_measurements_m` と比較 | `measured_m.garments`、警告 `garment.measurement` |
| 単位・法線・UV・パーツ ID の再読込照合 | `promodeler character check` が `model.glb` を読み、ノード名 = Recipe の slot/accessory id、Y-up、m 単位を確認（既存 glTF 検査を流用） | 照合表 |

`tools/blueprint_check.py` は Blender ビルド（`report.json`）と Unity ビルド（`build.json`）の両方を受け付けるよう
`promodeler/character/check.py` に一般化し、既存の引数は互換維持する。

---

## 15. 既存コードへの影響

### 15.1 変更するもの

| ファイル | 変更 |
| --- | --- |
| `promodeler/cli.py` | `character` サブコマンド群、`generate`、`doctor` の Unity/UMA/カタログ検出 |
| `promodeler/contact_sheet.py` | `report["renders"]` の読み方はそのまま。build.json を渡せることをテストで保証 |
| `promodeler/core/asset.py` | 変更なし（`Asset.extras` に `promodeler_socket` を入れるのは慣習であり型変更不要） |
| `tools/blueprint_check.py` | 本体を `promodeler/character/check.py` に移し、薄いラッパにする |
| `pyproject.toml` | optional `character = ["jsonschema"]`、`all` に追加 |
| `.gitignore` | `unity/**/Library/`, `unity/**/Temp/`, `unity/**/Logs/`, `unity/**/UserSettings/`, `unity/**/Assets/ProModeler/Generated/` |
| `README.md` | 「人体素体: Meta MHR（M6）」節を「人型キャラクター（M9–M13）」に改め、Blender 人型経路は参照・凍結と明記。Recipe が正である例外規則を書く |
| `Skill/SKILL.md`（`.claude/skills/promodeler/SKILL.md` はこれを参照する薄いファイルなので、description に「人物は Recipe 経路」と一文足すだけ） | 「Human bodies」節を「Characters」節に置換: 人型は `.py` を書かず `character recipe → validate → build → check` を回す。髪・服・靴を `Strands`/`Loft` で作らない。装備品は従来どおり |
| `docs/01-realitizer-analysis-and-design.md` | §6 ロードマップに M9–M13 を追記し、§8.1 の「素体は MHR、それ以外はコード」を本書へのリンクで更新 |

### 15.2 凍結するもの（削除しない）

- `assets/haruka.py`: ビルド可能な状態で残す（回帰テストと Blender 単独レンダの参照）。髪・服・靴・目のコードは拡張しない。
  新しい人型 `.py` アセットは作らない（原案 §29 の「禁止処理」に相当する本プロジェクトの規則）。
- `promodeler/human/mhr.py`: API 維持。用途は 6 章の参照フィットと、将来 MHR をカスタムレースとして Unity に持ち込む場合の素体書き出し（17 章）。

### 15.3 触らないもの

`promodeler/core/*`（asset.py 以外も含め）、`promodeler/kernel/*`、非人型の `assets/*.py`、`blueprints/`（設計書は入力であり編集しない）。

---

## 16. ロードマップ（既存 M0–M8 の続き）

| 段階 | 内容 | 完了判定 |
| --- | --- | --- |
| **M9 Recipe 層（Python のみ）** 完了 2026-09-22 | `promodeler/character/{recipe,schema,from_blueprint,catalog,consistency,check}`、`schemas/*.json`、CLI `character recipe/validate/diff/catalog`、`generate` の振り分け、カタログ雛形（ID とライセンス欄だけ、実体なし）、15 体 + 2 衣装の Recipe 生成、整合性検査結果の一覧、単体テスト（Unity 不要） | `character/recipes/*.json` 17 件がスキーマ検証を通り、`validate --mhr` が設計書間の矛盾を表として出す |
| **M10 Unity MVP（1 体、原案 §31）** | Unity プロジェクト作成、HDRP と UMA 導入、Intel iGPU でのバッチレンダ実測、`RecipeLoader`、`BodyMeasurer`、`DnaCalibrationTool`、`BodyResolver`、UMA 同梱資産だけで `businessman`（男性・スーツに最も近い既定衣装）を組み、`build.json` + front/side/back レンダ + FBX/GLB、`bridge.build`、`character check` | `promodeler character build businessman` が一発で通り、身長 ±2 mm、周長の残差が表に出る。対応パラメータは原案 §31 の 15–20 項目 |
| **M11 寸法精度と全員** | 独自 DNA（肩幅・胴長・頭高）の追加と校正、顔 DNA 表、靴による接地補正、`GarmentMeasurer`、15 体すべてのビルドと照合表、コンタクトシート、`.claude/skills` の更新 | 15 体で身長 ±2 mm、周長 ±1 cm 以内（UMA の限界は残差として明記）。全員のコンタクトシートが並ぶ |
| **M12 カタログと装備・衣装** | `tools/uma_slot_from_glb.py`、MakeHuman CC0 資産の変換と登録（髪 10、上衣 10、下衣 8、靴 6、眉・まつ毛・髭）、肌・眼球テクスチャ、`assets/props/` の装備品 8 点とソケット装着、Outfit 36・37、Addressables、`character edit` GUI（Face/Body/Hair/Skin/Wardrobe、Save は Recipe のみ） | 設計書の衣装語彙の 8 割が `catalog_id` で解決され、`wardrobe.missing` 警告が例外になる。GUI 保存 → `character diff` で差分追跡できる |
| **M13 生成モード** | `presets`（性別・年齢別の人体計測事前分布）、`character random`、`character prompt`（LLM → Recipe、スキーマ制約、カタログ ID の実在検証）、クリップ動画記録、`physics_settings` 書き出し | 1,000 体を seed 決定的に生成して全件 `validate` を通す。プロンプト 1 文から `build` まで人手なし |

M10 の最初に **HDRP のヘッドレスレンダが Intel iGPU で動くか** と **UMA の HDRP シェーダの入手** を確認し、駄目なら検証レンダ用 URP プロジェクトに分ける判断をここで下す。

---

## 17. リスクと対策

1. **写実性の上限はカタログの品質で決まる**。UMA 同梱資産と MakeHuman 資産はゲーム品質で、設計書の「写実・HDRP」には届かない可能性が高い。
   対策: Recipe と Unity 側の解決層をカタログの中身から独立させ（ID 参照のみ）、高品質資産（自作・購入）を後から差し替えられるようにする。
   M12 で「どの程度まで見えるか」を 1 体で判定し、購入資産の要否を判断する。これは原案が想定していないコストであり、先に明記する。
2. **UMA の DNA 空間が設計書寸法に届かない**（例: passerby-c の胸囲 1.12 / 腹囲 1.04、女性 05 のバスト−アンダー差 20 cm）。
   対策: 10.1 の独自 DNA、10.3 の残差報告。MHR 参照フィットで「人体として可能か」を先に見る。それでも届かない場合は設計書側の値を議論する材料にする。
3. **HDRP + Intel iGPU のヘッドレス描画**。動作しない・遅い可能性。対策: M10 冒頭で実測、URP 分離の逃げ道。
4. **Recipe が正であることと code-first の衝突**。GUI 編集で Recipe が設計書から乖離する。対策: `source.sha256` と `character diff`、CI で「設計書再生成との差分がある Recipe」を一覧表示（禁止はしない）。
5. **物理の未実装**。設計書の胸・髪・服の動力学は本設計の範囲外。対策: `physics_settings` の書き出しと `check` の `not_verified` 表示で、未検証を検証済みに見せない（既存設計の「検証の誠実さ」）。
6. **MHR を Unity に持ち込みたくなる誘惑**。フィット済み MHR 素体を UMA のカスタムレースにすれば寸法は正確になるが、45 体型係数のブレンドシェイプ化、126 関節への衣装ウェイト転写、カタログ全件の再フィットが必要で、衣装互換という UMA 採用の利点を失う。**本設計では採らない**。将来やる場合は `base.race = "mhr_female"` として別レースを追加する余地だけ残す。
7. **Unity のバージョン・パッケージ更新**。対策: `ProjectVersion.txt` と `manifest.json` を固定し `environment` をキャッシュ鍵に含める。

---

## 18. 未決事項（実装フェーズで決める）

- Unity 6 の具体的な LTS 番号、UMA の取得元（Asset Store か GitHub）、UMA HDRP シェーダの入手経路。
- GLB 書き出しライブラリ（UnityGLTF を第一候補。スキン + モーフ + アニメーションの書き出し実績を M10 で確認）。
- 顔ブレンドシェイプ（ARKit 52 相当）の供給。UMA 既定レースには無いため、カタログの「顔パック」として扱うか、レース拡張とするか。
- `presets` の人体計測事前分布の出典（日本人成人の公開統計）。
- Addressables のローカル/リモート構成と、購入資産の保管場所（Git LFS 別リポジトリか、ローカル専用か）。

---

## 付録 A. 原案との対応表

| 原案 | 本書 |
| --- | --- |
| §2 二系統分割・§6 Router・§25 Generator Interface | 2 章（`kind` による CLI 振り分け。core に新抽象なし） |
| §3 最重要変更・§29 禁止処理 | 1.2, 15.2（髪・服・靴・目の手続き生成を凍結。人型 `.py` を新規に書かない） |
| §4 システム境界・§26 Unity Bridge | 4 章（Recipe）、7 章 `bridge.py`、9.3 バッチ契約 |
| §5 ディレクトリ | 3 章（`promodeler/character/`, `character/`, `unity/`, `schemas/`, `build/character/`） |
| §7 CharacterRecipe・§8 意味ベース | 4 章（snake_case、寸法はメートル、UMA 名なし） |
| §9 Character Creator 構成・§11 Adapter | 9.2 |
| §10 UMA の役割 | 9.1, 10 章 |
| §12 対話往復・§14 GUI・§27 Interactive と Batch の共通化 | 4.3 以下「Recipe が正」、8 章 `character edit`、9.2 `CharacterEditorWindow`（Batch と同じ `UMACharacterRuntime` を使う） |
| §13 CLI | 8 章 |
| §15 自動生成・§16 AI・§17 Random・§35 Phase 5 | 8 章 `random` / `prompt`、M13 |
| §18 Seed・§19 Version | 13 章 |
| §20 Asset Catalog | 11 章 |
| §21 MakeHuman・§22 Blender の役割 | 11 章（供給源）、`tools/uma_slot_from_glb.py`、15.2（MHR の位置付け） |
| §23 ProModeler で生成するもの・§30 例外 | 12 章 |
| §24 最終構成・§36 採用アーキテクチャ | 2 章 |
| §28 保存するもの | 13 章 |
| §31–§34 MVP・Phase 2–4 | 16 章 M10–M12 |
