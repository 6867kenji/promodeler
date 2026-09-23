"""Host-side orchestration: load an asset module, produce a recipe, run the kernel, collect results.

Two cache keys keep iteration fast. The asset key covers geometry,
materials and quality: it names the output directory and decides whether
baked textures can be reused. The render key covers views, passes,
environment and engine: it names the renders subdirectory. Changing only
render settings therefore never repeats a bake.
"""

from __future__ import annotations

import glob
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from . import KERNEL_VERSION
from .contact_sheet import make_contact_sheet
from .blueprint_qa import check_blueprint
from .video import encode_frames
from .core import Asset, AssetGenerator, ExportSettings, ModelingError, RenderSettings, build_recipe, dump_recipe, recipe_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KERNEL_ENTRY = Path(__file__).resolve().parent / "kernel" / "entry.py"


class BlenderNotFound(RuntimeError):
    pass


def find_blender() -> str:
    """``PROMODELER_BLENDER`` wins; then PATH; then the standard Windows install locations."""
    env = os.environ.get("PROMODELER_BLENDER")
    if env:
        if os.path.isfile(env):
            return env
        raise BlenderNotFound(f"PROMODELER_BLENDER points to a missing file: {env}")
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    candidates = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise BlenderNotFound("Blender was not found. Set PROMODELER_BLENDER to the blender executable.")


_version_cache: dict[str, str] = {}


def blender_version(executable: str) -> str:
    if executable in _version_cache:
        return _version_cache[executable]
    out = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=60, check=False)
    for line in out.stdout.splitlines():
        if line.startswith("Blender "):
            _version_cache[executable] = line.split()[1]
            return _version_cache[executable]
    raise BlenderNotFound(f"Could not read the Blender version from {executable}.")


def _merge_render(base: RenderSettings, override) -> RenderSettings:
    """A ``RenderSettings`` replaces the asset's settings; a dict replaces only the named fields."""
    if override is None:
        return base
    if isinstance(override, dict):
        return replace(base, **override)
    return override


@dataclass
class LoadedAsset:
    asset: Asset
    recipe: dict
    name: str
    blueprint: dict | None = None
    blueprint_path: Path | None = None
    blueprint_part_map: dict | None = None
    blueprint_motion_map: dict | None = None
    blueprint_required_parts: tuple[str, ...] = ()
    blueprint_texel_parts: tuple[str, ...] | None = None
    blueprint_envelope_mode: str = "exact"
    blueprint_prototype_parts: tuple[str, ...] = ()


