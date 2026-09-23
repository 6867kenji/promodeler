"""``promodeler character prompt``: one sentence -> CharacterRecipe (docs/03 M13).

The prompt never writes the recipe directly. It is reduced to a small typed ``PromptSpec`` (sex, age, height,
build, style, hair, garments as catalog ids, accessories ...), either by the rule-based parser here or by an LLM
that is constrained to the spec's JSON Schema through tool use. ``sampler.sample_character`` then fills everything
the spec leaves open from the anthropometric priors with a seed derived from the text, so the result is
deterministic, validates like any other recipe, and every catalog id in it exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from ..core.diagnostics import ModelingError
from . import sampler, serialize
from .catalog import Catalog
from .recipe import HEX_COLOR, CharacterRecipe, RecipeWarning, Source

DEFAULT_MODEL = "claude-sonnet-5"
PROMPT_VERSION = 1
STYLES = ("business", "casual", "uniform", "sport")

# ---- vocabulary (Japanese first; the blueprints and the catalog match fragments are Japanese) ----------------------
SEX_WORDS = (("女性", "female"), ("女の子", "female"), ("女子", "female"), ("女", "female"), ("OL", "female"), ("主婦", "female"),
             ("男性", "male"), ("男の子", "male"), ("男子", "male"), ("男", "male"), ("サラリーマン", "male"), ("おじさん", "male"))
STYLE_WORDS = (("スーツ", "business"), ("ビジネス", "business"), ("会社員", "business"), ("サラリーマン", "business"), ("OL", "business"), ("営業", "business"),
               ("制服", "uniform"), ("店員", "uniform"), ("エプロン", "uniform"), ("カフェ", "uniform"), ("コンビニ", "uniform"), ("作業", "uniform"),
               ("スポーツ", "sport"), ("ランニング", "sport"), ("ジョギング", "sport"), ("運動", "sport"), ("ジム", "sport"), ("空手", "sport"),
               ("カジュアル", "casual"), ("私服", "casual"), ("休日", "casual"), ("学生", "casual"), ("通行人", "casual"))
BODY_WORDS = (("鍛えた", {"muscle": 0.72}), ("筋肉質", {"muscle": 0.75, "body_fat": 0.35}), ("引き締まった", {"muscle": 0.62, "body_fat": 0.3}),
              ("がっしり", {"muscle": 0.62, "body_fat": 0.6}), ("スレンダー", {"body_fat": 0.28}), ("細身", {"body_fat": 0.3}), ("痩せ", {"body_fat": 0.25}),
              ("華奢", {"body_fat": 0.3, "muscle": 0.3}), ("ぽっちゃり", {"body_fat": 0.72}), ("太め", {"body_fat": 0.72}), ("肥満", {"body_fat": 0.85}),
              ("中肉中背", {"body_fat": 0.45}), ("猫背", {"posture": 0.35}), ("姿勢が良い", {"posture": 0.65}), ("スポーティー", {"muscle": 0.6}))
HEIGHT_WORDS = (("小柄", -0.06), ("背が低い", -0.06), ("低身長", -0.06), ("高身長", 0.08), ("背が高い", 0.08), ("長身", 0.08))
FACE_WORDS = (("面長", {"face_length": 0.7}), ("丸顔", {"face_length": 0.38, "cheek_width": 0.6}), ("卵型", {"face_length": 0.55, "jaw_width": 0.45}),
              ("角張った", {"jaw_width": 0.68, "chin_size": 0.6}), ("小顔", {"face_length": 0.45, "cheek_width": 0.45}), ("大きな目", {"eye_size": 0.65}),
              ("つり目", {"eye_tilt": 0.65}), ("たれ目", {"eye_tilt": 0.35}), ("厚い唇", {"lip_thickness": 0.65}), ("薄い唇", {"lip_thickness": 0.38}),
              ("高い鼻", {"nose_bridge": 0.65}), ("低い鼻", {"nose_bridge": 0.38}), ("えら", {"jaw_width": 0.7}))
HAIR_COLOR_WORDS = (("黒髪", "#1E1A18"), ("黒い髪", "#1E1A18"), ("茶髪", "#4A3524"), ("明るい茶", "#6B4A2E"), ("栗色", "#4A3524"), ("白髪", "#8A8683"),
                    ("銀髪", "#A9A6A3"), ("金髪", "#C9A86A"), ("赤髪", "#7A3A2A"))
ACCESSORY_WORDS = (("黒縁眼鏡", "glasses"), ("眼鏡", "glasses"), ("メガネ", "glasses"), ("腕時計", "watch"), ("スポーツウォッチ", "sports-watch"),
                   ("時計", "watch"), ("名札", "badge"), ("スマホ", "phone"), ("スマートフォン", "phone"), ("ブリーフケース", "briefcase"), ("鞄", "briefcase"),
                   ("カバン", "briefcase"), ("リュック", "backpack"), ("バックパック", "backpack"), ("トート", "tote"), ("ショルダーバッグ", "shoulder-bag"),
                   ("メッセンジャー", "messenger"), ("エコバッグ", "eco-bag"))
BEARD_WORDS = ("ひげ", "髭", "無精ひげ")
CLEAN_SHAVEN_WORDS = ("ひげなし", "髭なし", "ひげのない")


@dataclass(frozen=True)
class PromptSpec:
    """What a prompt pins down. Everything null is drawn from the priors by the sampler."""

    sex: str | None = field(default=None, metadata={"enum": ("male", "female"), "description": "Biological sex of the character."})
    age: int | None = field(default=None, metadata={"minimum": 18, "maximum": 100, "description": "Age in years."})
    height_m: float | None = field(default=None, metadata={"minimum": 1.3, "maximum": 2.2, "description": "Barefoot height in metres."})
    body_fat: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 1.0, "description": "0 lean ... 1 obese (0.45 average)."})
    muscle: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 1.0, "description": "0 untrained ... 1 athlete (0.4-0.5 average)."})
    posture: float | None = field(default=None, metadata={"minimum": 0.0, "maximum": 1.0, "description": "0 slouched ... 1 upright (0.5 neutral)."})
    style: str | None = field(default=None, metadata={"enum": STYLES, "description": "Wardrobe style the outfit is drawn from."})
    hair_style: str | None = field(default=None, metadata={"description": "Catalog id of a hair style (category hair)."})
    hair_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    iris_color_srgb: str | None = field(default=None, metadata={"pattern": HEX_COLOR})
    skin_preset: str | None = field(default=None, metadata={"description": "Catalog id of a skin preset (category skin)."})
    facial_hair: bool | None = field(default=None, metadata={"description": "Men only: true for a beard/stubble, false for clean shaven."})
    face_shape: dict[str, float] = field(default_factory=dict, metadata={"description": "face.shape sliders 0...1 the prompt implies (face_length, jaw_width, cheek_width, eye_size, eye_tilt, lip_thickness, nose_bridge ...)."})
    garments: tuple[str, ...] = field(default=(), metadata={"description": "Catalog ids of garments the prompt names (category wardrobe or footwear)."})
    garment_colors: dict[str, str] = field(default_factory=dict, metadata={"description": "slot -> #RRGGBB for garments whose color the prompt gives."})
    accessories: tuple[str, ...] = field(default=(), metadata={"description": "Accessory ids: glasses, watch, sports-watch, badge, phone, briefcase, backpack, tote, shoulder-bag, messenger, eco-bag."})
    name: str | None = field(default=None, metadata={"description": "Display name for the character (short)."})
    descriptors: tuple[str, ...] = field(default=(), metadata={"description": "Traits worth keeping as text for humans and later prompts."})

    def to_json(self) -> dict:
        return serialize.encode(self)

    @classmethod
    def from_json(cls, data: dict) -> "PromptSpec":
        spec = serialize.decode(cls, data, "prompt_spec")
        serialize.check_metadata(spec, "prompt_spec")
        return spec

    def to_overrides(self) -> dict:
        out = {k: v for k, v in self.to_json().items() if v not in (None, (), [], {})}
        out["face_descriptors"] = tuple(self.descriptors)
        return out


def spec_schema() -> dict:
    return serialize.schema(PromptSpec, "promodeler-prompt-spec/1.0", "PromptSpec", "What a one-sentence character description pins down.")


# ---- rule-based parser -------------------------------------------------------------------------------------------

def _first(text: str, table):
    for word, value in table:
        if word in text:
            return value
    return None


def parse_prompt(text: str, catalog: Catalog) -> PromptSpec:
    """Japanese (and a little English) keyword parsing into a PromptSpec. Anything it cannot read stays null."""
    t = text.strip()
    lower = t.lower()
    sex = _first(t, SEX_WORDS)
    if sex is None:
        sex = "female" if re.search(r"\b(woman|female|girl)\b", lower) else "male" if re.search(r"\b(man|male|boy)\b", lower) else None

    age = None
    m = re.search(r"(\d{2})\s*歳", t)
    if m:
        age = int(m.group(1))
    else:
        m = re.search(r"(\d)0\s*代", t)
        if m:
            decade = int(m.group(1)) * 10
            age = decade + 5 if decade >= 20 else 20
        elif re.search(r"\b(\d{2})\s*(years? old|yo)\b", lower):
            age = int(re.search(r"\b(\d{2})\s*(years? old|yo)\b", lower).group(1))
    if age is not None:
        age = min(100, max(18, age))

    height = None
    m = re.search(r"(\d{3})\s*(cm|センチ)", t)
    if m:
        height = int(m.group(1)) / 100.0
    else:
        m = re.search(r"(\d\.\d{1,2})\s*m\b", lower)
        if m:
            height = float(m.group(1))
    height_shift = _first(t, HEIGHT_WORDS)

    shape: dict = {}
    for word, values in BODY_WORDS:
        if word in t:
            shape.update(values)
    face: dict = {}
    descriptors = []
    for word, values in FACE_WORDS:
        if word in t:
            face.update(values)
            descriptors.append(word)
    for word, _ in BODY_WORDS:
        if word in t:
            descriptors.append(word)

    style = _first(t, STYLE_WORDS)
    race = {"male": "human_male", "female": "human_female"}.get(sex)
    hair_entry = catalog.match_text(t, "hair", race=race)
    hair_color = _first(t, HAIR_COLOR_WORDS)
    # Garments: per slot, the entry whose longest fragment occurs in the text (「七分袖シャツ」 beats 「シャツ」 for inner).
    best_per_slot: dict[str, tuple[int, str]] = {}
    for entry in catalog.entries.values():
        if entry.category not in ("wardrobe", "footwear") or (race and race not in entry.compatibility.races):
            continue
        hit = max((len(f) for f in entry.match if f and f in t), default=0)
        if hit == 0:
            continue
        slot = entry.slots[0] if entry.slots else entry.category
        if slot not in best_per_slot or hit > best_per_slot[slot][0]:
            best_per_slot[slot] = (hit, entry.id)
    garments = [entry_id for _, entry_id in best_per_slot.values()]
    accessories = []
    for word, accessory in ACCESSORY_WORDS:
        if word in t and accessory not in accessories:
            accessories.append(accessory)
    facial_hair = None
    if any(w in t for w in CLEAN_SHAVEN_WORDS):
        facial_hair = False
    elif any(w in t for w in BEARD_WORDS):
        facial_hair = True

    if height is None and height_shift is not None and sex is not None:
        base = 1.71 if sex == "male" else 1.58
        height = round(base + height_shift, 3)
    return PromptSpec(
        sex=sex, age=age, height_m=height, body_fat=shape.get("body_fat"), muscle=shape.get("muscle"), posture=shape.get("posture"), style=style,
        hair_style=hair_entry.id if hair_entry else None, hair_color_srgb=hair_color, facial_hair=facial_hair, face_shape=face,
        garments=tuple(dict.fromkeys(garments)), accessories=tuple(accessories), descriptors=tuple(dict.fromkeys(descriptors)),
    )


# ---- LLM extraction (Anthropic API, schema-constrained through a forced tool call) ---------------------------------

def _anthropic_client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ModelingError("prompt.llm", "the anthropic package is not installed (pip install promodeler[critique]).") from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ModelingError("prompt.llm", "ANTHROPIC_API_KEY is not set; use the rule-based parser (default) or set the key.")
    return anthropic.Anthropic()


def llm_messages(text: str, catalog: Catalog) -> tuple[str, list[dict]]:
    """System prompt and messages: the spec's meaning plus the catalog ids the model may use."""
    hair = ", ".join(f"{e.id} ({'/'.join(e.match[:2])})" for e in catalog.find("hair"))
    wardrobe = ", ".join(f"{e.id} [{'/'.join(e.slots)}] ({'/'.join(e.match[:1])})" for e in list(catalog.find("wardrobe")) + list(catalog.find("footwear")))
    skins = ", ".join(e.id for e in catalog.find("skin"))
    system = (
        "You turn a short character description (usually Japanese) into a PromptSpec for a 3D character generator. "
        "Fill only what the text states or clearly implies; leave everything else null so the generator can draw it from "
        "Japanese adult anthropometric priors. Heights in metres. body_fat/muscle/posture are 0..1 with 0.45/0.45/0.5 average. "
        "Use only these catalog ids.\n"
        f"hair: {hair}\nwardrobe/footwear: {wardrobe}\nskin: {skins}\n"
        "accessories: glasses, watch, sports-watch, badge, phone, briefcase, backpack, tote, shoulder-bag, messenger, eco-bag."
    )
    return system, [{"role": "user", "content": text}]


