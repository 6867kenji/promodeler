"""Reusable, metre-scaled warehouse inspired by the supplied WSE_11 reference.

The shell is generated from primitives; the source mesh and textures are never
copied into the generated model. Roof glazing occupies actual panel openings.
"""

from __future__ import annotations

import math
from dataclasses import replace

from promodeler.core import Array, Box, Cylinder, Extrude, Material, Part, Profile, Transform, srgb


WIDTH, DEPTH, HEIGHT = 25., 26.5, 8.55
EAVE, RIDGE = 6.15, 8.48
HALF_BODY_X, HALF_BODY_Z = 12., 12.75
BAYS = (-7.1, 0., 7.1)
SKYLIGHTS = (-9., -5.4, -1.8, 1.8, 5.4, 9.)


def materials():
    return (
        Material("wh_roof", base_color=srgb(.53, .56, .57), roughness=.52, metallic=.15),
        Material("wh_wall", base_color=srgb(.59, .61, .59), roughness=.56, metallic=.05),
        Material("wh_brick", base_color=srgb(.50, .265, .195), roughness=.82),
        Material("wh_shutter", base_color=srgb(.40, .46, .47), roughness=.43, metallic=.25),
        Material("wh_steel", base_color=srgb(.22, .27, .28), roughness=.38, metallic=.8),
        Material("wh_glass", base_color=srgb(.31, .48, .53, .35), roughness=.15, alpha_mode="blend"),
        Material("wh_floor", base_color=srgb(.49, .50, .47), roughness=.78),
        Material("wh_yellow", base_color=srgb(.87, .65, .14), roughness=.58),
        Material("wh_black", base_color=srgb(.08, .095, .10), roughness=.68),
        Material("wh_light", base_color=srgb(.92, .87, .68), roughness=.3,
                 emission_color=srgb(.9, .82, .58), emission_strength=1.5),
        Material("wh_wood", base_color=srgb(.55, .39, .22), roughness=.86),
        Material("wh_apron", base_color=srgb(.32, .34, .34), roughness=.90),
    )


def tile_specs():
    return {
        "wh_roof": {"pattern": "corrugated_metal", "scale_m": .96, "resolution": 1024,
                    "wave_axis": "v", "pitch_m": .24, "normal_strength": .55},
        "wh_wall": {"pattern": "corrugated_metal", "scale_m": .96, "resolution": 1024,
                    "wave_axis": "u", "pitch_m": .16, "normal_strength": .6},
        "wh_brick": {"pattern": "weathered_brick", "scale_m": .96, "resolution": 1024},
        "wh_shutter": {"pattern": "corrugated_metal", "scale_m": .96, "resolution": 1024,
                       "wave_axis": "v", "pitch_m": .08, "normal_strength": .35},
        "wh_steel": {"pattern": "brushed_metal", "scale_m": .4, "resolution": 256},
        "wh_floor": {"pattern": "concrete", "scale_m": .4, "resolution": 256},
        "wh_wood": {"pattern": "wood", "scale_m": .4, "resolution": 256},
        "wh_apron": {"pattern": "asphalt", "scale_m": .4, "resolution": 256,
                     "normal_strength": .08},
    }


