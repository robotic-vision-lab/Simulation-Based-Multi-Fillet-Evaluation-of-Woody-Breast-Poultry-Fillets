using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System;

public class SimulationServer : MonoBehaviour{
    public FilletSpawner spawner;

    private ResponseSocket _serverSocket;
    private bool _isRunning = true;

    void Start(){
        _serverSocket = new ResponseSocket();
        _serverSocket.Options.Linger = TimeSpan.Zero;
        _serverSocket.Bind("tcp://*:5557");
        Debug.Log("Simulation Server listening on tcp://*:5557");
    }

    void Update(){
        if (!_isRunning) return;

        string message = null;
        if (_serverSocket.TryReceiveFrameString(out message)){
            string[] parts = message.Split(':');
            
            if (parts[0] == "SPAWN" && parts.Length >= 4){
                int id = int.Parse(parts[1]);
                float stiff = float.Parse(parts[2]);
                float speed = float.Parse(parts[3]);
                float mass = (parts.Length > 4) ? float.Parse(parts[4]) : 0.5f;

                string dims = spawner.SpawnSpecificFillet(id, stiff, speed, mass);
                _serverSocket.SendFrame($"OK:{dims}");
            }
            else{
                _serverSocket.SendFrame("ERROR");
            }
        }
    }

    void OnDestroy(){
        CleanupNetMQ();
    }

    void OnApplicationQuit(){
        CleanupNetMQ();
    }

    private void CleanupNetMQ(){
        _isRunning = false;
        if (_serverSocket != null){
            try{
                _serverSocket.Close();
                _serverSocket.Dispose();
            }
            catch (Exception ex){
                Debug.LogWarning($"Server cleanup error: {ex.Message}");
            }
            finally{
                _serverSocket = null;
            }
        }
    }
}