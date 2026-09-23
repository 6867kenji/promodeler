// Metric measurements of a skinned body, with the same definitions as promodeler.human.mhr.MHRModel.measure so the
// Python reference fit, the Unity build and tools/blueprint_check compare like with like.
//
//  barefoot_height   max y - min y of the body mesh (no shoes)
//  inseam            lowest vertex of the midline (|x| < 2 cm) between 40 % and 65 % of the height, above the floor
//  foot_length       z extent of the vertices below floor + 4 cm
//  head_height       top of the head - Head bone position + 3 cm
//  shoulder_width    x extent of the arm-free torso slice at the shoulders landmark (acromion width, not joint distance)
//  <landmark>        perimeter of the arm-free torso outline where the horizontal plane at that landmark cuts the mesh
//  <landmark>_width / _depth   x and z extents of the same slice
//
// Landmarks are fractions of the measured height; the recipe's cross sections give them (height / barefoot_height).
// Vertices dominated by arm or hand bones are excluded from torso slices, so A-pose arms never join a circumference.

using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;
using ProModeler.Recipe;

namespace ProModeler.Measure
{
    public class BodyMeasurer
    {
        public static readonly Regex ArmBonePattern = new Regex("(Arm|Hand|Thumb|Index|Middle|Ring|Pinky|Finger)", RegexOptions.IgnoreCase);
        public const float TorsoHalfWidthLimit = 0.3f;
        public const float AcromionFraction = 0.818f;  // adult acromial height / stature when the recipe gives no shoulders section
        public const float MeasurementArmDropDegrees = 55f;  // T-pose arms lowered to the blueprint A-pose (35 degrees from the torso) while measuring

        public static bool DebugLog = false;

        /// <summary>Rotate an upper arm about world Z so the hand moves down, whichever side of the body the arm extends to.</summary>
        static void LowerArm(Transform upperArm, string handName)
        {
            if (upperArm == null) return;
            var hand = FindChild(upperArm, handName);
            var direction = hand != null ? (hand.position - upperArm.position) : (upperArm.position.x < 0f ? Vector3.left : Vector3.right);
            // Rotating a +X arm by a negative angle about +Z (and a -X arm by a positive one) lowers the hand toward -Y.
            var angle = direction.x >= 0f ? -MeasurementArmDropDegrees : MeasurementArmDropDegrees;
            upperArm.Rotate(Vector3.forward, angle, Space.World);
        }

