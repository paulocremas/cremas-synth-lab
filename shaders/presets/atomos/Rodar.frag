// fx: giro=0.5, zoom=0.5, velocidade=0.5
// cat: geometria
// bipolar: giro, zoom, velocidade
// ritmo: velocidade
// mod: zoom=pulsa
// ATOMOS · Rodar. Aproxima e gira a imagem em volta do centro. giro = ângulo fixo; zoom = aproxima/afasta;
// velocidade = gira sozinho (abaixo/acima = um sentido/outro). Os três: 0.5 = parado. No loop ↻ de um Feedback,
// cada volta gira de novo: o rastro vira espiral.

uniform float u_fx_zoom, u_fx_giro, u_fx_velocidade;

void main() {
    vec2 p = asp(uv());
    float a = (u_fx_giro - 0.5) * 6.2831853 + u_time * (u_fx_velocidade - 0.5) * 2.0;
    p = rot(a) * p / pow(4.0, u_fx_zoom - 0.5);
    gl_FragColor = A(fract(desasp(p)));
}
