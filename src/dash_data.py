"""Funcoes puras que produzem os NUMEROS do dashboard (nao formatam terminal nem HTML).

Fonte unica de verdade do dash de audio: o audio_thread chama audio_dash_data() e publica
o dict em state['audio_dash']; tanto o dash de terminal quanto o payload HTTP so renderizam
esse mesmo dict. Sem import de native_synth (evita circular) — so numpy.
"""
import glob
import json
import math
import os
import re
import tempfile

import numpy as np


def parse_fx_manifest(src):
    """Nomes dos potenciometros de efeito que um shader expoe, do comentario-cabecalho
    "// fx: nome1, nome2, ..." (aba Efeitos do dash). Sem essa linha -> []. Cada nome vira
    o uniform u_fx_<nome> no GLSL (0..1, 1.0 = cheio) e um slider no dash. "nome=0.5" da' o
    valor padrao do knob (ver parse_fx_defaults)."""
    return list(parse_fx_defaults(src))


def parse_fx_defaults(src):
    """{nome: padrao} do cabecalho "// fx: nome, nome=0.5, ..." — padrao = valor do knob
    enquanto a entrada da pilha nao tem forca gravada (e o do duplo-clique). Sem "=x" -> 1.0."""
    m = re.search(r'(?m)^//\s*fx:\s*(.+)$', src or '')
    out = {}
    for s in (m.group(1).split(',') if m else []):
        n, _, d = s.partition('=')
        if not n.strip():
            continue
        try:
            v = min(1.0, max(0.0, float(d))) if d.strip() else 1.0
        except ValueError:
            v = 1.0
        out[n.strip()] = v
    return out

def parse_meta(src):
    """Modulo (dash v3): {cat, ins, desc} do cabecalho — "// cat: cor", "// in: fb, src" (entradas
    padrao ao inserir: u_texture_1/2) e a 1a linha de comentario livre ("// SET · Nome. desc" -> desc)."""
    src = src or ''
    m = re.search(r'(?m)^//\s*cat:\s*(\S+)', src)
    i = re.search(r'(?m)^//\s*in:\s*(.+)$', src)
    d = re.search(r'(?m)^//(?!\s*(?:fx|cat|in|mod|opcoes|bipolar|ritmo|estado|escala):)\s*(.+)$', src)
    mo = re.search(r'(?m)^//\s*mod:\s*(.+)$', src)
    desc = d.group(1).strip() if d else ''
    nome = ''
    if '·' in desc:   # "SORTIDOS · Contorno. Contornos em neon." -> "Contornos em neon." (+ nome "Contorno", com acento)
        nome = desc.split('·', 1)[1].strip().partition('.')[0].strip()
        desc = desc.split('·', 1)[1].strip().partition('. ')[2] or desc
    out = {'cat': m.group(1) if m else '', 'ins': [s.strip() for s in i.group(1).split(',') if s.strip()][:2] if i else [],
           'desc': desc}
    if nome:   # o nome mostrado no dash (o arquivo nao tem acento: Reacao.frag -> "Reação")
        out['nome'] = nome[:32]
    if mo:   # MOVIMENTO SUGERIDO: "// mod: forca=pulsa, matiz=respira" (knob = preset de MOV_PRESETS; o dash oferece, nao liga)
        out['mod'] = {k.strip(): v.strip() for k, _, v in (x.partition('=') for x in mo.group(1).split(',')) if k.strip() and v.strip()}
    ch = knob_switches(src)
    if ch:
        out['chave'] = ch
    es = knob_choices(src)
    if es:
        out['escolha'] = es
    for tag in ('bipolar', 'ritmo'):   # ATOMO v2: knob de dois lados (0.5 = nada) / que pode travar no BPM
        if _header_list(src, tag):
            out[tag] = _header_list(src, tag)
    est = parse_estado(src)
    if est:                            # ATOMO v2: atomo com MEMORIA (o dash oferece semear/limpar)
        out['estado'] = est
    return out


def knob_choices(src):
    """Knobs que sao ESCOLHA (um entre N): o codigo le floor(u_fx_X * K) (K ~ N - 0.01). -> {knob: [nomes]}; os nomes vem de
    "// opcoes: modo=a|b|c" no cabecalho (sem eles, "1".."N"). O valor guardado da opcao i e' (i + 0.5) / N."""
    code = re.sub(r'//[^\n]*', '', src or '')
    op = re.search(r'(?m)^//\s*opcoes:\s*(.+)$', src or '')
    names = {}
    if op:
        for part in re.split(r'[;,]\s*(?=\w+=)', op.group(1)):
            k, _, v = part.partition('=')
            names[k.strip()] = [x.strip() for x in v.split('|') if x.strip()]
    out = {}
    for k in parse_fx_defaults(src):
        m = re.search(r'floor\(\s*u_fx_' + re.escape(k) + r'\s*\*\s*([0-9.]+)\s*\)', code)
        if not m:
            continue
        n = int(round(float(m.group(1))))
        if 2 <= n <= 16:
            nm = names.get(k) or []
            out[k] = nm if len(nm) == n else [str(i + 1) for i in range(n)]
    return out


def knob_switches(src):
    """Knobs que sao CHAVE (liga/desliga): o codigo so' os le como step(0.5, u_fx_X) — o dash mostra um botao, nao
    um knob. Deduzido do codigo (sem cabecalho): quem usa o valor continuo continua knob."""
    code = re.sub(r'//[^\n]*', '', src or '')
    out = []
    for k in parse_fx_defaults(src):
        uses = len(re.findall(r'\bu_fx_' + re.escape(k) + r'\b', code))
        steps = len(re.findall(r'step\(\s*0?\.5\s*,\s*u_fx_' + re.escape(k) + r'\s*\)', code))
        if steps and steps == uses - 1:   # -1 = a declaracao do uniform
            out.append(k)
    return out



# PADRAO ATOMO (shaders/ATOMO.md): o que um .frag de shaders/presets/atomos/ pode e nao pode
ATOM_CATS = ('cor', 'luz', 'forma', 'geometria', 'distorcao', 'textura', 'tempo', 'mistura', 'gerador', 'mascara')
ATOM_DRAW_CATS = ('gerador', 'forma')   # quem DESENHA/gera: vai POR CIMA da corrente; o resto e' FILTRO (TROCA, ATOMO §5)


def atom_replaces(rel, src):
    """COMO o atomo entra na corrente (ATOMO §5): True = FILTRO, a saida dele SUBSTITUI a entrada (opacidade = o quanto
    do original volta; o alfa e' o que ele devolve: leu transparente, fica transparente); False = DESENHA por cima
    (gerador, traco; e todo shader classico, que sempre foi camada com cobertura). Base opaca = o mesmo resultado."""
    return is_atom_path(rel) and parse_meta(src)['cat'] not in ATOM_DRAW_CATS
MASK_UNIFORMS = {'u_subject', 'u_subject_on'}   # so' atomo de MASCARA (dash v5): a mascara do assunto (U2-Net) da fonte
MASK_UNIFORMS |= {'u_rosto', 'u_olhos', 'u_rosto_on', 'u_corpo', 'u_corpo_on', 'u_obj', 'u_obj_p', 'u_obj_on', 'u_olho', 'u_olho_on'}   # + o RASTREIO (src/rastreio.py)
ATOM_MAX_KNOBS = 3   # minimalismo: o principal + ate' 2 detalhes essenciais; mais que isso = dividir em atomos
ATOM_UNIFORMS = {'u_resolution', 'u_time', 'u_beat', 'u_bar', 'u_phrase', 'u_texture_0', 'u_texture_1', 'u_texture_2', 'u_texture_src'}

# PRELUDIO do ATOMO v2 (shaders/ATOMO.md §3): o motor poe ISTO antes de todo .frag de presets/atomos/ (atom_source).
# O atomo nao declara estes uniforms nem copia funcoes: a mesma palavra faz a mesma coisa em todo atomo. Texturas
# topo->baixo (A/B/C/S leem em uv()); o ESTADO (E) e' gravado em gl_FragCoord, entao E() vira de volta. u_agl = 1:
# u_texture_0 tambem esta' em orientacao GL (loop RETORNO: o atomo le o estado de outro como a sua corrente).
ATOM_PRELUDE_U = {'u_resolution', 'u_time', 'u_beat', 'u_bar', 'u_phrase', 'u_dt', 'u_seed', 'u_vista', 'u_fase',
                  'u_semear', 'u_agl', 'u_texture_0', 'u_texture_1', 'u_texture_2', 'u_texture_src', 'u_state'}
