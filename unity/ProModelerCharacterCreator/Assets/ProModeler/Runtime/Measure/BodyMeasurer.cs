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
            public float Floor;
            public float Height;
        }

        public static Sample SampleBody(SkinnedMeshRenderer body)
        {
            var baked = new Mesh();
            body.BakeMesh(baked, true);  // local space with the renderer scale applied
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
            var triangles = shared != null && shared.vertexCount == vertices.Length ? shared.triangles : baked.triangles;
            for (var t = 0; t + 2 < triangles.Length; t += 3)
            {
                AddEdge(edges, torso, arm, triangles[t], triangles[t + 1]);
                AddEdge(edges, torso, arm, triangles[t + 1], triangles[t + 2]);
                AddEdge(edges, torso, arm, triangles[t + 2], triangles[t]);
            }

            float minY = float.MaxValue, maxY = float.MinValue;
            foreach (var v in vertices) { if (v.y < minY) minY = v.y; if (v.y > maxY) maxY = v.y; }
            UnityEngine.Object.DestroyImmediate(baked);
            return new Sample { Vertices = vertices, ArmVertex = arm, TorsoEdges = torso, Floor = minY, Height = maxY - minY };
        }

        static void AddEdge(HashSet<long> seen, List<int[]> torso, bool[] arm, int a, int b)
        {
            if (a == b) return;
            var lo = Math.Min(a, b);
            var hi = Math.Max(a, b);
            var key = ((long)lo << 32) | (uint)hi;
            if (!seen.Add(key)) return;
            if (!arm[lo] && !arm[hi]) torso.Add(new[] { lo, hi });
        }

        public static List<Vector2> SlicePoints(Sample sample, float y, float xLimit = TorsoHalfWidthLimit)
        {
            var points = new List<Vector2>();
            foreach (var edge in sample.TorsoEdges)
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

        public static float Perimeter(List<Vector2> points)
        {
            if (points.Count < 6) return 0f;
            var center = Vector2.zero;
            foreach (var p in points) center += p;
            center /= points.Count;
            points.Sort((p, q) => Mathf.Atan2(p.y - center.y, p.x - center.x).CompareTo(Mathf.Atan2(q.y - center.y, q.x - center.x)));
            var length = 0f;
            for (var i = 0; i < points.Count; i++) length += Vector2.Distance(points[i], points[(i + 1) % points.Count]);
            return length;
        }

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

        /// <summary>All measurements in metres, keyed like the recipe's body.measurements_m (plus joint_shoulder_width).</summary>
        public Dictionary<string, float> Measure(SkinnedMeshRenderer body, Transform headBone, Transform leftUpperArm, Transform rightUpperArm)
        {
            var sample = SampleBody(body);
            var out_ = new Dictionary<string, float> { { "barefoot_height", sample.Height } };
            var floor = sample.Floor;
            var height = sample.Height;

            var inseam = float.MaxValue;
            float footMin = float.MaxValue, footMax = float.MinValue;
            foreach (var v in sample.Vertices)
            {
                if (Mathf.Abs(v.x) < 0.02f && v.y > floor + 0.4f * height && v.y < floor + 0.65f * height && v.y < inseam) inseam = v.y;
                if (v.y < floor + 0.04f) { if (v.z < footMin) footMin = v.z; if (v.z > footMax) footMax = v.z; }
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
