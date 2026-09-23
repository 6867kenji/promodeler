// Interactive character maker (docs/03 chapter 9.2 / original proposal section 14): edits a CharacterRecipe in place
// and previews it with the same UMACharacterRuntime the batch build uses. Save writes only the recipe JSON; the Unity
// scene is never the source of truth. Opened from the menu or by `promodeler character edit <id>`, which starts the
// editor with -executeMethod ProModeler.Editor.CharacterEditorWindow.Open -recipe <path>.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Catalog;
using ProModeler.Measure;
using ProModeler.Recipe;
using ProModeler.Resolve;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public class CharacterEditorWindow : EditorWindow
    {
        string _recipePath = "";
        string _catalogRoot = "";
        CharacterRecipe _recipe;
        UMACharacterRuntime _runtime;
        AssetCatalog _catalog;
        Vector2 _scroll;
        string _status = "";
        bool _solveOnRebuild = true;
        readonly List<string> _log = new List<string>();
        Dictionary<string, float> _measured;

        [MenuItem("ProModeler/Character Editor")]
        public static void ShowWindow()
        {
            Show(null, null);
        }

        /// <summary>A floating (utility) window in front of the main editor window, sized so the sliders are visible.</summary>
        static CharacterEditorWindow Show(string recipe, string catalog)
        {
            var window = GetWindow<CharacterEditorWindow>(utility: true, title: "ProModeler Character", focus: true);
            if (window.position.width < 200f || window.position.height < 200f)
                window.position = new Rect(120f, 120f, 560f, 860f);
            window.minSize = new Vector2(420f, 400f);
            if (!string.IsNullOrEmpty(catalog)) window._catalogRoot = catalog;
            if (!string.IsNullOrEmpty(recipe))
            {
                window._recipePath = recipe;
                window.Load();
            }
            window.Show();
            window.Focus();
            Debug.Log($"[ProModeler] character editor window open (recipe {(string.IsNullOrEmpty(recipe) ? "none" : recipe)})");
            return window;
        }

        /// <summary>-executeMethod entry: opens the window on the recipe given by -recipe (and -catalog). The editor restores
        /// its window layout after start-up methods run and would discard a window made here, so the window is opened on the
        /// next editor update instead.</summary>
        public static void Open()
        {
            var args = CharacterBatchBuilder.Args.Parse(Environment.GetCommandLineArgs());
            var recipe = args.Get("-recipe");
            var catalog = args.Get("-catalog");
            EditorApplication.delayCall += () => EditorApplication.delayCall += () => Show(recipe, catalog);
        }

        void OnGUI()
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            EditorGUILayout.LabelField("Recipe", EditorStyles.boldLabel);
            using (new EditorGUILayout.HorizontalScope())
            {
                _recipePath = EditorGUILayout.TextField("recipe.json", _recipePath);
                if (GUILayout.Button("...", GUILayout.Width(30)))
                {
                    var picked = EditorUtility.OpenFilePanel("Character recipe", Path.GetDirectoryName(_recipePath), "json");
                    if (!string.IsNullOrEmpty(picked)) _recipePath = picked;
                }
                if (GUILayout.Button("Load", GUILayout.Width(60))) Load();
                GUI.enabled = _recipe != null;
                if (GUILayout.Button("Save", GUILayout.Width(60))) Save();
                GUI.enabled = true;
            }
            _catalogRoot = EditorGUILayout.TextField("catalog root", _catalogRoot);
            if (_recipe == null)
            {
                EditorGUILayout.HelpBox("Load a character/recipes/<id>.json. Sliders edit the recipe; Rebuild previews it with UMA; Save writes the JSON only.", MessageType.Info);
                EditorGUILayout.EndScrollView();
                return;
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField($"{_recipe.Name} ({_recipe.Id}) - {_recipe.Identity.Sex}, {_recipe.Base.Race}", EditorStyles.boldLabel);

            EditorGUILayout.LabelField("Body measurements (m)", EditorStyles.boldLabel);
            var m = _recipe.Body.MeasurementsM;
            m.BarefootHeight = EditorGUILayout.FloatField("barefoot_height", m.BarefootHeight);
            m.Inseam = OptionalFloat("inseam", m.Inseam);
            m.ShoulderWidth = OptionalFloat("shoulder_width", m.ShoulderWidth);
            m.FootLength = OptionalFloat("foot_length", m.FootLength);
            m.HeadHeight = OptionalFloat("head_height", m.HeadHeight);
            foreach (var key in m.Circumferences.Keys.ToList())
                m.Circumferences[key] = EditorGUILayout.FloatField(key + " circumference", m.Circumferences[key]);

            EditorGUILayout.LabelField("Body shape (0..1)", EditorStyles.boldLabel);
            foreach (var key in _recipe.Body.Shape.Keys.ToList())
                _recipe.Body.Shape[key] = EditorGUILayout.Slider(key, _recipe.Body.Shape[key], 0f, 1f);

            EditorGUILayout.LabelField("Face shape (0..1, 0.5 neutral)", EditorStyles.boldLabel);
            foreach (var key in _recipe.Face.Shape.Keys.ToList())
                _recipe.Face.Shape[key] = EditorGUILayout.Slider(key, _recipe.Face.Shape[key], 0f, 1f);

            EditorGUILayout.LabelField("Appearance", EditorStyles.boldLabel);
            var a = _recipe.Appearance;
            a.Skin.Preset = EditorGUILayout.TextField("skin preset", a.Skin.Preset);
            a.Skin.BaseColorSrgb = ColorField("skin color", a.Skin.BaseColorSrgb);
            a.Hair.Style = EditorGUILayout.TextField("hair style", a.Hair.Style);
            a.Hair.BaseColorSrgb = ColorField("hair color", a.Hair.BaseColorSrgb);
            a.Eyebrows.Style = EditorGUILayout.TextField("eyebrows", a.Eyebrows.Style);
            a.Eyes.IrisColorSrgb = ColorField("iris color", a.Eyes.IrisColorSrgb);
            if (a.FacialHair != null) a.FacialHair.Style = EditorGUILayout.TextField("facial hair", a.FacialHair.Style);

            EditorGUILayout.LabelField("Wardrobe (catalog ids)", EditorStyles.boldLabel);
            foreach (var garment in _recipe.Wardrobe)
                garment.CatalogId = EditorGUILayout.TextField(garment.Slot, garment.CatalogId);

            EditorGUILayout.Space();
            _solveOnRebuild = EditorGUILayout.Toggle("solve body measurements on rebuild", _solveOnRebuild);
            using (new EditorGUILayout.HorizontalScope())
            {
                if (GUILayout.Button(_solveOnRebuild ? "Rebuild preview (solve measurements, 30-90 s)" : "Rebuild preview (race defaults, a few seconds)")) Rebuild();
                if (GUILayout.Button("Clear preview", GUILayout.Width(110))) ClearPreview();
            }
            EditorGUILayout.HelpBox("The body appears in the Scene view (Window > General > Scene if it is closed). Load builds a quick preview; the solve toggle fits the measurements.", MessageType.None);
            if (_measured != null)
            {
                EditorGUILayout.LabelField("Measured (naked, m)", EditorStyles.boldLabel);
                foreach (var kv in _measured.OrderBy(kv => kv.Key))
                    if (!kv.Key.EndsWith("_width") && !kv.Key.EndsWith("_depth"))
                        EditorGUILayout.LabelField(kv.Key, kv.Value.ToString("F3"));
            }
            if (!string.IsNullOrEmpty(_status)) EditorGUILayout.HelpBox(_status, MessageType.None);
            foreach (var line in _log.Skip(Math.Max(0, _log.Count - 8))) EditorGUILayout.LabelField(line, EditorStyles.miniLabel);
            EditorGUILayout.EndScrollView();
        }

        static float? OptionalFloat(string label, float? value)
        {
            var shown = EditorGUILayout.FloatField(label + (value.HasValue ? "" : " (unset)"), value ?? 0f);
            return value.HasValue || shown != 0f ? shown : (float?)null;
        }

        static string ColorField(string label, string hex)
        {
            var color = Color.white;
            if (!string.IsNullOrEmpty(hex)) ColorUtility.TryParseHtmlString(hex, out color);
            var picked = EditorGUILayout.ColorField(label, color);
            return picked == color ? hex : "#" + ColorUtility.ToHtmlStringRGB(picked);
        }

        void Load()
        {
            try
            {
                _recipe = RecipeLoader.LoadCharacter(_recipePath);
                if (string.IsNullOrEmpty(_catalogRoot))
                {
                    // character/recipes/<id>.json -> character/catalog
                    var dir = Path.GetDirectoryName(Path.GetFullPath(_recipePath));
                    var candidate = Path.Combine(Path.GetDirectoryName(dir) ?? dir, "catalog");
                    if (Directory.Exists(candidate)) _catalogRoot = candidate;
                }
                _catalog = AssetCatalog.Load(_catalogRoot);
                _status = $"loaded {_recipePath} ({_catalog.Entries.Count} catalog entries)";
                _log.Clear();
                Debug.Log($"[ProModeler] editor: loaded {_recipePath}");
            }
            catch (Exception exc)
            {
                _status = "load failed: " + exc.Message;
                Debug.LogException(exc);
                Repaint();
                return;
            }
            // Show the body right away (race defaults, dressed); the measurement solve is a separate, slower step.
            Rebuild(solve: false);
        }

        void Save()
        {
            try
            {
                _recipe.Source.Kind = "gui";
                RecipeJson.WriteFile(_recipePath, _recipe);
                _status = $"saved {_recipePath} (source.kind = gui; run `promodeler character validate` and `character diff` on the Python side)";
            }
            catch (Exception exc)
            {
                _status = "save failed: " + exc.Message;
            }
        }

        void Rebuild() => Rebuild(_solveOnRebuild);

        void Rebuild(bool solve)
        {
            try
            {
                ClearPreview();
                if (EditorSceneManager.GetActiveScene().rootCount > 0 && !EditorSceneManager.GetActiveScene().isDirty)
                    EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
                var report = new BuildReport();
                _runtime = new UMACharacterRuntime();
                _runtime.Create(_recipe, _catalog, (code, message) => _log.Add(code + ": " + message));
                if (!_runtime.Rebuild(120f)) throw new RecipeException("uma.build", "UMA did not produce a body mesh");
                var measurer = BodyMeasurer.ForRecipe(_recipe);
                var resolver = new BodyResolver(_runtime, measurer, _recipe);
                if (solve)
                {
                    var resolved = resolver.Solve(report, 8);
                    _log.Add($"solved in {resolved.Iterations} iterations, root scale {resolved.RootScale:F4}");
                }
                _runtime.SetDna(FaceResolver.ToDna(_recipe.Face.Shape), (code, message) => _log.Add(code + ": " + message));
                _measured = resolver.Measure();
                _runtime.Dress();
                if (!_runtime.Rebuild(120f)) throw new RecipeException("uma.build", "rebuild after dressing failed");
                // Show the skeleton's own pose, not the Animator's cached T-pose (see VerificationRenderer).
                var animator = _runtime.Root.GetComponentInChildren<Animator>();
                if (animator != null) animator.enabled = false;
                foreach (var w in report.Warnings) _log.Add(w.Code + ": " + w.Message);
                _status = solve
                    ? "preview rebuilt with the measurement solve"
                    : "preview rebuilt at the race defaults (measurements not solved yet); tick the solve toggle and press Rebuild preview to fit the body";
                Selection.activeGameObject = _runtime.Root;
                var view = SceneView.lastActiveSceneView ?? GetWindow<SceneView>(typeof(CharacterEditorWindow));
                if (view != null)
                {
                    view.Show();
                    view.FrameSelected();
                    view.Repaint();
                }
                Debug.Log($"[ProModeler] editor: preview {_recipe.Id} rebuilt (solve {solve}); root {_runtime.Root.name} with {_runtime.AllRenderers.Count()} renderers");
            }
            catch (Exception exc)
            {
                _status = "rebuild failed: " + exc.Message;
                Debug.LogException(exc);
            }
            Repaint();
        }

        void ClearPreview()
        {
            _runtime?.Dispose();
            _runtime = null;
        }

        void OnDestroy() => ClearPreview();
    }
}
