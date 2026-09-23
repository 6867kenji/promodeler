"""Host side of the Unity character creator: locate the editor, stage a recipe, run the batch build, collect build.json.

Mirrors ``promodeler.build`` for asset builds: the recipe (plus outfit,
catalog version, Unity/UMA versions and accessory GLB hashes) is the
cache key, the output lands in ``build/character/<id>/<hash>/`` and a
``build.json`` is always read back, so a crashed editor is reported as a
failed build and never mistaken for a result. See
docs/03-character-recipe-pipeline.md chapter 9.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..contact_sheet import make_contact_sheet
from ..core.diagnostics import ModelingError
from .catalog import Catalog
from .recipe import CharacterRecipe, OutfitRecipe, recipe_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UNITY_PROJECT = PROJECT_ROOT / "unity" / "ProModelerCharacterCreator"
UMA_SOURCE = PROJECT_ROOT / "external" / "uma" / "UMAProject" / "Assets" / "UMA"  # sparse clone of umasteeringgroup/UMA v3.05
UMA_GIT = "https://github.com/umasteeringgroup/UMA"
UMA_TAG = "v3.05"
BATCH_METHOD = "ProModeler.Editor.CharacterBatchBuilder.Build"
SETUP_METHOD = "ProModeler.Editor.ProjectSetup.Run"
DEFAULT_VIEWS = ("front", "side", "back", "perspective", "face")
DEFAULT_PASSES = ("shaded", "clay")
DEFAULT_FORMATS = ("fbx", "glb")


class UnityNotFound(RuntimeError):
    pass


# --- environment -------------------------------------------------------------------------------

def project_version(project: Path = UNITY_PROJECT) -> str | None:
    """The Unity editor version pinned by the project, or None when the project does not exist yet."""
    path = project / "ProjectSettings" / "ProjectVersion.txt"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    return None


def find_unity(project: Path = UNITY_PROJECT) -> str:
    """``PROMODELER_UNITY`` wins; then PATH; then the Unity Hub install matching the project version, else the newest."""
    env = os.environ.get("PROMODELER_UNITY")
    if env:
        if os.path.isfile(env):
            return env
        raise UnityNotFound(f"PROMODELER_UNITY points to a missing file: {env}")
    on_path = shutil.which("Unity")
    if on_path:
        return on_path
    candidates = sorted(glob.glob(r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe"), reverse=True)
    wanted = project_version(project)
    for candidate in candidates:
        if wanted and f"\\{wanted}\\" in candidate:
            return candidate
    if candidates:
        return candidates[0]
    raise UnityNotFound("Unity was not found. Install it with Unity Hub or set PROMODELER_UNITY to Unity.exe.")


def uma_version(project: Path = UNITY_PROJECT) -> str | None:
    """UMA version from Assets/UMA/package.json (UMA 3 ships as an Assets folder), else a UPM manifest entry."""
    package = project / "Assets" / "UMA" / "package.json"
    if package.is_file():
        try:
            return str(json.loads(package.read_text(encoding="utf-8")).get("version"))
        except (OSError, ValueError):
            return None
    manifest = project / "Packages" / "manifest.json"
    if manifest.is_file():
        dependencies = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})
        for key, value in dependencies.items():
            if "uma" in key.lower():
                return str(value)
    return None


def project_ready(project: Path = UNITY_PROJECT) -> tuple[bool, str]:
    """Whether the Unity project has what a batch build needs, with the first missing item."""
    if not project.is_dir():
        return False, f"Unity project not present at {project} (M10)."
    if not (project / "Assets" / "ProModeler" / "Editor" / "Batch" / "CharacterBatchBuilder.cs").is_file():
        return False, "Assets/ProModeler/Editor/Batch/CharacterBatchBuilder.cs is missing."
    if not (project / "Assets" / "UMA" / "Core").is_dir():
        return False, "UMA is not linked into the Unity project (Assets/UMA/Core); run `promodeler character setup`."
    return True, ""


# --- project setup --------------------------------------------------------------------------------

def link_uma(project: Path = UNITY_PROJECT, source: Path = UMA_SOURCE) -> dict:
    """Make Assets/UMA of the Unity project point at the sparse clone under external/uma.

    UMA 3 expects to live at ``Assets/UMA`` (its HDRP content package and setup script use that path), so a
    directory junction is created instead of a UPM package entry. The clone is gitignored; ``UMA.meta`` is copied
    next to the junction so the folder keeps UMA's GUID.
    """
    assets = project / "Assets"
    target = assets / "UMA"
    meta_source = source.parent / "UMA.meta"
    if not (source / "Core").is_dir():
        raise UnityNotFound(
            f"UMA source not found at {source}. Clone it with:\n"
            f"  git clone --filter=blob:none --sparse --depth 1 --branch {UMA_TAG} {UMA_GIT} external/uma\n"
            f"  git -C external/uma sparse-checkout set UMAProject/Assets/UMA UMAProject/Assets/UMA2")
    assets.mkdir(parents=True, exist_ok=True)
    created = False
    if target.exists() or target.is_symlink():
        if not (target / "Core").is_dir():
            raise UnityNotFound(f"{target} exists but is not a UMA folder; remove it and rerun setup.")
    else:
        if os.name == "nt":
            completed = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(source)], capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise UnityNotFound(f"mklink /J failed: {completed.stdout.strip()} {completed.stderr.strip()}")
        else:
            target.symlink_to(source, target_is_directory=True)
        created = True
    if meta_source.is_file() and not (assets / "UMA.meta").is_file():
        shutil.copyfile(meta_source, assets / "UMA.meta")
    return {"target": str(target), "source": str(source), "created": created, "uma": uma_version(project)}


def extract_unitypackage(package: Path, assets_parent: Path, overwrite: bool = True) -> dict:
    """Unpack a .unitypackage (tar.gz of <guid>/{asset, asset.meta, pathname}) under ``assets_parent``.

    Unity's ``AssetDatabase.ImportPackage`` is asynchronous in batch mode, so the editor may exit before the
    import lands; extracting the archive ourselves is deterministic. ``pathname`` entries start with ``Assets/``
    and are written relative to ``assets_parent`` (the directory that contains ``Assets``). Returns counts.
    """
    written = skipped = unchanged = 0
    with tarfile.open(package, "r:gz") as archive:
        members = {m.name: m for m in archive.getmembers()}
        for name, member in members.items():
            if not name.endswith("/pathname") or not member.isfile():
                continue
            folder = name[: -len("/pathname")]
            target_rel = archive.extractfile(member).read().decode("utf-8").splitlines()[0].strip()
            if not target_rel.startswith("Assets/"):
                skipped += 1
                continue
            target = assets_parent / target_rel
            asset = members.get(folder + "/asset")
            meta = members.get(folder + "/asset.meta")
            if asset is None:  # a folder entry: only its .meta exists
                target.mkdir(parents=True, exist_ok=True)
            else:
                data = archive.extractfile(asset).read()
                if target.is_file() and target.read_bytes() == data:
                    unchanged += 1
                elif target.is_file() and not overwrite:
                    skipped += 1
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    written += 1
            if meta is not None:
                meta_path = Path(str(target) + ".meta")
                meta_data = archive.extractfile(meta).read()
                if not (meta_path.is_file() and meta_path.read_bytes() == meta_data):
                    meta_path.parent.mkdir(parents=True, exist_ok=True)
                    meta_path.write_bytes(meta_data)
    return {"package": str(package), "written": written, "unchanged": unchanged, "skipped": skipped}


def install_uma_hdrp_content(project: Path = UNITY_PROJECT) -> dict:
    """Unpack UMA's HDRP content (materials, shader graphs, setup prefab) next to the UMA sources."""
    package = project / "Assets" / "UMA" / "SRP" / "UMAHDRP.unitypackage"
    if not package.is_file():
        raise UnityNotFound(f"UMA HDRP package not found at {package}; is Assets/UMA linked?")
    result = extract_unitypackage(package, project)
    result["setup_prefab"] = (project / "Assets" / "UMA" / "SRP" / "HDRPSetup" / "UMAHDRPSetup.prefab").is_file()
    return result


