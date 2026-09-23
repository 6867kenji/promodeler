# 04. 衣装の調達調査（UMA 3 / HDRP / 現代日本）— 2026-09-23

docs/03 の M12「カタログ実資産」に向けた調査。承認済み計画の (b)。条件は 3 つ: **UMA 3 のレース（Human Male/Female 3.0）で着られる**、
**HDRP で描ける**、**現代日本の服装語彙（スーツ、シャツ、制服、空手着、エプロン …）に近い**。結論を先に書く。

## 結論

- 2026-09 時点で **3 条件を同時に満たす購入資産はない**。UMA 3（2026-06 公開、3.05 は 2026-08-31）向けに作られたサードパーティ衣装は見つからず、
  既存の UMA 衣装パックはすべて UMA 2 のレース（HumanMale/HumanFemale）用。UMA 3 は「UMA 2 レースと互換」と告知しているが、
  それは UMA 2 のレースを UMA 3 で走らせられるという意味で、UMA 2 用衣装が 3.0 レースの体に合う意味ではない。
- したがって当面の主軸は 18.7/18.8 節の経路（promodeler で裁断 → `import-slot`）で正しい。購入で最も効くのは
  **「他の体に合わせて作られた服を UMA 3.0 中立体にフィットさせる工程」** を `WardrobeSlotImporter` の前段に足すことで、これがあれば
  下表 C・D（非 UMA のモジュール衣装、MakeHuman の CC0/CC-BY 衣装）が使えるようになる。
- 今すぐ写実的な現代服が要るなら o3n の HDRP セット（約 $128）が最有力だが、o3n 独自レースへの乗り換えになり、解法の校正
  （DNA 名・調整ボーン）をやり直す。1 体で試してから決める。

## 候補の比較

