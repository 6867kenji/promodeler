// Turns a promodeler-built garment GLB into UMA 3 wardrobe content: a SlotDataAsset skinned to the race's neutral
// body by closest-surface weight transfer, an OverlayDataAsset with flat textures, and a UMAWardrobeRecipe in the
// requested wardrobe slot, all registered in the global library. The garment must be authored on the race profile
// (RaceProfileExporter) so it sits on the neutral body in the rest pose; UMA then moves it with the skeleton.
//
// The weight transfer follows UMA's own SceneMeshSlotBuilderWindow (closest triangle on the baked body, barycentric
// blend of that triangle's bone weights, vertices unskinned into bind space), reduced to what a batch run needs.
//
//   Unity -batchmode -projectPath <project> -executeMethod ProModeler.Editor.WardrobeSlotImporter.Import
//         -glb <path> -race human_female -name white_shirt_f -wardrobe-slot TopUnderlayer
//         [-color #FFFFFF] [-material-from-recipe colors_top_Recipe] [-material UMA_Diffuse_Normal_Metallic]
//         -out Assets/ProModeler/Generated/Wardrobe/white_shirt_f -report <path.json>

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using Unity.Collections;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UMA;
using UMA.CharacterSystem;
using ProModeler.Recipe;
using ProModeler.Runtime;
using Debug = UnityEngine.Debug;

namespace ProModeler.Editor
{
    public static class WardrobeSlotImporter
    {
        const int MaxInfluences = 4;
        const float Epsilon = 1e-6f;

