// fx: smoke, layer
// Efeito ISOLADO (pedido do usuário: cada efeito no seu próprio arquivo, pra estudar um de
// cada vez — misturar vem depois, em outro preset). Reescrito com pesquisa de verdade sobre
// como fumaça é feita em GLSL: a técnica clássica pra fogo/fumaça/fluido 2D barato não é
// ruído genérico (curl noise, Perlin) — é "turbulence": deslocar a posição de leitura com
// senos cuja fase é a própria posição girada por uma matriz de rotação que acumula giro a
// cada iteração (frequência sobe, amplitude cai — como fBm, só que deformando coordenada em
// vez de somar ruído). Ver mini.gmshaders.com/p/turbulence. Essa parte roda no Python
// (native_synth.py — SMOKE_SRC) porque fumaça precisa de MEMÓRIA entre frames (persistir,
// decair, subir) — um shader sozinho não tem estado, só vê o frame atual. Aqui é só o
// "acabamento": pega a densidade já calculada (u_texture_fumaca) e decide a cor.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform sampler2D u_texture_fumaca; // densidade 0..1 (canal .r) — motion + turbulência + decaimento, no Python

// potenciometros de efeito (aba "Visuals" -> tuning.FX -> state['fx']). 0 = desligado,
// 1 = cheio. Sem toggle = uniform ausente = no-op silencioso.
uniform float u_fx_smoke;
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

    // ===== FUMAÇA — sobe de onde a imagem está se mexendo de verdade (motion real: compara
    // o frame atual com o anterior). Aditivo, então nunca esconde o fundo por baixo.
    float smoke_amt = u_fx_smoke; // <- edita aqui. 0 = desligado, 1 = cheio
    if (smoke_amt > 0.1) {
        float density = texture2D(u_texture_fumaca, st).r;
        // fina = acinzentada/azulada (translúcida), densa = branca — como fumaça de verdade
        vec3 grey = mix(vec3(0.55, 0.58, 0.63), vec3(0.95), smoothstep(0.05, 0.55, density)); // <- edita aqui: cores fina/densa
        vec3 rainbow = hsv2rgb(vec3(fract(u_time * 0.04 + density * 0.15), 0.55, 1.0));
        vec3 smoke_color = mix(grey, rainbow, 0.15); // <- edita aqui: 0 = fumaça realista pura, 1 = arco-íris total
        col += smoke_color * density * smoke_amt;
    }

    // ===== CAMADA: mistura o efeito com a imagem crua (mesmo esquema do image.frag) =====
    float layer = u_fx_layer; // <- edita aqui. 0 = só original, 1 = só efeito
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
