"""Asset catalog: the IDs a recipe may reference, with slot/race compatibility and license policy.

``character/catalog/<category>.json`` files are shared verbatim with the
Unity project. Python validates references and licenses; Unity resolves
``runtime.addressable`` to content. Entries with ``runtime.status ==
"placeholder"`` have no content yet and every reference to them is
reported, so a recipe never looks more finished than the catalog is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core.diagnostics import ModelingError
from . import serialize
from .recipe import HEX_COLOR, ID_PATTERN, RACES, SLOTS, RecipeWarning, canonical_dump

CATEGORIES = ("skin", "hair", "eyebrows", "facial_hair", "eyes", "teeth", "wardrobe", "footwear", "accessories")
STATUSES = ("placeholder", "ready", "deprecated")
DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent / "character" / "catalog"


@dataclass(frozen=True)
class Compatibility:
    races: tuple[str, ...] = field(default=RACES, metadata={"description": "Base races this asset fits."})
    layers_over: tuple[str, ...] = field(default=(), metadata={"description": "Slots this garment may be worn over."})
    hides: tuple[str, ...] = field(default=(), metadata={"description": "Body regions hidden under the garment."})


@dataclass(frozen=True)
class Runtime:
    status: str = field(default="placeholder", metadata={"enum": STATUSES})
    uma_wardrobe_recipe: str | None = field(default=None, metadata={"description": "UMA wardrobe recipe asset name (race neutral)."})
    uma_wardrobe_recipe_by_race: dict[str, str] = field(default_factory=dict, metadata={"description": "Race -> UMA wardrobe recipe asset name; wins over uma_wardrobe_recipe."})
    addressable: str | None = None


@dataclass(frozen=True)
class License:
    type: str = field(default="own", metadata={"description": "SPDX-like identifier: CC0-1.0, CC-BY-4.0, MIT, Apache-2.0, own, purchased, unknown."})
    source: str | None = None
    attribution: str | None = None
    redistribution: bool = True


@dataclass(frozen=True)
class CatalogEntry:
    id: str = field(metadata={"pattern": ID_PATTERN})
    category: str = field(metadata={"enum": CATEGORIES})
    name: str = ""
    slots: tuple[str, ...] = field(default=(), metadata={"description": "Wardrobe slots this entry can fill (wardrobe/footwear only)."})
    match: tuple[str, ...] = field(default=(), metadata={"description": "Blueprint text fragments that select this entry; higher priority, then the longest fragment wins."})
    priority: int = field(default=0, metadata={"description": "Tie-break for match_text: specific styles (a side part) beat generic ones (short hair)."})
    compatibility: Compatibility = field(default_factory=Compatibility)
    runtime: Runtime = field(default_factory=Runtime)
    base_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR, "description": "Nominal color of presets (skin, teeth, eyes) used for nearest-color selection."})
    materials: dict = field(default_factory=dict)
    neutral_measurements_m: dict[str, float] = field(default_factory=dict)
    triangles: int | None = field(default=None, metadata={"minimum": 0})
    license: License = field(default_factory=License)
    provenance: dict = field(default_factory=dict)
    version: str = "0"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogFile:
    """One ``character/catalog/<category>.json`` document."""

    category: str = field(metadata={"enum": CATEGORIES})
    version: str = "0"
    entries: tuple[CatalogEntry, ...] = ()


@dataclass(frozen=True)
class LicensePolicy:
    allowed: tuple[str, ...] = ("CC0-1.0", "MIT", "Apache-2.0", "own")
    attribution_required: tuple[str, ...] = ("CC-BY-4.0", "CC-BY-3.0")
    forbidden_fragments: tuple[str, ...] = ("NC", "ND", "unknown")
    note: str | None = None


class Catalog:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_ROOT
        self.entries: dict[str, CatalogEntry] = {}
        self.files: dict[str, CatalogFile] = {}
        self.policy = LicensePolicy()
        if not self.root.is_dir():
            raise ModelingError("catalog.root", f"Catalog directory not found: {self.root}")
        digest = hashlib.sha256()
        for path in sorted(self.root.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            digest.update(canonical_dump(data).encode("ascii"))
            if path.stem == "policy":
                self.policy = serialize.decode(LicensePolicy, data, "policy")
                continue
            document = serialize.decode(CatalogFile, data, path.name)
            serialize.check_metadata(document, path.name)
            if document.category != path.stem:
                raise ModelingError("catalog.category", f"{path.name} declares category {document.category!r}; the file name must match.")
            self.files[document.category] = document
            for entry in document.entries:
                if entry.id in self.entries:
                    raise ModelingError("catalog.duplicateID", f"Catalog id {entry.id!r} is defined twice.")
                if entry.category != document.category:
                    raise ModelingError("catalog.category", f"{entry.id}: category {entry.category!r} inside {path.name}.")
                if entry.category in ("wardrobe", "footwear") and not entry.slots:
                    raise ModelingError("catalog.slots", f"{entry.id}: wardrobe and footwear entries need slots.")
                for slot in entry.slots:
                    if slot not in SLOTS:
                        raise ModelingError("catalog.slots", f"{entry.id}: unknown slot {slot!r}.")
                self.entries[entry.id] = entry
        self.version = digest.hexdigest()[:12]

    # -- lookup --
    def get(self, catalog_id: str) -> CatalogEntry:
        try:
            return self.entries[catalog_id]
        except KeyError:
            raise ModelingError("catalog.unknown", f"Unknown catalog id {catalog_id!r}.") from None

    def find(self, category: str | None = None, slot: str | None = None, race: str | None = None,
             tags: set[str] | None = None) -> list[CatalogEntry]:
        out = []
        for entry in self.entries.values():
            if category and entry.category != category:
                continue
            if slot and slot not in entry.slots:
                continue
            if race and race not in entry.compatibility.races:
                continue
            if tags and not tags <= set(entry.tags):
                continue
            out.append(entry)
        return out

    def match_text(self, text: str, category: str | tuple[str, ...], slot: str | None = None, race: str | None = None) -> CatalogEntry | None:
        """The entry with the highest ``priority`` whose ``match`` fragment occurs in ``text``; longer fragments win ties, then file order."""
        categories = (category,) if isinstance(category, str) else tuple(category)
        best: tuple[tuple, CatalogEntry] | None = None
        for index, entry in enumerate(self.entries.values()):
            if entry.category not in categories:
                continue
            if slot and slot not in entry.slots:
                continue
            if race and race not in entry.compatibility.races:
                continue
            for fragment in entry.match:
                if fragment and fragment in text:
                    key = (entry.priority, len(fragment), -index)
                    if best is None or key > best[0]:
                        best = (key, entry)
        return best[1] if best else None

    def nearest_color(self, category: str, color_hex: str) -> CatalogEntry | None:
        """The preset of ``category`` whose nominal color is closest (sRGB Euclidean) to ``color_hex``."""
        target = _hex_to_rgb(color_hex)
        best = None
        for entry in self.find(category):
            if entry.base_color_srgb is None:
                continue
            rgb = _hex_to_rgb(entry.base_color_srgb)
            distance = sum((a - b) ** 2 for a, b in zip(rgb, target))
            if best is None or distance < best[0]:
                best = (distance, entry)
        return best[1] if best else None

    # -- checks --
    def check(self, entry: CatalogEntry, slot: str | None = None, race: str | None = None, label: str = "") -> list[RecipeWarning]:
        """License is a hard failure when forbidden; compatibility and placeholder status are warnings."""
        prefix = f"{label}: " if label else ""
        warnings: list[RecipeWarning] = []
        license_type = entry.license.type
        if any(fragment in license_type for fragment in self.policy.forbidden_fragments):
            raise ModelingError("catalog.license", f"{prefix}{entry.id} has a forbidden license {license_type!r}.")
        if license_type in self.policy.attribution_required and not entry.license.attribution:
            raise ModelingError("catalog.license", f"{prefix}{entry.id} needs an attribution string for {license_type}.")
        if license_type not in self.policy.allowed and license_type not in self.policy.attribution_required:
            warnings.append(RecipeWarning("catalog.licenseReview", f"{prefix}{entry.id} license {license_type!r} is not in the allowed list; review before shipping."))
        if not entry.license.redistribution:
            warnings.append(RecipeWarning("catalog.noRedistribution", f"{prefix}{entry.id} cannot be redistributed; keep it out of Git and shared builds."))
        if slot and slot not in entry.slots:
            raise ModelingError("catalog.slot", f"{prefix}{entry.id} does not fit slot {slot!r} (fits {list(entry.slots)}).")
        if race and race not in entry.compatibility.races:
            warnings.append(RecipeWarning("catalog.race", f"{prefix}{entry.id} is not made for {race} (races {list(entry.compatibility.races)})."))
        if entry.runtime.status == "placeholder":
            warnings.append(RecipeWarning("catalog.placeholder", f"{prefix}{entry.id} is a placeholder without content; the build will show the UMA default."))
        elif entry.runtime.status == "deprecated":
            warnings.append(RecipeWarning("catalog.deprecated", f"{prefix}{entry.id} is deprecated."))
        return warnings


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
