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
python -m promodeler character random --seed 100 --count 20 [--sex female] [--style business] [--out build/random]   # 18.10 節（presets は character/presets/anthropometry.json）
python -m promodeler character prompt "20代女性。小柄で細身、丸顔。黒髪のボブ。カフェ店員で七分袖シャツにエプロン。" [--llm anthropic] [--build]   # 18.11 節
python -m promodeler character profile human_female                   # レース中立体のプロファイル（衣服生成用、18.8 節）
python -m promodeler character import-slot --manifest character/garments.json   # promodeler 製衣服 → UMA スロット（18.8 節）
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
   実装では DynamicDNA ではなく `UMACharacterRuntime.Adjusts`（生成後に骸骨へ掛ける骨スケール/オフセット）とし、`character build --probe`
   で校正表 `calibration.json` を出す。鎖骨は UMA 3 の Shoulder ボーンの **ローカル Y** に沿う（X・Z のスケールは肩幅に無反応、Y は
   可動域で −49/+70 mm）。子の Arm ボーンに逆数のスケールを掛けて腕の長さを保つ。各調整は主ボーン（指数 1）と隣接ボーン（指数 0.4）に
   分配し、1 本のウェイト境界で輪郭が段になるのを避ける。

### 10.2 計測（`BodyMeasurer`、`promodeler/human/mhr.py::MHRModel.measure` と同じ定義）

| 計測 | 定義（両実装で同一にする） |
| --- | --- |
| `barefoot_height` | 素体メッシュの y 最大 − y 最小（靴なし、A ポーズ） |
| `inseam` | 正中面 (x = 0) とメッシュ辺の交点（正中線）のうち 40–65% 高さ帯で最も低い点の高さ − 床（頂点選択ではなく辺の交点なので、パラメータに対して連続。18.7 節） |
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
7. 実装の要点（18.7 節で確定）: Levenberg–Marquardt の減衰は単位行列ではなく **Marquardt の対角スケーリング**
   （`J^T J` の対角に比例、床は対角平均の 5%）。単位減衰では列ノルムの小さい `legsSize` が凍り、女性 4 体の股下 −10〜−17 mm の原因だった。
   ステップは受理前に 1 → 1/2 → 1/4 の後退線形探索を行い、減衰の増加はその後。目標を持たない調整パラメータ（`head_height` 目標のない
   Recipe の `adj:head_height`）は解かない（身長を頭で買って 0.65 倍の頭になった）。断面幅・奥行きは重み 0（計測・報告のみ、5 項）。

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
| promodeler で裁断する衣服（シャツ、T シャツなど布の単純な形） | `assets/wardrobe/<name>.py` を **レースプロファイル**（`character/profiles/<race>.json`）上で生成 → `promodeler character import-slot` で UMA スロット化（18.8 節） | `wardrobe[]`（カタログの `uma_wardrobe_recipe_by_race` が生成レシピ名を指す） |

衣服のうち剛体で十分なもの（ネクタイ、帯、ベルト、名札）は **カタログ側で promodeler プロップとして実現** できる:
カタログ項目の `runtime.promodeler_asset`（`assets/props/necktie.py` など）、`runtime.socket`（`neck` / `waist` ...）、
`runtime.parameters`（プロップのパラメータ ← `garment.<仕上がり寸法>`・`garment.material.<欄>`・`body.<計測>` と数値の `+` 式。
例: 帯の `size = ["body.waist_width + 0.07", "garment.width", "body.waist_depth + 0.07"]`）。Recipe の `wardrobe[]` は変えず、
Unity は UMA 衣装の代わりに `AccessoryResolver` でソケットへ装着し、`build.json` の wardrobe 行は `resolved` にアセットパス、CLI は `prop` と表示する。
`neck` は着衣メッシュの襟前（Neck ボーン高さの輪郭前端）を錨に、胸の接線まで傾けて掛ける。`waist` は Recipe の腰断面高さ（身長比）の
着衣輪郭中心。プロップは親ボーンの `lossyScale`（UMA の DNA による骨スケール）を打ち消して実寸を保つ。

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
| **M10 Unity MVP（1 体、原案 §31）** 完了 2026-09-23（18.1・18.2 節） | Unity プロジェクト作成、HDRP と UMA 導入、Intel iGPU でのバッチレンダ実測、`RecipeLoader`、`BodyMeasurer`、`DnaCalibrationTool`、`BodyResolver`、UMA 同梱資産だけで `businessman`（男性・スーツに最も近い既定衣装）を組み、`build.json` + front/side/back レンダ + FBX/GLB、`bridge.build`、`character check` | `promodeler character build businessman` が一発で通り、身長 ±2 mm、周長の残差が表に出る。対応パラメータは原案 §31 の 15–20 項目 |
| **M11 寸法精度と全員** 寸法部分は完了 2026-09-23（18.3・18.4 節）。GarmentMeasurer・顔 DNA の検証は M12 へ | 独自 DNA（肩幅・胴長・頭高）の追加と校正、顔 DNA 表、靴による接地補正、`GarmentMeasurer`、15 体すべてのビルドと照合表、コンタクトシート、`.claude/skills` の更新 | 15 体で身長 ±2 mm、周長 ±1 cm 以内（UMA の限界は残差として明記）。全員のコンタクトシートが並ぶ |
| **M12 カタログと装備・衣装** 装備・衣装・GUI は完了 2026-09-23（18.5 節）。ネクタイ・帯はプロップ衣服として解決（18.7 節）。GLB → UMA スロット変換は 1 着で疎通（18.8 節）。カタログ実資産の制作は残り | `tools/uma_slot_from_glb.py`、MakeHuman CC0 資産の変換と登録（髪 10、上衣 10、下衣 8、靴 6、眉・まつ毛・髭）、肌・眼球テクスチャ、`assets/props/` の装備品 8 点とソケット装着、Outfit 36・37、Addressables、`character edit` GUI（Face/Body/Hair/Skin/Wardrobe、Save は Recipe のみ） | 設計書の衣装語彙の 8 割が `catalog_id` で解決され、`wardrobe.missing` 警告が例外になる。GUI 保存 → `character diff` で差分追跡できる |
| **M13 生成モード** `random`（18.10 節）と `prompt`（18.11 節）は完了 2026-09-23。クリップ動画・物理書き出しは残り | `presets`（性別・年齢別の人体計測事前分布）、`character random`、`character prompt`（LLM → Recipe、スキーマ制約、カタログ ID の実在検証）、クリップ動画記録、`physics_settings` 書き出し | 1,000 体を seed 決定的に生成して全件 `validate` を通す。プロンプト 1 文から `build` まで人手なし |

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

