// Reads character/catalog/*.json (the same files the Python side validates) and resolves a catalog id to the
// runtime asset it names. Entries are kept as JObjects so a new catalog field never breaks the C# side.

using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;

namespace ProModeler.Catalog
{
    public class CatalogEntry
    {
        public string Id;
        public string Category;
        public string Name;
        public List<string> Slots = new List<string>();
        public string Status = "placeholder";
        public string UmaWardrobeRecipe;
        public Dictionary<string, string> UmaWardrobeRecipeByRace = new Dictionary<string, string>();
        public string Addressable;
        public string PromodelerAsset;   // assets/props/<name>.py: the garment is a promodeler prop attached at Socket, not a UMA recipe
        public string Socket;
        public string BaseColorSrgb;
        public JObject Raw;
    }

    public class AssetCatalog
    {
        public readonly Dictionary<string, CatalogEntry> Entries = new Dictionary<string, CatalogEntry>();
        public string Root;
        public string Version;

        public static AssetCatalog Load(string root, string version = null)
        {
            var catalog = new AssetCatalog { Root = root, Version = version };
            if (string.IsNullOrEmpty(root) || !Directory.Exists(root)) return catalog;
            foreach (var path in Directory.GetFiles(root, "*.json"))
            {
                if (Path.GetFileName(path) == "policy.json") continue;
                var document = JObject.Parse(File.ReadAllText(path));
                var entries = document["entries"] as JArray;
                if (entries == null) continue;
                foreach (var token in entries)
                {
                    var raw = token as JObject;
                    if (raw == null) continue;
                    var entry = new CatalogEntry
                    {
                        Id = (string)raw["id"],
                        Category = (string)raw["category"],
                        Name = (string)raw["name"],
                        Status = (string)raw["runtime"]?["status"] ?? "placeholder",
                        UmaWardrobeRecipe = (string)raw["runtime"]?["uma_wardrobe_recipe"],
                        Addressable = (string)raw["runtime"]?["addressable"],
                        PromodelerAsset = (string)raw["runtime"]?["promodeler_asset"],
                        Socket = (string)raw["runtime"]?["socket"],
                        BaseColorSrgb = (string)raw["base_color_srgb"],
                        Raw = raw,
                    };
                    var byRace = raw["runtime"]?["uma_wardrobe_recipe_by_race"] as JObject;
                    if (byRace != null) foreach (var prop in byRace.Properties()) entry.UmaWardrobeRecipeByRace[prop.Name] = (string)prop.Value;
                    var slots = raw["slots"] as JArray;
                    if (slots != null) foreach (var s in slots) entry.Slots.Add((string)s);
                    if (!string.IsNullOrEmpty(entry.Id)) catalog.Entries[entry.Id] = entry;
                }
            }
            return catalog;
        }

        /// <summary>The UMA recipe for a race: the per-race table first, then the race-neutral name.</summary>
        public static string UmaRecipeFor(CatalogEntry entry, string race)
        {
            if (entry == null) return null;
            if (!string.IsNullOrEmpty(race) && entry.UmaWardrobeRecipeByRace.TryGetValue(race, out var byRace) && !string.IsNullOrEmpty(byRace)) return byRace;
            return entry.UmaWardrobeRecipe;
        }

        public CatalogEntry Get(string id)
        {
            if (string.IsNullOrEmpty(id)) return null;
            return Entries.TryGetValue(id, out var entry) ? entry : null;
        }
    }
}
