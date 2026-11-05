// fx: rastro=0.6, junta=0
// opcoes: junta=claro|mistura
// cat: tempo
// estado: canais=4, passos=1
// mod: rastro=drop
// ATOMOS · Feedback. A imagem volta em cima dela mesma (o LocalIn/LocalOut do SuperCollider): o que vem antes na
// corrente deixa RASTRO. Memória própria em 16 bits (o rastro apaga até o preto, sem fantasma) e passo fixo (o
// mesmo rastro a 30 e a 60 fps). rastro = quanto dura (0 = nada; 1 = ~6 s pra cair à metade); junta = claro (o
// mais claro fica: rastro de luz) ou mistura (o velho se dissolve no novo). Átomos soltos NO MEIO dele (↻) agem a
// cada volta: Rodar = espiral, Desfocar = fumaça, Matiz = arco-íris. limpar = apaga o rastro.

uniform float u_fx_rastro, u_fx_junta;

void main() {
    vec2 st = uv();
    if (u_vista > 0.5) { gl_FragColor = E(st); return; }
    vec4 cur = A(st);
    vec4 old = E(st);
    float k = u_fx_rastro < 0.005 ? 0.0 : decai(0.02 + u_fx_rastro * u_fx_rastro * 6.0);
    vec4 o;
    if (floor(u_fx_junta * 1.999) < 0.5) o = max(cur, old * k - u_dt * 0.004);   // claro: o piso garante o preto
    else o = mix(cur, old, k);
    o.rgb *= step(1.0 / 512.0, max(max(o.r, o.g), o.b));   // abaixo de meio nivel de 8 bits = preto (sem grao de dither)
    gl_FragColor = clamp(o, 0.0, 1.0);
}
