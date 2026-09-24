"""Small, physically scaled PBR maps shared by large architectural meshes."""

from __future__ import annotations

import math
import os
import struct
import zlib

import bpy

from . import materials


def project(obj: bpy.types.Object, scale_m: float) -> None:
    """Box-project each face in object metres so large walls repeat a small image."""
    mesh = obj.data
    layer = mesh.uv_layers.active or mesh.uv_layers.new(name="TiledUV")
    for polygon in mesh.polygons:
        normal = polygon.normal
        dominant = max(range(3), key=lambda axis: abs(normal[axis]))
        axes = ((1, 2), (0, 2), (0, 1))[dominant]
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            layer.data[loop_index].uv = (vertex[axes[0]] / scale_m,
                                         vertex[axes[1]] / scale_m)


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


def _maps(spec: dict, tile: dict, directory: str) -> dict[str, str]:
    os.makedirs(directory, exist_ok=True)
    n = tile.get("resolution", 256)
    kind = tile["pattern"]
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
                       "subway_floor": 0.013, "stone": 0.008, "brick": 0.012,
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
                    wear = (math.sin(2 * math.pi * (u * 2.3 + v * 0.7)) *
                            math.sin(2 * math.pi * (v * 3.1 - u * 0.4)))
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
    _png(paths["normal"], n, n, normal)
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