ATOM_PRELUDE = """#ifdef GL_ES
precision highp float;
#endif
uniform vec2 u_resolution;
uniform float u_time, u_beat, u_bar, u_phrase, u_dt, u_seed, u_vista, u_fase, u_semear, u_agl;
uniform sampler2D u_texture_0, u_texture_1, u_texture_2, u_texture_src, u_state;
vec2 uv() { vec2 s = gl_FragCoord.xy / u_resolution; return vec2(s.x, 1.0 - s.y); }
vec2 px() { return 1.0 / u_resolution; }
vec2 _ag(vec2 s) { return u_agl > 0.5 ? vec2(s.x, 1.0 - s.y) : s; }
vec4 A(vec2 s) { return texture2D(u_texture_0, _ag(s)); }
vec4 Am(vec2 s) { vec4 c = A(s); return vec4(c.rgb * c.a, c.a); }
vec4 B(vec2 s) { return texture2D(u_texture_1, s); }
vec4 C(vec2 s) { return texture2D(u_texture_2, s); }
vec4 S(vec2 s) { return texture2D(u_texture_src, s); }
vec4 E(vec2 s) { return texture2D(u_state, vec2(s.x, 1.0 - s.y)); }
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float aspecto() { return u_resolution.x / u_resolution.y; }
vec2 asp(vec2 s) { return vec2((s.x - 0.5) * aspecto(), s.y - 0.5); }
vec2 desasp(vec2 p) { return vec2(p.x / aspecto() + 0.5, p.y + 0.5); }
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
float hash(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031 + u_seed * 0.6180339);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p), u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p, float detalhe) {
    float s = 0.0, a = 0.5, w = 0.0, n = 1.0 + floor(clamp(detalhe, 0.0, 1.0) * 5.0);
    for (int i = 0; i < 6; i++) {
        if (float(i) >= n) break;
        s += a * noise(p); w += a;
        p = rot(0.6) * p * 2.03 + 17.1; a *= 0.5;
    }
    return s / w;
}
float _lu(sampler2D t, vec2 s) { return luma(texture2D(t, s).rgb); }
vec2 dirOf(sampler2D t, vec2 s, float modo, float ang) {
    if (modo < 0.5) { float a = ang * 6.2831853; return vec2(cos(a), -sin(a)); }
    if (modo > 2.5) { vec2 v = (texture2D(t, s).rg - 0.5) * 2.0; return vec2(v.x, -v.y); }
    vec2 e = vec2(1.0 / (240.0 * aspecto()), 1.0 / 240.0);
    vec2 g = vec2(_lu(t, s + vec2(e.x, 0.0)) - _lu(t, s - vec2(e.x, 0.0)),
                  _lu(t, s + vec2(0.0, e.y)) - _lu(t, s - vec2(0.0, e.y))) * 6.0;
    if (modo > 1.5) g = vec2(-g.y, g.x);
    else g = -g;
    float l = length(g);
    return l > 1.0 ? g / l : g;
}
vec3 paleta(float t, vec3 a, vec3 b, vec3 c, vec3 d) { return a + b * cos(6.2831853 * (c * t + d)); }
float decai(float s) { return exp2(-u_dt / max(s, 1e-4)); }
"""


def is_atom_path(rel):
    """O .frag e' um ATOMO (recebe o preludio)? rel = caminho sob shaders/ ('presets/atomos/X.frag')."""
    return str(rel or '').replace('\\', '/').lstrip('/').startswith('presets/atomos/')


def atom_source(rel, src):
    """Fonte que vai pro compilador: atomo = PRELUDIO + o arquivo (#line: o erro aponta a linha do arquivo — GLSL
    1.10, sem #version: a linha depois de '#line N' e' a N+1). Outros shaders: como estao."""
    return ATOM_PRELUDE + '#line 0\n' + src if is_atom_path(rel) else src


def parse_estado(src):
    """'// estado: canais=4, passos=8, fases=1, escala=0.25' -> {canais, passos, fases, escala} | None (sem estado).
    passos = quantos passos a cada 1/60 s (passo fixo); fases = sub-passes por passo (u_fase 0..F-1, a sim de
    fluido); escala = linhas do buffer / 1080 (fixa: a mesma forma em qualquer saida)."""
    m = re.search(r'(?m)^//\s*estado:\s*(.*)$', src or '')
    if not m:
        return None
    kv = {k.strip(): v.strip() for k, _, v in (x.partition('=') for x in m.group(1).split(',')) if k.strip()}
    num = lambda k, lo, hi, d, t=float: max(lo, min(hi, t(kv[k]))) if re.fullmatch(r'[0-9.]+', kv.get(k, '')) else d
    return {'canais': num('canais', 1, 4, 4, int), 'passos': num('passos', 1, 32, 1, int),
            'fases': num('fases', 1, 64, 1, int), 'escala': num('escala', 0.05, 2.0, 0.5)}


def _header_list(src, tag):
    """'// bipolar: giro, zoom' -> ['giro', 'zoom']."""
    m = re.search(r'(?m)^//\s*' + tag + r':\s*(.+)$', src or '')
    return [x.strip() for x in m.group(1).split(',') if x.strip()] if m else []


def atom_problems(src):
    """Regras do padrao ATOMO v2 que o .frag quebra (lista vazia = ok). Ver shaders/ATOMO.md. O arquivo e' lido SEM
    o preludio (o motor o poe antes: atom_source) — declarar um uniform dele = erro de compilacao."""
    src = src or ''
    out, fx, meta = [], parse_fx_defaults(src), parse_meta(src)
    code = re.sub(r'//[^\n]*', '', src)
    if len(fx) > ATOM_MAX_KNOBS:
        out.append(f'{len(fx)} knobs: atomo tem no maximo {ATOM_MAX_KNOBS} (o principal + 2 detalhes); o resto e\' outro atomo')
    if meta['cat'] not in ATOM_CATS:
        out.append(f"// cat: '{meta['cat']}' nao e' um tipo de atomo ({', '.join(ATOM_CATS)})")
    if not re.search(r'(?m)^//\s*ATOMOS\s*·\s*\S', src):
        out.append('falta a linha "// ATOMOS · Nome. o que faz"')
    for n in re.findall(r'\buniform\s+\w+\s+([^;]+);', code):
        for u in (x.strip().split('[')[0] for x in n.split(',')):
            if u.startswith('u_fx_'):
                k = u[5:]
                if k == 'layer' or k.startswith('on_'):
                    out.append(f'knob proibido {k}: misturar = opacidade da peca; som = modulador no knob')
                elif k not in fx:
                    out.append(f'{u} declarado mas fora do // fx:')
            elif u in ATOM_PRELUDE_U:
                out.append(f'{u} vem do preludio: nao declare (ATOMO.md §3)')
            elif u in MASK_UNIFORMS and meta['cat'] != 'mascara':
                out.append(f'{u} so\' em atomo de mascara (// cat: mascara)')
            elif u not in MASK_UNIFORMS:
                out.append(f'{u} nao e\' entrada de atomo (so\' imagem e relogio: o preludio; som = modulador no knob)')
    if re.search(r'^\s*#\s*(ifdef\s+GL_ES|version)', code, re.M):
        out.append('#ifdef GL_ES/#version vem do preludio')
    for k in fx:
        if not re.search(r'\bu_fx_' + re.escape(k) + r'\b', code):
            out.append(f'knob {k} do // fx: nao e\' usado no codigo')
    if re.search(r'\b(u_texture_[12]|[BC]\s*\()', code) and not meta['ins']:
        out.append('le a entrada B (B()/u_texture_1) sem "// in:"')
    for k, v in (meta.get('mod') or {}).items():
        if k not in fx and k != 'opacity':
            out.append(f'// mod: knob {k} nao existe no // fx:')
        if v not in MOV_PRESETS:
            out.append(f"// mod: '{v}' nao e' um movimento ({', '.join(MOV_PRESETS)})")
    for tag in ('bipolar', 'ritmo'):
        for k in _header_list(src, tag):
            if k not in fx:
                out.append(f'// {tag}: knob {k} nao existe no // fx:')
    est = meta.get('estado')
    if est:
        if not re.search(r'\bu_vista\b', code):
            out.append('// estado: sem u_vista (fase 0 atualiza, 1 mostra)')
        if re.search(r'\bu_time\b', code):
            out.append('// estado: acumula com u_dt/decai(), nao com u_time (passo fixo)')
    elif re.search(r'\b(u_state|u_vista|u_fase|u_semear|E\s*\()', code):
        out.append('le o estado (E()/u_state/u_vista) sem "// estado:"')
    if 'gl_FragColor' not in code:
        out.append('sem gl_FragColor')
    return out