## 18. 実装記録

### 18.1 M10 の着手状況（2026-09-22）

決めたこと・作ったもの（Unity エディタ未起動のため **C# は未コンパイル**）:

| 項目 | 決定 / 状態 |
| --- | --- |
| Unity プロジェクト | エディタの同梱 HDRP テンプレート（`com.unity.template.3d-high-end`）の `ProjectData~` から骨格を作成（エディタ不要）。`ProjectVersion.txt` は 6000.3.21f1 (c02631ffc030) |
| ライセンス | `Unity.exe -batchmode` が終了コード 198「No valid Unity Editor license found」で停止。Unity Hub でのサインインとライセンス有効化は利用者の作業。`bridge.build` は 198 を `unity.license` として `build.json` に記録する |
| UMA | v3.05（2026-08-31、MIT）。UPM 配布ではなく 1.16 GB の unitypackage。`UMAProject/Assets/UMA` に `package.json` はあるが、HDRP 用コンテンツ（`SRP/UMAHDRP.unitypackage`）とセットアップスクリプトが `Assets/UMA/...` を前提にするため、**`external/uma` に sparse clone（約 3.5 GB、gitignore）し、`Assets/UMA` へディレクトリ・ジャンクション**で取り込む。`promodeler character setup --no-unity` が作成する |
| UMA 3 の語彙 | レース `Human Male 3.0` / `Human Female 3.0`。衣装スロット Chest / Legs / Feet / Hair / Eyebrows / Beard / TopUnderlayer / BottomUnderlayer / Hands。体 DNA に `shoulderWidth` `height` `legsSize` `chestSize` `waist` `belly` `gluteusSize` `upperWeight` `lowerWeight` `feetSize` があり、10.1 で懸念した「肩幅の独立 DNA がない」は UMA 3 では解消 |
| 同期生成 | `DynamicCharacterAvatar.GenerateNow()`（同期）。ジェネレータは `UMAAssetIndexer.Instance.generator`。`UMA_GLIB.prefab` はダミー |
| パッケージ | HDRP / Core / ShaderGraph 17.3.0（UMA 3 プロジェクトと同じ）、`com.unity.formats.fbx` 5.1.6、`com.unity.nuget.newtonsoft-json` 3.2.1、UnityGLTF `release/2.20.0`（git URL）。glTFast はモーフターゲット書き出し非対応なので GLB は UnityGLTF、FBX は FBX Exporter。両者はリフレクション経由で呼び、欠けても警告で済むようにした |
| バッチ契約 | `-quit` を渡さず、`CharacterBatchBuilder.Build` が `build.json` を書いて `EditorApplication.Exit` する。初回セットアップ（HDRP パッケージ取込 → ドメインリロード）は別エントリ `ProjectSetup.Run`（`promodeler character setup`）。取込直後は 2 回目の実行が必要 |
| カタログ | 53 項目に UMA 3 サンプル資産を **代替（stand_in）** として `runtime.uma_wardrobe_recipe_by_race` に登録。`status` は placeholder のまま、ビルド時に `catalog.placeholder` 警告 |
| 制約 | UMA 3 サンプルにはインナー（TopUnderlayer）用の衣装がないため、`inner` と `upper` が同じ Chest スロットを取り合う。後着が勝ち、`wardrobe.slotConflict` で報告 |

### 18.2 M10 の結果（2026-09-23）

ライセンス有効化後、`character setup` → `character build` がエンドツーエンドで通った。コンパイルエラーは 2 件のみ
（`UMAData.umaGenerator` が読み取り専用、HDRP 17.3 で `SetIntensity` が廃止）。1 体のビルドは約 40 秒（UMA 生成、
最大 10 反復の寸法解法、HDRP レンダ 10 枚、FBX 58 MB + GLB 17 MB）。HDRP のヘッドレス描画は Intel iGPU で動いた。

