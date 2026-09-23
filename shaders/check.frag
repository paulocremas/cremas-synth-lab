#ifdef GL_ES
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;

void main() {
    // "oscilador": mesmo sin() do SinOsc, só que 1x por frame em vez de 48000x por segundo
    float onda = sin(u_time * 4.0) * 0.5 + 0.5;
    gl_FragColor = vec4(vec3(onda), 1.0);
}
