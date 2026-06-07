using UnityEngine;
using System.Linq;
using System.Collections.Generic;

public class FilletBuilder : MonoBehaviour{
    [Range(2, 80)] public int numberOfSegments = 40;
    public float totalMass = 1f;

    [Range(0, 180)] public float maxDownwardBend = 130f;
    [Range(0, 180)] public float maxUpwardBend = 130f; 

    public float springForce = 0f;
    public float springDamper = 0.01f; 
    public float jointDrag = 0.00f;
    public float jointAngularDrag = 0.00f;
    public PhysicsMaterial segmentPhysicMaterial;

    public float horizontalAirDrag = 12.0f; 
    public float fallThreshold = -0.1f;

    private List<Rigidbody> _segmentRbs = new List<Rigidbody>();

    void Start(){
        _segmentRbs = new List<Rigidbody>(GetComponentsInChildren<Rigidbody>());
    }

    void Update(){
        if (Application.isPlaying){
            UpdateJointsRuntime();
        }
    }

    void FixedUpdate(){
        foreach (var rb in _segmentRbs){
            if (rb == null) continue;

            if (rb.linearVelocity.y < fallThreshold){
                Vector3 horizontalVel = new Vector3(rb.linearVelocity.x, 0, rb.linearVelocity.z);
                rb.AddForce(-horizontalVel * horizontalAirDrag, ForceMode.Acceleration);
            }
        }
    }

    private void UpdateJointsRuntime(){
        ConfigurableJoint[] joints = GetComponentsInChildren<ConfigurableJoint>();
        foreach (var joint in joints){
            JointDrive drive = joint.angularXDrive;
            if (drive.positionSpring != springForce || drive.positionDamper != springDamper){
                drive.positionSpring = springForce;
                drive.positionDamper = springDamper;
                joint.angularXDrive = drive;
            }
        }
    }

