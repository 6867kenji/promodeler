// Attach promodeler-built accessories (GLB from the Blender pipeline, listed in assets.json by the bridge) to the
// character's sockets. Sockets are recipe vocabulary (hand_r, shoulder_l, back, face ...); the table below maps them to
// UMA 3 bone names and default offsets. The GLB's `promodeler_socket` extras (grip point, orientation) decide where the
// object is held and whether it hangs with world up or follows the bone.

using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Measure;
using ProModeler.Recipe;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class AccessoryResolver
    {
        public const string ImportFolder = "Assets/ProModeler/Generated/Accessories";

        class Socket
        {
            public string Bone;
            public Vector3 Offset;          // metres, in the bone's local axes scaled to world (applied in world space after bone rotation)
            public Socket(string bone, Vector3 offset) { Bone = bone; Offset = offset; }
        }

        static readonly Dictionary<string, Socket> Sockets = new Dictionary<string, Socket>
        {
            { "hand_r", new Socket("RightHand", new Vector3(0f, -0.03f, 0f)) },
            { "hand_l", new Socket("LeftHand", new Vector3(0f, -0.03f, 0f)) },
            { "wrist_r", new Socket("RightHand", new Vector3(0.03f, 0f, 0f)) },
            { "wrist_l", new Socket("LeftHand", new Vector3(-0.03f, 0f, 0f)) },
            { "shoulder_r", new Socket("RightShoulder", new Vector3(0.10f, 0.04f, 0f)) },
            { "shoulder_l", new Socket("LeftShoulder", new Vector3(-0.10f, 0.04f, 0f)) },
            { "back", new Socket("Spine1", new Vector3(0f, 0.05f, -0.13f)) },
            { "waist", new Socket("Hips", new Vector3(0f, 0.08f, 0f)) },        // overridden by WaistAnchor: the centre of the waist slice
            { "neck", new Socket("Neck", new Vector3(0f, -0.02f, 0.08f)) },       // overridden by NeckAnchor: the collar front
            { "head", new Socket("Head", new Vector3(0f, 0.12f, 0f)) },
            { "face", new Socket("Head", new Vector3(0f, 0.065f, 0.105f)) },
            { "chest", new Socket("Spine1", new Vector3(-0.08f, 0.10f, 0.15f)) },   // outside a shirt on the wearer's left
        };

        /// <summary>Attach the recipe's accessories and the wardrobe garments the catalog realizes as promodeler props
        /// (assets.json "garments", keyed by slot). Garment props report as "garment:&lt;slot&gt;".</summary>
        public static List<AccessoryEntry> Attach(UMACharacterRuntime runtime, CharacterRecipe recipe, JObject assets, BuildReport report)
        {
            var entries = new List<AccessoryEntry>();
            var table = assets?["accessories"] as JObject;
            foreach (var accessory in recipe.Accessories)
                entries.Add(AttachOne(runtime, recipe, report, accessory.Id, accessory.Source?.Path, accessory.Socket, table?[accessory.Id] as JObject));
            var garments = assets?["garments"] as JObject;
            if (garments != null)
            {
                foreach (var property in garments.Properties())
                {
                    var info = property.Value as JObject;
                    var socket = (string)info?["socket"]?["socket"];
                    entries.Add(AttachOne(runtime, recipe, report, "garment:" + property.Name, (string)info?["catalog_id"], socket, info));
                }
            }
            return entries;
        }

        static AccessoryEntry AttachOne(UMACharacterRuntime runtime, CharacterRecipe recipe, BuildReport report, string id, string source, string socketName, JObject info)
        {
            var entry = new AccessoryEntry { Id = id, Source = source, Socket = socketName, Attached = false };
            var glb = (string)info?["glb"];
            if (string.IsNullOrEmpty(glb) || !File.Exists(glb))
            {
                report.Warn("accessory.missingAsset", $"{id}: no built GLB ({(string)info?["missing"] ?? (string)info?["error"]?["message"] ?? "not built"})");
                return entry;
            }
            if (string.IsNullOrEmpty(socketName) || !Sockets.TryGetValue(socketName, out var socket))
            {
                report.Warn("accessory.socket", $"{id}: socket {socketName ?? "null"} is unknown; not attached");
                return entry;
            }
            var bone = runtime.Bone(socket.Bone);
            if (bone == null)
            {
                report.Warn("accessory.bone", $"{id}: bone {socket.Bone} not found on {runtime.RaceName}; not attached");
                return entry;
            }
            try
            {
                var instance = Import(glb, id.Replace(':', '_'), report);
                if (instance == null) return entry;
                Vector3? anchorOverride = null;
                Quaternion? rotationOverride = null;
                if (socketName == "face") anchorOverride = EyeAnchor(runtime);
                else if (socketName == "neck")
                {
                    anchorOverride = NeckAnchor(runtime);
                    if (anchorOverride.HasValue) rotationOverride = HangOnChest(runtime, anchorOverride.Value, info?["socket"] as JObject);
                }
                else if (socketName == "waist") anchorOverride = WaistAnchor(runtime, recipe);
                Place(instance, bone, socket, info?["socket"] as JObject, anchorOverride, rotationOverride);
                entry.Attached = true;
            }
            catch (Exception exc)
            {
                report.Warn("accessory.attach", $"{id}: {exc.GetType().Name}: {exc.Message}");
            }
            return entry;
        }

        /// <summary>The dressed body's outline at a height: the (x, z) points of the merged body+clothes mesh cut there.</summary>
        static List<Vector2> DressedSlice(UMACharacterRuntime runtime, float y, out BodyMeasurer.Sample sample)
        {
            sample = null;
            if (runtime.BodyRenderer == null) return null;
            sample = BodyMeasurer.SampleBody(runtime.BodyRenderer);
            return BodyMeasurer.SlicePoints(sample, y, 0.4f, includeArms: false);
        }

        /// <summary>A necktie's knot sits at the collar front: the Neck bone's height, in front of the dressed body's outline there.</summary>
        static Vector3? NeckAnchor(UMACharacterRuntime runtime)
        {
            var neck = runtime.Bone("Neck");
            if (neck == null) return null;
            var y = neck.position.y - 0.015f;
            var slice = DressedSlice(runtime, y, out _);
            if (slice == null || slice.Count < 3) return null;
            var front = float.MinValue;
            foreach (var p in slice) if (Mathf.Abs(p.x) < 0.04f && p.y > front) front = p.y;   // the outline directly in front of the throat
            if (front == float.MinValue) return null;
            return new Vector3(0f, y, front + 0.004f);
        }

        /// <summary>A tie hangs from the collar and lies on the chest, which stands further forward than the throat: tilt
        /// it so its tip reaches the outermost front of the dressed body along its length.</summary>
        static Quaternion? HangOnChest(UMACharacterRuntime runtime, Vector3 anchor, JObject socketExtras)
        {
            var grip = socketExtras?["grip_offset_m"] as JArray;
            var length = grip != null && grip.Count == 3 ? (float)grip[1] : 0.45f;
            if (length < 0.1f || runtime.BodyRenderer == null) return null;
            // The tangent from the collar over the chest (upper half of the tie): the blade rests on the chest and, on a
            // puffy jacket, disappears into the belly rather than floating in front of the chest.
            var sample = BodyMeasurer.SampleBody(runtime.BodyRenderer);
            var tilt = 0f;
            for (var i = 1; i <= 4; i++)
            {
                var drop = length * 0.5f * i / 4f;
                var slice = BodyMeasurer.SlicePoints(sample, anchor.y - drop, 0.4f, includeArms: false);
                var front = float.MinValue;
                foreach (var p in slice) if (Mathf.Abs(p.x) < 0.05f && p.y > front) front = p.y;
                if (front == float.MinValue) continue;
                tilt = Mathf.Max(tilt, Mathf.Atan2(front + 0.008f - anchor.z, drop) * Mathf.Rad2Deg);
            }
            var rotation = Quaternion.AngleAxis(tilt, Vector3.right);
            if ((rotation * Vector3.down).z < 0f) rotation = Quaternion.AngleAxis(-tilt, Vector3.right);   // the tip must swing forward (+Z)
            return rotation;
        }

        /// <summary>A belt ring is centred on the recipe's waist plane (the cross-section height as a fraction of the
        /// barefoot height, so it follows the solved body) at the centre of the dressed outline there.</summary>
        static Vector3? WaistAnchor(UMACharacterRuntime runtime, CharacterRecipe recipe)
        {
            var waist = recipe.Body.MeasurementsM.CrossSections.Find(s => s.Landmark == "waist");
            var fraction = waist != null && recipe.Body.MeasurementsM.BarefootHeight > 0f ? waist.Height / recipe.Body.MeasurementsM.BarefootHeight : 0.63f;
            if (runtime.BodyRenderer == null) return null;
            var sample = BodyMeasurer.SampleBody(runtime.BodyRenderer);
            var y = sample.Floor + fraction * sample.Height;
            var slice = BodyMeasurer.SlicePoints(sample, y, 0.4f, includeArms: false);
            if (slice.Count < 3) return new Vector3(0f, y, 0f);
            float zMin = float.MaxValue, zMax = float.MinValue;
            foreach (var p in slice) { if (p.y < zMin) zMin = p.y; if (p.y > zMax) zMax = p.y; }
            return new Vector3(0f, y, (zMin + zMax) * 0.5f);
        }

        static GameObject Import(string glbPath, string id, BuildReport report)
        {
            Directory.CreateDirectory(ImportFolder);
            var target = $"{ImportFolder}/{id}.glb";
            File.Copy(glbPath, target, true);
            AssetDatabase.ImportAsset(target, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(target);
            if (prefab == null)
            {
                report.Warn("accessory.import", $"{id}: UnityGLTF did not import {target} as a GameObject");
                return null;
            }
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            instance.name = $"accessory:{id}";
            return instance;
        }

        /// <summary>Glasses sit on the nose between the eyes: the eye bones give that point directly when the race has them.</summary>
        static Vector3? EyeAnchor(UMACharacterRuntime runtime)
        {
            var left = runtime.Bone("LeftEye");
            var right = runtime.Bone("RightEye");
            if (left == null || right == null) return null;
            var between = (left.position + right.position) * 0.5f;
            return between + new Vector3(0f, -0.005f, 0.028f);   // just in front of the eyeballs (the character faces +Z)
        }

        static void Place(GameObject instance, Transform bone, Socket socket, JObject socketExtras, Vector3? anchorOverride, Quaternion? rotationOverride = null)
        {
            var grip = Vector3.zero;
            var orientation = "world_up";
            if (socketExtras != null)
            {
                var g = socketExtras["grip_offset_m"] as JArray;
                if (g != null && g.Count == 3) grip = new Vector3((float)g[0], (float)g[1], (float)g[2]);
                orientation = (string)socketExtras["orientation"] ?? orientation;
            }
            // Blender/glTF authoring space is Y up with +Z toward the viewer; UnityGLTF flips X on import, so the grip's
            // X mirrors while Y and Z carry over.
            var gripUnity = new Vector3(-grip.x, grip.y, grip.z);
            instance.transform.SetParent(bone, false);
            // UMA scales bones for its DNA (lowerWeight scales Hips, height the root); the prop keeps its metric size.
            var lossy = bone.lossyScale;
            instance.transform.localScale = new Vector3(1f / Mathf.Max(lossy.x, 1e-4f), 1f / Mathf.Max(lossy.y, 1e-4f), 1f / Mathf.Max(lossy.z, 1e-4f));
            // Both orientations place the object world-aligned in the rest pose (UMA bone axes run along the bone, so
            // copying bone.rotation turned glasses 90 degrees); "follow_bone" differs only in that the object then moves
            // with the bone when animated, which parenting already provides.
            var rotation = rotationOverride ?? Quaternion.identity;
            var anchor = anchorOverride ?? (bone.position + bone.rotation * socket.Offset);
            instance.transform.rotation = rotation;
            instance.transform.position = anchor - rotation * gripUnity;
            var bounds = new Bounds(instance.transform.position, Vector3.zero);
            var first = true;
            foreach (var r in instance.GetComponentsInChildren<Renderer>()) { if (first) { bounds = r.bounds; first = false; } else bounds.Encapsulate(r.bounds); }
            var children = string.Join(", ", System.Linq.Enumerable.Select(instance.GetComponentsInChildren<Transform>(), t => $"{t.name}@{t.localEulerAngles}"));
            Debug.Log($"[ProModeler] accessory {instance.name}: bounds size {bounds.size:F3} centre {bounds.center:F3}; bone {bone.name} lossyScale {lossy:F3}; nodes {children}");
        }
    }
}
