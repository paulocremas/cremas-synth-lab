// fx: raio=0.5, borda=0.3, preencher=0, pulso=0.3, layer
// Efeito ISOLADO: um círculo em cima de cada olho. Os olhos vêm do Python (eyes_thread, YuNet)
// por fonte: u_eyes = (esq.x, esq.y, dir.x, dir.y) em uv 0..1 com origem EM CIMA (= `st` daqui),
// u_eyes_on = 0..1 (some devagar quando perde o rosto). Raio proporcional à distância entre os
// olhos -> o círculo acompanha o rosto chegando perto/longe da câmera.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform vec4 u_eyes;
uniform float u_eyes_on;
uniform float u_kick;    // 0..1, pula na batida e decai sozinho

uniform float u_fx_raio;      // 0..1 -> raio = 0.15..0.75 x distância entre os olhos
uniform float u_fx_borda;     // 0..1 -> espessura do anel
uniform float u_fx_preencher; // 0 = só anel, 1 = disco cheio
uniform float u_fx_pulso;     // quanto o raio cresce na batida
uniform float u_fx_layer;

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

// 1 dentro do anel/disco em volta de `c`, 0 fora; `p`/`c` em uv, medido em px (círculo redondo
// mesmo com a tela não-quadrada)
float circle(vec2 p, vec2 c, float r, float w, float fill) {
    float d = length((p - c) * u_resolution);
    float aa = 1.5;                                             // anti-alias: ~1.5 px de degradê
    float disk = 1.0 - smoothstep(r - aa, r + aa, d);
    float ring = disk * smoothstep(r - w - aa, r - w + aa, d);
    return mix(ring, disk, fill);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    vec3 col = orig;

    if (u_eyes_on > 0.0) {
        float dist = length((u_eyes.zw - u_eyes.xy) * u_resolution);   // entre os olhos, em px
        float r = dist * mix(0.15, 0.75, u_fx_raio) * (1.0 + u_fx_pulso * u_kick);
        float w = max(1.0, r * mix(0.05, 0.6, u_fx_borda));
        float m = max(circle(st, u_eyes.xy, r, w, u_fx_preencher),
                      circle(st, u_eyes.zw, r, w, u_fx_preencher));
        vec3 c = hsv2rgb(vec3(fract(u_time * 0.1), 0.8, 1.0));        // <- edita aqui: cor do círculo
        col = mix(col, c, m * u_eyes_on);
    }

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    col = mix(orig, col, u_fx_layer);
    gl_FragColor = vec4(col, 1.0);
}
