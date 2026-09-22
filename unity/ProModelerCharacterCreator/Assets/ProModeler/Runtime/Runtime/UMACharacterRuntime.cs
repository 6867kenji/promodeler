// ICharacterRuntime on UMA 3 (DynamicCharacterAvatar). This is the only file that speaks UMA vocabulary:
// race names, wardrobe slot names, DNA names and shared color names. Everything above it uses the recipe vocabulary.

using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UMA;
using UMA.CharacterSystem;
using ProModeler.Catalog;
using ProModeler.Recipe;

namespace ProModeler.Runtime
{
    public class UMACharacterRuntime : ICharacterRuntime
    {
        public static readonly Dictionary<string, string> RaceNames = new Dictionary<string, string>
        {
            { "human_male", "Human Male 3.0" },
            { "human_female", "Human Female 3.0" },
        };

        // recipe wardrobe slot -> UMA wardrobe slot. Slots UMA 3 has no place for are reported, not dropped silently.
        public static readonly Dictionary<string, string> SlotNames = new Dictionary<string, string>
        {
            { "upper", "Chest" }, { "dress", "Chest" }, { "outer", "Chest" }, { "inner", "TopUnderlayer" },
            { "lower", "Legs" }, { "socks", "BottomUnderlayer" }, { "hands", "Hands" }, { "footwear", "Feet" },
            { "headwear", "Helmet" }, { "neck", "Neck" }, { "waist", "Waist" },
        };

        // Preferred UMA 3 body DNA in the order the resolver may move them; filtered against what the race exposes.
        public static readonly string[] PreferredBodyDna =
        {
            "height", "legsSize", "shoulderWidth", "feetSize", "chestSize", "breastSize", "breastPosition", "breastWidth", "upperWeight",
            "upperMuscle", "waist", "belly", "gluteusSize", "lowerWeight", "lowerMuscle",
        };

        /// <summary>
        /// Shape freedoms UMA's DNA lacks, realised as scales/offsets on UMA's leaf "Adjust" bones after every
        /// generation (they carry local skin weights and no children, so scaling them deforms only their region).
        /// 0.5 is neutral; scales run 0.6..1.5, offsets +-4 cm outward. Names are ProModeler's, not UMA's.
        /// </summary>
        public static readonly SkeletonAdjust[] Adjusts =
        {
            new SkeletonAdjust("adj:chest_depth", new[] { "Spine1Adjust" }, Axis.Z, false),
            new SkeletonAdjust("adj:chest_width", new[] { "Spine1Adjust" }, Axis.X, false),
            new SkeletonAdjust("adj:underbust_depth", new[] { "SpineAdjust" }, Axis.Z, false),
            new SkeletonAdjust("adj:underbust_width", new[] { "SpineAdjust" }, Axis.X, false),
            new SkeletonAdjust("adj:belly_depth", new[] { "LowerBackBelly" }, Axis.Z, false),
            new SkeletonAdjust("adj:hip_depth", new[] { "LowerBackAdjust" }, Axis.Z, false),
            new SkeletonAdjust("adj:hip_width", new[] { "LowerBackAdjust" }, Axis.X, false),
            new SkeletonAdjust("adj:head_height", new[] { "HeadAdjust" }, Axis.Y, false),
            // ShoulderAdjust bones carry no usable skin weight (probe: +6 mm over the full range); the arm root offset is
            // the shoulder-width handle for races without a shoulderWidth DNA.
            new SkeletonAdjust("pos:arm_spread", new[] { "LeftArm", "RightArm" }, Axis.X, true),
        };

        public enum Axis { X, Y, Z }

        public class SkeletonAdjust
        {
            public readonly string Name;
            public readonly string[] Bones;
            public readonly Axis Axis;
            public readonly bool IsOffset;
            public SkeletonAdjust(string name, string[] bones, Axis axis, bool isOffset) { Name = name; Bones = bones; Axis = axis; IsOffset = isOffset; }
            public static float Scale(float v) => Mathf.Lerp(0.65f, 1.45f, Mathf.Clamp01(v));   // 0.6-1.5 stepped the silhouette, 0.7-1.4 lost 2-3 cm of chest girth; compromise at the bone's weight boundary
            public static float Offset(float v) => (Mathf.Clamp01(v) - 0.5f) * 0.16f;   // +-8 cm outward at the extremes
        }

