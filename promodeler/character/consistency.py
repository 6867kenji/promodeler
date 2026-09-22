"""Measurement consistency: catch blueprint contradictions before any Unity build.

Static checks compare each cross section's ellipse perimeter with the
circumference given for the same landmark and body ratios with adult
ranges. The optional MHR reference fit (``torch`` required) asks the
parametric body whether these numbers describe a possible human and
records the residuals in ``body.reference_fit``.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .recipe import CharacterRecipe, Measurements, RecipeWarning, ReferenceFit

SECTION_TOLERANCE = 0.03  # relative difference between the ellipse perimeter and the stated circumference
RATIO_RANGES = {  # fraction of barefoot height for adults
    "inseam": (0.42, 0.52), "shoulder_width": (0.19, 0.27), "foot_length": (0.13, 0.17), "head_height": (0.12, 0.15),
}
GIRTH_RANGES = {  # circumference / height
    "chest": (0.45, 0.75), "bust": (0.45, 0.75), "underbust": (0.38, 0.6), "waist": (0.32, 0.7), "hip": (0.45, 0.72),
}


def ellipse_perimeter(width: float, depth: float) -> float:
    """Ramanujan's approximation of the perimeter of an ellipse with the given full axes."""
    a, b = width / 2.0, depth / 2.0
    if a + b <= 0.0:
        return 0.0
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1.0 + 3.0 * h / (10.0 + math.sqrt(4.0 - 3.0 * h)))


def static_checks(measurements: Measurements) -> list[RecipeWarning]:
    warnings: list[RecipeWarning] = []
    height = measurements.barefoot_height
    for name, (lo, hi) in RATIO_RANGES.items():
        value = getattr(measurements, name)
        if value is not None and not lo <= value / height <= hi:
            warnings.append(RecipeWarning("measurements.ratio", f"{name} {value:.3f} m is {value / height:.3f} of the height; adults are {lo}...{hi}."))
    for name, value in measurements.circumferences.items():
        lo, hi = GIRTH_RANGES.get(name, (0.0, 10.0))
        if not lo <= value / height <= hi:
            warnings.append(RecipeWarning("measurements.ratio", f"{name} circumference {value:.3f} m is {value / height:.3f} of the height; adults are {lo}...{hi}."))
    for section in measurements.cross_sections:
        if section.width is None or section.depth is None:
            continue
        stated = section.circumference or measurements.circumferences.get(section.landmark)
        if not stated:
            continue
        perimeter = ellipse_perimeter(section.width, section.depth)
        diff = perimeter - stated
        if abs(diff) / stated > SECTION_TOLERANCE:
            warnings.append(RecipeWarning(
                "measurements.sectionVsCircumference",
                f"{section.landmark}: ellipse {section.width:.3f} x {section.depth:.3f} m has perimeter {perimeter:.3f} m but the circumference is "
                f"{stated:.3f} m ({diff * 1000:+.0f} mm); circumferences lead, section extents are reported only."))
    return warnings


def mhr_targets(measurements: Measurements) -> dict:
    """Recipe measurements in the vocabulary of ``promodeler.human.mhr.fitted_body``. ``chest`` maps to MHR's bust plane."""
    targets = {
        "height": measurements.barefoot_height, "inseam": measurements.inseam, "shoulder_width": measurements.shoulder_width,
        "foot_length": measurements.foot_length, "head_height": measurements.head_height,
    }
    for name, value in measurements.circumferences.items():
        targets["bust" if name == "chest" else name] = value
    for section in measurements.cross_sections:
        landmark = "bust" if section.landmark == "chest" else section.landmark
        if section.width is not None:
            targets[f"{landmark}_width"] = section.width
        if section.depth is not None:
            targets[f"{landmark}_depth"] = section.depth
    return {k: float(v) for k, v in targets.items() if v}


ACROMION_FRACTION = 0.818  # acromial height / stature for adults (Drillis & Contini), used when no shoulders section is given


def mhr_landmarks(measurements: Measurements) -> dict:
    """Landmark planes as fractions of the height from the recipe's cross sections; ``chest`` maps to MHR's bust plane.

    Sections the recipe does not give fall back to MHR's 05-woman defaults, except the shoulders, which use the
    adult acromion fraction: the 05-woman value (0.8375) cuts a 1.76 m man's neck instead of his shoulders.
    """
    height = measurements.barefoot_height
    landmarks = {"shoulders": ACROMION_FRACTION}
    for section in measurements.cross_sections:
        name = "bust" if section.landmark == "chest" else section.landmark
        landmarks[name] = round(section.height / height, 5)
    return landmarks


def reference_fit(recipe: CharacterRecipe, out_root="build/human", log=None) -> ReferenceFit:
    """Run the MHR fit on the recipe's measurements (cached under ``out_root``) and return the residuals."""
    from ..human import mhr  # torch is imported lazily inside

    targets = mhr_targets(recipe.body.measurements_m)
    landmarks = mhr_landmarks(recipe.body.measurements_m)
    fit = mhr.fitted_body(targets, out_root=out_root, name=f"ref-{recipe.id}", log=log, landmarks=landmarks)
    measured = {k: round(float(v), 4) for k, v in fit["measurements"].items() if isinstance(v, (int, float))}
    residuals = {k: round(measured[k] - v, 4) for k, v in targets.items() if k in measured}
    return ReferenceFit(
        solver="mhr", fit_version=mhr.FIT_VERSION, measured_m=measured, residuals_m=residuals,
        seconds=measured.get("fit_seconds"),
        note=f"Landmark planes (fraction of height): {landmarks}; chest is measured on MHR's bust plane. Reference only, not the Unity result.",
    )


def with_reference_fit(recipe: CharacterRecipe, fit: ReferenceFit) -> CharacterRecipe:
    return replace(recipe, body=replace(recipe.body, reference_fit=fit))
