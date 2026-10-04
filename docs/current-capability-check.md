# promodeler の機能確認（2026-09-30）

## 今回確認した実動作

| 対象 | 確認結果 | 確認場所 |
| --- | --- | --- |
| コードからの形状生成 | `assets/mug.py` を低解像度設定で生成し、形状QA、画像、GLBが成功。3,644三角形、非多様体辺0 | `C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-new-assets-20260930/capability-check/mug/7e733995bc9e/report.json` |
| 設計書付き空間生成 | 以前の汐見町・地下鉄駅のビルドは `status: ok`、`blueprint_qa.status: pass`。警告と見た目の確認は別途必要 | `C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-subway-update/index.html` |
| Canonicalキャラクター | 甲冑男性とDidoのGLBをBlenderで再読込。いずれも101ボーン、上腕の変形追従を確認 | `C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-new-assets-20260930/index.html` |
| 参考モデル | 改札・自販機および駅・車両のFBXをGLBへ書き出して再読込。駅2の大規模Blendは参照登録・画像監査まで | 同上 |

## おすすめの確認順序

1. **まず見た目を比較する。** `promodeler-new-assets-20260930/index.html` のキャラクター・小物と、`promodeler-subway-update/index.html` の街・駅を開く。元の設計画像、正面・側面、近景で形と質感を評価する。
2. **次に一つだけ変更する。** 非人体は対象の `assets/*.py` または対応する `blueprints/*/blueprint.json` の寸法・配置・材質を変更し、同じ視点で前後比較する。人物は `character/canonical_recipes/*.json` の衣装・髪型を一つ変更する。顔・体型の変更は対応するベースの `manifest.json` にマッピングがある項目だけを試す。
3. **最後にGLBを実物確認する。** Blenderで［ファイル → インポート → glTF 2.0］からGLBを読み、寸法・材質・リグ・関節の変形を確認する。生成時の `report.json`、人物の `build.json` も見る。

## 再現用コマンド

プロジェクトフォルダー `C:/Users/kuwano/develop/promodeler` で実行する。`--out` は書き込み可能な作業フォルダーに指定する。

```powershell
python -m promodeler doctor
python -m promodeler build assets/mug.py --resolution 320 --texture-resolution 256 --bake-samples 2 --views perspective --formats glb --out "C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-capability-check"
python -m promodeler character validate dido-male-tshirt --mode canonical --strict
python -m promodeler character build dido-male-tshirt --mode canonical --strict-base --no-render --out "C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-capability-check"
python -m promodeler external verify subway-gates-vending
python -m promodeler external export subway-gates-vending --out "C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-capability-check/subway-gates-vending.glb"
```

街・統合駅は重いので、小物と人物の確認後に個別に試す。設計QAの合格だけでは、質感や通行しやすさは保証されない。

## 現在の調整範囲と制約

- 非人体：形状プリミティブ、ブーリアン、反復配置、材質・テクスチャ、照明・カメラ、設計寸法、GLB出力をコードと設計書で調整できる。
- Canonical人物：ベースに用意された衣装・髪型・アクセサリーを選べる。`RiggedWoman_v6` には顔・体型のShapeKey/骨マッピングがある。Didoは現在、衣装・髪型の選択が中心で、顔・体型のスライダーは未登録。
- 参考モデル：元ファイルを保持したままSHA-256検証とGLB変換ができる。登録しただけでは街や駅に自動配置されない。
- `doctor` ではBlender 5.2を検出。Pillow未導入のためコンタクトシート機能、Anthropic未導入のため自動批評機能は使用できない。Unity/UMA連携は未確認。

## 追加素材の優先順位

1. **Didoの元テクスチャ一式。** 新しい `Dido+V2.blend` の画像220件のうち、有効な37件は主に撮影用の室内・小物。人物・髪・衣装に使う画像はすべて参照切れ。元の `textures` フォルダーと `.fbm` フォルダー、または画像をPackしたBlendが必要。
2. **不足する設備・駅の画像。** 洗濯機FBXは4画像、駅2Blendは青い壁のBase Color/Normal/Roughness 3画像が欠けている。
3. **使い回せる男性素体と衣装。** 男性ベースは個別のリグ付きモデル中心で、現在のDido用衣装はTシャツが主。共通リグ・中立姿勢・全身のウェイト・Pack済みPBR画像を持つ男性素体と、同じリグに合う上着・下衣・靴があると、組合せを増やしやすい。
4. **車両外装・駅サインのPBR画像。** 新しい駅FBXの車両材質は主に単色。近景品質を上げる場合は車体・窓・座席・行先表示などのBase Color/Normal/Roughnessが有効。