# MODULADOR LFO (dash v4: peca de controle que se solta num knob; mod[knob] = {b: ['lfo'], lo, hi, lfo: {f, r, ph}})
IMG_MODS = (('luz', 'BRILHO'), ('mov', 'MOVIMENTO'))   # fonte de modulacao -> grid da analise da imagem de entrada


def img_mod_levels(image):
    """Analise da imagem de entrada (image_dash_data) -> {'luz', 'mov'} 0..1 pros knobs modulados pela IMAGEM."""
    tot = {g.get('name'): g.get('total', 0.0) for g in (image or {}).get('grids') or ()}
    return {k: max(0.0, min(1.0, float(tot.get(g, 0.0)))) for k, g in IMG_MODS}


LFO_SHAPES = ('sin', 'tri', 'saw', 'sq', 'rnd', 'sh', 'passos')   # sh = acaso SEGURADO (S&H); passos = sequencia 'st'


def lfo(p, bpos):
    """Valor 0..1 de um LFO no TEMPO da musica. p = {f: forma (LFO_SHAPES), r: batidas por ciclo, ph: fase
    0..1}; bpos = batidas desde um '1' (continuo; sem tempo detectado o native conta a 120 BPM). sin/tri
    comecam em 0 no '1'; sq = metade ligado; rnd = acaso suave (um valor novo por ciclo, deslizando do anterior)."""
    p = p or {}
    c = bpos / max(1 / 16, float(p.get('r') or 4)) + float(p.get('ph') or 0)
    x, f = c % 1.0, p.get('f', 'sin')
    if f == 'tri':
        return 1.0 - abs(2.0 * x - 1.0)
    if f == 'saw':
        return x
    if f == 'sq':
        return 1.0 if x < 0.5 else 0.0
    if f in ('rnd', 'sh'):
        a, b = _h(math.floor(c)), _h(math.floor(c) + 1)
        return a if f == 'sh' else a + (b - a) * (0.5 - 0.5 * math.cos(math.pi * x))
    if f == 'passos':
        st = [v for v in p.get('st') or () if isinstance(v, (int, float))] or [1.0, 0.0, 0.5, 0.0]
        return max(0.0, min(1.0, float(st[min(len(st) - 1, int(x * len(st)))])))
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * x)


def _h(k):
    """acaso deterministico 0..1 de um inteiro (o mesmo k = o mesmo valor em todo knob que segue o movimento)."""
    return (math.sin(k * 12.9898 + 78.233) * 43758.5453) % 1.0


# MOVIMENTO (Claude Doc "PRISMA — sync com a musica"): fonte -> modo -> forma -> faixa. mod[knob] = {b, lo, hi, lfo?,
# modo?, ev?, env?, seg?, q?, id?, nome?}. Formato velho (sem modo) = 'loop' se b tem 'lfo', senao 'segue' sem slew.
MOV_MODES = ('loop', 'disparo', 'segue')
TRACK_SIGNALS = ('rosto.x', 'rosto.y', 'rosto.tam', 'mao.x', 'mao.y', 'corpo.x', 'corpo.abre', 'obj.x', 'obj.y', 'obj.tam')
TRACK_GATES = ('rosto.on', 'mao.on', 'corpo.on', 'obj.on')
SECOES = ('intro', 'sobe', 'drop', 'pausa')
EVENTS = ('batida', 'compasso', 'frase', 'kick', 'golpe') + tuple('secao:' + x for x in SECOES) + TRACK_GATES \
    + ('pad:1', 'pad:2', 'pad:3', 'pad:4')
# presets de 1 gesto (dash: botao do knob). faixa = (de, ate') RELATIVA ao valor do knob (None = absoluta 0..1)
MOV_PRESETS = {
    'pulsa':   {'mod': {'b': [], 'modo': 'disparo', 'ev': {'src': 'kick'}, 'env': {'a': 0, 'd': 0.5}}, 'faixa': (0.0, 0.4)},
    'respira': {'mod': {'b': ['lfo'], 'modo': 'loop', 'lfo': {'f': 'sin', 'r': 4, 'ph': 0}}, 'faixa': (-0.25, 0.25)},
    'anda':    {'mod': {'b': ['lfo'], 'modo': 'loop', 'lfo': {'f': 'saw', 'r': 16, 'ph': 0}}, 'faixa': None},
    'passos':  {'mod': {'b': ['lfo'], 'modo': 'loop', 'lfo': {'f': 'passos', 'r': 4, 'ph': 0, 'st': [1, 0, 0.5, 0, 0.75, 0, 0.25, 0]}}, 'faixa': (-0.3, 0.3)},
    'acaso':   {'mod': {'b': ['lfo'], 'modo': 'loop', 'lfo': {'f': 'sh', 'r': 1, 'ph': 0}}, 'faixa': (-0.3, 0.3)},
    'grave':   {'mod': {'b': ['subbass'], 'modo': 'segue', 'seg': {'a': 10, 'r': 200}}, 'faixa': (0.0, 1.0)},
    'drop':    {'mod': {'b': [], 'modo': 'disparo', 'ev': {'src': 'secao:drop'}, 'env': {'a': 0, 'd': 8}}, 'faixa': (0.0, 1.0)},
    'abaixa':  {'mod': {'b': [], 'modo': 'disparo', 'ev': {'src': 'kick'}, 'env': {'a': 0, 'd': 0.5}}, 'faixa': (0.0, -0.5)},
}


def env(a, d, x):
    """ENVELOPE AD em batidas: x = batidas desde o disparo. Sobe em `a` (linear), cai em `d` (curva (1-t)^2: soco
    rapido e cauda). Antes do disparo / depois do fim = 0."""
    if x < 0:
        return 0.0
    a, d = max(0.0, float(a or 0)), max(1e-3, float(d or 0.5))
    if x < a:
        return x / a
    t = (x - a) / d
    return (1.0 - t) ** 2 if t < 1 else 0.0


def ev_ok(cond, k, salt=0):
    """CONDICAO do evento (trig condition do Elektron) para a k-esima vez (1, 2, 3...) que ele aconteceu:
    {n: N} a cada N | {a: A, b: B} A:B (a A-esima de cada B) | {p: 0..1} probabilidade | {first: 1} so' a 1a."""
    if not cond:
        return True
    if cond.get('first'):
        return k == 1
    if 'b' in cond:
        b = max(1, int(cond['b']))
        return (k - 1) % b + 1 == max(1, min(b, int(cond.get('a', 1))))
    if 'n' in cond:
        return (k - 1) % max(1, int(cond['n'])) == 0
    if 'p' in cond:
        return _h(k * 7.31 + salt) < float(cond['p'])
    return True


def track_signals(kind, d):
    """Rastreio (dict da track_thread: u_rosto/u_corpo/u_obj + on) -> SINAIS 0..1 com y PRA CIMA (1 = alto da tela).
    Posicao x fica no ultimo lugar quando perde; o resto (y, tamanho, abertura) vai junto com 'on' (some com a pessoa)."""
    d = d or {}
    on = float(d.get('on', 0.0))
    if kind == 'rosto':
        r = d.get('u_rosto')
        if r is None or len(r) < 4:
            return {}
        return {'rosto.x': float(r[0]), 'rosto.y': (1 - float(r[1])) * on, 'rosto.tam': min(1.0, float(r[2]) * 2.5) * on}
    if kind == 'corpo':
        c = d.get('u_corpo')
        if c is None or len(c) < 99:
            return {}
        c = np.asarray(c, np.float32).reshape(33, 3)
        w = [i for i in (15, 16) if c[i, 2] > 0.5] or [15, 16]       # pulsos visiveis (MediaPipe: 15 esq, 16 dir)
        top = min(w, key=lambda i: c[i, 1])                           # a mao mais alta
        return {'mao.x': float(c[top, 0]), 'mao.y': (1 - float(c[top, 1])) * on,
                'corpo.x': float((c[23, 0] + c[24, 0]) / 2), 'corpo.abre': min(1.0, abs(float(c[15, 0] - c[16, 0])) * 1.5) * on}
    if kind == 'obj':
        o = d.get('u_obj')
        if o is None or len(o) < 4:
            return {}
        x0, y0, x1, y1 = (float(v) for v in o[:4])
        return {'obj.x': (x0 + x1) / 2, 'obj.y': (1 - (y0 + y1) / 2) * on, 'obj.tam': min(1.0, max(0.0, (x1 - x0) * (y1 - y0)) * 4) * on}
    return {}


