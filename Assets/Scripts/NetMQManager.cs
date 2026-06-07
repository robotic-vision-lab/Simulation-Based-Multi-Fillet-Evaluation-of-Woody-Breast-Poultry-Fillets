using UnityEngine;
using NetMQ;
using AsyncIO;

public class NetMQManager : MonoBehaviour{
    void Awake(){
        // init netmq context once before any sockets open
        ForceDotNet.Force();
        Debug.Log("Global NetMQ Context Initialized.");
    }

    void OnApplicationQuit(){
        // clean up netmq context once after all sockets close
        NetMQConfig.Cleanup(false);
        Debug.Log("Global NetMQ Context Cleaned Up.");
    }
}