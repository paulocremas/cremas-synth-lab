// fx: liquid, colorvibe, particles, smoke, silhueta, aura, pulse, layer
// ^ manifest lido por dash_data.parse_fx_manifest: cada nome vira o uniform u_fx_<nome>
//   (0..1, 1.0 = cheio) e um potenciometro na aba "Visuals" do dash.
//   SNAPSHOT salvo à parte (pedido do usuário) — cópia do Caos.frag no momento em que ele
//   tinha os dois efeitos separados: EFEITO 6 fumaça procedural (u_texture_fumaca) +
//   EFEITO 7 silhueta gráfica (sim de fluido, u_texture_smoke). Caos.frag é o arquivo "vivo"
//   que segue sendo editado; esse aqui fica parado nesse ponto.
//   v3: mais movimento (a VELOCIDADE dos efeitos agora reage a musica, nao so a
//   intensidade), cores mais psicodelicas (plasma RGB = grave/medio/agudo cada um
//   pilotando um canal de cor) e particulas com hue girando sozinho + pulso por batida.
//   v4: + FUMAÇA saindo de onde a imagem se mexe (u_texture_fumaca — calculado no Python,
//   native_synth.py: diff do frame com o anterior + buffer que persiste, decai e sobe com
//   curl noise; ver SMOKE_SRC la).
//   v5: tentei trocar a fumaca por uma simulacao de fluido de verdade (Stable Fluids,
//   u_texture_smoke) — ficou parecendo uma cortina caindo, nao fumaca subindo de objeto
//   (bug de convencao de eixo Y entre o espaco da sim e o da tela, bem provavelmente).
//   Em vez de arriscar mais um ajuste as cegas, a FUMAÇA voltou a usar a versao
//   procedural (que ja funcionava bem) e a sim de fluido virou EFEITO 7 "SILHUETA" —
//   o resultado dela sozinho e' grafico/interessante, so nao parece fumaca.

#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform sampler2D u_texture_fumaca; // densidade da fumaça procedural 0..1 (canal .r) — EFEITO 6
uniform sampler2D u_texture_smoke;  // campo da sim de fluido 0..1 (canal .r) — EFEITO 7 silhueta
uniform float u_amp;     // 0..1, volume geral — usado como VELOCIDADE do fluido e do plasma
uniform float u_bass;    // 0..1, grave — canal R do plasma (EFEITO 2)
uniform float u_mid;     // 0..1, medio — canal G do plasma + saturacao/hue (EFEITO 2)
uniform float u_treble;  // 0..1, agudo — canal B do plasma + deriva das particulas (EFEITO 3)
uniform float u_kick;    // 0..1, pula na batida e decai sozinho — EFEITO 3/4/5
uniform vec3 u_dominant; // cor RGB mais frequente do frame atual — EFEITO 4 aura

// faixas finas de mixagem/EQ (0..1)
uniform float u_subbass;  // EFEITO 1 líquido — força da ondulação
uniform float u_presence; // EFEITO 3 partículas — tamanho de cada uma
uniform float u_brilho;   // EFEITO 4 aura — intensidade do halo

// potenciometros de efeito (aba "Visuals" -> tuning.FX -> state['fx']). 0 = desligado,
// 1 = cheio. Sem toggle = uniform ausente = no-op silencioso.
uniform float u_fx_liquid;
uniform float u_fx_colorvibe;
uniform float u_fx_particles;
uniform float u_fx_smoke;
uniform float u_fx_silhueta;
uniform float u_fx_aura;
uniform float u_fx_pulse;
uniform float u_fx_layer;

// ruído branco pontual — hash de uma posição -> 0..1
float random(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

// ruído suave (value noise, interpolação smoothstep entre 4 hashes de grade) — base do líquido
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = random(i);
    float b = random(i + vec2(1.0, 0.0));
    float c = random(i + vec2(0.0, 1.0));
    float d = random(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// conversão RGB <-> HSV padrão (cor vibrante + arco-íris das partículas/pulso)
vec3 rgb2hsv(vec3 c) {
    vec4 k = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, k.wz), vec4(c.gb, k.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec4 k = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + k.xyz) * 6.0 - k.www);
    return c.z * mix(k.xxx, clamp(p - k.xxx, 0.0, 1.0), c.y);
}

