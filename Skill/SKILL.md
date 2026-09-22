---
name: promodeler
description: Author realistic 3D assets as promodeler Python files and iterate on them with headless Blender builds, numerical QA, contact-sheet renders and optional Claude critique. Use when a task asks to create or change a 3D model, prop, container, tool or material with promodeler; not for interactive Blender UI work.
---

# promodeler asset authoring

Python source is the model's source of truth. You edit an asset file, run a build, read the report and the contact sheet, and edit again. Nothing is done through a Blender UI or a Blender MCP session. This skill is self-contained: it holds the workflow, the API cheat sheet and the judgement rules.

## Environment and commands

- Run from the repository root with the system Python 3.13+. Blender 4.2+ must be installed (`python -m promodeler doctor` reports the path, Pillow for contact sheets and the `anthropic` package for critique).
- `python -m promodeler new assets/<name>.py --name "<Name>"` creates a starting file.
- `python -m promodeler recipe assets/<name>.py` validates and prints the recipe without Blender. Use it first after every edit; validation errors are `code: message` pairs and are the cheapest feedback.
- `python -m promodeler build assets/<name>.py` builds. For iteration add `--texture-resolution 256 --bake-samples 4 --passes shaded`; for the final check drop those flags and add `--passes shaded,clay,wireframe --engine cycles`.
- Overrides: `--views perspective,front,back,side,top`, `--passes shaded,clay,wireframe,normals,uv`, `--environment studio|overcast|sunny|sunset|<file.hdr>`, `--engine eevee|cycles`, `--force` (ignore caches).
- `python -m promodeler critique assets/<name>.py [--reference photo.jpg] [--goal "..."]` asks Claude for a structured review of the newest build. When you can view images yourself, look at the contact sheet directly instead.
- `python -m promodeler clean --keep 2` prunes old builds.

Outputs land in `build/<asset>/<hash>/`: `report.json`, `renders/<render-key>/contact_sheet.png` plus individual PNGs, `textures/*.png` (baked PBR set), `model.glb`, `blender.log`. The directory name is the hash of geometry, materials and quality; render-only changes reuse the baked textures and add a renders subfolder.

## Coordinate and unit contracts

- Meters, right-handed, +Y up, +Z toward the viewer (glTF convention). Angles in radians. Colors are sRGB via `srgb(r, g, b)`.
- Primitives are centered on their local origin with height along local Y. `Transform(translation, rotation, scale)` is parent-local XYZ Euler.
- Parts are addressed by string IDs; `root` is reserved. Cutters are never exported.
- Out-of-range values raise `ModelingError` instead of being clamped. Never suppress or work around a validation error; change the value.

## Asset file shape

```python
from dataclasses import dataclass
from promodeler.core import (Asset, AssetGenerator, Bevel, Boolean, Cutter, Cylinder, Displace, Extrude,
                             GenerationInput, Material, ModelingError, Part, Profile, RenderSettings, Revolve,
                             Subdivision, Sweep, Transform, curves, imperfections, presets, srgb)

@dataclass(frozen=True)
class Parameters:
    height: float = 0.11

def validate(p: Parameters) -> None:
    if not 0.03 <= p.height <= 0.3:
        raise ModelingError("can.height", "height must be 3...30 cm.")

def build(input: GenerationInput) -> Asset:
    p = input.parameters
    iron = presets.rusty_iron("iron", seed=input.seed, rust=0.5)
    body = Part(id="body", shape=Revolve(profile=[(0, 0), (0.037, 0), (0.037, p.height), (0, p.height)]),
                material="iron", modifiers=(Subdivision(levels=1, smooth=False),
                                            Displace(height=imperfections.dents(size=0.04, depth=0.003))),
                smooth_angle=0.5)
    return Asset(name="Can", materials=(iron,), parts=(body,))

asset = AssetGenerator(name="Can", parameters=Parameters(), build=build, validate=validate, seed=7)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "clay"))
```

All randomness derives from `input.seed`; pass it into presets and fields. Keep parameters in the dataclass and validate their domain.

## Shapes

