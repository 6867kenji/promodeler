"""Planned facilities occupy dedicated city lots and retain street access."""

import json
from pathlib import Path

from promodeler.core import Box, Extrude, ModelingError, Part, Profile, Transform
from assets.warehouse import warehouse_parts
from assets.subway_station import station


CONFIG_PATH = Path(__file__).resolve().parents[1] / "blueprints/japan-realistic-v1/01-city/facility_layout.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def with_facilities(layout):
    facilities = CONFIG["facilities"]
    occupied_ids = {f["occupiedSite"] for f in facilities}
    occupied = [dict(r, status="occupied", facility=next(f["id"] for f in facilities if f["occupiedSite"] == r["id"]))
                for r in layout["reservedSites"] if r["id"] in occupied_ids]
    result = {**layout, "schema": "promodeler-city-layout/3.0", "baseBuildingCount": len(layout["buildings"]),
              "buildingCount": len(layout["buildings"])+sum(f.get("countAsBuilding",True) for f in facilities), "facilities": facilities,
              "occupiedSites": occupied, "reservedSites": [r for r in layout["reservedSites"] if r["id"] not in occupied_ids]}
    validate_facilities(result)
    return result


def validate_facilities(layout):
    ids = set()
    for facility in layout.get("facilities", []):
        if facility["id"] in ids:
            raise ModelingError("city.facilityId", "Duplicate facility")
        ids.add(facility["id"])
        lot = next((r for r in layout.get("occupiedSites", []) if r["id"] == facility["occupiedSite"]), None)
        if lot is None:
            raise ModelingError("city.facilityLot", facility["id"])
        x0, z0, x1, z1 = facility["bounds"]
        a, b, c, d = lot["bounds"]
        if not (a <= x0 < x1 <= c and b <= z0 < z1 <= d):
            raise ModelingError("city.facilityBoundary", "Facility extends beyond its dedicated lot")
        if any(overlap(facility["bounds"], r["bounds"]) for r in layout["buildings"]+layout["reservedSites"]):
            raise ModelingError("city.facilityCollision", facility["id"])
        # A connected walkway reaches the front personnel doorway. The
        # separate vehicle entrance crosses the sidewalk through a curb ramp.
        path = facility["pedestrianRoute"]
        if any(min(r[2]-r[0], r[3]-r[1]) < facility["pedestrianRouteWidthM"]-1e-8 for r in path):
            raise ModelingError("city.facilityWalkWidth", facility["id"])
        for previous, current in zip(path, path[1:]):
            if (max(previous[0], current[0]) > min(previous[2], current[2]) or
                    max(previous[1], current[1]) > min(previous[3], current[3])):
                raise ModelingError("city.facilityWalkDisconnected", facility["id"])
        if facility.get("kind") == "subway":
            x,z = facility["entrancePointXZ"]
            if path[0][2] < -10 or not any(a <= x <= c and b <= z <= d for a,b,c,d in path):
                raise ModelingError("city.facilityWalkEndpoint",facility["id"])
        elif path[0][0] > 10 or path[-1][3] < 33.25 or not (path[-1][0] <= 15.45 <= path[-1][2]):
            raise ModelingError("city.facilityWalkEndpoint", facility["id"])


