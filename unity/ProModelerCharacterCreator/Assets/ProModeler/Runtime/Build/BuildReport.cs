// build.json written by the batch build (schemas/character_build.schema.json). Key names follow the Blender kernel's
// report.json so promodeler.contact_sheet and `promodeler character check` read both.

using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace ProModeler.Build
{
    public class BuildError
    {
        public string Code;
        public string Message;
        public string Stack;
    }

    public class Resolved
    {
        public string Race;
        public Dictionary<string, float> Dna = new Dictionary<string, float>();
        public float RootScale = 1f;
        public int Iterations;
        public Dictionary<string, float> ResidualsM = new Dictionary<string, float>();
    }

    public class WardrobeEntry
    {
        public string Slot;
        public string CatalogId;
        public string Resolved;
        public bool Fitted;
    }

    public class AccessoryEntry
    {
        public string Id;
        public string Source;
        public string Socket;
        public bool Attached;
    }

    public class ClipEntry
    {
        public string Id;
        public string Directory;     // PNG frames f_0000.png ... (the bridge encodes them)
        public int Frames;
        public int Fps;
        public float DurationS;
        public bool Loop;
        public string Description;
        public bool Written;
        public float Seconds;
    }

    public class RenderEntry
    {
        public string View;
        public string Pass = "shaded";
        public string Path;
        public bool Written;
        public float Seconds;
    }

    public class FileEntry
    {
        public string Path;
        public bool Written;
        public long Bytes;
    }

    public class Warning
    {
        public string Code;
        public string Message;

        public Warning(string code, string message) { Code = code; Message = message; }
    }

    public class BuildReport
    {
        public string Status = "failed";
        public string RecipeHash;
        public BuildError Error;
        public Dictionary<string, string> Environment = new Dictionary<string, string>();
        public Resolved Resolved;
        public JObject MeasuredM = new JObject();
        public Dictionary<string, Dictionary<string, int>> Parts = new Dictionary<string, Dictionary<string, int>>();
        public Dictionary<string, float> Totals = new Dictionary<string, float>();
        public List<WardrobeEntry> Wardrobe = new List<WardrobeEntry>();
        public List<AccessoryEntry> Accessories = new List<AccessoryEntry>();
        public List<RenderEntry> Renders = new List<RenderEntry>();
        public List<ClipEntry> Clips = new List<ClipEntry>();
        public JObject ContactSheet;
        public Dictionary<string, object> Exports = new Dictionary<string, object>();
        public List<Warning> Warnings = new List<Warning>();
        public float Seconds;

        public void Warn(string code, string message)
        {
            Warnings.Add(new Warning(code, message));
            UnityEngine.Debug.LogWarning($"[ProModeler] {code}: {message}");
        }
    }
}