TRACK_KIND = {'rosto': 'rosto', 'mao': 'corpo', 'corpo': 'corpo', 'obj': 'obj'}   # prefixo do sinal -> thread de rastreio


# espelha FREQ_BANDS (native_synth.py) pro lado web/JSON — nome, [lo, hi] default, cor.
_FREQ_BANDS = [
    ('Sub-bass', 20, 250, (30, 140, 255)), ('Low-mid', 250, 500, (0, 200, 255)),
    ('Midrange', 500, 2000, (0, 230, 200)), ('High-mid', 2000, 4000, (140, 140, 255)),
    ('Presence', 4000, 6000, (190, 100, 255)), ('Treble', 6000, 10000, (225, 80, 255)),
    ('Brilliance', 10000, 16000, (255, 70, 210)), ('Air', 16000, 20000, (255, 110, 160)),
]
FREQ_BAND_RGB = {name: rgb for name, _, _, rgb in _FREQ_BANDS}
_GREY = (95, 95, 95)  # Hz que nao cai em nenhuma faixa (buraco no modo crossover)


def _band_rgb_for_hz(hz, lohi=None):
    """Cor da faixa de mixagem que contem esse Hz, ou cinza se nenhuma. `lohi` = [(lo, hi)]x8
    ao vivo (de native_synth.freq_bands); sem ele usa os defaults de _FREQ_BANDS."""
    pairs = lohi if lohi is not None else [(lo, hi) for _, lo, hi, _ in _FREQ_BANDS]
    for (lo, hi), (*_, rgb) in zip(pairs, _FREQ_BANDS):
        if lo <= hz < hi:
            return rgb
    return _GREY


def band_magnitudes(spectrum, freqs, bars):
    """`bars` faixas log (30Hz-Nyquist): (freq do topo, magnitude media bruta). Faixa mais
    estreita que a resolucao da FFT usa o bin mais proximo do centro (senao viraria 0/-120dB,
    artefato, nao silencio de verdade)."""
    edges = np.logspace(np.log10(30), np.log10(freqs[-1]), bars + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (freqs >= lo) & (freqs < hi)
        mag = spectrum[mask].mean() if mask.any() else spectrum[np.argmin(np.abs(freqs - (lo + hi) / 2))]
        out.append((float(hi), float(mag)))
    return out


def audio_dash_data(bands_raw, amp_raw, amp_raw_level, amp_final, amp_smoothing,
                    kick_final, kick_decay, smooth_spectrum, freqs, bars=24, range_db=40.0,
                    band_lohi=None):
    """Monta o dict do dash de audio.

    bands_raw: 8 tuplas (nome, mag_bruta, nivel_bruto, final, smoothing) na ordem grave->agudo
    de FREQ_BANDS. 'bands' sai na ordem de exibicao do terminal: amp primeiro, depois agudo->grave.
    Cada linha tem raw_mag (magnitude crua, sem teto), raw_level (0..1 relativo ao pico da
    propria banda, sem suavizar), final (o que vai pro shader), smoothing (coef attack/release
    que valeu no chunk) e delta = |final - raw_level|.
    'spectrum': `bars` faixas log, agudo em cima, com db absoluto e rel (0..1, dB abaixo do
    pico do frame / range_db)."""
    rows = [{'name': 'amp', 'rgb': None, 'raw_mag': amp_raw, 'raw_level': amp_raw_level,
             'final': amp_final, 'smoothing': amp_smoothing,
             'delta': min(1.0, abs(amp_final - amp_raw_level))}]
    for name, mag, lvl, final, s in reversed(bands_raw):
        rows.append({'name': name, 'rgb': FREQ_BAND_RGB.get(name),
                     'raw_mag': float(mag), 'raw_level': float(lvl), 'final': float(final),
                     'smoothing': float(s), 'delta': min(1.0, abs(float(final) - float(lvl)))})

    mags = band_magnitudes(smooth_spectrum, freqs, bars)
    peak_db = 20.0 * np.log10(max(m for _, m in mags) + 1e-6)
    spectrum = []
    for hz, mag in reversed(mags):
        db = 20.0 * np.log10(mag + 1e-6)
        rel = float(np.clip((db - peak_db + range_db) / range_db, 0.0, 1.0))
        spectrum.append({'hz': int(round(hz)), 'db': round(float(db), 1), 'rel': round(rel, 3),
                         'rgb': _band_rgb_for_hz(hz, band_lohi)})

    return {
        'kick': {'final': round(float(kick_final), 4), 'decay': round(float(kick_decay), 4)},
        'bands': [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
        'spectrum': spectrum,
    }


def parse_xrandr(text):
    """Saida de `xrandr --query` -> [{name, primary, active, w, h, x, y, pref}] das saidas CONECTADAS.
    active = tem modo ligado agora (w/h/x/y = geometria atual; 0 se nao). pref = [w, h] do modo
    preferido do EDID (o '+'), senao o 1o listado — e' o que `xrandr --auto` liga. Plug novo
    (telao, processadora, dummy) costuma aparecer conectado mas DESLIGADO."""
    outs, cur = [], None
    for line in (text or '').splitlines():
        m = re.match(r'(\S+) (connected|disconnected)( primary)?(?: (\d+)x(\d+)\+(-?\d+)\+(-?\d+))?', line)
        if m:
            cur = None
            if m.group(2) == 'connected':
                w, h, x, y = (int(v) if v else 0 for v in m.group(4, 5, 6, 7))
                cur = {'name': m.group(1), 'primary': bool(m.group(3)), 'active': bool(m.group(4)),
                       'w': w, 'h': h, 'x': x, 'y': y, 'pref': None}
                outs.append(cur)
            continue
        mm = re.match(r'\s+(\d+)x(\d+)i?\s+(.*)$', line)
        if cur is not None and mm:
            wh = [int(mm.group(1)), int(mm.group(2))]
            if '+' in mm.group(3):
                cur['pref'] = wh
            cur.setdefault('first', wh)
    for o in outs:
        first = o.pop('first', None)
        o['pref'] = o['pref'] or first
    return outs


# TELAO VIRTUAL (src/telao_sim.py): enquanto aberto, o simulador anuncia saidas aqui —
# {"outputs": [{"name": "SIM-1", "w", "h", "label"}], "pid": N}. Native (get_monitors) e dash
# (detectar telao) leem junto com o xrandr; pid morto = arquivo velho, ignorado. A janela de saida
# "vai pra" x = largura da tela X (fora da area visivel; o WM deixa uma tira) e o simulador a
# captura pelo id (composite: pega a janela inteira mesmo fora da tela).
VIRTUAL_OUTPUTS = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir(), 'prisma-telao-virtual.json')


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def virtual_outputs(screen_w, path=None, alive=_pid_alive):
    """Saidas do telao virtual no formato do parse_xrandr (+ virtual=True), a direita da tela X
    (x = screen_w). [] sem simulador aberto."""
    try:
        with open(path or VIRTUAL_OUTPUTS, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(d, dict) or not alive(d.get('pid')):
        return []
    out = []
    for o in d.get('outputs') or []:
        try:
            w, h = int(o['w']), int(o['h'])
        except (KeyError, TypeError, ValueError):
            continue
        if w >= 16 and h >= 16:
            out.append({'name': str(o.get('name') or 'SIM-1'), 'primary': False, 'active': True, 'virtual': True,
                        'w': w, 'h': h, 'x': int(screen_w or 0), 'y': 0, 'pref': [w, h],
                        'label': str(o.get('label') or '')})
    return out


def xrandr_screen_w(text):
    """Largura atual da tela X ('Screen 0: ... current W x H') — onde o telao virtual comeca."""
    m = re.search(r'current (\d+) x (\d+)', text or '')
    return int(m.group(1)) if m else 0


def pick_led_output(outs):
    """Qual saida e' o telao: a 1a REAL que NAO e' a principal (sem principal marcada, a 1a depois
    da que tem a tela em 0,0); sem nenhuma, o telao VIRTUAL (simulador). None se so' ha' a do
    operador. Real ganha do virtual: simulador esquecido aberto nao rouba o show."""
    real, virt = [o for o in outs if not o.get('virtual')], [o for o in outs if o.get('virtual')]
    rest = [o for o in real if not o['primary']]
    if len(rest) == len(real):
        rest = [o for o in real if not (o['active'] and o['x'] == 0 and o['y'] == 0)] or real[1:]
    if len(real) < 2:
        rest = []
    return (rest + virt)[0] if rest + virt else None


# ---------- TELAS DO PALCO com forma livre (tuning.SCREENS[i].rot / .poly) ----------
# Uma tela = o PAINEL retangular (x, y, w, h em metros, origem em cima; pw x ph LEDs) GIRADO `rot`
# graus (horario, em volta do centro) e, opcional, recortado pelo poligono `poly` ([[u, v], ...]
# 0..1 no painel SEM giro, origem em cima): fora dele o painel fica apagado. Sem rot/poly = o
# retangulo de sempre. Mesma conta no native (_stage), no dash v2 (shapeAxes) e no telao_sim.
MAX_POLY = 32   # = largura da textura de poligonos do native (POLY_TEX_W)


def screen_poly(t):
    """`poly` valido da tela -> [(u, v), ...] (3..MAX_POLY pontos, 0..1) ou None (= o painel inteiro)."""
    try:
        pts = [(min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))) for p in t.get('poly') or ()]
    except (TypeError, ValueError, IndexError, AttributeError):
        return None
    return pts[:MAX_POLY] if len(pts) >= 3 else None