ビルド中に直した計測・解法の問題:

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| 周長が +2.3 m | UMA は身体と衣服を 1 つの SkinnedMeshRenderer に結合する | 裸のレースで解いてから `Dress()` で着せる |
| 最終計測がソルバーのログと一致しない | ソルバー終了時に UMA が保持していたのは最後の試行値（ヤコビアン探索や棄却ステップ） | 採用値を再適用して再生成してから計測 |
| 胸囲の断面幅が肩幅と同じ | T ポーズでは腕根が胸の平面を通る | 計測時のみ上腕を 55° 下げた A ポーズにする（腕の向きから回転符号を決める。UMA の左腕は −X） |
| 身長のルートスケールが 2 倍に効く | `BakeMesh` の結果に祖先スケールが既に入っている | 位置・回転のみの行列で世界座標へ |
| 解法が「改善なし」で早期終了 | 減衰固定のガウス・ニュートン | 減衰を 4 倍ずつ上げて再試行する Levenberg–Marquardt 風に |
| 初回レンダが露出過多 | HDRP の初フレームで露出・空が未収束 | 捨てフレームを 2 枚描く |
| shaded パスがマゼンタ | `UMAHDRP.unitypackage` の非同期インポートが終了前に打ち切られていた | Python で unitypackage を展開（`install_uma_hdrp_content`） |

残差（`character check <id> --build`、許容は身長 2 mm・その他 5 mm）:

| 項目 | businessman（男 1.76 m） | woman / 春香（女 1.60 m） |
| --- | --- | --- |
| barefoot_height | −0 mm | +0 mm |
| inseam | +2 mm | −7 mm |
| foot_length | +1 mm | −1 mm |
| shoulder_width | −12 mm | −19 mm |
| waist | +6 mm | −7 mm |
| hip | −17 mm | −3 mm |
| chest / bust | **+99 mm**（幅 +79、奥行 −78） | **−97 mm**（幅 −7、奥行 −68） |
| underbust | — | +42 mm |

胸囲だけが大きく外れる。UMA 3 の素体は胴が幅広で浅く、男性は設計書の 0.326×0.284 m に対し 0.405×0.206 m、女性はバストの奥行きが
68 mm 足りない。MHR で「周長だけ合わせると胸が平らになる」と同じ失敗モードで、DNA（`chestSize`, `breastSize`, `upperWeight`, `upperMuscle`）
では奥行きを出せない。春香の解は `breastSize` 0.07・`upperMuscle` 1.0 に張り付いており、バストとアンダーバストが同じ DNA を逆方向に
引いた結果でもある（UMA 3 の女性レースには `shoulderWidth` DNA がなく、肩幅 −19 mm も動かせない）。M11 で断面の幅・奥行きを目標に
加える（`chest_depth` を重み付け）か、UMA の DNA に胸の奥行き・肩幅用の骨スケールを追加して校正する。

その他の未解決: 髪と髭の共有色 `Hair` は UMA レシピに保存されているのに白く描かれる（UMA 3 の髪シェーダーの色経路が別。M11）。
`inner` と `upper` は UMA 3 サンプルにアンダーレイヤー衣装がなく同じ Chest スロットを取り合う（後着優先、`wardrobe.slotConflict`）。
ネクタイは代替がなく空。付属品の装着は M12。

次の手順は M11（寸法精度と全員）: 断面奥行きの目標化、独自 DNA の校正、顔 DNA 表の検証、靴による接地補正、`GarmentMeasurer`、15 体のビルドと照合表。

### 18.3 M11 の進捗（2026-09-23）

- **独自パラメータ（10.1 の「独自 DNA」）を UMA 資産を編集せずに実装**: 生成後に UMA の葉「Adjust」補助骨（`Spine1Adjust`, `SpineAdjust`,
  `LowerBackBelly`, `LowerBackAdjust`, `HeadAdjust`）をスケールし、`LeftArm`/`RightArm` の位置を外側へずらす（`adj:*`, `pos:arm_spread`、
  0.5 が中立、スケール 0.7–1.4、位置 ±8 cm）。UMA は生成ごとに骨格を作り直すので `Rebuild()` の直後に毎回適用する。
- **感度表（校正ツール）**: `character build --probe` が全パラメータを 0 と 1 にして計測差分を `calibration.json` に書く。男性の主な値
  （全可動域あたり）: `height` 身長 +1730 mm、`adj:chest_depth` 胸奥行 +193 / 胸囲 +269、`adj:chest_width` 胸幅 +282、`adj:hip_width`
  ヒップ +428、`shoulderWidth` 肩幅 +204、`pos:arm_spread` 肩幅 +30。効かないもの: `chestSize`（男性で +5）、`ShoulderAdjust` の
  スケール（+6、削除）。`adj:head_height` は頭頂を動かすので身長比の断面平面すべてに波及する。
- **目標の追加**: 断面の幅・奥行き（`cross_sections`）と `head_height` を目標に加えた。UMA の胴断面は楕円より角張っており、
  周長・幅・奥行きの 3 目標は同時に満たせない。設計書の優先順位どおり周長を重み 1、断面を 0.25 とした。
- **計測**: 周長は断面外形の **凸包** の周長（巻き尺は腋や胸の谷間を渡る）。角度順折れ線は非凸外形でギザギザになり、ソルバーの
  ヤコビアンにノイズを入れていた。ソルバーは停滞時に差分ステップを半分にしてヤコビアンを作り直す（最大 2 回）。
- **副作用**: 補助骨スケールは重みの境界で側面シルエットに段差を作る（ビジネスマンの側面クレイで胸下に棚）。可動域を 0.6–1.5 から
  0.7–1.4 に絞った。滑らかさが要る場合は複数骨への分散か、UMA の DNA コンバータ（複数骨のカーブ）を作る必要がある。
