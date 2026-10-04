"""Small, physically scaled PBR maps shared by large architectural meshes."""

from __future__ import annotations

import math
import os
import struct
import zlib

import bpy

from . import materials


def project(obj: bpy.types.Object, scale_m: float, mapping: str = "world") -> None:
    """Box-project shared masonry in world metres or a decal within its own bounds."""
    mesh = obj.data
    layer = mesh.uv_layers.active or mesh.uv_layers.new(name="TiledUV")
    if mapping not in {"world", "local"}:
        raise ValueError(f"Unsupported tiled mapping: {mapping}")
    if mapping == "local":
        lo = [min(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)]
        hi = [max(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)]
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    for polygon in mesh.polygons:
        normal = normal_matrix @ polygon.normal if mapping == "world" else polygon.normal
        dominant = max(range(3), key=lambda axis: abs(normal[axis]))
        axes = ((1, 2), (0, 2), (0, 1))[dominant]
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if mapping == "local":
                layer.data[loop_index].uv = tuple(
                    (vertex[axis] - lo[axis]) / max(hi[axis] - lo[axis], 1e-8)
                    for axis in axes)
            else:
                world = obj.matrix_world @ vertex
                layer.data[loop_index].uv = (world[axes[0]] / scale_m,
                                             world[axes[1]] / scale_m)


def _png(path: str, width: int, height: int, data: bytes) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))
    rows = b"".join(b"\x00" + data[y * width * 4:(y + 1) * width * 4]
                    for y in range(height))
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as stream:
        stream.write(payload)


