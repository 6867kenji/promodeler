"""Host-side orchestration: load an asset module, produce a recipe, run the kernel, collect results."""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import KERNEL_VERSION
from .core import Asset, AssetGenerator, ModelingError, RenderSettings, build_recipe, dump_recipe, recipe_hash

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


def blender_version(executable: str) -> str:
    out = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=60, check=False)
    for line in out.stdout.splitlines():
        if line.startswith("Blender "):
            return line.split()[1]
    raise BlenderNotFound(f"Could not read the Blender version from {executable}.")


@dataclass
class LoadedAsset:
    asset: Asset
    recipe: dict
    name: str


def load_asset_module(path: str):
    module_path = Path(path).resolve()
    if not module_path.is_file():
        raise ModelingError("asset.file", f"Asset file not found: {module_path}")
    spec = importlib.util.spec_from_file_location(f"promodeler_asset_{module_path.stem}", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_asset(path: str, render: RenderSettings | None = None) -> LoadedAsset:
    """An asset file exposes ``asset`` as an ``AssetGenerator`` or an ``Asset``; ``render`` is optional."""
    module = load_asset_module(path)
    target = getattr(module, "asset", None)
    render = render or getattr(module, "render", None) or RenderSettings()
    if isinstance(target, AssetGenerator):
        input = target.make_input()
        asset = target.generate(input)
        recipe = build_recipe(
            asset, input, render,
            parameters=target.parameters_recipe(input.parameters),
            generator_version=target.version,
        )
    elif isinstance(target, Asset):
        target.validate()
        asset = target
        recipe = build_recipe(asset, None, render)
    else:
        raise ModelingError("asset.module", f"{path} must define `asset` as an AssetGenerator or Asset.")
    return LoadedAsset(asset=asset, recipe=recipe, name=asset.name)


@dataclass
class BuildResult:
    out_dir: Path
    report: dict
    cached: bool
    hash: str

    @property
    def ok(self) -> bool:
        return self.report.get("status") == "ok"


def build(path: str, out_root: str = "build", force: bool = False, render: RenderSettings | None = None,
          timeout: float = 600.0) -> BuildResult:
    loaded = load_asset(path, render)
    blender = find_blender()
    version = blender_version(blender)
    digest = recipe_hash(loaded.recipe, kernel_version=KERNEL_VERSION, blender=version)
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in loaded.name.lower())
    out_dir = Path(out_root).resolve() / slug / digest[:12]
    report_path = out_dir / "report.json"
    if report_path.is_file() and not force:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        if report.get("status") == "ok":
            return BuildResult(out_dir=out_dir, report=report, cached=True, hash=digest)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    recipe_path = out_dir / "recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        f.write(dump_recipe(loaded.recipe))
    command = [blender, "-b", "--python", str(KERNEL_ENTRY), "--", str(PROJECT_ROOT), str(recipe_path), str(out_dir)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                               encoding="utf-8", errors="replace")
    with open(out_dir / "blender.log", "w", encoding="utf-8") as f:
        f.write(completed.stdout)
        f.write("\n--- stderr ---\n")
        f.write(completed.stderr)
    if not report_path.is_file():
        report = {
            "status": "failed",
            "error": {"code": "kernel.noReport", "message": f"Blender exited with {completed.returncode} without writing report.json. See blender.log."},
        }
    else:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    report["hash"] = digest
    report["blender_exit_code"] = completed.returncode
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return BuildResult(out_dir=out_dir, report=report, cached=False, hash=digest)
