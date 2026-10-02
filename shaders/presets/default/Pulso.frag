// fx: pulse, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Clarão colorido na batida + uma
// onda de choque que se expande sozinha: o truque é usar o próprio decaimento do u_kick
// (pula pra 1 no hit, cai sozinho) como "tempo desde a batida" — o raio do anel cresce E o
// brilho cai juntos, sem precisar guardar estado entre frames (um shader não tem memória).

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_kick; // 0..1, pula na batida do grave e decai sozinho

uniform float u_fx_pulse;
uniform float u_fx_layer;

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    vec3 col = orig;

    // ===== PULSO + ONDA DE CHOQUE =====
    float pulse_amt = u_fx_pulse; // <- edita aqui. 0 = desligado, 1 = cheio
    vec3 pulse_color = hsv2rgb(vec3(fract(u_time * 0.12), 0.85, 1.0));
    col += pulse_color * u_kick * 0.35 * pulse_amt; // <- edita aqui: 0.35 = força do clarão

    float t_since = 1.0 - u_kick;
    float ring_r = t_since * 0.9;                             // <- edita aqui: 0.9 = até onde o anel chega
    float ring = smoothstep(0.05, 0.0, abs(length(st - 0.5) - ring_r)) * u_kick;
    col += pulse_color * ring * 1.2 * pulse_amt;              // <- edita aqui: 1.2 = brilho do anel

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