def _clamp(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def _periodic_noise(u, v, columns: int, rows: int, seed: int):
    """Smooth, deterministic weathering without a visible edge at UV repeat."""
    import numpy as np

    values = np.random.default_rng(seed).random((rows, columns), dtype=np.float32)
    x, y = u * columns, v * rows
    ix, iy = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = values[iy % rows, ix % columns]
    b = values[iy % rows, (ix + 1) % columns]
    c = values[(iy + 1) % rows, ix % columns]
    d = values[(iy + 1) % rows, (ix + 1) % columns]
    return ((a * (1 - fx) + b * fx) * (1 - fy) +
            (c * (1 - fx) + d * fx) * fy)


def _architectural_maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    """Periodic height-derived joints, with separate wear and roughness maps."""
    import numpy as np

    n = tile.get("resolution", 512)
    scale = tile["scale_m"]
    kind = tile["pattern"]
    v, u = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = (u + .5) / n, (v + .5) / n
    seed = sum((index + 1) * ord(char) for index, char in enumerate(spec["id"]))
    if "columns" in tile:
        grain = (np.sin(2 * math.pi * 61 * u) * np.sin(2 * math.pi * 73 * v) * .5 +
                 np.sin(2 * math.pi * 127 * u) * np.sin(2 * math.pi * 89 * v) * .25)
    else:
        grain = (np.sin(2 * math.pi * (61 * u + 37 * v)) * .5 +
                 np.sin(2 * math.pi * (127 * u - 83 * v)) * .25)
    # The colour of each unit stays within the blueprint's small tolerance.
    # Sparse runoff and mortar deposits are separate from that pigment variation.
    broad = _periodic_noise(u, v, 3, 3, seed + 11)
    patches = _periodic_noise(u, v, 9, 7, seed + 23)
    runoff = _periodic_noise(u, v, 24, 3, seed + 37)
    grain_noise = _periodic_noise(u, v, 83, 79, seed + 53) - .5
    # The map repeats every few metres. Keep only fine pigment variation in
    # masonry; broad weathering is placed once in world space as sparse decals.
    if kind in {"weathered_brick", "facade_tile", "weathered_paving", "station_wall"}:
        dirt = np.clip((patches - .64) * .10 + grain_noise * .025, 0, .035)
    else:
        dirt = np.clip((broad - .56) * .8 + (patches - .62) * .5 +
                       (runoff - .68) * .35, 0, .28)
    groove = np.zeros_like(u)
    tone = np.zeros_like(u)
    if kind != "roof_membrane":
        columns = tile.get("columns", 4)
        rows = tile.get("rows", 8 if kind in {"weathered_brick", "facade_tile", "station_wall"} else 4)
        row = np.floor(v * rows).astype(int)
        offset = .5 * (row % 2) if kind == "weathered_brick" else 0
        cell_u = u * columns + offset
        column = np.floor(cell_u).astype(int) % columns
        cu, cv = cell_u % 1, (v * rows) % 1
        gap = {"weathered_brick": .010, "facade_tile": .005, "weathered_paving": .004, "station_wall": .003}[kind]
        edge = np.minimum(np.minimum(cu, 1 - cu) * scale / columns,
                          np.minimum(cv, 1 - cv) * scale / rows)
        bevel = .0015
        groove = 1 - np.clip((edge - gap / 2) / bevel, 0, 1)
        if "columns" in tile:
            cell_hash = ((column * 73856093) ^ (row * 19349663) ^ seed) & 255
            tone = (cell_hash / 255 - .5) * (.12 if kind == "weathered_brick" else .06)
        else:
            tone = (((column * 37 + row * 53) % 13) - 6) * (.014 if kind == "weathered_brick" else .004)
    shade = 1 + tone + grain * .012 + grain_noise * .026 - dirt * .35
    if kind == "roof_membrane":
        seams = np.minimum(u, 1 - u)
        groove = 1 - np.clip((seams - .009) / .006, 0, 1)
        shade -= dirt * .2
    # Mortar is coloured independently; this is surface pigment, not baked AO.
    color = np.empty((n, n, 4), dtype=np.uint8)
    for channel, value in enumerate(spec["base_color"]["value"][:3]):
        mortar = value * (.74 + .05 * patches) if kind == "weathered_brick" else value * (.66 + .07 * patches)
        pigment = value * shade * (1 - groove) + mortar * groove
        color[:, :, channel] = np.clip(np.rint(pigment * 255), 0, 255).astype(np.uint8)
    color[:, :, 3] = 255
    rough = np.clip(spec["roughness"]["value"] + dirt * .32 + groove * .10 +
                    (patches - .5) * .065 + grain_noise * .035, 0, 1)
    roughness = np.full((n, n, 4), 255, dtype=np.uint8)
    roughness[:, :, :3] = np.rint(rough * 255).astype(np.uint8)[:, :, None]
    depth = .001 if kind == "roof_membrane" else .002
    height = -groove * depth + grain_noise * .00008 + grain * .000025
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2 * scale / n)
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / (2 * scale / n)
    tangent = np.stack((-dx, dy, np.ones_like(dx)), axis=-1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    normal = np.full((n, n, 4), 255, dtype=np.uint8)
    normal[:, :, :3] = np.rint((tangent * .5 + .5) * 255).astype(np.uint8)
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    for channel, pixels in (("base_color", color), ("roughness", roughness), ("normal", normal)):
        _png(paths[channel], n, n, pixels.tobytes())
    return paths


def _runoff_decal_maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    """Soft transparent rain trails for the wall immediately below a drip edge."""
    import numpy as np

    n = tile.get("resolution", 512)
    v, u = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = (u + .5) / n, (v + .5) / n
    seed = sum((i + 1) * ord(ch) for i, ch in enumerate(spec["id"]))
    rng = np.random.default_rng(seed)
    alpha = np.zeros((n, n), dtype=np.float32)
    for _ in range(5):
        centre = rng.uniform(.18, .82)
        width = rng.uniform(.014, .047)
        length = rng.uniform(.38, .90)
        trail = np.exp(-((u - centre) / width) ** 2)
        trail *= np.clip((v - (1 - length)) / .20, 0, 1)
        alpha += trail * rng.uniform(.045, .095)
    alpha += np.exp(-((u - .5) / .31) ** 4) * np.clip((v - .72) / .28, 0, 1) * .10
    alpha *= np.clip(np.minimum(u, 1 - u) / .08, 0, 1)
    alpha *= np.clip(v / .12, 0, 1)
    alpha = np.clip(alpha, 0, .28)
    color = np.empty((n, n, 4), dtype=np.uint8)
    for channel, value in enumerate(spec["base_color"]["value"][:3]):
        color[:, :, channel] = round(value * 255)
    color[:, :, 3] = np.rint(alpha * 255).astype(np.uint8)
    roughness = np.full((n, n, 4), 255, dtype=np.uint8)
    roughness[:, :, :3] = round(spec["roughness"]["value"] * 255)
    normal = np.full((n, n, 4), (128, 128, 255, 255), dtype=np.uint8)
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    for channel, pixels in (("base_color", color), ("roughness", roughness), ("normal", normal)):
        _png(paths[channel], n, n, pixels.tobytes())
    return paths


def _weather_patch_maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    """Soft, irregular local decal; placement, size and rotation are world seeded."""
    import numpy as np

    n = tile.get("resolution", 256)
    v, u = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = (u + .5) / n, (v + .5) / n
    seed = zlib.crc32(spec["id"].encode("utf-8"))
    low = _periodic_noise(u, v, 7, 9, seed + 17)
    high = _periodic_noise(u, v, 19, 17, seed + 31)
    radius = ((u - .5) / .49) ** 2 + ((v - .5) / .47) ** 2
    feather = np.clip((1 - radius) * 2, 0, 1) ** 2
    mottle = np.clip((low - .28) * 1.7 + (high - .5) * .38, 0, 1)
    alpha = np.clip(feather * mottle * tile.get("opacity", .18), 0, .38)
    color = np.empty((n, n, 4), dtype=np.uint8)
    for channel, value in enumerate(spec["base_color"]["value"][:3]):
        color[:, :, channel] = round(value * 255)
    color[:, :, 3] = np.rint(alpha * 255).astype(np.uint8)
    roughness = np.full((n, n, 4), 255, dtype=np.uint8)
    roughness[:, :, :3] = round(spec["roughness"]["value"] * 255)
    normal = np.full((n, n, 4), (128, 128, 255, 255), dtype=np.uint8)
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    for channel, pixels in (("base_color", color), ("roughness", roughness), ("normal", normal)):
        _png(paths[channel], n, n, pixels.tobytes())
    return paths


def _subway_floor_normal(tile: dict) -> bytes:
    """Normal map from the same 300 mm grout grid used by the color map."""
    import numpy as np

    n = tile.get("resolution", 256)
    scale = tile["scale_m"]
    v, u = np.mgrid[0:n, 0:n].astype(np.float64)
    u, v = (u + .5) / n, (v + .5) / n
    cell_u, cell_v = (u * 4) % 1, (v * 4) % 1
    edge_m = np.minimum(np.minimum(cell_u, 1 - cell_u),
                        np.minimum(cell_v, 1 - cell_v)) * scale / 4
    grout = 1 - np.clip((edge_m - .002) / .0025, 0, 1)
    grain = (np.sin(2 * math.pi * (29 * u + 17 * v)) * .5 +
             np.sin(2 * math.pi * (43 * u - 31 * v)) * .25)
    height = -grout * .0003 + grain * .00001
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2 * scale / n)
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / (2 * scale / n)
    tangent = np.stack((-dx, dy, np.ones_like(dx)), axis=-1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    normal = np.full((n, n, 4), 255, dtype=np.uint8)
    normal[:, :, :3] = np.rint((tangent * .5 + .5) * 255).astype(np.uint8)
    return normal.tobytes()


def _aggregate_asphalt_maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    """Periodic 2–12 mm aggregate shared by color, roughness, and normal maps."""
    import numpy as np

    n = tile.get("resolution", 512)
    scale = tile["scale_m"]
    metres_per_pixel = scale / n
    seed = 742311 + zlib.crc32(spec["id"].encode("utf-8"))
    rng = np.random.default_rng(seed)
    aggregate = np.zeros((n, n), dtype=np.float32)
    stone_tone = np.zeros_like(aggregate)
    for _ in range(round(scale * scale * 30000)):
        radius = rng.uniform(.001, .006)
        radius_x = radius / metres_per_pixel
        radius_y = radius_x * rng.uniform(.75, 1)
        cx, cy = rng.uniform(0, n, 2)
        x = np.arange(math.floor(cx - radius_x), math.ceil(cx + radius_x) + 1)
        y = np.arange(math.floor(cy - radius_y), math.ceil(cy + radius_y) + 1)
        local_x = (x[None, :] + .5 - cx) / radius_x
        local_y = (y[:, None] + .5 - cy) / radius_y
        angle = np.arctan2(local_y, local_x)
        phase_a, phase_b = rng.uniform(0, 2 * math.pi, 2)
        boundary = .9 + .07 * np.sin(3 * angle + phase_a) + \
                   .03 * np.sin(5 * angle + phase_b)
        profile = np.clip(1 - (local_x ** 2 + local_y ** 2) / boundary ** 2, 0, 1) ** .65
        indices = np.ix_(y % n, x % n)
        previous = aggregate[indices]
        stronger = profile > previous
        aggregate[indices] = np.maximum(previous, profile)
        stone_tone[indices] = np.where(stronger, rng.uniform(-.06, .06) * profile,
                                       stone_tone[indices])

    v, u = np.mgrid[0:n, 0:n].astype(np.float32)
    u, v = (u + .5) / n, (v + .5) / n
    fine = (np.sin(2 * math.pi * (79 * u + 13 * v)) *
            np.sin(2 * math.pi * (17 * u - 89 * v)))
    wear = np.sin(2 * math.pi * (2 * u + v)) * np.sin(2 * math.pi * (u - 3 * v))
    shade = .94 + aggregate * .09 + stone_tone + fine * .018 + wear * .025
    color = np.full((n, n, 4), 255, dtype=np.uint8)
    for channel, base in enumerate(spec["base_color"]["value"][:3]):
        color[:, :, channel] = np.rint(np.clip(base * shade, 0, 1) * 255).astype(np.uint8)
    rough = np.clip(spec["roughness"]["value"] + .025 - aggregate * .04 +
                    fine * .012 + wear * .014, 0, 1)
    roughness = np.full((n, n, 4), 255, dtype=np.uint8)
    roughness[:, :, :3] = np.rint(rough * 255).astype(np.uint8)[:, :, None]

    height = aggregate * .0008 + fine * .000025
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / (2 * metres_per_pixel)
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / (2 * metres_per_pixel)
    tangent = np.stack((-dx, dy, np.ones_like(dx)), axis=-1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    normal = np.full((n, n, 4), 255, dtype=np.uint8)
    normal[:, :, :3] = np.rint((tangent * .5 + .5) * 255).astype(np.uint8)
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    for channel, pixels in (("base_color", color), ("roughness", roughness), ("normal", normal)):
        _png(paths[channel], n, n, pixels.tobytes())
    return paths


def _maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    if tile["pattern"] == "source_pbr":
        paths = tile["maps"]
        required = ("base_color", "roughness", "normal")
        if not all(channel in paths and os.path.isfile(paths[channel]) for channel in required):
            raise FileNotFoundError(f"Missing source PBR maps for {spec['id']}: {paths}")
        return {channel: paths[channel] for channel in required}
    os.makedirs(directory, exist_ok=True)
    n = tile.get("resolution", 256)
    kind = tile["pattern"]
    if kind == "corrugated_metal":
        return _corrugated_maps(spec, tile, directory)
    if kind == "aggregate_asphalt":
        return _aggregate_asphalt_maps(spec, tile, directory)
    if kind == "runoff_decal":
        return _runoff_decal_maps(spec, tile, directory)
    if kind == "weather_patch":
        return _weather_patch_maps(spec, tile, directory)
    if kind == "tread_grooves":
        return _corrugated_maps(spec, {**tile,"pitch_m":.003,"wave_axis":"u","amplitude_m":.00045}, directory)
    if kind in {"weathered_brick", "facade_tile", "weathered_paving", "roof_membrane", "station_wall"}:
        return _architectural_maps(spec, tile, directory)
    base = spec["base_color"]["value"]
    rough = spec["roughness"]["value"]
    color = bytearray()
    roughness = bytearray()
    normal = bytearray()
    for y in range(n):
        v = (y + 0.5) / n
        for x in range(n):
            u = (x + 0.5) / n
            grain = (math.sin(2 * math.pi * (17 * u + 7 * v)) * 0.5 +
                     math.sin(2 * math.pi * (43 * u - 19 * v)) * 0.24 +
                     math.sin(2 * math.pi * (83 * u + 71 * v)) * 0.12)
            broad = math.sin(2 * math.pi * (3 * u + 2 * v)) * 0.5
            shade = 1 + grain * 0.055 + broad * 0.055
            groove = 0.0
            pixel_rough = rough
            if kind in {"ceramic", "floor_tile", "subway_floor", "paving", "stone", "brick", "store_tile"}:
                gap = {"ceramic": 0.018, "floor_tile": 0.011, "paving": 0.02,
                       "subway_floor": .002 / (tile["scale_m"] / 4),
                       "stone": 0.008, "brick": 0.012,
                       "store_tile": 0.012}[kind]
                groove = 1.0 if min(u, 1 - u, v, 1 - v) < gap else 0.0
                if kind == "brick":
                    row = int(v * 4)
                    brick_u = (u * 2 + 0.5 * (row % 2)) % 1
                    brick_v = (v * 4) % 1
                    groove = 1.0 if min(brick_u, 1 - brick_u, brick_v, 1 - brick_v) < 0.035 else 0.0
                    brick_tone = (((int(u * 2) * 37 + row * 97) * 53) % 13 - 6) * 0.012
                    shade += brick_tone
                elif kind == "store_tile":
                    tile_v = (v * 2) % 1
                    groove = 1.0 if min(u, 1 - u, tile_v, 1 - tile_v) < 0.016 else 0.0
                elif kind == "subway_floor":
                    # A 4x4 atlas keeps the 300 mm joints while giving adjacent
                    # tiles different, lightly worn and dusty patches.
                    tile_u, tile_v = (u * 4) % 1, (v * 4) % 1
                    cell_u, cell_v = int(u * 4), int(v * 4)
                    groove = 1.0 if min(tile_u, 1 - tile_u,
                                        tile_v, 1 - tile_v) < gap else 0.0
                    tile_tone = (((cell_u * 13 + cell_v * 29) % 9) - 4) * 0.007
                    wear = (math.sin(2 * math.pi * (2 * u + v)) *
                            math.sin(2 * math.pi * (3 * v - u)))
                    grime = max(0.0, wear * 0.5 + broad * 0.42 + grain * 0.18)
                    shade = 1 + tile_tone + grain * 0.018 - grime * 0.10
                    pixel_rough += grime * 0.10
                shade *= 1 - (0.21 if kind == "subway_floor" else 0.25) * groove
            elif kind == "brushed_metal":
                shade += math.sin(2 * math.pi * 91 * v) * 0.035
            elif kind in {"wood", "bark"}:
                shade += math.sin(2 * math.pi * (18 * u + 2 * math.sin(2 * math.pi * v))) * 0.085
            elif kind == "asphalt":
                grain = (((x * 73856093) ^ (y * 19349663)) & 255) / 255 - 0.5
                shade = 1 + grain * 0.07 + broad * 0.012
            elif kind == "carpet":
                shade += math.sin(2 * math.pi * 73 * u) * math.sin(2 * math.pi * 73 * v) * 0.04
            elif kind == "rubber":
                speckle = (((x * 73856093) ^ (y * 19349663)) & 255) / 255 - 0.5
                shade = 1 + speckle * 0.085 + grain * 0.035
            for component in base[:3]:
                color.append(_clamp(component * shade))
            color.append(255)
            roughness.extend((_clamp(min(1, max(0, pixel_rough +
                                               grain * (0.025 if kind == "subway_floor" else 0.09)
                                               + groove * 0.12))),) * 3 + (255,))
            nx = 0.5 + math.cos(2 * math.pi * (17 * u + 7 * v)) * 0.022
            ny = 0.5 + math.cos(2 * math.pi * (43 * u - 19 * v)) * 0.022
            normal.extend((_clamp(nx), _clamp(ny), _clamp(0.997), 255))
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    _png(paths["base_color"], n, n, color)
    _png(paths["roughness"], n, n, roughness)
    _png(paths["normal"], n, n,
         _subway_floor_normal(tile) if kind == "subway_floor" else normal)
    return paths


def _corrugated_maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    """Periodic sheet corrugation, pigment weathering and linear roughness.

    Normal derivatives use the same physical height profile as the panel pitch.
    The colour map contains pigment variation only; no lighting is baked in.
    """
    import numpy as np

    n, scale = tile.get("resolution", 1024), tile["scale_m"]
    v, u = np.mgrid[0:n, 0:n].astype(np.float64)
    u, v = (u+.5)/n, (v+.5)/n
    across, along = (u, v) if tile.get("wave_axis", "u") == "u" else (v, u)
    cycles = scale / tile["pitch_m"]
    if abs(cycles-round(cycles)) > 1e-8:
        raise ValueError("Corrugated texture scale must contain whole panel pitches")
    wave = np.cos(2*math.pi*cycles*across)
    grain = np.sin(2*math.pi*(113*u+67*v))*.5 + np.sin(2*math.pi*(79*u-137*v))*.25
    streaks = np.maximum(0, np.sin(2*math.pi*(19*across)))*(.6+.4*np.cos(2*math.pi*along))
    wear = np.clip(.25+.20*np.sin(2*math.pi*(2*u+v))+.16*streaks, 0, 1)
    oxide = np.clip((np.sin(2*math.pi*(7*u-3*v))+np.cos(2*math.pi*(11*u+5*v))-1.5)*.07, 0, .08)
    color = np.full((n, n, 4), 255, dtype=np.uint8)
    rust_color = (.34, .19, .10)
    for c, base in enumerate(spec["base_color"]["value"][:3]):
        pigment = base*(1-wear*.11+grain*.015)*(1-oxide)+rust_color[c]*oxide
        color[:, :, c] = np.clip(np.rint(pigment*255), 0, 255).astype(np.uint8)
    roughness = np.full((n, n, 4), 255, dtype=np.uint8)
    rough = np.clip(spec["roughness"]["value"]+wear*.12+oxide*.5+grain*.015, 0, 1)
    roughness[:, :, :3] = np.rint(rough*255).astype(np.uint8)[:, :, None]
    height = wave*tile.get("amplitude_m", .003) + grain*.000025
    dx = (np.roll(height, -1, axis=1)-np.roll(height, 1, axis=1))/(2*scale/n)
    dy = (np.roll(height, -1, axis=0)-np.roll(height, 1, axis=0))/(2*scale/n)
    tangent = np.stack((-dx, dy, np.ones_like(dx)), axis=-1)
    tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
    normal = np.full((n, n, 4), 255, dtype=np.uint8)
    normal[:, :, :3] = np.rint((tangent*.5+.5)*255).astype(np.uint8)
    paths = {channel: os.path.join(directory, f"tile_{spec['id']}_{channel}.png")
             for channel in ("base_color", "roughness", "normal")}
    for channel, pixels in (("base_color", color), ("roughness", roughness), ("normal", normal)):
        _png(paths[channel], n, n, pixels.tobytes())
    return paths


def build(spec: dict, tile: dict, directory: str) -> tuple[bpy.types.Material, dict]:
    paths = _maps(spec, tile, directory)
    mat, tree, output = materials._fresh_material(spec["id"] + "_tiled")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    bsdf.inputs["Metallic"].default_value = spec["metallic"]["value"]
    bsdf.inputs["Alpha"].default_value = spec["base_color"]["value"][3]
    textures = {}
    for channel, path in paths.items():
        image = bpy.data.images.load(path, check_existing=True)
        image.colorspace_settings.name = "sRGB" if channel == "base_color" else "Non-Color"
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.extension = "REPEAT"
        if channel == "base_color":
            tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
            if tile.get("alpha_map"):
                tree.links.new(node.outputs["Alpha"], bsdf.inputs["Alpha"])
        elif channel == "roughness":
            tree.links.new(node.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            normal_map.inputs["Strength"].default_value = tile.get("normal_strength", 0.55)
            tree.links.new(node.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        textures[channel] = {"path": path, "resolution": tile.get("resolution", 256),
                             "colorspace": image.colorspace_settings.name, "cached": False,
                             "seconds": 0.0,
                             "image": image.name}
    materials._apply_surface_settings(mat, spec)
    return mat, textures
