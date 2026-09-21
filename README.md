# promodeler

コードから写実的な 3D モデルを決定的に生成するツールキット。
Python のソースコードがアセットの唯一の正であり、ヘッドレス Blender を
コンパイラのバックエンドとして使う。設計の背景は
[docs/01-realitizer-analysis-and-design.md](docs/01-realitizer-analysis-and-design.md)。

## 使い方 (M0)

```sh
python -m promodeler doctor                 # Blender を検出できるか確認
python -m promodeler recipe assets/crate.py # レシピ JSON を表示 (Blender 不要)
python -m promodeler build assets/crate.py  # 生成 + レンダ + glTF 書き出し
```

出力は `build/<asset>/<hash12>/` に置かれる:

| ファイル | 内容 |
| --- | --- |
| `recipe.json` | kernel に渡した正規化レシピ。キャッシュ鍵の元 |
| `report.json` | 数値 QA (バウンディング、三角形数、非マニフォールド辺)、レンダ結果、書き出し結果、失敗時は `error` |
| `renders/*.png` | 固定ライト・自動フレーミングの検証レンダ |
| `model.glb` | モディファイア適用済み、Y-up、パーツ名 = セマンティック ID の glTF |
| `blender.log` | Blender の標準出力 |

同じレシピ・同じ kernel/Blender バージョンなら再ビルドせずキャッシュを返す (`--force` で無効化)。

## アセットファイルの書き方

`assets/crate.py` を参照。モジュールは `asset` に `AssetGenerator` か `Asset` を置く。
任意で `render = RenderSettings(...)` を置ける。

- 座標系: メートル、右手系、**+Y が上**、+Z が手前 (glTF と同じ)。角度はラジアン。
- 色: sRGB 非乗算 + 線形アルファ。`alpha_mode="opaque"` のとき alpha < 1 は検証エラー。
- 範囲外の値は黙って丸めず `ModelingError(code, message)` を投げる。

## テスト

```sh
python -m unittest discover -s tests -v
```

`tests/test_build.py` は実際に Blender を起動する。`PROMODELER_SKIP_BLENDER=1` でスキップ。

## 環境

- Python 3.13 以上 (core は標準ライブラリのみ)。kernel は Blender 同梱 Python で動く。
- Blender 4.2 以上を想定、5.1.2 で確認。`PROMODELER_BLENDER` で実行ファイルを指定できる。
