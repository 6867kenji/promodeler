// Verification renders with the Blender kernel's view names (front, side, back, perspective) plus authored close-ups
// (face, hand), in a shaded and a clay pass, under a neutral gradient sky. Output entries match report.json renders.

using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using ProModeler.Build;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class VerificationRenderer
    {
        public static readonly string[] KnownViews = { "front", "side", "back", "perspective", "face", "hand" };
        public static readonly string[] KnownPasses = { "shaded", "clay" };

        public static List<RenderEntry> Render(ICharacterRuntime runtime, IEnumerable<string> views, IEnumerable<string> passes,
                                               string directory, int resolution, BuildReport report)
        {
            Directory.CreateDirectory(directory);
            var entries = new List<RenderEntry>();
            var bounds = Bounds(runtime);
            var environment = CreateEnvironment();
            var camera = CreateCamera();
            try
            {
                // HDRP's first frame in a fresh scene comes out with unsettled exposure and sky; render and discard one.
                try
                {
                    Frame(camera, "front", bounds, runtime);
                    var warmup = Path.Combine(directory, "_warmup.png");
                    RenderToPng(camera, 64, warmup);
                    RenderToPng(camera, 64, warmup);
                    File.Delete(warmup);
                }
                catch (Exception exc) { report.Warn("render.warmup", exc.Message); }
                foreach (var pass in passes)
                {
                    if (Array.IndexOf(KnownPasses, pass) < 0) { report.Warn("render.pass", $"unknown pass {pass}"); continue; }
                    using (new ClayScope(runtime, pass == "clay"))
                    {
                        foreach (var view in views)
                        {
                            if (Array.IndexOf(KnownViews, view) < 0) { report.Warn("render.view", $"unknown view {view}"); continue; }
                            var started = DateTime.UtcNow;
                            var path = Path.Combine(directory, pass == "shaded" ? $"{view}.png" : $"{view}_{pass}.png");
                            var ok = false;
                            try
                            {
                                Frame(camera, view, bounds, runtime);
                                ok = RenderToPng(camera, resolution, path);
                            }
                            catch (Exception exc)
                            {
                                report.Warn("render.failed", $"{pass}/{view}: {exc.GetType().Name}: {exc.Message}");
                            }
                            entries.Add(new RenderEntry
                            {
                                View = view, Pass = pass, Path = path, Written = ok && File.Exists(path),
                                Seconds = (float)(DateTime.UtcNow - started).TotalSeconds,
                            });
                        }
                    }
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(camera.gameObject);
                foreach (var go in environment) UnityEngine.Object.DestroyImmediate(go);
            }
            return entries;
        }

        public static Bounds Bounds(ICharacterRuntime runtime)
        {
            var first = true;
            var bounds = new Bounds(Vector3.zero, Vector3.zero);
            foreach (var renderer in runtime.AllRenderers)
            {
                if (renderer is SkinnedMeshRenderer smr) smr.updateWhenOffscreen = true;
                if (first) { bounds = renderer.bounds; first = false; } else bounds.Encapsulate(renderer.bounds);
            }
            if (first) bounds = new Bounds(new Vector3(0f, 0.9f, 0f), new Vector3(0.6f, 1.8f, 0.4f));
            return bounds;
        }

        static Camera CreateCamera()
        {
            var go = new GameObject("ProModelerCamera");
            var camera = go.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.35f, 0.35f, 0.35f, 1f);
            camera.nearClipPlane = 0.02f;
            camera.farClipPlane = 50f;
            camera.allowHDR = true;
            var hd = go.AddComponent<HDAdditionalCameraData>();
            hd.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
            hd.backgroundColorHDR = camera.backgroundColor;
            hd.volumeLayerMask = ~0;
            return camera;
        }

        static List<GameObject> CreateEnvironment()
        {
            var objects = new List<GameObject>();
            var lightGo = new GameObject("ProModelerKey");
            var light = lightGo.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = Color.white;
            lightGo.transform.rotation = Quaternion.Euler(40f, 35f, 0f);
            var hdLight = lightGo.AddComponent<HDAdditionalLightData>();
            light.lightUnit = LightUnit.Lux;   // Unity 6 core light units; HDRP 17 dropped SetIntensity
            light.intensity = 20000f;
            hdLight.EnableShadows(true);
            objects.Add(lightGo);

            var fillGo = new GameObject("ProModelerFill");
            var fill = fillGo.AddComponent<Light>();
            fill.type = LightType.Directional;
            fill.color = new Color(0.8f, 0.85f, 1f);
            fillGo.transform.rotation = Quaternion.Euler(20f, -120f, 0f);
            var hdFill = fillGo.AddComponent<HDAdditionalLightData>();
            fill.lightUnit = LightUnit.Lux;
            fill.intensity = 6000f;
            hdFill.EnableShadows(false);
            objects.Add(fillGo);

            var volumeGo = new GameObject("ProModelerSky");
            var volume = volumeGo.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 100f;
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            var environment = profile.Add<VisualEnvironment>(true);
            environment.skyType.value = (int)SkyType.Gradient;
            environment.skyAmbientMode.value = SkyAmbientMode.Dynamic;
            var sky = profile.Add<GradientSky>(true);
            sky.top.value = new Color(0.55f, 0.58f, 0.62f);
            sky.middle.value = new Color(0.42f, 0.42f, 0.42f);
            sky.bottom.value = new Color(0.25f, 0.25f, 0.25f);
            sky.exposure.value = 0f;
            sky.multiplier.value = 1f;
            var exposure = profile.Add<Exposure>(true);
            exposure.mode.value = ExposureMode.Fixed;
            exposure.fixedExposure.value = 10.5f;
            volume.sharedProfile = profile;
            objects.Add(volumeGo);
            return objects;
        }

        static void Frame(Camera camera, string view, Bounds bounds, ICharacterRuntime runtime)
        {
            var center = bounds.center;
            var height = Mathf.Max(bounds.size.y, 0.5f);
            camera.fieldOfView = 35f;
            var distance = height / (2f * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad)) * 1.15f;
            Vector3 position;
            Vector3 target = center;
            switch (view)
            {
                case "front": position = center + new Vector3(0f, 0f, distance); break;           // the character faces +Z
                case "back": position = center + new Vector3(0f, 0f, -distance); break;
                case "side": position = center + new Vector3(distance, 0f, 0f); break;             // anatomical left side toward the camera
                case "perspective": position = center + new Vector3(distance * 0.7f, height * 0.25f, distance * 0.7f); break;
                case "face":
                {
                    var head = runtime.Bone("Head");
                    target = head != null ? head.position + new Vector3(0f, 0.08f, 0.04f) : center + new Vector3(0f, height * 0.42f, 0.05f);
                    camera.fieldOfView = 22f;
                    position = target + new Vector3(0f, 0.01f, 0.75f);
                    break;
                }
                case "hand":
                {
                    var hand = runtime.Bone("RightHand") ?? runtime.Bone("LeftHand");
                    target = hand != null ? hand.position : center + new Vector3(-0.35f, -0.05f, 0f);
                    camera.fieldOfView = 18f;
                    position = target + new Vector3(-0.35f, 0.15f, 0.55f);
                    break;
                }
                default: position = center + new Vector3(0f, 0f, distance); break;
            }
            camera.transform.position = position;
            camera.transform.LookAt(target, Vector3.up);
        }

        static bool RenderToPng(Camera camera, int resolution, string path)
        {
            var rt = new RenderTexture(resolution, resolution, 24, RenderTextureFormat.ARGB32) { antiAliasing = 1 };
            rt.Create();
            var previous = RenderTexture.active;
            try
            {
                camera.targetTexture = rt;
                var request = new RenderPipeline.StandardRequest { destination = rt };
                if (RenderPipeline.SupportsRenderRequest(camera, request)) RenderPipeline.SubmitRenderRequest(camera, request);
                else camera.Render();
                camera.targetTexture = null;
                RenderTexture.active = rt;
                var texture = new Texture2D(resolution, resolution, TextureFormat.RGBA32, false);
                texture.ReadPixels(new Rect(0, 0, resolution, resolution), 0, 0);
                texture.Apply();
                File.WriteAllBytes(path, texture.EncodeToPNG());
                UnityEngine.Object.DestroyImmediate(texture);
                return true;
            }
            finally
            {
                RenderTexture.active = previous;
                camera.targetTexture = null;
                rt.Release();
                UnityEngine.Object.DestroyImmediate(rt);
            }
        }

        /// <summary>Temporarily replaces every material with a neutral matte gray so silhouette and proportions read without textures.</summary>
        sealed class ClayScope : IDisposable
        {
            readonly List<(Renderer renderer, Material[] materials)> _saved = new List<(Renderer, Material[])>();
            readonly Material _clay;

            public ClayScope(ICharacterRuntime runtime, bool enabled)
            {
                if (!enabled) return;
                var shader = Shader.Find("HDRP/Lit");
                _clay = new Material(shader);
                _clay.SetColor("_BaseColor", new Color(0.62f, 0.6f, 0.58f, 1f));
                _clay.SetFloat("_Smoothness", 0.25f);
                _clay.SetFloat("_Metallic", 0f);
                foreach (var renderer in runtime.AllRenderers)
                {
                    _saved.Add((renderer, renderer.sharedMaterials));
                    var replacement = new Material[renderer.sharedMaterials.Length];
                    for (var i = 0; i < replacement.Length; i++) replacement[i] = _clay;
                    renderer.sharedMaterials = replacement;
                }
            }

            public void Dispose()
            {
                foreach (var (renderer, materials) in _saved)
                    if (renderer != null) renderer.sharedMaterials = materials;
                if (_clay != null) UnityEngine.Object.DestroyImmediate(_clay);
            }
        }
    }
}
