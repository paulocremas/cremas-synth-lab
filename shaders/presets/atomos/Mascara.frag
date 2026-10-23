// fx: limiar=0.5, borda=0.1, inverter=0
// cat: mistura
// in: src
// ATOMOS · Máscara. A corrente so' aparece onde a entrada B e' clara (o resto fica preto). Sem B ligada
// = a propria fonte crua. limiar = a partir de que brilho; borda = macia/dura; inverter = so' no escuro.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;   // a corrente
uniform sampler2D u_texture_1;   // B: a mascara
uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    float b = dot(texture2D(u_texture_1, st).rgb, vec3(0.299, 0.587, 0.114));
    float m = smoothstep(u_fx_limiar - u_fx_borda * 0.5, u_fx_limiar + u_fx_borda * 0.5 + 1e-3, b);
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(texture2D(u_texture_0, st).rgb * m, 1.0);
}