    public void BuildAutomaticRig(){
        CleanupOldRig();
        _segmentRbs.Clear();

        GameObject sourceGo;
        Mesh sourceMesh;
        Material sourceMaterial;
        bool isAlreadySkinned;

        if (!FindSourceMesh(out sourceGo, out sourceMesh, out sourceMaterial, out isAlreadySkinned)){
            Debug.LogError("FilletBuilder Error: No mesh found.", this);
            return;
        }

        if (segmentPhysicMaterial == null){
            segmentPhysicMaterial = new PhysicsMaterial("SlipperyFillet");
            segmentPhysicMaterial.dynamicFriction = 0f;
            segmentPhysicMaterial.staticFriction = 0f;
            segmentPhysicMaterial.frictionCombine = PhysicsMaterialCombine.Minimum;
            segmentPhysicMaterial.bounciness = 0f;
            segmentPhysicMaterial.bounceCombine = PhysicsMaterialCombine.Minimum;
        }
        
        var vertices = sourceMesh.vertices;
        float minX = float.MaxValue; float maxX = float.MinValue;
        foreach (var vertex in vertices) { minX = Mathf.Min(minX, vertex.x); maxX = Mathf.Max(maxX, vertex.x); }
        float totalLength = maxX - minX;
        float segmentLength = totalLength / numberOfSegments;
        
        List<List<Vector3>> segmentVertices = new List<List<Vector3>>();
        for (int i = 0; i < numberOfSegments; i++) segmentVertices.Add(new List<Vector3>());
        foreach (var vertex in vertices){
            int segmentIndex = Mathf.FloorToInt((vertex.x - minX) / segmentLength);
            segmentIndex = Mathf.Clamp(segmentIndex, 0, numberOfSegments - 1);
            segmentVertices[segmentIndex].Add(vertex);
        }

        List<float> crossSectionalAreas = new List<float>();
        List<Bounds> segmentLocalBounds = new List<Bounds>();
        float totalCrossSectionalArea = 0f;

        for (int i = 0; i < numberOfSegments; i++){
            List<Vector3> verts = segmentVertices[i];
            float minY = float.MaxValue, maxY = float.MinValue, minZ = float.MaxValue, maxZ = float.MinValue;
            if (verts.Count > 0){
                foreach (var v in verts) { minY = Mathf.Min(minY, v.y); maxY = Mathf.Max(maxY, v.y); minZ = Mathf.Min(minZ, v.z); maxZ = Mathf.Max(maxZ, v.z); }
            }
            else { 
                minY = sourceMesh.bounds.min.y; maxY = sourceMesh.bounds.max.y; 
                minZ = sourceMesh.bounds.min.z; maxZ = sourceMesh.bounds.max.z; 
            }
            
            float height = Mathf.Max(maxY - minY, 0.001f);
            float width = Mathf.Max(maxZ - minZ, 0.001f);
            float area = height * width; 
            crossSectionalAreas.Add(area);
            totalCrossSectionalArea += area;
            
            Vector3 sliceCenter = new Vector3(minX + (i + 0.5f) * segmentLength, (minY + maxY) / 2f, (minZ + maxZ) / 2f);
            segmentLocalBounds.Add(new Bounds(sliceCenter, new Vector3(segmentLength, height, width)));
        }

        List<float> shapeRatios = new List<float>();
        if (totalCrossSectionalArea > 0) for (int i = 0; i < numberOfSegments; i++) shapeRatios.Add(crossSectionalAreas[i] / totalCrossSectionalArea);
        else for (int i = 0; i < numberOfSegments; i++) shapeRatios.Add(1f / numberOfSegments);
        var bones = new List<Transform>();
        var colliders = new List<Collider>();
        
        for (int i = 0; i < numberOfSegments; i++){
            GameObject segmentGo = new GameObject($"Segment_{i}");
            segmentGo.transform.SetParent(this.transform);
            
            Vector3 localPos = segmentLocalBounds[i].center; 
            segmentGo.transform.position = sourceGo.transform.TransformPoint(localPos);
            segmentGo.transform.rotation = sourceGo.transform.rotation;
            bones.Add(segmentGo.transform);

            Rigidbody rb = segmentGo.AddComponent<Rigidbody>();
            float calculatedMass = (shapeRatios.Count > i) ? totalMass * shapeRatios[i] : totalMass / numberOfSegments;
            
            rb.mass = calculatedMass;
            rb.linearDamping = jointDrag;
            rb.angularDamping = jointAngularDrag; 
            rb.constraints = RigidbodyConstraints.None;
            rb.sleepThreshold = 0f; 

            _segmentRbs.Add(rb);

            BoxCollider collider = segmentGo.AddComponent<BoxCollider>();
            Bounds localBounds = segmentLocalBounds[i];
            Vector3 meshScale = sourceGo.transform.lossyScale;
            Vector3 colliderSize = localBounds.size;
            colliderSize.Scale(meshScale); 
            
            collider.contactOffset = 0.001f;
            colliderSize.x *= 1.0f; 
            colliderSize.y *= 1.0f; 

            collider.size = colliderSize;
            collider.center = Vector3.zero; 
            collider.material = segmentPhysicMaterial;
            colliders.Add(collider);
        }
        
        for (int i = 1; i < numberOfSegments; i++){
            ConfigurableJoint joint = bones[i].gameObject.AddComponent<ConfigurableJoint>();
            joint.connectedBody = bones[i - 1].GetComponent<Rigidbody>(); 
            joint.axis = Vector3.forward; 
            joint.secondaryAxis = Vector3.up;
            joint.autoConfigureConnectedAnchor = false;
            joint.anchor = bones[i].InverseTransformPoint(bones[i - 1].position) * 0.5f;
            joint.connectedAnchor = bones[i - 1].InverseTransformPoint(bones[i].position) * 0.5f;
            joint.enablePreprocessing = false; 
            joint.projectionMode = JointProjectionMode.None; 
            joint.xMotion = ConfigurableJointMotion.Locked;
            joint.yMotion = ConfigurableJointMotion.Locked;
            joint.zMotion = ConfigurableJointMotion.Locked;
            joint.angularXMotion = ConfigurableJointMotion.Limited; 
            joint.angularYMotion = ConfigurableJointMotion.Locked; 
            joint.angularZMotion = ConfigurableJointMotion.Locked;
            joint.lowAngularXLimit = new SoftJointLimit() { limit = -maxDownwardBend };
            joint.highAngularXLimit = new SoftJointLimit() { limit = maxDownwardBend };
            
            if (springForce > 0 || springDamper > 0){
                joint.angularXDrive = new JointDrive(){ 
                    positionSpring = springForce, 
                    positionDamper = springDamper, 
                    maximumForce = float.MaxValue 
                };
            }
        }
        IgnoreInternalCollisions(colliders);
        SkinMeshToBones(sourceGo, bones, sourceMesh, sourceMaterial, isAlreadySkinned);
    }