def add_facilities(parts, layout):
    def b(name, bounds, material):
        x0, x1, y0, y1, z0, z1 = bounds
        parts.append(Part(id="lot_warehouse_"+name, shape=Box(size=(x1-x0, y1-y0, z1-z0)),
                          material=material, transform=Transform(translation=((x0+x1)/2, (y0+y1)/2, (z0+z1)/2))))

    for f in layout["facilities"]:
        if f.get("kind") == "subway":
            _add_subway(parts,f)
            continue
        parts.extend(warehouse_parts(f["id"], origin=tuple(f["position_m"]), yaw=f["yaw_rad"]))
        a, c, d, e = f["loadingApron"]
        b("apron", (a, d, .036, .042, c, e), "wh_apron")
        # Cut the original curb at the drive, instead of hiding it under a slab.
        curb = next(p for p in parts if p.id == "curb_ew_1_2_1")
        parts.remove(curb)
        for name, left, right in (("curb_w", 10., 21.5), ("curb_e", 30.5, 120.)):
            b(name, (left, right, 0, .15, 6., 6.18), "concrete")
        b("drive_over_walk", (21.5, 30.5, .150, .158, 6.18, 10.), "wh_apron")
        for name, poly in (("drive_ramp_street", ((-6.18, 0), (-5.5, 0), (-5.5, .005), (-6.18, .158))),
                           ("drive_ramp_lot", ((-11.8, .036), (-10., .036), (-10., .158), (-11.8, .042)))):
            parts.append(Part(id="lot_warehouse_"+name, shape=Extrude(Profile(poly), depth=9., axis="x"),
                              material="wh_apron", transform=Transform(translation=(21.5, 0, 0))))
        # Accessible person route: a shallow transition from the existing
        # sidewalk, then paving along the west side of the loading court.
        parts.append(Part(id="lot_warehouse_walk_ramp",
                          shape=Extrude(Profile(((10., .035), (13., .035), (13., .07), (10., .15))), depth=1.8, axis="z"),
                          material="brick_walk", transform=Transform(translation=(0, 0, 17.))))
        for i, r in enumerate(f["pedestrianRoute"][1:]):
            b(f"walk_{i}", (r[0], r[2], .036, .07, r[1], r[3]), "brick_walk")
        # Short ramp from the path to the warehouse's 10 cm finished floor.
        parts.append(Part(id="lot_warehouse_personnel_ramp",
                          shape=Extrude(Profile(((-33.25, .036), (-32.45, .036), (-32.45, .07), (-33.25, .10))), depth=1.4, axis="x"),
                          material="wh_floor", transform=Transform(translation=(14.75, 0, 0))))
        for i in range(3):
            x = 33.3+i*2.65
            b(f"parking_line_{i}", (x, x+.08, .043, .046, 14, 20), "wh_yellow")
        for side in (-1, 1):
            b(f"drive_edge_{side}", (26+side*4.4-.04, 26+side*4.4+.04, .043, .046, 12, 26), "wh_yellow")


def _add_subway(parts, facility):
    model = station(facility["id"],origin=tuple(facility["stationOrigin_m"]))
    parts.extend(model.parts)
    def b(name, bounds, material):
        x0,z0,x1,z1 = bounds
        parts.append(Part(id="lot_subway_"+name,shape=Box(size=(x1-x0,.115,z1-z0)),material=material,
                          transform=Transform(translation=((x0+x1)/2,.0925,(z0+z1)/2))))
    for i,bounds in enumerate(facility["pedestrianRoute"]):
        b(f"walk_{i}",bounds,"brick_walk")
    b("lift_approach",facility["elevatorApproach"],"brick_walk")
    # Guidance follows the raised approach from the east sidewalk to the stair.
    from promodeler.core import Array
    for i in range(4):
        z=-62.3+i*.075
        parts.append(Part(id=f"lot_subway_guide_{i}",shape=Box(size=(18.,.012,.018)),material="tactile",
                          transform=Transform(translation=(-20.,.156,z))))
    for i in range(2):
        x=-31.5-i*1.8
        parts.append(Part(id=f"lot_subway_bollard_{i}",shape=Box(size=(.09,.85,.09)),material="metal",
                          transform=Transform(translation=(x,.575,-59.))))


def open_station_ground(parts,layout):
    """Cut the city ground and the relevant block slab at the stairwell."""
    from dataclasses import replace
    holes = [f["groundOpening"] for f in layout["facilities"] if f.get("kind") == "subway"]
    for i,part in enumerate(parts):
        if part.id not in ("ground","block_1_1"):
            continue
        sx,sy,sz = part.shape.size
        x,y,z = part.transform.translation
        outer = ((x-sx/2,-z-sz/2),(x+sx/2,-z-sz/2),(x+sx/2,-z+sz/2),(x-sx/2,-z+sz/2))
        rings = tuple(((a,-d),(c,-d),(c,-b),(a,-b)) for a,b,c,d in holes)
        parts[i] = replace(part,shape=Extrude(Profile(outer,rings),depth=sy,axis="y"),transform=Transform(translation=(0,y-sy/2,0)))
