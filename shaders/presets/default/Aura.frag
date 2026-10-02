// fx: aura, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Halo radial aditivo, metade na cor
// mais comum do frame (u_dominant, calculada no Python) e metade arco-íris girando sozinho.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform vec3 u_dominant; // cor RGB mais frequente do frame atual, calculada no Python
uniform float u_brilho;  // 0..1, faixa "Brilliance" ~10-16kHz — intensidade do halo
uniform float u_kick;    // 0..1, pula na batida e decai sozinho — piscada extra

uniform float u_fx_aura;
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

    // ===== AURA DA COR DOMINANTE — halo aditivo, metade cor da cena / metade arco-íris =====
    float aura_amt = u_fx_aura; // <- edita aqui. 0 = desligado, 1 = cheio
    if (aura_amt > 0.0) {
        vec3 aura_color = mix(u_dominant, hsv2rgb(vec3(fract(u_time * 0.08), 1.0, 1.0)), 0.5);
        float glow = smoothstep(0.7, 0.0, length(st - 0.5)) * (0.3 + 0.7 * u_brilho) * (1.0 + 1.5 * u_kick);
        col += aura_color * glow * aura_amt; // <- edita aqui: 0.7 (acima) = raio do halo
    }

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
