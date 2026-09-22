// Damped Gauss-Newton over box-constrained 0..1 parameters with finite-difference Jacobians.
//
// The solver knows nothing about UMA: `evaluate` takes parameter values, rebuilds whatever it drives and returns
// measurements. Residuals are relative (measured / target - 1) so metres and millimetres weigh alike. Every
// iteration is logged so build.json can show what moved; nothing is silently clamped away - the final residuals
// are reported and compared with the recipe tolerances by the caller.

using System;
using System.Collections.Generic;
using System.Linq;

namespace ProModeler.Resolve
{
    public class MeasurementSolver
    {
        public class Result
        {
            public Dictionary<string, float> Parameters = new Dictionary<string, float>();
            public Dictionary<string, float> Measured = new Dictionary<string, float>();
            public Dictionary<string, float> Residuals = new Dictionary<string, float>();   // measured - target, metres
            public int Iterations;
            public int Evaluations;
            public List<string> Log = new List<string>();
            public bool Converged;
        }

        public float FiniteDifferenceStep = 0.08f;
        public float Damping = 0.3f;
        public float MaxStep = 0.35f;
        public int MaxIterations = 14;
        public int MaxDampingRetries = 4;
        public int MaxStepRefinements = 2;   // on a stall, halve the finite-difference step and rebuild the Jacobian

        public Result Solve(
            IReadOnlyDictionary<string, float> initial,
            IReadOnlyDictionary<string, float> targets,
            IReadOnlyDictionary<string, float> tolerances,
            Func<IReadOnlyDictionary<string, float>, Dictionary<string, float>> evaluate,
            IReadOnlyDictionary<string, float> weights = null)
        {
            var result = new Result();
            var names = initial.Keys.OrderBy(k => k).ToList();
            var measureNames = targets.Keys.OrderBy(k => k).ToList();
            var x = names.Select(n => Clamp01(initial[n])).ToArray();
            var n = names.Length();
            var m = measureNames.Count;

            Dictionary<string, float> measured = Evaluate(evaluate, names, x, result);
            var r = Residuals(measured, targets, measureNames, weights);
            result.Log.Add($"start: {Describe(measured, targets, measureNames)}");

            var fdStep = FiniteDifferenceStep;
            var refinements = 0;
            for (var iteration = 0; iteration < MaxIterations; iteration++)
            {
                if (Within(measured, targets, tolerances, measureNames))
                {
                    result.Converged = true;
                    break;
                }
                // Jacobian by forward differences (backward when a parameter sits at the upper bound).
                var J = new float[m, n];
                for (var j = 0; j < n; j++)
                {
                    var step = x[j] + fdStep <= 1f ? fdStep : -fdStep;
                    var probe = (float[])x.Clone();
                    probe[j] = Clamp01(x[j] + step);
                    var actual = probe[j] - x[j];
                    if (Math.Abs(actual) < 1e-6f) continue;
                    var probed = Evaluate(evaluate, names, probe, result);
                    var rp = Residuals(probed, targets, measureNames, weights);
                    for (var i = 0; i < m; i++) J[i, j] = (rp[i] - r[i]) / actual;
                }
                // (J^T J + lambda I) dx = -J^T r, with lambda raised while the step does not improve (Levenberg-Marquardt).
                var lambda = Damping;
                float[] next = null;
                Dictionary<string, float> nextMeasured = null;
                float[] nextR = null;
                var improved = false;
                for (var retry = 0; retry <= MaxDampingRetries && !improved; retry++)
                {
                    var A = new float[n, n];
                    var b = new float[n];
                    for (var j = 0; j < n; j++)
                    {
                        for (var k = 0; k < n; k++)
                        {
                            var s = 0f;
                            for (var i = 0; i < m; i++) s += J[i, j] * J[i, k];
                            A[j, k] = s + (j == k ? lambda : 0f);
                        }
                        var t = 0f;
                        for (var i = 0; i < m; i++) t += J[i, j] * r[i];
                        b[j] = -t;
                    }
                    var dx = SolveLinear(A, b);
                    var scale = 1f;
                    var largest = dx.Max(v => Math.Abs(v));
                    if (largest > MaxStep) scale = MaxStep / largest;
                    next = new float[n];
                    for (var j = 0; j < n; j++) next[j] = Clamp01(x[j] + dx[j] * scale);
                    nextMeasured = Evaluate(evaluate, names, next, result);
                    nextR = Residuals(nextMeasured, targets, measureNames, weights);
                    improved = Norm(nextR) < Norm(r);
                    if (!improved) lambda *= 4f;
                }
                if (!improved)
                {
                    if (refinements < MaxStepRefinements)
                    {
                        refinements++;
                        fdStep *= 0.5f;
                        Damping = Math.Max(Damping, 0.3f);
                        result.Log.Add($"iteration {iteration + 1}: no improving step; refining the finite-difference step to {fdStep:F3}");
                        continue;
                    }
                    result.Log.Add($"iteration {iteration + 1}: no improving step after {MaxDampingRetries} damping increases and {refinements} refinements; stopping");
                    break;
                }
                Damping = Math.Max(Damping * 0.5f, lambda * 0.25f);
                x = next;
                measured = nextMeasured;
                r = nextR;
                result.Iterations = iteration + 1;
                result.Log.Add($"iteration {iteration + 1}: {Describe(measured, targets, measureNames)}");
            }
            if (!result.Converged) result.Converged = Within(measured, targets, tolerances, measureNames);
            for (var j = 0; j < n; j++) result.Parameters[names[j]] = x[j];
            result.Measured = measured;
            foreach (var name in measureNames)
                if (measured.ContainsKey(name)) result.Residuals[name] = measured[name] - targets[name];
            return result;
        }

