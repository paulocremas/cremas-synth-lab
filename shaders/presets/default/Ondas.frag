// fx: aneis, foco, zoom, torcao, cor, flash, layer
// cat: gerador
// Efeito de brincar: cada uma das 8 faixas vira um anel concêntrico (Sub-bass no centro → Air
// na borda) que acende com a energia dela. Sliders:
//   aneis  = força dos anéis           foco  = qual faixa fica em destaque (0 = Sub-bass … 1 = Air)
//   zoom   = grave pulsa a imagem       torcao = médios torcem a imagem em espiral
//   cor    = agudos giram a cor         flash  = piscada na batida (kick)
//   layer  = 0 só original, 1 só efeito

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_bass;
uniform float u_mid;
uniform float u_treble;
uniform float u_kick;

// as 8 faixas, na ordem do dash
uniform float u_subbass;
uniform float u_lowmid;
uniform float u_midrange;
uniform float u_highmid;
uniform float u_presence;
uniform float u_treble_hi;
uniform float u_brilho;
uniform float u_air;

uniform float u_fx_aneis;
uniform float u_fx_foco;
uniform float u_fx_zoom;
uniform float u_fx_torcao;
uniform float u_fx_cor;
uniform float u_fx_flash;
uniform float u_fx_layer;

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

// GLSL ES 1.0 não indexa uniform por variável → if-chain
float band(int i) {
    if (i == 0) return u_subbass;
    if (i == 1) return u_lowmid;
    if (i == 2) return u_midrange;
    if (i == 3) return u_highmid;
    if (i == 4) return u_presence;
    if (i == 5) return u_treble_hi;
    if (i == 6) return u_brilho;
    return u_air;
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;

    // coordenadas centradas, corrigidas pelo aspecto (anel redondo, não oval)
    vec2 p = st - 0.5;
    p.x *= u_resolution.x / u_resolution.y;
    float r = length(p);

    // ===== ZOOM (grave) + TORÇÃO (médios) na imagem =====
    vec2 uv = p / (1.0 + 0.25 * u_bass * u_fx_zoom);
    float ang = u_mid * u_fx_torcao * 3.0 * smoothstep(0.6, 0.0, r);
    uv = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * uv;
    uv.x /= u_resolution.x / u_resolution.y;
    vec3 col = texture2D(u_texture_0, uv + 0.5).rgb;

    // ===== ANÉIS: faixa i ocupa o raio (i+0.5)/8 * 0.6 =====
    int foco = int(floor(u_fx_foco * 7.99));
    vec3 rings = vec3(0.0);
    for (int i = 0; i < 8; i++) {
        float e = band(i);
        float center = (float(i) + 0.5) / 8.0 * 0.6;
        float width = 0.004 + 0.03 * e; // <- edita aqui: espessura base / quanto a energia engorda
        float ring = smoothstep(width, 0.0, abs(r - center));
        float boost = (i == foco) ? 2.5 : 0.6; // faixa em foco brilha mais
        float hue = float(i) / 8.0 + u_time * 0.05 + u_treble * u_fx_cor;
        rings += hsv2rgb(vec3(hue, 0.8, 1.0)) * ring * e * boost;
    }
    col += rings * u_fx_aneis * 2.0;

    // ===== COR: agudos giram o matiz da imagem inteira =====
    float h = u_treble * u_fx_cor * 6.2832;
    col = mix(col, col.gbr, 0.5 - 0.5 * cos(h)); // ponytail: rotação barata de canais, não HSV de verdade

    // ===== FLASH na batida, na cor da faixa em foco =====
    col += hsv2rgb(vec3(float(foco) / 8.0, 0.6, 1.0)) * u_kick * u_fx_flash * 0.5;

    gl_FragColor = vec4(mix(orig, col, u_fx_layer), 1.0);
}
