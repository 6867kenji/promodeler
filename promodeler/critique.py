"""Visual critique of a build by Claude: reads the contact sheet, the QA report and an optional reference photo.

Inside an agent session the agent can simply look at the contact sheet.
This module automates the same judgement for unattended pipelines, and
returns a structured verdict that an agent or a script can act on.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"
MAX_IMAGES = 5

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "Overall realism and craft from 1 (unusable) to 10 (indistinguishable from a photo)."},
        "verdict": {"type": "string", "description": "One or two sentences on what the asset reads as and how convincing it is."},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string", "enum": ["silhouette", "proportion", "material", "detail", "lighting", "uv", "topology", "scale", "other"]},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string", "description": "A concrete change to the asset code: which shape, modifier, preset argument or field to adjust and roughly by how much."},
                },
                "required": ["area", "severity", "description", "suggestion"],
                "additionalProperties": False,
            },
        },
        "next_steps": {"type": "array", "items": {"type": "string"}, "description": "Ordered list of the changes most worth making next."},
    },
    "required": ["score", "verdict", "strengths", "issues", "next_steps"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a senior 3D asset artist reviewing a procedurally generated model.
You see verification renders (a contact sheet of views and diagnostic passes), a numerical QA
summary, and sometimes a reference photograph. Judge silhouette, proportions, material response,
surface detail, wear placement, scale cues and lighting. Be specific and honest: name what looks
computer-generated and why. Suggestions must be actionable edits to the asset definition, which is
written with the promodeler Python API (shapes, modifiers such as Bevel/Boolean/Displace, layered
materials built from fields such as Noise, Voronoi, Curvature and Cavity, and presets with
parameters like wear, rust and edge_radius). Do not comment on the gray studio background."""


def _image_block(path: Path) -> dict:
    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def report_summary(report: dict) -> dict:
    """The parts of report.json a reviewer needs, without paths."""
    parts = {}
    for part_id, stats in report.get("parts", {}).items():
        parts[part_id] = {
            key: stats.get(key)
            for key in ("triangles", "watertight", "volume", "self_intersections", "non_manifold_edges", "uv")
        }
        if "textures" in stats:
            parts[part_id]["textures"] = {c: m.get("resolution") for c, m in stats["textures"].items()}
    return {
        "asset": report.get("asset"),
        "bounds": report.get("bounds"),
        "parts": parts,
        "warnings": report.get("warnings", []),
        "blueprint_qa": {k: v for k, v in report.get("blueprint_qa", {}).items() if k != "reference_image"},
    }


def select_images(out_dir: Path, report: dict) -> list[Path]:
    """The contact sheet when present, otherwise the shaded renders."""
    sheet = report.get("contact_sheet")
    if sheet and Path(sheet["path"]).is_file():
        return [Path(sheet["path"])]
    renders = [Path(r["path"]) for r in report.get("renders", []) if r.get("written") and r.get("pass", "shaded") == "shaded"]
    return renders[:MAX_IMAGES]


def build_messages(images: list[Path], summary: dict, goal: str | None, reference: Path | None) -> list[dict]:
    content: list[dict] = []
    for image in images:
        content.append(_image_block(image))
    text = ["Verification renders of the generated asset are above."]
    if reference is not None:
        content.append(_image_block(reference))
        text.append("The last image is a visual reference, possibly concept art. Compare its intended appearance, "
                    "but use the numerical blueprint checks for dimensions and part counts.")
    if goal:
        text.append(f"The author's intent: {goal}")
    text.append("Numerical QA summary (JSON):\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    text.append("Review the asset and answer in the required JSON structure.")
    content.append({"type": "text", "text": "\n\n".join(text)})
    return [{"role": "user", "content": content}]


def critique_build(out_dir: str | Path, reference: str | None = None, goal: str | None = None,
                   model: str = DEFAULT_MODEL, fallbacks: bool = True) -> dict:
    """Ask Claude to review a finished build. Writes and returns ``critique.json``."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("The `anthropic` package is required for critique: pip install anthropic") from exc

    out_dir = Path(out_dir)
    report_path = out_dir / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"No report.json in {out_dir}")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    if report.get("status") != "ok":
        raise RuntimeError(f"Build {out_dir} did not succeed; nothing to critique.")
    images = select_images(out_dir, report)
    if not images:
        raise RuntimeError("The build has no renders to review.")
    reference_path = Path(reference) if reference else None
    if reference_path is None:
        linked_reference = report.get("blueprint_qa", {}).get("reference_image")
        if linked_reference and Path(linked_reference).is_file():
            reference_path = Path(linked_reference)
    if reference_path is not None and not reference_path.is_file():
        raise FileNotFoundError(f"Reference image not found: {reference_path}")
    messages = build_messages(images, report_summary(report), goal, reference_path)

    client = anthropic.Anthropic()
    request = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": CRITIQUE_SCHEMA}},
    )
    if fallbacks:
        # Route policy declines to a fallback model server-side instead of returning nothing.
        response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **request)
    else:
        response = client.messages.create(**request)
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise RuntimeError(f"The model declined to review this build: {getattr(details, 'explanation', None)}")
    text = next(block.text for block in response.content if block.type == "text")
    critique = json.loads(text)
    critique["model"] = response.model
    critique["images"] = [str(p) for p in images]
    if reference_path is not None:
        critique["reference"] = str(reference_path)
    with open(out_dir / "critique.json", "w", encoding="utf-8") as f:
        json.dump(critique, f, indent=2, ensure_ascii=False)
    return critique


def format_critique(critique: dict) -> str:
    lines = [f"score:    {critique['score']}/10", f"verdict:  {critique['verdict']}"]
    for item in critique.get("strengths", []):
        lines.append(f"  + {item}")
    for issue in critique.get("issues", []):
        lines.append(f"  - [{issue['severity']}/{issue['area']}] {issue['description']}")
        lines.append(f"      -> {issue['suggestion']}")
    for index, step in enumerate(critique.get("next_steps", []), 1):
        lines.append(f"  {index}. {step}")
    return "\n".join(lines)
