// fx: matiz1=0.6, matiz2=0.05, giro=0, salto=0.5, contraste=0.5, layer, on_kick=0, on_sub=1, on_lowmid=0, on_mid=0, on_highmid=0, on_presence=0, on_treble=0, on_brilliance=0, on_air=0
// cat: cor
// SORTIDOS · Duotone. Pinta a imagem com 2 cores (sombra → luz). matiz1 = cor da sombra; matiz2 = cor da luz;
// giro = as duas giram sozinhas; salto = o nível gira as duas; contraste = mais duro.
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
uniform float u_fx_matiz1;
uniform float u_fx_matiz2;
uniform float u_fx_giro;
uniform float u_fx_salto;
uniform float u_fx_contraste;

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
    float lum = dot(orig, vec3(0.299, 0.587, 0.114));
    lum = clamp((lum - 0.5) * (0.5 + 2.0 * u_fx_contraste) + 0.5, 0.0, 1.0);
    float sh = u_time * u_fx_giro * 0.2 + n * u_fx_salto * 0.5;
    col = mix(hsv2rgb(vec3(fract(u_fx_matiz1 + sh), 0.9, 0.35)), hsv2rgb(vec3(fract(u_fx_matiz2 + sh), 0.8, 1.0)), lum);
    gl_FragColor = vec4(mix(orig, col, u_fx_layer), 1.0);
}
