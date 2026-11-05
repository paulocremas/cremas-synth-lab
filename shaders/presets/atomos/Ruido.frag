// fx: tamanho=0.6, velocidade=0.3, detalhe=0.4
// cat: gerador
// ritmo: velocidade
// mod: velocidade=respira
// ATOMOS · Ruído. Nuvem cinza que se mexe sozinha e se dobra nela mesma (fbm com domain warping, Inigo Quilez):
// matéria-prima pra direção (relevo/redemoinho num Deslocar ou Fluido), máscara (Luma), Paleta, Dobrar. Cinza opaco
// (quantidade pura); pra ver por cima, modo soma/tela ou a opacidade. tamanho = grão fino (0) a nuvem grande (1);
// velocidade = quanto anda; detalhe = liso (0) a rendado (1). Cada Ruído tem a sua semente: dois nunca são iguais.

uniform float u_fx_tamanho, u_fx_velocidade, u_fx_detalhe;

void main() {
    vec2 p = asp(uv()) * mix(10.0, 1.0, u_fx_tamanho);
    float t = u_time * u_fx_velocidade * 0.4;
    vec2 q = vec2(fbm(p + vec2(0.0, t), u_fx_detalhe), fbm(p + vec2(5.2, 1.3) - vec2(t * 0.7, 0.0), u_fx_detalhe));
    vec2 r = vec2(fbm(p + 2.0 * q + vec2(1.7, 9.2) + t * 0.3, u_fx_detalhe), fbm(p + 2.0 * q + vec2(8.3, 2.8), u_fx_detalhe));
    float n = fbm(p + 2.0 * r, u_fx_detalhe);
    gl_FragColor = vec4(vec3(smoothstep(0.15, 0.85, n)), 1.0);
}