        private readonly Dictionary<string, float> _adjustValues = new Dictionary<string, float>();
        private readonly Dictionary<int, Vector3> _basePositions = new Dictionary<int, Vector3>();
        private readonly Dictionary<int, Vector3> _baseScales = new Dictionary<int, Vector3>();

        public GameObject Root { get; private set; }
        public DynamicCharacterAvatar Avatar { get; private set; }
        public UMAGenerator Generator { get; private set; }
        public string RaceName { get; private set; }
        public string Version => UMAVersion();

        private readonly List<string> _bodyParameterNames = new List<string>();
        private CharacterRecipe _recipe;

        public IReadOnlyList<string> BodyParameterNames => _bodyParameterNames;

        // -- creation --------------------------------------------------------------------------------

        public void Create(CharacterRecipe recipe, AssetCatalog catalog, Action<string, string> warn)
        {
            _recipe = recipe;
            if (!RaceNames.TryGetValue(recipe.Base.Race, out var race))
                throw new RecipeException("base.race", $"no UMA race for base.race {recipe.Base.Race}");
            RaceName = race;
            Generator = EnsureGenerator();
            if (UMAAssetIndexer.Instance.GetRace(race) == null)
                throw new RecipeException("uma.race", $"UMA race {race} is not in the asset index; run the project setup (promodeler character setup).");

            Root = new GameObject(recipe.Id);
            Root.transform.position = Vector3.zero;
            Avatar = Root.AddComponent<DynamicCharacterAvatar>();
            Avatar.editorTimeGeneration = false;   // we drive generation ourselves; UMAData.umaGenerator reads UMAAssetIndexer.Instance.Generator
            Avatar.RacePreset = race;
            Avatar.ChangeRace(race);
            _catalog = catalog;
            _warn = warn;
            // Wardrobe is applied by Dress() after the body has been solved: UMA merges body and clothes into one
            // skinned mesh, so measuring a dressed avatar would tape-measure the jacket and the shoes.
        }

        private AssetCatalog _catalog;
        private Action<string, string> _warn;
        public bool Dressed { get; private set; }

        /// <summary>Apply wardrobe, hair, eyebrows, beard and colors (call after the body solve, then Rebuild).</summary>
        public void Dress()
        {
            if (Dressed) return;
            ApplyWardrobe(_recipe, _catalog, _warn);
            ApplyColors(_recipe, _warn);
            Dressed = true;
        }

        static UMAGenerator EnsureGenerator()
        {
            var indexer = UMAAssetIndexer.Instance;
            if (indexer == null) throw new RecipeException("uma.indexer", "UMAAssetIndexer is not available (editor compiling or UMA missing).");
            var generator = indexer.Generator;  // creates the scene generator on demand
            if (generator == null) throw new RecipeException("uma.generator", "UMAAssetIndexer.Instance.Generator is null; UMA could not create its generator in this scene.");
            return generator;
        }

        // Layering order: what UMA shows in a shared slot is the last recipe set, so underlayers go first.
        static readonly string[] SlotOrder = { "socks", "inner", "lower", "dress", "upper", "outer", "neck", "waist", "hands", "footwear", "headwear" };

