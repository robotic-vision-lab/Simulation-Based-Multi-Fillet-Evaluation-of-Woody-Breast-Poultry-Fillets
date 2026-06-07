using UnityEngine;
using UnityEditor;

public class FilletImportSettings : AssetPostprocessor{
    void OnPreprocessModel(){
        if (assetPath.Contains("/Resources/Fillets/")){
            ModelImporter modelImporter = assetImporter as ModelImporter;
            modelImporter.isReadable = true;
            modelImporter.globalScale = 1.0f;
            modelImporter.useFileScale = true;
            modelImporter.materialImportMode = ModelImporterMaterialImportMode.None;
        }
    }
}