        public static void Import()
        {
            var code = 1;
            var report = new JObject { ["ok"] = false };
            var args = CharacterBatchBuilder.Args.Parse(Environment.GetCommandLineArgs());
            var reportPath = args.Get("-report");
            var watch = Stopwatch.StartNew();
            try
            {
                var glb = args.Get("-glb") ?? throw new ArgumentException("-glb <path> is required");
                var race = args.Get("-race") ?? "human_female";
                var name = args.Get("-name") ?? Path.GetFileNameWithoutExtension(glb);
                var wardrobeSlot = args.Get("-wardrobe-slot") ?? "Chest";
                var outFolder = (args.Get("-out") ?? $"Assets/ProModeler/Generated/Wardrobe/{name}").Replace('\\', '/').TrimEnd('/');
                var color = Color.white;
                if (args.Get("-color") != null && !ColorUtility.TryParseHtmlString(args.Get("-color"), out color)) color = Color.white;
                var result = ImportGarment(glb, race, name, wardrobeSlot, outFolder, color, args.Get("-material-from-recipe"), args.Get("-material"), report);
                report["ok"] = result;
                code = result ? 0 : 1;
            }
            catch (Exception exc)
            {
                Debug.LogException(exc);
                report["error"] = new JObject { ["code"] = exc is RecipeException re ? re.Code : "import." + exc.GetType().Name, ["message"] = exc.Message };
            }
            finally
            {
                report["seconds"] = watch.Elapsed.TotalSeconds;
                if (!string.IsNullOrEmpty(reportPath))
                {
                    try
                    {
                        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath)));
                        File.WriteAllText(reportPath, report.ToString(Newtonsoft.Json.Formatting.Indented));
                    }
                    catch (Exception exc) { Debug.LogException(exc); }
                }
                EditorApplication.Exit(code);
            }
        }

        public static bool ImportGarment(string glbPath, string race, string name, string wardrobeSlot, string outFolder, Color color,
                                         string materialFromRecipe, string materialName, JObject report)
        {
            report["race"] = race; report["name"] = name; report["wardrobe_slot"] = wardrobeSlot; report["folder"] = outFolder;
            Directory.CreateDirectory(outFolder);
            AssetDatabase.Refresh();

            // 1. The neutral body of the race: the target surface and skeleton.
            var runtime = RaceProfileExporter.NeutralBody(race);
            try
            {
                var body = runtime.BodyRenderer;
                var target = CaptureTarget(runtime, body);
                report["uma_race"] = runtime.RaceName;
                report["body_vertices"] = body.sharedMesh.vertexCount;

                // 2. The garment mesh from the GLB (UnityGLTF import), in the body renderer's local space.
                var source = LoadGarment(glbPath, name, outFolder, body.transform.worldToLocalMatrix, report);

                // 3. Weights by closest body triangle, then the mesh unskinned into bind space.
                var surface = BuildSurface(target, body);
                var weights = TransferWeights(source.Vertices, surface, target);
                report["fallback_vertices"] = weights.FallbackVertices;
                var slotMesh = BuildSlotMesh(source, target, weights, name);

                // 4. A temporary renderer on the body's skeleton, then the SlotDataAsset from it.
                var tempObject = new GameObject(name + "_slotcapture");
                tempObject.transform.SetParent(body.transform.parent, false);
                tempObject.transform.localPosition = body.transform.localPosition;
                tempObject.transform.localRotation = body.transform.localRotation;
                tempObject.transform.localScale = body.transform.localScale;
                var temp = tempObject.AddComponent<SkinnedMeshRenderer>();
                temp.sharedMesh = slotMesh;
                temp.sharedMaterials = new[] { source.Material };
                temp.bones = target.Bones;
                temp.rootBone = target.RootBone;
                try
                {
                    var slotPath = $"{outFolder}/{name}_slot.asset";
                    var slot = SaveSlot(temp, target, name, slotPath, report);
                    var material = ResolveMaterial(materialFromRecipe, materialName, runtime.RaceName, report);
                    var overlay = SaveOverlay(slot, material, color, outFolder, name, report);
                    var recipe = SaveRecipe(slot, overlay, target.RaceData, wardrobeSlot, outFolder, name, report);
                    AssetDatabase.SaveAssets();
                    AssetDatabase.Refresh();
                    UMAAssetIndexer.Instance.ForceSave();
                    Debug.Log($"[ProModeler] wardrobe slot {slot.slotName}: {slotMesh.vertexCount} vertices, recipe {recipe.name} ({wardrobeSlot}, {runtime.RaceName})");
                    return true;
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(tempObject);
                }
            }
            finally
            {
                runtime.Dispose();
            }
        }

        // ---- target body -------------------------------------------------------------------------------------------

        class Target
        {
            public Transform[] Bones;
            public Matrix4x4[] BindPoses;
            public int[] BoneNameHashes;
            public Transform RootBone;
            public RaceData RaceData;
            public Matrix4x4[] SkinMatrices;     // renderer-local skinning matrix per bone in the current (rest) pose
            public List<BoneWeight1>[] VertexWeights;
        }

        static Target CaptureTarget(UMACharacterRuntime runtime, SkinnedMeshRenderer body)
        {
            var mesh = body.sharedMesh;
            var bones = body.bones;
            var bindPoses = mesh.bindposes;
            if (bones == null || bones.Length == 0 || bindPoses.Length != bones.Length)
                throw new RecipeException("import.skeleton", $"body renderer has {bones?.Length ?? 0} bones and {bindPoses.Length} bind poses");
            var rootBone = body.rootBone ?? runtime.Avatar.umaData.skeleton.GetGlobalTransform() ?? runtime.Avatar.umaData.GetGlobalTransform();
            if (rootBone == null) throw new RecipeException("import.skeleton", "body renderer has no root bone");
            var hashes = bones.Select(b => UMAUtils.StringToHash(b.name)).ToArray();

            var perVertex = mesh.GetBonesPerVertex();
            var all = mesh.GetAllBoneWeights();
            var vertexWeights = new List<BoneWeight1>[mesh.vertexCount];
            var offset = 0;
            for (var v = 0; v < mesh.vertexCount; v++)
            {
                var count = perVertex[v];
                var list = new List<BoneWeight1>(count);
                for (var i = 0; i < count; i++) list.Add(all[offset + i]);
                offset += count;
                vertexWeights[v] = list;
            }
            var worldToLocal = body.transform.worldToLocalMatrix;
            var skin = new Matrix4x4[bones.Length];
            for (var b = 0; b < bones.Length; b++) skin[b] = worldToLocal * bones[b].localToWorldMatrix * bindPoses[b];

            RaceData raceData = null;
            var active = runtime.Avatar.activeRace;
            if (active != null) raceData = active.data != null ? active.data : active.racedata;
            if (raceData == null) raceData = UMAAssetIndexer.Instance.GetRace(runtime.RaceName);

            return new Target { Bones = bones, BindPoses = bindPoses, BoneNameHashes = hashes, RootBone = rootBone, RaceData = raceData, SkinMatrices = skin, VertexWeights = vertexWeights };
        }

        struct Triangle { public Vector3 A, B, C; public int I0, I1, I2; }

        static Triangle[] BuildSurface(Target target, SkinnedMeshRenderer body)
        {
            var baked = new Mesh();
            try
            {
                body.BakeMesh(baked);   // renderer-local, current pose (the rest pose), bone scales included
                var vertices = baked.vertices;
                var indices = body.sharedMesh.triangles;
                var triangles = new Triangle[indices.Length / 3];
                for (var t = 0; t < triangles.Length; t++)
                {
                    var i0 = indices[t * 3]; var i1 = indices[t * 3 + 1]; var i2 = indices[t * 3 + 2];
                    triangles[t] = new Triangle { A = vertices[i0], B = vertices[i1], C = vertices[i2], I0 = i0, I1 = i1, I2 = i2 };
                }
                return triangles;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(baked);
            }
        }

        // ---- source garment ------------------------------------------------------------------------------------------

        class Source
        {
            public Vector3[] Vertices;      // body-renderer local
            public Vector3[] Normals;
            public Vector2[] Uv;
            public int[] Triangles;
            public Material Material;
        }

        static Source LoadGarment(string glbPath, string name, string outFolder, Matrix4x4 worldToBodyLocal, JObject report)
        {
            if (!File.Exists(glbPath)) throw new RecipeException("import.glb", $"GLB not found: {glbPath}");
            var assetPath = $"{outFolder}/{name}_source.glb";
            File.Copy(glbPath, assetPath, true);
            AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null) throw new RecipeException("import.glb", $"UnityGLTF did not import {assetPath} as a GameObject");
            var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            try
            {
                instance.transform.position = Vector3.zero;
                instance.transform.rotation = Quaternion.identity;
                var vertices = new List<Vector3>();
                var normals = new List<Vector3>();
                var uvs = new List<Vector2>();
                var triangles = new List<int>();
                Material material = null;
                var parts = 0;
                foreach (var filter in instance.GetComponentsInChildren<MeshFilter>())
                {
                    var mesh = filter.sharedMesh;
                    if (mesh == null) continue;
                    var toBody = worldToBodyLocal * filter.transform.localToWorldMatrix;
                    var baseIndex = vertices.Count;
                    var v = mesh.vertices; var n = mesh.normals; var uv = mesh.uv;
                    for (var i = 0; i < v.Length; i++)
                    {
                        vertices.Add(toBody.MultiplyPoint3x4(v[i]));
                        normals.Add(n != null && n.Length == v.Length ? toBody.MultiplyVector(n[i]).normalized : Vector3.up);
                        uvs.Add(uv != null && uv.Length == v.Length ? uv[i] : Vector2.zero);
                    }
                    var idx = mesh.triangles;
                    for (var i = 0; i < idx.Length; i++) triangles.Add(idx[i] + baseIndex);
                    var renderer = filter.GetComponent<MeshRenderer>();
                    if (material == null && renderer != null) material = renderer.sharedMaterial;
                    parts++;
                }
                if (vertices.Count == 0) throw new RecipeException("import.glb", $"{assetPath} has no mesh");
                report["source_parts"] = parts;
                report["source_vertices"] = vertices.Count;
                report["source_triangles"] = triangles.Count / 3;
                var bounds = new Bounds(vertices[0], Vector3.zero);
                foreach (var p in vertices) bounds.Encapsulate(p);
                report["source_bounds_min"] = new JArray(bounds.min.x, bounds.min.y, bounds.min.z);
                report["source_bounds_max"] = new JArray(bounds.max.x, bounds.max.y, bounds.max.z);
                // One mesh; promodeler constant-material parts carry no UVs and UMA atlases overlays through UV0, so chart
                // one here, before the weights are transferred (the unwrap splits vertices at chart seams).
                var combined = new Mesh { name = name + "_combined", indexFormat = vertices.Count > 65535 ? IndexFormat.UInt32 : IndexFormat.UInt16 };
                combined.SetVertices(vertices);
                combined.SetNormals(normals);
                combined.SetUVs(0, uvs);
                combined.SetTriangles(triangles, 0, true);
                try
                {
                    if (uvs.All(uv => uv == Vector2.zero))
                    {
                        Unwrapping.GenerateSecondaryUVSet(combined);
                        combined.uv = combined.uv2;
                        report["uv"] = "generated";
                    }
                    else report["uv"] = "from glb";
                    report["mesh_vertices"] = combined.vertexCount;
                    return new Source { Vertices = combined.vertices, Normals = combined.normals, Uv = combined.uv, Triangles = combined.triangles, Material = material };
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(combined);
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        // ---- weight transfer -----------------------------------------------------------------------------------------

        class Weights { public byte[] PerVertex; public BoneWeight1[] All; public int FallbackVertices; }

        static Weights TransferWeights(Vector3[] vertices, Triangle[] surface, Target target)
        {
            var perVertex = new byte[vertices.Length];
            var all = new List<BoneWeight1>(vertices.Length * 4);
            var fallback = 0;
            var fallbackBone = Math.Max(0, Array.FindIndex(target.Bones, b => b.name == "Spine1"));
            for (var v = 0; v < vertices.Length; v++)
            {
                List<BoneWeight1> list;
                if (Closest(vertices[v], surface, out var hit, out var closest))
                {
                    var bary = Barycentric(closest, hit.A, hit.B, hit.C);
                    var merged = new Dictionary<int, float>();
                    Accumulate(merged, target.VertexWeights[hit.I0], bary.x);
                    Accumulate(merged, target.VertexWeights[hit.I1], bary.y);
                    Accumulate(merged, target.VertexWeights[hit.I2], bary.z);
                    list = merged.Where(kv => kv.Value > Epsilon).OrderByDescending(kv => kv.Value).Take(MaxInfluences)
                                 .Select(kv => new BoneWeight1 { boneIndex = kv.Key, weight = kv.Value }).ToList();
                    var sum = list.Sum(w => w.weight);
                    if (list.Count == 0 || sum <= Epsilon) { list = new List<BoneWeight1> { new BoneWeight1 { boneIndex = fallbackBone, weight = 1f } }; fallback++; }
                    else for (var i = 0; i < list.Count; i++) { var w = list[i]; w.weight /= sum; list[i] = w; }
                }
                else
                {
                    list = new List<BoneWeight1> { new BoneWeight1 { boneIndex = fallbackBone, weight = 1f } };
                    fallback++;
                }
                perVertex[v] = (byte)list.Count;
                all.AddRange(list);
            }
            return new Weights { PerVertex = perVertex, All = all.ToArray(), FallbackVertices = fallback };
        }

        static void Accumulate(Dictionary<int, float> merged, List<BoneWeight1> weights, float factor)
        {
            if (weights == null || factor <= Epsilon) return;
            foreach (var w in weights)
            {
                var value = w.weight * factor;
                if (value <= Epsilon) continue;
                merged[w.boneIndex] = merged.TryGetValue(w.boneIndex, out var current) ? current + value : value;
            }
        }

        static bool Closest(Vector3 p, Triangle[] surface, out Triangle best, out Vector3 closest)
        {
            best = default; closest = p;
            var bestDistance = float.MaxValue;
            for (var t = 0; t < surface.Length; t++)
            {
                var tri = surface[t];
                // Cheap reject on the vertex bounding sphere of the triangle.
                var centre = (tri.A + tri.B + tri.C) / 3f;
                var radius = Mathf.Sqrt(Mathf.Max((tri.A - centre).sqrMagnitude, (tri.B - centre).sqrMagnitude, (tri.C - centre).sqrMagnitude));
                var d = (p - centre).magnitude - radius;
                if (d > 0f && d * d >= bestDistance) continue;
                var c = ClosestPointOnTriangle(p, tri.A, tri.B, tri.C);
                var sq = (c - p).sqrMagnitude;
                if (sq < bestDistance) { bestDistance = sq; best = tri; closest = c; }
            }
            return bestDistance < float.MaxValue;
        }

        /// <summary>Ericson, Real-Time Collision Detection 5.1.5.</summary>
        static Vector3 ClosestPointOnTriangle(Vector3 p, Vector3 a, Vector3 b, Vector3 c)
        {
            var ab = b - a; var ac = c - a; var ap = p - a;
            var d1 = Vector3.Dot(ab, ap); var d2 = Vector3.Dot(ac, ap);
            if (d1 <= 0f && d2 <= 0f) return a;
            var bp = p - b;
            var d3 = Vector3.Dot(ab, bp); var d4 = Vector3.Dot(ac, bp);
            if (d3 >= 0f && d4 <= d3) return b;
            var vc = d1 * d4 - d3 * d2;
            if (vc <= 0f && d1 >= 0f && d3 <= 0f) return a + ab * (d1 / (d1 - d3));
            var cp = p - c;
            var d5 = Vector3.Dot(ab, cp); var d6 = Vector3.Dot(ac, cp);
            if (d6 >= 0f && d5 <= d6) return c;
            var vb = d5 * d2 - d1 * d6;
            if (vb <= 0f && d2 >= 0f && d6 <= 0f) return a + ac * (d2 / (d2 - d6));
            var va = d3 * d6 - d5 * d4;
            if (va <= 0f && (d4 - d3) >= 0f && (d5 - d6) >= 0f) return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)));
            var denom = 1f / (va + vb + vc);
            return a + ab * (vb * denom) + ac * (vc * denom);
        }

        static Vector3 Barycentric(Vector3 p, Vector3 a, Vector3 b, Vector3 c)
        {
            var v0 = b - a; var v1 = c - a; var v2 = p - a;
            var d00 = Vector3.Dot(v0, v0); var d01 = Vector3.Dot(v0, v1); var d11 = Vector3.Dot(v1, v1);
            var d20 = Vector3.Dot(v2, v0); var d21 = Vector3.Dot(v2, v1);
            var denom = d00 * d11 - d01 * d01;
            if (Mathf.Abs(denom) < Epsilon) return new Vector3(1f, 0f, 0f);
            var v = (d11 * d20 - d01 * d21) / denom;
            var w = (d00 * d21 - d01 * d20) / denom;
            var u = 1f - v - w;
            return new Vector3(Mathf.Clamp01(u), Mathf.Clamp01(v), Mathf.Clamp01(w));
        }

        // ---- slot mesh -----------------------------------------------------------------------------------------------

        static Mesh BuildSlotMesh(Source source, Target target, Weights weights, string name)
        {
            var count = source.Vertices.Length;
            var bind = new Vector3[count];
            var bindNormals = new Vector3[count];
            var offset = 0;
            for (var v = 0; v < count; v++)
            {
                var influences = weights.PerVertex[v];
                var blended = Matrix4x4.zero;
                for (var i = 0; i < influences; i++)
                {
                    var w = weights.All[offset + i];
                    var m = target.SkinMatrices[w.boneIndex];
                    for (var r = 0; r < 4; r++) for (var c = 0; c < 4; c++) blended[r, c] += m[r, c] * w.weight;
                }
                offset += influences;
                if (Mathf.Abs(blended.determinant) <= Epsilon) throw new RecipeException("import.skin", $"vertex {v} has a singular skinning matrix");
                var unskin = blended.inverse;
                bind[v] = unskin.MultiplyPoint3x4(source.Vertices[v]);
                var n = unskin.inverse.transpose.MultiplyVector(source.Normals[v]);
                bindNormals[v] = n.sqrMagnitude > Epsilon ? n.normalized : source.Normals[v];
            }
            var mesh = new Mesh { name = name + "_slotmesh", indexFormat = count > 65535 ? IndexFormat.UInt32 : IndexFormat.UInt16 };
            mesh.SetVertices(bind);
            mesh.SetNormals(bindNormals);
            mesh.SetUVs(0, source.Uv);
            mesh.subMeshCount = 1;
            mesh.SetTriangles(source.Triangles, 0, true);
            mesh.RecalculateTangents();
            using (var perVertex = new NativeArray<byte>(weights.PerVertex, Allocator.Temp))
            using (var all = new NativeArray<BoneWeight1>(weights.All, Allocator.Temp))
                mesh.SetBoneWeights(perVertex, all);
            mesh.bindposes = (Matrix4x4[])target.BindPoses.Clone();
            mesh.RecalculateBounds();
            return mesh;
        }

        // ---- UMA assets ----------------------------------------------------------------------------------------------

        static SlotDataAsset SaveSlot(SkinnedMeshRenderer temp, Target target, string name, string slotPath, JObject report)
        {
            var existing = AssetDatabase.LoadAssetAtPath<SlotDataAsset>(slotPath);
            if (existing != null) AssetDatabase.DeleteAsset(slotPath);
            var slot = ScriptableObject.CreateInstance<SlotDataAsset>();
            slot.name = name;
            slot.subMeshIndex = 0;
            slot.sourceSubmeshIndex = 0;
            slot.UpdateMeshData(temp, target.RootBone.name, false, 0, false, false);
            if (!UMAMeshData.IsNullOrEmptyMeshData(slot.meshData))
            {
                slot.meshData.RootBoneName = target.RootBone.name;
                slot.meshData.rootBoneHash = UMAUtils.StringToHash(target.RootBone.name);
                slot.meshData.boneNameHashes = (int[])target.BoneNameHashes.Clone();
                slot.meshData.SlotName = name;
            }
            var reasons = new List<string>();
            if (!slot.ValidateMeshData(reasons)) throw new RecipeException("import.slot", "SlotDataAsset failed validation: " + string.Join("; ", reasons));
            slot.PrepareForAssetPath(slotPath, name);
            AssetDatabase.CreateAsset(slot, slotPath);
            EditorUtility.SetDirty(slot);
            UMAAssetIndexer.Instance.EvilAddAsset(typeof(SlotDataAsset), slot);
            report["slot"] = slotPath;
            report["slot_vertices"] = slot.meshData?.vertexCount ?? 0;
            return slot;
        }

        static UMAMaterial ResolveMaterial(string fromRecipe, string materialName, string umaRace, JObject report)
        {
            if (!string.IsNullOrEmpty(fromRecipe))
            {
                var recipe = WardrobeLookup.Find(fromRecipe);
                var uma = recipe?.GetCachedRecipe();
                var slots = uma?.GetAllSlots();
                if (slots != null)
                {
                    foreach (var slot in slots)
                    {
                        if (slot == null) continue;
                        for (var i = 0; i < slot.OverlayCount; i++)
                        {
                            var overlay = slot.GetOverlay(i);
                            if (overlay?.asset?.material != null)
                            {
                                report["material"] = overlay.asset.material.name + " (from " + fromRecipe + ")";
                                return overlay.asset.material;
                            }
                        }
                    }
                }
                Debug.LogWarning($"[ProModeler] recipe {fromRecipe} has no overlay material; falling back to {materialName ?? "UMA_Diffuse_Normal_Metallic"}");
            }
            materialName = materialName ?? "UMA_Diffuse_Normal_Metallic";
            foreach (var guid in AssetDatabase.FindAssets($"{materialName} t:UMAMaterial"))
            {
                var asset = AssetDatabase.LoadAssetAtPath<UMAMaterial>(AssetDatabase.GUIDToAssetPath(guid));
                if (asset != null && asset.name == materialName) { report["material"] = asset.name; return asset; }
            }
            throw new RecipeException("import.material", $"UMAMaterial {materialName} not found");
        }

        static OverlayDataAsset SaveOverlay(SlotDataAsset slot, UMAMaterial material, Color color, string outFolder, string name, JObject report)
        {
            var overlayPath = $"{outFolder}/{name}_overlay.asset";
            if (AssetDatabase.LoadAssetAtPath<OverlayDataAsset>(overlayPath) != null) AssetDatabase.DeleteAsset(overlayPath);
            var overlay = ScriptableObject.CreateInstance<OverlayDataAsset>();
            overlay.name = name + "_overlay";
            overlay.material = material;
            overlay.materialName = material.name;
            var channels = material.channels?.Length ?? 0;
            overlay.textureList = new Texture[channels];
            overlay.textureNames = new string[channels];
            overlay.overlayBlend = new OverlayDataAsset.OverlayBlend[channels];
            for (var i = 0; i < channels; i++)
            {
                var channel = material.channels[i];
                var property = channel.materialPropertyName ?? "";
                var kind = property.IndexOf("Bump", StringComparison.OrdinalIgnoreCase) >= 0 || property.IndexOf("Normal", StringComparison.OrdinalIgnoreCase) >= 0
                    ? "normal" : i == 0 ? "diffuse" : "mask";
                var pixel = kind == "normal" ? new Color(0.5f, 0.5f, 1f, 1f) : kind == "diffuse" ? color : new Color(0f, 0f, 0f, 0.2f);   // mask: non-metallic, rough
                var texture = FlatTexture($"{outFolder}/{name}_{kind}_{i}.png", pixel, kind == "normal");
                overlay.textureList[i] = texture;
                overlay.textureNames[i] = texture != null ? texture.name : "";
                overlay.overlayBlend[i] = OverlayDataAsset.OverlayBlend.Normal;
            }
            overlay.ValidateBlendList();
            AssetDatabase.CreateAsset(overlay, overlayPath);
            EditorUtility.SetDirty(overlay);
            UMAUpdateProcessor.UpdateOverlay(overlay);
            UMAAssetIndexer.Instance.EvilAddAsset(typeof(OverlayDataAsset), overlay);
            report["overlay"] = overlayPath;
            report["overlay_channels"] = channels;
            return overlay;
        }

        static Texture2D FlatTexture(string path, Color color, bool normalMap)
        {
            const int size = 16;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, false);
            var pixels = Enumerable.Repeat(color, size * size).ToArray();
            texture.SetPixels(pixels);
            texture.Apply();
            File.WriteAllBytes(path, texture.EncodeToPNG());
            UnityEngine.Object.DestroyImmediate(texture);
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer != null)
            {
                importer.textureType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
                importer.sRGBTexture = !normalMap;
                importer.mipmapEnabled = false;
                importer.wrapMode = TextureWrapMode.Repeat;
                importer.textureCompression = TextureImporterCompression.Uncompressed;
                importer.SaveAndReimport();
            }
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }

        static UMAWardrobeRecipe SaveRecipe(SlotDataAsset slot, OverlayDataAsset overlay, RaceData raceData, string wardrobeSlot, string outFolder, string name, JObject report)
        {
            var recipeName = name + "_Wardrobe";
            var recipePath = $"{outFolder}/{recipeName}.asset";
            if (AssetDatabase.LoadAssetAtPath<UMAWardrobeRecipe>(recipePath) != null) AssetDatabase.DeleteAsset(recipePath);
            var uma = new UMAData.UMARecipe();
            uma.ClearDna();
            if (raceData != null) uma.SetRace(raceData);
            var slotData = new SlotData(slot);
            if (raceData != null && !string.IsNullOrEmpty(raceData.raceName)) slotData.Races = new[] { raceData.raceName };
            slotData.AddOverlay(new OverlayData(overlay));
            uma.SetSlot(0, slotData);
            var recipe = ScriptableObject.CreateInstance<UMAWardrobeRecipe>();
            recipe.name = recipeName;
            recipe.recipeType = "Wardrobe";
            recipe.DisplayValue = name;
            recipe.wardrobeSlot = wardrobeSlot;
            recipe.compatibleRaces = new List<string>();
            if (raceData != null && !string.IsNullOrEmpty(raceData.raceName)) recipe.compatibleRaces.Add(raceData.raceName);
            recipe.Save(uma);
            AssetDatabase.CreateAsset(recipe, recipePath);
            EditorUtility.SetDirty(recipe);
            UMAAssetIndexer.Instance.EvilAddAsset(typeof(UMAWardrobeRecipe), recipe);
            report["recipe"] = recipePath;
            report["uma_wardrobe_recipe"] = recipeName;
            return recipe;
        }
    }
}
