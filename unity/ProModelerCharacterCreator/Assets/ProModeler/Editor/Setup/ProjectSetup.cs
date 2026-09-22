// One-time project preparation, run as its own editor invocation:
//   Unity.exe -batchmode -projectPath <project> -executeMethod ProModeler.Editor.ProjectSetup.Run -logFile <log>
// 1. checks that UMA's HDRP content (unpacked by `promodeler character setup` from Assets/UMA/SRP/UMAHDRP.unitypackage,
//    because AssetDatabase.ImportPackage is asynchronous in batch mode) is present,
// 2. makes sure the UMA asset index knows the UMA 3 human races (rebuilding it from the asset database otherwise),
// 3. writes Assets/ProModeler/setup.json, then lets the editor run a few update ticks so UMA's own
//    [InitializeOnLoad] HDRP setup hook (diffusion profile, skin shader repair) can apply before exiting.
// Safe to run repeatedly.

using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using UMA;

namespace ProModeler.Editor
{
    public static class ProjectSetup
    {
        public const string HdrpPackagePath = "Assets/UMA/SRP/UMAHDRP.unitypackage";
        public const string HdrpSetupPrefab = "Assets/UMA/SRP/HDRPSetup/UMAHDRPSetup.prefab";
        public const string StatusPath = "Assets/ProModeler/setup.json";

        [MenuItem("ProModeler/Run Project Setup")]
        public static void RunFromMenu() => Run(false);

        public static void Run() => Run(true);

        public static void Run(bool exitWhenDone)
        {
            var status = new SetupStatus { Started = DateTime.UtcNow.ToString("o") };
            var code = 0;
            try
            {
                status.UmaPresent = Directory.Exists("Assets/UMA/Core");
                if (!status.UmaPresent)
                    throw new InvalidOperationException("Assets/UMA is missing; run `promodeler character setup` to link external/uma into the project.");

                status.HdrpContentPresent = File.Exists(HdrpSetupPrefab);
                if (!status.HdrpContentPresent)
                    status.Note = "UMA HDRP content is missing (Assets/UMA/SRP/HDRPSetup); run `promodeler character setup` so the unitypackage is unpacked, then rerun.";
                else
                {
                    var setupPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(HdrpSetupPrefab);
                    var setup = setupPrefab != null ? setupPrefab.GetComponent("UMAHDRPSetup") : null;
                    if (setup != null)
                    {
                        // Same entry point as the prefab's context menu; runs synchronously here.
                        var method = setup.GetType().GetMethod("ApplySetup");
                        if (method != null) { method.Invoke(setup, null); status.HdrpSetupApplied = true; }
                    }
                }

                var indexer = UMAAssetIndexer.Instance;
                if (indexer == null) throw new InvalidOperationException("UMAAssetIndexer is not available (editor still compiling?)");
                status.RaceMalePresent = indexer.GetRace("Human Male 3.0") != null;
                status.RaceFemalePresent = indexer.GetRace("Human Female 3.0") != null;
                if (!status.RaceMalePresent || !status.RaceFemalePresent)
                {
                    Debug.Log("[ProModeler] UMA 3 human races missing from the index; rebuilding the UMA asset index");
                    indexer.AddEverything(true);
                    indexer.ForceSave();
                    status.IndexRebuilt = true;
                    status.RaceMalePresent = indexer.GetRace("Human Male 3.0") != null;
                    status.RaceFemalePresent = indexer.GetRace("Human Female 3.0") != null;
                }
                status.Ok = status.RaceMalePresent && status.RaceFemalePresent && status.HdrpContentPresent;
                if (!status.Ok) code = 1;
            }
            catch (Exception exc)
            {
                status.Ok = false;
                status.Error = exc.GetType().Name + ": " + exc.Message;
                Debug.LogError("[ProModeler] setup failed: " + exc);
                code = 1;
            }
            finally
            {
                status.Finished = DateTime.UtcNow.ToString("o");
                Directory.CreateDirectory(Path.GetDirectoryName(StatusPath));
                File.WriteAllText(StatusPath, JsonUtility.ToJson(status, true));
                AssetDatabase.SaveAssets();
                Debug.Log("[ProModeler] setup " + (status.Ok ? "ok" : "incomplete") + ": " + JsonUtility.ToJson(status));
                if (exitWhenDone) ExitAfterTicks(code, 60);
            }
        }

        static int _ticksLeft;
        static int _exitCode;

        /// <summary>Let delayCall-based hooks (UMA's HDRP setup queue) run before the editor quits.</summary>
        static void ExitAfterTicks(int code, int ticks)
        {
            _ticksLeft = ticks;
            _exitCode = code;
            EditorApplication.update += Tick;
        }

        static void Tick()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
            if (--_ticksLeft > 0) return;
            EditorApplication.update -= Tick;
            AssetDatabase.SaveAssets();
            EditorApplication.Exit(_exitCode);
        }

        [Serializable]
        public class SetupStatus
        {
            public bool Ok;
            public bool UmaPresent;
            public bool HdrpContentPresent;
            public bool HdrpImported;
            public bool HdrpSetupApplied;
            public bool IndexRebuilt;
            public bool RaceMalePresent;
            public bool RaceFemalePresent;
            public string Note;
            public string Error;
            public string Started;
            public string Finished;
        }
    }
}
