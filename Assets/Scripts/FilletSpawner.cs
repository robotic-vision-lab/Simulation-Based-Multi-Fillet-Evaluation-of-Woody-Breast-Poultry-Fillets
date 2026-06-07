using UnityEngine;
using System.Linq;
using System.Collections.Generic;

public class FilletSpawner : MonoBehaviour{

    public GameObject beltMeshObject;
    public float beltSpeedFPM = 50f;
    [Range(0f, 50f)] public float beltStaticFriction = 0.8f;
    [Range(0f, 50f)] public float beltDynamicFriction = 0.6f;

    private ConveyorBelt _activeBeltScript;

    public string resourcesFolder = "Fillets";
    public Transform spawnPoint;
    public Material filletMaterial;
    public bool alignLeftEdge = true;

    // multiple fillets per row
    public bool spawnRow = false; 
    public Transform endSpawnPoint; 

    // rigging
    [Range(2, 80)] public int segmentCount = 40;
    public float totalMass = 100.0f; 
    
    public float springForce = 0f;
    public float springDamper = 0.01f;
    public float jointDrag = 0.00f; 
    public float jointAngularDrag = 0.00f;
    public float horizontalAirDrag = 0.0f;

    private Mesh[] _meshes;
    private int _currentIndex = 0;
    private GameObject _currentFillet; 
    private List<GameObject> _extraFillets = new List<GameObject>(); // To track the extra row fillets

    void Start(){
        if (beltMeshObject != null){
            _activeBeltScript = beltMeshObject.GetComponent<ConveyorBelt>();
            if (_activeBeltScript == null) {
                _activeBeltScript = beltMeshObject.AddComponent<ConveyorBelt>();
            }
            SyncBeltSettings();
        }

        // Load all meshes from Resources/Fillets
        _meshes = Resources.LoadAll<Mesh>(resourcesFolder).OrderBy(m => m.name).ToArray();
    }

    void Update(){
        if (_activeBeltScript != null) SyncBeltSettings();
    }

    void SyncBeltSettings(){
        _activeBeltScript.SetSpeed(beltSpeedFPM);
        if (_activeBeltScript.staticFriction != beltStaticFriction) _activeBeltScript.staticFriction = beltStaticFriction;
        if (_activeBeltScript.dynamicFriction != beltDynamicFriction) _activeBeltScript.dynamicFriction = beltDynamicFriction;
    }

    public string SpawnSpecificFillet(int meshIndex, float stiffness, float speedFPM, float mass){
        if (_meshes == null || _meshes.Length == 0) return "0:0:0";
        
        // update params
        this.beltSpeedFPM = speedFPM;
        this.totalMass = mass; 
        
        if (_activeBeltScript != null) _activeBeltScript.SetSpeed(speedFPM);

        // cleanup old meshes
        if (_currentFillet != null) Destroy(_currentFillet);
        foreach (var f in _extraFillets) { if (f != null) Destroy(f); }
        _extraFillets.Clear();

        // select mesh
        int safeIndex = meshIndex % _meshes.Length;
        _currentIndex = safeIndex;
        Mesh meshToSpawn = _meshes[_currentIndex];
        
        // get loop count and positions
        int spawnCount = 1;
        if (spawnRow && endSpawnPoint != null) spawnCount = 3;

        Transform startTrans = spawnPoint ? spawnPoint : transform;
        Vector3 startPos = startTrans.position;
        Quaternion startRot = startTrans.rotation;

        Vector3 endPos = (endSpawnPoint != null) ? endSpawnPoint.position : startPos;
        Quaternion endRot = (endSpawnPoint != null) ? endSpawnPoint.rotation : startRot;

        // spawn loop
        for (int i = 0; i < spawnCount; i++)
        {
            // determine position (lerp)
            float t = 0;
            if (spawnCount > 1) t = (float)i / (spawnCount - 1); // 0.0, 0.5, 1.0

            Vector3 spawnPos = Vector3.Lerp(startPos, endPos, t);
            Quaternion spawnRot = Quaternion.Lerp(startRot, endRot, t);

            GameObject go = new GameObject($"Fillet_{meshToSpawn.name}_{i}");
            go.transform.position = spawnPos;
            go.transform.rotation = spawnRot;

            MeshFilter mf = go.AddComponent<MeshFilter>();
            mf.sharedMesh = meshToSpawn;

            MeshRenderer mr = go.AddComponent<MeshRenderer>();
            if (filletMaterial != null) mr.sharedMaterial = filletMaterial;

            // align
            if (alignLeftEdge){
                float zOffset = -meshToSpawn.bounds.max.z;
                go.transform.Translate(0, 0, zOffset, Space.Self);
            }

            // build rig
            FilletBuilder builder = go.AddComponent<FilletBuilder>();
            builder.numberOfSegments = segmentCount;
            builder.totalMass = totalMass;
            
            builder.springForce = stiffness; 
            builder.springDamper = springDamper;
            builder.jointDrag = jointDrag;
            builder.jointAngularDrag = jointAngularDrag;
            builder.horizontalAirDrag = horizontalAirDrag;

            builder.BuildAutomaticRig();

            go.transform.SetParent(this.transform);

            // track references
            if (i == 0){
                _currentFillet = go; // side view only
            }
            else{
                _extraFillets.Add(go); // track extras for cleanup
            }
        }

        // get dimensions of mesh
        Vector3 size = meshToSpawn.bounds.size;
        float L = size.x * 1000f; 
        float H = size.y * 1000f; 
        float W = size.z * 1000f; 

        return $"{L:F1}:{W:F1}:{H:F1}";
    }
}