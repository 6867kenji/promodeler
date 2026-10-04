"""Reference-informed fixtures for the connected station.

The supplied FBX sets establish the look of the gates, ticket vending and
station finishes. These dimensioned parts retain the blueprint's clearances.
"""

from __future__ import annotations

from promodeler.core import Bevel, Box, Cylinder, Part, Transform


def _box(parts, name, bounds, material, bevel=0.0):
    x0, x1, y0, y1, z0, z1 = bounds
    parts.append(Part(
        id=name,
        shape=Box(size=(x1 - x0, y1 - y0, z1 - z0)),
        material=material,
        transform=Transform(translation=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)),
        modifiers=(Bevel(width=bevel, segments=3),) if bevel else (),
    ))


def concourse_reference_details(parts, design):
    # Dark tiled wainscot and a brushed upper rail give the long B1 hall a
    # visual rhythm while keeping the 20 m shell and walking surface intact.
    for side, x0, x1 in (("west", -9.79, -9.77), ("east", 9.77, 9.79)):
        _box(parts, f"reference_wainscot_{side}",
             (x0, x1, 0.12, 0.82, -47.8, 47.8), "reference-dark-tile")
        _box(parts, f"reference_wainscot_cap_{side}",
             (x0 - .006, x1 + .006, .82, .845, -47.8, 47.8), "stainless")

    # Each cabinet gets a profiled top, inset end cap, glass side and a
    # readable illuminated entry marker based on the supplied turnstiles.
    cabinets = design["faregates"]["lanes"]
    for index in range(len(cabinets) + 1):
        x = -3.67 + index * .88 if index < 8 else 3.67
        if index == 8:
            x = 3.67
        _box(parts, f"reference_gate_top_{index}",
             (x - .145, x + .145, .965, 1.03, -28.83, -27.17),
             "reference-metal-plate", bevel=.018)
        for tag, z0, z1 in (("entry", -28.86, -28.81),
                            ("exit", -27.19, -27.14)):
            _box(parts, f"reference_gate_end_{index}_{tag}",
                 (x - .136, x + .136, .08, .96, z0, z1),
                 "reference-metal-plate", bevel=.009)
        for tag, face_x in (("left", x - .151), ("right", x + .147)):
            _box(parts, f"reference_gate_side_{index}_{tag}",
                 (face_x, face_x + .004, .37, .84, -28.52, -27.49), "glass")
        _box(parts, f"reference_gate_reader_surround_{index}",
             (x - .116, x + .116, 1.03, 1.045, -28.65, -28.36),
             "dark-display", bevel=.008)
        _box(parts, f"reference_gate_entry_led_{index}",
             (x - .09, x + .09, 1.046, 1.05, -28.75, -28.7), "teal")
        _box(parts, f"reference_gate_exit_led_{index}",
             (x - .09, x + .09, 1.031, 1.036, -27.29, -27.25), "light")

    # Ticket machines are already laid out in the design JSON; the front
    # hardware is added here, facing the public hall at x < 8.5.
    for index, z in enumerate((-36.0, -39.0, -42.0)):
        _box(parts, f"reference_ticket_frame_{index}",
             (8.475, 8.5, .21, 1.58, z - .31, z + .31),
             "reference-metal-plate", bevel=.01)
        _box(parts, f"reference_ticket_screen_{index}",
             (8.466, 8.476, .93, 1.43, z - .24, z + .24), "dark-display")
        _box(parts, f"reference_ticket_screen_glass_{index}",
             (8.46, 8.466, .94, 1.42, z - .23, z + .23), "glass")
        _box(parts, f"reference_ticket_header_{index}",
             (8.457, 8.473, 1.48, 1.56, z - .24, z + .24), "teal")
        _box(parts, f"reference_ticket_slot_{index}",
             (8.451, 8.471, .64, .69, z - .18, z + .15), "dark-display")
        _box(parts, f"reference_ticket_payment_{index}",
             (8.449, 8.469, .45, .56, z + .07, z + .21), "stainless")
        _box(parts, f"reference_ticket_foot_{index}",
             (8.46, 8.53, 0, .2, z - .32, z + .32), "reference-dark-tile")

    # Two vending fronts mirror the reference set; both stay in the side bay
    # so the gate approaches and tactile guide remain open.
    for index, z in enumerate((-45.15, -33.0)):
        body = "vending-blue" if index == 0 else "vending-ivory"
        for tag, bounds in (
            ("left", (8.52, 9.41, 0, 2.02, z - .55, z - .49)),
            ("right", (8.52, 9.41, 0, 2.02, z + .49, z + .55)),
            ("back", (9.35, 9.41, 0, 2.02, z - .49, z + .49)),
            ("roof", (8.52, 9.41, 1.95, 2.02, z - .49, z + .49)),
            ("base", (8.52, 9.41, 0, .31, z - .49, z + .49)),
            ("control", (8.52, 8.56, .31, 1.72, z + .22, z + .49)),
        ):
            _box(parts, f"reference_vending_body_{index}_{tag}", bounds, body,
                 bevel=.008)
        _box(parts, f"reference_vending_header_{index}",
             (8.494, 8.519, 1.72, 1.95, z - .49, z + .49),
             "vending-blue" if index == 0 else "teal")
        _box(parts, f"reference_vending_window_{index}",
             (8.87, 8.89, .7, 1.67, z - .45, z + .22), "dark-display")
        _box(parts, f"reference_vending_glass_{index}",
             (8.478, 8.484, .7, 1.67, z - .45, z + .22), "glass")
        _box(parts, f"reference_vending_payment_{index}",
             (8.47, 8.49, 1.03, 1.45, z + .28, z + .47), "dark-display")
        _box(parts, f"reference_vending_delivery_{index}",
             (8.47, 8.49, .34, .62, z - .3, z + .3), "dark-display")
        for row in range(3):
            shelf_y = .78 + row * .27
            _box(parts, f"reference_vending_shelf_{index}_{row}",
                 (8.56, 8.86, shelf_y, shelf_y + .018,
                  z - .44, z + .20), "reference-metal-plate")
            for column in range(4):
                product_z = z - .37 + column * .17
                product_y = shelf_y + .105
                tone = "teal" if (row + column + index) % 3 == 0 else "paint"
                for suffix, radius, height, offset, material in (
                    ("bottle", .045, .16, 0, body),
                    ("label", .046, .06, -.015, tone),
                    ("cap", .028, .018, .09, "paint"),
                ):
                    parts.append(Part(
                        id=f"reference_vending_product_{index}_{row}_{column}_{suffix}",
                        shape=Cylinder(radius=radius, height=height, segments=16),
                        material=material,
                        transform=Transform(translation=(8.63, product_y + offset,
                                                         product_z + .055)),
                    ))


def platform_reference_details(parts, design):
    # Track beds use the source's worn concrete PBR; sidewall bands carry its
    # dark tile. Keep all of these beyond the platform glazing and tactile run.
    for side, x0, x1 in (("west", -10.29, -10.27), ("east", 10.27, 10.29)):
        _box(parts, f"reference_platform_wainscot_{side}",
             (x0, x1, -.95, 1.05, -65.8, 65.8), "reference-dark-tile")
        _box(parts, f"reference_platform_band_{side}",
             (x0 - .006, x1 + .006, 1.05, 1.1, -65.8, 65.8), "stainless")
    # Small platform door base plinths give the glazing a more complete,
    # mechanically plausible connection to the floor.
    for side, x0, x1 in (("west", -4.94, -4.89), ("east", 4.89, 4.94)):
        for index, z in enumerate(range(-60, 61, 6)):
            _box(parts, f"reference_platform_door_plinth_{side}_{index}",
                 (x0, x1, .02, .15, z - 2.7, z + 2.7),
                 "reference-metal-plate")