def screen_axes(t):
    """O painel em metros: (o, ex, ey) — o = canto (u, v) = (0, 0) dele, ex/ey = vetores de u e v
    de 0 a 1. Ponto do painel em metros = o + u*ex + v*ey (ja girado)."""
    x, y, w, h = (float(t[k]) for k in ('x', 'y', 'w', 'h'))
    a = math.radians(float(t.get('rot') or 0.0))
    c, s = math.cos(a), math.sin(a)
    ex, ey = (w * c, w * s), (-h * s, h * c)
    cx, cy = x + w / 2, y + h / 2
    return (cx - (ex[0] + ey[0]) / 2, cy - (ex[1] + ey[1]) / 2), ex, ey


def screen_pts(t):
    """Contorno da tela em metros (o poligono, ou os 4 cantos do painel), ja girado."""
    o, ex, ey = screen_axes(t)
    return [(o[0] + u * ex[0] + v * ey[0], o[1] + u * ex[1] + v * ey[1])
            for u, v in (screen_poly(t) or ((0, 0), (1, 0), (1, 1), (0, 1)))]


def screen_bbox(t):
    """Retangulo (x0, y0, x1, y1) em metros que envolve o contorno da tela."""
    p = screen_pts(t)
    return min(q[0] for q in p), min(q[1] for q in p), max(q[0] for q in p), max(q[1] for q in p)