def load_asset_module(path: str):
    module_path = Path(path).resolve()
    if not module_path.is_file():
        raise ModelingError("asset.file", f"Asset file not found: {module_path}")
    spec = importlib.util.spec_from_file_location(f"promodeler_asset_{module_path.stem}", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_asset(path: str, render=None, quality_overrides: dict | None = None, formats=None,
               parameter_overrides: dict | None = None) -> LoadedAsset:
    """An asset file exposes ``asset`` as an ``AssetGenerator`` or an ``Asset``; ``render`` and ``export`` are optional.

    ``quality_overrides`` replaces fields of the generator's quality profile,
    for example a lower texture resolution for a quick iteration. ``formats``
    overrides the export formats. ``parameter_overrides`` replaces fields of
    the generator's parameter dataclass (unknown names are an error), which is
    how a character recipe sizes its accessories.
    """
    module = load_asset_module(path)
    target = getattr(module, "asset", None)
    base_render = getattr(module, "render", None) or RenderSettings()
    render = _merge_render(base_render, render)
    export = getattr(module, "export", None) or ExportSettings()
    if formats:
        export = ExportSettings(formats=tuple(formats))
    if isinstance(target, AssetGenerator):
        quality = replace(target.quality, **quality_overrides) if quality_overrides else None
        parameters = None
        if parameter_overrides:
            unknown = [k for k in parameter_overrides if not hasattr(target.parameters, k)]
            if unknown:
                raise ModelingError("generator.parameters", f"{path}: parameters have no field(s) {unknown}.")
            parameters = replace(target.parameters, **parameter_overrides)
        input = target.make_input(parameters=parameters, quality=quality)
        asset = target.generate(input)
        recipe = build_recipe(
            asset, input, render,
            parameters=target.parameters_recipe(input.parameters),
            generator_version=target.version, export=export,
        )
    elif isinstance(target, Asset):
        target.validate()
        asset = target
        recipe = build_recipe(asset, None, render, export=export)
    else:
        raise ModelingError("asset.module", f"{path} must define `asset` as an AssetGenerator or Asset.")
    if quality_overrides and "texture_resolution" in quality_overrides:
        for part in recipe["asset"]["parts"]:
            if part.get("texture_resolution") is not None:
                part["texture_resolution"] = quality_overrides["texture_resolution"]
    blueprint = None
    blueprint_path = None
    blueprint_ref = getattr(module, "blueprint", None)
    if blueprint_ref is not None:
        blueprint_path = (Path(path).resolve().parent / blueprint_ref).resolve()
        if not blueprint_path.is_file():
            raise ModelingError("blueprint.file", f"Blueprint file not found: {blueprint_path}")
        raw = blueprint_path.read_bytes()
        blueprint = json.loads(raw)
        if blueprint.get("kind") in ("humanoid", "wearable"):
            raise ModelingError("blueprint.kind", "The non-character blueprint QA cannot validate a humanoid or wearable.")
        recipe["blueprint"] = {"id": blueprint.get("id"), "sha256": hashlib.sha256(raw).hexdigest()}
        dependencies = getattr(module, "blueprint_dependencies", ())
        recipe["blueprint"]["dependencies"] = []
        for dependency in dependencies:
            dependency_path = (Path(path).resolve().parent / dependency).resolve()
            if not dependency_path.is_file():
                raise ModelingError("blueprint.file", f"Blueprint dependency not found: {dependency_path}")
            recipe["blueprint"]["dependencies"].append({
                "path": dependency, "sha256": hashlib.sha256(dependency_path.read_bytes()).hexdigest(),
            })
    return LoadedAsset(
        asset=asset, recipe=recipe, name=asset.name, blueprint=blueprint, blueprint_path=blueprint_path,
        blueprint_part_map=getattr(module, "blueprint_part_map", None),
        blueprint_motion_map=getattr(module, "blueprint_motion_map", None),
        blueprint_required_parts=tuple(getattr(module, "blueprint_required_parts", ())),
        blueprint_texel_parts=getattr(module, "blueprint_texel_parts", None),
        blueprint_envelope_mode=getattr(module, "blueprint_envelope_mode", "exact"),
        blueprint_prototype_parts=tuple(getattr(module, "blueprint_prototype_parts", ())),
    )


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())


def asset_key(recipe: dict, blender: str) -> str:
    """Hash of everything except render and export settings, plus kernel and Blender versions."""
    without_render = {k: v for k, v in recipe.items() if k not in ("render", "export")}
    return recipe_hash(without_render, kernel_version=KERNEL_VERSION, blender=blender)


def render_key(recipe: dict) -> str:
    return recipe_hash({"render": recipe["render"], "export": recipe.get("export")}, kernel_version=KERNEL_VERSION)[:8]


