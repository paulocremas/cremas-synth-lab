// fx: limiar=0.5, borda=0.3, inverter=0
// cat: mascara
// ATOMOS · Assunto. Máscara da pessoa/objeto principal (U²-Net). limiar = a partir de que certeza;
// borda = macia/dura; inverter = só o fundo. Sem a detecção ainda (1º quadro, branch sem fonte) = vazia.

uniform sampler2D u_subject;     // mascara do assunto da fonte, topo->baixo
uniform float u_subject_on;
uniform float u_fx_limiar, u_fx_borda, u_fx_inverter;

void main() {
    vec2 st = uv();
    float s = texture2D(u_subject, st).r * u_subject_on;
    float h = u_fx_borda * 0.5 + 1e-3;
    float m = smoothstep(u_fx_limiar - h, u_fx_limiar + h, s);
    m = mix(m, 1.0 - m, step(0.5, u_fx_inverter));
    gl_FragColor = vec4(vec3(m), 1.0);
}