- **髪・髭・眉の色**: UMA 3 の髪シェーダーは共有色のチャンネルマスクではなく、共有色が運ぶシェーダープロパティ
  `_BaseColor` / `_RootColor` / `_Tip_Color` を読む（`SRP/Colors/HairColors.asset` の構造）。`OverlayColorData.SetColorProperty` で
  3 つを設定するようにした（根元 0.8 倍、毛先は白へ 15 % 寄せる）。

全 15 体の残差は `promodeler character report` の表（18.4）。

### 18.4 全 15 体の残差（2026-09-23、`promodeler character report`）

段階解法（長さ → 周長 → 全体、各 6 / 8 / 14 反復、周長段階も全目標を評価）の結果。単位 mm、`*` は許容超え（身長 2 mm、他 5 mm）、
`s` はビルド秒数（3 段階の解法で 1 体約 4 分）。

| id | status | s | barefoot_height | inseam | shoulder_width | foot_length | head_height | chest | bust | underbust | waist | hip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| businessman | ok | 230 | +0 | -1 | -1 | -0 |  | +4 |  |  | +4 | +2 |
| businesswoman | ok | 239 | -0 | +1 | -1 | -0 |  |  | +2 |  | +2 | +3 |
| cafe-clerk | ok | 238 | +0 | +1 | -1 | -0 |  |  | +3 |  | +2 | +3 |
| convenience-clerk | ok | 224 | +0 | +1 | -1 | +0 |  | +9* |  |  | +6* | +3 |
| convenience-customer | ok | 242 | -0 | +1 | -1 | -0 |  |  | +3 |  | +2 | +2 |
| karate-master | ok | 217 | +0 | -15* | -1 | -1 |  | +15* |  |  | +4 | -2 |
| karate-student | ok | 244 | +0 | -15* | -6* | -2 |  |  | +2 |  | +3 | -10* |
| passerby-a | ok | 220 | +0 | -1 | -1 | -0 |  | +9* |  |  | +5* | +2 |
| passerby-b | ok | 239 | -0 | +1 | -1 | -0 |  |  | +3 |  | +2 | +1 |
| passerby-c | ok | 227 | -0 | +1 | -1 | -0 |  | +5 |  |  | +4 | +7* |
| passerby-d | ok | 245 | +0 | +1 | -1 | +0 |  |  | +2 |  | +2 | +3 |
| passerby-e | ok | 227 | -0 | -2 | -1 | -0 |  | +7* |  |  | +3 | +4 |
| passerby-f | ok | 242 | -0 | +7* | -12* | -1 |  |  | +17* |  | +13* | -8* |
| passerby-g | ok | 233 | +0 | +0 | -0 | -0 |  | +8* |  |  | +5* | +2 |
| woman | ok | 233 | +0 | -11* | -1 | -1 | -32* |  | -29* | +52* | -0 | -2 |

- 身長は 15 体すべて ±1 mm。股下・肩幅・足長は 12 体で ±2 mm 以内。
- 周長は 11 体で ±1 cm 以内。超えるのは空手師範（胸囲 +15、股下 −15: 胸囲 1.04 m の筋肉質な体で `upperMuscle`/`upperWeight` が上限）、
  通行人 F（バスト +17、腰 +13）、そして春香（バスト −29、アンダーバスト +52、頭高 −32）。
- 春香のバストとアンダーバストは 7 cm しか離れておらず、UMA 女性素体では乳房の下端がアンダーバスト平面（身長比 0.7375）を割るため
  同時には満たせない。`breastPosition` DNA を含めても解消しない。周長の優先順位は設計書どおりバストを重み 1.5 にしている。
- 段階解法の前（全パラメータを同時に解く）は同じ 15 体で胸囲の残差が最大 +79 mm、女性 3 体は股下が −60〜−90 mm に発散していた。
- 補助骨スケールによる側面シルエットの段差は残る（18.3）。滑らかにするには複数骨への分散か UMA の DNA コンバータ化が必要。
- 髪・眉・髭の色は `SetRawColor` で解決（`SetColor` はプロパティブロックを捨てる）。全員の髪が設計書の色で描かれる。
- 未着手: `GarmentMeasurer`（着衣後の完成寸法）、顔 DNA 表の妥当性確認、接地補正の検証、`.claude/skills` の同期（Skill/SKILL.md は更新済み）。

### 18.5 M12 の進捗（2026-09-23）

- **装備品**: 設計書の付属品 11 種を `assets/props/*.py`（briefcase, tote, eco_bag, backpack, shoulder_bag, messenger, glasses, watch,
  sports_watch, phone, badge）として実装。定数マテリアルなのでベイクなしで 1 個 10–20 秒。共通部品は `promodeler/props.py`
  （丸めた箱、ストラップ、コード、アーチ、`socket_extras`）。閉じたリングは閉じた `Sweep` だと端が重なって自己交差するため、
  閉じたプロファイルの `Revolve`（トーラス）で作る。`Asset.extras.promodeler_socket` に把持点 `grip_offset_m` と姿勢
  （`world_up` = 吊り下げ、`follow_bone` = 骨に追従）を書く。
- **寸法の受け渡し**: `promodeler.build.load_asset(parameter_overrides=...)` を追加し、Recipe の `accessories[].size_xyz_m` が
  アセットの `size` を上書きする（同じ `tote` でも人物ごとの寸法で生成される）。ブリッジが GLB のパス・ハッシュ・把持点を
  `assets.json` に書く。