| Shape | Notes |
| --- | --- |
| `Box(size)`, `Plane(size)`, `Cylinder(radius, height)`, `Cone(radius, height, top_radius)`, `Sphere(radius)` | segments default to `input.quality.curve_segments` |
| `Extrude(profile=Profile(outer, holes), depth, axis="y")` | profile on the ground (u along X, v along -Z), extruded up; holes are triangulated with constrained Delaunay |
| `Revolve(profile=[(radius, height), ...], segments, angle, cap_ends)` | around Y; zero radius only at the ends (poles); winding is normalized |
| `Sweep(profile=Profile(outer), path=[(x, y, z), ...], scales, twist, capped, up)` | rotation-minimizing frames; no holes; no reversals; `up` fixes the first frame (pass a surface normal to lay a flat profile on a surface) |
| `Strands(strands=(Sweep, ...))` | many sweeps in one mesh without booleans (hair bundles, laces, cables); shells may overlap, self-intersections are not checked, never a boolean operand |
| `Loft(sections=(LoftSection(points, transform), ...), capped)` | equal point counts; point 0 corresponds |

Point helpers in `curves`: `circle`, `regular_polygon`, `rect`, `rounded_rect`, `arc`, `bezier`, `symmetric` (mirror a half outline into a full ring), `join`. Prefer many profile points and `Subdivision(smooth=False)` when a surface will be displaced.

## Modifiers (applied in order)

`Bevel(width, segments, angle_limit)`, `Subdivision(levels, smooth)`, `Solidify(thickness, offset)`, `Mirror(axes)`, `Array(count, offset)`, `Boolean(operation, cutter=Cutter(shape, transform, modifiers), solver="exact")`, `Displace(height=<field>)`, `SimpleDeform(method, angle, factor, axis)`.

Rules that save iterations:

- Bevel outline edges first, cut grooves and holes with booleans afterwards. A bevel after a boolean produces degenerate faces on the cut.
- Never mirror a closed solid whose faces lie on the mirror plane; build the full outline with `curves.symmetric`.
- Offset boolean cutters so no cutter vertex lies exactly in a face plane (rotate a cylinder by half a segment, shift by a fraction of a millimeter).
- Displacement fields may use only `Noise`, `Voronoi`, `Position`, `Facing` and arithmetic. Curvature and cavity need the renderer and are rejected.

## Materials

`Material(id, base_color, roughness, metallic, emission_color, emission_strength, height, layers, bump_strength)`. Every channel is a constant or a field. Fields: `Noise(size, detail, roughness, seed)`, `Voronoi(size, feature, seed)`, `Curvature(radius)`, `Cavity(distance)`, `AmbientOcclusion(distance)`, `Thickness(distance)`, `Facing(direction)`, `Position(axis, start, end)`, combined with `+ - * /`, `.pow()`, `.clamp()`, `.smoothstep(lo, hi)`, `.ramp(stops)`, `ColorRamp(field, stops)`, `.mix()`. Sizes are meters. Layers: `Layer(base_color=..., roughness=..., metallic=..., height=..., mask=<field>)` composite bottom to top.

Presets in `presets`: `worn_leather`, `rusty_iron`, `painted_metal`, `brushed_metal`, `old_wood`, `ceramic_glaze`, `concrete`. Each takes `seed` and a few intent parameters (`wear`, `rust`, `weathering`, `crazing`, `staining`) and `edge_radius`.

Rules:

- `Curvature(radius)` and `edge_radius` must be about three times the geometric bevel width, otherwise rounded edges look flat to the probe and no edge wear appears.
- Feature sizes are physical: leather pores 3 mm, rust pits 2.5 mm, brushed lines 0.4 mm across. Scale them with the object, not with the texture resolution.
- Bump heights are physical meters (0.1 to 1 mm). `bump_strength` of 1.0 to 2.0 is the artistic range.
- A material with any field is baked; a constant material is not. Bakes cost roughly 3 s per channel at 1024 px and 32 samples on a 20-core CPU; iterate at 256 px and 4 samples.

## Rigs, animation, scatter, fur, cloth, LODs

