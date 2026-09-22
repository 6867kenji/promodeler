"""Side-by-side comparison of blueprint targets, recipe values and a Unity ``build.json``.

Nothing here is a pass/fail gate. It is the evidence list the blueprint's
QA section asks for, in the same shape as ``tools/blueprint_check.py``.
Until a Unity build exists, the table shows targets, the consistency
findings and the MHR reference fit when present.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .consistency import static_checks
from .recipe import CharacterRecipe, RecipeWarning


@dataclass(frozen=True)
class Row:
    label: str
    target: float | None
    got: float | None
    unit: str = "m"
    tolerance: float | None = None

    @property
    def diff(self) -> float | None:
        if self.target is None or self.got is None:
            return None
        return self.got - self.target

    @property
    def status(self) -> str:
        if self.diff is None:
            return "-"
        if self.tolerance is None:
            return "measured"
        return "ok" if abs(self.diff) <= self.tolerance else "OVER"


def load_build(build_dir: str | Path) -> dict | None:
    path = Path(build_dir) / "build.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def measurement_rows(recipe: CharacterRecipe, measured: dict | None) -> list[Row]:
    m = recipe.body.measurements_m
    tol = recipe.body.tolerances_m
    measured = measured or {}
    rows = [Row("barefoot_height", m.barefoot_height, measured.get("barefoot_height"), tolerance=tol.get("barefoot_height"))]
    for name in ("inseam", "shoulder_width", "foot_length", "head_height"):
        value = getattr(m, name)
        if value is not None:
            rows.append(Row(name, value, measured.get(name), tolerance=tol.get("length")))
    for name, value in m.circumferences.items():
        rows.append(Row(f"{name} circumference", value, measured.get(name), tolerance=tol.get("circumference")))
    for section in m.cross_sections:
        if section.width is not None:
            rows.append(Row(f"{section.landmark} width (report only)", section.width, measured.get(f"{section.landmark}_width")))
        if section.depth is not None:
            rows.append(Row(f"{section.landmark} depth (report only)", section.depth, measured.get(f"{section.landmark}_depth")))
    for garment in recipe.wardrobe:
        got = (measured.get("garments") or {}).get(garment.slot, {})
        for key, value in garment.finished_measurements_m.items():
            rows.append(Row(f"{garment.slot} {key}", value, got.get(key)))
    return rows


def budget_rows(recipe: CharacterRecipe, build: dict | None) -> list[Row]:
    target = recipe.target
    totals = (build or {}).get("totals") or {}
    parts = (build or {}).get("parts") or {}
    rows = [Row("triangles lod0", target.get("triangles_lod0_max"), totals.get("triangles"), unit="tris")]
    for name, budget in (target.get("triangles_by_part") or {}).items():
        rows.append(Row(f"triangles {name}", budget, (parts.get(name) or {}).get("triangles"), unit="tris"))
    rows.append(Row("texture resident MiB", target.get("texture_resident_budget_mib"), totals.get("texture_resident_mib"), unit="MiB"))
    return rows


def compare(recipe: CharacterRecipe, build: dict | None = None) -> tuple[list[Row], list[Row], list[RecipeWarning]]:
    """Measurement rows, budget rows and consistency/build warnings for a recipe and an optional build."""
    measured = None
    warnings = list(static_checks(recipe.body.measurements_m))
    if build is not None:
        measured = build.get("measured_m") or {}
        for warning in build.get("warnings") or []:
            warnings.append(RecipeWarning(warning.get("code", "build"), warning.get("message", "")))
    elif recipe.body.reference_fit is not None:
        measured = dict(recipe.body.reference_fit.measured_m)
        measured["barefoot_height"] = measured.get("height")
        if "chest" in recipe.body.measurements_m.circumferences or any(s.landmark == "chest" for s in recipe.body.measurements_m.cross_sections):
            for suffix in ("", "_width", "_depth"):  # the MHR fit measures a male chest on its bust plane
                if f"bust{suffix}" in measured:
                    measured[f"chest{suffix}"] = measured[f"bust{suffix}"]
    return measurement_rows(recipe, measured), budget_rows(recipe, build), warnings


def format_row(row: Row) -> str:
    scale = 1000.0 if row.unit == "m" else 1.0
    unit = "mm" if row.unit == "m" else row.unit
    target = "-" if row.target is None else f"{row.target:.3f}" if row.unit == "m" else f"{row.target:.0f}"
    got = "-" if row.got is None else f"{row.got:.3f}" if row.unit == "m" else f"{row.got:.0f}"
    diff = "" if row.diff is None else f"{row.diff * scale:+8.1f} {unit}"
    flag = "" if row.status in ("-", "measured") else f"  {row.status}" + (f" (tol {row.tolerance * scale:.0f} {unit})" if row.status == "OVER" else "")
    return f"  {row.label:34s} {target:>9}  {got:>9}  {diff}{flag}"


def format_table(recipe: CharacterRecipe, rows: list[Row], budgets: list[Row], warnings: list[RecipeWarning], source_label: str) -> str:
    lines = [f"recipe:    {recipe.id} ({recipe.name})", f"measured:  {source_label}",
             "", "[measurements]                        target        got      diff"]
    lines += [format_row(r) for r in rows]
    lines += ["", "[budgets]                              max        got"]
    lines += [format_row(r) for r in budgets]
    lines += ["", f"warnings: {len(warnings)}"]
    lines += [f"  {w.code}: {w.message}" for w in warnings]
    return "\n".join(lines)
