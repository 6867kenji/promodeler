"""Record actual model footprints and the reserved sites as JSON and a plan."""

import html
import json
import sys
from pathlib import Path


def write_plan(output, layout):
    output = Path(output)
    (output / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    scale, margin = 1.8, 50
    def rect(bounds, fill, stroke="none", extra=""):
        x0, z0, x1, z1 = bounds
        return (f'<rect x="{margin + (x0 + 250) * scale:.2f}" y="{150 + (z0 + 250) * scale:.2f}" '
                f'width="{(x1 - x0) * scale:.2f}" height="{(z1 - z0) * scale:.2f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1.5" {extra}/>')
    def text(x, y, value, size=16, extra=""):
        return f'<text x="{x}" y="{y}" font-size="{size}" {extra}>{html.escape(value)}</text>'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1260" viewBox="0 0 1000 1260">',
           '<style>text{font-family:"Yu Gothic",Meiryo,sans-serif;fill:#243640}.lot{stroke:#536572;stroke-width:.5}</style>',
           '<rect width="1000" height="1260" fill="#f0f4f5"/>',
           text(50, 50, "汐見町 — 倉庫と地下鉄入口の配置", 30),
           text(50, 88, "16区画 × 20棟 + 倉庫1棟 = 321棟  ·  歩道端から1.4m  ·  建物間1–12m"),
           text(50, 116, "小さいビルの左右：1–2.4m  ·  北↑／南↓  ·  500m × 500m"),
           rect((-250, -250, 250, 250), "#d9d8c9")]
    intervals = ((-250, -130), (-120, -10), (10, 120), (130, 250))
    for center in (-125, 0, 125):
        half, carriage = (10, 6) if center == 0 else (5, 3)
        svg.extend((rect((-250, center-half, 250, center+half), "#b7bbb8"),
                    rect((center-half, -250, center+half, 250), "#b7bbb8"),
                    rect((-250, center-carriage, 250, center+carriage), "#5e666b"),
                    rect((center-carriage, -250, center+carriage, 250), "#5e666b")))
    colors = {"02-apartment": "#bfa486", "03-convenience": "#dfcdb4", "04-office": "#829eac",
              "brick_red": "#a96249", "brick_sand": "#c49b72", "brick_charcoal": "#67615b",
              "tile_sand": "#c5b494", "tile_rose": "#c1a198", "tile_gray": "#8b969a",
              "paint_cream": "#ddcdb1", "paint_sage": "#95a58d", "paint_blue": "#8aa7b7"}
    for site in layout["buildings"]:
        svg.append(rect(site["bounds"], colors[site.get("facade", site.get("blueprint"))], extra='class="lot"'))
    for facility in layout.get("facilities", []):
        for area in layout.get("occupiedSites", []):
            if area["facility"] == facility["id"]:
                svg.append(rect(area["bounds"], "#d0c7b7", "#785f49", extra='stroke-dasharray="5 3"'))
        if "loadingApron" in facility:
            svg.append(rect(facility["loadingApron"], "#969d9b"))
        if "elevatorApproach" in facility:
            svg.append(rect(facility["elevatorApproach"], "#cc9a75"))
        for walkway in facility["pedestrianRoute"]:
            svg.append(rect(walkway, "#cc9a75"))
        svg.append(rect(facility["bounds"], "#516e7c", "#243640"))
    for row, (z0, z1) in enumerate(intervals):
        for column, (x0, x1) in enumerate(intervals):
            svg.append(text(margin+(x0+252)*scale, 150+(z0+248)*scale, "20棟", 12))
    for index, reserve in enumerate(layout["reservedSites"], start=1):
        svg.append(rect(reserve["bounds"], "#f8da7d" if index == 1 else "#a8d8ce", "#243640",
                        extra='stroke-dasharray="5 3"'))
        x0, z0, x1, z1 = reserve["bounds"]
        svg.append(text(margin+((x0+x1)/2+250)*scale, 150+((z0+z1)/2+250)*scale,
                        str(index), 26, extra='text-anchor="middle" font-weight="bold"'))
        width, depth = reserve["size_m"]
        svg.append(text(50, 1100+(index-1)*35,
                        f'{index}  {reserve["use"]}用：{width:.1f} × {depth:.1f}m'))
    svg.append(text(50, 1155, "倉庫25×26.5m：北側荷捌き場と車両入口、西側1.8m幅の歩行通路", 16))
    svg.append(text(50, 1180, "地下鉄：地上0.15m → B1 -5.85m → B2 -11.85m／東側歩道から入口とEVへ接続", 15))
    svg.extend((text(50, 1200, "色付き矩形＝建物の外形／点線＝倉庫・地下鉄入口の敷地", 15),
                text(50, 1230, "階数・色・間隔は固定シード91108で再現。正確な座標と間隔はlayout.jsonに記録。", 14), '</svg>'))
    (output / "density-plan.svg").write_text("\n".join(svg), encoding="utf-8")


if __name__ == "__main__":
    output = Path(sys.argv[1]).resolve()
    recipe = json.loads((output / "recipe.json").read_text(encoding="utf-8"))
    write_plan(output, recipe["asset"]["extras"]["city_layout"])