def pack_raster(screens, rw, rh):
    """ox/oy de cada tela (pw x ph) no raster rw x rh, como a processadora reempacota: 1o canto livre
    (de cima pra baixo) em algumas ordens; fica a 1a que cabe inteira, senao a que deixa menos px de
    fora (essas vao pra baixo do raster). = pmPack do dash v2. Muda as telas; -> as que nao couberam."""
    def hit(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
    orders = [lambda t: (-t['ph'], -t['pw']), lambda t: (-t['pw'], -t['ph']),
              lambda t: -t['pw'] * t['ph'], lambda t: -max(t['pw'], t['ph'])]
    best = None
    for key in orders:
        placed, pos, out, bottom = [], {}, 0, 0
        for i, t in sorted(enumerate(screens), key=lambda it: key(it[1])):
            cand = sorted([(0, 0)] + [c for o in placed for c in ((o[0] + o[2], o[1]), (o[0], o[1] + o[3]), (0, o[1] + o[3]))],
                          key=lambda c: (c[1], c[0]))
            at = next((c for c in cand if c[0] + t['pw'] <= rw and c[1] + t['ph'] <= rh
                       and not any(hit((c[0], c[1], t['pw'], t['ph']), o) for o in placed)), None)
            if at is None:
                out += t['pw'] * t['ph']
                at = (0, max(rh, bottom))
            r = (at[0], at[1], t['pw'], t['ph'])
            placed.append(r)
            pos[i] = r
            bottom = max(bottom, r[1] + r[3])
        if best is None or out < best[0]:
            best = (out, pos)
        if not out:
            break
    for i, r in best[1].items():
        screens[i]['ox'], screens[i]['oy'] = r[0], r[1]
    return [t for t in screens if t['ox'] + t['pw'] > rw or t['oy'] + t['ph'] > rh]


def in_poly(pts, x, y):
    """Ponto dentro do poligono (par-impar)."""
    ins, j = False, len(pts) - 1
    for i in range(len(pts)):
        (xi, yi), (xj, yj) = pts[i], pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def vcam_cfg(d):
    """WEBCAM VIRTUAL (tuning.VCAM): {on, w (largura 320..1920), fps 10..60}. Sai SEMPRE 16:9 (w x h pares) com o
    palco encaixado e barras pretas — mudar o palco nao troca o formato da camera (com alguem lendo, trocar falha)."""
    d = d or {}
    w = int(max(320, min(1920, int(d.get('w', 1280)))) // 16 * 16)
    return {'on': int(bool(d.get('on', 0))), 'w': w, 'h': w * 9 // 16 // 2 * 2,
            'fps': int(max(10, min(60, int(d.get('fps', 30)))))}


# ---------------- GRAFO (dash v5, 2026-11-01: cabos como no VCV) ----------------
# OVERLAYS = os NOS: fonte (file = camera/video/imagem), atomo (file '@<id>' = le aquele no'; 1 atomo em BINDINGS[chave]),
# STAGING (kind 'mix') e SAIDA (kind 'out'). Staging e saida = mixer: layers = [{from: '@<id>', opacity, blend, off, mod,
# acao, rect}] (0 = atras; rect = lugar DENTRO dele, 0..1), atomos DEPOIS da mistura em BINDINGS['+<id>']; a saida tem
# rect no PALCO. Entrada aceita UM fio, saida varios. Laco (A -> B -> A) = o fio que fecha le o QUADRO ANTERIOR.
# ESPELHO = item da pilha {file, espelho: <id do original>, id}: knobs/movimento/liga do original, fio e estado do lugar.
NODE_KINDS = ('mix', 'out')
LAYER_PROPS = ('opacity', 'off', 'blend', 'mod', 'acao', 'rect')   # o que era da caixa NA SAIDA e virou da CAMADA
MIRROR_PROPS = ('fx', 'mod', 'opacity', 'off', 'kick', 'in', 'estado', 'region')   # do ORIGINAL; ins/post/id = do lugar


def node_key(o):
    """Chave do no' (= a de BINDINGS): staging/saida = '+<id>'; fonte/atomo = 'file' ('file#N' se repetido)."""
    if o.get('kind') in NODE_KINDS:
        return '+' + str(o.get('id') or '')
    d = o.get('dup')
    return f"{o.get('file', '')}#{d}" if d else o.get('file', '')


def stable_id(key):
    """Id deterministico de uma chave (FNV-1a 32 bits em base 36): a mesma cena antiga migra sempre igual
    (o dash5 faz a mesma conta em stableId)."""
    h = 2166136261
    for ch in str(key).encode('utf-8'):
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    s, d = '', '0123456789abcdefghijklmnopqrstuvwxyz'
    while True:
        h, r = divmod(h, 36)
        s = d[r] + s
        if not h:
            return 'k' + s


def migrate_graph(overlays):
    """Cena SEM saida (todas antes de 2026-11-01) -> a mesma imagem no grafo novo: cada caixa NO AR vira uma camada
    da 'saida 1' (palco inteiro), na mesma ordem, levando o que era dela na SAIDA (LAYER_PROPS). v5 (caixas com xy):
    'off' = meio de corrente, nao entra. v3/v4: 'off' = mudo no programa, entra desligada (menos quem outra fileira le).
    Ja' tem saida = devolve a MESMA lista (o native guarda pela identidade)."""
    if any(o.get('kind') == 'out' for o in overlays or ()):
        return overlays
    rows = [dict(o) for o in overlays or () if o.get('kind') not in NODE_KINDS]
    v5 = any('xy' in o for o in rows)
    used = {o['id'] for o in rows if o.get('id')}
    for o in rows:
        if not o.get('id'):
            i, base = 1, stable_id(node_key(o))
            o['id'] = base
            while o['id'] in used:
                i += 1
                o['id'] = f'{base}{i}'
            used.add(o['id'])
    read = {str(o['file'])[1:] for o in rows if str(o.get('file') or '').startswith('@')}
    layers = []
    for o in rows:
        lay = {'from': '@' + o['id']}
        for p in LAYER_PROPS:
            if p in o:
                lay[p] = o.pop(p)
        if lay.get('off') and (v5 or o['id'] in read):
            continue
        if (lay.get('opacity') if 'opacity' in lay else 1.0) == 1.0:
            lay.pop('opacity', None)
        layers.append(lay)
    oid = 'o1' if 'o1' not in used else stable_id('saida' + ''.join(sorted(used)))
    return rows + [{'kind': 'out', 'id': oid, 'n': 1, 'nome': 'saída 1', 'layers': layers}]


def _stack_items(b):
    return list((b or {}).get('shaders') or []) + list(((b or {}).get('matte') or {}).get('items') or [])


def graph_index(overlays, bindings):
    """id -> chave do no' que o tem: id da fileira (o FIM, depois da mascara), id de staging/saida e id de cada atomo
    (pilha e mascara; ramo do meio da v4)."""
    ix = {}
    for o in overlays or ():
        if o.get('id'):
            ix[o['id']] = node_key(o)
    for o in overlays or ():
        for it in _stack_items((bindings or {}).get(node_key(o))):
            if it.get('id'):
                ix.setdefault(it['id'], node_key(o))
    return ix


def node_refs(o, b, active=False):
    """'@<id>' que o no' le: fileira = a entrada (file) + entrada B de cada atomo + Luma da mascara; staging/saida = as
    camadas. active=True = so' o que conta pra RODAR (atomo/camada desligada ou camada a 0% nao puxa)."""
    out = []
    if o.get('kind') in NODE_KINDS:
        for L in o.get('layers') or ():
            if active and (L.get('off') or float(L.get('opacity', 1.0) or 0) <= 0):
                continue
            if str(L.get('from') or '').startswith('@'):
                out.append(L['from'])
    elif str(o.get('file') or '').startswith('@'):
        out.append(o['file'])
    for it in _stack_items(b):
        if active and it.get('off'):
            continue
        out += [r for r in it.get('ins') or () if str(r).startswith('@')]
    return out


def graph_order(overlays, bindings):
    """Ordem de render (cada no' DEPOIS de quem ele le) -> (chaves, late): late = {(quem, id lido)} = fios que fecham um
    LACO; esses leem o quadro anterior (como o LocalIn/LocalOut). Ordem estavel: a do OVERLAYS onde nao ha dependencia."""
    ix = graph_index(overlays, bindings)
    deps = {}
    for o in overlays or ():
        k = node_key(o)
        deps[k] = [(ix[r[1:]], r[1:]) for r in node_refs(o, (bindings or {}).get(k)) if ix.get(r[1:]) not in (None, k)]
    seen, out, late = {}, [], set()

    def visit(k):
        seen[k] = 1
        for d, rid in deps.get(k, ()):
            if seen.get(d) == 1:
                late.add((k, rid))
            elif not seen.get(d):
                visit(d)
        seen[k] = 2
        out.append(k)
    for o in overlays or ():
        if not seen.get(node_key(o)):
            visit(node_key(o))
    return out, late


def graph_pull(overlays, bindings, extra=()):
    """Chaves dos nos que precisam RODAR: tudo que chega numa SAIDA (camada ligada) + os ids em `extra` (sinal no:<id>)."""
    ix = graph_index(overlays, bindings)
    by = {node_key(o): o for o in overlays or ()}
    todo = [node_key(o) for o in overlays or () if o.get('kind') == 'out'] + [ix[i] for i in extra if i in ix]
    need = set()
    while todo:
        k = todo.pop()
        if k in need or k not in by:
            continue
        need.add(k)
        todo += [ix[r[1:]] for r in node_refs(by[k], (bindings or {}).get(k), active=True) if r[1:] in ix]
    return need


def resolve_mirrors(bindings):
    """ESPELHOS -> itens de verdade pro motor: knobs, movimento, opacidade, liga/desliga (MIRROR_PROPS) do ORIGINAL;
    fio (ins, post), id (estado = um buffer por LUGAR) e chave da cena do lugar; '_seed' = id do original (o mesmo
    acaso). Original sumido = o espelho roda com o que tem. Sem espelho = devolve o MESMO dict."""
    if not any(it.get('espelho') for b in (bindings or {}).values() for it in (b or {}).get('shaders') or ()):
        return bindings
    orig = {}
    for b in bindings.values():
        for it in _stack_items(b):
            if it.get('id') and not it.get('espelho'):
                fx = it['fx'] if isinstance(it.get('fx'), dict) else ((b.get('fx') or {}).get(it.get('file')) or {})
                orig[it['id']] = dict(it, fx=fx)
    out = {}
    for k, b in bindings.items():
        st = (b or {}).get('shaders') or []
        if not any(it.get('espelho') for it in st):
            out[k] = b
            continue
        new = []
        for it in st:
            o = orig.get(it.get('espelho')) if it.get('espelho') else None
            if o and o.get('file') == it.get('file'):
                it = dict({p: it[p] for p in ('file', 'id', 'ins', 'post', 'espelho') if p in it},
                          **{p: o[p] for p in MIRROR_PROPS if p in o}, _seed=o['id'])
            new.append(it)
        out[k] = dict(b, shaders=new)
    return out


if __name__ == '__main__':  # self-check (roda: python dash_data.py)
    # GRAFO: a cena antiga vira saida 1 com as caixas no ar, na mesma ordem; ja' migrada = a mesma lista
    v5 = [{'file': 'webcam:/dev/video0', 'id': 'c1', 'xy': [0, 0], 'off': 1}, {'file': '@c1', 'id': 'c2', 'xy': [9, 0], 'opacity': 0.5,
          'blend': 'soma', 'rect': [0, 0, 0.5, 0.5]}, {'file': 'a.png', 'xy': [0, 99], 'mod': {'opacity': {'b': ['kick']}}}]
    g = migrate_graph(v5)
    assert [o.get('kind') for o in g] == [None, None, None, 'out'] and g[2]['id'] == stable_id('a.png') == migrate_graph(v5)[2]['id']
    assert g[3]['layers'] == [{'from': '@c2', 'opacity': 0.5, 'blend': 'soma', 'rect': [0, 0, 0.5, 0.5]},
                              {'from': '@' + g[2]['id'], 'mod': {'opacity': {'b': ['kick']}}}], g[3]
    assert 'off' not in g[0] and 'opacity' not in g[1] and migrate_graph(g) is g and v5[1]['opacity'] == 0.5, 'migra sem mexer no original'
    v4 = migrate_graph([{'file': 'a.png', 'id': 'r1', 'off': 1}, {'file': '@r1', 'id': 'r2'}, {'file': 'b.png', 'id': 'r3', 'off': 1}])
    assert v4[3]['layers'] == [{'from': '@r2'}, {'from': '@r3', 'off': 1}], 'v4: mudo continua na saida (desligado); lido por outra nao'
    assert migrate_graph([])[0]['layers'] == [] and stable_id('x') == stable_id('x') != stable_id('y')
    gb = {'@c1': {'shaders': [{'file': 'A.frag', 'id': 'a1', 'ins': ['@c9']}]}, '+m1': {'shaders': []}}
    gg = [{'file': 'v.mp4', 'id': 'c1'}, {'kind': 'out', 'id': 'o1', 'layers': [{'from': '@m1'}]},
          {'kind': 'mix', 'id': 'm1', 'layers': [{'from': '@a1'}, {'from': '@c9', 'off': 1}]}, {'file': '@c1', 'id': 'c3'}, {'file': 'w.png', 'id': 'c9'}]
    order, late = graph_order(gg, gb)
    assert order.index('v.mp4') < order.index('@c1') < order.index('+m1') < order.index('+o1') and order.index('w.png') < order.index('@c1'), order
    assert late == set() and graph_index(gg, gb)['a1'] == '@c1'
    assert graph_pull(gg, gb) == {'+o1', '+m1', '@c1', 'v.mp4', 'w.png'}, 'puxa so\' o que chega numa saida (w.png = entrada B)'
    assert graph_pull(gg, gb, extra=('c3',)) >= {'@c1'} and 'w.png' in graph_pull(gg, gb)
    loop = [{'kind': 'mix', 'id': 'm1', 'layers': [{'from': '@m2'}]}, {'kind': 'mix', 'id': 'm2', 'layers': [{'from': '@m1'}]}]
    o2, l2 = graph_order(loop, {})
    assert len(o2) == 2 and len(l2) == 1, 'laco: um fio le o quadro anterior'
    mb = {'a': {'shaders': [{'file': 'M.frag', 'id': 'h1', 'fx': {'matiz': 0.7}, 'mod': {'matiz': {'b': ['lfo']}}}]},
          '+m1': {'shaders': [{'file': 'M.frag', 'id': 'h2', 'espelho': 'h1', 'fx': {'matiz': 0.1}, 'ins': ['@x']}]}}
    rm = resolve_mirrors(mb)
    assert rm['+m1']['shaders'][0] == {'file': 'M.frag', 'id': 'h2', 'ins': ['@x'], 'espelho': 'h1', 'fx': {'matiz': 0.7},
                                       'mod': {'matiz': {'b': ['lfo']}}, '_seed': 'h1'}, rm
    assert rm['a'] is mb['a'] and resolve_mirrors(gb) is gb, 'sem espelho = o mesmo dict'

    assert vcam_cfg(None) == {'on': 0, 'w': 1280, 'h': 720, 'fps': 30}
    assert vcam_cfg({'on': True, 'w': 99999, 'fps': 1}) == {'on': 1, 'w': 1920, 'h': 1080, 'fps': 10}
    assert parse_fx_manifest('// fx: wave, grain ,vignette\nfoo bar') == ['wave', 'grain', 'vignette']
    assert parse_fx_manifest('//fx:wave') == ['wave']
    assert parse_fx_manifest('nada aqui') == [] and parse_fx_manifest('') == []
    assert parse_fx_manifest('// fx: a=0.5, b') == ['a', 'b']
    assert parse_fx_defaults('// fx: a=0.5, b, c=2, d=x') == {'a': 0.5, 'b': 1.0, 'c': 1.0, 'd': 1.0}
    assert parse_meta('// fx: a\n// cat: tempo\n// in: fb, src, x\n// ATOMOS · Feedback. Rastro. Mais.\n') == \
        {'cat': 'tempo', 'ins': ['fb', 'src'], 'desc': 'Rastro. Mais.', 'nome': 'Feedback'}
    assert parse_meta('// fx: a\n// so texto\n') == {'cat': '', 'ins': [], 'desc': 'so texto'}
    near = lambda a, b: abs(a - b) < 1e-9
    assert near(lfo({'f': 'sin', 'r': 4}, 0), 0) and near(lfo({'f': 'sin', 'r': 4}, 2), 1) and near(lfo({'r': 4}, 4), 0), 'sin: 0 no 1, cheio no meio'
    assert near(lfo({'f': 'tri', 'r': 2}, 1), 1) and near(lfo({'f': 'saw', 'r': 4}, 1), 0.25), 'tri e serra'
    assert lfo({'f': 'sq', 'r': 4}, 1) == 1.0 and lfo({'f': 'sq', 'r': 4}, 3) == 0.0, 'quadrada: metade ligada'
    assert near(lfo({'f': 'saw', 'r': 4, 'ph': 0.5}, 0), 0.5), 'fase desloca o ciclo'
    rs = [lfo({'f': 'rnd', 'r': 1}, k / 8) for k in range(64)]
    assert all(0 <= v <= 1 for v in rs) and max(rs) - min(rs) > 0.2 and max(abs(a - b) for a, b in zip(rs, rs[1:])) < 0.5, 'acaso: 0..1, suave'
    assert near(lfo({'f': 'rnd', 'r': 2}, 6), lfo({'f': 'rnd', 'r': 2}, 6.0)) and lfo(None, 1) == lfo({'f': 'sin', 'r': 4}, 1), 'deterministico; padrao = seno de 4 batidas'

    assert lfo({'f': 'sh', 'r': 1}, 2.1) == lfo({'f': 'sh', 'r': 1}, 2.9) != lfo({'f': 'sh', 'r': 1}, 3.1), 'acaso segurado: um valor por ciclo'
    assert lfo({'f': 'passos', 'r': 4, 'st': [1, 0, 0.5, 0]}, 0.1) == 1 and lfo({'f': 'passos', 'r': 4, 'st': [1, 0, 0.5, 0]}, 2.5) == 0.5, 'passos'
    assert env(0, 1, -0.1) == 0 and env(0, 1, 0) == 1 and near(env(0, 1, 0.5), 0.25) and env(0, 1, 1) == 0, 'envelope: soco e cauda'
    assert near(env(1, 1, 0.5), 0.5) and env(1, 1, 1) == 1, 'ataque linear'
    assert [k for k in range(1, 9) if ev_ok({'n': 2}, k)] == [1, 3, 5, 7] and [k for k in range(1, 9) if ev_ok({'a': 2, 'b': 4}, k)] == [2, 6]
    assert [k for k in range(1, 4) if ev_ok({'first': 1}, k)] == [1] and ev_ok(None, 5)
    ps = [ev_ok({'p': 0.5}, k) for k in range(200)]; assert 60 < sum(ps) < 140 and ps == [ev_ok({'p': 0.5}, k) for k in range(200)], 'probabilidade deterministica'
    cp = np.zeros((33, 3), np.float32); cp[15] = (0.2, 0.3, 1); cp[16] = (0.8, 0.9, 1); cp[23] = (0.4, 0.6, 1); cp[24] = (0.6, 0.6, 1)
    ts = track_signals('corpo', {'u_corpo': cp.ravel(), 'on': 1.0})
    assert all(abs(ts[k] - v) < 1e-6 for k, v in {'mao.y': 0.7, 'mao.x': 0.2, 'corpo.x': 0.5, 'corpo.abre': 0.9}.items()), ts
    assert track_signals('corpo', {'u_corpo': cp.ravel(), 'on': 0.0})['mao.y'] == 0, 'perdeu = some'
    assert abs(track_signals('rosto', {'u_rosto': np.array([0.5, 0.25, 0.2, 0.3] * 4), 'on': 1})['rosto.y'] - 0.75) < 1e-6
    assert set(TRACK_KIND) == {x.split('.')[0] for x in TRACK_SIGNALS + TRACK_GATES}
    assert parse_meta('// fx: a\n// cat: cor\n// mod: a=pulsa, b = respira\n// ATOMOS · X. y\n')['mod'] == {'a': 'pulsa', 'b': 'respira'}
    assert parse_meta('// fx: a\n// cat: cor\n// mod: a=pulsa\n// ATOMOS · X. y\n')['desc'] == 'y', '// mod: nao vira descricao'

    freqs = np.fft.rfftfreq(1024, d=1 / 44100)
    spec = np.full(len(freqs), 0.01)
    spec[5:15] = 1.0  # pico no grave
    bands_raw = [(n, 0.3, 0.3, 0.2, 0.7) for n in FREQ_BAND_RGB]  # 8, grave->agudo
    d = audio_dash_data(bands_raw, 0.25, 0.8, 0.6, 0.9, 0.5, 0.83, spec, freqs)
    assert d['kick'] == {'final': 0.5, 'decay': 0.83}, d['kick']
    names = [b['name'] for b in d['bands']]
    assert names[0] == 'amp' and names[-1] == 'Sub-bass', names
    assert len(d['bands']) == 9 and len(d['spectrum']) == 24
    assert d['bands'][0]['delta'] == round(abs(0.6 - 0.8), 4), d['bands'][0]
    assert tuple(d['bands'][-1]['rgb']) == (30, 140, 255)
    assert max(s['rel'] for s in d['spectrum']) == 1.0  # faixa mais forte sempre 100%
    assert all(0.0 <= s['rel'] <= 1.0 for s in d['spectrum'])
    # cinza quando o Hz cai num buraco entre faixas (modo crossover)
    assert _band_rgb_for_hz(300, [(20, 200), (400, 600)] + [(0, 0)] * 6) == _GREY
    assert _band_rgb_for_hz(100, [(20, 200), (400, 600)] + [(0, 0)] * 6) == (30, 140, 255)
    xr = ('Screen 0: minimum 8 x 8, current 3286 x 1080\n'
          'HDMI-0 connected primary 1366x768+0+0 (normal left) 434mm x 236mm\n'
          '   1366x768      59.79*+\n   1280x720      60.00\n'
          'DP-0 disconnected (normal left inverted right x axis y axis)\n'
          'HDMI-1 connected (normal left inverted right x axis y axis)\n'
          '   3840x2160     30.00 +  60.00\n   1920x1080     60.00\n'
          'DP-2 connected 1920x1080+1366+0 (normal left) 0mm x 0mm\n'
          '   2560x1440     60.00\n   1920x1080     60.00*+\n')
    o = parse_xrandr(xr)
    assert [x['name'] for x in o] == ['HDMI-0', 'HDMI-1', 'DP-2'], o
    assert o[0]['primary'] and o[0]['active'] and (o[0]['w'], o[0]['h']) == (1366, 768)
    assert not o[1]['active'] and o[1]['pref'] == [3840, 2160], o[1]
    assert o[2]['active'] and o[2]['x'] == 1366 and o[2]['pref'] == [1920, 1080], o[2]
    assert pick_led_output(o)['name'] == 'HDMI-1' and pick_led_output(o[:1]) is None
    np_ = [dict(x, primary=False) for x in o]
    assert pick_led_output(np_)['name'] == 'HDMI-1'
    v = [{'name': 'SIM-1', 'primary': False, 'active': True, 'virtual': True, 'w': 3840, 'h': 1080, 'x': 1366, 'y': 0}]
    assert pick_led_output(o[:1] + v)['name'] == 'SIM-1'          # so' a principal + simulador
    assert pick_led_output(o + v)['name'] == 'HDMI-1'             # real ganha
    assert xrandr_screen_w(xr) == 3286
    vp = os.path.join(tempfile.gettempdir(), 'prisma-vo-test.json')
    json.dump({'pid': 1, 'outputs': [{'name': 'SIM-1', 'w': 3840, 'h': 2160, 'label': '4K'}, {'w': 'x'}]}, open(vp, 'w', encoding='utf-8'))
    vo = virtual_outputs(1366, vp, alive=lambda p: True)
    assert len(vo) == 1 and vo[0]['x'] == 1366 and vo[0]['pref'] == [3840, 2160] and vo[0]['virtual'], vo
    assert virtual_outputs(1366, vp, alive=lambda p: False) == []
    os.remove(vp); assert virtual_outputs(1366, vp) == []
    # telas com forma livre: giro em volta do centro, poligono no painel sem giro
    sq = {'x': 0, 'y': 0, 'w': 2, 'h': 1}
    assert [tuple(round(c, 6) for c in p) for p in screen_pts(sq)] == [(0, 0), (2, 0), (2, 1), (0, 1)]
    r = [tuple(round(c, 6) + 0.0 for c in p) for p in screen_pts(dict(sq, rot=90))]
    assert r == [(1.5, -0.5), (1.5, 1.5), (0.5, 1.5), (0.5, -0.5)], r     # em pe', mesmo centro
    assert [round(c, 6) for c in screen_bbox(dict(sq, rot=90))] == [0.5, -0.5, 1.5, 1.5]
    tri = dict(sq, poly=[[0, 1], [0.5, 0], [1, 1]])
    assert screen_bbox(tri) == (0, 0, 2, 1) and in_poly(screen_pts(tri), 1, 0.6) and not in_poly(screen_pts(tri), 0.2, 0.2)
    assert screen_poly({'poly': [[0, 0], [1, 1]]}) is None and screen_poly({'poly': [[0, 0], [2, 'x']]}) is None
    assert screen_poly({'poly': [[-1, 0], [1, 0], [1, 5]]}) == [(0, 0), (1, 0), (1, 1)]
    pk = [{'pw': 256, 'ph': 1024}, {'pw': 1024, 'ph': 256}, {'pw': 256, 'ph': 1024}]
    assert pack_raster(pk, 1920, 1080) == [] and [(t['ox'], t['oy']) for t in pk] == [(0, 0), (512, 0), (256, 0)], pk
    assert [t['pw'] for t in pack_raster([{'pw': 2000, 'ph': 10}, {'pw': 10, 'ph': 10}], 1920, 1080)] == [2000]
    assert img_mod_levels({'grids': [{'name': 'BRILHO', 'total': 0.4}, {'name': 'MOVIMENTO', 'total': 1.3}]}) == {'luz': 0.4, 'mov': 1.0}
    assert img_mod_levels(None) == {'luz': 0.0, 'mov': 0.0}
    ok = '// fx: forca=0.5\n// cat: cor\n// ATOMOS · T. x\nuniform float u_fx_forca;\nvoid main(){ gl_FragColor = vec4(u_fx_forca) * A(uv()); }\n'
    assert atom_problems(ok) == [], atom_problems(ok)
    bad = '// fx: layer, z\n// cat: luzes\nuniform float u_bass, u_fx_layer;\nvoid main(){ gl_FragColor = vec4(u_bass * u_fx_layer) * B(uv()); }\n'
    pr = ' | '.join(atom_problems(bad))
    assert any('no maximo' in x for x in atom_problems('// fx: a, b, c, d\n' + ok))
    for frag in ("cat: 'luzes'", 'ATOMOS', 'u_bass', 'knob proibido layer', 'knob z', 'sem "// in:"'):
        assert frag in pr, (frag, pr)
    mk = '// cat: mascara\n// ATOMOS · M. x\nuniform sampler2D u_subject;\nuniform float u_subject_on;\nvoid main(){ gl_FragColor = vec4(u_subject_on); }\n'
    assert atom_problems(mk) == [], atom_problems(mk)
    assert any("'pula' nao" in x for x in atom_problems(ok.replace('// cat: cor', '// cat: cor\n// mod: forca=pula')))
    assert any('knob zz' in x for x in atom_problems(ok.replace('// cat: cor', '// cat: cor\n// mod: zz=pulsa')))
    assert atom_problems(ok.replace('// cat: cor', '// cat: cor\n// mod: forca=pulsa')) == []
    assert any('so\' em atomo de mascara' in x for x in atom_problems(mk.replace('mascara', 'cor', 1)))
    assert atom_problems(mk.replace('M. x', 'M. x\n// in: src').replace('vec4(u_subject_on)', 'B(uv())')) == [], 'mascara le B (Luma)'
    # ATOMO v2: preludio nao se declara; estado pede u_vista e nao usa u_time; bipolar/ritmo so' em knob que existe
    assert any('vem do preludio' in x for x in atom_problems(ok.replace('uniform float', 'uniform vec2 u_resolution;\nuniform float')))
    assert any('#ifdef' in x for x in atom_problems('#ifdef GL_ES\nprecision mediump float;\n#endif\n' + ok))
    st_ = ok.replace('// cat: cor', '// cat: tempo\n// estado: canais=2, passos=4\n// bipolar: forca').replace('A(uv())', 'E(uv()) * u_vista')
    assert atom_problems(st_) == [], atom_problems(st_)
    assert parse_meta(st_)['estado'] == {'canais': 2, 'passos': 4, 'fases': 1, 'escala': 0.5} and parse_meta(st_)['bipolar'] == ['forca']
    assert any('u_vista' in x for x in atom_problems(st_.replace('* u_vista', '')))
    assert any('u_time' in x for x in atom_problems(st_.replace('* u_vista', '* u_vista * u_time')))
    assert any('sem "// estado:"' in x for x in atom_problems(ok.replace('A(uv())', 'E(uv())')))
    assert any('bipolar: knob zz' in x for x in atom_problems(ok.replace('// cat: cor', '// cat: cor\n// bipolar: zz')))
    assert atom_source('presets/atomos/X.frag', 'y').startswith(ATOM_PRELUDE) and atom_source('presets/sortidos/X.frag', 'y') == 'y'
    assert parse_estado('// estado: canais=9, passos=x, escala=0.25') == {'canais': 4, 'passos': 1, 'fases': 1, 'escala': 0.25}
    sw = '// fx: limiar=0.5, inverter=0\nuniform float u_fx_limiar, u_fx_inverter;\nvoid main(){ float m = step(u_fx_limiar, 0.3); m = mix(m, 1.0 - m, step(0.5, u_fx_inverter)); }'
    assert knob_switches(sw) == ['inverter'] and parse_meta(sw)['chave'] == ['inverter'], 'chave = so\' step(0.5, ...)'
    assert knob_switches(sw.replace('step(0.5, u_fx_inverter)', 'u_fx_inverter')) == [], 'valor continuo = knob'
    assert knob_switches(sw.replace('step(0.5,', 'step(.5,')) == ['inverter'], 'step(.5, ...) tambem'
    es = '// fx: modo=0\n// opcoes: modo=a|b|c\nuniform float u_fx_modo;\nvoid main(){ float m = floor(u_fx_modo * 2.999); }'
    assert knob_choices(es) == {'modo': ['a', 'b', 'c']} and parse_meta(es)['escolha'] == {'modo': ['a', 'b', 'c']}
    assert knob_choices(es.replace('// opcoes: modo=a|b|c\n', '')) == {'modo': ['1', '2', '3']}, 'sem nomes = numeros'
    assert all(int((i + 0.5) / 3 * 2.999) == i for i in range(3)), 'valor da opcao cai no meio da fatia'
    assert any('so\' em atomo de mascara' in x for x in atom_problems(ok.replace('u_fx_forca;', 'u_fx_forca;\nuniform vec4 u_rosto[4];')))
    for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shaders', 'presets', 'atomos', '*.frag'))):
        assert not atom_problems(open(f, encoding='utf-8').read()), (os.path.basename(f), atom_problems(open(f, encoding='utf-8').read()))
    print('dash_data self-check ok')
