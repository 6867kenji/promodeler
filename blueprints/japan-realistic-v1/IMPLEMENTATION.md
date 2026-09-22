# promodeler 実装担当向け

この設計書は独自スキーマ promodeler-blueprint/1.0。`recipe.json` として直接実行しない。

1. blueprint.json の軸・寸法・パーツIDを読み、Asset/Partを記述。内部空間を包絡Boxで埋めない。
2. Box/Extrude/Loft/Revolve/SweepとBooleanで骨格を作り、形状を検証してから材質を付ける。
3. 建具ピボットをJoint.head/tailへ変換。回転はradians、スライドはm。階の反復は配置表を参照。
4. 建築は平面矩形から壁・開口を明示生成。部屋の区画が重なるコアや廊下は記載の差分で切り欠く。
5. 人体は断面だけで完成としない。顔・手・関節のトポロジー、ウェイト補正とmorphの追加工程が必要。
6. `python -m promodeler recipe assets/<id>.py` で検証、低解像度buildで形状確認、最後に品質を上げる。
7. report.json と実際のレンダを照合。正面・側面・背面・斜め・細部・可動証拠を保存。

確認した現行機能: メートル/Y-up、PBRベイク、Joint/Pose/Clip、距離ベースウェイト、ClothDrape、LOD。READMEとcore/rig.pyを根拠とする。

差分: ClothDrapeは静止形状を凍結し、継続的な服物理ではない。胸・髪動力学、IK/FK制御、顔morph、透過/SSS/異方性の目標を既存機能だけで満たしたことにしない。Unityへの座標変換・接線・クリップと物理の共存を実装時に確認する。

標準検証ビューは perspective/front/side/top。背面ビューは追加実装するか、検証専用のカメラを設ける。設計参考シートを検証画像として転用しない。

各モデルGLBはPBR・骨アニメ検証用。物理設定は別の編集可能データと動画を伴う。独自ライセンスは私有状態から開始し、参照商品のライセンスを成果物へ転記しない。