        static Transform FindChild(Transform root, string name)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true)) if (t.name == name) return t;
            return null;
        }

        static int CountTrue(bool[] flags)
        {
            var n = 0;
            foreach (var f in flags) if (f) n++;
            return n;
        }

        /// <summary>Landmark name -> fraction of the standing height.</summary>
        public readonly Dictionary<string, float> Landmarks = new Dictionary<string, float>();

        public static BodyMeasurer ForRecipe(CharacterRecipe recipe)
        {
            var measurer = new BodyMeasurer();
            var height = recipe.Body.MeasurementsM.BarefootHeight;
            measurer.Landmarks["shoulders"] = AcromionFraction;
            foreach (var section in recipe.Body.MeasurementsM.CrossSections)
                measurer.Landmarks[section.Landmark] = section.Height / height;
            // Circumferences without a section still need a plane: use the 05-woman planes as MHR does.
            var defaults = new Dictionary<string, float> { { "hip", 0.95f / 1.6f }, { "waist", 1.06f / 1.6f }, { "underbust", 1.18f / 1.6f }, { "bust", 1.25f / 1.6f }, { "chest", 1.25f / 1.6f } };
            foreach (var name in recipe.Body.MeasurementsM.Circumferences.Keys)
                if (!measurer.Landmarks.ContainsKey(name) && defaults.ContainsKey(name)) measurer.Landmarks[name] = defaults[name];
            return measurer;
        }

        public class Sample
        {
            public Vector3[] Vertices;        // world space, metres
            public bool[] ArmVertex;
            public List<int[]> TorsoEdges;    // vertex index pairs with neither end on an arm
            public List<int[]> AllEdges;      // every unique edge
            public float Floor;
            public float Height;
        }

        public static Sample SampleBody(SkinnedMeshRenderer body)
        {
            var baked = new Mesh();
            // BakeMesh skins with the bones' world matrices, so ancestor scale (the resolver's root scale) is already in the
            // result; only the renderer's position and rotation remain to be applied. Measured: applying localToWorldMatrix
            // here doubled a 0.5 % root scale.
            body.BakeMesh(baked, false);
            var toWorld = Matrix4x4.TRS(body.transform.position, body.transform.rotation, Vector3.one);
            var local = baked.vertices;
            var vertices = new Vector3[local.Length];
            for (var i = 0; i < local.Length; i++) vertices[i] = toWorld.MultiplyPoint3x4(local[i]);

            var arm = new bool[vertices.Length];
            var shared = body.sharedMesh;
            var bones = body.bones;
            var weights = shared != null && shared.vertexCount == vertices.Length ? shared.boneWeights : null;
            if (weights != null && weights.Length == vertices.Length && bones != null)
            {
                var armBone = new bool[bones.Length];
                for (var b = 0; b < bones.Length; b++) armBone[b] = bones[b] != null && ArmBonePattern.IsMatch(bones[b].name);
                for (var i = 0; i < vertices.Length; i++)
                {
                    var w = weights[i];
                    var dominant = w.boneIndex0;
                    var best = w.weight0;
                    if (w.weight1 > best) { best = w.weight1; dominant = w.boneIndex1; }
                    if (w.weight2 > best) { best = w.weight2; dominant = w.boneIndex2; }
                    if (w.weight3 > best) { dominant = w.boneIndex3; }
                    arm[i] = dominant >= 0 && dominant < armBone.Length && armBone[dominant];
                }
            }

            var edges = new HashSet<long>();
            var torso = new List<int[]>();
            var all = new List<int[]>();
            var triangles = shared != null && shared.vertexCount == vertices.Length ? shared.triangles : baked.triangles;
            for (var t = 0; t + 2 < triangles.Length; t += 3)
            {
                AddEdge(edges, torso, all, arm, triangles[t], triangles[t + 1]);
                AddEdge(edges, torso, all, arm, triangles[t + 1], triangles[t + 2]);
                AddEdge(edges, torso, all, arm, triangles[t + 2], triangles[t]);
            }

            float minY = float.MaxValue, maxY = float.MinValue;
            foreach (var v in vertices) { if (v.y < minY) minY = v.y; if (v.y > maxY) maxY = v.y; }
            UnityEngine.Object.DestroyImmediate(baked);
            return new Sample { Vertices = vertices, ArmVertex = arm, TorsoEdges = torso, AllEdges = all, Floor = minY, Height = maxY - minY };
        }

        static void AddEdge(HashSet<long> seen, List<int[]> torso, List<int[]> all, bool[] arm, int a, int b)
        {
            if (a == b) return;
            var lo = Math.Min(a, b);
            var hi = Math.Max(a, b);
            var key = ((long)lo << 32) | (uint)hi;
            if (!seen.Add(key)) return;
            all.Add(new[] { lo, hi });
            if (!arm[lo] && !arm[hi]) torso.Add(new[] { lo, hi });
        }

        public static List<Vector2> SlicePoints(Sample sample, float y, float xLimit = TorsoHalfWidthLimit, bool includeArms = false)
        {
            var points = new List<Vector2>();
            foreach (var edge in includeArms ? sample.AllEdges : sample.TorsoEdges)
            {
                var a = sample.Vertices[edge[0]];
                var b = sample.Vertices[edge[1]];
                if ((a.y - y) * (b.y - y) >= 0f) continue;
                var t = (y - a.y) / (b.y - a.y);
                var p = a + t * (b - a);
                if (Mathf.Abs(p.x) < xLimit) points.Add(new Vector2(p.x, p.z));
            }
            return points;
        }

        /// <summary>Tape-measure circumference: the perimeter of the convex hull of the slice outline. A tape spans
        /// concavities (armpit folds, the cleft between the breasts) instead of following them, and the hull is smooth
        /// in the parameters, which an angular-sorted polyline of a non-convex outline is not.</summary>
        public static float Perimeter(List<Vector2> points)
        {
            if (points.Count < 6) return 0f;
            var hull = ConvexHull(points);
            var length = 0f;
            for (var i = 0; i < hull.Count; i++) length += Vector2.Distance(hull[i], hull[(i + 1) % hull.Count]);
            return length;
        }

        /// <summary>Andrew's monotone chain; returns the hull counter-clockwise.</summary>
        public static List<Vector2> ConvexHull(List<Vector2> points)
        {
            var sorted = new List<Vector2>(points);
            sorted.Sort((a, b) => a.x != b.x ? a.x.CompareTo(b.x) : a.y.CompareTo(b.y));
            var hull = new List<Vector2>(sorted.Count * 2);
            foreach (var p in sorted)
            {
                while (hull.Count >= 2 && Cross(hull[hull.Count - 2], hull[hull.Count - 1], p) <= 0f) hull.RemoveAt(hull.Count - 1);
                hull.Add(p);
            }
            var lower = hull.Count + 1;
            for (var i = sorted.Count - 2; i >= 0; i--)
            {
                var p = sorted[i];
                while (hull.Count >= lower && Cross(hull[hull.Count - 2], hull[hull.Count - 1], p) <= 0f) hull.RemoveAt(hull.Count - 1);
                hull.Add(p);
            }
            hull.RemoveAt(hull.Count - 1);
            return hull;
        }

        static float Cross(Vector2 o, Vector2 a, Vector2 b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);

        public static Vector2 Extents(List<Vector2> points)
        {
            if (points.Count < 6) return Vector2.zero;
            float minX = float.MaxValue, maxX = float.MinValue, minZ = float.MaxValue, maxZ = float.MinValue;
            foreach (var p in points)
            {
                if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
                if (p.y < minZ) minZ = p.y; if (p.y > maxZ) maxZ = p.y;
            }
            return new Vector2(maxX - minX, maxZ - minZ);
        }

        /// <summary>All measurements in metres, keyed like the recipe's body.measurements_m (plus joint_shoulder_width).
        /// The upper arms are rotated down into an A-pose for the duration of the sampling and restored afterwards.</summary>
        public Dictionary<string, float> Measure(SkinnedMeshRenderer body, Transform headBone, Transform leftUpperArm, Transform rightUpperArm)
        {
            var savedLeft = leftUpperArm != null ? leftUpperArm.localRotation : Quaternion.identity;
            var savedRight = rightUpperArm != null ? rightUpperArm.localRotation : Quaternion.identity;
            Sample sample;
            try
            {
                // T-pose arms point along +X (left) and -X (right); rotating about world Z lowers them toward -Y.
                var hand = leftUpperArm != null ? FindChild(leftUpperArm, "LeftHand") : null;
                var before = hand != null ? hand.position : Vector3.zero;
                LowerArm(leftUpperArm, "LeftHand");
                LowerArm(rightUpperArm, "RightHand");
                sample = SampleBody(body);
                if (DebugLog && leftUpperArm != null)
                    Debug.Log($"[ProModeler] measure: arm {leftUpperArm.name} parent {leftUpperArm.parent?.name} pos {leftUpperArm.position} lossyScale {leftUpperArm.lossyScale} " +
                              $"hand {(hand != null ? hand.position.ToString("F3") : "n/a")} (was {before:F3}); floor {sample.Floor:F3} height {sample.Height:F3} " +
                              $"renderer {body.name} bones {body.bones?.Length} verts {sample.Vertices.Length} torsoEdges {sample.TorsoEdges.Count} armVerts {CountTrue(sample.ArmVertex)}");
            }
            finally
            {
                if (leftUpperArm != null) leftUpperArm.localRotation = savedLeft;
                if (rightUpperArm != null) rightUpperArm.localRotation = savedRight;
            }
            var out_ = new Dictionary<string, float> { { "barefoot_height", sample.Height } };
            var floor = sample.Floor;
            var height = sample.Height;

            float footMin = float.MaxValue, footMax = float.MinValue;
            foreach (var v in sample.Vertices)
                if (v.y < floor + 0.04f) { if (v.z < footMin) footMin = v.z; if (v.z > footMax) footMax = v.z; }
            // Inseam: the crotch is the lowest point of the body's midline between 40 and 65 percent of the height. The
            // midline is cut from mesh edges crossing the x = 0 plane, so it moves continuously with the parameters
            // (picking the lowest vertex within |x| < 2 cm flipped by 11 mm between an inner-thigh and a crotch vertex
            // on a 0.03 percent root scale).
            var inseam = float.MaxValue;
            float lo = floor + 0.4f * height, hi = floor + 0.65f * height;
            foreach (var edge in sample.AllEdges)
            {
                var a = sample.Vertices[edge[0]];
                var b = sample.Vertices[edge[1]];
                if (a.x * b.x > 0f) continue;
                var t = Mathf.Abs(b.x - a.x) < 1e-9f ? 0f : -a.x / (b.x - a.x);
                var y = a.y + t * (b.y - a.y);
                if (y > lo && y < hi && y < inseam) inseam = y;
            }
            if (inseam < float.MaxValue) out_["inseam"] = inseam - floor;
            if (footMax > footMin) out_["foot_length"] = footMax - footMin;
            if (headBone != null) out_["head_height"] = (floor + height) - headBone.position.y + 0.03f;
            if (leftUpperArm != null && rightUpperArm != null) out_["joint_shoulder_width"] = Vector3.Distance(leftUpperArm.position, rightUpperArm.position);

            foreach (var landmark in Landmarks)
            {
                var points = SlicePoints(sample, floor + landmark.Value * height);
                var extents = Extents(points);
                out_[landmark.Key + "_width"] = extents.x;
                out_[landmark.Key + "_depth"] = extents.y;
                if (landmark.Key == "shoulders") out_["shoulder_width"] = extents.x;
                else if (landmark.Key != "neck" && landmark.Key != "head") out_[landmark.Key] = Perimeter(points);
            }
            return out_;
        }
    }
}