def warehouse_parts(prefix="warehouse", *, origin=(0., 0., 0.), yaw=0.):
    parts = []

    def b(name, bounds, material, repeat=None):
        x0, x1, y0, y1, z0, z1 = bounds
        parts.append(Part(id=prefix + "_" + name, shape=Box(size=(x1-x0, y1-y0, z1-z0)),
                          material=material, transform=Transform(translation=((x0+x1)/2, (y0+y1)/2, (z0+z1)/2)),
                          modifiers=(Array(count=repeat[0], offset=repeat[1]),) if repeat else ()))

    def member(name, start, end, thickness=.10):
        # Structural beams in a cross-section at fixed Z.
        dx, dy = end[0]-start[0], end[1]-start[1]
        parts.append(Part(id=prefix + "_" + name, shape=Box(size=(math.hypot(dx, dy), thickness, thickness)),
                          material="wh_steel", transform=Transform(
                              translation=tuple((a+b)/2 for a, b in zip(start, end)),
                              rotation=(0., 0., math.atan2(dy, dx)))))

    b("foundation", (-12, 12, 0, .10, -12.75, 12.75), "wh_floor")
    # The front wall is segmented around three real 4.6 x 4.6 m openings
    # and a personnel doorway. There is no hidden wall across the open bay.
    openings = [(c-2.3, c+2.3, 4.7) for c in BAYS] + [(10., 11.1, 2.3)]
    cursor = -12.
    for index, (a, c, top) in enumerate(openings):
        if a > cursor:
            b(f"front_brick_{index}", (cursor, a, .10, 1.75, 12.55, 12.75), "wh_brick")
            b(f"front_wall_{index}", (cursor, a, 1.75, EAVE, 12.55, 12.75), "wh_wall")
        b(f"front_header_{index}", (a, c, top, EAVE, 12.55, 12.75), "wh_wall")
        cursor = c
    b("front_brick_end", (cursor, 12, .10, 1.75, 12.55, 12.75), "wh_brick")
    b("front_wall_end", (cursor, 12, 1.75, EAVE, 12.55, 12.75), "wh_wall")
    b("rear_brick", (-12, 12, .10, 1.75, -12.75, -12.55), "wh_brick")
    b("rear_wall", (-12, 12, 1.75, EAVE, -12.75, -12.55), "wh_wall")
    for side in (-1, 1):
        x0, x1 = (-12, -11.8) if side < 0 else (11.8, 12)
        # Side windows have physical openings, glazing and mullions.
        b(f"side_{side}_base", (x0, x1, .10, .72, -12.55, 12.55), "wh_brick")
        b(f"side_{side}_brick_header", (x0, x1, 1.52, 1.75, -12.55, 12.55), "wh_brick")
        b(f"side_{side}_wall", (x0, x1, 1.75, EAVE, -12.55, 12.55), "wh_wall")
        last = -12.55
        for index, z in enumerate((-9., -3., 3., 9.)):
            b(f"side_{side}_pier_{index}", (x0, x1, .72, 1.52, last, z-1.15), "wh_brick")
            b(f"side_{side}_glass_{index}", (side*11.94-.012, side*11.94+.012, .75, 1.49, z-1.15, z+1.15), "wh_glass")
            for edge, h in (("bottom", .72), ("top", 1.48)):
                b(f"side_{side}_{edge}_{index}", (x0-.035, x1+.035, h, h+.04, z-1.2, z+1.2), "wh_steel")
            for j, zz in enumerate((z-1.15, z, z+1.15)):
                b(f"side_{side}_mullion_{index}_{j}", (x0-.025, x1+.025, .72, 1.52, zz-.022, zz+.022), "wh_steel")
            last = z+1.15
        b(f"side_{side}_pier_end", (x0, x1, .72, 1.52, last, 12.55), "wh_brick")
    for tag, z in (("front", 12.55), ("rear", -12.75)):
        parts.append(Part(id=prefix + f"_{tag}_gable",
                          shape=Extrude(Profile(((-12, EAVE), (12, EAVE), (0, RIDGE))), depth=.20, axis="z"),
                          material="wh_wall", transform=Transform(translation=(0, 0, z))))

    slope = (RIDGE-EAVE)/12.5
    angle = math.atan(slope)
    def roof_piece(name, x0, x1, z0, z1, side, material="wh_roof", thick=.065, lift=0.):
        # x coordinates are positive distances from the ridge on each slope.
        mid = (x0+x1)/2
        parts.append(Part(id=prefix + "_" + name,
                          shape=Box(size=((x1-x0)/math.cos(angle), thick, z1-z0)), material=material,
                          transform=Transform(translation=(side*mid, RIDGE-slope*mid+lift, (z0+z1)/2),
                                              rotation=(0, 0, -side*angle))))

    for side in (-1, 1):
        last = -13.25
        for i, z in enumerate(SKYLIGHTS):
            roof_piece(f"roof_{side}_panel_{i}", 0, 12.5, last, z-.36, side)
            for name, a, c in (("ridge", 0, 2.0), ("eave", 10.8, 12.5)):
                roof_piece(f"roof_{side}_{name}_{i}", a, c, z-.36, z+.36, side)
            roof_piece(f"skylight_{side}_{i}", 2., 10.8, z-.33, z+.33, side, "wh_glass", .025, .005)
            for edge, zz in (("n", z-.36), ("s", z+.36)):
                roof_piece(f"skylight_frame_{side}_{i}_{edge}", 1.96, 10.84, zz-.025, zz+.025, side, "wh_steel", .075, .035)
            for j, xx in enumerate((2., 4.2, 6.4, 8.6, 10.8)):
                roof_piece(f"skylight_bar_{side}_{i}_{j}", xx-.025, xx+.025, z-.36, z+.36, side, "wh_steel", .075, .035)
            last = z+.36
        roof_piece(f"roof_{side}_panel_end", 0, 12.5, last, 13.25, side)
        # Raised seams add silhouette detail and stop at the glazed openings.
        for j in range(110):
            z = -13.08+j*.24
            if any(abs(z-c) < .40 for c in SKYLIGHTS):
                continue
            roof_piece(f"roof_{side}_rib_{j}", .06, 12.46, z-.012, z+.012, side, thick=.018, lift=.049)
        b(f"gutter_{side}", (side*12.35-.075, side*12.35+.075, EAVE-.10, EAVE+.04, -13.22, 13.22), "wh_steel")
    b("ridge_cap", (-.10, .10, RIDGE+.025, HEIGHT, -13.25, 13.25), "wh_shutter")
    for side in (-1, 1):
        for z in (-12.3, 12.3):
            parts.append(Part(id=prefix + f"_downpipe_{side}_{z}",
                              shape=Cylinder(radius=.055, height=EAVE-.1, segments=12), material="wh_steel",
                              transform=Transform(translation=(side*12.18, EAVE/2+.05, z))))

    for i, x in enumerate(BAYS):
        for j, xx in enumerate((x-2.37, x+2.37)):
            b(f"bay_{i}_jamb_{j}", (xx-.075, xx+.075, .1, 4.8, 12.73, 12.91), "wh_steel")
        b(f"bay_{i}_hood", (x-2.5, x+2.5, 4.72, 5.12, 12.68, 13.04), "wh_shutter")
        if i != 1:
            b(f"bay_{i}_shutter_low", (x-2.27, x+2.27, .12, .88, 12.66, 12.72), "wh_shutter")
            b(f"bay_{i}_shutter_high", (x-2.27, x+2.27, 1.18, 4.70, 12.66, 12.72), "wh_shutter")
            for j in range(5):
                xx = x-2.27+j*.91
                b(f"bay_{i}_vision_{j}", (xx+.08, xx+.78, .9, 1.16, 12.675, 12.697), "wh_glass")
                b(f"bay_{i}_vision_pier_{j}", (xx, xx+.08, .88, 1.18, 12.66, 12.72), "wh_shutter")
                b(f"bay_{i}_vision_end_{j}", (xx+.78, min(xx+.91, x+2.27), .88, 1.18, 12.66, 12.72), "wh_shutter")
        for j, xx in enumerate((x-2.57, x+2.57)):
            parts.append(Part(id=prefix + f"_bay_{i}_bollard_{j}", shape=Cylinder(radius=.08, height=1.05, segments=16),
                              material="wh_yellow", transform=Transform(translation=(xx, .625, 13.04))))
            for k in (0, 1, 2):
                parts.append(Part(id=prefix + f"_bay_{i}_bollard_{j}_stripe_{k}", shape=Cylinder(radius=.081, height=.10, segments=16),
                                  material="wh_black", transform=Transform(translation=(xx, .35+k*.27, 13.04))))
        b(f"bay_{i}_lamp", (x-.25, x+.25, 5.32, 5.46, 12.76, 12.96), "wh_steel")
        b(f"bay_{i}_lamp_lens", (x-.20, x+.20, 5.33, 5.42, 12.965, 12.975), "wh_light")
    b("personnel_door", (10.03, 11.07, .1, 2.28, 12.66, 12.72), "wh_shutter")
    b("personnel_handle", (10.88, 10.91, 1.0, 1.13, 12.73, 12.79), "wh_steel")
    b("personnel_transom", (9.93, 11.17, 2.30, 2.40, 12.73, 12.83), "wh_steel")
    # Minimal functional interior, visible through the open centre loading bay.
    for j, z in enumerate((-10, -5, 0, 5, 10)):
        for side in (-1, 1):
            b(f"column_{j}_{side}", (side*11.5-.12, side*11.5+.12, .1, EAVE, z-.12, z+.12), "wh_steel")
            member(f"truss_top_{j}_{side}", (0, RIDGE-.22, z), (side*11.5, EAVE-.14, z), .14)
            member(f"truss_web_{j}_{side}", (side*5.6, EAVE-.2, z), (0, RIDGE-.22, z), .07)
        b(f"truss_tie_{j}", (-11.5, 11.5, EAVE-.28, EAVE-.14, z-.06, z+.06), "wh_steel")
    for index, z in enumerate((-7., -3.)):
        b(f"pallet_{index}", (-8.8, -6.4, .1, .25, z-.65, z+.65), "wh_wood")
        b(f"crate_{index}", (-8.65, -6.55, .25, 1.55, z-.58, z+.58), "wh_wood")
    # Apply yaw only after all local slope rotations have been authored.
    if abs(math.sin(yaw)) > 1e-8:
        raise ValueError("Warehouse placement currently supports north/south frontages (0 or pi yaw).")
    ox, oy, oz = origin
    for i, p in enumerate(parts):
        x, y, z = p.transform.translation
        parts[i] = replace(p, transform=replace(p.transform,
            translation=(ox+x*math.cos(yaw)+z*math.sin(yaw), oy+y, oz-x*math.sin(yaw)+z*math.cos(yaw)),
            rotation=(p.transform.rotation[0], yaw, p.transform.rotation[2]*math.cos(yaw))))
    return parts
