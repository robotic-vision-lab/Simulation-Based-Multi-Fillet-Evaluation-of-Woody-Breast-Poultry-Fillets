// File: DepthDisplay.shader
Shader "Unlit/DepthDisplay"
{
    Properties
    {
        _MainTex ("Depth Texture", 2D) = "white" {}
    }
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        LOD 100

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            #include "UnityCG.cginc"

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
            };

            struct v2f
            {
                float2 uv : TEXCOORD0;
                float4 vertex : SV_POSITION;
            };

            sampler2D _MainTex;
            
            v2f vert (appdata v)
            {
                v2f o;
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                return o;
            }
            
            fixed4 frag (v2f i) : SV_Target
            {
                // Sample the raw depth value from the texture.
                float rawDepth = tex2D(_MainTex, i.uv).r;

                // Convert the non-linear depth value to a linear [0,1] range.
                float linearDepth = Linear01Depth(rawDepth);
                
                // Output the linear depth as a grayscale color.
                return fixed4(linearDepth, linearDepth, linearDepth, 1.0);
            }
            ENDCG
        }
    }
}