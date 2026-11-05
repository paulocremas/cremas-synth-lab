// fx: forma=0.17, angulo=0.0, quantos=0.0
// opcoes: forma=linear|radial|angulo
// cat: gerador
// mod: angulo=anda
// ATOMOS · Rampa. Degradê de preto a branco (a rampa do sintetizador de vídeo LZX): a matéria-prima de Paleta,
// Dobrar, Limiar e das máscaras. forma = linear (de um lado ao outro), radial (do centro pra fora) ou angulo (gira
// em volta do centro); angulo = pra onde aponta (linear) ou onde começa (radial/angulo) — movido, a rampa anda;
// quantos = quantas vezes repete (0 = uma).

uniform float u_fx_forma, u_fx_angulo, u_fx_quantos;

void main() {
    vec2 p = asp(uv());
    float m = floor(u_fx_forma * 2.999), t;
    if (m < 0.5) {
        float a = u_fx_angulo * 6.2831853;
        t = dot(p, vec2(cos(a), -sin(a))) / (0.5 * (abs(cos(a)) * aspecto() + abs(sin(a)))) * 0.5 + 0.5;
    } else if (m < 1.5) {
        t = length(p) / length(vec2(0.5 * aspecto(), 0.5)) - u_fx_angulo;
    } else {
        t = atan(-p.y, p.x) / 6.2831853 + 0.5 - u_fx_angulo;
    }
    float n = 1.0 + floor(15.0 * u_fx_quantos);   // (15 * x: e' knob, nao ESCOLHA)
    t = (n < 1.5 && m < 0.5) ? clamp(t, 0.0, 1.0) : fract(t * n);
    gl_FragColor = vec4(vec3(t), 1.0);
}
