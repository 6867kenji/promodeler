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
            if (m.HeadHeight.HasValue) targets["head_height"] = m.HeadHeight.Value;
            foreach (var kv in m.Circumferences) targets[kv.Key] = kv.Value;
            // Section extents: the blueprint's width/depth at each landmark. MHR could not hold them together with the
            // circumferences (memory: 05-woman hip); here they are fitted at half weight because UMA's torsos are wide
            // and flat and the circumference alone cannot say so.
            foreach (var section in m.CrossSections)
            {
                if (section.Width.HasValue) targets[section.Landmark + "_width"] = section.Width.Value;
                if (section.Depth.HasValue) targets[section.Landmark + "_depth"] = section.Depth.Value;
            }
            return targets;
        }

        public static Dictionary<string, float> Weights(CharacterRecipe recipe)
        {
            var weights = new Dictionary<string, float> { { "barefoot_height", 3f }, { "inseam", 2f }, { "shoulder_width", 1f }, { "head_height", 0.7f },
                                                          { "chest", 1.5f }, { "bust", 1.5f },  // the girth UMA misses most gets the most say
                                                          { "underbust", 0f } };  // measured and reported only: UMA's breasts cross the underbust plane, and chasing it drove breastSize to 0
            foreach (var section in recipe.Body.MeasurementsM.CrossSections)
            {
                // Circumferences lead (blueprint priority) and the extents are measured and reported only: blueprint
                // extents are ellipse-derived from the girth or contradict it, and at weight 0.25 they still bought chest
                // depth with inseam (karate-student: inseam -16 mm against a derived chest depth).
                weights[section.Landmark + "_width"] = 0f;
                weights[section.Landmark + "_depth"] = 0f;
            }
            return weights;
        }

        public Dictionary<string, float> Tolerances()
        {
            var t = _recipe.Body.TolerancesM;
            float height = t.TryGetValue("barefoot_height", out var h) ? h : 0.002f;
            float length = t.TryGetValue("length", out var l) ? l : 0.005f;
            float girth = t.TryGetValue("circumference", out var c) ? c : 0.005f;
            var tolerances = new Dictionary<string, float> { { "barefoot_height", height } };
            foreach (var name in new[] { "inseam", "shoulder_width", "foot_length", "head_height" }) tolerances[name] = length;
            foreach (var name in _recipe.Body.MeasurementsM.Circumferences.Keys) tolerances[name] = girth;
            foreach (var section in _recipe.Body.MeasurementsM.CrossSections)
            {
                tolerances[section.Landmark + "_width"] = 0.01f;
                tolerances[section.Landmark + "_depth"] = 0.01f;
            }
            return tolerances;
        }

        /// <summary>Seed values from body.shape: muscle and body_fat move the weight/muscle sliders before solving.</summary>
        public Dictionary<string, float> InitialParameters()
        {
            var initial = new Dictionary<string, float>();
            var current = _runtime.GetBodyParameters();
            foreach (var name in _runtime.BodyParameterNames) initial[name] = current.TryGetValue(name, out var v) ? v : 0.5f;
            // The head adjust only serves a head_height target. Without one it is a free height handle and the solver
            // bought height with it (karate-student ended with a 0.65x head).
            if (!_recipe.Body.MeasurementsM.HeadHeight.HasValue) initial.Remove("adj:head_height");
            var shape = _recipe.Body.Shape;
            if (shape.TryGetValue("body_fat", out var fat))
            {
                foreach (var name in new[] { "upperWeight", "lowerWeight", "belly" })
                    if (initial.ContainsKey(name)) initial[name] = Mathf.Lerp(0.3f, 0.8f, fat);
            }
            return initial;
        }

        public Dictionary<string, float> Measure()
        {
            return _measurer.Measure(_runtime.BodyRenderer, _runtime.Bone("Head"), _runtime.Bone("LeftArm"), _runtime.Bone("RightArm"));
        }

        /// <summary>Measurement deltas per parameter at 0 and 1 relative to the current values (metres). Restores the parameters.</summary>
        public Dictionary<string, Dictionary<string, Dictionary<string, float>>> Probe(IEnumerable<string> keys)
        {
            var saved = _runtime.GetBodyParameters();
            var baseline = Measure();
            var table = new Dictionary<string, Dictionary<string, Dictionary<string, float>>>();
            var keyList = new List<string>(keys);
            foreach (var name in new List<string>(_runtime.BodyParameterNames))  // Rebuild refreshes the live list
            {
                var entry = new Dictionary<string, Dictionary<string, float>>();
                foreach (var value in new[] { 0f, 1f })
                {
                    var probe = new Dictionary<string, float>(saved) { [name] = value };
                    _runtime.SetBodyParameters(probe);
                    if (!_runtime.Rebuild(60f)) continue;
                    var measured = Measure();
                    var deltas = new Dictionary<string, float>();
                    foreach (var key in keyList)
                        if (measured.TryGetValue(key, out var m) && baseline.TryGetValue(key, out var b)) deltas[key] = m - b;
                    entry[value == 0f ? "at_0" : "at_1"] = deltas;
                }
                table[name] = entry;
                Debug.Log($"[ProModeler] probe {name}: " + string.Join(" ", entry.Select(kv => kv.Key + "{" + string.Join(",", kv.Value.Select(d => $"{d.Key}:{d.Value * 1000f:+0}")) + "}")));
            }
            _runtime.SetBodyParameters(saved);
            _runtime.Rebuild(60f);
            return table;
        }

        public Resolved Solve(BuildReport report, int maxIterations = 14)
        {
            var solver = new MeasurementSolver { MaxIterations = maxIterations };
            var targets = Targets();
            var tolerances = Tolerances();
            var initial = InitialParameters();
            var weights = Weights(_recipe);

            if (_runtime is UMACharacterRuntime uma)
            {
                uma.ApplySemanticShape(_recipe.Body.Shape);  // muscle stays what the blueprint says
                if (!uma.Rebuild(60f)) throw new RecipeException("uma.rebuild", "character rebuild failed applying body.shape");
            }
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
                // Staged like the MHR fit (docs/01 8.5): lengths first with the skeletal parameters, then girths with the
                // shape parameters, then everything together. Solving all 20+ parameters at once from the race defaults
                // stalled in compromises that varied from character to character.
                Func<IReadOnlyDictionary<string, float>, Dictionary<string, float>> evaluate = values =>
                {
                    _runtime.SetBodyParameters(values);
                    if (!_runtime.Rebuild(60f)) throw new RecipeException("uma.rebuild", "character rebuild failed during the body solve");
                    return Measure();
                };
                var lengthTargets = new[] { "barefoot_height", "inseam", "shoulder_width", "foot_length", "head_height" };
                var lengthParameters = new[] { "height", "legsSize", "feetSize", "shoulderWidth", "adj:shoulder_length", "pos:arm_spread", "adj:head_height" };
                var current = new Dictionary<string, float>(initial);
                var stages = new[]
                {
                    ("lengths", lengthParameters, (Func<string, bool>)(t => Array.IndexOf(lengthTargets, t) >= 0), 6),
                    // Shape parameters also move lengths (lowerMuscle shifts the inseam by 13 cm over its range), so the
                    // girth stage keeps every target in view and only restricts which parameters may move.
                    ("girths", initial.Keys.Except(lengthParameters).ToArray(), (Func<string, bool>)(t => true), 8),
                    // Shape parameters drag the inseam and shoulders along; a second length pass puts them back before
                    // the joint refinement (the MHR fit alternates the same way, docs/01 8.5).
                    ("lengths2", lengthParameters, (Func<string, bool>)(t => Array.IndexOf(lengthTargets, t) >= 0), 4),
                    ("all", initial.Keys.ToArray(), (Func<string, bool>)(t => true), maxIterations),
                };
                result = null;
                var totalIterations = 0;
                foreach (var (stageName, parameterNames, targetFilter, iterations) in stages)
                {
                    var stageInitial = parameterNames.Where(current.ContainsKey).ToDictionary(n => n, n => current[n]);
                    var stageTargets = solvable.Where(kv => targetFilter(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
                    if (stageInitial.Count == 0 || stageTargets.Count == 0) continue;
                    var stageSolver = new MeasurementSolver { MaxIterations = iterations };
                    var fixedValues = current.Where(kv => !stageInitial.ContainsKey(kv.Key)).ToDictionary(kv => kv.Key, kv => kv.Value);
                    var stageResult = stageSolver.Solve(stageInitial, stageTargets, tolerances, values =>
                    {
                        var all = new Dictionary<string, float>(fixedValues);
                        foreach (var kv in values) all[kv.Key] = kv.Value;
                        return evaluate(all);
                    }, weights);
                    foreach (var kv in stageResult.Parameters) current[kv.Key] = kv.Value;
                    foreach (var line in stageResult.Log) Debug.Log($"[ProModeler] solve[{stageName}] " + line);
                    totalIterations += stageResult.Iterations;
                    result = stageResult;
                }
                result.Iterations = totalIterations;
                // The runtime still holds the last probe (a Jacobian column or a rejected step); restore the solution.
                _runtime.SetBodyParameters(current);
                if (!_runtime.Rebuild(60f)) throw new RecipeException("uma.rebuild", "character rebuild failed after the body solve");
                result.Parameters = current;
                result.Measured = Measure();
                Debug.Log("[ProModeler] solve restored: " + string.Join(", ", targets.Keys.Where(result.Measured.ContainsKey).Select(k => $"{k} {(result.Measured[k] - targets[k]) * 1000f:+0} mm")));
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
                if (kv.Key.EndsWith("_width") || kv.Key.EndsWith("_depth")) continue;  // extents are reported in the table, not as warnings
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
