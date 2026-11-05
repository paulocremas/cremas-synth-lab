// fx: forca=0.75
// cat: luz
// mod: forca=passos
// ATOMOS · Níveis. Poucos tons, como serigrafia (posterizar). forca = de nada (0) a só 2 tons por cor (1).

uniform float u_fx_forca;

void main() {
    vec4 c = A(uv());
    float n = floor(2.0 + (1.0 - u_fx_forca) * (1.0 - u_fx_forca) * 30.0);
    vec3 p = floor(c.rgb * n + 0.5) / n;
    gl_FragColor = vec4(mix(c.rgb, p, smoothstep(0.0, 0.1, u_fx_forca)), c.a);
}
