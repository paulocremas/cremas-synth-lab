// fx: tamanho=0.5, borda=0.3, inverter=0
// cat: mascara
// ATOMOS · Corpo. Máscara do esqueleto de uma pessoa (IA BlazePose, 33 pontos): tronco, braços, pernas e cabeça
// como tubos. tamanho = grossura (osso fino a silhueta cheia); borda = macia/dura; inverter = tudo menos o corpo.
// Precisa ver o corpo (de longe): só o rosto na câmera dá esqueleto chutado.

uniform vec3 u_corpo[33];        // x, y (uv topo->baixo), visibilidade 0..1 dos pontos do MediaPipe
uniform float u_corpo_on;
uniform float u_fx_tamanho, u_fx_borda, u_fx_inverter;

vec2 P(vec3 a) { return a.xy * u_resolution; }

float osso(vec2 p, vec3 a, vec3 b, float r) {     // tubo de a ate' b, raio r (px); 0..1 = dentro / distancia
    vec2 pa = p - P(a), ba = P(b) - P(a);
    float d = length(pa - ba * clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0)) / r;
    return d + 9.0 * step(min(a.z, b.z), 0.5);    // ponto escondido = sem osso
}

void main() {
    vec2 st = uv();
    vec2 p = st * u_resolution;
    float ombro = length(P(u_corpo[11]) - P(u_corpo[12])) + 1.0;   // largura dos ombros = escala do corpo
    float r = ombro * mix(0.05, 0.3, u_fx_tamanho);
    vec3 om = (u_corpo[11] + u_corpo[12]) * 0.5, qd = (u_corpo[23] + u_corpo[24]) * 0.5;
    float d = osso(p, om, qd, ombro * 0.5 + r);                     // tronco: do meio dos ombros ao do quadril
    d = min(d, osso(p, u_corpo[0], u_corpo[0], ombro * 0.3 + r));   // cabeca: bola no nariz
    d = min(d, osso(p, u_corpo[11], u_corpo[13], r));
    d = min(d, osso(p, u_corpo[13], u_corpo[15], r));
    d = min(d, osso(p, u_corpo[12], u_corpo[14], r));
    d = min(d, osso(p, u_corpo[14], u_corpo[16], r));
    d = min(d, osso(p, u_corpo[15], u_corpo[19], r * 0.8));
    d = min(d, osso(p, u_corpo[16], u_corpo[20], r * 0.8));
    d = min(d, osso(p, u_corpo[23], u_corpo[25], r * 1.2));
    d = min(d, osso(p, u_corpo[25], u_corpo[27], r));
    d = min(d, osso(p, u_corpo[24], u_corpo[26], r * 1.2));
    d = min(d, osso(p, u_corpo[26], u_corpo[28], r));
    d = min(d, osso(p, u_corpo[27], u_corpo[31], r * 0.8));
    d = min(d, osso(p, u_corpo[28], u_corpo[32], r * 0.8));
    float h = u_fx_borda * 0.5 + 0.02;
    float m = (1.0 - smoothstep(1.0 - h, 1.0 + h, d)) * u_corpo_on;
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
