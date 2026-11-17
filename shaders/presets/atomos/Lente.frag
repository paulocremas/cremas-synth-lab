// fx: dobra=0.75, modo=0, onde=0.5, olho=0.5, distancia=0.35
// opcoes: modo=chao|canto
// cat: geometria
// bipolar: olho
// montagem: a geometria dos telões dobrados (ajusta uma vez pro lugar)
// ATOMOS · Lente. ANAMORFOSE pra telões DOBRADOS: dois painéis em ângulo (parede + chão = |_, ou duas paredes num
// canto) e o público num ponto vê a imagem RETA, como uma tela plana de frente pra ele, sem quebrar na dobra.
// dobra = quanto os painéis dobram (0 = plano = nada; 0.75 = 90°; 1 = 60°); modo = chao (dobra deitada: parede em
// cima, chão embaixo) ou canto (dobra em pé: parede da esquerda e da direita); onde = onde fica a dobra na imagem (de
// cima / da esquerda); olho = de onde o público olha dentro do ângulo (0.5 = no meio; no chao, 1 = mais alto);
// distancia = quão longe da dobra o público está (perto = correção forte).
// Fora da imagem corrigida = preto.

uniform float u_fx_dobra, u_fx_modo, u_fx_onde, u_fx_olho, u_fx_distancia;

void main() {
    vec2 st = uv();
    float a = aspecto();
    bool canto = floor(u_fx_modo * 1.999) > 0.5;
    // unidades = altura da imagem. s = distancia ATE a dobra, atravessando (> 0 = painel 1: parede de cima / da
    // esquerda; < 0 = painel 2: chao / parede da direita); e = posicao AO LONGO da dobra (0 = meio)
    float cf = canto ? u_fx_onde * a : u_fx_onde;
    float s = cf - (canto ? st.x * a : st.y);
    float e = canto ? st.y - 0.5 : (st.x - 0.5) * a;
    // corte de perfil (2D, a dobra e' a origem): painel 1 deitado em +x; o 2 girado de th em volta da dobra
    float th = radians(180.0 - u_fx_dobra * 120.0);
    vec2 P = s > 0.0 ? vec2(s, 0.0) : -s * vec2(cos(th), sin(th));
    float ph = th * mix(0.95, 0.05, u_fx_olho);              // direcao do olho dentro do angulo (0.5 = bissetriz)
    float D = mix(0.6, 8.0, u_fx_distancia * u_fx_distancia);
    vec2 n = vec2(cos(ph), sin(ph)), E = n * D;
    // plano de mentira: passa pela dobra, de FRENTE pro olho (normal n). O raio olho -> ponto do painel cruza o
    // plano em Q: o que o publico ve em P e' o pixel Q da imagem plana
    float den = D - dot(P, n);
    if (den < 0.05) { gl_FragColor = vec4(0.0, 0.0, 0.0, A(st).a); return; }   // atras do olho
    float t = D / den;
    float w = dot(E + t * (P - E), vec2(sin(ph), -cos(ph)));
    float ce = t * e;
    vec2 q = canto ? vec2((cf - w) / a, ce + 0.5) : vec2(ce / a + 0.5, cf - w);
    vec2 r = q;
    vec4 c = A(clamp(r, 0.0, 1.0));
    float fora = step(0.0, r.x) * step(r.x, 1.0) * step(0.0, r.y) * step(r.y, 1.0);
    gl_FragColor = vec4(c.rgb * fora, A(st).a);
}
