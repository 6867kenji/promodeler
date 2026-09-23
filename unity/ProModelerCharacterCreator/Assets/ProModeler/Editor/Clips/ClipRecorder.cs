// Records the recipe's animation.clips as PNG frame sequences (docs/03 M13). No motion capture ships with UMA 3, so
// the clips are procedural poses driven on the UMA skeleton in world axes from the rest pose: idle (breathing, head
// sway), walk (in-place leg and arm swing, hip bob), turn (180 degrees about the root), sit (hips and knees to 90
// degrees, root lowered to the seat height), raise-arms (abduction to the recipe's shoulder_raise limit),
// physics-settle (idle, walk, idle) and device (right forearm raised, head down). They exercise the skinning, the
// attachments and the rig limits for the verification videos; they are not performance animation. The bridge
// encodes the frames to MP4 (ffmpeg) or GIF (Pillow).

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Recipe;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class ClipRecorder
    {
        public static readonly string[] KnownClips = { "idle", "walk", "turn", "sit", "raise-arms", "physics-settle", "device" };

        static readonly string[] PoseBones =
        {
            "Hips", "Spine", "Spine1", "Neck", "Head", "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "RightShoulder", "RightArm", "RightForeArm", "RightHand",
            "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
        };

        public static List<ClipEntry> Record(UMACharacterRuntime runtime, CharacterRecipe recipe, IEnumerable<string> clipIds, string directory,
                                             int fps, float maxSeconds, int resolution, BuildReport report)
        {
            var entries = new List<ClipEntry>();
            var wanted = clipIds.Select(c => c.Trim()).Where(c => c.Length > 0).ToList();
            var specs = recipe.Animation.Clips.Where(c => wanted.Count == 0 || wanted.Contains(c.Id)).ToList();
            foreach (var id in wanted.Where(id => specs.All(s => s.Id != id)))
                specs.Add(new ClipSpec { Id = id, DurationS = 3f, Loop = id == "idle" || id == "walk", Description = "requested on the command line" });
            if (specs.Count == 0) return entries;

            var animator = runtime.Root.GetComponentInChildren<Animator>();
            var animatorWasEnabled = animator != null && animator.enabled;
            if (animator != null) animator.enabled = false;   // the recorder owns the bones while it runs

            var bones = PoseBones.Select(runtime.Bone).Where(b => b != null).ToArray();
            // A manual render request does not run the player loop's skinning update, so the skinned mesh would keep
            // showing the pose of the last editor tick; force the bone matrices to be recomputed for every render.
            var skinned = runtime.AllRenderers.OfType<SkinnedMeshRenderer>().ToList();
            var forced = skinned.ToDictionary(r => r, r => r.forceMatrixRecalculationPerRender);
            foreach (var r in skinned) { r.forceMatrixRecalculationPerRender = true; r.updateWhenOffscreen = true; }
            var restRotation = bones.ToDictionary(b => b, b => b.rotation);
            var restPosition = bones.ToDictionary(b => b, b => b.position);
            var rootPosition = runtime.Root.transform.position;
            var rootRotation = runtime.Root.transform.rotation;
            var bounds = VerificationRenderer.Bounds(runtime);
            bounds.Expand(new Vector3(0.6f, 0.3f, 0.6f));   // room for swinging limbs and the sit drop
            var environment = VerificationRenderer.CreateEnvironment();
            var camera = VerificationRenderer.CreateCamera();
            try
            {
                VerificationRenderer.Frame(camera, "perspective", bounds, runtime);
                var warmup = Path.Combine(directory, "_warmup.png");
                Directory.CreateDirectory(directory);
                VerificationRenderer.RenderToPng(camera, 64, warmup);
                File.Delete(warmup);
                foreach (var spec in specs)
                {
                    var started = DateTime.UtcNow;
                    var duration = Mathf.Clamp(spec.DurationS, 0.5f, maxSeconds);
                    var frames = Mathf.Max(2, Mathf.RoundToInt(duration * fps));
                    var clipDir = Path.Combine(directory, spec.Id);
                    Directory.CreateDirectory(clipDir);
                    var entry = new ClipEntry { Id = spec.Id, Directory = clipDir, Fps = fps, DurationS = duration, Frames = frames, Loop = spec.Loop, Description = spec.Description };
                    if (Array.IndexOf(KnownClips, spec.Id) < 0)
                        report.Warn("clip.unknown", $"clip {spec.Id}: no procedural pose; recorded as idle");
                    var written = 0;
                    for (var f = 0; f < frames; f++)
                    {
                        var t = f / (float)fps;
                        Restore(bones, restRotation, restPosition, runtime.Root.transform, rootPosition, rootRotation);
                        Pose(spec.Id, t, duration, spec.DurationS, runtime, recipe, bones, restRotation);
                        VerificationRenderer.Frame(camera, "perspective", bounds, runtime);
                        var path = Path.Combine(clipDir, $"f_{f:0000}.png");
                        if (VerificationRenderer.RenderToPng(camera, resolution, path)) written++;
                    }
                    entry.Written = written == frames;
                    entry.Seconds = (float)(DateTime.UtcNow - started).TotalSeconds;
                    entries.Add(entry);
                    Debug.Log($"[ProModeler] clip {spec.Id}: {written}/{frames} frames at {fps} fps in {entry.Seconds:F1} s");
                }
            }
            finally
            {
                Restore(bones, restRotation, restPosition, runtime.Root.transform, rootPosition, rootRotation);
                if (animator != null) animator.enabled = animatorWasEnabled;
                foreach (var kv in forced) if (kv.Key != null) kv.Key.forceMatrixRecalculationPerRender = kv.Value;
                UnityEngine.Object.DestroyImmediate(camera.gameObject);
                foreach (var go in environment) UnityEngine.Object.DestroyImmediate(go);
            }
            return entries;
        }

        static void Restore(Transform[] bones, Dictionary<Transform, Quaternion> rotations, Dictionary<Transform, Vector3> positions, Transform root, Vector3 rootPosition, Quaternion rootRotation)
        {
            root.position = rootPosition;
            root.rotation = rootRotation;
            // Parents first so children inherit the restored frame before their own rest values are written.
            foreach (var bone in bones.OrderBy(Depth)) { bone.rotation = rotations[bone]; bone.position = positions[bone]; }
        }

        static int Depth(Transform t) { var d = 0; while (t.parent != null) { d++; t = t.parent; } return d; }

        static float Smooth(float p) => p <= 0f ? 0f : p >= 1f ? 1f : p * p * (3f - 2f * p);

        /// <summary>World-axis rotation applied to a bone (and inherited by its children through the hierarchy).</summary>
        static void Rotate(UMACharacterRuntime runtime, Dictionary<Transform, Quaternion> rest, string bone, Vector3 axis, float degrees)
        {
            var t = runtime.Bone(bone);
            if (t == null || Mathf.Abs(degrees) < 1e-4f) return;
            t.rotation = Quaternion.AngleAxis(degrees, axis) * t.rotation;
        }

        static float Limit(CharacterRecipe recipe, string name, float fallback)
        {
            return recipe.Animation.LimitsDeg.TryGetValue(name, out var range) && range != null && range.Length == 2 ? range[1] : fallback;
        }

        /// <summary>Elevation of an arm from hanging straight down: 0 = at the side, 90 = horizontal (T-pose).</summary>
        static float ArmElevation(UMACharacterRuntime runtime, string side)
        {
            var arm = runtime.Bone(side + "Arm");
            var hand = runtime.Bone(side + "Hand");
            if (arm == null || hand == null) return 90f;
            var d = hand.position - arm.position;
            return Vector3.Angle(Vector3.down, new Vector3(d.x, d.y, 0f));
        }

        /// <summary>Rotate an arm in the frontal plane (about Z) so it hangs at <paramref name="elevation"/> degrees from vertical.</summary>
        static void SetArmElevation(UMACharacterRuntime runtime, string side, float elevation, float s)
        {
            var arm = runtime.Bone(side + "Arm");
            if (arm == null) return;
            var current = ArmElevation(runtime, side);
            var sign = arm.position.x < 0f ? 1f : -1f;   // the left arm points to -X: a positive angle about Z lowers it
            arm.rotation = Quaternion.AngleAxis(sign * (current - elevation) * s, Vector3.forward) * arm.rotation;
        }

        /// <summary>The rest pose UMA generates is a T-pose (or an A-pose depending on when the animator last wrote the
        /// skeleton); every clip starts from a natural stance instead: arms hanging 12 degrees out, elbows slightly bent.</summary>
        static void Stance(UMACharacterRuntime runtime)
        {
            foreach (var side in new[] { "Left", "Right" })
            {
                SetArmElevation(runtime, side, 12f, 1f);
                Rotate(runtime, null, side + "ForeArm", Vector3.right, -12f);
            }
        }

        static void Pose(string clip, float t, float duration, float specDuration, UMACharacterRuntime runtime, CharacterRecipe recipe, Transform[] bones, Dictionary<Transform, Quaternion> rest)
        {
            var p = duration > 0f ? t / duration : 0f;
            if (clip != "raise-arms") Stance(runtime);
            switch (clip)
            {
                case "walk": Walk(runtime, rest, t, Mathf.Clamp(specDuration, 0.8f, 1.6f)); break;
                case "turn": runtime.Root.transform.rotation = Quaternion.AngleAxis(180f * Smooth(p), Vector3.up) * runtime.Root.transform.rotation; Idle(runtime, rest, t); break;
                case "sit": Sit(runtime, recipe, rest, Smooth(Mathf.Min(1f, p * 1.5f))); break;
                case "raise-arms": RaiseArms(runtime, recipe, rest, Smooth(p < 0.5f ? p * 2f : 2f - p * 2f)); break;
                case "physics-settle":
                    if (p < 1f / 3f || p > 2f / 3f) Idle(runtime, rest, t); else Walk(runtime, rest, t, 1.2f);
                    break;
                case "device": Device(runtime, rest, Smooth(Mathf.Min(1f, p * 3f)), t); break;
                default: Idle(runtime, rest, t); break;
            }
        }

        static void Idle(UMACharacterRuntime runtime, Dictionary<Transform, Quaternion> rest, float t)
        {
            var breath = Mathf.Sin(2f * Mathf.PI * t / 4f);
            Rotate(runtime, rest, "Spine1", Vector3.right, -1.5f * breath);
            Rotate(runtime, rest, "Head", Vector3.up, 6f * Mathf.Sin(2f * Mathf.PI * t / 6f + 1f));
            Rotate(runtime, rest, "Head", Vector3.right, 2f * Mathf.Sin(2f * Mathf.PI * t / 5f));
            Rotate(runtime, rest, "LeftArm", Vector3.forward, -1.0f * breath);    // arms drift out a little with the breath
            Rotate(runtime, rest, "RightArm", Vector3.forward, 1.0f * breath);
        }

        static void Walk(UMACharacterRuntime runtime, Dictionary<Transform, Quaternion> rest, float t, float period)
        {
            var theta = 2f * Mathf.PI * t / period;
            var swing = Mathf.Sin(theta);
            // Legs swing about X (forward is +Z; a negative angle about +X carries a hanging limb forward).
            Rotate(runtime, rest, "LeftUpLeg", Vector3.right, -28f * swing);
            Rotate(runtime, rest, "RightUpLeg", Vector3.right, 28f * swing);
            Rotate(runtime, rest, "LeftLeg", Vector3.right, 22f * Mathf.Max(0f, Mathf.Sin(theta + Mathf.PI * 0.5f)) * Mathf.Max(0f, -swing) * 2f);
            Rotate(runtime, rest, "RightLeg", Vector3.right, 22f * Mathf.Max(0f, Mathf.Sin(theta - Mathf.PI * 0.5f)) * Mathf.Max(0f, swing) * 2f);
            // Arms swing opposite to the same-side leg.
            Rotate(runtime, rest, "LeftArm", Vector3.right, 22f * swing);
            Rotate(runtime, rest, "RightArm", Vector3.right, -22f * swing);
            Rotate(runtime, rest, "LeftForeArm", Vector3.right, -12f * Mathf.Max(0f, swing));
            Rotate(runtime, rest, "RightForeArm", Vector3.right, -12f * Mathf.Max(0f, -swing));
            Rotate(runtime, rest, "Spine", Vector3.up, 4f * swing);
            var hips = runtime.Bone("Hips");
            if (hips != null) hips.position += new Vector3(0f, 0.02f * Mathf.Abs(Mathf.Sin(theta)) - 0.01f, 0f);
        }

        static void Sit(UMACharacterRuntime runtime, CharacterRecipe recipe, Dictionary<Transform, Quaternion> rest, float s)
        {
            var hipFlex = Mathf.Min(90f, Limit(recipe, "hip_flexion", 115f)) * s;
            var kneeFlex = Mathf.Min(90f, Limit(recipe, "knee_flexion", 130f)) * s;
            foreach (var side in new[] { "Left", "Right" })
            {
                Rotate(runtime, rest, side + "UpLeg", Vector3.right, -hipFlex);     // thighs forward to horizontal
                Rotate(runtime, rest, side + "Leg", Vector3.right, kneeFlex);        // shins back to vertical
            }
            Rotate(runtime, rest, "Spine", Vector3.right, 6f * s);                    // slight lean back
            var hips = runtime.Bone("Hips");
            var upLeg = runtime.Bone("LeftUpLeg");
            if (hips != null && upLeg != null)
            {
                var thigh = Vector3.Distance(upLeg.position, runtime.Bone("LeftLeg")?.position ?? upLeg.position);
                var seat = 0.43f + (recipe.Wardrobe.FirstOrDefault(g => g.Slot == "footwear")?.SoleHeightM ?? 0f);
                var drop = Mathf.Max(0f, hips.position.y - (seat + 0.09f));   // pelvis centre sits about 9 cm above the seat
                hips.position += new Vector3(0f, -drop * s, 0f);
                _ = thigh;
            }
            Rotate(runtime, rest, "LeftArm", Vector3.right, -25f * s);   // upper arms a little forward, forearms onto the lap
            Rotate(runtime, rest, "RightArm", Vector3.right, -25f * s);
            Rotate(runtime, rest, "LeftForeArm", Vector3.right, -55f * s);
            Rotate(runtime, rest, "RightForeArm", Vector3.right, -55f * s);
        }

        static void RaiseArms(UMACharacterRuntime runtime, CharacterRecipe recipe, Dictionary<Transform, Quaternion> rest, float s)
        {
            // From the natural stance (12 degrees) up to the recipe's shoulder_raise limit and back.
            var target = Mathf.Min(Limit(recipe, "shoulder_raise", 160f), 175f);
            foreach (var side in new[] { "Left", "Right" }) SetArmElevation(runtime, side, Mathf.Lerp(12f, target, s), 1f);
        }

        static void Device(UMACharacterRuntime runtime, Dictionary<Transform, Quaternion> rest, float s, float t)
        {
            Rotate(runtime, rest, "RightArm", Vector3.right, -20f * s);
            Rotate(runtime, rest, "RightArm", Vector3.forward, -20f * s);       // upper arm in toward the body
            Rotate(runtime, rest, "RightForeArm", Vector3.right, -85f * s);     // forearm up to the chest
            Rotate(runtime, rest, "RightForeArm", Vector3.up, -25f * s);
            Rotate(runtime, rest, "Head", Vector3.right, 18f * s);              // looking down at the hand
            Rotate(runtime, rest, "LeftArm", Vector3.right, -10f * s);
            Rotate(runtime, rest, "Spine1", Vector3.right, -1.5f * Mathf.Sin(2f * Mathf.PI * t / 4f));
        }
    }
}
