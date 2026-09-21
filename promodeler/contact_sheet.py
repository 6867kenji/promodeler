"""Compose every render of a build into one labeled contact sheet (host side, needs Pillow)."""

from __future__ import annotations

from pathlib import Path


def make_contact_sheet(report: dict, out_path: Path, cell: int = 384) -> dict | None:
    """Rows are passes, columns are views. Returns metadata, or ``None`` when Pillow is unavailable."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    renders = [r for r in report.get("renders", []) if r.get("written")]
    if not renders:
        return None
    views = list(dict.fromkeys(r["view"] for r in renders))
    passes = list(dict.fromkeys(r.get("pass", "shaded") for r in renders))
    label_h = 18
    width = cell * len(views)
    height = (cell + label_h) * len(passes)
    sheet = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    lookup = {(r.get("pass", "shaded"), r["view"]): r["path"] for r in renders}
    for row, pass_name in enumerate(passes):
        for col, view in enumerate(views):
            path = lookup.get((pass_name, view))
            x = col * cell
            y = row * (cell + label_h)
            draw.text((x + 6, y + 3), f"{pass_name} / {view}", fill=(230, 230, 230))
            if path is None:
                continue
            with Image.open(path) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((cell, cell))
                sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + label_h + (cell - thumb.height) // 2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return {"path": str(out_path), "views": views, "passes": passes, "width": width, "height": height}
