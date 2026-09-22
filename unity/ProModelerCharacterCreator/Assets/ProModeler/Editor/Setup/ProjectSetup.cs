// One-time project preparation, run as its own editor invocation because it imports scripts (domain reload):
//   Unity.exe -batchmode -projectPath <project> -executeMethod ProModeler.Editor.ProjectSetup.Run -logFile <log>
// 1. imports UMA's HDRP content package (Assets/UMA/SRP/UMAHDRP.unitypackage) when its setup prefab is missing,
// 2. makes sure the UMA asset index knows the UMA 3 human races (rebuilding it from the asset database otherwise),
// 3. writes Assets/ProModeler/setup.json with what it found, then exits.
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
                if (!status.HdrpContentPresent && File.Exists(HdrpPackagePath))
                {
                    Debug.Log("[ProModeler] importing " + HdrpPackagePath);
                    AssetDatabase.ImportPackage(HdrpPackagePath, false);
                    AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                    status.HdrpContentPresent = File.Exists(HdrpSetupPrefab);
                    status.HdrpImported = status.HdrpContentPresent;
                    // Importing adds scripts: the domain reloads after this method returns. The next invocation
                    // (or the build itself) will see the compiled UMAHDRPSetup and its InitializeOnLoad hook.
                    status.Note = "HDRP package imported; run setup once more so the UMA HDRP setup hook can apply.";
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
                status.Ok = status.RaceMalePresent && status.RaceFemalePresent;
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
                if (exitWhenDone) EditorApplication.Exit(code);
            }
        }

        [Serializable]
        public class SetupStatus
        {
            public bool Ok;
            public bool UmaPresent;
            public bool HdrpContentPresent;
            public bool HdrpImported;
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
