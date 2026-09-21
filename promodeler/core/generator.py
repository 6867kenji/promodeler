from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Callable

from .asset import Asset, GenerationInput, QualityProfile
from .diagnostics import ModelingError


@dataclass
class AssetGenerator:
    """A caller-owned parameter struct, an optional validator, a seed and a build function.

    ``build`` receives a ``GenerationInput`` and returns an ``Asset``. Randomness
    must derive from ``input.seed``; the generator never consults global state.
    """

    name: str
    parameters: Any
    build: Callable[[GenerationInput], Asset]
    seed: int = 0
    quality: QualityProfile = field(default_factory=QualityProfile)
    validate: Callable[[Any], None] | None = None
    version: int = 1

    def make_input(self, parameters: Any = None, seed: int | None = None, quality: QualityProfile | None = None) -> GenerationInput:
        return GenerationInput(
            parameters=self.parameters if parameters is None else parameters,
            seed=self.seed if seed is None else seed,
            quality=self.quality if quality is None else quality,
        )

    def generate(self, input: GenerationInput | None = None) -> Asset:
        if input is None:
            input = self.make_input()
        if not isinstance(input.seed, int):
            raise ModelingError("generator.seed", "seed must be an integer.")
        input.quality.validate()
        if self.validate is not None:
            self.validate(input.parameters)
        asset = self.build(input)
        if not isinstance(asset, Asset):
            raise ModelingError("generator.result", f"build must return an Asset, got {type(asset).__name__}.")
        asset.validate()
        return asset

    def parameters_recipe(self, parameters: Any) -> Any:
        """Serializable view of the parameters for the recipe and cache key."""
        if is_dataclass(parameters) and not isinstance(parameters, type):
            return {f.name: _plain(getattr(parameters, f.name)) for f in fields(parameters)}
        return _plain(parameters)


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ModelingError("generator.parameters", f"Parameter value of type {type(value).__name__} is not serializable.")
