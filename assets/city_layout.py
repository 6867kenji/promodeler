"""Deterministic dense lots, street frontages and unoccupied future sites."""

import json
import math
import random
from pathlib import Path

from promodeler.core import ModelingError


RULES = json.loads((Path(__file__).resolve().parents[1] / "blueprints/japan-realistic-v1/01-city/density_layout.json").read_text(encoding="utf-8"))
BLOCK_INTERVALS = ((-250., -130.), (-120., -10.), (10., 120.), (130., 250.))
BODY_BOUNDS = {"02-apartment": (-15., -8.8, 15., 8.5),
               "03-convenience": (-9., -6., 9., 6.), "04-office": (-12., -9., 12., 9.)}


def overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _widths(target, ranges, weights):
    """Fill a row without changing the requested gap distances."""
    minimum, maximum = sum(low for low, high in ranges), sum(high for low, high in ranges)
    if not minimum - 1e-8 <= target <= maximum + 1e-8:
        raise ModelingError("city.rowCapacity", f"Cannot fit row width {target:.2f} into {ranges}")
    target = min(maximum, max(minimum, target))
    low, high = 0., 20.
    for _ in range(60):
        factor = (low + high) / 2
        values = [min(hi, max(lo, weight * factor)) for (lo, hi), weight in zip(ranges, weights)]
        if sum(values) < target:
            low = factor
        else:
            high = factor
    return [min(hi, max(lo, weight * (low + high) / 2)) for (lo, hi), weight in zip(ranges, weights)]


def dense_layout(design, variation):
    rng = random.Random(RULES["seed"])
    records, reserves, gaps, rows = [], [], [], []
    indexed = {p["id"]: (index, p) for index, p in enumerate(design["placements"])}
    for row_block, (z0, z1) in enumerate(BLOCK_INTERVALS):
        for column, (x0, x1) in enumerate(BLOCK_INTERVALS):
            block = [column, row_block]
            reserved = next((r for r in RULES["reservedSites"] if r["block"] == block), None)
            primary = [indexed[f"b-{column}-{row_block}-{i}"] for i in range(4)]
            rng.shuffle(primary)
            setback = RULES["frontageSetbackM"]
            row_gaps = [rng.uniform(3., 5.5) for _ in range(3)]
            weights = [rng.uniform(.92, 1.08) for _ in range(4)]
            available = z1 - z0 - 2 * setback - sum(row_gaps)
            depths = [available * w / sum(weights) for w in weights]
            z_cursor = z0 + setback
            for lane in range(4):
                depth = depths[lane]
                z_back, z_front = z_cursor, z_cursor + depth
                start, end = x0 + setback, x1 - setback
                short = reserved and ((reserved["corner"] == "nw" and lane < 2)
                                      or (reserved["corner"] == "se" and lane >= 2))
                if short:
                    if reserved["corner"] == "nw":
                        start = x0 + reserved["widthM"] + setback
                    else:
                        end = x1 - reserved["widthM"] - setback
                primary_index, original = primary[lane]
                kind = original["blueprint"]
                horizontal, vertical = variation(primary_index)
                # A native building occupies the middle column. Its width is
                # unchanged; depth adapts to its lot, keeping the street edge.
                primary_width = (BODY_BOUNDS[kind][2] - BODY_BOUNDS[kind][0]) * horizontal
                primary_column = 2
                small_columns = {0, 4} if not short else {0, 1, 3, 4}
                ranges, weights_x = [], []
                for slot in range(5):
                    if slot == primary_column:
                        ranges.append((primary_width, primary_width))
                        weights_x.append(primary_width)
                    elif slot in small_columns:
                        ranges.append((8., 14. if not short else 22.))
                        weights_x.append(rng.uniform(9., 12.))
                    else:
                        ranges.append((18., 36.))
                        weights_x.append(rng.uniform(22., 30.))
                # Narrow-frontage neighbours get the tightest gaps on both
                # sides. Other pairs can have wider service passages.
                distances = [rng.uniform(1., 2.4) if i in small_columns or i + 1 in small_columns
                             else rng.uniform(3., 12.) for i in range(4)]
                target = end - start - sum(distances)
                if target < sum(lo for lo, hi in ranges):
                    deficit = sum(lo for lo, hi in ranges) - target + 1e-7
                    slack = sum(distance - 1 for distance in distances)
                    distances = [distance - deficit * (distance - 1) / slack for distance in distances]
                    target = end - start - sum(distances)
                widths = _widths(target, ranges, weights_x)
                # Classification uses the final widths, so any narrow lot
                # produced by a compressed row still receives a tight gap.
                for i in range(4):
                    if min(widths[i], widths[i + 1]) <= 14:
                        distances[i] = min(distances[i], 2.4)
                widths = _widths(end - start - sum(distances), ranges, weights_x)
                x_cursor = start
                row_ids = []
                for slot, width in enumerate(widths):
                    left, right = x_cursor, x_cursor + width
                    center_x, center_z = (left + right) / 2, (z_back + z_front) / 2
                    yaw = math.pi if lane == 0 or lane == 2 else 0.
                    if lane in (1, 2) and slot in (0, 4) and not short:
                        yaw = -math.pi / 2 if slot == 0 else math.pi / 2
                    local_w, local_d = (depth, width) if abs(math.sin(yaw)) > .5 else (width, depth)
                    record = {"block": block, "row": lane, "column": slot,
                              "bounds": [left, z_back, right, z_front], "x": center_x, "z": center_z,
                              "width": width, "depth": depth, "local_width": local_w,
                              "local_depth": local_d, "yaw": yaw,
                              "side_gaps_m": [distances[slot - 1] if slot else None,
                                               distances[slot] if slot < 4 else None]}
                    if slot == primary_column:
                        lo_x, lo_z, hi_x, hi_z = BODY_BOUNDS[kind]
                        sx, sz = local_w / (hi_x - lo_x), local_d / (hi_z - lo_z)
                        local_offset = (lo_z + hi_z) / 2 * sz
                        position = [center_x - local_offset * math.sin(yaw), 0.,
                                    center_z - local_offset * math.cos(yaw)]
                        record.update({"id": "site_" + original["id"], "kind": "designed",
                                       "source_index": primary_index, "blueprint": kind,
                                       "placement": {**original, "position_m": position, "yaw_rad": yaw,
                                                     "layout_scale": [sx, vertical, sz], "layout_bounds": record["bounds"]}})
                    else:
                        narrow = width <= 14
                        record.update({"id": f"infill_{column}_{row_block}_{lane}_{slot}", "kind": "infill",
                                       "floors": rng.randint(2, 6) if narrow else rng.randint(4, 10),
                                       "facade": rng.choice(("brick_red", "brick_sand", "brick_charcoal",
                                                             "tile_sand", "tile_rose", "tile_gray",
                                                             "paint_cream", "paint_sage", "paint_blue")),
                                       "glass": rng.choice(("glass", "glass_blue", "glass_green"))})
                    records.append(record)
                    row_ids.append(record["id"])
                    if slot < 4:
                        gaps.append({"block": block, "row": lane, "left": record["id"],
                                     "distance_m": distances[slot]})
                        x_cursor = right + distances[slot]
                rows.append({"block": block, "row": lane, "bounds": [start, z_back, end, z_front],
                             "buildings": row_ids})
                if reserved and ((reserved["corner"] == "nw" and lane == 1)
                                 or (reserved["corner"] == "se" and lane == 2)):
                    if reserved["corner"] == "nw":
                        rect = [x0 + .3, z0 + .3, x0 + reserved["widthM"] - .3, z_front - .3]
                    else:
                        rect = [x1 - reserved["widthM"] + .3, z_back + .3, x1 - .3, z1 - .3]
                    reserves.append({**reserved, "bounds": rect,
                                     "size_m": [rect[2] - rect[0], rect[3] - rect[1]]})
                z_cursor = z_front + (row_gaps[lane] if lane < 3 else 0)
    result = {"schema": "promodeler-city-layout/2.0", "seed": RULES["seed"],
              "buildingCount": len(records), "buildingsPerBlock": 20,
              "frontageSetbackM": RULES["frontageSetbackM"], "buildings": records,
              "reservedSites": reserves, "rows": rows, "sideGaps": gaps}
    validate_dense_layout(result, design)
    return result