// EFEITO 3: PARTÍCULAS — pontinhos coloridos flutuando por cima da cena (aditivo, não
// mexe na UV de leitura da imagem — o fundo nunca fica escondido por causa delas).
// busca nas 9 células vizinhas (3x3) pra partícula poder derivar sem "pular" na borda.
vec3 particles(vec2 uv) {
    vec3 acc = vec3(0.0);
    float grid = 12.0;                      // <- edita aqui: densidade (nº de células por eixo)
    vec2 cell = floor(uv * grid);
    float speed = 0.3 + 0.9 * u_treble;     // <- edita aqui: agudo acelera a deriva (mais movimento)
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 c = cell + vec2(float(x), float(y));
            float rnd = random(c);
            vec2 drift = 0.45 * vec2(sin(u_time * speed * 0.6 + rnd * 6.2831),
                                      cos(u_time * speed * 0.5 + rnd * 6.2831));
            vec2 center = (c + 0.5 + drift) / grid;
            float kick_pulse = 1.0 + 1.3 * u_kick * random(c + 1.7); // cada uma reage um pouco diferente
            float size = (0.003 + 0.01 * u_presence) * kick_pulse;   // <- edita aqui: tamanho base
            float d = length(uv - center);
            float core = smoothstep(size, 0.0, d);
            float halo = smoothstep(size * 4.0, 0.0, d) * 0.3;       // brilho suave ao redor do núcleo
            float hue = fract(rnd + u_time * 0.15 + u_mid * 0.3);    // matiz girando sozinho = psicodélico
            acc += hsv2rgb(vec3(hue, 0.95, 1.0)) * (core + halo);
        }
    }
    return acc;
}