def spec_from_llm(text: str, model: str = DEFAULT_MODEL, catalog: Catalog | None = None, client=None) -> PromptSpec:
    """Ask the model for a PromptSpec through a forced tool call whose input schema is the spec schema."""
    catalog = catalog or Catalog()
    client = client or _anthropic_client()
    system, messages = llm_messages(text, catalog)
    schema = spec_schema()
    schema.pop("$schema", None)
    schema.pop("$id", None)
    tool = {"name": "emit_prompt_spec", "description": "Return the PromptSpec for the description.", "input_schema": schema}
    response = client.messages.create(model=model, max_tokens=1024, system=system, messages=messages, tools=[tool],
                                      tool_choice={"type": "tool", "name": "emit_prompt_spec"})
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "emit_prompt_spec":
            data = dict(block.input)
            for key in ("garments", "accessories", "descriptors"):
                if isinstance(data.get(key), list):
                    data[key] = tuple(data[key])
            try:
                return PromptSpec.from_json(data)
            except ModelingError as exc:
                raise ModelingError("prompt.llm", f"the model's spec did not validate: {exc}") from exc
    raise ModelingError("prompt.llm", "the model returned no emit_prompt_spec tool call.")


# ---- recipe ----------------------------------------------------------------------------------------------------

def prompt_seed(text: str) -> int:
    return int(hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:8], 16)


