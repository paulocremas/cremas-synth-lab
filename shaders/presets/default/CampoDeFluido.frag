// fx: silhueta, layer
// Efeito ISOLADO (um por arquivo — misturar vem depois). Este é o EFEITO 7 "silhueta" do
// Caos.frag isolado — não confundir com Silhueta.frag, que é um SNAPSHOT histórico (a versão
// inteira de antes, quando essa mesma simulação era usada como fumaça e ficou parecendo uma
// cortina caindo). Aqui é só o campo em si, já estilizado como forma gráfica.
// A densidade vem de uma simulação de fluido de verdade (Stable Fluids — native_synth.py,
// SIM_*_SRC): advecção, empuxo, confinamento de vorticidade, projeção de pressão (Jacobi).
// Numa grade baixa + confinamento forte isso vira blobs grandes em vez de fibras finas —
// não parece fumaça, mas sozinho é um visual gráfico interessante. Por isso o tratamento
// aqui é chapado/contornado (silhueta), não suave como fumaça de verdade.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform sampler2D u_texture_smoke; // campo da sim de fluido 0..1 (canal .r), calculado no Python

uniform float u_fx_silhueta;
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

    // ===== SILHUETA — preenchimento chapado + contorno na borda do campo de fluido =====
    float silhueta_amt = u_fx_silhueta; // <- edita aqui. 0 = desligado, 1 = cheio
    if (silhueta_amt > 0.0) {
        float field = texture2D(u_texture_smoke, st).r;
        float fill = smoothstep(0.15, 0.5, field) * 0.5;                          // <- edita aqui: 0.5 = opacidade do preenchimento
        float edge = smoothstep(0.35, 0.4, field) - smoothstep(0.4, 0.45, field); // contorno fino na borda do campo
        vec3 silhueta_color = hsv2rgb(vec3(fract(u_time * 0.03), 0.7, 1.0));      // <- edita aqui: cor (gira devagar sozinha)
        col += silhueta_color * (fill + edge * 2.0) * silhueta_amt;
    }

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