@dataclass
class BuildResult:
    out_dir: Path
    report: dict
    cached: bool
    hash: str
    renders_dir: Path | None = None
    textures_reused: bool = False

    @property
    def ok(self) -> bool:
        return self.report.get("status") == "ok"

    @property
    def design_ok(self) -> bool:
        check = self.report.get("blueprint_qa")
        return self.ok and (check is None or check.get("status") == "pass")


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build(path: str, out_root: str = "build", force: bool = False, render=None,
          timeout: float = 1800.0, quality_overrides: dict | None = None, formats=None,
          parameter_overrides: dict | None = None) -> BuildResult:
    loaded = load_asset(path, render, quality_overrides, formats, parameter_overrides)
    blender = find_blender()
    version = blender_version(blender)
    digest = asset_key(loaded.recipe, version)
    rkey = render_key(loaded.recipe)
    out_dir = Path(out_root).resolve() / slugify(loaded.name) / digest[:12]
    renders_dir = out_dir / "renders" / rkey
    report_path = out_dir / "report.json"
    previous = _read_json(report_path)

    if previous and previous.get("status") == "ok" and previous.get("render_key") == rkey and not force:
        if all(Path(r["path"]).is_file() for r in previous.get("renders", [])):
            return BuildResult(out_dir=out_dir, report=previous, cached=True, hash=digest, renders_dir=renders_dir)

    reuse_textures = bool(previous and previous.get("status") == "ok" and (out_dir / "textures").is_dir() and not force)
    if force and out_dir.exists():
        shutil.rmtree(out_dir)
    if renders_dir.exists():
        shutil.rmtree(renders_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = out_dir / "recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        f.write(dump_recipe(loaded.recipe))
    command = [blender, "-b", "--python", str(KERNEL_ENTRY), "--", str(PROJECT_ROOT), str(recipe_path), str(out_dir),
               str(renders_dir), "reuse" if reuse_textures else "bake"]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                               encoding="utf-8", errors="replace")
    with open(out_dir / "blender.log", "w", encoding="utf-8") as f:
        f.write(completed.stdout)
        f.write("\n--- stderr ---\n")
        f.write(completed.stderr)
    report = _read_json(report_path)
    if report is None or "seconds" not in report:
        report = {
            "status": "failed",
            "error": {"code": "kernel.noReport", "message": f"Blender exited with {completed.returncode} without writing report.json. See blender.log."},
        }
    report["hash"] = digest
    report["render_key"] = rkey
    report["blender_exit_code"] = completed.returncode
    report["wall_seconds"] = round(time.perf_counter() - started, 3)
    if report.get("status") == "ok":
        if loaded.blueprint is not None:
            report["blueprint_qa"] = check_blueprint(
                loaded.blueprint, loaded.recipe, report,
                part_map=loaded.blueprint_part_map,
                motion_map=loaded.blueprint_motion_map,
                required_parts=loaded.blueprint_required_parts,
                texel_parts=loaded.blueprint_texel_parts,
                envelope_mode=loaded.blueprint_envelope_mode,
                prototype_parts=loaded.blueprint_prototype_parts,
            )
            reference = (loaded.blueprint.get("image_generation") or {}).get("reference_sheet")
            if reference and loaded.blueprint_path is not None:
                reference_path = loaded.blueprint_path.parent / reference
                if reference_path.is_file():
                    report["blueprint_qa"]["reference_image"] = str(reference_path)
        for entry in report.get("renders", []):
            if entry.get("video") and entry.get("frames_dir"):
                encoded = encode_frames(entry["frames_dir"], entry.get("fps", 24), Path(entry["frames_dir"]))
                entry.update({"path": encoded["path"], "format": encoded["format"], "encoder": encoded["encoder"],
                              "written": entry["written"] and encoded["written"]})
        report["contact_sheet"] = make_contact_sheet(report, renders_dir / "contact_sheet.png")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return BuildResult(out_dir=out_dir, report=report, cached=False, hash=digest, renders_dir=renders_dir,
                       textures_reused=reuse_textures)


def latest_build_dir(path_or_dir: str, out_root: str = "build") -> Path:
    """Resolve an asset file to its most recently modified build directory, or pass a directory through."""
    candidate = Path(path_or_dir)
    if candidate.is_dir():
        return candidate.resolve()
    loaded = load_asset(str(candidate))
    asset_dir = Path(out_root).resolve() / slugify(loaded.name)
    builds = [p for p in asset_dir.glob("*") if (p / "report.json").is_file()]
    if not builds:
        raise FileNotFoundError(f"No builds found under {asset_dir}")
    return max(builds, key=lambda p: (p / "report.json").stat().st_mtime)


def clean(out_root: str = "build", keep: int = 1) -> list[Path]:
    """Delete all but the ``keep`` newest builds of every asset. Returns the removed directories."""
    removed = []
    root = Path(out_root)
    if not root.is_dir():
        return removed
    for asset_dir in root.iterdir():
        if not asset_dir.is_dir():
            continue
        builds = sorted(
            (p for p in asset_dir.iterdir() if p.is_dir()),
            key=lambda p: (p / "report.json").stat().st_mtime if (p / "report.json").is_file() else 0,
            reverse=True,
        )
        for stale in builds[keep:]:
            shutil.rmtree(stale)
            removed.append(stale)
    return removed