- **装着（Unity）**: `AccessoryResolver` が GLB を `Assets/ProModeler/Generated/Accessories/` へ複製し UnityGLTF のインポータで読み、
  ソケット表（`hand_r`→RightHand … `face`→Head+(0, 0.065, 0.105) など）の骨に親子付け。把持点が骨の位置＋オフセットに一致する
  よう配置し、`world_up` なら鉛直に吊る。glTF 読込で X が反転するため把持点の X を反転する。ビジネスマンのブリーフケースは
  右手の位置に取っ手が来て鉛直に吊れた。`build.json` の `accessories[].attached` と三角形数に反映。
- **衣服の完成寸法（GarmentMeasurer 相当）**: 着衣後の胴断面の周長をスロット別に `measured_m.garments` へ（upper/inner/dress → 胸、
  lower/dress → 腰・ヒップ）。ビジネスマンの上着は設計書 1.08 m に対し 1.09 m。
- **衣装（Outfit）**: `character build woman --outfit haruka-karate-uniform` が通る（衣装置換、裸足、編み込みの髪）。空手着・帯は
  代替資産（パーカー・スウェットパンツ）で帯は空。
- **GUI**: `CharacterEditorWindow`（メニュー ProModeler → Character Editor、または `promodeler character edit <id>`）。寸法・体型・
  顔・色・衣装 ID を編集し、同じ `UMACharacterRuntime` でプレビューを再生成、Save は Recipe JSON だけを書き `source.kind = gui`
  にする。保存後は Python 側の `character validate` / `character diff` で追跡する。
- **解法の修正**: 春香の衣装ビルドで `upperMuscle` 1.0・`breastSize` 0 の解（筋肉質で胸のない体）が出た。筋肉スライダーは
  `body.shape.muscle` の意味値で固定し解法から外した。アンダーバストは UMA の乳房が平面を割るため報告のみ（重み 0）にした。
- **装着の向き**: UMA の骨は骨軸に沿ったローカル軸を持つため `bone.rotation` を写すと眼鏡が 90° 回る。休止姿勢では常に世界座標で
  水平に置き、骨への親子付けだけで追従させる。眼鏡は `LeftEye`/`RightEye` 骨の中点の 28 mm 前に掛ける（Head 骨からの固定
  オフセットでは頭の中に入った）。レンズは不透明の代替色。
- **未着手**: カタログ実資産（MakeHuman CC0 → UMA スロット変換 `tools/uma_slot_from_glb.py`、ネクタイ・帯・インナー）、
  Addressables、付属品と身体の貫通確認、`follow_bone` 装備（眼鏡・時計・名札）の向きの目視確認。

### 18.6 装備・衣装・GUI 追加後の全 15 体（2026-09-23、`promodeler character report`）

段階解法を「長さ → 周長 → 長さ → 全体」（6 / 8 / 4 / 14 反復）にし、筋肉は意味値で固定、アンダーバストは報告のみ、
`pos:arm_spread` は ±12 cm、重みは身長 3・股下 2・肩幅 1・胸囲/バスト 1.5。付属品を持つ 10 体は装着込み。

| id | status | s | barefoot_height | inseam | shoulder_width | foot_length | head_height | chest | bust | underbust | waist | hip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| businessman | ok | 111 | +0 | -0 | -3 | -0 |  | +9* |  |  | +6* | +4 |
| businesswoman | ok | 120 | -0 | +1 | +0 | +0 |  |  | +9* |  | +3 | +4 |
| cafe-clerk | ok | 117 | +0 | +3 | +1 | +0 |  |  | +3 |  | +1 | +5* |
| convenience-clerk | ok | 108 | -0 | -0 | -3 | -0 |  | +10* |  |  | +7* | +3 |
| convenience-customer | ok | 123 | +0 | +2 | -0 | +0 |  |  | +5 |  | +3 | +4 |
| karate-master | ok | 184 | -0 | -5* | -3 | -0 |  | +6* |  |  | +4 | +2 |
| karate-student | ok | 118 | -0 | -17* | -17* | -2 |  |  | -1 |  | -6* | -5* |
| passerby-a | ok | 175 | -0 | -1 | -2 | -0 |  | +12* |  |  | +6* | +1 |
| passerby-b | ok | 187 | -0 | +1 | -1 | -0 |  |  | +4 |  | +2 | +4 |
| passerby-c | ok | 169 | -0 | +1 | -1 | -0 |  | +5 |  |  | +3 | +7* |
| passerby-d | ok | 187 | +0 | -17* | -13* | -2 |  |  | +2 |  | -1 | -5* |
| passerby-e | ok | 169 | +0 | +4 | -1 | +0 |  | +9* |  |  | +9* | +8* |
| passerby-f | ok | 124 | -0 | -10* | -25* | -3 |  |  | -1 |  | -6* | -7* |
| passerby-g | ok | 80 | -0 | -10* | -18* | -0 |  | +20* |  |  | +12* | -1 |
| woman | ok | 120 | +0 | -1 | -8* | +0 | -10* |  | -14* | +85* | -1 | -8* |

