using UnityEngine;
using UnityEngine.Rendering;
using NetMQ;
using NetMQ.Sockets;
using System.Linq;

[RequireComponent(typeof(Camera))]
public class TopDownCam : MonoBehaviour{
    public Shader depthDisplayShader;
    public Vector2Int resolution = new Vector2Int(672, 376);
    private PublisherSocket pubSocket;
    private Camera rgbCamera;
    private Camera depthCamera;
    private RenderTexture rgbRenderTexture;
    private RenderTexture depthOnlyRenderTexture;
    private RenderTexture processedDepthTexture;
    private Material depthMaterial;
    private bool isRequestInProgress = false;
    private bool isShuttingDown = false;

    void Start(){
        pubSocket = new PublisherSocket();
        pubSocket.Bind("tcp://*:5556");
        Debug.Log("Publisher started on tcp://*:5556");

        rgbCamera = GetComponent<Camera>();
        rgbRenderTexture = new RenderTexture(resolution.x, resolution.y, 24, RenderTextureFormat.Default);
        rgbCamera.targetTexture = rgbRenderTexture;
        rgbCamera.aspect = (float)resolution.x / resolution.y;

        GameObject depthCameraObject = new GameObject("DepthCamera (Auto-Generated)");
        depthCameraObject.transform.SetParent(this.transform, false);
        depthCamera = depthCameraObject.AddComponent<Camera>();
        depthCamera.CopyFrom(rgbCamera);
        
        depthOnlyRenderTexture = new RenderTexture(resolution.x, resolution.y, 24, RenderTextureFormat.Depth);
        depthCamera.targetTexture = depthOnlyRenderTexture;

        processedDepthTexture = new RenderTexture(resolution.x, resolution.y, 0, RenderTextureFormat.RFloat);
        depthMaterial = new Material(depthDisplayShader);
    }

    void LateUpdate(){
        if (isRequestInProgress || isShuttingDown) return;
        isRequestInProgress = true;
        Graphics.Blit(depthOnlyRenderTexture, processedDepthTexture, depthMaterial);
        AsyncGPUReadback.Request(rgbRenderTexture, 0, TextureFormat.RGB24, OnCompleteRGBReadback);
    }

    void OnCompleteRGBReadback(AsyncGPUReadbackRequest request){
        if (isShuttingDown || pubSocket == null) { isRequestInProgress = false; return; }
    
        if (request.hasError){
            isRequestInProgress = false;
            return;
        }

        var rgbData = request.GetData<byte>().ToArray();

        AsyncGPUReadback.Request(processedDepthTexture, 0, TextureFormat.RFloat, (depthRequest) => {
            if (isShuttingDown || pubSocket == null) { isRequestInProgress = false; return; }
            
            if (depthRequest.hasError){
                isRequestInProgress = false;
                return;
            }

            var depthData = depthRequest.GetData<byte>().ToArray();

            try{
                if (pubSocket != null && !pubSocket.IsDisposed){
                    pubSocket.SendMoreFrame("camera_feed")
                             .SendMoreFrame($"{resolution.x},{resolution.y}")
                             .SendMoreFrame(rgbData)
                             .SendFrame(depthData);
                }
            }
            catch (System.Exception){
            }

            isRequestInProgress = false;
        });
    }

    void OnDestroy(){
        isShuttingDown = true;
        
        if (pubSocket != null){
            try{
                pubSocket.Close();
                pubSocket.Dispose();
            }
            catch (System.Exception){
            }
            finally{
                pubSocket = null;
            }
        }
        
        if (rgbRenderTexture) Destroy(rgbRenderTexture);
        if (depthOnlyRenderTexture) Destroy(depthOnlyRenderTexture);
        if (processedDepthTexture) Destroy(processedDepthTexture);
        if (depthMaterial) Destroy(depthMaterial);
    }
}