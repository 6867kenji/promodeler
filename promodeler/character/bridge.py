"""Host side of the Unity character creator: locate the editor and the project.

The batch build itself (docs/03-character-recipe-pipeline.md, 9.3) arrives
with M10. Until then this module answers ``promodeler doctor`` and tells
``character build`` what is missing instead of pretending to build.
"""

from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UNITY_PROJECT = PROJECT_ROOT / "unity" / "ProModelerCharacterCreator"


class UnityNotFound(RuntimeError):
    pass


def project_version() -> str | None:
    """The Unity editor version pinned by the project, or None when the project does not exist yet."""
    path = UNITY_PROJECT / "ProjectSettings" / "ProjectVersion.txt"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    return None


def find_unity() -> str:
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
    wanted = project_version()
    for candidate in candidates:
        if wanted and f"\\{wanted}\\" in candidate:
            return candidate
    if candidates:
        return candidates[0]
    raise UnityNotFound("Unity was not found. Install it with Unity Hub or set PROMODELER_UNITY to Unity.exe.")


def uma_version() -> str | None:
    """UMA package version from the Unity project's manifest, when the project exists."""
    manifest = UNITY_PROJECT / "Packages" / "manifest.json"
    if not manifest.is_file():
        return None
    import json

    dependencies = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})
    for key, value in dependencies.items():
        if "uma" in key.lower():
            return str(value)
    return None
