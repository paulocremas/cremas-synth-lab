// fx: limiar=0.5, borda=0.2, inverter=0
// cat: mascara
// ATOMOS · Brilho. Máscara do que é claro na entrada (luma key). limiar = a partir de que brilho;
// borda = macia/dura; inverter = só o escuro.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a entrada da caixa
uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float b = dot(texture2D(u_texture_0, st).rgb, vec3(0.299, 0.587, 0.114));
    float h = u_fx_borda * 0.5 + 1e-3;
    float m = smoothstep(u_fx_limiar - h, u_fx_limiar + h, b);
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