def run_setup(project: Path = UNITY_PROJECT, timeout: float = 1800.0, log=None) -> dict:
    """Run the editor-side setup (HDRP content import, UMA index) and return Assets/ProModeler/setup.json."""
    unity = find_unity(project)
    log_path = project / "Logs" / "promodeler-setup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [unity, "-batchmode", "-projectPath", str(project), "-executeMethod", SETUP_METHOD, "-logFile", str(log_path)]
    if log:
        log("unity: " + " ".join(command))
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, encoding="utf-8", errors="replace",
                               cwd=str(project))  # never let the editor mistake the repository root for a project
    status_path = project / "Assets" / "ProModeler" / "setup.json"
    status = _read_json(status_path) or {}
    status["unity_exit_code"] = completed.returncode
    status["log"] = str(log_path)
    if completed.returncode == 198 or "No valid Unity Editor license" in (completed.stdout + completed.stderr):
        status["error"] = "Unity has no active license. Sign in with Unity Hub and activate a license, then rerun setup."
        status["Ok"] = False
    return status


# --- staging -------------------------------------------------------------------------------------

@dataclass
class Staged:
    out_dir: Path
    hash: str
    recipe_path: Path
    outfit_path: Path | None
    assets: dict  # accessory id -> {"glb": path, "hash": asset hash}


