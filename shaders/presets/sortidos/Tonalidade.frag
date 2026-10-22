// fx: base=0.3, forca=0.6, harmonia=0.5, brilho=0.5, layer, on_kick=0, on_sub=0, on_lowmid=0, on_mid=0, on_highmid=0, on_presence=0, on_treble=0, on_brilliance=0, on_air=0
// SORTIDOS · Tonalidade. Pinta a imagem com uma PALETA HARMONICA tirada do TOM da musica (ritmo.py):
// a cor do tom (circulo das quintas ou Scriabin, aba Audio) vai nos meios-tons; as sombras e as luzes
// ganham a cor HARMONICA dela — harmonia 0 = analoga (vizinha), 0.5 = complementar (oposta),
// 1 = triade (120°). Tom menor = paleta mais fechada (menos saturada). Confianca baixa do tom = efeito
// mais fraco (nao pinta com um tom chutado). base/forca = quanto pinta parado/no disparo; brilho =
// realce das luzes. Caixas no dash: on_kick = so' junto com o kick; on_<faixa> = faixas que disparam.
#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform sampler2D u_texture_0;
uniform float u_amp;
uniform float u_kick;
uniform float u_subbass, u_lowmid, u_midrange, u_highmid, u_presence, u_treble_hi, u_brilho, u_air;
uniform float u_key_hue, u_key_minor, u_key_conf;
uniform float u_fx_on_kick, u_fx_on_sub, u_fx_on_lowmid, u_fx_on_mid, u_fx_on_highmid,
              u_fx_on_presence, u_fx_on_treble, u_fx_on_brilliance, u_fx_on_air;
uniform float u_fx_layer;
uniform float u_fx_base;
uniform float u_fx_forca;
uniform float u_fx_harmonia;
uniform float u_fx_brilho;

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

vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    float l = dot(orig, vec3(0.299, 0.587, 0.114));
    // harmonia 0..1 -> deslocamento de matiz: 1/12 (analoga) .. 1/2 (complementar) .. 1/3 (triade)
    float d = u_fx_harmonia < 0.5 ? mix(1.0 / 12.0, 0.5, u_fx_harmonia * 2.0) : mix(0.5, 1.0 / 3.0, (u_fx_harmonia - 0.5) * 2.0);
    float sat = mix(0.85, 0.55, u_key_minor);
    vec3 cTom = hsv2rgb(vec3(u_key_hue, sat, 1.0));
    vec3 cSombra = hsv2rgb(vec3(fract(u_key_hue + d), sat, 0.35));
    vec3 cLuz = hsv2rgb(vec3(fract(u_key_hue - d * 0.5), sat * 0.5, 1.0));
    // gradiente sombra -> tom -> luz pela luminancia (um "gradient map" harmonico)
    vec3 pal = l < 0.5 ? mix(cSombra, cTom * 0.8, l * 2.0) : mix(cTom * 0.8, cLuz, (l - 0.5) * 2.0);
    pal *= mix(1.0, 1.0 + u_fx_brilho * 0.6, smoothstep(0.6, 1.0, l));
    float a = clamp(u_fx_base + u_fx_forca * nivel(), 0.0, 1.0) * clamp(u_key_conf * 1.5, 0.0, 1.0);
    vec3 col = mix(orig, pal, a);
    gl_FragColor = vec4(mix(orig, col, u_fx_layer), 1.0);
}
