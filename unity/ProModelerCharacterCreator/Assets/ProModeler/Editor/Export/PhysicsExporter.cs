// physics.json: the runtime physics set-up the target engine needs to reproduce the recipe's `physics` block on the
// built character (docs/03 M13): the blueprint settings verbatim, the rig limits, body colliders sized from the
// measured girths, the attached accessories with their measured bounds (collider size) and mass, and the garments
// with their deformation class. Nothing here is simulated in the batch build; it is the contract for whoever runs it.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Recipe;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class PhysicsExporter
    {
        const float DefaultAccessoryDensityKgM3 = 250f;   // bags and cases: mostly air around a few solid parts

        public static string Export(UMACharacterRuntime runtime, CharacterRecipe recipe, BuildReport report, string outDir)
        {
            var measured = report.MeasuredM ?? new JObject();
            var height = (float?)measured["barefoot_height"] ?? recipe.Body.MeasurementsM.BarefootHeight;
            var scale = recipe.Body.MeasurementsM.BarefootHeight > 0f ? height / recipe.Body.MeasurementsM.BarefootHeight : 1f;

            var colliders = new JArray();
            foreach (var section in recipe.Body.MeasurementsM.CrossSections)
            {
                var girth = (float?)measured[section.Landmark];
                if (girth == null || girth <= 0f) continue;
                var bone = section.Landmark == "hip" ? "Hips" : section.Landmark == "waist" ? "Spine" : "Spine1";
                colliders.Add(new JObject
                {
                    ["landmark"] = section.Landmark, ["bone"] = bone, ["shape"] = "capsule",
                    ["radius_m"] = Math.Round(girth.Value / (2.0 * Math.PI), 4), ["centre_height_m"] = Math.Round(section.Height * scale, 4),
                    ["half_height_m"] = 0.06, ["note"] = "radius from the measured girth (tape circle); the torso is wider than deep, so pair with the section extents when the engine supports ellipsoids",
                });
            }
            foreach (var side in new[] { "Left", "Right" })
            {
                var upper = runtime.Bone(side + "UpLeg"); var knee = runtime.Bone(side + "Leg"); var arm = runtime.Bone(side + "Arm"); var fore = runtime.Bone(side + "ForeArm"); var hand = runtime.Bone(side + "Hand");
                if (upper != null && knee != null) colliders.Add(Capsule(side.ToLowerInvariant() + "_thigh", side + "UpLeg", Vector3.Distance(upper.position, knee.position), 0.075f * scale));
                if (arm != null && fore != null) colliders.Add(Capsule(side.ToLowerInvariant() + "_upper_arm", side + "Arm", Vector3.Distance(arm.position, fore.position), 0.045f * scale));
                if (fore != null && hand != null) colliders.Add(Capsule(side.ToLowerInvariant() + "_forearm", side + "ForeArm", Vector3.Distance(fore.position, hand.position), 0.04f * scale));
            }

            var accessories = new JArray();
            foreach (var accessory in recipe.Accessories)
            {
                var go = FindAccessory(runtime, accessory.Id);
                var entry = new JObject { ["id"] = accessory.Id, ["socket"] = accessory.Socket, ["attached"] = go != null, ["settings"] = accessory.Physics ?? new JObject() };
                if (go != null)
                {
                    var bounds = Bounds(go);
                    var volume = bounds.size.x * bounds.size.y * bounds.size.z;
                    var mass = (float?)accessory.Physics?["mass_kg"];
                    entry["bone"] = go.transform.parent != null ? go.transform.parent.name : null;
                    entry["collider"] = new JObject { ["shape"] = "box", ["size_m"] = Vec(bounds.size), ["centre_m"] = Vec(bounds.center), ["local_centre_m"] = Vec(go.transform.InverseTransformPoint(bounds.center)) };
                    entry["mass_kg"] = Math.Round(mass ?? volume * DefaultAccessoryDensityKgM3, 3);
                    entry["mass_source"] = mass != null ? "recipe.accessories[].physics.mass_kg" : $"estimated from the bounding box at {DefaultAccessoryDensityKgM3} kg/m3";
                    entry["hang"] = accessory.Socket != null && (accessory.Socket.StartsWith("shoulder") || accessory.Socket.StartsWith("hand")) ? "pendulum" : "fixed";
                }
                accessories.Add(entry);
            }

            var garments = new JArray();
            foreach (var garment in recipe.Wardrobe)
            {
                garments.Add(new JObject
                {
                    ["slot"] = garment.Slot, ["catalog_id"] = garment.CatalogId, ["deformation"] = garment.Deformation,
                    ["simulated_cloth"] = garment.Deformation == "cloth" || garment.Deformation == "pinned_cloth" || garment.Deformation == "skinned_with_secondary_cloth",
                    ["pinned_regions"] = garment.Deformation == "pinned_cloth" ? "see settings.clothing.pin" : null,
                });
            }

            var doc = new JObject
            {
                ["schema"] = "promodeler-physics/1.0",
                ["recipe"] = recipe.Id,
                ["settings"] = recipe.Physics ?? new JObject(),
                ["rig"] = new JObject
                {
                    ["rest_pose"] = recipe.Animation.RestPose,
                    ["limits_deg"] = JObject.FromObject(recipe.Animation.LimitsDeg.ToDictionary(kv => kv.Key, kv => kv.Value)),
                    ["root_scale"] = report.Resolved?.RootScale ?? 1f,
                },
                ["body_colliders"] = colliders,
                ["accessories"] = accessories,
                ["garments"] = garments,
                ["measured_m"] = new JObject { ["barefoot_height"] = height },
                ["note"] = "Runtime physics is not simulated by the batch build (settings.common.execution); this file carries the set-up for the engine.",
            };
            var path = Path.Combine(outDir, "physics.json");
            File.WriteAllText(path, doc.ToString(Newtonsoft.Json.Formatting.Indented));
            return path;
        }

        static JObject Capsule(string id, string bone, float length, float radius)
        {
            return new JObject { ["landmark"] = id, ["bone"] = bone, ["shape"] = "capsule", ["radius_m"] = Math.Round(radius, 4), ["length_m"] = Math.Round(length, 4), ["note"] = "along the bone; radius is a race-typical estimate" };
        }

        static GameObject FindAccessory(UMACharacterRuntime runtime, string id)
        {
            foreach (var t in runtime.Root.GetComponentsInChildren<Transform>(true))
                if (t.name == "accessory:" + id || t.name == "accessory:" + id.Replace(':', '_')) return t.gameObject;
            return null;
        }

        static Bounds Bounds(GameObject go)
        {
            var renderers = go.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0) return new Bounds(go.transform.position, Vector3.zero);
            var bounds = renderers[0].bounds;
            foreach (var r in renderers.Skip(1)) bounds.Encapsulate(r.bounds);
            return bounds;
        }

        static JArray Vec(Vector3 v) => new JArray(Math.Round(v.x, 4), Math.Round(v.y, 4), Math.Round(v.z, 4));
    }
}
