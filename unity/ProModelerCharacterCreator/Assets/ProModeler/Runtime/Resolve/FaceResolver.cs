// recipe face.shape (anatomical 0..1 sliders, 0.5 neutral) -> UMA 3 face DNA names (docs/03, 10.4).
// Only sliders that leave 0.5 are written, so the race's default face stays untouched where the recipe is silent.

using System.Collections.Generic;
using UnityEngine;

namespace ProModeler.Resolve
{
    public static class FaceResolver
    {
        /// <summary>Initial table; a slider may drive several DNA. Refine per race once faces are compared against references (M11).</summary>
        public static readonly Dictionary<string, string[]> Table = new Dictionary<string, string[]>
        {
            { "face_length", new[] { "jawsPosition", "chinPosition" } },
            { "jaw_width", new[] { "mandibleSize" } },
            { "chin_size", new[] { "chinSize" } },
            { "cheek_width", new[] { "cheekWidth" } },
            { "nose_width", new[] { "noseWidth" } },
            { "nose_length", new[] { "noseSize" } },
            { "nose_bridge", new[] { "noseCurve" } },
            { "eye_size", new[] { "eyeSize" } },
            { "eye_spacing", new[] { "eyeSpacing" } },
            { "eye_tilt", new[] { "eyeRotation" } },
            { "mouth_width", new[] { "mouthSize" } },
            { "lip_thickness", new[] { "lipsSize" } },
            { "brow_height", new[] { "BrowPosition" } },
            { "forehead_height", new[] { "foreheadSize" } },
        };

        public static Dictionary<string, float> ToDna(IReadOnlyDictionary<string, float> shape)
        {
            var dna = new Dictionary<string, float>();
            if (shape == null) return dna;
            foreach (var kv in shape)
            {
                if (Mathf.Abs(kv.Value - 0.5f) < 1e-4f) continue;
                if (!Table.TryGetValue(kv.Key, out var names)) continue;
                foreach (var name in names) dna[name] = Mathf.Clamp01(kv.Value);
            }
            return dna;
        }
    }
}