        void ApplyWardrobe(CharacterRecipe recipe, AssetCatalog catalog, Action<string, string> warn)
        {
            var taken = new Dictionary<string, string>();
            foreach (var garment in recipe.Wardrobe.OrderBy(g => Array.IndexOf(SlotOrder, g.Slot) < 0 ? 99 : Array.IndexOf(SlotOrder, g.Slot)))
            {
                if (!SlotNames.TryGetValue(garment.Slot, out var umaSlot))
                {
                    warn("wardrobe.slot", $"slot {garment.Slot} has no UMA wardrobe slot; left empty");
                    continue;
                }
                var umaRecipe = ResolveWardrobe(garment.CatalogId, catalog, umaSlot, warn, $"wardrobe[{garment.Slot}]");
                if (umaRecipe == null) continue;
                if (taken.TryGetValue(umaRecipe.wardrobeSlot, out var previous))
                    warn("wardrobe.slotConflict", $"wardrobe[{garment.Slot}]: {umaRecipe.name} replaces {previous} in UMA slot {umaRecipe.wardrobeSlot} (the UMA 3 samples have no underlayer for it)");
                if (!Avatar.SetSlot(umaRecipe))
                    warn("wardrobe.incompatible", $"wardrobe[{garment.Slot}]: UMA recipe {umaRecipe.name} is not compatible with {RaceName}");
                else taken[umaRecipe.wardrobeSlot] = umaRecipe.name;
            }
            var a = recipe.Appearance;
            ApplyAppearanceSlot(a.Hair?.Style, catalog, "Hair", "appearance.hair", warn);
            ApplyAppearanceSlot(a.Eyebrows?.Style, catalog, "Eyebrows", "appearance.eyebrows", warn);
            if (a.FacialHair != null) ApplyAppearanceSlot(a.FacialHair.Style, catalog, "Beard", "appearance.facial_hair", warn);
        }

        void ApplyAppearanceSlot(string catalogId, AssetCatalog catalog, string umaSlot, string label, Action<string, string> warn)
        {
            if (string.IsNullOrEmpty(catalogId)) return;
            var umaRecipe = ResolveWardrobe(catalogId, catalog, umaSlot, warn, label);
            if (umaRecipe != null && !Avatar.SetSlot(umaRecipe))
                warn("wardrobe.incompatible", $"{label}: UMA recipe {umaRecipe.name} is not compatible with {RaceName}");
        }

        UMATextRecipe ResolveWardrobe(string catalogId, AssetCatalog catalog, string umaSlot, Action<string, string> warn, string label)
        {
            if (string.IsNullOrEmpty(catalogId)) return null;
            var entry = catalog.Get(catalogId);
            if (entry == null)
            {
                warn("catalog.unknown", $"{label}: catalog id {catalogId} not found in {catalog.Root}");
                return null;
            }
            var umaName = AssetCatalog.UmaRecipeFor(entry, _recipe.Base.Race);
            if (string.IsNullOrEmpty(umaName))
            {
                warn("wardrobe.missing", $"{label}: {catalogId} has no UMA recipe (status {entry.Status}); slot left empty");
                return null;
            }
            var umaRecipe = WardrobeLookup.Find(umaName);
            if (umaRecipe == null)
            {
                warn("wardrobe.missing", $"{label}: UMA wardrobe recipe {umaName} (for {catalogId}) was not found in the project");
                return null;
            }
            if (umaRecipe.wardrobeSlot != umaSlot)
                warn("wardrobe.slotMismatch", $"{label}: {umaName} is a {umaRecipe.wardrobeSlot} recipe, expected {umaSlot}");
            if (entry.Status == "placeholder")
                warn("catalog.placeholder", $"{label}: {catalogId} is a placeholder; UMA sample {umaName} stands in");
            return umaRecipe;
        }

        void ApplyColors(CharacterRecipe recipe, Action<string, string> warn)
        {
            var a = recipe.Appearance;
            SetColorIfGiven("Skin", a.Skin?.BaseColorSrgb, warn);
            SetColorIfGiven("Hair", a.Hair?.BaseColorSrgb, warn);
            SetColorIfGiven("Brows", a.Eyebrows?.ColorSrgb, warn);
            SetColorIfGiven("Eyes", a.Eyes?.IrisColorSrgb, warn);
            SetColorIfGiven("Sclera", a.Eyes?.ScleraColorSrgb, warn);
            if (a.FacialHair != null) SetColorIfGiven("Beard", a.FacialHair.ColorSrgb, warn);
        }

        // UMA 3's card hair / beard / brow shaders read their color from shader properties carried by the shared
        // color (see SRP/Colors/HairColors.asset), not from the albedo channel mask.
        static readonly HashSet<string> StrandColors = new HashSet<string> { "Hair", "Beard", "Brows" };