void main() {
    vec2 st = gl_FragCoord.xy / u_resolution;
    st.y = 1.0 - st.y;
    vec2 st0 = st; // UV crua, congelada antes de qualquer efeito — partículas e blend final usam essa

    // ===== EFEITO 1: LÍQUIDO — ondula a leitura da imagem como água (2 camadas de ruído) =====
    // subbass incha a força; u_amp (volume geral) acelera o fluxo — música mais alta = flui mais rápido
    float liquid_amt = u_fx_liquid;     // <- edita aqui. 0 = desligado, 1 = cheio
    if (liquid_amt > 0.0) {
        float speed = 0.04 + 0.6 * u_amp;                        // <- edita aqui: velocidade base do fluxo
        vec2 flow_uv = st * 3.0 + u_time * speed;
        float nx = 0.7 * vnoise(flow_uv) + 0.3 * vnoise(flow_uv * 2.5 - u_time * speed * 0.7);
        float ny = 0.7 * vnoise(flow_uv + 100.0) + 0.3 * vnoise(flow_uv * 2.5 + 100.0 - u_time * speed * 0.7);
        float wobble = 0.015 + 0.05 * u_subbass;                  // <- edita aqui: força do fluido
        st += (vec2(nx, ny) - 0.5) * wobble * liquid_amt;
    }

    vec3 col = texture2D(u_texture_0, st).rgb;

    // ===== EFEITO 2: COR PSICODÉLICA — gira o matiz + tinge com um plasma RGB=grave/médio/agudo =====
    // cada canal de cor do plasma é literalmente pilotado por uma faixa diferente da música;
    // u_amp acelera tudo (plasma "ferve" mais rápido quando a música está mais alta)
    float colorvibe_amt = u_fx_colorvibe; // <- edita aqui. 0 = cor original, 1 = psicodélico total
    if (colorvibe_amt > 0.0) {
        vec3 hsv = rgb2hsv(col);
        hsv.y = clamp(hsv.y * (1.0 + 0.7 * u_mid), 0.0, 1.0);       // <- edita aqui: força da saturação
        hsv.x = fract(hsv.x + u_time * 0.05 * (0.2 + u_mid));       // <- edita aqui: velocidade do giro
        vec3 shifted = hsv2rgb(hsv);

        float speed = 0.6 + 1.8 * u_amp;                            // <- edita aqui: velocidade do plasma
        float p1 = sin(st0.x * 8.0 + u_time * speed + u_bass * 6.0);
        float p2 = sin(st0.y * 8.0 - u_time * speed * 1.3 + u_mid * 6.0);
        float p3 = sin((st0.x + st0.y) * 8.0 + u_time * speed * 0.7 + u_treble * 6.0);
        vec3 plasma = 0.5 + 0.5 * vec3(p1, p2, p3);

        col = mix(col, shifted * plasma * 1.4, colorvibe_amt);
    }

    // ===== EFEITO 3: PARTÍCULAS — soma o glow colorido de particles() em cima da imagem =====
    col += particles(st0) * u_fx_particles * (0.4 + 0.8 * u_presence);

    // ===== EFEITO 6: FUMAÇA — sobe de onde a imagem está se mexendo (motion real: native_synth.py
    // compara o frame atual com o anterior e alimenta um buffer que persiste, decai e sobe com
    // curl noise — ver SMOKE_SRC/u_texture_fumaca). Aditivo, então nunca esconde o fundo.
    float smoke_amt = u_fx_smoke;       // <- edita aqui. 0 = desligado, 1 = cheio
    if (smoke_amt > 0.0) {
        float density = texture2D(u_texture_fumaca, st0).r;
        // fina = acinzentada/azulada (translúcida), densa = branca — como fumaça de verdade
        vec3 grey = mix(vec3(0.55, 0.58, 0.63), vec3(0.95), smoothstep(0.05, 0.55, density)); // <- edita aqui: cores fina/densa
        vec3 rainbow = hsv2rgb(vec3(fract(u_time * 0.04 + density * 0.15), 0.55, 1.0));
        vec3 smoke_color = mix(grey, rainbow, 0.15); // <- edita aqui: 0 = fumaça realista pura, 1 = arco-íris total
        col += smoke_color * density * smoke_amt;
    }

    // ===== EFEITO 7: SILHUETA — formas grandes e gráficas vindas da simulação de fluido de
    // verdade (Stable Fluids, native_synth.py — SIM_*_SRC/u_texture_smoke). Não parece fumaça
    // (grade baixa + confinamento de vorticidade forte = blobs, não fibras finas), mas sozinha
    // é um visual gráfico interessante — por isso o estilo aqui é chapado/contornado, não suave.
    float silhueta_amt = u_fx_silhueta; // <- edita aqui. 0 = desligado, 1 = cheio
    if (silhueta_amt > 0.0) {
        float field = texture2D(u_texture_smoke, st0).r;
        float fill = smoothstep(0.15, 0.5, field) * 0.5;                          // <- edita aqui: 0.5 = opacidade do preenchimento
        float edge = smoothstep(0.35, 0.4, field) - smoothstep(0.4, 0.45, field); // contorno fino na borda do campo
        vec3 silhueta_color = hsv2rgb(vec3(fract(u_time * 0.03), 0.7, 1.0));      // <- edita aqui: cor (gira devagar sozinha)
        col += silhueta_color * (fill + edge * 2.0) * silhueta_amt;
    }

    // ===== EFEITO 4: AURA DA COR DOMINANTE — halo aditivo, metade cor da cena / metade arco-íris =====
    // brilho infla o halo; o kick dá uma piscada extra de intensidade
    float aura_amt = u_fx_aura;         // <- edita aqui. 0 = desligado, 1 = cheio
    if (aura_amt > 0.0) {
        vec3 aura_color = mix(u_dominant, hsv2rgb(vec3(fract(u_time * 0.08), 1.0, 1.0)), 0.5);
        float glow = smoothstep(0.7, 0.0, length(st0 - 0.5)) * (0.3 + 0.7 * u_brilho) * (1.0 + 1.5 * u_kick);
        col += aura_color * glow * aura_amt; // <- edita aqui: 0.7 = raio do halo (mais acima)
    }

    // ===== EFEITO 5: PULSO + ONDA DE CHOQUE — clarão colorido e um anel que se expande na batida =====
    // o anel usa o próprio decaimento do u_kick (1 no hit -> 0) como "tempo desde a batida":
    // raio cresce E o brilho cai juntos, sem precisar guardar estado entre frames
    float pulse_amt = u_fx_pulse;       // <- edita aqui. 0 = desligado, 1 = cheio
    vec3 pulse_color = hsv2rgb(vec3(fract(u_time * 0.12), 0.85, 1.0));
    col += pulse_color * u_kick * 0.35 * pulse_amt;           // <- edita aqui: 0.35 = força do clarão

    float t_since = 1.0 - u_kick;
    float ring_r = t_since * 0.9;                             // <- edita aqui: 0.9 = até onde o anel chega
    float ring = smoothstep(0.05, 0.0, abs(length(st0 - 0.5) - ring_r)) * u_kick;
    col += pulse_color * ring * 1.2 * pulse_amt;              // <- edita aqui: 1.2 = brilho do anel

    // ===== CAMADA: mistura a pilha de efeitos com a imagem crua (mesmo esquema do image.frag) =====
    vec3 orig = texture2D(u_texture_0, st0).rgb;
    float layer = u_fx_layer;           // <- edita aqui. 0 = só original, 1 = só efeitos
    col = mix(orig, col, layer);

    gl_FragColor = vec4(col, 1.0);
}