| # | 候補 | UMA 3.0 レース | HDRP | 様式 | 価格・更新 | 備考 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | [UMA Clothing Pack](https://assetstore.unity.com/packages/3d/characters/uma-clothing-pack-119640)（Nesalis） | × UMA 2 レース用 | × Built-in 世代（2018）。UMA 3 の `translateSRP` で材質変換は可能だが未検証 | カジュアル中心（男女 64 着ずつ） | $50、2018-06 | 3.0 レースにはフィット工程が必要 |
| A2 | [UMA Human Cloth Pack](https://assetstore.unity.com/packages/3d/characters/uma-human-cloth-pack-141035)（Dragonsan） | × UMA 2 レース用 | × Built-in 世代（2021） | 現代 + ファンタジー混在（76 枚の画像、品目表なし） | $110、2021-02 | 同上 |
| A3 | UMA Anime Clothing Pack | × | × | アニメ調（制服系がある可能性） | 不明 | 実写志向と合わない |
| B | [o3n UMA Races Stunner Jane & John HDRP](https://assetstore.unity.com/packages/3d/characters/humanoids/o3n-uma-races-stunner-jane-john-hdrp-189470) + [John Modern Clothing Pack (HDRP)](https://assetstore.unity.com/packages/3d/characters/humanoids/o3n-john-modern-clothing-pack-hdrp-204471) + [Jane Modern Clothing Pack](https://assetstore.unity.com/packages/3d/characters/humanoids/o3n-jane-modern-clothing-pack-urp-193519) | △ o3n 独自レース（UMA 2 系）。「UMA 3 が必要」と表記 | ○ HDRP ネイティブ（拡散プロファイル登録が要る） | 現代カジュアル・ビジネス | $89.99 + $37.99 + $37.99、2021-10 | 最も写実的。レース乗り換え = 解法再校正、`Adjusts` のボーン名確認 |
| C | 非 UMA のモジュール衣装: [Collection 3 - Business Suit](https://assetstore.unity.com/packages/3d/characters/collection-3-man-woman-in-business-suit-rigged-276854), [Collection 10 - Business/Casual](https://assetstore.unity.com/packages/3d/characters/collection-10-man-in-business-casual-outfits-278058), [Man in Business Outfit](https://assetstore.unity.com/packages/3d/characters/man-in-business-outfit-273698), [Office Suit Girl](https://assetstore.unity.com/packages/3d/characters/office-suit-girl-313874), [Business Boy](https://assetstore.unity.com/packages/3d/characters/humanoids/modular-anime-character-business-boy-312185) | × 独自リグ | ○ HDRP 対応表記 | スーツ・オフィス（サラリーマン像に近い） | 各 $20–60 前後 | 体形が別。フィット工程 + `import-slot` で取り込む候補 |
| D | MakeHuman アセットパック: [Shirts 01](https://static.makehumancommunity.org/assets/assetpacks/shirts01.html)（CC0、T シャツ・ポロ・セーター 10 点）、Pants 01 / Shoes 01 / Dress 01（CC0）、Suits 01（フォーマルスーツ、CC-BY）、Shirts 02/03・Pants 02（CC-BY） — [一覧](https://static.makehumancommunity.org/assets/assetpacks.html) | × MakeHuman 体形用 | △ テクスチャ付き。材質は作り直し | 現代基本服。日本の制服はなし | 無料（CC-BY は帰属表示） | ライセンス方針（`character/catalog/policy.json`）に合う。フィット工程が要る |
| E | 日本固有（学ラン・セーラー服、帯、割烹着） | — | — | — | — | UMA 向け既製品なし。promodeler 裁断（18.8 節の経路）か外注 |

出典: [UMA 3 (Asset Store)](https://assetstore.unity.com/packages/3d/characters/uma-3-35611)、[UMA 3 告知スレッド](https://discussions.unity.com/t/uma-3-unity-multipurpose-avatar-3-0/1735272)、
[UMA releases](https://github.com/umasteeringgroup/UMA/releases)、[MakeHuman FAQ（CC0）](https://static.makehumancommunity.org/makehuman/faq/are_makehuman_files_free.html)。

## 条件ごとの評価

1. **UMA 3.0 レース対応**: どの候補も直接には満たさない。B は独自レース、A/C/D は別の体形。3.0 レース用衣装は UMA 3 同梱サンプル（Chest/Legs/Feet の数点、
   下着層なし）だけで、これが 18.6 節の「inner と upper が同じ Chest スロットを取り合う」問題の原因。
2. **HDRP**: B と C は対応。A は Built-in 世代で、UMA 3 の UMAMaterial `translateSRP` に頼る。D は材質を作り直す。
3. **様式**: C と B が近い。A は混在、D は基本服のみ、E は該当なし。

## 推奨

1. **主軸は継続**: promodeler 裁断 + `import-slot`（18.8 節）。白シャツで疎通したので、次は T シャツ・パンツ・ジャケット（襟付き）を
   同じ生成器の派生で増やし、`character/garments.json` に並べる。1 着あたり数十分。
2. **フィット工程を作る**（次の技術投資）: 「ソースの体 A に合わせた服メッシュ → UMA 3.0 中立体 B」の変換。A の体メッシュと B の中立体
   （`character/profiles/<race>.json` の元）を対応させ、服の各頂点を A 表面からの法線オフセットとして表し B 表面に移す（MakeHuman の
   mhclo と同じ考え方）。これがあれば D（無料・CC0）と C（有料・HDRP）が `import-slot` に流れ、Skill の「髪・服・靴を手続き生成しない」
   方針とも整合する。見積り: Unity 側 300 行前後、検証 1 着。
3. **購入は 1 体で試す**: o3n セット（B）を試すなら businessman 1 体で HDRP の見え方と解法の再校正コストを測ってから判断する。
   A1/A2 は 3.0 レースに合わないので、フィット工程ができるまで買わない。
4. **日本固有の品目** は promodeler で裁断する（帯・ネクタイはプロップで済んだ。学ランの詰襟、セーラー襟、割烹着は Loft の派生で作れる）。
