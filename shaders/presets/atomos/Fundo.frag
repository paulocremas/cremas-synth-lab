// fx: limiar=0.5, borda=0.3
// cat: mascara
// ATOMOS · Fundo. Máscara do FUNDO: tudo menos a pessoa/objeto principal (IA U²-Net; o contrário do Assunto).
// Efeitos da caixa só no fundo. limiar = a partir de que certeza é pessoa; borda = macia/dura. Pra TIRAR o fundo
// (transparente), use o Assunto com "recortar" na caixa. Sem a detecção ainda = fundo inteiro.

uniform sampler2D u_subject;     // mascara do assunto da fonte, topo->baixo
uniform float u_subject_on;
uniform float u_fx_limiar, u_fx_borda;

void main() {
    vec2 st = uv();
    float s = texture2D(u_subject, st).r * u_subject_on;
    float h = u_fx_borda * 0.5 + 1e-3;
    gl_FragColor = vec4(vec3(1.0 - smoothstep(u_fx_limiar - h, u_fx_limiar + h, s)), 1.0);
}
