"""Small building blocks for character accessories (bags, straps, handles) authored under ``assets/props``.

Accessories are ordinary promodeler assets: real dimensions, constant PBR
materials (no bakes, so they build in seconds) and an ``extras`` block
``promodeler_socket`` that tells the character creator where the object is
held (``grip_offset_m`` is the grip point relative to the asset origin,
which sits at the bottom centre like every promodeler asset).
"""

from __future__ import annotations

import math

from .core import Bevel, Box, Material, Part, Profile, Sweep, Transform, curves, srgb


def hex_color(value: str):
    value = value.lstrip("#")
    return srgb(int(value[0:2], 16) / 255.0, int(value[2:4], 16) / 255.0, int(value[4:6], 16) / 255.0)


def leather(material_id: str = "leather", color: str = "#302C29") -> Material:
    return Material(material_id, base_color=hex_color(color), roughness=0.42)


def canvas(material_id: str = "canvas", color: str = "#D9D2C2") -> Material:
    return Material(material_id, base_color=hex_color(color), roughness=0.85)


def metal(material_id: str = "metal", color: str = "#A3A5A7") -> Material:
    return Material(material_id, base_color=hex_color(color), roughness=0.3, metallic=1.0)


def plastic(material_id: str = "plastic", color: str = "#1E1F22") -> Material:
    return Material(material_id, base_color=hex_color(color), roughness=0.35)


def rounded_box(part_id: str, size: tuple[float, float, float], material: str, bevel: float = 0.006,
                translation=(0.0, 0.0, 0.0), parent: str | None = None, smooth: float = math.radians(50)) -> Part:
    """A box standing on its bottom face at ``translation`` (bottom centre) with rounded edges."""
    bevel = min(bevel, min(size) / 3.0)
    return Part(id=part_id, shape=Box(size=size), material=material, parent=parent,
                transform=Transform(translation=(translation[0], translation[1] + size[1] / 2, translation[2])),
                modifiers=(Bevel(width=bevel, segments=3),), smooth_angle=smooth)


def strap(part_id: str, path, material: str, width: float = 0.02, thickness: float = 0.004, parent: str | None = None) -> Part:
    """A flat strap swept along a 3D polyline (rectangular profile, thin axis along the local up vector)."""
    profile = Profile(curves.rect(thickness, width))
    return Part(id=part_id, shape=Sweep(profile=profile, path=tuple(tuple(float(c) for c in p) for p in path), capped=True),
                material=material, parent=parent, smooth_angle=math.radians(60))


def cord(part_id: str, path, material: str, radius: float = 0.006, parent: str | None = None) -> Part:
    """A round handle or strap: a circle swept along a polyline."""
    profile = Profile(curves.circle(radius, 12))
    return Part(id=part_id, shape=Sweep(profile=profile, path=tuple(tuple(float(c) for c in p) for p in path), capped=True),
                material=material, parent=parent, smooth_angle=math.radians(70))


def arch(x_half: float, y_base: float, height: float, z: float = 0.0, segments: int = 10):
    """Points of a handle arch in the XY plane from (-x_half, y_base) over (0, y_base + height) to (+x_half, y_base)."""
    points = []
    for i in range(segments + 1):
        t = i / segments
        angle = math.pi * (1.0 - t)
        points.append((x_half * math.cos(angle), y_base + height * math.sin(angle), z))
    return points


def socket_extras(socket: str, grip_offset_m, orientation: str = "world_up", note: str | None = None) -> dict:
    """The ``promodeler_socket`` block: where the character creator holds the asset and how it should hang."""
    return {"promodeler_socket": {"socket": socket, "grip_offset_m": [round(float(c), 4) for c in grip_offset_m],
                                  "orientation": orientation, "note": note}}
