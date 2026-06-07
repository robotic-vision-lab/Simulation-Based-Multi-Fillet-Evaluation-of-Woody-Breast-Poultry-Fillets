using UnityEngine;
using UnityEngine.Rendering; 
using NetMQ;
using NetMQ.Sockets;
using System;

public class SideViewCam : MonoBehaviour{
    public int imageWidth = 960;
    public int imageHeight = 696;
    public bool sendRawBytes = true; 

    private PublisherSocket _pubSocket;
    private RenderTexture _rt;
    private bool _isRequestInProgress = false;
    private bool _isShuttingDown = false;

    void Start(){
        _pubSocket = new PublisherSocket();
        
        _pubSocket.Options.SendHighWatermark = 1; 
        _pubSocket.Options.Linger = TimeSpan.Zero;
        
        _pubSocket.Bind("tcp://*:5555");
        Application.targetFrameRate = 200;
        QualitySettings.vSyncCount = 0;

        _rt = new RenderTexture(imageWidth, imageHeight, 24, RenderTextureFormat.ARGB32);
        GetComponent<Camera>().targetTexture = _rt;
    }

    void Update(){
        if (_isShuttingDown) return;
        
        if (!_isRequestInProgress){
            _isRequestInProgress = true;
            AsyncGPUReadback.Request(_rt, 0, TextureFormat.RGB24, OnCompleteReadback);
        }
    }

    void OnCompleteReadback(AsyncGPUReadbackRequest request){
        if (_isShuttingDown) return;
        _isRequestInProgress = false; 
        if (request.hasError) return;
        var rawData = request.GetData<byte>();
        _pubSocket.SendMoreFrame("CameraStream").TrySendFrame(rawData.ToArray());
    }

    void OnDestroy(){
        CleanupNetMQ();
    }

    void OnApplicationQuit(){
        CleanupNetMQ();
    }

    private void CleanupNetMQ(){
        _isShuttingDown = true;
        if (_pubSocket != null){
            try {
                _pubSocket.Options.Linger = TimeSpan.Zero; 
                _pubSocket.Close();
                _pubSocket.Dispose();
            }
            catch (Exception ex) {
                Debug.LogWarning($"Socket cleanup error: {ex.Message}");
            }
            finally {
                _pubSocket = null;
            }
        }
    }
}