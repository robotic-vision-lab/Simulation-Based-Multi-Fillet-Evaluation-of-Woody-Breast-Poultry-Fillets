using UnityEngine;
using System.Collections.Generic;

public class ConveyorBelt : MonoBehaviour
{
    public float speedFeetPerMin = 50f;
    public Vector3 primaryFlowDirection = Vector3.right;
    public float staticFriction = 0.8f;  
    public float dynamicFriction = 0.6f; 
    public bool showForces = true;

    private float _speedMetersPerSec;
    private Rigidbody _beltRb;
    
    private Dictionary<Rigidbody, float> _smoothedNormalForces = new Dictionary<Rigidbody, float>();

    void Start(){
        CalculateSpeed();
        _beltRb = GetComponent<Rigidbody>();
        if (_beltRb != null) _beltRb.isKinematic = true;
        ApplyFrictionlessMaterial();
    }

    void ApplyFrictionlessMaterial(){
        PhysicsMaterial slipperyMat = new PhysicsMaterial("ConveyorSlippery");
        slipperyMat.dynamicFriction = 0f;
        slipperyMat.staticFriction = 0f;
        slipperyMat.bounciness = 0f;
        slipperyMat.frictionCombine = PhysicsMaterialCombine.Minimum;
        slipperyMat.bounceCombine = PhysicsMaterialCombine.Minimum;
        foreach (Collider col in GetComponentsInChildren<Collider>()) col.material = slipperyMat;
    }

    public void SetSpeed(float fpm)
    {
        speedFeetPerMin = fpm;
        CalculateSpeed();
    }

    void CalculateSpeed(){
        // FPM to m/s
        _speedMetersPerSec = (speedFeetPerMin * 0.3048f) / 60f;
    }

    void OnCollisionStay(Collision collision){
        Rigidbody targetRb = collision.gameObject.GetComponent<Rigidbody>();
        if (targetRb == null || targetRb.isKinematic) return;

        // determine average normal (points out of the belt)
        Vector3 summedNormal = Vector3.zero;
        int contactCount = collision.contactCount;
        for (int i = 0; i < contactCount; i++){
            summedNormal += collision.GetContact(i).normal;
        }
        Vector3 bestNormal = (summedNormal / contactCount).normalized;

        // get normal force
        float currentRawForce = collision.impulse.magnitude / Time.fixedDeltaTime;
        if (!_smoothedNormalForces.ContainsKey(targetRb)) _smoothedNormalForces[targetRb] = currentRawForce;
        _smoothedNormalForces[targetRb] = Mathf.Lerp(_smoothedNormalForces[targetRb], currentRawForce, 0.25f);
        float normalForce = _smoothedNormalForces[targetRb];

        // get velocity along surface
        Vector3 tangentMoveDir = Vector3.ProjectOnPlane(primaryFlowDirection, bestNormal).normalized;

        Vector3 targetVel = tangentMoveDir * _speedMetersPerSec;
        Vector3 currentVel = targetRb.linearVelocity;
        Vector3 velocityDiff = targetVel - currentVel;
        
        float diffAlongPath = Vector3.Dot(velocityDiff, tangentMoveDir);
        Vector3 neededChange = tangentMoveDir * diffAlongPath;

        Vector3 forceToLock = (neededChange / Time.fixedDeltaTime) * targetRb.mass;
        float maxStaticForce = normalForce * staticFriction;

        // apply friction
        if (forceToLock.magnitude <= maxStaticForce){
            targetRb.AddForce(forceToLock, ForceMode.Force);
        }
        else{
            float maxDynamicForce = normalForce * dynamicFriction;
            targetRb.AddForce(neededChange.normalized * maxDynamicForce, ForceMode.Force);
        }

    }

    void OnCollisionExit(Collision collision){
        Rigidbody targetRb = collision.gameObject.GetComponent<Rigidbody>();
        if (targetRb != null && _smoothedNormalForces.ContainsKey(targetRb)){
            _smoothedNormalForces.Remove(targetRb);
        }
    }

    void OnValidate(){
        CalculateSpeed();
    }
}