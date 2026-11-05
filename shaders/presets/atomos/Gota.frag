// fx: forca=0.4, tamanho=0.4, velocidade=0.5
// cat: distorcao
// ritmo: velocidade
// mod: forca=pulsa
// ATOMOS · Gota. Anéis saem do centro e entortam a imagem, como pedra na água. forca = altura dos anéis (0 = nada);
// tamanho = anéis juntos (0) a espaçados (1); velocidade = rapidez com que se abrem.

uniform float u_fx_forca, u_fx_tamanho, u_fx_velocidade;

void main() {
    vec2 st = uv(), p = asp(st);
    float r = length(p), f = mix(70.0, 10.0, u_fx_tamanho);
    float w = sin(r * f - u_time * u_fx_velocidade * 8.0) * u_fx_forca * 0.025 * smoothstep(0.0, 0.08, r);
    vec2 d = p / max(r, 1e-4) * w;
    gl_FragColor = A(st + vec2(d.x / aspecto(), d.y));
}
