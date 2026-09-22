// FBX (com.unity.formats.fbx) and GLB (UnityGLTF) exports plus the UMA-level recipe string. Both exporters are called
// through reflection so this project compiles even while one of the packages is missing; a missing exporter becomes
// a warning in build.json instead of a broken project.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;
using ProModeler.Build;
using ProModeler.Runtime;

namespace ProModeler.Editor
{
    public static class CharacterExporter
    {
        public static Dictionary<string, object> Export(UMACharacterRuntime runtime, string directory, IEnumerable<string> formats, BuildReport report)
        {
            var exports = new Dictionary<string, object>();
            foreach (var format in formats)
            {
                switch (format)
                {
                    case "fbx": exports["fbx"] = ExportFbx(runtime.Root, Path.Combine(directory, "model.fbx"), report); break;
                    case "glb": exports["glb"] = ExportGlb(runtime.Root, directory, "model", report); break;
                    default: report.Warn("export.format", $"unknown export format {format}"); break;
                }
            }
            var umaRecipe = runtime.UmaRecipeString();
            if (!string.IsNullOrEmpty(umaRecipe))
            {
                var path = Path.Combine(directory, "recipe.uma.json");
                File.WriteAllText(path, umaRecipe);
                exports["uma_recipe"] = path;
            }
            return exports;
        }

        static FileEntry FileResult(string path)
        {
            var exists = File.Exists(path);
            return new FileEntry { Path = path, Written = exists, Bytes = exists ? new FileInfo(path).Length : 0 };
        }

        public static FileEntry ExportFbx(GameObject root, string path, BuildReport report)
        {
            var type = FindType("UnityEditor.Formats.Fbx.Exporter.ModelExporter");
            if (type == null)
            {
                report.Warn("export.fbx", "FBX Exporter package (com.unity.formats.fbx) is not available; fbx skipped");
                return new FileEntry { Path = path, Written = false, Bytes = 0 };
            }
            try
            {
                var method = type.GetMethods(BindingFlags.Public | BindingFlags.Static)
                    .First(m => m.Name == "ExportObject" && m.GetParameters().Length == 2 && m.GetParameters()[1].ParameterType == typeof(UnityEngine.Object));
                method.Invoke(null, new object[] { path, root });
            }
            catch (Exception exc)
            {
                report.Warn("export.fbx", $"{Unwrap(exc).GetType().Name}: {Unwrap(exc).Message}");
            }
            return FileResult(path);
        }

        public static FileEntry ExportGlb(GameObject root, string directory, string fileName, BuildReport report)
        {
            var path = Path.Combine(directory, fileName + ".glb");
            var exporterType = FindType("UnityGLTF.GLTFSceneExporter");
            var contextType = FindType("UnityGLTF.ExportContext");
            if (exporterType == null || contextType == null)
            {
                report.Warn("export.glb", "UnityGLTF (org.khronos.unitygltf) is not available; glb skipped");
                return new FileEntry { Path = path, Written = false, Bytes = 0 };
            }
            try
            {
                var context = Activator.CreateInstance(contextType);
                var ctor = exporterType.GetConstructor(new[] { typeof(Transform[]), contextType });
                if (ctor == null) throw new MissingMethodException("GLTFSceneExporter(Transform[], ExportContext) not found");
                var exporter = ctor.Invoke(new object[] { new[] { root.transform }, context });
                var save = exporterType.GetMethod("SaveGLB", new[] { typeof(string), typeof(string) });
                if (save == null) throw new MissingMethodException("GLTFSceneExporter.SaveGLB(string, string) not found");
                save.Invoke(exporter, new object[] { directory, fileName });
            }
            catch (Exception exc)
            {
                report.Warn("export.glb", $"{Unwrap(exc).GetType().Name}: {Unwrap(exc).Message}");
            }
            return FileResult(path);
        }

        static Exception Unwrap(Exception exc) => exc is TargetInvocationException tie && tie.InnerException != null ? tie.InnerException : exc;

        static Type FindType(string fullName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type type = null;
                try { type = assembly.GetType(fullName, false); } catch (Exception) { }
                if (type != null) return type;
            }
            return null;
        }
    }
}
