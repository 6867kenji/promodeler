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
            { "waist", new Socket("Hips", new Vector3(0.12f, 0f, 0f)) },
            { "head", new Socket("Head", new Vector3(0f, 0.12f, 0f)) },
            { "face", new Socket("Head", new Vector3(0f, 0.065f, 0.105f)) },
            { "chest", new Socket("Spine1", new Vector3(-0.08f, 0.10f, 0.15f)) },   // outside a shirt on the wearer's left
        };

        public static List<AccessoryEntry> Attach(UMACharacterRuntime runtime, CharacterRecipe recipe, JObject assets, BuildReport report)
        {
            var entries = new List<AccessoryEntry>();
            var table = assets?["accessories"] as JObject;
            foreach (var accessory in recipe.Accessories)
            {
                var entry = new AccessoryEntry { Id = accessory.Id, Source = accessory.Source?.Path, Socket = accessory.Socket, Attached = false };
                entries.Add(entry);
                var info = table?[accessory.Id] as JObject;
                var glb = (string)info?["glb"];
                if (string.IsNullOrEmpty(glb) || !File.Exists(glb))
                {
                    report.Warn("accessory.missingAsset", $"{accessory.Id}: no built GLB ({(string)info?["missing"] ?? (string)info?["error"]?["message"] ?? "not built"}); run `promodeler build {accessory.Source?.Path}`");
                    continue;
                }
                if (string.IsNullOrEmpty(accessory.Socket) || !Sockets.TryGetValue(accessory.Socket, out var socket))
                {
                    report.Warn("accessory.socket", $"{accessory.Id}: socket {accessory.Socket ?? "null"} is unknown; not attached");
                    continue;
                }
                var bone = runtime.Bone(socket.Bone);
                if (bone == null)
                {
                    report.Warn("accessory.bone", $"{accessory.Id}: bone {socket.Bone} not found on {runtime.RaceName}; not attached");
                    continue;
                }
                try
                {
                    var instance = Import(glb, accessory.Id, report);
                    if (instance == null) continue;
                    var anchorOverride = accessory.Socket == "face" ? EyeAnchor(runtime) : (Vector3?)null;
                    Place(instance, bone, socket, info?["socket"] as JObject, anchorOverride);
                    entry.Attached = true;
                }
                catch (Exception exc)
                {
                    report.Warn("accessory.attach", $"{accessory.Id}: {exc.GetType().Name}: {exc.Message}");
                }
            }
            return entries;
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

        static void Place(GameObject instance, Transform bone, Socket socket, JObject socketExtras, Vector3? anchorOverride)
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
            // Both orientations place the object world-aligned in the rest pose (UMA bone axes run along the bone, so
            // copying bone.rotation turned glasses 90 degrees); "follow_bone" differs only in that the object then moves
            // with the bone when animated, which parenting already provides.
            var rotation = Quaternion.identity;
            var anchor = anchorOverride ?? (bone.position + bone.rotation * socket.Offset);
            instance.transform.rotation = rotation;
            instance.transform.position = anchor - rotation * gripUnity;
            var bounds = new Bounds(instance.transform.position, Vector3.zero);
            var first = true;
            foreach (var r in instance.GetComponentsInChildren<Renderer>()) { if (first) { bounds = r.bounds; first = false; } else bounds.Encapsulate(r.bounds); }
            var children = string.Join(", ", System.Linq.Enumerable.Select(instance.GetComponentsInChildren<Transform>(), t => $"{t.name}@{t.localEulerAngles}"));
            Debug.Log($"[ProModeler] accessory {instance.name}: bounds size {bounds.size:F3} centre {bounds.center:F3}; nodes {children}");
        }
    }
}
