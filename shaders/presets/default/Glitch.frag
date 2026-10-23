// fx: sens=0.4, blocos=0.7, rasgo=0.6, espelho=0, pixel=0.3, poster=0.3, neon=0.3, inverte=0, layer=0.85
// cat: distorcao
// Doideira digital, primo do image.frag: tudo reage ao áudio. Sliders:
//   blocos  = no kick, blocos da tela pulam pro lado (datamosh fake)
//   rasgo   = faixas horizontais escorregam com o grave (VHS rasgando)
//   espelho = caleidoscópio que gira com os médios (0 = imagem normal)
//   pixel   = pixeliza com os agudos              poster = poucas cores (posterização)
//   neon    = falsa cor: brilho vira arco-íris     inverte = negativo piscando na batida
//   layer   = 0 só original, 1 só efeito
//   sens    = quanto o áudio mexe em tudo (0 = parado, 1 = nervoso)

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
uniform float u_subbass;
uniform float u_highmid;

uniform float u_fx_sens;
uniform float u_fx_blocos;
uniform float u_fx_rasgo;
uniform float u_fx_espelho;
uniform float u_fx_pixel;
uniform float u_fx_poster;
uniform float u_fx_neon;
uniform float u_fx_inverte;
uniform float u_fx_layer;

float random(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec3 orig = texture2D(u_texture_0, st).rgb;
    float aspect = u_resolution.x / u_resolution.y;
    // relógio em degraus: o glitch "sorteia" de novo ~12x/s em vez de tremer todo frame
    float tick = floor(u_time * 6.0);

    // ===== ESPELHO: caleidoscópio — dobra o ângulo em N fatias, gira com os médios =====
    if (u_fx_espelho > 0.01) {
        vec2 p = st - 0.5;
        p.x *= aspect;
        float n = floor(2.0 + u_fx_espelho * 8.0);              // <- edita aqui: 2..10 fatias
        float a = atan(p.y, p.x) + u_time * 0.2 + u_mid * u_fx_sens;
        float slice = 6.2832 / n;
        a = abs(mod(a, slice) - slice * 0.5);
        p = vec2(cos(a), sin(a)) * length(p);
        p.x /= aspect;
        st = mix(st, p + 0.5, u_fx_espelho);
    }

    // ===== RASGO: cada faixa horizontal escorrega um tanto aleatório, mais no grave =====
    float lines = 40.0;                                          // <- edita aqui: nº de faixas
    float row = floor(st.y * lines);
    float tear = (random(vec2(row, tick)) - 0.5) * step(0.7, random(vec2(row * 1.7, tick)));
    st.x += tear * 0.06 * (u_bass + u_subbass) * u_fx_sens * u_fx_rasgo;

    // ===== BLOCOS: no kick, alguns blocos copiam a imagem de outro lugar =====
    vec2 cell = floor(st * vec2(16.0, 9.0));                     // <- edita aqui: grade dos blocos
    float pick = random(cell + tick);
    if (pick < u_kick * u_fx_sens * u_fx_blocos * 0.25) {   // <- edita aqui: fração máx. de blocos que pulam
        st += (vec2(random(cell * 3.1 + tick), random(cell * 7.3 + tick)) - 0.5) * 0.12;
    }

    // ===== PIXEL: quantiza a coordenada (tamanho do pixel sobe com o agudo) =====
    float px = mix(1.0, 24.0, u_fx_pixel * (0.3 + 0.7 * u_treble * u_fx_sens)); // <- edita aqui: pixel máximo em px
    st = (floor(st * u_resolution / px) + 0.5) * px / u_resolution;

    // RGB rachado: cada canal lê com um empurrão diferente quando o kick bate
    float split = 0.006 * u_kick * u_fx_sens * (u_fx_blocos + u_fx_rasgo);
    vec3 col = vec3(texture2D(u_texture_0, fract(st + vec2(split, 0.0))).r,
                    texture2D(u_texture_0, fract(st)).g,
                    texture2D(u_texture_0, fract(st - vec2(split, split * 0.5))).b);

    // ===== POSTER: poucos níveis por canal =====
    float levels = mix(32.0, 3.0, u_fx_poster);                  // <- edita aqui: menos = mais chapado
    col = mix(col, floor(col * levels) / levels, step(0.01, u_fx_poster));   // floor = arredonda pra baixo (escurece)

    // ===== NEON: falsa cor — o brilho vira matiz que corre no tempo =====
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    vec3 neon = hsv2rgb(vec3(lum * 2.0 + u_time * 0.1 + u_highmid, 0.9, lum));   // valor = brilho original (nao clareia)
    col = mix(col, neon, u_fx_neon);

    // ===== INVERTE: negativo que pisca na batida (meio a meio: imagem escura invertida = quase branca) =====
    col = mix(col, 1.0 - col, step(0.9, u_kick) * u_fx_inverte * u_fx_sens * 0.5);

    gl_FragColor = vec4(mix(orig, col, u_fx_layer), 1.0);
}