def _build_accessories(recipe: CharacterRecipe, force: bool, log=None) -> dict:
    """Build promodeler-authored accessories with the Blender pipeline; returns id -> {glb, hash} for the ones that exist."""
    from .. import build as asset_build

    assets: dict = {}
    for accessory in recipe.accessories:
        source = accessory.source
        if source.kind != "promodeler_asset" or not source.path:
            continue
        path = PROJECT_ROOT / source.path
        if not path.is_file():
            assets[accessory.id] = {"glb": None, "hash": None, "missing": str(path)}
            continue
        if log:
            log(f"accessory {accessory.id}: building {source.path} with Blender")
        overrides = {"size": tuple(accessory.size_xyz_m)} if accessory.size_xyz_m else None
        try:
            result = asset_build.build(str(path), force=force, render={"views": ("perspective",), "passes": ("shaded",), "resolution": 256},
                                       parameter_overrides=overrides)
        except ModelingError as exc:
            if exc.code != "generator.parameters":
                raise
            result = asset_build.build(str(path), force=force, render={"views": ("perspective",), "passes": ("shaded",), "resolution": 256})
        glb = result.report.get("export", {}).get("path") if result.ok else None
        extras = _read_json(result.out_dir / "extras.json") or {}
        assets[accessory.id] = {"glb": glb, "hash": result.hash[:12], "ok": result.ok, "socket": extras.get("promodeler_socket"),
                                "error": None if result.ok else result.report.get("error")}
    return assets


