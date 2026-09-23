// Exports the neutral body of a UMA race (all DNA at 0.5, no wardrobe, rest pose) as a JSON profile the promodeler
// garment generators build against: torso outlines every 2 cm, arm cross-sections along each arm, key bone positions.
// A UMA slot is authored on the race's neutral body and follows the skeleton afterwards, so garments are cut for
// this body, not for a particular character (docs/03 chapter 12, 18.8).
//
//   Unity -batchmode -projectPath <project> -executeMethod ProModeler.Editor.RaceProfileExporter.Export
//         -race human_female -out <path/to/profile.json>

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using ProModeler.Measure;
using ProModeler.Recipe;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class RaceProfileExporter
    {
        static readonly string[] ProfileBones =
        {
            "Hips", "Spine", "Spine1", "Neck", "Head", "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
            "RightShoulder", "RightArm", "RightForeArm", "RightHand", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
        };

        public static void Export()
        {
            var code = 1;
            try
            {
                var args = CharacterBatchBuilder.Args.Parse(Environment.GetCommandLineArgs());
                var race = args.Get("-race") ?? "human_female";
                var outPath = args.Get("-out") ?? Path.Combine(Directory.GetCurrentDirectory(), $"race_profile_{race}.json");
                var profile = Profile(race);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
                File.WriteAllText(outPath, profile.ToString(Newtonsoft.Json.Formatting.Indented));
                Debug.Log($"[ProModeler] race profile written: {outPath}");
                code = 0;
            }
            catch (Exception exc)
            {
                Debug.LogException(exc);
            }
            finally
            {
                EditorApplication.Exit(code);
            }
        }

        /// <summary>The neutral body of a race as a UMACharacterRuntime (caller disposes).</summary>
        public static UMACharacterRuntime NeutralBody(string race)
        {
            EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            var recipe = new CharacterRecipe { Id = $"neutral-{race}", Name = $"neutral {race}" };
            recipe.Base.Race = race;
            var runtime = new UMACharacterRuntime();
            runtime.Create(recipe, null, (c, m) => Debug.LogWarning($"[ProModeler] {c}: {m}"));
            if (!runtime.Rebuild(120f)) throw new RecipeException("uma.build", $"UMA did not produce the neutral {race} body");
            return runtime;
        }

        public static JObject Profile(string race)
        {
            var runtime = NeutralBody(race);
            try
            {
                var body = runtime.BodyRenderer;
                var sample = BodyMeasurer.SampleBody(body);
                var floor = sample.Floor;
                var height = sample.Height;
                var profile = new JObject
                {
                    ["schema"] = "promodeler-race-profile/1.0",
                    ["race"] = race,
                    ["uma_race"] = runtime.RaceName,
                    ["pose"] = "rest pose (UMA 3 A-pose, arms about 45 degrees down), left arm toward -X, character faces +Z, Unity left-handed metres",
                    ["floor"] = floor,
                    ["height"] = height,
                    ["vertices"] = sample.Vertices.Length,
                };
                var bones = new JObject();
                foreach (var name in ProfileBones)
                {
                    var bone = runtime.Bone(name);
                    if (bone != null) bones[name] = Vec(bone.position);
                }
                profile["bones"] = bones;

                // Torso outlines: arm-free slices from the hip to the top of the neck, as convex hulls (x, z).
                var neck = runtime.Bone("Neck");
                var head = runtime.Bone("Head");
                var top = head != null ? head.position.y : floor + 0.88f * height;
                var torso = new JArray();
                for (var y = floor + 0.42f * height; y < top; y += 0.02f)
                {
                    var points = BodyMeasurer.SlicePoints(sample, y, 0.4f, includeArms: false);
                    if (points.Count < 6) continue;
                    var hull = BodyMeasurer.ConvexHull(points);
                    torso.Add(new JObject { ["y"] = y, ["points"] = Ring(hull) });
                }
                profile["torso_slices"] = torso;
                profile["neck_y"] = neck != null ? neck.position.y : top;

                // Arm cross-sections: planes perpendicular to the straight shoulder-to-wrist axis (UMA 3 rests in an A-pose,
                // the arms slope about 45 degrees), arm vertices only. Points are (a, b) in the plane: a along the in-plane
                // perpendicular e1 = (cos angle_z, sin angle_z, 0), b along +Z; a LoftSection rotated by angle_z about Z
                // maps its local (u, 0, -v) onto (a, b) = (u, -v).
                var arms = new JObject();
                foreach (var side in new[] { "Left", "Right" })
                {
                    var upper = runtime.Bone(side + "Arm");
                    var fore = runtime.Bone(side + "ForeArm");
                    var hand = runtime.Bone(side + "Hand");
                    if (upper == null || hand == null) continue;
                    var axis = hand.position - upper.position;
                    var length = axis.magnitude;
                    var dir = new Vector3(axis.x, axis.y, 0f).normalized;   // the z slope of the rest pose is negligible; keep sections upright in Z
                    var angleZ = Mathf.Atan2(-dir.x, dir.y);
                    var e1 = new Vector3(Mathf.Cos(angleZ), Mathf.Sin(angleZ), 0f);
                    var slices = new JArray();
                    for (var t = 0f; t < length - 0.02f; t += 0.03f)
                    {
                        var centre = upper.position + dir * t;
                        var points = ArmSlice(sample, centre, dir, e1, upper.position.x < 0f);
                        if (points.Count < 6) continue;
                        var hull = BodyMeasurer.ConvexHull(points);
                        slices.Add(new JObject { ["t"] = t, ["center"] = Vec(centre), ["points"] = Ring(hull) });
                    }
                    arms[side.ToLowerInvariant()] = new JObject
                    {
                        ["shoulder"] = Vec(upper.position), ["elbow"] = fore != null ? Vec(fore.position) : null, ["wrist"] = Vec(hand.position),
                        ["dir"] = Vec(dir), ["angle_z"] = angleZ, ["length"] = length, ["slices"] = slices,
                    };
                }
                profile["arms"] = arms;
                return profile;
            }
            finally
            {
                runtime.Dispose();
            }
        }

        /// <summary>Points where arm edges cross the plane through <paramref name="centre"/> with normal <paramref name="dir"/>,
        /// as (a, b) = (along e1, along +Z); only vertices on the arm's side of the body count.</summary>
        static List<Vector2> ArmSlice(BodyMeasurer.Sample sample, Vector3 centre, Vector3 dir, Vector3 e1, bool negativeSide)
        {
            var points = new List<Vector2>();
            foreach (var edge in sample.AllEdges)
            {
                if (!sample.ArmVertex[edge[0]] || !sample.ArmVertex[edge[1]]) continue;
                var a = sample.Vertices[edge[0]];
                var b = sample.Vertices[edge[1]];
                if (negativeSide ? (a.x > 0f || b.x > 0f) : (a.x < 0f || b.x < 0f)) continue;
                var da = Vector3.Dot(a - centre, dir);
                var db = Vector3.Dot(b - centre, dir);
                if (da * db >= 0f) continue;
                var t = da / (da - db);
                var p = a + t * (b - a) - centre;
                if (p.magnitude > 0.2f) continue;   // the plane also cuts the hand or the torso far from the axis
                points.Add(new Vector2(Vector3.Dot(p, e1), p.z));
            }
            return points;
        }

        static JArray Vec(Vector3 v) => new JArray(v.x, v.y, v.z);

        static JArray Ring(List<Vector2> hull)
        {
            var ring = new JArray();
            foreach (var p in hull) ring.Add(new JArray(p.x, p.y));
            return ring;
        }
    }
}
