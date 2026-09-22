// DTOs for promodeler-character/1.0 and promodeler-outfit/1.0 (schemas/character_recipe.schema.json).
// Field names are the snake_case JSON keys via the SnakeCase naming strategy in RecipeJson; keep this file
// structurally identical to promodeler/character/recipe.py. No UMA names belong here.

using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ProModeler.Recipe
{
    public class Source
    {
        public string Kind = "blueprint";
        public string Path;
        public string Sha256;
        public int GeneratorVersion = 1;
        public string CatalogVersion;
    }

    public class Identity
    {
        public bool Fictional = true;
        public string Sex = "female";
        public int? Age;
        public List<string> Descriptors = new List<string>();
    }

    public class Base
    {
        public string Skeleton = "humanoid_a_pose";
        public string Race = "human_female";
    }

    public class CrossSection
    {
        public string Landmark;
        public float Height;
        public float? Width;
        public float? Depth;
        public float? Circumference;
    }

    public class Measurements
    {
        public float BarefootHeight;
        public float? Inseam;
        public float? ShoulderWidth;
        public float? FootLength;
        public float? HeadHeight;
        public Dictionary<string, float> Circumferences = new Dictionary<string, float>();
        public List<CrossSection> CrossSections = new List<CrossSection>();
    }

    public class ReferenceFit
    {
        public string Solver;
        public int FitVersion;
        public Dictionary<string, float> MeasuredM = new Dictionary<string, float>();
        public Dictionary<string, float> ResidualsM = new Dictionary<string, float>();
        public float? Seconds;
        public string Note;
    }

    public class Body
    {
        public Measurements MeasurementsM = new Measurements();
        public Dictionary<string, float> Shape = new Dictionary<string, float>();
        public Dictionary<string, float> TolerancesM = new Dictionary<string, float>();
        public ReferenceFit ReferenceFit;
    }

    public class Face
    {
        public Dictionary<string, float?> MetricsM = new Dictionary<string, float?>();
        public Dictionary<string, float> Shape = new Dictionary<string, float>();
        public List<string> Descriptors = new List<string>();
    }

    public class Skin
    {
        public string Preset;
        public string BaseColorSrgb;
        public float[] Roughness;
    }

    public class Hair
    {
        public string Style;
        public string BaseColorSrgb;
        public float? LengthM;
    }

    public class Eyebrows
    {
        public string Style;
        public string ColorSrgb;
    }

    public class Eyes
    {
        public string IrisColorSrgb;
        public string ScleraColorSrgb;
    }

    public class FacialHair
    {
        public string Style;
        public string ColorSrgb;
    }

    public class Teeth
    {
        public string Preset;
        public string BaseColorSrgb;
    }

    public class Appearance
    {
        public Skin Skin = new Skin();
        public Hair Hair = new Hair();
        public Eyebrows Eyebrows = new Eyebrows();
        public Eyes Eyes = new Eyes();
        public FacialHair FacialHair;
        public Teeth Teeth = new Teeth();
    }

    public class GarmentMaterial
    {
        public string BaseColorSrgb;
        public float[] Roughness;
        public float? Metallic;
    }

    public class Garment
    {
        public string Slot;
        public string CatalogId;
        public string BlueprintGarment;
        public string Name;
        public GarmentMaterial Material;
        public Dictionary<string, float> FinishedMeasurementsM = new Dictionary<string, float>();
        public string Deformation;
        public string Construction;
        public float? SoleHeightM;
        public float? HeelHeightM;
        public float? InternalLengthM;
        public JObject Controls = new JObject();
    }

    public class AccessorySource
    {
        public string Kind = "promodeler_asset";
        public string CatalogId;
        public string Path;
        public string BuildHash;
    }

    public class Accessory
    {
        public string Id;
        public AccessorySource Source = new AccessorySource();
        public string Socket;
        public float[] SizeXyzM;
        public string Detail;
        public JObject Physics = new JObject();
    }

    public class ClipSpec
    {
        public string Id;
        public float DurationS;
        public bool Loop;
        public string Description;
    }

    public class Animation
    {
        public string RestPose = "a_pose_35deg";
        public Dictionary<string, float[]> LimitsDeg = new Dictionary<string, float[]>();
        public List<string> FaceShapes = new List<string>();
        public List<ClipSpec> Clips = new List<ClipSpec>();
    }

    public class CharacterRecipe
    {
        public const string SchemaId = "promodeler-character/1.0";

        public string Schema;
        public string Id;
        public string Name = "";
        public int Seed;
        public Source Source = new Source();
        public Identity Identity = new Identity();
        public Base Base = new Base();
        public Body Body = new Body();
        public Face Face = new Face();
        public Appearance Appearance = new Appearance();
        public List<Garment> Wardrobe = new List<Garment>();
        public List<Accessory> Accessories = new List<Accessory>();
        public Animation Animation = new Animation();
        public JObject Physics = new JObject();
        public JObject Target = new JObject();
        public List<string> Acceptance = new List<string>();

        public Garment GarmentInSlot(string slot)
        {
            foreach (var g in Wardrobe) if (g.Slot == slot) return g;
            return null;
        }
    }

    public class OutfitRecipe
    {
        public const string SchemaId = "promodeler-outfit/1.0";

        public string Schema;
        public string Id;
        public string BaseCharacter;
        public string Name = "";
        public Source Source = new Source();
        public string BodyPolicy = "keep";
        public bool Barefoot;
        public List<Garment> Wardrobe = new List<Garment>();
        public Hair HairOverride;
        public List<string> ExtraBones = new List<string>();
        public JObject Controls = new JObject();
        public List<ClipSpec> ClipsExtra = new List<ClipSpec>();
        public JObject Physics = new JObject();
        public JObject Target = new JObject();
        public List<string> Acceptance = new List<string>();
    }
}