        void SetColorIfGiven(string sharedColor, string hex, Action<string, string> warn)
        {
            if (string.IsNullOrEmpty(hex)) return;
            if (!ColorUtility.TryParseHtmlString(hex, out var color))
            {
                warn("appearance.color", $"{sharedColor}: cannot parse color {hex}");
                return;
            }
            var data = new OverlayColorData(3) { name = sharedColor };
            data.channelMask[0] = color;
            if (StrandColors.Contains(sharedColor))
            {
                data.SetColorProperty("_BaseColor", color);
                data.SetColorProperty("_RootColor", color * 0.8f);
                data.SetColorProperty("_Tip_Color", Color.Lerp(color, Color.white, 0.15f));
            }
            // SetColor(name, OverlayColorData) copies only the albedo and metallic channels; SetRawColor keeps the property block.
            Avatar.SetRawColor(sharedColor, data, false);
        }

        // -- generation --------------------------------------------------------------------------------

        public bool Rebuild(float timeoutSeconds)
        {
            var started = DateTime.UtcNow;
            Avatar.GenerateNow();
            ApplyAdjusts();
            if (BodyRenderer == null && (DateTime.UtcNow - started).TotalSeconds < timeoutSeconds)
            {
                // GenerateNow is synchronous; a missing renderer means the build failed rather than that it is pending.
                return false;
            }
            RefreshBodyParameterNames();
            return BodyRenderer != null && BodyRenderer.sharedMesh != null && BodyRenderer.sharedMesh.vertexCount > 0;
        }

        void RefreshBodyParameterNames()
        {
            _bodyParameterNames.Clear();
            var dna = Avatar.GetDNA();
            foreach (var name in PreferredBodyDna)
                if (dna.ContainsKey(name)) _bodyParameterNames.Add(name);
            var skeleton = Avatar.skeleton;
            foreach (var adjust in Adjusts)
            {
                var present = skeleton != null;
                foreach (var bone in adjust.Bones) present &= skeleton != null && skeleton.HasBone(UMAUtils.StringToHash(bone));
                if (present) _bodyParameterNames.Add(adjust.Name);
            }
        }

        /// <summary>Re-apply the adjust parameters to the freshly generated skeleton (UMA rebuilds it every generation).</summary>
        void ApplyAdjusts()
        {
            var skeleton = Avatar.skeleton;
            if (skeleton == null) return;
            _basePositions.Clear();
            _baseScales.Clear();
            foreach (var adjust in Adjusts)
            {
                if (!_adjustValues.TryGetValue(adjust.Name, out var value) || Mathf.Abs(value - 0.5f) < 1e-4f) continue;
                foreach (var bone in adjust.Bones)
                {
                    var hash = UMAUtils.StringToHash(bone);
                    if (!skeleton.HasBone(hash)) continue;
                    if (adjust.IsOffset)
                    {
                        var basePosition = skeleton.GetPosition(hash);
                        var sign = basePosition.x < 0f ? -1f : 1f;   // outward on either side
                        var delta = Vector3.zero;
                        var offset = SkeletonAdjust.Offset(value) * sign;
                        if (adjust.Axis == Axis.X) delta.x = offset; else if (adjust.Axis == Axis.Y) delta.y = offset; else delta.z = offset;
                        // Bone positions are in the parent's frame; the offset is applied in world axes through the parent rotation.
                        var boneGo = skeleton.GetBoneGameObject(hash);
                        if (boneGo != null && boneGo.transform.parent != null)
                            delta = boneGo.transform.parent.InverseTransformVector(delta);
                        skeleton.SetPosition(hash, basePosition + delta);
                    }
                    else
                    {
                        var scale = skeleton.GetScale(hash);
                        var factor = SkeletonAdjust.Scale(value);
                        if (adjust.Axis == Axis.X) scale.x *= factor; else if (adjust.Axis == Axis.Y) scale.y *= factor; else scale.z *= factor;
                        skeleton.SetScale(hash, scale);
                    }
                }
            }
        }

        public IEnumerable<string> AllDnaNames() => Avatar.GetDNA().Keys;

        public Dictionary<string, float> GetBodyParameters()
        {
            var dna = Avatar.GetDNA();
            var values = new Dictionary<string, float>();
            foreach (var name in _bodyParameterNames)
            {
                if (dna.TryGetValue(name, out var setter)) values[name] = setter.Value;
                else values[name] = _adjustValues.TryGetValue(name, out var v) ? v : 0.5f;
            }
            return values;
        }