- 身長は 15 体すべて ±0 mm。周長は 11 体で ±1 cm 以内（超過: 通行人 A 胸囲 +12、通行人 G 胸囲 +20・腰 +12、春香 バスト −14）。
- 女性 4 体（空手門下生、通行人 D・F・G は男性）で股下 −10〜−17 mm、肩幅 −13〜−25 mm が残る。ログでは長さ段階で身長と肩幅が
  互いに引き合っている（女性レースに肩幅 DNA がなく、`height` DNA が肩幅を +320 mm/可動域で動かす唯一の強い手段）。
  `pos:arm_spread` を ±12 cm にしても足りない体型がある。解決策は UMA 側に肩幅の骨スケール DNA を足すか、肩幅の許容を
  女性で緩めるかの判断で、次の段階へ持ち越す。
- 春香のアンダーバスト +85 mm は報告のみ（UMA の乳房が平面を割る）。
- 15 体の総ビルド時間は約 35 分（1 体 80〜190 秒、付属品の Blender ビルドはキャッシュ済み）。

### 18.7 肩幅ハンドル・解法の修正・プロップ衣服（2026-09-23）

18.6 節の持ち越し（女性 4 体の股下・肩幅残差、輪郭の段、ネクタイ・帯の欠落）に対して行ったこと。

1. **鎖骨長ハンドル `adj:shoulder_length`**。`--probe` で Shoulder ボーンの X/Y/Z スケールを比べ、ローカル Y が鎖骨方向だった
   （肩幅 −49/+70 mm、バストへの副作用 ±10 mm。`pos:arm_spread` はバスト +99 mm を伴う）。子の Arm ボーンに逆数スケール。
   これだけで空手門下生の肩幅は −17 → −4 mm。
2. **股下が直らなかった真因は解法**。単位行列の LM 減衰（0.3）が列ノルム ~0.8 の `legsSize` を凍らせ（`height` は ~30）、
   `lengths2` 段で同じ残差を 4 回繰り返していた。Marquardt の対角スケーリング + 後退線形探索 + 対角の床（効かない `chestSize` 列が
   巨大ステップを出して全員のステップを潰すのを防ぐ）に変更。
3. **`adj:head_height` は目標があるときだけ解く**。空手門下生では身長合わせに使われ頭が 0.65 倍になっていた。
4. **股下計測を連続化**。ルートスケール 0.03% で頂点選択が飛び、−2 → +9 mm になった。x = 0 面と辺の交点の最低点に変更。
5. **断面幅・奥行きは重み 0**。設計書の幅・奥行きは周長から楕円で導いた値か周長と矛盾する値で、0.25 の重みでも股下を胸の奥行きと
   引き換えていた。報告のみ（UMA の胴は同じ周長で設計書より幅広・平たい: 男性で胸奥行き −115〜−149 mm、幅 +48〜+70 mm）。
6. **調整の隣接分配**。各 `adj:*` を主ボーン（指数 1）と隣接ボーン（指数 0.4）に掛ける。
7. **プロップ衣服**（12 章）。`assets/props/necktie.py`（`neck`）と `assets/props/obi_belt.py`（`waist`）を作り、カタログの
   `necktie_01` / `karate_belt_01` を `promodeler_asset` で解決。`wardrobe.missing` は消え、`build.json` に `garment:<slot>` の装着結果が入る。
   帯は UMA サンプルのパーカーの裾に隠れる（実寸・位置は境界ボックスで確認: 幅 0.294 × 高 0.297 × 奥 0.281 m、中心が腰面）。
   ネクタイは T ポーズの厚いジャケットの上で胸の接線（約 31°）に傾く。

全 15 体を再ビルドした結果（`promodeler character report`）:

| id | status | s | barefoot_height | inseam | shoulder_width | foot_length | head_height | chest | bust | underbust | waist | hip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| businessman | ok | 123 | +0 | +0 | +0 | +0 |  | +0 |  |  | +0 | -0 |
| businesswoman | ok | 117 | +0 | +0 | -0 | +0 |  |  | +0 |  | +0 | -0 |
| cafe-clerk | ok | 117 | -0 | +0 | +0 | -0 |  |  | -0 |  | +0 | +0 |
| convenience-clerk | ok | 105 | -0 | -0 | -0 | +0 |  | +0 |  |  | +0 | +0 |
| convenience-customer | ok | 117 | -0 | -0 | +0 | +0 |  |  | +0 |  | -0 | +0 |
| karate-master | ok | 111 | +0 | +0 | +0 | +0 |  | +0 |  |  | +0 | -0 |
| karate-student | ok | 120 | +0 | +0 | -0 | +0 |  |  | +0 |  | +0 | -0 |
| passerby-a | ok | 108 | +0 | +0 | +0 | -0 |  | +0 |  |  | +0 | -0 |
| passerby-b | ok | 123 | +0 | -0 | +0 | -0 |  |  | +0 |  | +0 | -0 |
| passerby-c | ok | 108 | +0 | +0 | +0 | +0 |  | -0 |  |  | +0 | +0 |
| passerby-d | ok | 105 | +0 | -0 | -0 | +0 |  |  | +0 |  | +0 | -0 |
| passerby-e | ok | 120 | +0 | +0 | +0 | +0 |  | +0 |  |  | -0 | -0 |
| passerby-f | ok | 123 | -0 | +0 | +0 | +0 |  |  | +0 |  | +0 | +0 |
| passerby-g | ok | 120 | +0 | +0 | +0 | +0 |  | +0 |  |  | +0 | -0 |
| woman | ok | 141 | +0 | -5 | -8* | -1 | -17* |  | -7* | +181* | -2 | -3 |

