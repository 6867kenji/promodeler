// Batch entry point (docs/03, 9.3):
//   Unity.exe -batchmode -projectPath <project> -executeMethod ProModeler.Editor.CharacterBatchBuilder.Build
//             -recipe <recipe.json> [-outfit <outfit.json>] -out <dir> -views front,side -passes shaded,clay -formats fbx,glb
//             -logFile <dir>/unity.log
// Always writes <dir>/build.json and exits the editor itself (0 on success, 1 on failure), because UMA generation is
// synchronous here and nothing else should keep the editor alive.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using ProModeler.Build;
using ProModeler.Catalog;
using ProModeler.Measure;
using ProModeler.Recipe;
using ProModeler.Resolve;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class CharacterBatchBuilder
    {
        public static void Build()
        {
            var args = Args.Parse(Environment.GetCommandLineArgs());
            var outDir = args.Get("-out");
            var report = new BuildReport();
            var started = DateTime.UtcNow;
            var code = 1;
            try
            {
                if (string.IsNullOrEmpty(outDir)) throw new RecipeException("args.out", "-out <directory> is required");
                Directory.CreateDirectory(outDir);
                var recipePath = args.Get("-recipe") ?? Path.Combine(outDir, "recipe.json");
                var outfitPath = args.Get("-outfit");
                var views = (args.Get("-views") ?? "front,side,back,perspective,face").Split(',').Select(v => v.Trim()).Where(v => v.Length > 0).ToList();
                var passes = (args.Get("-passes") ?? "shaded,clay").Split(',').Select(v => v.Trim()).Where(v => v.Length > 0).ToList();
                var formats = (args.Get("-formats") ?? "fbx,glb").Split(',').Select(v => v.Trim()).Where(v => v.Length > 0).ToList();
                var resolution = int.TryParse(args.Get("-resolution"), out var r) ? r : 768;
                var render = !args.Has("-nographics");

                BuildCharacter(recipePath, outfitPath, outDir, views, passes, formats, resolution, render, report);
                code = report.Status == "ok" ? 0 : 1;
            }
            catch (Exception exc)
            {
                Fail(report, exc);
            }
            finally
            {
                report.Seconds = (float)(DateTime.UtcNow - started).TotalSeconds;
                try
                {
                    if (!string.IsNullOrEmpty(outDir)) RecipeJson.WriteFile(Path.Combine(outDir, "build.json"), report);
                }
                catch (Exception exc)
                {
                    Debug.LogError("[ProModeler] could not write build.json: " + exc);
                }
                Debug.Log($"[ProModeler] build {report.Status} in {report.Seconds:F1} s");
                EditorApplication.Exit(code);
            }
        }

        static void Fail(BuildReport report, Exception exc)
        {
            report.Status = "failed";
            var code = exc is RecipeException re ? re.Code : exc.GetType().Name;
            report.Error = new BuildError { Code = code, Message = exc.Message, Stack = exc.StackTrace };
            Debug.LogError($"[ProModeler] {code}: {exc.Message}\n{exc.StackTrace}");
        }

        public static void BuildCharacter(string recipePath, string outfitPath, string outDir, List<string> views, List<string> passes,
                                          List<string> formats, int resolution, bool render, BuildReport report)
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var recipe = RecipeLoader.LoadCharacter(recipePath);
            OutfitRecipe outfit = null;
            if (!string.IsNullOrEmpty(outfitPath)) outfit = RecipeLoader.LoadOutfit(outfitPath);
            var dressed = RecipeLoader.ApplyOutfit(recipe, outfit);

            var assets = LoadAssets(Path.Combine(outDir, "assets.json"));
            var catalogRoot = (string)assets?["catalog_root"];
            var catalog = AssetCatalog.Load(catalogRoot, (string)assets?["catalog_version"]);
            if (catalog.Entries.Count == 0) report.Warn("catalog.empty", $"no catalog entries loaded from {catalogRoot}");

            report.Environment["unity"] = Application.unityVersion;
            report.Environment["hdrp"] = PackageVersion("com.unity.render-pipelines.high-definition");
            report.Environment["uma"] = UMACharacterRuntime.UMAVersion();
            report.Environment["catalog_version"] = catalog.Version ?? "";
            report.Environment["render_pipeline"] = GraphicsSettings.currentRenderPipeline != null ? GraphicsSettings.currentRenderPipeline.GetType().Name : "built-in";

            using (var runtime = new UMACharacterRuntime())
            {
                runtime.Create(dressed, catalog, report.Warn);
                if (!runtime.Rebuild(120f)) throw new RecipeException("uma.build", "UMA did not produce a body mesh");
                Debug.Log("[ProModeler] DNA available: " + string.Join(", ", runtime.AllDnaNames()));

                var measurer = BodyMeasurer.ForRecipe(dressed);
                var resolver = new BodyResolver(runtime, measurer, dressed);
                report.Resolved = resolver.Solve(report);

                var faceDna = FaceResolver.ToDna(dressed.Face.Shape);
                if (faceDna.Count > 0)
                {
                    runtime.SetDna(faceDna, report.Warn);
                    if (!runtime.Rebuild(120f)) throw new RecipeException("uma.build", "rebuild after face DNA failed");
                }

                var measured = resolver.Measure();
                report.MeasuredM = JObject.FromObject(measured);
                if (dressed.GarmentInSlot("footwear")?.SoleHeightM is float sole && measured.TryGetValue("barefoot_height", out var barefoot))
                    report.MeasuredM["standing_shod_height"] = barefoot + sole;

                CountGeometry(runtime, report);
                report.Wardrobe = dressed.Wardrobe.Select(g => new WardrobeEntry
                {
                    Slot = g.Slot, CatalogId = g.CatalogId,
                    Resolved = AssetCatalog.UmaRecipeFor(catalog.Get(g.CatalogId), dressed.Base.Race),
                    Fitted = runtime.Avatar.GetWardrobeItem(UMACharacterRuntime.SlotNames.TryGetValue(g.Slot, out var s) ? s : "") != null,
                }).ToList();
                foreach (var accessory in dressed.Accessories)
                    report.Accessories.Add(new AccessoryEntry { Id = accessory.Id, Source = accessory.Source?.Path, Socket = accessory.Socket, Attached = false });
                if (dressed.Accessories.Count > 0) report.Warn("accessory.notAttached", "accessory attachment arrives with M12; accessories are listed but not attached");

                if (render)
                {
                    var key = RenderKey(views, passes, resolution);
                    report.Renders = VerificationRenderer.Render(runtime, views, passes, Path.Combine(outDir, "renders", key), resolution, report);
                }
                else report.Warn("render.skipped", "renders skipped (-nographics)");

                report.Exports = CharacterExporter.Export(runtime, outDir, formats, report);
                report.Status = "ok";
            }
        }

        static void CountGeometry(UMACharacterRuntime runtime, BuildReport report)
        {
            var totalTriangles = 0;
            var totalVertices = 0;
            var materials = new HashSet<Material>();
            foreach (var renderer in runtime.AllRenderers)
            {
                Mesh mesh = renderer is SkinnedMeshRenderer smr ? smr.sharedMesh : renderer.GetComponent<MeshFilter>()?.sharedMesh;
                if (mesh == null) continue;
                var triangles = 0;
                for (var i = 0; i < mesh.subMeshCount; i++) triangles += (int)mesh.GetIndexCount(i) / 3;
                totalTriangles += triangles;
                totalVertices += mesh.vertexCount;
                foreach (var material in renderer.sharedMaterials) if (material != null) materials.Add(material);
                report.Parts[renderer.name] = new Dictionary<string, int> { { "triangles", triangles }, { "vertices", mesh.vertexCount }, { "materials", renderer.sharedMaterials.Length } };
            }
            report.Totals["triangles"] = totalTriangles;
            report.Totals["vertices"] = totalVertices;
            report.Totals["materials"] = materials.Count;
        }

        static JObject LoadAssets(string path) => File.Exists(path) ? JObject.Parse(File.ReadAllText(path)) : null;

        static string RenderKey(IEnumerable<string> views, IEnumerable<string> passes, int resolution)
        {
            var text = string.Join(",", views) + "|" + string.Join(",", passes) + "|" + resolution;
            using (var sha = System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(text))).Replace("-", "").Substring(0, 8).ToLowerInvariant();
        }

        public static string PackageVersion(string packageName)
        {
            var info = UnityEditor.PackageManager.PackageInfo.GetAllRegisteredPackages().FirstOrDefault(p => p.name == packageName);
            return info != null ? info.version : "missing";
        }

        public class Args
        {
            readonly Dictionary<string, string> _values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            readonly HashSet<string> _flags = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            public static Args Parse(string[] argv)
            {
                var args = new Args();
                for (var i = 0; i < argv.Length; i++)
                {
                    if (!argv[i].StartsWith("-")) continue;
                    args._flags.Add(argv[i]);
                    if (i + 1 < argv.Length && !argv[i + 1].StartsWith("-")) args._values[argv[i]] = argv[i + 1];
                }
                return args;
            }

            public string Get(string name) => _values.TryGetValue(name, out var v) ? v : null;
            public bool Has(string name) => _flags.Contains(name);
        }
    }
}
