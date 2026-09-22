// JSON settings shared by every promodeler document: snake_case keys, nulls written explicitly, unknown keys rejected
// so a recipe field the C# side does not know about fails loudly instead of being dropped.

using System;
using System.IO;
using Newtonsoft.Json;
using Newtonsoft.Json.Serialization;

namespace ProModeler.Recipe
{
    public static class RecipeJson
    {
        public static readonly JsonSerializerSettings Settings = new JsonSerializerSettings
        {
            ContractResolver = new DefaultContractResolver { NamingStrategy = new SnakeCaseNamingStrategy() },
            NullValueHandling = NullValueHandling.Include,
            MissingMemberHandling = MissingMemberHandling.Error,
            Formatting = Formatting.Indented,
        };

        public static readonly JsonSerializerSettings LenientSettings = new JsonSerializerSettings
        {
            ContractResolver = new DefaultContractResolver { NamingStrategy = new SnakeCaseNamingStrategy() },
            NullValueHandling = NullValueHandling.Include,
            MissingMemberHandling = MissingMemberHandling.Ignore,
            Formatting = Formatting.Indented,
        };

        public static T Read<T>(string path, bool strict = true)
        {
            if (!File.Exists(path)) throw new FileNotFoundException("Recipe file not found", path);
            var text = File.ReadAllText(path);
            return JsonConvert.DeserializeObject<T>(text, strict ? Settings : LenientSettings);
        }

        public static string Write(object value)
        {
            return JsonConvert.SerializeObject(value, Settings) + "\n";
        }

        public static void WriteFile(string path, object value)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, Write(value));
        }
    }

    public class RecipeException : Exception
    {
        public readonly string Code;

        public RecipeException(string code, string message) : base(code + ": " + message)
        {
            Code = code;
        }
    }

    public static class RecipeLoader
    {
        public static CharacterRecipe LoadCharacter(string path)
        {
            var recipe = RecipeJson.Read<CharacterRecipe>(path);
            if (recipe.Schema != CharacterRecipe.SchemaId)
                throw new RecipeException("recipe.schema", $"{path}: schema {recipe.Schema} is not {CharacterRecipe.SchemaId}");
            if (string.IsNullOrEmpty(recipe.Id)) throw new RecipeException("recipe.id", $"{path}: id is required");
            if (recipe.Body?.MeasurementsM == null || recipe.Body.MeasurementsM.BarefootHeight <= 0f)
                throw new RecipeException("measurements.range", $"{path}: body.measurements_m.barefoot_height is required");
            return recipe;
        }

        public static OutfitRecipe LoadOutfit(string path)
        {
            var outfit = RecipeJson.Read<OutfitRecipe>(path);
            if (outfit.Schema != OutfitRecipe.SchemaId)
                throw new RecipeException("outfit.schema", $"{path}: schema {outfit.Schema} is not {OutfitRecipe.SchemaId}");
            return outfit;
        }

        /// <summary>The character dressed in the outfit: wardrobe replaced, hair style overridden, body untouched.</summary>
        public static CharacterRecipe ApplyOutfit(CharacterRecipe recipe, OutfitRecipe outfit)
        {
            if (outfit == null) return recipe;
            if (outfit.BaseCharacter != recipe.Id)
                throw new RecipeException("outfit.base", $"outfit {outfit.Id} is for {outfit.BaseCharacter}, not {recipe.Id}");
            var dressed = JsonConvert.DeserializeObject<CharacterRecipe>(JsonConvert.SerializeObject(recipe, RecipeJson.Settings), RecipeJson.Settings);
            dressed.Wardrobe = new System.Collections.Generic.List<Garment>(outfit.Wardrobe);
            if (outfit.Barefoot) dressed.Wardrobe.RemoveAll(g => g.Slot == "footwear");
            if (outfit.HairOverride != null && !string.IsNullOrEmpty(outfit.HairOverride.Style))
                dressed.Appearance.Hair.Style = outfit.HairOverride.Style;
            foreach (var clip in outfit.ClipsExtra) dressed.Animation.Clips.Add(clip);
            return dressed;
        }
    }
}