- Rig: `Asset(rig=Rig(id, joints=(Joint(id, head, tail, parent), ...)), poses=(Pose(id, {joint: JointTransform(rotation=(x, y, z))}),), clips=(Clip(id, duration, keyframes=(Keyframe(t, pose_id_or_None), ...)),))`. Joint rotations default to the joint's local frame (Y from head to tail, roll dependent); write verification poses with `space="world"` so Z raises an arm sideways and X swings a limb forward. `Part(skinned=True)` binds by automatic distance weights; `Part(parent_joint=...)` attaches rigidly. Use joint ids distinct from part ids. Verify poses with `--pose <id>` from a view perpendicular to the rotation axis; the export carries clips as glTF animations (`skins`, `animations` in the glb).
- `Scatter(surface=<part id>, instance=<shape>, density, seed, scale, mask)` and `Fur(surface, density, length, thickness, segments, sides, droop, curl, mask)` are shapes of their own parts. Fur triangles = strands x segments x sides x 2: keep strands in the low thousands.
- `ClothDrape(frames, mass, stiffness, bending, pin=<field>)` simulates a part against the other parts and freezes the result; give the cloth a `Subdivision(smooth=False)` for resolution and expect a few self-intersections in folds.
- `Part(lods=(LOD(distance, ratio), ...))` exports decimated `<id>:lod<n>` nodes. `ExportSettings(formats=("glb", "usdz"))` or `--formats glb,usdz` adds USDZ.
- `report.stages` lists seconds per pipeline stage; use it before blaming Blender for a slow build.
- Clip videos: `--clip <id> [--clip-fps 60]` (or `RenderSettings(clip=...)`) renders that clip for every view/camera as a PNG sequence that the host encodes to .mp4 (ffmpeg on PATH) or animated .webp (Pillow). Shaded pass only; the contact sheet skips videos. Budget frames x per-frame render time (about 5 s per 384 px EEVEE frame on this machine) and pick short clips or `--views front`.

## Human bodies

- Do not build a human body from lofts. Fit Meta's MHR to the blueprint: `fit = fitted_body(blueprint_targets(blueprint), out_root=ROOT / "build" / "human", name=<asset>)`, then `Part(id="body", shape=MeshFile(fit["mesh"]), material="skin", skinned=True)` and `rig = rig_from_file(fit["rig"], rig_id=<asset>)` (126 joints, MHR names such as `l_uparm`, `r_upleg`, `c_spine3`, `c_head`; rest pose is an A-pose with arms about 40 degrees below horizontal). The first build fits for about 40 s and caches under `build/human/`.
- Fit clothing and hair to the fitted surface, not to the blueprint numbers: slice `body.npz` at the section heights (`assets/haruka.py` has `BodyMeasure.slice`) and add ease. Loft sections must run bottom to top or the closed shell faces inward (`geometry.insideOut`).
- Requires `torch` and `numpy` on the host Python and the MHR assets under `external/mhr` (see `tools/mhr_dump_lod1.py`); Blender never loads torch. If `mhr.assets` is raised, report it instead of falling back to a loft body.
- Check the fitted measurements in `build/human/<name>-<hash>/rig.json` (`measurements`) against the blueprint before judging renders; a few millimeters on lengths and 1 to 2 cm on circumferences is the current accuracy.
- Hair: a thin scalp cap plus `Strands` bundles whose paths follow a skull ellipsoid measured from the body, then hang with an eased drift to a target behind or in front of the shoulders. Pass the skull normal as `Sweep.up` so flat bundles lie on the scalp, make bundle widths about twice their spacing, and start outer layers lower than inner ones so they emerge from underneath.
- Clothing: build the loft as the garment's inner surface from body slices plus ease, keep the cloth quads near square (rings every 5 to 10 cm, `Subdivision(levels=1, smooth=True)`), pin the neckline band and let `ClothDrape` settle; a dense ring with sparse rings buckles into an accordion. Shape gathers in the ring points, not in a texture.
- Shoes: measure the foot print and ankle from the body slices, extrude the sole outline, loft the upper as the inner surface with 6 mm clearance and `Solidify(offset=1.0)` outward, attach every shoe part with `parent_joint=<side>_subtalar`, and lift the body and rig by the sole (`rig_from_file(..., offset=(0, sole, 0))`, `Part(transform=Transform(translation=(0, sole, 0)))`).
- Bakes fill texels no UV island touched with the mean baked value, so meshes with tiny islands (MHR faces) no longer show black specks; the face still needs 2048 px or more (`QualityProfile(texture_resolution=2048)` on the generator).
- The blueprint's QA stills come from authored cameras (`face`, `neckline`, `sneaker`, `hand`); its range-of-motion check is a pose (`range_check`) rendered with `--pose`.
- Eyes on an MHR body: cut sockets with two ellipsoid `Boolean("difference")` cutters centred 6 mm in front of the `l_eye`/`r_eye` joints (scale about 1.4 x 1.0 x 1.8 of a 10 mm sphere) and add 12 mm `Sphere` parts with `parent_joint="l_eye"`; the iris and pupil are `Position("z", ...)` layers in the sphere's object space. File weights survive the boolean (nearest-vertex transfer, `influences: "file:nearest"` in the report).
- Hands: MHR rests with straight fingers. Curl `<side>_<finger>1..3` in joint space (20-35 degrees about local X) in a `hands` dict merged into every pose, and key a `rest` pose instead of `None` so clips keep the curl.
- `Asset(extras={...})` carries JSON the GLB cannot express (runtime physics settings, engine targets); it lands in `extras.json` and the glTF root node's `promodeler_extras`.
- After a humanoid build run `python tools/blueprint_check.py <blueprint.json>` and report its table: fit residuals, part boxes, triangle budgets and warnings against the blueprint. Blueprint numbers can contradict each other (an ellipse of the 05-woman hip section is 9 cm short of its hip circumference); circumferences lead, torso widths/depths are reported, and you say which side you kept.

