// fx: base=0.3, forca=0.7, linhas=0.5, rolagem=0.3, cor=0.5, layer, on_kick=1, on_sub=0, on_lowmid=0, on_mid=0, on_highmid=0, on_presence=0, on_treble=0, on_brilliance=0, on_air=0
// SORTIDOS · VHS. Fita VHS: linhas, rasgos horizontais e cor borrada. base/forca = estrago parado/no disparo;
// linhas = densidade das linhas; rolagem = velocidade dos rasgos; cor = sangramento de cor.
// Caixas no dash: on_kick = só junto com o kick; on_<faixa> = faixas que disparam (várias = a mais
// forte vale; nenhuma = volume geral). layer = 0 só original, 1 só efeito.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_amp;
uniform float u_kick;
uniform float u_subbass, u_lowmid, u_midrange, u_highmid, u_presence, u_treble_hi, u_brilho, u_air;
// caixas do dash (0/1): on_kick + as faixas que disparam — pode marcar várias
uniform float u_fx_on_kick, u_fx_on_sub, u_fx_on_lowmid, u_fx_on_mid, u_fx_on_highmid,
              u_fx_on_presence, u_fx_on_treble, u_fx_on_brilliance, u_fx_on_air;
uniform float u_fx_layer;
uniform float u_fx_base;
uniform float u_fx_forca;
uniform float u_fx_linhas;
uniform float u_fx_rolagem;
uniform float u_fx_cor;

// NIVEL 0..1 que dispara o efeito = o MAIOR entre as faixas marcadas (nenhuma = volume geral).
// on_kick = só na batida (u_kick pula pra 1 e decai): sem faixa marcada = a batida pura; com
// faixa = batida × nível da faixa.
float nivel() {
    float b = max(max(max(step(.5, u_fx_on_sub) * u_subbass, step(.5, u_fx_on_lowmid) * u_lowmid),
                      max(step(.5, u_fx_on_mid) * u_midrange, step(.5, u_fx_on_highmid) * u_highmid)),
                  max(max(step(.5, u_fx_on_presence) * u_presence, step(.5, u_fx_on_treble) * u_treble_hi),
                      max(step(.5, u_fx_on_brilliance) * u_brilho, step(.5, u_fx_on_air) * u_air)));
    float marcou = step(.5, max(max(max(u_fx_on_sub, u_fx_on_lowmid), max(u_fx_on_mid, u_fx_on_highmid)),
                                max(max(u_fx_on_presence, u_fx_on_treble), max(u_fx_on_brilliance, u_fx_on_air))));
    float kick = step(.5, u_fx_on_kick);
    return mix(mix(u_amp, 1.0, kick), b, marcou) * mix(1.0, u_kick, kick);
}

vec3 rgb2hsv(vec3 c) {
    vec4 k = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, k.wz), vec4(c.gb, k.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1.0e-10)), d / (q.x + 1.0e-10), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
vec2 espelha(vec2 uv) { return 1.0 - abs(1.0 - mod(uv, 2.0)); }  // fora de 0..1 = reflete, sem borda

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    float n = nivel();
    vec3 col = orig;
    float a = clamp(u_fx_base + u_fx_forca * n, 0.0, 1.0);
    float line = 0.5 + 0.5 * sin(st.y * u_resolution.y * (0.3 + 1.2 * u_fx_linhas) * 3.14159);
    float jit = (fract(sin(floor(st.y * 80.0 + u_time * u_fx_rolagem * 40.0) * 91.7) * 4375.85) - 0.5) * 0.02 * a;
    vec2 uv = vec2(st.x + jit, st.y);
    float sp = 0.006 * a * u_fx_cor;
    vec3 c = vec3(texture2D(u_texture_0, espelha(uv + vec2(sp, 0.0))).r, texture2D(u_texture_0, espelha(uv)).g,
                  texture2D(u_texture_0, espelha(uv - vec2(sp, 0.0))).b);
    col = c * mix(1.0, 0.6 + 0.4 * line, a);
    gl_FragColor = vec4(mix(orig, col, u_fx_layer), 1.0);
}
