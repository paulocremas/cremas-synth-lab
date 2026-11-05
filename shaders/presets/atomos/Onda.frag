// fx: forca=0.3, tamanho=0.4, velocidade=0.6
// cat: distorcao
// ritmo: velocidade
// mod: forca=grave
// ATOMOS · Onda. Ondas atravessam a imagem como bandeira. forca = altura da onda (0 = nada); tamanho = largura;
// velocidade = rapidez.

uniform float u_fx_forca, u_fx_tamanho, u_fx_velocidade;

void main() {
    vec2 st = uv();
    float f = mix(40.0, 3.0, u_fx_tamanho), t = u_time * u_fx_velocidade * 6.0;
    vec2 d = vec2(sin(st.y * f + t), cos(st.x * aspecto() * f * 0.8 + t * 1.3)) * u_fx_forca * 0.04;
    gl_FragColor = A(st + vec2(d.x / aspecto(), d.y));
}