- 14 体で解いた全項目（身長・股下・肩幅・足長・周長）が ±0 mm（表示丸め）。18.6 節の残差はすべて解法側の問題だった。
- 春香（`woman`、設計書 05）は肩幅 −8、頭高 −17、バスト −7、アンダーバスト +181（報告のみ: UMA の乳房が平面を割る）。
  `adj:shoulder_length` と `pos:arm_spread` が上限で飽和し（空手門下生も同じ）、`all` 段の 14 反復で頭高が 1 mm/反復しか縮まない。
  肩幅 0.36 m の要求に対し UMA 女性の鎖骨可動域が足りない。次は肩幅ハンドルの範囲拡大（Shoulder Y スケール 1.45 → 1.7）か、
  頭高の重みの見直し。
- 副作用: 鎖骨 1.45 倍で肩の輪郭が角張る（空手門下生のクレイ前面）。実資産の袖で隠れる範囲だが、範囲拡大の前に見た目の上限を決める。
- 1 体 105〜141 秒、15 体で約 30 分（後退線形探索で評価回数は増えたが、反復が早く収束する）。


### 18.8 GLB → UMA スロット変換の 1 着スパイク（2026-09-23）

承認済み計画の (a)。promodeler で裁断した白シャツを UMA 3 の衣装（スロット + オーバーレイ + Wardrobe レシピ）に変換し、
カフェ店員（女性、`inner` = `shirt_three_quarter_01`）が着るまでを通した。

**経路**

1. `promodeler character profile human_female` → Unity バッチ `RaceProfileExporter` がレースの中立体（全 DNA 0.5、裸、
   静止ポーズ）を組み、`character/profiles/human_female.json` に胴の輪郭（2 cm 刻みの凸包 48 枚）、腕の断面（肩→手首軸に
   垂直な面、3 cm 刻み 19 枚 × 2）、主要ボーン位置を書く。17 秒。判明したこと: **UMA 3 の静止ポーズは腕が約 45° 下がった
   A ポーズ**（レンダはアニメータの T ポーズ）、女性中立体の身長は **1.99 m**（DNA 0.5 は実寸ではない。スロットは骸骨に
   追従するので実寸の体には DNA で縮む）。
2. `assets/wardrobe/white_shirt.py`: 胴は裾（身長比 0.50）から襟（Neck ボーン −1.5 cm）までの輪郭に ease 2.5 cm を足し
   48 点に再標本化した `Loft`、袖は腕断面に ease 1.8 cm を足した `Loft` を軸方向の `Transform(rotation=(0,0,angle_z))`
   で並べる。袖丈は肩→手首の 0.75。Blender ビルド 3 秒、2,507 頂点。
3. `promodeler character import-slot <glb> --race human_female --name white_shirt_f --slot TopUnderlayer --material-from-recipe colors_top_Recipe`
   → Unity バッチ `WardrobeSlotImporter`: UnityGLTF で GLB を読み、UV のない promodeler メッシュに `Unwrapping.GenerateSecondaryUVSet`
   で UV を張り（頂点 2,507 → 3,005 に分割。ウェイト転写の **前** にやらないと `ManagedBonesPerVertex` 不一致で失敗）、
   中立体の最近接三角形の重心補間でボーンウェイトを転写（UMA 同梱 `SceneMeshSlotBuilderWindow` と同じ方式、4 影響まで）、
   現在ポーズのスキニング行列の逆でバインド空間へ戻し、`SlotDataAsset.UpdateMeshData` → スロット、`colors_top_Recipe` の
   UMAMaterial（`UMAMaterial_UMA_SRP_DiffuseNormalSpecular`、3 チャンネル）に 16×16 の平坦テクスチャ（白 / 法線 / マスク）を
   充てたオーバーレイ、`UMAWardrobeRecipe`（`wardrobeSlot = TopUnderlayer`, `compatibleRaces = [Human Female 3.0]`）を作り
   `UMAAssetIndexer.EvilAddAsset` + `ForceSave` で登録。15 秒。フォールバック頂点 0。
4. カタログ `shirt_three_quarter_01.runtime.uma_wardrobe_recipe_by_race.human_female = "white_shirt_f_Wardrobe"`、status ready。
   `character build cafe-clerk` で `inner` が `fitted`、シャツは体型（中立体より 30 cm 低い 1.60 m）に追従して着られ、
   着衣バストは 0.905 m（素体 0.85 + ease）。

**1 着あたりのコスト**: 生成器 140 行（プロファイル → Loft）、Blender 3 秒、変換 15 秒、レースごとにプロファイル 1 回。
男性用は `character profile human_male` と `garments.json` に行を足すだけ。

**制限・次**

- 単一面のメッシュ（裏面なし）、襟・カフス・ボタンなし、袖は胴に突き刺す（内側は隠れる）。実資産の代わりにはならないが
  「意味 → 布の形」を確かめる下地としては足りる。
- オーバーレイは平坦色のみ。Recipe の `material.base_color_srgb` を `--color` に渡す経路は `garments.json` に持たせた。
- 生成された Unity 資産（`Assets/ProModeler/Generated/Wardrobe/`）と UMA インデックスの登録は **ビルド生成物**（gitignore）。
  クローン後は `promodeler character import-slot --manifest character/garments.json` で再生成する。
- FBX 書き出しが `Can't export a RenderTexture normal texture in material ...white_shirt_f_overlay` と警告する（UMA のアトラスは
  RenderTexture。表示には影響なし。書き出しテクスチャの焼き込みは M13 以降）。
