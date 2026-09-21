from __future__ import annotations


class ModelingError(ValueError):
    """A structured authoring or compilation failure.

    ``code`` is a stable dotted identifier such as ``part.duplicateID`` so
    tools and agents can match on it; ``message`` is for humans.
    Operations raise instead of silently degrading their output.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ModelingError(code, message)


def is_finite(value: float) -> bool:
    return isinstance(value, (int, float)) and value == value and value not in (float("inf"), float("-inf"))


def finite_vector(values, count: int, code: str, label: str) -> tuple[float, ...]:
    values = tuple(float(v) for v in values)
    require(len(values) == count, code, f"{label} needs {count} components, got {len(values)}.")
    require(all(is_finite(v) for v in values), code, f"{label} must be finite.")
    return values