def stage(recipe: CharacterRecipe, outfit: OutfitRecipe | None, catalog: Catalog, out_root: str | Path = "build/character",
          force: bool = False, log=None, project: Path = UNITY_PROJECT) -> Staged:
    """Resolve accessories, compute the cache key and write recipe.json / outfit.json / assets.json into the output directory."""
    assets = _build_accessories(recipe, force, log)
    environment = {
        "outfit": outfit.to_json() if outfit else None,
        "catalog_version": catalog.version,
        "unity": project_version(project),
        "uma": uma_version(project),
        "accessories": {k: v.get("hash") for k, v in assets.items()},
    }
    digest = recipe_hash(recipe.to_json(), **environment)
    out_dir = Path(out_root).resolve() / recipe.id / digest[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = out_dir / "recipe.json"
    recipe_path.write_text(json.dumps(recipe.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outfit_path = None
    if outfit is not None:
        outfit_path = out_dir / "outfit.json"
        outfit_path.write_text(json.dumps(outfit.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "assets.json").write_text(json.dumps({"accessories": assets, "catalog_root": str(catalog.root), "catalog_version": catalog.version},
                                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return Staged(out_dir=out_dir, hash=digest, recipe_path=recipe_path, outfit_path=outfit_path, assets=assets)


# --- build -------------------------------------------------------------------------------------

@dataclass
class CharacterBuildResult:
    out_dir: Path
    build: dict
    cached: bool
    hash: str

    @property
    def ok(self) -> bool:
        return self.build.get("status") == "ok"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def batch_command(unity: str, staged: Staged, views, passes, formats, render: bool, project: Path = UNITY_PROJECT, probe: bool = False) -> list[str]:
    command = [unity, "-batchmode", "-projectPath", str(project), "-executeMethod", BATCH_METHOD,
               "-recipe", str(staged.recipe_path), "-out", str(staged.out_dir),
               "-views", ",".join(views), "-passes", ",".join(passes), "-formats", ",".join(formats),
               "-logFile", str(staged.out_dir / "unity.log")]  # no -quit: the builder calls EditorApplication.Exit after UMA finished
    if staged.outfit_path is not None:
        command[command.index("-out"):command.index("-out")] = ["-outfit", str(staged.outfit_path)]
    if not render:
        command.insert(1, "-nographics")
    if probe:
        command.append("-probe")
    return command


def build(recipe: CharacterRecipe, outfit: OutfitRecipe | None = None, catalog: Catalog | None = None,
          out_root: str | Path = "build/character", force: bool = False, views=None, passes=None, formats=None,
          render: bool = True, timeout: float = 1800.0, log=None, project: Path = UNITY_PROJECT, probe: bool = False) -> CharacterBuildResult:
    """Stage the recipe, run the Unity batch build and return its ``build.json`` (cached when the hash already built)."""
    catalog = catalog or Catalog()
    views = tuple(views or DEFAULT_VIEWS)
    passes = tuple(passes or DEFAULT_PASSES)
    formats = tuple(formats or DEFAULT_FORMATS)
    for fmt in formats:
        if fmt not in DEFAULT_FORMATS:
            raise ModelingError("character.formats", f"unknown export format {fmt!r}; use fbx and/or glb.")
    ready, reason = project_ready(project)
    if not ready:
        raise UnityNotFound(reason)
    unity = find_unity(project)
    staged = stage(recipe, outfit, catalog, out_root, force=force, log=log, project=project)
    build_path = staged.out_dir / "build.json"
    previous = _read_json(build_path)
    if previous and previous.get("status") == "ok" and not force:
        if all(Path(r["path"]).is_file() for r in previous.get("renders", []) if r.get("written")):
            return CharacterBuildResult(out_dir=staged.out_dir, build=previous, cached=True, hash=staged.hash)
    for stale in (build_path, staged.out_dir / "unity.log"):
        if stale.exists():
            stale.unlink()
    if (staged.out_dir / "renders").exists():
        shutil.rmtree(staged.out_dir / "renders")
    command = batch_command(unity, staged, views, passes, formats, render, project, probe=probe)
    if log:
        log("unity: " + " ".join(command))
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, encoding="utf-8", errors="replace",
                               cwd=str(project))  # never let the editor mistake the repository root for a project
    result = _read_json(build_path)
    if result is None or "status" not in result:
        result = {
            "status": "failed",
            "error": {"code": "unity.noReport", "message": f"Unity exited with {completed.returncode} without writing build.json. See unity.log."},
            "seconds": 0.0,
        }
        if completed.returncode == 198 or "No valid Unity Editor license" in (completed.stdout + completed.stderr):
            result["error"] = {"code": "unity.license", "message": "Unity has no active license. Sign in with Unity Hub and activate a license, then rebuild."}
    result["recipe_hash"] = staged.hash
    result["unity_exit_code"] = completed.returncode
    result["wall_seconds"] = round(time.perf_counter() - started, 3)
    if result.get("status") == "ok" and result.get("renders"):
        try:
            result["contact_sheet"] = make_contact_sheet(result, staged.out_dir / "contact_sheet.png")
        except Exception as exc:  # noqa: BLE001 - a broken PNG must not turn a finished build into a crash
            result["contact_sheet"] = None
            result.setdefault("warnings", []).append({"code": "contactSheet.failed", "message": f"{type(exc).__name__}: {exc}"})
    build_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CharacterBuildResult(out_dir=staged.out_dir, build=result, cached=False, hash=staged.hash)