- カフェ店員の髪（`Hair_Bun_Recipe` スタンドイン）は今回のスパイク前から白い。UMA 3 サンプルの一部の髪はシェーダ色を
  読まない（18.5 節の `_BaseColor` 経路が効かない）ので別件。

### 18.10 M13 その 1: `character random`（2026-09-23）

`character/presets/anthropometry.json`（日本人成人 20–59 歳の近似事前分布: 身長の平均・SD、身長比の股下・肩幅・足長・頭高、
体脂肪 Beta 分布、周長 = 平均 + 身長勾配 + 体脂肪勾配 + 残差、髪色・虹彩・肌の重み、様式 business/casual/uniform/sport ごとの
カタログ ID と色）から `promodeler/character/sampler.py` が 1 つの `random.Random(seed)` で Recipe を組む。比率は
`consistency` の成人範囲の内側にクランプし、周長は腰 < 尻・胸の順序を保つ。断面は高さと周長のみ（幅・奥行きは作らない）。
`source` に presets の sha256 とカタログ版を記録し、同じ seed は同じ Recipe になる。

- 受入: 1,000 体を `--dry-run` で生成 → 全件 `validate` 通過、寸法警告 0（クランプ前は 12 体が分布の裾で範囲外だった）。生成は 300 体 0.07 秒。
- 1 体（`random-000003e9`、男性 1.726 m、胸 0.96 腰 0.87 尻 0.92）を Unity でビルドしたところ、周長段階が 1 歩も進めず +79/+86/−76 mm。
  原因は **調整ボーンを 0.5 のとき「触らない」最適化**: UMA 骸骨の `SetScale` は倍率 1.0 でも生成結果を 15 mm 動かす（骨に触れると
  `accessedFrame` が更新され UMA の復元経路が変わる）ため、全調整 0.5 の初期体だけが応答曲線から外れ、有限差分ヤコビアンが指す
  方向がすべて悪化に見えた。0.5 でも常に適用するよう変更し、`PROMODELER_SWEEP=<param>` で 1 パラメータ掃引を記録する診断と、
  却下ステップの計測値ログ（`MeasurementSolver.Verbose`）を足した。修正後は同じ体が 4 反復で全項目 ≤3 mm。
- 全 15 体を再ビルドして残差表を更新（`docs/character-residuals.md`）: 14 体は全項目 ±0 mm のまま、春香は肩幅 −8 → −3、バスト −7 → −2、股下 −5 → −2 に改善したが頭高が −17 → −22 mm（`adj:head_height` の重み 0.7 では身長・肩と引き合う。設計書 05 だけが頭高を指定する）。

### 18.11 M13 その 2: `character prompt`（2026-09-23）

一文 → `PromptSpec`（性別・年齢・身長・体脂肪/筋肉/姿勢・様式・髪型 ID・髪色・虹彩・肌・ひげ・顔スライダー・衣服カタログ ID・
色・装備・名前・記述子。`promodeler/character/prompt.py`、JSON Schema は `serialize.schema` から生成）→ `sampler.sample_character`
に **上書きとして**渡し、文が決めない項目は文のハッシュを seed にして事前分布から引く。LLM は Recipe を直接書かない: `--llm anthropic`
は Anthropic API の tool use（`emit_prompt_spec`、`input_schema` = PromptSpec スキーマ、`tool_choice` 強制）で Spec だけを返させ、
system プロンプトにカタログ ID の一覧を渡す。返った Spec は同じ `decode` で検証し、存在しないカタログ ID は警告して seed の値で埋める。
既定はルールベース解析（日本語語彙: 性別・年齢「30代」・身長「178cm」/「小柄」・体格語・顔語・髪色・様式語・カタログ match 断片・装備語・ひげ）で、
API キーなしで動く（このマシンには `ANTHROPIC_API_KEY` がなく、LLM 経路は偽クライアントのテストで確認）。

- 例: 「30代の男性会社員。身長178cm、がっしりした体型。黒縁眼鏡にブリーフケース。」→ male 35、1.780 m、body_fat 0.6 / muscle 0.62、
  business、glasses + briefcase → `--build --no-render` で Unity ビルドまで人手なし（受入基準「プロンプト 1 文から build まで」）。
- 同じ文は同じ Recipe（`source.kind = prompt`, `sha256` = 文のハッシュ、`identity.descriptors[1] = "prompt:<文>"`）。
- 衣服は 1 スロットにつき最長一致の断片を採用（「七分袖シャツ」が「シャツ」に勝つ）。ワンピース指定時は上下を外す。
- 残り: 英語語彙の拡充、`garment_colors`（「紺のスーツ」）の色語、`--llm` の実機確認、クリップ動画記録と物理設定書き出し（M13 その 3）。

### 18.9 衣装調達の調査（2026-09-23）

承認済み計画の (b)。結果は `docs/04-wardrobe-sourcing-survey.md`。要点: UMA 3.0 レース用のサードパーティ衣装は 2026-09 時点で存在せず、
既存の UMA 衣装パックは UMA 2 体形用、o3n の HDRP セットは独自レース。当面は 18.8 節の裁断経路を主軸にし、次の技術投資は
「別の体に合わせた服を 3.0 中立体にフィットさせる工程」（MakeHuman CC0 衣装と HDRP モジュール衣装を取り込む鍵）。

## 19. 未決事項（実装フェーズで決める）

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
| §31–§34 MVP・Phase 2–4 | 16 章 M10–M12、18.1 |