        static Dictionary<string, float> Evaluate(Func<IReadOnlyDictionary<string, float>, Dictionary<string, float>> evaluate, List<string> names, float[] x, Result result)
        {
            var values = new Dictionary<string, float>();
            for (var j = 0; j < names.Count; j++) values[names[j]] = x[j];
            result.Evaluations++;
            return evaluate(values);
        }

        static float[] Residuals(Dictionary<string, float> measured, IReadOnlyDictionary<string, float> targets, List<string> names, IReadOnlyDictionary<string, float> weights)
        {
            var r = new float[names.Count];
            for (var i = 0; i < names.Count; i++)
            {
                var name = names[i];
                if (!measured.TryGetValue(name, out var value) || targets[name] <= 0f) { r[i] = 0f; continue; }
                var w = weights != null && weights.TryGetValue(name, out var ww) ? ww : 1f;
                r[i] = w * (value / targets[name] - 1f);
            }
            return r;
        }

        static bool Within(Dictionary<string, float> measured, IReadOnlyDictionary<string, float> targets, IReadOnlyDictionary<string, float> tolerances, List<string> names)
        {
            foreach (var name in names)
            {
                if (!measured.TryGetValue(name, out var value)) return false;
                var tolerance = tolerances != null && tolerances.TryGetValue(name, out var t) ? t : 0.005f;
                if (Math.Abs(value - targets[name]) > tolerance) return false;
            }
            return true;
        }

        static string Describe(Dictionary<string, float> measured, IReadOnlyDictionary<string, float> targets, List<string> names)
        {
            return string.Join(", ", names.Select(nm => measured.TryGetValue(nm, out var v) ? $"{nm} {(v - targets[nm]) * 1000f:+0} mm" : $"{nm} n/a"));
        }

        static float Norm(float[] r)
        {
            var s = 0f;
            foreach (var v in r) s += v * v;
            return s;
        }

        static float Clamp01(float v) => v < 0f ? 0f : (v > 1f ? 1f : v);

        /// <summary>Gaussian elimination with partial pivoting; A is symmetric positive definite after damping.</summary>
        public static float[] SolveLinear(float[,] A, float[] b)
        {
            var n = b.Length;
            var M = (float[,])A.Clone();
            var v = (float[])b.Clone();
            for (var col = 0; col < n; col++)
            {
                var pivot = col;
                for (var row = col + 1; row < n; row++) if (Math.Abs(M[row, col]) > Math.Abs(M[pivot, col])) pivot = row;
                if (Math.Abs(M[pivot, col]) < 1e-12f) continue;
                if (pivot != col)
                {
                    for (var k = 0; k < n; k++) { var tmp = M[col, k]; M[col, k] = M[pivot, k]; M[pivot, k] = tmp; }
                    var tb = v[col]; v[col] = v[pivot]; v[pivot] = tb;
                }
                for (var row = col + 1; row < n; row++)
                {
                    var f = M[row, col] / M[col, col];
                    if (f == 0f) continue;
                    for (var k = col; k < n; k++) M[row, k] -= f * M[col, k];
                    v[row] -= f * v[col];
                }
            }
            var x = new float[n];
            for (var row = n - 1; row >= 0; row--)
            {
                var s = v[row];
                for (var k = row + 1; k < n; k++) s -= M[row, k] * x[k];
                x[row] = Math.Abs(M[row, row]) < 1e-12f ? 0f : s / M[row, row];
            }
            return x;
        }
    }

    static class ListExtensions
    {
        public static int Length(this List<string> list) => list.Count;
    }
}