    private void CleanupOldRig(){ 
        foreach (var t in GetComponentsInChildren<Transform>().Where(t => t.gameObject != gameObject && t.name.StartsWith("Segment_")).ToList()) Destroy(t.gameObject);
    }
    
    private bool FindSourceMesh(out GameObject go, out Mesh mesh, out Material mat, out bool skinned){ 
        go=null; 
        mesh=null; 
        mat=null; 
        skinned=false; 
        var smr=GetComponentInChildren<SkinnedMeshRenderer>(); 
        if(smr){
            go=smr.gameObject; 
            mesh=smr.sharedMesh; 
            mat=smr.sharedMaterial; 
            skinned=true;
        } 
        else{
            var mf=GetComponentInChildren<MeshFilter>();
            if(mf){
                go=mf.gameObject; 
                mesh=mf.sharedMesh; 
                var mr=go.GetComponent<MeshRenderer>(); 
                if(mr){
                    mat=mr.sharedMaterial;
                }
            }
        } 
        return go!=null && mesh!=null; 
    }
    
    private void IgnoreInternalCollisions(List<Collider> c){ 
        for(int i=0;i<c.Count;i++) for(int j=i+1;j<c.Count;j++) Physics.IgnoreCollision(c[i], c[j]); 
    }
    
    private void SkinMeshToBones(GameObject go, List<Transform> bones, Mesh mesh, Material mat, bool skinned){ 
        SkinnedMeshRenderer smr = skinned ? go.GetComponent<SkinnedMeshRenderer>() : go.AddComponent<SkinnedMeshRenderer>();
        if(!skinned){ 
            Destroy(go.GetComponent<MeshFilter>()); 
            Destroy(go.GetComponent<MeshRenderer>()); 
        }
        Mesh newMesh = Instantiate(mesh); 
        smr.sharedMesh = newMesh; 
        smr.sharedMaterial = mat; 
        smr.bones = bones.ToArray(); 
        smr.rootBone = bones[0]; 
        smr.updateWhenOffscreen = true;
        var weights = new BoneWeight[newMesh.vertexCount]; 
        var verts = newMesh.vertices;
        Vector3[] boneWorldPos = new Vector3[bones.Count];
        for(int i = 0; i < bones.Count; i++) boneWorldPos[i] = bones[i].position;
        for(int i=0; i<verts.Length; i++) {
            Vector3 worldPt = go.transform.TransformPoint(verts[i]);
            int b1 = -1, b2 = -1; 
            float d1 = float.MaxValue, d2 = float.MaxValue;
            for(int j=0; j<bones.Count; j++){ 
                float dist = Mathf.Abs(worldPt.x - boneWorldPos[j].x); 
                if(dist < d1){
                    d2 = d1; b2 = b1; d1 = dist; b1 = j; 
                } 
                else if(dist < d2){ 
                    d2 = dist; b2 = j; 
                } 
            }
            weights[i].boneIndex0 = b1; weights[i].weight0 = (d1==0) ? 1 : (d2/(d1+d2)); 
            weights[i].boneIndex1 = b2; weights[i].weight1 = (d1==0) ? 0 : (d1/(d1+d2));
        }
        newMesh.boneWeights = weights;
        var poses = new Matrix4x4[bones.Count]; 
        for(int i=0; i<bones.Count; i++) poses[i] = bones[i].worldToLocalMatrix * go.transform.localToWorldMatrix; 
        newMesh.bindposes = poses;
    }
}