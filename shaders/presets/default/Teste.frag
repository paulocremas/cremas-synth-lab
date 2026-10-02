// fx: grade=1, cor=0.6, varredura=1, layer
// PADRÃO DE TESTE pro pixel map / telão (ver tools/telao_sim.py). Não é efeito: troca a imagem
// por referências que DENUNCIAM erro de mapeamento — com a fonte cobrindo o canvas inteiro
// (rect padrão), cada linha/diagonal tem que atravessar as telas reta e contínua; degrau = ox/oy
// ou pw/ph errado. Quadrado branco = canto de cima à esquerda (espelhou/virou → aparece em outro
// canto). Fundo: matiz anda em x, brilho em y → a cor diz de onde no canvas o pedaço veio.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;

uniform float u_fx_grade;     // linhas: grade fina (1/32), grossa (1/8), diagonais, moldura
uniform float u_fx_cor;       // brilho do fundo colorido
uniform float u_fx_varredura; // barra que corre em x (tearing / atraso entre telas)
uniform float u_fx_layer;

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

// 1 em cima de uma linha a cada `n` (em uv), `w` pixels de largura
float lines(vec2 st, float n, float w) {
    vec2 d = abs(fract(st * n + 0.5) - 0.5) / n * u_resolution;
    return 1.0 - smoothstep(w * 0.5, w * 0.5 + 1.0, min(d.x, d.y));
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;                                   // origem em cima, igual ao dash/canvas
    vec3 orig = texture2D(u_texture_0, st).rgb;

    // ===== FUNDO: posição vira cor =====
    vec3 col = hsv2rgb(vec3(st.x * 0.85, 0.75, mix(0.9, 0.35, st.y))) * u_fx_cor;

    // ===== GRADE + DIAGONAIS + MOLDURA =====
    float g = lines(st, 32.0, 1.0) * 0.35 + lines(st, 8.0, 2.0);
    vec2 px = st * u_resolution;
    float dg = min(abs(st.x - st.y), abs(st.x - (1.0 - st.y))) * min(u_resolution.x, u_resolution.y);
    g = max(g, 1.0 - smoothstep(1.0, 2.0, dg));
    float edge = min(min(px.x, u_resolution.x - px.x), min(px.y, u_resolution.y - px.y));
    col = mix(col, vec3(1.0, 0.1, 0.1), (1.0 - smoothstep(3.0, 4.0, edge)) * u_fx_grade);
    col = mix(col, vec3(1.0), clamp(g, 0.0, 1.0) * u_fx_grade);

    // ===== CANTO DE CIMA À ESQUERDA (orientação) + CENTRO =====
    vec2 q = st / vec2(1.0 / 32.0);
    if (q.x > 0.5 && q.x < 2.5 && q.y > 0.5 && q.y < 2.5) col = vec3(1.0);
    float r = length((st - 0.5) * u_resolution) / min(u_resolution.x, u_resolution.y);
    col = mix(col, vec3(1.0, 1.0, 0.0), (1.0 - smoothstep(1.0, 2.0, abs(r - 0.25) * min(u_resolution.x, u_resolution.y))) * u_fx_grade);

    // ===== VARREDURA: barra que dá a volta em x a cada 4 s =====
    float bx = fract(u_time * 0.25);
    col = mix(col, vec3(0.0, 1.0, 0.6), (1.0 - smoothstep(0.004, 0.006, abs(st.x - bx))) * u_fx_varredura);

    // ===== CAMADA: mistura o padrão com a imagem crua (mesmo esquema do image.frag) =====
    col = mix(orig, col, u_fx_layer);
    gl_FragColor = vec4(col, 1.0);
}
