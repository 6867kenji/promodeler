// Metric body measurements -> character body parameters (docs/03, chapter 10.3).
//
// The resolver never sees UMA names directly: the runtime exposes its 0..1 body parameters, the measurer returns
// metres, and MeasurementSolver closes the loop. Semantic sliders (body.shape) seed the start point; the final
// root scale nudges the height into its 2 mm tolerance when the parameter space cannot.

using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Measure;
using ProModeler.Recipe;
using ProModeler.Runtime;

namespace ProModeler.Resolve
{
    public class BodyResolver
    {
        public const float MinRootScale = 0.98f;
        public const float MaxRootScale = 1.02f;

        readonly ICharacterRuntime _runtime;
        readonly BodyMeasurer _measurer;
        readonly CharacterRecipe _recipe;

        public BodyResolver(ICharacterRuntime runtime, BodyMeasurer measurer, CharacterRecipe recipe)
        {
            _runtime = runtime;
            _measurer = measurer;
            _recipe = recipe;
        }

        /// <summary>Metric targets the runtime can be measured against, keyed like BodyMeasurer output.</summary>
        public Dictionary<string, float> Targets()
        {
            var m = _recipe.Body.MeasurementsM;
            var targets = new Dictionary<string, float> { { "barefoot_height", m.BarefootHeight } };
            if (m.Inseam.HasValue) targets["inseam"] = m.Inseam.Value;
            if (m.ShoulderWidth.HasValue) targets["shoulder_width"] = m.ShoulderWidth.Value;
            if (m.FootLength.HasValue) targets["foot_length"] = m.FootLength.Value;
            foreach (var kv in m.Circumferences) targets[kv.Key] = kv.Value;
            return targets;
        }

        public Dictionary<string, float> Tolerances()
        {
            var t = _recipe.Body.TolerancesM;
            float height = t.TryGetValue("barefoot_height", out var h) ? h : 0.002f;
            float length = t.TryGetValue("length", out var l) ? l : 0.005f;
            float girth = t.TryGetValue("circumference", out var c) ? c : 0.005f;
            var tolerances = new Dictionary<string, float> { { "barefoot_height", height } };
            foreach (var name in new[] { "inseam", "shoulder_width", "foot_length" }) tolerances[name] = length;
            foreach (var name in _recipe.Body.MeasurementsM.Circumferences.Keys) tolerances[name] = girth;
            return tolerances;
        }

        /// <summary>Seed values from body.shape: muscle and body_fat move the weight/muscle sliders before solving.</summary>
        public Dictionary<string, float> InitialParameters()
        {
            var initial = new Dictionary<string, float>();
            var current = _runtime.GetBodyParameters();
            foreach (var name in _runtime.BodyParameterNames) initial[name] = current.TryGetValue(name, out var v) ? v : 0.5f;
            var shape = _recipe.Body.Shape;
            if (shape.TryGetValue("body_fat", out var fat))
            {
                foreach (var name in new[] { "upperWeight", "lowerWeight", "belly" })
                    if (initial.ContainsKey(name)) initial[name] = Mathf.Lerp(0.3f, 0.8f, fat);
            }
            if (shape.TryGetValue("muscle", out var muscle))
            {
                foreach (var name in new[] { "upperMuscle", "lowerMuscle" })
                    if (initial.ContainsKey(name)) initial[name] = Mathf.Lerp(0.2f, 0.8f, muscle);
            }
            return initial;
        }

        public Dictionary<string, float> Measure()
        {
            return _measurer.Measure(_runtime.BodyRenderer, _runtime.Bone("Head"), _runtime.Bone("LeftArm"), _runtime.Bone("RightArm"));
        }

        public Resolved Solve(BuildReport report, int maxIterations = 10)
        {
            var solver = new MeasurementSolver { MaxIterations = maxIterations };
            var targets = Targets();
            var tolerances = Tolerances();
            var initial = InitialParameters();
            var weights = new Dictionary<string, float> { { "barefoot_height", 3f }, { "inseam", 1.5f }, { "shoulder_width", 1.5f } };

            // Only solve for targets the measurer can produce on this body.
            var probe = Measure();
            var solvable = targets.Where(kv => probe.ContainsKey(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
            foreach (var missing in targets.Keys.Except(solvable.Keys))
                report.Warn("resolve.unmeasured", $"{missing} cannot be measured on this body; not solved");

            MeasurementSolver.Result result;
            if (initial.Count == 0)
            {
                report.Warn("resolve.noParameters", "the runtime exposes none of the preferred body parameters; body left at race defaults");
                result = new MeasurementSolver.Result { Measured = probe };
            }
            else
            {
                result = solver.Solve(initial, solvable, tolerances, values =>
                {
                    _runtime.SetBodyParameters(values);
                    if (!_runtime.Rebuild(60f)) throw new RecipeException("uma.rebuild", "character rebuild failed during the body solve");
                    return Measure();
                }, weights);
                foreach (var line in result.Log) Debug.Log("[ProModeler] solve " + line);
                // The runtime still holds the last probe (a Jacobian column or a rejected step); restore the solution.
                _runtime.SetBodyParameters(result.Parameters);
                if (!_runtime.Rebuild(60f)) throw new RecipeException("uma.rebuild", "character rebuild failed after the body solve");
                result.Measured = Measure();
            }

            // Root scale as the last resort for the strict height tolerance.
            var rootScale = 1f;
            if (result.Measured.TryGetValue("barefoot_height", out var measuredHeight) && measuredHeight > 0f)
            {
                var wanted = targets["barefoot_height"] / measuredHeight;
                rootScale = Mathf.Clamp(wanted, MinRootScale, MaxRootScale);
                if (Mathf.Abs(rootScale - 1f) > 1e-4f)
                {
                    _runtime.Root.transform.localScale = Vector3.one * rootScale;
                    if (Mathf.Abs(wanted - rootScale) > 1e-4f)
                        report.Warn("resolve.rootScale", $"height needs root scale {wanted:F4}, clamped to {rootScale:F4}");
                }
            }

            var final = Measure();
            var residuals = new Dictionary<string, float>();
            foreach (var kv in targets)
                if (final.TryGetValue(kv.Key, out var value)) residuals[kv.Key] = value - kv.Value;
            foreach (var kv in residuals)
            {
                var tolerance = tolerances.TryGetValue(kv.Key, out var t) ? t : 0.005f;
                if (Mathf.Abs(kv.Value) > tolerance)
                    report.Warn("resolve.residual", $"{kv.Key} residual {kv.Value * 1000f:+0.0} mm exceeds tolerance {tolerance * 1000f:0} mm");
            }
            var resolved = new Resolved
            {
                Race = _runtime.RaceName,
                Dna = new Dictionary<string, float>(result.Parameters),
                RootScale = rootScale,
                Iterations = result.Iterations,
                ResidualsM = residuals,
            };
            return resolved;
        }
    }
}