        public void SetBodyParameters(IReadOnlyDictionary<string, float> values)
        {
            var dna = Avatar.GetDNA();
            foreach (var kv in values)
            {
                if (dna.TryGetValue(kv.Key, out var setter)) setter.Set(Mathf.Clamp01(kv.Value));
                else if (kv.Key.StartsWith("adj:") || kv.Key.StartsWith("pos:")) _adjustValues[kv.Key] = Mathf.Clamp01(kv.Value);
            }
        }

        /// <summary>Set any DNA by UMA name (used by the face resolver); unknown names are reported through <paramref name="warn"/>.</summary>
        public void SetDna(IReadOnlyDictionary<string, float> values, Action<string, string> warn)
        {
            var dna = Avatar.GetDNA();
            foreach (var kv in values)
            {
                if (dna.TryGetValue(kv.Key, out var setter)) setter.Set(Mathf.Clamp01(kv.Value));
                else warn?.Invoke("face.dna", $"UMA race {RaceName} has no DNA {kv.Key}");
            }
        }

        public void SetFaceShape(IReadOnlyDictionary<string, float> shape, Action<string, string> warn)
        {
            SetDna(Resolve.FaceResolver.ToDna(shape), warn);
        }

        // -- geometry --------------------------------------------------------------------------------

        public SkinnedMeshRenderer BodyRenderer
        {
            get
            {
                if (Avatar == null) return null;
                try
                {
                    var renderer = Avatar.GetRenderer(0);
                    if (renderer != null) return renderer;
                }
                catch (Exception) { }
                return Root != null ? Root.GetComponentInChildren<SkinnedMeshRenderer>() : null;
            }
        }

        public IEnumerable<Renderer> AllRenderers => Root == null ? Enumerable.Empty<Renderer>() : Root.GetComponentsInChildren<Renderer>(false);

        public Transform Bone(string name)
        {
            if (Avatar == null) return null;
            try
            {
                var go = Avatar.GetBoneGameObject(name);
                if (go != null) return go.transform;
            }
            catch (Exception) { }
            return Root != null ? Root.GetComponentsInChildren<Transform>(true).FirstOrDefault(t => t.name == name) : null;
        }

        public string UmaRecipeString()
        {
            try { return Avatar.GetCurrentRecipe(); }
            catch (Exception) { return null; }
        }

        public static string UMAVersion()
        {
#if UNITY_EDITOR
            foreach (var guid in UnityEditor.AssetDatabase.FindAssets("package t:TextAsset", new[] { "Assets/UMA" }))
            {
                var path = UnityEditor.AssetDatabase.GUIDToAssetPath(guid);
                if (!path.EndsWith("Assets/UMA/package.json")) continue;
                var text = System.IO.File.ReadAllText(path);
                var match = System.Text.RegularExpressions.Regex.Match(text, "\"version\"\\s*:\\s*\"([^\"]+)\"");
                if (match.Success) return match.Groups[1].Value;
            }
#endif
            return "unknown";
        }

        public void Dispose()
        {
            if (Root != null) UnityEngine.Object.DestroyImmediate(Root);
            Root = null;
            Avatar = null;
        }
    }

    /// <summary>Find UMA wardrobe recipes by asset name: the asset database in the editor, the UMA index at runtime.</summary>
    public static class WardrobeLookup
    {
        public static UMATextRecipe Find(string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
#if UNITY_EDITOR
            foreach (var guid in UnityEditor.AssetDatabase.FindAssets($"{name} t:UMAWardrobeRecipe"))
            {
                var path = UnityEditor.AssetDatabase.GUIDToAssetPath(guid);
                var recipe = UnityEditor.AssetDatabase.LoadAssetAtPath<UMAWardrobeRecipe>(path);
                if (recipe != null && recipe.name == name) return recipe;
            }
#endif
            try { return UMAAssetIndexer.Instance.GetRecipe(name, false); }
            catch (Exception) { return null; }
        }
    }
}