def character_from_prompt(text: str, catalog: Catalog, spec: PromptSpec | None = None, seed: int | None = None,
                          recipe_id: str | None = None, presets: dict | None = None) -> tuple[CharacterRecipe, list[RecipeWarning]]:
    """The recipe for a prompt: its spec (parsed here unless given) applied over the seeded priors."""
    spec = spec or parse_prompt(text, catalog)
    seed = prompt_seed(text) if seed is None else seed
    presets = presets or sampler.load_presets()
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    overrides = spec.to_overrides()
    overrides["descriptors"] = (f"prompt:{text.strip()}",) + tuple(spec.descriptors)
    overrides["source"] = Source(kind="prompt", path=None, sha256=digest, generator_version=PROMPT_VERSION, catalog_version=catalog.version)
    overrides.setdefault("name", spec.name or text.strip()[:40])
    recipe, warnings = sampler.sample_character(seed, catalog, presets, recipe_id=recipe_id or f"prompt-{digest[:8]}", overrides=overrides)
    if spec.sex is None:
        warnings.append(RecipeWarning("prompt.sex", "the prompt does not say the sex; it was drawn from the seed."))
    if spec.style is None:
        warnings.append(RecipeWarning("prompt.style", "the prompt does not imply a wardrobe style; it was drawn from the seed."))
    return recipe, warnings