def validate_dense_layout(layout, design):
    records = layout["buildings"]
    if len(records) != 320 or len({r["id"] for r in records}) != 320:
        raise ModelingError("city.denseCount", "Expected 320 distinct buildings")
    roads = [r["rect_xz_m"] for r in design["layout"]]
    for row_block in range(4):
        for column in range(4):
            if sum(r["block"] == [column, row_block] for r in records) != 20:
                raise ModelingError("city.blockCount", "Every block must contain 20 buildings")
    for i, record in enumerate(records):
        bounds = record["bounds"]
        if min(bounds[:2]) < -250 or max(bounds[2:]) > 250:
            raise ModelingError("city.boundary", record["id"])
        if any(overlap(bounds, road) for road in roads):
            raise ModelingError("city.roadCollision", record["id"])
        if any(overlap(bounds, other["bounds"]) for other in records[:i]):
            raise ModelingError("city.buildingCollision", record["id"])
        if any(overlap(bounds, reserve["bounds"]) for reserve in layout["reservedSites"]):
            raise ModelingError("city.reservationCollision", record["id"])
        side_gaps = [gap for gap in record["side_gaps_m"] if gap is not None]
        if not all(1 - 1e-8 <= gap <= 12 + 1e-8 for gap in side_gaps):
            raise ModelingError("city.sideGap", record["id"])
        if record["width"] <= 14 and not all(gap <= 2.4 + 1e-8 for gap in side_gaps):
            raise ModelingError("city.smallSideGap", record["id"])
    for reserve in layout["reservedSites"]:
        if any(size < need for size, need in zip(reserve["size_m"], reserve["requiredClearanceM"])):
            raise ModelingError("city.reservationSize", reserve["id"])
