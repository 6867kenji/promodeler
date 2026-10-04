"""Fit authored cloth by smooth limb sections, retaining its folds and UVs.

Blender helper. This is geometric fitting in the bind pose, not a cloth solver.
"""

import bpy
import numpy as np


def _world_vertices(obj):
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", values)
    matrix = np.asarray(obj.matrix_world, dtype=np.float64)
    return values.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]


def _edges(obj, materials):
    obj.data.calc_loop_triangles()
    points = _world_vertices(obj)
    triangles = np.asarray([tuple(t.vertices) for t in obj.data.loop_triangles
                            if t.material_index in materials], dtype=np.int32)
    if not len(triangles):
        raise ValueError(f"No fitting surface on {obj.name}")
    coordinates = points[triangles]
    return coordinates[:, (0, 1, 2), :].reshape(-1, 3), coordinates[:, (1, 2, 0), :].reshape(-1, 3)


def _cut(edges, axis, station):
    a, b = edges
    difference = b[:, axis] - a[:, axis]
    nonflat = np.abs(difference) > 1e-9
    t = np.zeros(len(a), dtype=np.float64)
    t[nonflat] = (station - a[nonflat, axis]) / difference[nonflat]
    valid = nonflat & (t >= 0) & (t <= 1)
    return a[valid] + t[valid, None] * (b[valid] - a[valid])


def _smoothstep(values, low, high):
    t = np.clip((values - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def _write_world(obj, world):
    matrix = np.asarray(obj.matrix_world.inverted(), dtype=np.float64)
    local = world @ matrix[:3, :3].T + matrix[:3, 3]
    obj.data.vertices.foreach_set("co", local.ravel())
    obj.data.update()


def fit_sleeve_sections(obj, body, sleeve_materials, main_materials):
    bpy.context.view_layer.update()
    source_edges = _edges(obj, main_materials)
    target_edges = _edges(body, {2})
    stations, profiles = [], []
    for x in np.arange(.21, .551, .025):
        source, target = _cut(source_edges, 0, x), _cut(target_edges, 0, x)
        if not len(source) or not len(target):
            continue
        lo, hi = source[:, 1:].min(axis=0), source[:, 1:].max(axis=0)
        target_lo, target_hi = target[:, 1:].min(axis=0), target[:, 1:].max(axis=0)
        source_center, target_center = (lo + hi) / 2, (target_lo + target_hi) / 2
        scale = np.maximum(1, (target_hi - target_lo + .024) / np.maximum(hi - lo, .005))
        stations.append(x)
        profiles.append(np.concatenate((source_center, target_center, scale)))
    if len(stations) < 3:
        raise ValueError(f"Insufficient sleeve sections on {obj.name}")
    profile = np.asarray(profiles)
    world = _world_vertices(obj)
    ids = np.asarray(sorted({i for p in obj.data.polygons if p.material_index in sleeve_materials
                             for i in p.vertices}), dtype=np.int32)
    distance = np.abs(world[ids, 0])
    values = np.array([np.interp(distance, stations, profile[:, column]) for column in range(6)]).T
    corrected = (world[ids, 1:] - values[:, :2]) * values[:, 4:] + values[:, 2:4]
    blend = _smoothstep(distance, .16, .25)
    world[ids, 1:] += (corrected - world[ids, 1:]) * blend[:, None]
    _write_world(obj, world)
    print("SECTION_FIT_SLEEVES", obj.name, len(ids), len(stations))


def fit_pant_sections(obj, body, pants_materials):
    bpy.context.view_layer.update()
    source_edges = _edges(obj, {0})
    target_edges = _edges(body, {1, 3})
    stations, profiles = [], []
    for z in np.arange(.12, 1.021, .04):
        source, target = _cut(source_edges, 2, z), _cut(target_edges, 2, z)
        if not len(source) or not len(target):
            continue
        source = source[source[:, 0] > 0]
        target = target[target[:, 0] > 0]
        if not len(source) or not len(target):
            continue
        lo, hi = source[:, :2].min(axis=0), source[:, :2].max(axis=0)
        target_lo, target_hi = target[:, :2].min(axis=0), target[:, :2].max(axis=0)
        source_center, target_center = (lo + hi) / 2, (target_lo + target_hi) / 2
        waist_blend = float(_smoothstep(np.asarray(z), .78, .90))
        source_center[0] *= 1 - waist_blend
        target_center[0] *= 1 - waist_blend
        source_half = (hi - lo) / 2
        target_half = (target_hi - target_lo) / 2
        source_half[0] = source_half[0] * (1 - waist_blend) + hi[0] * waist_blend
        target_half[0] = target_half[0] * (1 - waist_blend) + target_hi[0] * waist_blend
        scale = np.maximum(1, (target_half + .015) / np.maximum(source_half, .005))
        stations.append(z)
        profiles.append(np.concatenate((source_center, target_center, scale)))
    if len(stations) < 5:
        raise ValueError(f"Insufficient trouser sections on {obj.name}")
    world = _world_vertices(obj)
    ids = np.asarray(sorted({i for p in obj.data.polygons if p.material_index in pants_materials
                             for i in p.vertices}), dtype=np.int32)
    z = world[ids, 2]
    profile = np.asarray(profiles)
    values = np.array([np.interp(z, stations, profile[:, column]) for column in range(6)]).T
    coords = world[ids, :2].copy()
    signs = np.where(coords[:, 0] >= 0, 1, -1)
    coords[:, 0] = np.abs(coords[:, 0])
    corrected = (coords - values[:, :2]) * values[:, 4:] + values[:, 2:4]
    corrected[:, 0] *= signs
    blend = 1 - _smoothstep(z, 1.02, 1.12)
    world[ids, :2] += (corrected - world[ids, :2]) * blend[:, None]
    _write_world(obj, world)
    print("SECTION_FIT_PANTS", obj.name, len(ids), len(stations))
