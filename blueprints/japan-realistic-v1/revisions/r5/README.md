# 日本・写実モデル設計図セット v1

19アセットの制作指示。各モデルは独立フォルダで、SPEC.md（日本語）、blueprint.json（構造化仕様）、images/reference-sheet.png（全体・三面・細部）、elevations.svg（数値管理図）、建築系はlayout.svg（平面配置）を含む。

まず index.html で各カテゴリを選択し、SPEC.md と blueprint.json を実装担当へ渡してください。追加家具・家電8セットは部屋へ組み込まず独立モデルとして扱います。都市は他3建築モデルを参照して64棟を配置します。女性と独立1Kは都市構成から独立しています。

採用したおまかせ項目: PC/Unity HDRP向け、現代日本、適度な使用感、建物内部あり、女性23歳・セージ色膝丈ワンピース・髪も物理、固定設備を含む空室。寸法と性能予算は設計目標です。設計JSONはpromodelerに直接投入できません。

優先順位: 数値JSON > 寸法SVG > 仕様文 > 参考画像。参考画像は雰囲気・材質の資料です。自動生成画像の階数・窓数・配置は厳密ではなく、画像をトレースして寸法を決めないでください。

参照商品: references.json。商品データの取り込みなし。マンションの部屋は参照商品の正確な間取りを取得できていないため独自1K案です。

モデル・リグ・物理の実生成や動作確認はこの納品の対象外。状態は設計レビュー。人型の確認記録はすべて未確認。販売承認・出品は含みません。

## 追加アセット

- [オークフレーム・シングルベッド](07-bed/SPEC.md)
- [ファブリック・コンパクト2人掛け](08-sofa/SPEC.md)
- [乳白カバー・LEDシーリングライト](09-ceiling-light/SPEC.md)
- [オーク机と椅子・コンパクトセット](10-table-chair/SPEC.md)
- [オーク天板・スチールPCデスク](11-pc-desk/SPEC.md)
- [コンパクトPC・周辺機器セット](12-pc-set/SPEC.md)
- [白い2ドア・コンパクト冷蔵庫](13-refrigerator/SPEC.md)
- [白いダイヤル式・電子レンジ](14-microwave/SPEC.md)

部屋の改訂画像は images/reference-sheet-v2.png。旧画像と旧仕様は保持。EAST SIDEの断面位置はsection-east.svgおよびJSONのviewsを参照。

## ゲーミングPC追加

- [ホワイト・ゲーミングPCとディスプレイ](15-gaming-pc-white/SPEC.md)
- [ピンク・ゲーミングPCとディスプレイ](16-gaming-pc-pink/SPEC.md)

白とピンクは同一形状の色違い。PC本体・ディスプレイ・キーボード・マウスを個別配置できます。

## 地下鉄駅

入口・改札通路・島式ホームを独立追加。地上0m、B1=-6m、B2=-12m。列車は含みません。

- [汐見駅S01・地上入口A1](17-subway-entrance/SPEC.md)
- [汐見駅S01・地下1階改札通路](18-subway-concourse/SPEC.md)
- [汐見駅S01・地下2階島式ホーム](19-subway-platform/SPEC.md)

[組立仕様](subway-assembly.json) / [接続模式図](subway-assembly.svg)。昇降設備は上階側アセットが下階まで所有し、下階で複製しません。