## Interiors and architecture

- Build rooms from the blueprint's zone rectangles as axis-aligned boxes (a small `box_part(x0, x1, y0, y1, z0, z1)` helper keeps extents readable) and cut openings with `Boolean("difference")` box cutters that overshoot the wall thickness by 2 cm.
- Movable fittings are joints: a hinge is a joint at the pivot with the tail 1 m up and a world-space Y rotation (`+` moves +X toward -Z); a slide is a world-space translation. Attach leaves with `parent_joint`.
- Verify with authored cameras: `RenderSettings(views=(), cameras=(Camera("interior", position, target, fov), Camera("section", ..., orthographic=True, ortho_scale=<width m>, clip_start=0.001), Camera("dollhouse", ..., hide_parts=("ceiling_slab",))))` and `lights=(Light(...),)` for interiors, then check the acceptance dimensions from `report.parts.<id>.bounds`.
- `Bricks(width, height, mortar, axis)` gives plank, tile and brick seams; use it in `height` (negative) and as a darker layer mask.
- Every part with a procedural material bakes its own texture set. For buildings with dozens of parts, keep small parts on constant materials or the export grows by megabytes per part.

## Imperfections

`imperfections.wobble(size, amplitude, seed)`, `dents(size, depth, coverage, seed)`, `grain(size, amplitude, seed)`, `ripples(size, amplitude, seed)` return height fields for `Displace`. Use them: a straight, round, flat object reads as computer generated before any texture does.

## Verification loop

1. `recipe` until validation passes.
2. `build` at iteration quality. Read the printed summary and `report.json`: bounds against the intended size, `watertight`, `volume` positive, `self_intersections` zero, `non_manifold_edges` zero, `uv.coverage` above 0.3, `texel_density_px_per_m` adequate for the closest view, and every entry in `warnings`.
3. Open `renders/<key>/contact_sheet.png`. Judge silhouette and proportions on the clay pass first, mesh density on the wireframe pass, then materials on the shaded pass: is the wear where hands and edges would wear it, is the roughness contrast visible, are feature sizes plausible for the object's size, does anything look uniformly repeated?
4. Change one thing at a time in the asset file, rebuild, compare.
5. Final check at full quality with `--passes shaded,clay,wireframe --engine cycles` and, when a reference photo exists, `critique --reference`.

Report what was verified and how: numerical checks passed, which images were inspected, and what was not checked (for example, no reference comparison). A finished render is not proof of correctness; a warning-free report is not proof of realism.

## Failure handling

- `status: failed` in the report carries `error.code` and `error.message`; `blender.log` has the traceback. Fix the recipe rather than retrying the same build.
- `geometry.selfIntersection` or `geometry.degenerate` after a boolean: change modifier order (bevel before boolean) or move the cutter off the face plane.
- `uv.coverage` low: the shape has long thin islands; increase `texture_resolution` or split the part.
- Displacement without visible effect: the mesh is too coarse; add `Subdivision(smooth=False)` or more profile points.
- A black render under `sunny`/`sunset`: an environment failure; rebuild with `--environment studio` and report the error.

Do not publish, install tools or edit unrelated project files while authoring an asset.
