// The one seam between recipes and a character system (docs/03, 9.2 / original proposal section 11).
// UMACharacterRuntime is the first implementation; a future MHR-based race or another system implements the same.

using System;
using System.Collections.Generic;
using UnityEngine;
using ProModeler.Catalog;
using ProModeler.Recipe;

namespace ProModeler.Runtime
{
    public interface ICharacterRuntime : IDisposable
    {
        GameObject Root { get; }

        /// <summary>Pick the base race, wardrobe and colors for the recipe. Unresolvable references go to <paramref name="warn"/>.</summary>
        void Create(CharacterRecipe recipe, AssetCatalog catalog, Action<string, string> warn);

        /// <summary>Names of the body parameters the resolver may move (0..1), all in the runtime's own vocabulary.</summary>
        IReadOnlyList<string> BodyParameterNames { get; }

        Dictionary<string, float> GetBodyParameters();

        void SetBodyParameters(IReadOnlyDictionary<string, float> values);

        /// <summary>Apply 0..1 face sliders in the recipe vocabulary (face_length, jaw_width, ...).</summary>
        void SetFaceShape(IReadOnlyDictionary<string, float> shape, Action<string, string> warn);

        /// <summary>Regenerate the mesh synchronously. Returns false when the character system did not finish within the timeout.</summary>
        bool Rebuild(float timeoutSeconds);

        SkinnedMeshRenderer BodyRenderer { get; }

        /// <summary>All renderers that make up the character (body, hair, wardrobe), for triangle counts, clay passes and export.</summary>
        IEnumerable<Renderer> AllRenderers { get; }

        /// <summary>Find a bone by its Humanoid-style name (Head, LeftArm, RightArm, LeftHand, ...).</summary>
        Transform Bone(string name);

        string RaceName { get; }

        string Version { get; }
    }
}
