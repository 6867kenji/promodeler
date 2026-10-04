# 2026-09-30 に追加した外部モデル

提供されたモデルは元の `C:/Users/kuwano/develop/3d` 以下に残し、promodelerには参照先と検証用SHA-256を登録する。配布用のアセットとしてリポジトリに複製しない。ライセンス文書は提供フォルダー内では確認できていないため、`external_references.json` では `not_recorded` とする。

## キャラクター

`female-swat-soldier` は `FemaleSWAT_Rigged_v1` のCanonicalレシピ。元の `SWAT_Blend.blend` を使用する。調査時点で、Armatureは150本の変形ボーンを持ち、23メッシュの全183,234頂点に変形ウェイトがある。画像77枚はBlendに格納されている。スーツ、ブーツ、防具の選択と、ヘルメット、マスク、ベルト、手袋、膝パッド、銃の着脱をレシピに割り当てた。銃の8メッシュは元のボーン構造とウェイトを使う。別の共通素体への衣装転用は、このレシピには含めない。

```powershell
python -m promodeler character validate female-swat-soldier --mode canonical --base-manifest character/bases/FemaleSWAT_Rigged_v1/manifest.json --strict
python -m promodeler character build female-swat-soldier --mode canonical --base-manifest character/bases/FemaleSWAT_Rigged_v1/manifest.json --out build/character --no-render --strict-base
```

## 服装・髪型

`male-armor-1-6` と `dido-male-tshirt` をCanonicalレシピに追加した。元FBXはどちらも101本のボーンと全頂点の変形ウェイトを持つ。甲冑の元FBXは人体と防具のバインド姿勢が食い違っていたため、`character/prepare_new_male_characters.py` で人体を防具に合わせた準備済みBlendを生成する。GLB書き出しでは全ウェイト影響を保持し、元FBXの誤った透過リンクを外す。Didoの元FBXが参照する画像63枚は提供フォルダーに存在せずFBX内にも埋め込まれていないため、仮のPBR材質色で表示する。

`male_tshirt` はDido用の上着としてカタログに追加した。付属の拡散色・法線画像を使い、99,976頂点にDidoのウェイトを転写した。元モデルの透過画像が生地に穴を開けるため、布地は不透明として扱う。Didoの体型に合わせた調整済みモデルは `DidoMale_v1.blend` に含む。

```powershell
python -m promodeler character validate male-armor-1-6 --mode canonical --strict
python -m promodeler character validate dido-male-tshirt --mode canonical --strict
python -m promodeler character build male-armor-1-6 --mode canonical --strict-base --no-render --out build/character
python -m promodeler character build dido-male-tshirt --mode canonical --strict-base --no-render --out build/character
```

`RiggedWoman_v6` はv5を基に、Streetwearのスポーツシャツ、フォーマルパンツ、靴、ボンバージャケット、バッグと、ポニーテールの別バージョンを追加した。StreetwearのOBJはセンチメートルからメートルへ変換し、共通素体のメッシュからボーンウェイトを転写した。各衣装のBase Color、Metallic、Roughness、Normal画像はPBR材質に接続し、準備済みBlendに格納している。既存のv5レシピ・ベースは保持する。

準備済み素体：`C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-new-assets-20260930/base/RiggedWoman_v6.blend`。

```powershell
python -m promodeler character validate streetwear-woman --mode canonical --base-manifest character/bases/RiggedWoman_v6/manifest.json --strict
python -m promodeler character build streetwear-woman --mode canonical --base-manifest character/bases/RiggedWoman_v6/manifest.json --out build/character --no-render --strict-base
```

`hair_ponytail_telo` は新しい選択肢。既存のヘアバンドとポニーテールもv6のmanifestから引き続き選べる。Streetwearの衣装と髪型はSWATモデル用のリグではなく、`RiggedWoman_v6` 用に合わせている。

ボンバージャケットは選択可能だが、元の袖形状が共通素体の肩・腕に合わず、袖に隙間が見える。標準の `streetwear-woman` 試着レシピでは外してある。袖の再フィットが必要。

## 設備・銃・植物

`assets/external_references.json` に室内設備4件、銃1件、植物4件を登録した。`promodeler external` でソースの参照、SHA-256検証、元ファイルを保持したままGLBへの書き出しができる。

```powershell
python -m promodeler external list
python -m promodeler external list --category plant
python -m promodeler external show indoor-plants
python -m promodeler external verify scar-h
python -m promodeler external export toilet --out build/references/toilet.glb
```

設備・銃・植物はキャラクター衣装ではなく、空間用の独立した参考モデルとして登録している。大きなOffice Basic FBXは必要なときだけ読み込む。モデルの内部座標や元の縮尺を無条件にシーン寸法へ合わせない。

## 書き出し確認

登録した19件の元ファイルをSHA-256で検証した。追加の男性2件はGLBを書き出してBlenderへ読み戻し、上腕を動かしたときのメッシュ追従を確認した。SWATは150本の変形ボーンと23メッシュ、Streetwearは101本の主リグで衣装・バッグ・髪型の追従を確認した。

| モデル | 確認結果 |
| --- | --- |
| Toilet、SCAR-H、Honey Locust | 元の材質を保持したGLBを書き出し・再読込 |
| Indoor Plants | FBXに未接続だった葉色・透過・法線画像を接続し、展示用のCubeを除外 |
| Red Maple | Corona材質の代わりに付属の葉・幹画像を接続し、展示用のCubeを除外。付属画像の葉色は緑 |
| Washing Machine | GLBを再読込できる。元Blendが参照する操作パネル等の画像6枚は提供フォルダーにないため、`textureStatus=missing_source_textures`。Blender 5.2は書き出し完了後の終了時に異常終了するため、構造検証済みのGLBを警告付きで返す |
| Washing Machine FBX | 追加された `final.fbx` はGLBに書き出せる。元画像4枚が提供フォルダーにないため、`textureStatus=missing_source_textures` |
| Garden Trees and Bushes | V-Rayのラッパー材質とMapsフォルダーの画像の対応を復元。葉・花・幹の色、透過、法線を反映したGLBをBlenderへ読み戻した。展示用Cubeを除外 |
| Male 1-6 Armor | 101本のボーン、全ウェイト影響を保持したGLBを再読込。上腕の追従を確認 |
| Dido Human Male + T-shirt | 101本のボーン、Tシャツを含むGLBを再読込。上腕の追従を確認。元画像63枚が欠落しているため仮色表示 |
| Office Basic | 1.2GBのFBXを参照登録・SHA-256検証。GLB書き出しは未実施 |

レビュー画像と各GLB：`C:/Users/kuwano/OneDrive/画像/モデル生成/promodeler-new-assets-20260930/index.html`。
