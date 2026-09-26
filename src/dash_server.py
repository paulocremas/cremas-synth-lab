"""Servidor do dashboard HTML — substitui (em paralelo) os dashes de terminal por uma
pagina interativa. Stdlib pura: http.server + SSE, sem dependencia nova.

Duas direcoes:
  - numeros SAINDO  : GET /events  -> stream text/event-stream com o `state` do synth
  - knobs ENTRANDO  : POST /knob   -> reescreve a linha em tuning.py; o hot-reload por
                      mtime do audio_thread aplica em <=1 chunk (~23ms), sem code path novo

O write-back e literalmente "editar tuning.py como o Paulo edita, so que por slider" — por
isso a posicao do knob persiste entre execucoes de graca. MIDI/potenciometro fisico depois
e so mais um chamador de set_knob().
"""
import atexit
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dash_data  # parse_fx_manifest (mesma pasta src/)

_HERE = os.path.dirname(os.path.abspath(__file__))          # src/
_ROOT = os.path.dirname(_HERE)                              # raiz do repo
_HTML = os.path.join(_ROOT, 'dash.html')
_HTML2 = os.path.join(_ROOT, 'dash2.html')                   # v2 (ao vivo), servido em /v2
_FAVICON = os.path.join(_ROOT, 'favicon.png')  # copia do de paulocremas.github.io
_SHADERS = os.path.join(_ROOT, 'shaders')                   # image.frag + presets/*.frag
_MEDIA = os.path.join(_ROOT, 'media')                       # galeria da aba Visuais (imgs/videos)
_TRANS = os.path.join(_ROOT, 'transitions')                 # galeria "Transições": *.glsl
_DEFAULT_TUNING = os.path.join(_HERE, 'tuning.py')

# knobs "ao vivo" — os fixos que controlam a DINAMICA (ver explicacao no README/CLAUDE.md).
# min/max = trilho do slider e clamp do POST; step so afeta o slider. group = secao na UI.
# popup: knob que sai da lista "Knobs" geral e vai pro popup "engrenagem" daquele alvo
# (kick / amp). Sem popup = fica na lista geral (globais + escalas).
KNOBS = [
    {"name": "KICK_THRESHOLD",      "min": 1.0,  "max": 3.0,    "step": 0.05,   "group": "kick", "popup": "kick", "label": "threshold (x baseline)"},
    {"name": "KICK_DECAY",          "min": 0.5,  "max": 0.99,   "step": 0.01,   "group": "kick", "popup": "kick", "label": "decay fixo (antes da 1a batida)"},
    {"name": "KICK_WARMUP_CHUNKS",  "min": 0,    "max": 80,     "step": 1,      "group": "kick", "popup": "kick", "label": "aquecimento (chunks mudos no boot)", "int": True},
    {"name": "KICK_FADE_FLOOR",     "min": 0.01, "max": 0.3,    "step": 0.01,   "group": "kick", "popup": "kick", "label": "'apagado' abaixo de"},
    {"name": "KICK_DECAY_FRACTION", "min": 0.3,  "max": 1.0,    "step": 0.05,   "group": "kick", "popup": "kick", "label": "pulso / intervalo"},
    {"name": "KICK_DECAY_MIN",      "min": 0.3,  "max": 0.9,    "step": 0.01,   "group": "kick", "popup": "kick", "label": "decay min (rapido)"},
    {"name": "KICK_DECAY_MAX",      "min": 0.8,  "max": 0.99,   "step": 0.01,   "group": "kick", "popup": "kick", "label": "decay max (lento)"},
    {"name": "AMP_SCALE",           "min": 0.5,  "max": 20.0,   "step": 0.5,    "group": "amp",  "popup": "amp",  "label": "ganho (RMS x isto, teto 1.0)"},
    {"name": "AMP_SMOOTHING",       "min": 0.5,  "max": 0.99,   "step": 0.01,   "group": "amp",  "popup": "amp",  "label": "release (perto de 1 = lento)"},
    {"name": "AMP_ATTACK_RATIO",    "min": 0.05, "max": 1.0,    "step": 0.05,   "group": "amp",  "popup": "amp",  "label": "attack / release (1 = sem soco)"},
    {"name": "ATTACK_RATIO",        "min": 0.05, "max": 1.0,    "step": 0.05,   "group": "smooth",   "label": "attack / release global (bass/mid/treble)"},
    {"name": "SMOOTHING",           "min": 0.5,  "max": 0.99,   "step": 0.01,   "group": "smooth",   "label": "release global (bass/mid/treble + espectro)"},
    {"name": "PEAK_DECAY",          "min": 0.99, "max": 0.9999, "step": 0.0001, "group": "autogain", "label": "memoria do teto (auto-gain da imagem)"},
    {"name": "BASS_SCALE",          "min": 0.01, "max": 1.0,    "step": 0.01,   "group": "scale",    "label": "bass x"},
    {"name": "MID_SCALE",           "min": 0.5,  "max": 20.0,   "step": 0.5,    "group": "scale",    "label": "mid x"},
    {"name": "TREBLE_SCALE",        "min": 1.0,  "max": 80.0,   "step": 1.0,    "group": "scale",    "label": "treble x"},
    {"name": "BASS_MID_HZ",         "min": 50,   "max": 500,    "step": 10,     "group": "scale",    "label": "corte bass|mid (Hz)",    "int": True},
    {"name": "MID_TREBLE_HZ",       "min": 1000, "max": 8000,   "step": 100,    "group": "scale",    "label": "corte mid|treble (Hz)",  "int": True},
]
_SPEC = {k["name"]: k for k in KNOBS}

# range de mixagem das 8 faixas finas — editado pela secao "Ranges das faixas" do dash (nao e
# um knob-slider comum, e um endpoint proprio /bands que reescreve o bloco FREQ_BAND_HZ inteiro).
_BAND_NAMES = ['Sub-bass', 'Low-mid', 'Midrange', 'High-mid', 'Presence', 'Treble', 'Brilliance', 'Air']
_HZ_MIN, _HZ_MAX = 20, 20000
_MAX_CHAN = 8  # teto (nao tamanho fixo) — tuning.CHANNELS e lista livre, add/remove no dash
_knob_lock = threading.Lock()  # serializa read-modify-write do tuning.py (set_knob + set_band_ranges)

_state = {}
_tuning = None
_cfg = {'is_running': lambda: True, 'audio_source': '', 'video_mode': '', 'tuning_path': _DEFAULT_TUNING,
        'on_inputs': None, 'on_set_input': None, 'on_set_output': None}  # callbacks (native_synth)


def _write_atomic(path, text):
    """Grava o tuning.py de uma vez (temporario + os.replace): o native recarrega o arquivo pelo
    mtime a qualquer momento, e com open('w') ele podia ler o arquivo truncado pela metade."""
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def set_knob(name, value, tuning_path=None):
    """Reescreve `NAME = <numero>` em tuning.py preservando o comentario da linha. Devolve o
    valor efetivamente gravado (ja clampado ao [min,max] do spec). Levanta KeyError se o nome
    nao for um knob conhecido ou nao existir no arquivo."""
    spec = _SPEC.get(name)
    if spec is None:
        raise KeyError(name)
    value = max(spec['min'], min(spec['max'], float(value)))
    literal = str(int(round(value))) if spec.get('int') else str(round(value, 4))
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        new, n = re.subn(rf'(?m)^({re.escape(name)} = )[-\d.eE+]+', rf'\g<1>{literal}', src)
        if n != 1:
            raise KeyError(f'{name}: {n} ocorrencias em {path} (esperava 1)')
        _write_atomic(path, new)
    if _tuning is not None:   # na hora: o reload do native pode demorar (loop de audio parado)
        setattr(_tuning, name, int(round(value)) if spec.get('int') else round(value, 4))
    return value


def _clamp_ranges(overlap, ranges):
    """8 pares [lo, hi] -> versao consistente. Sempre: int, dentro de [20, 20000], lo < hi.
    overlap=1: cada faixa independente (podem se sobrepor). overlap=0 (crossover): SEM
    sobreposicao, na ordem do ESPECTRO (por lo) e nao do indice — o dash troca faixas de lugar
    (Treble no grave, Sub-bass no agudo). BURACOS sao permitidos (lo de uma > hi da anterior
    -> essas frequencias nao entram em nenhuma faixa)."""
    r = [[int(round(float(lo))), int(round(float(hi)))] for lo, hi in ranges[:8]]
    r = [[max(_HZ_MIN, min(_HZ_MAX, lo)), max(_HZ_MIN, min(_HZ_MAX, hi))] for lo, hi in r]
    if overlap:
        return [[lo, max(lo + 1, min(_HZ_MAX, hi))] for lo, hi in r]
    out, prev_hi = [None] * len(r), _HZ_MIN
    for k in sorted(range(len(r)), key=lambda k: (r[k][0], k)):   # grave -> agudo, empate = indice
        lo, hi = r[k]
        lo = max(lo, prev_hi)               # nao invade a faixa anterior no espectro (buraco ok)
        hi = min(max(hi, lo + 1), _HZ_MAX)  # lo < hi, dentro do teto
        lo = min(lo, hi - 1)
        out[k] = [lo, hi]
        prev_hi = hi
    return out


def set_band_ranges(overlap, ranges, tuning_path=None, enabled=None):
    """Reescreve HZ_OVERLAP e o bloco FREQ_BAND_HZ inteiro em tuning.py; se `enabled` nao for
    None, tambem reescreve BANDS_ENABLED (checkbox "ativar" no dash — 0 silencia u_subbass..
    u_air no shader, sem apagar as ranges). Devolve {'overlap','ranges','enabled'} ja normalizado."""
    overlap = 1 if overlap else 0
    ranges = _clamp_ranges(overlap, ranges)
    body = '\n'.join(f'    [{lo}, {hi}],  # {name}' for (lo, hi), name in zip(ranges, _BAND_NAMES))
    block = f'FREQ_BAND_HZ = [\n{body}\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n1 = re.subn(r'(?m)^HZ_OVERLAP = [01]', f'HZ_OVERLAP = {overlap}', src)
        src, n2 = re.subn(r'(?ms)^FREQ_BAND_HZ = \[.*?^\]', block, src)
        if n1 != 1 or n2 != 1:
            raise KeyError(f'tuning.py: HZ_OVERLAP x{n1}, FREQ_BAND_HZ x{n2} (esperava 1 cada)')
        if enabled is not None:
            enabled = 1 if enabled else 0
            src, n3 = re.subn(r'(?m)^BANDS_ENABLED = [01]', f'BANDS_ENABLED = {enabled}', src)
            if n3 != 1:
                raise KeyError(f'tuning.py: BANDS_ENABLED x{n3} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:   # na hora (o stream le daqui; o reload do native pode atrasar)
        _tuning.HZ_OVERLAP = overlap
        _tuning.FREQ_BAND_HZ = [list(x) for x in ranges]
        if enabled is not None:
            _tuning.BANDS_ENABLED = enabled
    out = {'overlap': overlap, 'ranges': ranges}
    if enabled is not None:
        out['enabled'] = enabled
    return out


# dinamica por faixa (release/attack/auto-gain das 8 finas): 3 listas de 8 floats em
# tuning.py. Endpoint proprio /tweaks reescreve so as listas que vierem no corpo (mirror de
# set_band_ranges). O clamp casa com os trilhos dos sliders no popup da faixa.
_BAND_TWEAK_CLAMP = {'BAND_SMOOTHING': (0.5, 0.99), 'BAND_ATTACK': (0.05, 1.0),
                     'BAND_PEAK_DECAY': (0.9, 0.9999)}


def set_band_tweaks(tweaks, tuning_path=None):
    """Reescreve as listas BAND_SMOOTHING / BAND_ATTACK / BAND_PEAK_DECAY em tuning.py (8
    floats cada, ordem de FREQ_BAND_HZ), preservando alinhamento e comentario da linha.
    `tweaks`: {NOME_DA_LISTA: [8 numeros]} — lista ausente do dict fica intocada. Devolve o
    dict do que foi escrito, ja clampado."""
    out = {}
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        for key, (lo, hi) in _BAND_TWEAK_CLAMP.items():
            if key not in tweaks:
                continue
            vals = [round(max(lo, min(hi, float(v))), 4) for v in list(tweaks[key])]
            if len(vals) != 8:
                raise ValueError(f'{key}: esperava 8 valores, veio {len(vals)}')
            src, n = re.subn(rf'(?m)^{key} *= *\[[^\]]*\]',
                             lambda m, v=vals: re.sub(r'\[.*', repr(v), m.group(0)), src)
            if n != 1:
                raise KeyError(f'tuning.py: {key} x{n} (esperava 1)')
            out[key] = vals
        _write_atomic(path, src)
    if _tuning is not None:
        for key, vals in out.items():
            setattr(_tuning, key, list(vals))
    return out


def _slugify(name):
    """<texto livre> -> nome seguro em [A-Za-z0-9_-]. ValueError se sobrar vazio."""
    slug = re.sub(r'[^A-Za-z0-9_-]', '', name.strip()).strip('.-')
    if not slug:
        raise ValueError(f'nome invalido: {name!r}')
    return slug


# ---------------- SETS de shader = subpastas em shaders/presets/ ----------------
# TODO set (inclusive "default") = presets/<set>/. "default" e' so o fallback: sempre existe,
# nao pode sumir (apagar = esvaziar). _migrate_default_to_folder move os .frag que ficavam
# soltos em presets/ pra presets/default/.
def _list_shader_sets():
    os.makedirs(os.path.join(_SHADERS, 'presets', 'default'), exist_ok=True)
    subs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(_SHADERS, 'presets', '*'))
                  if os.path.isdir(p))
    return ['default'] + [s for s in subs if s != 'default']


def _shader_set_dir(setname):
    return os.path.join(_SHADERS, 'presets', setname)


def _active_shader_set():
    return getattr(_tuning, 'SHADER_SET', 'default') or 'default'


def _list_shaders(setname=None):
    """image.frag (base, aparece em todo set) + presets do set `setname` (ativo se None).
    Caminhos relativos a shaders/ ('image.frag' | 'presets/<set>/x.frag')."""
    if setname is None:
        setname = _active_shader_set()
    out = ['image.frag'] if os.path.isfile(os.path.join(_SHADERS, 'image.frag')) else []
    for p in sorted(glob.glob(os.path.join(_SHADERS, 'presets', setname, '*.frag'))):
        out.append(os.path.relpath(p, _SHADERS).replace(os.sep, '/'))
    return out


def _shader_manifests(names, defaults=False):
    """{caminho: [nomes do cabecalho // fx:]} — os sliders de forca de cada shader.
    defaults=True -> {caminho: {nome: padrao}} (o "nome=0.5" do cabecalho)."""
    out = {}
    for rel in names:
        try:
            with open(os.path.join(_SHADERS, rel)) as f:
                d = dash_data.parse_fx_defaults(f.read(4000))
        except OSError:
            d = {}
        out[rel] = d if defaults else list(d)
    return out


def _all_shaders():
    """image.frag + TODOS os .frag sob presets/ (qualquer set) — pra validar set_shader."""
    out = ['image.frag'] if os.path.isfile(os.path.join(_SHADERS, 'image.frag')) else []
    out += sorted(os.path.relpath(p, _SHADERS).replace(os.sep, '/')
                  for p in glob.glob(os.path.join(_SHADERS, 'presets', '**', '*.frag'), recursive=True))
    return out


def set_shader(name, tuning_path=None):
    """Reescreve SHADER = "<name>" em tuning.py. `name` tem que ser um shader conhecido
    (barra path traversal). Aplica na hora patchando o modulo tuning."""
    if name not in _all_shaders():
        raise KeyError(f'shader desconhecido: {name!r}')
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        new, n = re.subn(r'(?m)^(SHADER = )"[^"]*"', rf'\g<1>"{name}"', src)
        if n != 1:
            raise KeyError(f'tuning.py: SHADER x{n} (esperava 1)')
        _write_atomic(path, new)
    if _tuning is not None:
        _tuning.SHADER = name
    return name


def set_active_shader_set(name, tuning_path=None):
    """Reescreve SHADER_SET. `name` tem que ser um set existente (pasta em presets/)."""
    if name not in _list_shader_sets():
        raise ValueError(f'set de shader desconhecido: {name!r}')
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^SHADER_SET = "[^"]*"', f'SHADER_SET = "{name}"', src)
        if n != 1:
            raise KeyError(f'tuning.py: SHADER_SET x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.SHADER_SET = name
    return name


def create_shader_set(name):
    """mkdir shaders/presets/<slug>. ValueError se ja existir."""
    slug = _slugify(name)
    if slug == 'default':
        raise ValueError('"default" sempre existe')
    d = os.path.join(_SHADERS, 'presets', slug)
    if os.path.isdir(d):
        raise ValueError(f'set ja existe: {slug}')
    os.makedirs(d)
    return slug


def delete_shader_set(name, tuning_path=None):
    """"default": apaga os .frag do set e recria a pasta vazia (default sempre existe, e o
    fallback). Set nomeado: move os .frag pro default e apaga a pasta. Nos dois casos tira o
    set de SHADER_KEYS e ajusta SHADER_SET/SHADER se apontavam pra ele."""
    d = os.path.join(_SHADERS, 'presets', name)
    if not os.path.isdir(d):
        raise ValueError(f'set nao existe: {name}')
    path = tuning_path or _cfg['tuning_path']
    if name == 'default':
        for f in glob.glob(os.path.join(d, '*.frag')):
            os.remove(f)
    else:
        dest_dir = os.path.join(_SHADERS, 'presets', 'default')
        os.makedirs(dest_dir, exist_ok=True)
        for f in glob.glob(os.path.join(d, '*.frag')):
            dest = os.path.join(dest_dir, os.path.basename(f))
            os.remove(f) if os.path.exists(dest) else os.rename(f, dest)
        shutil.rmtree(d)
    os.makedirs(os.path.join(_SHADERS, 'presets', 'default'), exist_ok=True)
    keys = _read_keys('SHADER_KEYS')
    if name in keys:
        del keys[name]
        _write_keys('SHADER_KEYS', keys, path)
    if _active_shader_set() == name and name != 'default':
        set_active_shader_set('default', path)
    pre = f'presets/{name}/'
    _remap_shader_layers({o['file']: (None if name == 'default' or
                                      'presets/default/' + o['file'][len(pre):] not in _all_shaders()
                                      else 'presets/default/' + o['file'][len(pre):])
                          for o in _current_shader_layers() if o['file'].startswith(pre)}, path)
    cur = getattr(_tuning, 'SHADER', '')
    if name == 'default' and cur.startswith('presets/default/'):
        set_shader('image.frag', path)
    elif name != 'default' and cur.startswith(f'presets/{name}/'):
        moved = 'presets/default/' + os.path.basename(cur)
        set_shader(moved if moved in _all_shaders() else 'image.frag', path)
    return name


def _shader_dir_of(rel):
    """diretorio absoluto de presets/<...>/x.frag (mantem o set do caminho)."""
    return os.path.dirname(os.path.join(_SHADERS, rel))


def rename_shader(name, newname, tuning_path=None, presets_dir=None):
    """Renomeia um preset DENTRO do mesmo set. Ajusta SHADER e a tecla (em qualquer set)."""
    if not name.startswith('presets/'):
        raise ValueError('so da pra renomear preset (image.frag e a base)')
    d = presets_dir or _shader_dir_of(name)
    old_p = os.path.join(d, os.path.basename(name))
    if not os.path.isfile(old_p):
        raise ValueError(f'nao existe: {name}')
    new_rel = os.path.dirname(name).replace(os.sep, '/') + '/' + _slugify(newname) + '.frag'
    new_p = os.path.join(d, os.path.basename(new_rel))
    if os.path.exists(new_p) and new_p != old_p:
        raise ValueError(f'ja existe: {new_rel}')
    os.rename(old_p, new_p)
    if presets_dir is None:
        path = tuning_path or _cfg['tuning_path']
        if getattr(_tuning, 'SHADER', '') == name:
            set_shader(new_rel, path)
        _rekey('SHADER_KEYS', name, new_rel, path)
        _remap_shader_layers({name: new_rel}, path)
        _remap_scenes(shaders={name: new_rel}, tuning_path=path)
    return new_rel


def delete_shader(name, tuning_path=None, presets_dir=None):
    """Apaga um preset. Se era o ativo, volta pra image.frag; tira a tecla."""
    if not name.startswith('presets/'):
        raise ValueError('so da pra apagar preset (image.frag e a base)')
    d = presets_dir or _shader_dir_of(name)
    p = os.path.join(d, os.path.basename(name))
    if not os.path.isfile(p):
        raise ValueError(f'nao existe: {name}')
    os.remove(p)
    if presets_dir is None:
        path = tuning_path or _cfg['tuning_path']
        if getattr(_tuning, 'SHADER', '') == name:
            set_shader('image.frag', path)
        _rekey('SHADER_KEYS', name, None, path)
        _remap_shader_layers({name: None}, path)
        _remap_scenes(shaders={name: None}, tuning_path=path)
    return name


# --- mapas de tecla POR SET: {set: {alvo: tecla}} no mesmo bloco `NOME = {...}` do tuning.py.
# So valem as teclas do set ativo. Migra sozinho um mapa flat antigo pra {"default": flat}. ---
def _read_keys(block):
    raw = dict(getattr(_tuning, block, {}) or {})
    if raw and all(isinstance(v, dict) for v in raw.values()):
        return {str(s): {str(k): str(x) for k, x in dict(mp).items()} for s, mp in raw.items()}
    if raw:  # formato antigo flat -> vira o set "default"
        return {'default': {str(k): str(v) for k, v in raw.items()}}
    return {}


def _read_keys_for(block, setname):
    return _read_keys(block).get(setname, {})


def _write_keys(block, nested, tuning_path=None):
    """Reescreve o bloco `<block> = {set: {alvo: tecla}}` inteiro. Dentro de cada set: tecla
    vazia dropa; tecla repetida -> so a 1a fica (uma tecla -> um alvo POR SET)."""
    clean = {}
    for setname, mp in dict(nested).items():
        inner, seen = {}, set()
        for k, v in dict(mp).items():
            k, v = str(k), str(v).strip().lower()
            if v and k not in inner and v not in seen:
                inner[k] = v
                seen.add(v)
        clean[str(setname)] = inner
    text = f'{block} = ' + json.dumps(clean, indent=4)
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(rf'(?ms)^{block} = \{{.*?^\}}', text, src)
        if n != 1:
            raise KeyError(f'tuning.py: {block} x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        setattr(_tuning, block, {s: dict(mp) for s, mp in clean.items()})
    return clean


def _rekey(block, old, new, tuning_path=None):
    """Renomeia (new) ou tira (new=None) `old` de qualquer set em que ele tenha tecla."""
    keys = _read_keys(block)
    hit = False
    for mp in keys.values():
        if old in mp:
            if new:
                mp[new] = mp.pop(old)
            else:
                del mp[old]
            hit = True
    if hit:
        _write_keys(block, keys, tuning_path)


def _bind_key(block, setname, valid, name, key, tuning_path=None):
    """Vincula/desvincula (key='') `name` a uma tecla DENTRO de `setname`. A tecla sai de
    qualquer outro alvo do mesmo set."""
    if name not in valid:
        raise KeyError(f'alvo desconhecido pra {block}[{setname}]: {name!r}')
    key = str(key).strip().lower()
    keys = _read_keys(block)
    mp = {k: v for k, v in keys.get(setname, {}).items() if v != key}
    if key:
        mp[name] = key
    else:
        mp.pop(name, None)
    keys[setname] = mp
    return _write_keys(block, keys, tuning_path)


def bind_shader_key(name, key, tuning_path=None):
    """POST /shader-key — tecla (no set de shader ativo) que troca o shader."""
    s = _active_shader_set()
    return _bind_key('SHADER_KEYS', s, _all_shaders(), name, key, tuning_path)


# ---------------- galeria de midia (aba Visuais): MEDIA + MEDIA_KEYS ----------------
# espelhado no accept= do <input id="media-file"> do dash.html — manter os dois iguais
_MEDIA_EXT = {'image': {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'},
              'video': {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}}
_MEDIA_CHUNK = 1024 * 1024       # upload vai do socket pro disco em blocos (memoria constante)
_MEDIA_FREE_MIN = 256 * 1024 * 1024  # folga que sobra no disco depois do upload


def _media_dir(override=None):
    return override or _MEDIA


def _media_kind_for(ext):
    """extensao (.png, .mp4, ...) -> 'image' | 'video' | None. Um botao de upload so: o kind
    sai daqui, nao de qual botao o usuario clicou."""
    for k, exts in _MEDIA_EXT.items():
        if ext in exts:
            return k
    return None


# SETS de midia = subpastas em media/ (espelho de shaders/presets/<set>/). "default" = os
# arquivos direto em media/. O 'set' de um item SAI do caminho em 'file' ('x.png' -> default,
# '<set>/x.png' -> <set>). Nao ha bloco MEDIA_SETS: a lista de sets vem do disco.
def _active_media_set():
    return getattr(_tuning, 'MEDIA_SET', 'default') or 'default'


def _list_media_sets(media_dir=None):
    d = _media_dir(media_dir)
    os.makedirs(os.path.join(d, 'default'), exist_ok=True)
    subs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, '*')) if os.path.isdir(p))
    return ['default'] + [s for s in subs if s != 'default']


def _media_set_dir(setname, media_dir=None):
    return os.path.join(_media_dir(media_dir), setname)


def _media_set_of(file):
    """set a partir do 'file' relativo a media/ ('a/b.png' -> 'a'; 'b.png' -> 'default' —
    fallback pra entrada antiga sem prefixo, antes de _migrate_default_to_folder)."""
    head = os.path.dirname(str(file).replace('\\', '/'))
    return head.split('/')[0] if head else 'default'


def _media_rel(setname, fname):
    return f'{setname}/{fname}'


def _read_media(setname=None, media_dir=None):
    """tuning.MEDIA normalizado (dropa item cujo arquivo sumiu). setname != None filtra."""
    d = _media_dir(media_dir)
    out = []
    for m in getattr(_tuning, 'MEDIA', []):
        name = str(m.get('name', ''))
        file = str(m.get('file', '')).replace('\\', '/').lstrip('/')
        mset = _media_set_of(file)
        if not name or '..' in file or not os.path.isfile(os.path.join(d, file)):
            continue
        if setname is not None and mset != setname:
            continue
        out.append({'name': name, 'file': file, 'set': mset,
                    'kind': 'video' if m.get('kind') == 'video' else 'image',
                    'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
                    'transition': str(m.get('transition', '') or ''),
                    **_bounce_field(m)})
    return out


def _bounce_field(m):
    """{'bounce': True} so em video com rebate ligado — ausente = desligado (nao suja os itens
    antigos do tuning.py nem as comparacoes dos testes)."""
    return {'bounce': True} if m.get('kind') == 'video' and m.get('bounce') else {}


def _write_media(allm, tuning_path=None):
    """Reescreve o bloco MEDIA inteiro (lista ja normalizada: name, file (relativo a media/,
    pode ter subpasta do set), kind, fit)."""
    clean = [{'name': m['name'], 'file': m['file'],
              'kind': 'video' if m.get('kind') == 'video' else 'image',
              'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
              'transition': str(m.get('transition', '') or ''),
              # 1, nao True: o bloco sai via json.dumps e `true` nao e Python valido no tuning.py
              **({'bounce': 1} if _bounce_field(m) else {})} for m in allm]
    body = '\n'.join('    ' + json.dumps(m) + ',' for m in clean)
    block = f'MEDIA = [\n{body}\n]' if clean else 'MEDIA = [\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^MEDIA = \[.*?^\]', block, src)
        if n != 1:
            raise KeyError(f'tuning.py: MEDIA x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:   # patch na hora (mesmo objeto do native_synth) — evita GET velho
        _tuning.MEDIA = [dict(m) for m in clean]
    return clean


def set_media(items, setname=None, tuning_path=None, media_dir=None):
    """Substitui os itens do set `setname` (ativo se None), mantendo os outros sets. Cada item
    de `items` e casado com o gravado pelo campo `file` (estavel); `name`/`fit` podem mudar —
    renomear move o arquivo tambem. Nome unico dentro do set. Devolve os itens do set."""
    if setname is None:
        setname = _active_media_set()
    d = _media_dir(media_dir)
    cur = {m['file']: m for m in _read_media(setname, media_dir)}
    keep = [m for m in _read_media(None, media_dir) if _media_set_of(m['file']) != setname]
    clean, seen = [], set()
    for m in items:
        src_item = cur.get(str(m.get('file', '')))
        if src_item is None:
            raise ValueError(f'midia desconhecida no set {setname!r}: {m.get("file")!r}')
        nm = _slugify(str(m.get('name', '')))
        if nm in seen:
            raise ValueError(f'nome repetido no set {setname!r}: {nm!r}')
        seen.add(nm)
        file = _media_rel(setname, nm + os.path.splitext(src_item['file'])[1])
        if file != src_item['file'] and not os.path.exists(os.path.join(d, file)):
            os.rename(os.path.join(d, src_item['file']), os.path.join(d, file))
        kind = m.get('kind') or src_item['kind']
        clean.append({'name': nm, 'file': file, 'kind': kind,
                      'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
                      'transition': str(m.get('transition', '') or ''),
                      **_bounce_field(dict(m, kind=kind))})
    _write_media(keep + clean, tuning_path)
    moved = {old: m['file'] for old, m in zip([str(it.get('file', '')) for it in items], clean) if old != m['file']}
    renamed = {cur[str(it.get('file', ''))]['name']: m['name'] for it, m in zip(items, clean)
               if cur[str(it.get('file', ''))]['name'] != m['name']}
    if moved:
        _remap_overlays(moved, tuning_path)
    if moved or renamed:
        _remap_scenes(files=moved, names=renamed, tuning_path=tuning_path)
    return [dict(m, set=setname) for m in clean]


class _Body:
    """Body do POST lido aos poucos, contando o que falta (pra `drain` se o upload for recusado)."""
    def __init__(self, rfile, length):
        self.rfile, self.left = rfile, length

    def read(self, n):
        buf = self.rfile.read(min(n, self.left)) if self.left > 0 else b''
        self.left -= len(buf)
        return buf

    def drain(self):
        while self.left > 0 and self.read(_MEDIA_CHUNK):
            pass


def add_media(orig_name, kind=None, data=b'', setname=None, tuning_path=None, media_dir=None,
              stream=None, length=0):
    """Grava `data` (ou `length` bytes lidos de `stream`, em blocos) em media/<set>/<slug><ext> e
    adiciona a MEDIA no set `setname` (ativo se None). `kind` opcional — sai da extensao."""
    if setname is None:
        setname = _active_media_set()
    ext = os.path.splitext(str(orig_name))[1].lower()
    if kind not in ('image', 'video'):
        kind = _media_kind_for(ext)
    if kind is None or ext not in _MEDIA_EXT[kind]:
        aceitas = _MEDIA_EXT['image'] | _MEDIA_EXT['video']
        raise ValueError(f'extensao {ext or "?"} nao suportada ({", ".join(sorted(aceitas))})')
    slug = _slugify(os.path.splitext(os.path.basename(str(orig_name)))[0])
    sd = _media_set_dir(setname, media_dir)
    os.makedirs(sd, exist_ok=True)
    fname = slug + ext
    fpath = os.path.join(sd, fname)
    if os.path.exists(fpath):
        raise ValueError(f'ja existe: media/{_media_rel(setname, fname)}')
    if any(m['name'] == slug for m in _read_media(setname, media_dir)):
        raise ValueError(f'ja existe midia {slug!r} no set {setname!r}')
    if stream is not None and shutil.disk_usage(sd).free < length + _MEDIA_FREE_MIN:
        raise ValueError(f'sem espaco em disco pra {length // (1024 * 1024)} MB')
    entry = {'name': slug, 'file': _media_rel(setname, fname), 'kind': kind, 'fit': 'fill', 'transition': ''}
    part = fpath + '.part'   # so vira o arquivo de verdade se chegou inteiro
    try:
        with open(part, 'wb') as f:
            if stream is None:
                f.write(data)
            else:
                left = length
                while left > 0:
                    buf = stream.read(min(_MEDIA_CHUNK, left))
                    if not buf:
                        raise ValueError(f'upload interrompido ({length - left} de {length} bytes)')
                    f.write(buf)
                    left -= len(buf)
        os.replace(part, fpath)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    _write_media(_read_media(None, media_dir) + [entry], tuning_path)
    return dict(entry, set=setname)


def delete_media(name, setname=None, tuning_path=None, media_dir=None):
    """Tira (name, setname) de MEDIA, apaga o arquivo, dropa a tecla. Se era o input ativo,
    volta pra webcam."""
    if setname is None:
        setname = _active_media_set()
    path = tuning_path or _cfg['tuning_path']
    hit = next((m for m in _read_media(setname, media_dir) if m['name'] == name), None)
    if hit is None:
        raise ValueError(f'nao existe midia {name!r} no set {setname!r}')
    _write_media([m for m in _read_media(None, media_dir)
                  if not (m['name'] == name and _media_set_of(m['file']) == setname)], path)
    fpath = os.path.join(_media_dir(media_dir), hit['file'])
    if os.path.isfile(fpath):
        os.remove(fpath)
    _rekey('MEDIA_KEYS', name, None, path)
    _remap_overlays({hit['file']: None}, path)
    _remap_scenes(files={hit['file']: None}, names={name: None}, tuning_path=path)
    fn = _cfg.get('on_set_input')
    if fn and (_state.get('video') or {}).get('mode') == 'media' \
            and (_state.get('video') or {}).get('name') == name:
        fn('video', 'webcam:/dev/video0')
    return name


# ---------------- miniatura dos canais da mesa (GET /thumb?src=) ----------------
_thumb_cache = {}   # caminho da midia -> (mtime, jpeg)


def _jpeg(args, data=None, vf='scale=240:-2'):
    try:
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', *args, '-frames:v', '1', '-vf', vf,
                            '-q:v', '6', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-'],
                           input=data, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout or None


def thumb(src):
    """JPEG pequeno pro card do canal: midia = 1 frame do arquivo (cache por mtime); camera/tela =
    o frame que o native esta capturando agora (on_thumb). None = sem imagem (fonte parada)."""
    src = _base_key(src)
    if src.startswith(('webcam:', 'screen:')):
        fn = _cfg.get('on_thumb')
        got = fn(src) if fn else None
        if not got:
            return None
        data, w, h = got
        return _jpeg(['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-i', '-'], data)
    if not src or '..' in src:
        return None
    path = os.path.join(_media_dir(), src)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _thumb_cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    jpg = None
    if os.path.splitext(path)[1].lower() in _MEDIA_EXT['video']:
        jpg = _jpeg(['-ss', '1', '-i', path])       # 1s adentro: evita o 1o frame preto
    jpg = jpg or _jpeg(['-i', path], vf='format=rgba,premultiply=inplace=1,scale=240:-2')  # transparente -> preto
    if jpg:
        _thumb_cache[path] = (mt, jpg)
    return jpg


# ---------------- camadas (overlay) de midia: OVERLAYS = [{file, opacity}] ----------------
# Ordem = de baixo pra cima, na ordem em que foram marcadas (a ultima marcada fica por cima).
# Vivo em _state['overlays'] (o native_synth compoe por frame em cima da fonte atual); gravado
# em tuning.OVERLAYS so quando save=True (soltar o slider / marcar/desmarcar) — igual o FX.
# modos de mistura das camadas de SHADER (camada de midia ignora). A ordem e' o indice que o
# native_synth passa pro shader de mistura (u_mode) — nao reordenar.
LAYER_BLENDS = ['normal', 'soma', 'tela', 'multiplicar', 'clarear']


def _chkey(o):
    """chave do CANAL da mesa: a mesma fonte pode estar 2x+ (item com 'dup': N >= 2) -> 'file#N'.
    BINDINGS e a selecao usam essa chave; o frame vem da fonte (_base_key)."""
    d = o.get('dup')
    return f"{o.get('file', '')}#{d}" if d else o.get('file', '')


def _base_key(key):
    """'file#N' -> 'file' (a fonte de verdade de um canal repetido)."""
    b, sep, n = str(key or '').rpartition('#')
    return b if sep and n.isdigit() else str(key or '')


def _remap_key(key, files):
    """renomear/apagar na Biblioteca numa chave de canal ('file' ou 'file#N'). None = apagada."""
    b = _base_key(key)
    if b not in files:
        return key
    return files[b] + key[len(b):] if files[b] else None


def _norm_fx(lv):
    return {str(n): round(max(0.0, min(1.0, float(x))), 4) for n, x in dict(lv or {}).items()}


def _norm_rect(r):
    """[x, y, w, h] de um canal no canvas (0..1, origem em cima a esquerda; pode sair um pouco do
    canvas, o que sobra e' cortado). None = canvas inteiro (o padrao nao vai pro tuning.py)."""
    try:
        x, y, w, h = (float(v) for v in r)
    except (TypeError, ValueError):
        return None
    w, h = (round(max(0.02, min(4.0, v)), 4) for v in (w, h))
    x, y = (round(max(-2.0, min(2.0, v)), 4) for v in (x, y))
    return None if [x, y, w, h] == [0, 0, 1, 1] else [x, y, w, h]


def _norm_overlays(items, dedupe=True):
    """dedupe=False na pilha de shaders: o mesmo .frag pode entrar 2x na mesma fonte (cada entrada
    com as suas forcas em 'fx')."""
    out, seen, aud = [], set(), False
    for it in items or []:
        f = str((it or {}).get('file', '')).replace('\\', '/').lstrip('/')
        dup = int(it.get('dup') or 0) if str(it.get('dup') or '').isdigit() else 0
        ck = f'{f}#{dup}' if dup >= 2 else f
        if not f or '..' in f or (dedupe and ck in seen):
            continue
        seen.add(ck)
        o = {'file': f, 'opacity': round(max(0.0, min(1.0, float(it.get('opacity', 1.0)))), 3)}
        if dup >= 2:        # 2a+ vez da mesma fonte na mesa (canal proprio: pilha/modo/opacidade)
            o['dup'] = dup
        if it.get('blend') in LAYER_BLENDS[1:]:   # 'normal' (padrao) nao vai pro tuning.py
            o['blend'] = it['blend']
        if it.get('off'):   # desligada: fica na lista (posicao/opacidade lembradas), fora da saida
            o['off'] = 1
        if it.get('audio') and not aud:   # 🔊 video = fonte de audio no lugar do PulseAudio (so' 1)
            o['audio'], aud = 1, True
        if isinstance(it.get('fx'), dict):   # forcas desta entrada da pilha (ausente = fx[shader] da fonte)
            o['fx'] = _norm_fx(it['fx'])
        r = _norm_rect(it.get('rect'))
        if r:               # objeto no CANVAS (posicao/tamanho); ausente = canvas inteiro
            o['rect'] = r
        out.append(o)
    return out


def _set_layers(key, var, items, save, tuning_path, comment):
    """Mecanica comum das camadas (midia e shader): _state[key] ao vivo; save=True reescreve o
    bloco `var = [...]` do tuning.py (acrescenta no fim se o tuning.py ainda nao tem o bloco)."""
    clean = _norm_overlays(items)
    if _state is not None:
        _state[key] = clean
    if save:
        body = '\n'.join('    ' + json.dumps(o) + ',' for o in clean)
        block = f'{var} = [\n{body}\n]' if clean else f'{var} = [\n]'
        path = tuning_path or _cfg['tuning_path']
        with _knob_lock:
            src = open(path).read()
            src, n = re.subn(rf'(?ms)^{var} = \[.*?^\]', block, src)
            if n == 0:
                src = src.rstrip('\n') + f'\n\n# {comment}\n' + block + '\n'
            _write_atomic(path, src)
        if _tuning is not None:
            setattr(_tuning, var, [dict(o) for o in clean])
    return clean


def _current_layers(key, var):
    ov = _state.get(key) if _state is not None else None
    return list(ov) if ov is not None else _norm_overlays(getattr(_tuning, var, []))


def _remap_layers(key, var, setter, mapping, tuning_path=None):
    """{file_antigo: file_novo | None} -> atualiza as camadas (renomear move, apagar tira)."""
    cur = _current_layers(key, var)
    if not any(o['file'] in mapping for o in cur):
        return
    new = [dict(o, file=mapping[o['file']]) if o['file'] in mapping else o for o in cur]
    setter([o for o in new if o['file']], save=True, tuning_path=tuning_path)


def set_overlays(items, save=False, tuning_path=None):
    return _set_layers('overlays', 'OVERLAYS', items, save, tuning_path,
                       'camadas de midia por cima da fonte (dash, aba Visuals)')


def _current_overlays():
    return _current_layers('overlays', 'OVERLAYS')


def _remap_overlays(mapping, tuning_path=None):
    _remap_layers('overlays', 'OVERLAYS', set_overlays, mapping, tuning_path)


# ---------------- camadas de SHADER: SHADER_LAYERS = [{file, opacity}] ----------------
# Mesmo esquema das camadas de midia, so que `file` e' um caminho de shader (igual SHADER:
# 'image.frag' | 'presets/<set>/x.frag'). O native_synth desenha o SHADER ativo e depois cada
# camada, com a MESMA imagem de entrada e os mesmos uniforms, por cima (alpha = opacidade).
def set_shader_layers(items, save=False, tuning_path=None):
    return _set_layers('shader_layers', 'SHADER_LAYERS', items, save, tuning_path,
                       'camadas de shader por cima do shader ativo (dash, aba Visuals)')


def _current_shader_layers():
    return _current_layers('shader_layers', 'SHADER_LAYERS')


def _remap_shader_layers(mapping, tuning_path=None):
    _remap_layers('shader_layers', 'SHADER_LAYERS', set_shader_layers, mapping, tuning_path)


# ---------------- LIGAÇÕES fonte -> shaders: BINDINGS = {fonte: {shaders, fx}} ----------------
# A saida e' SO o que esta marcado em OVERLAYS (fontes vivas + midias, de baixo pra cima). Cada
# fonte passa pela SUA pilha: BINDINGS[fonte]['shaders'] = [{file, opacity, blend?}] (mesmo
# formato das camadas; ordem = de baixo pra cima) e BINDINGS[fonte]['fx'] = {shader: {nome: 0..1}}
# (forca de cada efeito DAQUELE shader NAQUELA fonte). Chave da fonte = a mesma de OVERLAYS:
# 'webcam:/dev/videoN' | 'screen:<monitor>' | arquivo de midia ('default/x.mp4'). Fica lembrado
# mesmo com a fonte desmarcada. Vivo em _state['bindings'].
def _norm_bindings(b):
    out = {}
    for key, v in dict(b or {}).items():
        key = str(key).replace('\\', '/').lstrip('/')
        if not key or '..' in key or not isinstance(v, dict):
            continue
        fx = {}
        for sh, lv in dict(v.get('fx') or {}).items():
            if '..' in str(sh) or not isinstance(lv, dict):
                continue
            fx[str(sh)] = _norm_fx(lv)
        out[key] = {'shaders': _norm_overlays(v.get('shaders'), dedupe=False), 'fx': fx}
    return out


def set_bindings(b, save=False, tuning_path=None):
    """Aplica as ligacoes ao vivo; save=True reescreve o bloco BINDINGS (acrescenta se nao tem)."""
    clean = _norm_bindings(b)
    if _state is not None:
        _state['bindings'] = clean
    if save:
        body = '\n'.join(f'    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},'
                         for k, v in clean.items())
        block = f'BINDINGS = {{\n{body}\n}}' if clean else 'BINDINGS = {\n}'
        path = tuning_path or _cfg['tuning_path']
        with _knob_lock:
            src = open(path).read()
            src, n = re.subn(r'(?ms)^BINDINGS = \{.*?^\}', lambda _: block, src)
            if n == 0:
                src = src.rstrip('\n') + ('\n\n# fonte/midia -> shaders dela (+ forca dos efeitos), dash aba'
                                          ' Visuals > Sets\n') + block + '\n'
            _write_atomic(path, src)
        if _tuning is not None:
            _tuning.BINDINGS = json.loads(json.dumps(clean))
    return clean


def _current_bindings():
    b = _state.get('bindings') if _state is not None else None
    return json.loads(json.dumps(b)) if b is not None else _norm_bindings(getattr(_tuning, 'BINDINGS', {}))


def _remap_bindings(bindings, files=None, shaders=None):
    """Renomear/apagar na Biblioteca dentro de um dict de ligacoes (devolve um novo)."""
    files, shaders = files or {}, shaders or {}
    out = {}
    for key, v in bindings.items():
        nk = _remap_key(key, files)
        if not nk:
            continue
        out[nk] = {'shaders': [dict(o, file=shaders[o['file']]) if o['file'] in shaders else o
                               for o in v.get('shaders', []) if shaders.get(o['file'], 1)],
                   'fx': {shaders.get(sh, sh): lv for sh, lv in v.get('fx', {}).items() if shaders.get(sh, 1)}}
    return out


def _remap_live_bindings(files=None, shaders=None, tuning_path=None):
    cur = _current_bindings()
    new = _remap_bindings(cur, files, shaders)
    if new != cur:
        set_bindings(new, save=True, tuning_path=tuning_path)


def _media_by(field, value):
    return next((m for m in getattr(_tuning, 'MEDIA', []) if m.get(field) == value), None)


def _source_key_of_input(ident):
    """id de /input ('media:<nome>' | 'webcam:..' | 'screen:..') -> chave de fonte (OVERLAYS)."""
    ident = str(ident or '')
    if ident.startswith('media:'):
        m = _media_by('name', ident[6:])
        return m['file'] if m else ''
    return '' if ident == 'media' else ident


def _input_of_source_key(key):
    """chave de fonte -> id de /input (pra a captura/analise seguir a fonte SELECIONADA)."""
    key = str(key or '')
    if key.startswith(('webcam:', 'screen:')) or not key:
        return key
    m = _media_by('file', key)
    return 'media:' + m['name'] if m else ''


def _current_selected():
    """fonte SELECIONADA (a que a lista de efeitos mostra; nao mexe na saida)."""
    sel = (_state or {}).get('selected')
    if sel:
        return sel
    v = (_state or {}).get('video') or {}
    if v.get('mode') == 'media' and v.get('name'):
        return _source_key_of_input('media:' + v['name'])
    return (_state or {}).get('video_id', '') or ''


def set_source_fit(key, fit, tuning_path=None):
    """preencher ('fill' = estica pra cobrir a saida) / encaixar ('fit' = inteira, com margens) de
    uma CAMERA/TELA -> bloco SOURCE_FIT (so guarda os 'fit'; ausente = 'fill'). Midia guarda o
    dela no item de MEDIA (POST /media). Vale em todos os sets, igual o da midia."""
    key = str(key or '')
    if not key.startswith(('webcam:', 'screen:')):
        raise ValueError(f'nao e camera/tela: {key!r}')
    cur = dict(getattr(_tuning, 'SOURCE_FIT', None) or {})
    if fit == 'fit':
        cur[key] = 'fit'
    else:
        cur.pop(key, None)
    body = '\n'.join(f'    {json.dumps(k)}: "fit",' for k in sorted(cur))
    block = f'SOURCE_FIT = {{\n{body}\n}}' if cur else 'SOURCE_FIT = {\n}'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^SOURCE_FIT = \{.*?^\}', lambda _: block, src)
        if n == 0:
            src = src.rstrip('\n') + ('\n\n# camera/tela: "fit" = encaixa com margens (ausente = estica pra'
                                      ' preencher), dash aba Visuals > Sets\n') + block + '\n'
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.SOURCE_FIT = cur
    fn = _cfg.get('on_set_input')     # a capturada (selecionada) respawna com o -vf novo
    if fn and (_state or {}).get('video_id') == key:
        fn('video', key)
    return 'fit' if fit == 'fit' else 'fill'


def select_source(key):
    """Seleciona a fonte (clique no nome): a lista de efeitos passa a ser a dela, e a captura/
    analise (aba Source Image) segue ela. NAO muda a saida — so o que esta marcado conta."""
    key = str(key or '')
    ident = _input_of_source_key(_base_key(key))   # canal repetido ('file#2') captura a fonte dele
    if not ident:
        raise ValueError(f'fonte desconhecida: {key!r}')
    if _state is not None:
        _state['selected'] = key
    fn = _cfg.get('on_set_input')
    if fn:
        fn('video', ident)
    return key


# ---------------- DISPONÍVEIS por set: pool = {'sources': [...], 'shaders': [...]} ----------------
# Quais fontes/midias e quais shaders o set ATIVO oferece. Lista ausente = TUDO (set antigo, ou
# nunca editado). Tirar do set esconde do editor E da saida (o native filtra), mas as ligacoes
# (BINDINGS) e a marcacao (OVERLAYS) ficam lembradas — voltar ao set traz como estava. Vivo em
# _state['pool'] (o apply_scene poe o do set); gravado so dentro do set (campo 'pool').
def _norm_pool(p):
    if not isinstance(p, dict):
        return None
    out = {}
    for k in ('sources', 'shaders'):
        if isinstance(p.get(k), list):
            seen = []
            for x in p[k]:
                x = str(x or '')
                if x and '..' not in x and x not in seen:
                    seen.append(x)
            out[k] = seen
    return out or None


def _current_pool():
    return _norm_pool((_state or {}).get('pool'))


def set_pool(pool):
    """Troca o que o set ativo oferece (o dash manda a lista explicita inteira) e auto-salva."""
    if _state is not None:
        _state['pool'] = _norm_pool(pool)
    save_active_scene()
    return _current_pool()


def _pool_add(kind, key):
    """Arquivo NOVO na Biblioteca (upload / + criar .frag) entra no set ativo, se a lista dele e'
    explicita (lista ausente = tudo, ja entra)."""
    pool = _current_pool()
    if pool and kind in pool and key not in pool[kind]:
        pool[kind].append(key)
        set_pool(pool)


def _remap_pool(pool, files=None, shaders=None):
    if not pool:
        return pool
    files, shaders = files or {}, shaders or {}
    out = dict(pool)
    if 'sources' in out:
        out['sources'] = [files.get(k, k) for k in out['sources'] if files.get(k, k)]
    if 'shaders' in out:
        out['shaders'] = [shaders.get(k, k) for k in out['shaders'] if shaders.get(k, k)]
    return out


# ---------------- SETS (cenas): SCENES = [{...}], SCENE = "<nome do ativo>" ----------------
# Um set guarda TUDO que o Visuals mostra: 'sources' (as fontes/midias MARCADAS = a saida, igual
# OVERLAYS), 'bindings' (os shaders + forcas de cada fonte, igual BINDINGS) e 'selected' (a fonte
# selecionada na lista). O set ATIVO e' o estado ao vivo: toda edicao auto-salva nele
# (save_active_scene). Set no formato antigo (fonte principal + shader global) e' convertido na
# leitura (_upgrade_scene). Trocar de set = apply_scene (o native_synth
# chama no fim de um frame, pra capturar a imagem que sai e rodar a transicao de ENTRADA do set
# — campo 'transition': '' = TRANSITION_DEFAULT, 'none' = corte seco, '<x>.glsl').
# Tecla (campo 'key') troca de set na janela do native_synth ou no dash.
_applying = [False]   # dentro do apply_scene: os setters nao auto-salvam (o set ja e' a fonte)


def _upgrade_scene(sc):
    """Formato antigo -> novo: a fonte principal vira uma fonte MARCADA (embaixo, 100%) e a pilha
    antiga (shader principal + camadas de shader, com o FX global) vira a pilha de CADA fonte
    marcada — o visual fica o mais proximo possivel do que era."""
    if 'sources' in sc:
        return sc
    sources = _norm_overlays(sc.get('overlays'))
    main = _source_key_of_input(sc.get('video', ''))
    if main and not any(o['file'] == main for o in sources):
        sources.insert(0, {'file': main, 'opacity': 1.0})
    stack = ([{'file': sc['shader'], 'opacity': 1.0}] if sc.get('shader') else []) + \
        _norm_overlays(sc.get('shader_layers'))
    fx = {o['file']: dict(sc.get('fx') or {}) for o in stack} if sc.get('fx') else {}
    return {'name': sc.get('name', ''), 'key': sc.get('key', ''), 'transition': sc.get('transition', ''),
            'selected': main or (sources[0]['file'] if sources else ''), 'sources': sources,
            'bindings': _norm_bindings({o['file']: {'shaders': stack, 'fx': fx} for o in sources})}


def _read_scenes():
    return [_upgrade_scene(dict(sc)) for sc in (getattr(_tuning, 'SCENES', None) or [])]


def _active_scene_name():
    return str(getattr(_tuning, 'SCENE', '') or '')


def _write_scenes(scenes, active=None, tuning_path=None):
    """Reescreve SCENES (e SCENE se `active`); acrescenta os blocos se o tuning.py e' antigo.
    json.dumps serve de literal Python aqui: set so tem str/numero/lista/dict (sem bool/None)."""
    body = '\n'.join('    ' + json.dumps(sc, ensure_ascii=False) + ',' for sc in scenes)
    block = f'SCENES = [\n{body}\n]' if scenes else 'SCENES = [\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^SCENES = \[.*?^\]', lambda _: block, src)
        if n == 0:
            src = src.rstrip('\n') + ('\n\n# SETS (cenas) da aba Visuals: fonte + camadas + shader + camadas'
                                      ' de shader + forca dos efeitos (dash, sub-aba Sets)\n') + block + '\n'
        if active is not None:
            line = f'SCENE = {json.dumps(active, ensure_ascii=False)}'
            src, n = re.subn(r'(?m)^SCENE = .*$', lambda _: line, src)
            if n == 0:
                src = src.rstrip('\n') + '\n' + line + '\n'
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.SCENES = [dict(sc) for sc in scenes]
        if active is not None:
            _tuning.SCENE = active
    return scenes


def scene_capture():
    """O estado ao vivo, nos campos de um set ('pool' None = tudo disponivel -> campo some)."""
    g = _current_scene_grade()
    return {'selected': _current_selected(), 'sources': _current_overlays(), 'bindings': _current_bindings(),
            'pool': _current_pool(), 'grade': g if (g['fx'] or not g['on']) else None}


def _scene_with(sc, cap):
    """sc atualizado com o capturado; campo None sai (json 'null' nao e' Python no tuning.py)."""
    new = dict(sc, **cap)
    return {k: v for k, v in new.items() if v is not None}


def save_active_scene(tuning_path=None):
    """Auto-save: copia o estado ao vivo pro set ativo (chamado depois de cada edicao)."""
    if _applying[0] or _tuning is None or _state is None:
        return
    name = _active_scene_name()
    scenes = _read_scenes()
    for sc in scenes:
        if sc.get('name') == name:
            new = _scene_with(sc, scene_capture())
            if new != sc:
                sc.clear()          # substitui (update manteria campo que voltou a None: pool, grade)
                sc.update(new)
                _write_scenes(scenes, tuning_path=tuning_path)
            return


def _find_scene(name, scenes=None):
    sc = next((x for x in (scenes if scenes is not None else _read_scenes()) if x.get('name') == name), None)
    if sc is None:
        raise ValueError(f'scene desconhecida: {name!r}')
    return sc


def apply_scene(name, tuning_path=None):
    """Carrega o set `name` no estado ao vivo e marca como ativo. Devolve o set."""
    scenes = _read_scenes()
    sc = _find_scene(name, scenes)
    path = tuning_path or _cfg['tuning_path']
    _applying[0] = True
    try:
        _write_scenes(scenes, active=name, tuning_path=path)
        if _state is not None:
            _state['pool'] = _norm_pool(sc.get('pool'))
        set_overlays(sc.get('sources') or [], save=True, tuning_path=path)
        set_bindings(sc.get('bindings') or {}, save=True, tuning_path=path)
        set_scene_grade(sc.get('grade') or {}, save=True, tuning_path=path)   # sem campo = neutra
        if sc.get('selected'):
            try:
                select_source(sc['selected'])
            except ValueError:
                pass                                    # fonte sumiu (camera desplugada, midia apagada)
    finally:
        _applying[0] = False
    return sc


def request_scene(name):
    """Pedido de troca vindo do dash / tecla: valida e deixa pro loop GL aplicar no fim do
    frame (ele captura a imagem que sai pra transicao). Sem loop GL (testes): aplica direto."""
    _find_scene(name)
    if _state is not None and _state.get('gl_running'):
        _state['scene_pending'] = {'name': name, 'transition': True}
    else:
        apply_scene(name)
    return name


def create_scene(name, tuning_path=None):
    """Set novo = copia do estado ao vivo; vira o ativo (sem transicao: a imagem e' a mesma)."""
    name = str(name).strip()
    if not name:
        raise ValueError('nome vazio')
    scenes = _read_scenes()
    if any(sc.get('name') == name for sc in scenes):
        raise ValueError(f'scene ja existe: {name}')
    scenes.append(_scene_with({'name': name, 'key': '', 'transition': ''}, scene_capture()))
    _write_scenes(scenes, active=name, tuning_path=tuning_path)
    return name


def rename_scene(name, newname, tuning_path=None):
    newname = str(newname).strip()
    scenes = _read_scenes()
    sc = _find_scene(name, scenes)
    if not newname:
        raise ValueError('nome vazio')
    if newname != name and any(x.get('name') == newname for x in scenes):
        raise ValueError(f'scene ja existe: {newname}')
    sc['name'] = newname
    active = newname if _active_scene_name() == name else None
    _write_scenes(scenes, active=active, tuning_path=tuning_path)
    return newname


def delete_scene(name, tuning_path=None):
    """Apaga um set (tem que sobrar pelo menos 1). Se era o ativo, vai pro primeiro que sobrou."""
    scenes = _read_scenes()
    _find_scene(name, scenes)
    if len(scenes) <= 1:
        raise ValueError('precisa sobrar pelo menos uma scene')
    scenes = [x for x in scenes if x.get('name') != name]
    was_active = _active_scene_name() == name
    _write_scenes(scenes, tuning_path=tuning_path)
    if was_active:
        request_scene(scenes[0]['name'])
    return name


def set_scene_key(name, key, tuning_path=None):
    """Tecla (a-z/0-9) do set; '' desvincula. Tecla e' unica: sai de outro set que a tinha."""
    key = str(key or '').lower()
    if key and not re.fullmatch(r'[a-z0-9]', key):
        raise ValueError(f'tecla invalida: {key!r}')
    scenes = _read_scenes()
    sc = _find_scene(name, scenes)
    for x in scenes:
        if key and x.get('key') == key:
            x['key'] = ''
    sc['key'] = key
    _write_scenes(scenes, tuning_path=tuning_path)
    return key


def set_scene_transition(name, tn, tuning_path=None):
    """Transicao de ENTRADA do set: '' (padrao), 'none' (corte seco) ou um .glsl existente."""
    tn = str(tn or '')
    if tn not in ('', 'none') and tn not in _list_transitions():
        raise ValueError(f'transicao desconhecida: {tn!r}')
    scenes = _read_scenes()
    _find_scene(name, scenes)['transition'] = tn
    _write_scenes(scenes, tuning_path=tuning_path)
    return tn


def scene_transition_name(name):
    """Nome do .glsl de entrada do set (resolvendo o padrao), ou 'none'."""
    try:
        tn = str(_find_scene(name).get('transition', '') or '')
    except ValueError:
        return 'none'
    return tn or str(getattr(_tuning, 'TRANSITION_DEFAULT', 'none') or 'none')


def _remap_scenes(files=None, shaders=None, names=None, trans=None, tuning_path=None):
    """Renomear/apagar na Biblioteca -> atualiza as referencias em TODOS os sets e nas ligacoes
    vivas. files: {file de midia: novo | None}; shaders: {caminho: novo | None};
    trans: {x.glsl: novo | ''}. (`names` sobrou do formato antigo: midia agora e' chave por file.)"""
    files, shaders, trans = files or {}, shaders or {}, trans or {}
    if files or shaders:
        _remap_live_bindings(files, shaders, tuning_path)
        if _state is not None and _state.get('pool'):
            _state['pool'] = _remap_pool(_state['pool'], files, shaders)
    scenes = _read_scenes()
    changed = False
    for sc in scenes:
        before = json.dumps(sc, sort_keys=True)
        sc['sources'] = [dict(o, file=files[o['file']]) if o.get('file') in files else o
                         for o in sc.get('sources') or [] if files.get(o.get('file'), 1)]
        sc['bindings'] = _remap_bindings(sc.get('bindings') or {}, files, shaders)
        if sc.get('pool'):
            sc['pool'] = _remap_pool(sc['pool'], files, shaders)
        if sc.get('selected') and _base_key(sc['selected']) in files:
            sc['selected'] = _remap_key(sc['selected'], files) or ''
        if sc.get('transition') in trans:
            sc['transition'] = trans[sc['transition']]
        changed |= json.dumps(sc, sort_keys=True) != before
    if changed:
        _write_scenes(scenes, tuning_path=tuning_path)


def _scenes_payload():
    return {'list': [{'name': sc.get('name', ''), 'key': sc.get('key', ''),
                      'transition': sc.get('transition', '')} for sc in _read_scenes()],
            'active': _active_scene_name()}


def set_active_media_set(name, tuning_path=None, media_dir=None):
    if name not in _list_media_sets(media_dir):
        raise ValueError(f'set de midia desconhecido: {name!r}')
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^MEDIA_SET = "[^"]*"', f'MEDIA_SET = "{name}"', src)
        if n != 1:
            raise KeyError(f'tuning.py: MEDIA_SET x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.MEDIA_SET = name
    return name


def create_media_set(name, media_dir=None):
    """mkdir media/<slug>."""
    slug = _slugify(name)
    if slug == 'default':
        raise ValueError('"default" sempre existe')
    sd = _media_set_dir(slug, media_dir)
    if os.path.isdir(sd):
        raise ValueError(f'set ja existe: {slug}')
    os.makedirs(sd)
    return slug


def delete_media_set(name, tuning_path=None, media_dir=None):
    """"default": apaga os arquivos e as entradas de MEDIA do set, recria a pasta vazia
    (default sempre existe, e o fallback). Set nomeado: move os arquivos pro default, reescreve
    o 'file' das entradas, apaga a pasta. Nos dois casos dropa a tecla e ajusta MEDIA_SET."""
    dd = _media_set_dir('default', media_dir)
    sd = _media_set_dir(name, media_dir)
    if not os.path.isdir(sd):
        raise ValueError(f'set nao existe: {name}')
    path = tuning_path or _cfg['tuning_path']
    raw = [dict(m) for m in getattr(_tuning, 'MEDIA', [])]
    if name == 'default':
        raw = [m for m in raw if _media_set_of(m.get('file', '')) != 'default']
        for f in glob.glob(os.path.join(sd, '*')):
            if os.path.isfile(f):
                os.remove(f)
    else:
        os.makedirs(dd, exist_ok=True)
        for m in raw:   # itens do set: file passa a apontar pra media/default/
            if _media_set_of(m.get('file', '')) == name:
                m['file'] = 'default/' + os.path.basename(str(m['file']).replace('\\', '/'))
        for f in glob.glob(os.path.join(sd, '*')):
            if os.path.isfile(f):
                dest = os.path.join(dd, os.path.basename(f))
                os.remove(f) if os.path.exists(dest) else os.rename(f, dest)
        shutil.rmtree(sd)
    os.makedirs(dd, exist_ok=True)
    _write_media(raw, path)
    keys = _read_keys('MEDIA_KEYS')
    if name in keys:
        del keys[name]
        _write_keys('MEDIA_KEYS', keys, path)
    if _active_media_set() == name and name != 'default':
        set_active_media_set('default', path, media_dir)
    return name


def bind_media_key(name, key, tuning_path=None, media_dir=None):
    """POST /media-key — tecla (no set de midia ativo) que troca o input de imagem."""
    s = _active_media_set()
    return _bind_key('MEDIA_KEYS', s, [m['name'] for m in _read_media(s, media_dir)], name, key, tuning_path)


# ---------------- galeria de TRANSIÇÕES (aba Visuais): transitions/*.glsl + TRANSITION_DEFAULT
# Espelho enxuto da galeria de shader: por enquanto SEM sets nem teclas (pasta unica). O arquivo
# e' uma func `vec4 transition(vec2 uv)` estilo gl-transitions; native_synth embrulha num
# harness com getFromColor/getToColor/progress e roda num passe FBO na troca de midia. ----
_NEW_TRANS = """\
// ms: 400
// A = imagem que sai (getFromColor), B = a que entra (getToColor), progress 0..1.
vec4 transition(vec2 uv) {
    return mix(getFromColor(uv), getToColor(uv), progress);
}
"""


def _list_transitions(trans_dir=None):
    d = trans_dir or _TRANS
    os.makedirs(d, exist_ok=True)
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(d, '*.glsl')))


def _transitions_payload(trans_dir=None):
    return {'list': _list_transitions(trans_dir),
            'default': str(getattr(_tuning, 'TRANSITION_DEFAULT', 'none') or 'none')}


def set_transition_default(name, tuning_path=None, trans_dir=None):
    """Reescreve TRANSITION_DEFAULT. `name` = 'none' (corte seco) ou um .glsl existente."""
    name = str(name).strip() or 'none'
    if name != 'none' and name not in _list_transitions(trans_dir):
        raise ValueError(f'transicao desconhecida: {name!r}')
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^TRANSITION_DEFAULT = "[^"]*"', f'TRANSITION_DEFAULT = "{name}"', src)
        if n != 1:
            raise KeyError(f'tuning.py: TRANSITION_DEFAULT x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.TRANSITION_DEFAULT = name
    return name


def new_transition(name, trans_dir=None):
    """Cria transitions/<slug>.glsl (template crossfade). ValueError se vazio ou ja existir."""
    d = trans_dir or _TRANS
    os.makedirs(d, exist_ok=True)
    fname = _slugify(name) + '.glsl'
    p = os.path.join(d, fname)
    if os.path.exists(p):
        raise ValueError(f'ja existe: {fname}')
    open(p, 'w').write(_NEW_TRANS)
    return fname


def rename_transition(name, newname, tuning_path=None, trans_dir=None):
    d = trans_dir or _TRANS
    old_p = os.path.join(d, os.path.basename(str(name)))
    if not os.path.isfile(old_p) or not str(name).endswith('.glsl'):
        raise ValueError(f'nao existe: {name}')
    new_f = _slugify(newname) + '.glsl'
    new_p = os.path.join(d, new_f)
    if os.path.exists(new_p) and new_p != old_p:
        raise ValueError(f'ja existe: {new_f}')
    os.rename(old_p, new_p)
    _rename_transition_refs(os.path.basename(str(name)), new_f, tuning_path)
    return new_f


def delete_transition(name, tuning_path=None, trans_dir=None):
    d = trans_dir or _TRANS
    p = os.path.join(d, os.path.basename(str(name)))
    if not os.path.isfile(p) or not str(name).endswith('.glsl'):
        raise ValueError(f'nao existe: {name}')
    os.remove(p)
    _rename_transition_refs(os.path.basename(str(name)), '', tuning_path)  # '' -> volta pro default
    return name


def _rename_transition_refs(old, new, tuning_path=None):
    """Troca `old` por `new` em TRANSITION_DEFAULT, nos itens de MEDIA e nos sets (apagar -> '')."""
    path = tuning_path or _cfg['tuning_path']
    _remap_scenes(trans={old: new}, tuning_path=path)
    if str(getattr(_tuning, 'TRANSITION_DEFAULT', '')) == old:
        set_transition_default(new or 'none', path)
    media = [dict(m) for m in getattr(_tuning, 'MEDIA', [])]
    if any(m.get('transition') == old for m in media):
        for m in media:
            if m.get('transition') == old:
                m['transition'] = new
        _write_media(media, path)


_NEW_FRAG = """\
// fx: tint
#ifdef GL_ES
precision mediump float;
#endif
uniform vec2 u_resolution;
uniform float u_time;
uniform sampler2D u_texture_0;
uniform float u_fx_tint;

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.xy;
    vec3 cam = texture2D(u_texture_0, uv).rgb;
    vec3 tint = 0.5 + 0.5 * cos(u_time + uv.xyx + vec3(0.0, 2.0, 4.0));
    gl_FragColor = vec4(mix(cam, cam * tint, u_fx_tint), 1.0);
}
"""


def new_shader(name, tuning_path=None, presets_dir=None):
    """Cria um .frag (template minimo, efeito 'tint') NO SET de shader ativo e ja o deixa
    tocando. `name` vira slug [A-Za-z0-9_-]. ValueError se vazio ou o arquivo ja existir."""
    slug = _slugify(name)
    setname = _active_shader_set()
    d = presets_dir or _shader_set_dir(setname)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, slug + '.frag')
    if os.path.exists(path):
        raise ValueError(f'ja existe: {slug}.frag nesse set')
    open(path, 'w').write(_NEW_FRAG)
    rel = ('presets/' if presets_dir else f'presets/{setname}/') + slug + '.frag'
    if presets_dir is None:
        set_shader(rel, tuning_path)
    return rel


def set_fx(fx, tuning_path=None):
    """Reescreve o bloco FX = { ... } inteiro em tuning.py. `fx`: {nome: nivel}, nivel
    clampado 0..1. Mirror de set_channels (POST reescreve o bloco todo). Devolve o dict
    normalizado."""
    clean = {str(k): max(0.0, min(1.0, float(v))) for k, v in dict(fx).items()}
    body = '\n'.join(f'    {json.dumps(k)}: {round(v, 4)},' for k, v in clean.items())
    block = f'FX = {{\n{body}\n}}' if clean else 'FX = {\n}'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^FX = \{.*?^\}', block, src)
        if n != 1:
            raise KeyError(f'tuning.py: FX x{n} (esperava 1)')
        _write_atomic(path, src)
    return clean


OUTPUT_FPS_CHOICES = (24, 30, 50, 60)


def set_output_fps(fps, tuning_path=None):
    """fps da janela de saida (dash v2, aba Saida): patcha tuning.OUTPUT_FPS na hora (o loop GL
    le a cada frame) e grava `OUTPUT_FPS = N` no tuning.py (acrescenta a linha se nao houver)."""
    fps = int(fps)
    if fps not in OUTPUT_FPS_CHOICES:
        raise ValueError(f'fps {fps} fora de {OUTPUT_FPS_CHOICES}')
    if _tuning is not None:
        _tuning.OUTPUT_FPS = fps
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^OUTPUT_FPS = \d+', f'OUTPUT_FPS = {fps}', src)
        if n == 0:
            src = src.rstrip('\n') + ('\n\n# fps da janela de saida (dash v2 > Saida). A 60 o movimento dos shaders'
                                      ' fica liso; camera/video continuam no fps deles\n'
                                      f'OUTPUT_FPS = {fps}\n')
        _write_atomic(path, src)
    return fps


def _norm_screens(items):
    """TELAS do palco fisico: [{name, x, y, w, h (metros, origem em cima a esquerda), pw, ph (pixels
    do painel)}]. O canvas da saida e' o contorno delas (native_synth._stage). Ate 16."""
    out = []
    for i, t in enumerate(items or []):
        try:
            x, y = (round(max(-100.0, min(100.0, float(t[k]))), 3) for k in ('x', 'y'))
            w, h = (round(max(0.05, min(100.0, float(t[k]))), 3) for k in ('w', 'h'))
            pw, ph = (max(1, min(16384, int(t[k]))) for k in ('pw', 'ph'))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        name = str(t.get('name') or f'tela {i + 1}')[:24]
        out.append({'name': name, 'x': x, 'y': y, 'w': w, 'h': h, 'pw': pw, 'ph': ph})
    return out[:16]


def set_screens(items, save=True, tuning_path=None):
    """Telas do palco (dash v2, aba Saida): patcha tuning.SCREENS na hora (o loop GL le a cada
    frame); save=True grava o bloco `SCREENS = [...]` no tuning.py (acrescenta se nao houver).
    Global (o palco fisico e' o mesmo em todas as scenes)."""
    clean = _norm_screens(items)
    if _tuning is not None:
        _tuning.SCREENS = clean
    if save:
        body = '\n'.join('    ' + json.dumps(t, ensure_ascii=False) + ',' for t in clean)
        block = f'SCREENS = [\n{body}\n]' if clean else 'SCREENS = [\n]'
        path = tuning_path or _cfg['tuning_path']
        with _knob_lock:
            src = open(path).read()
            src, n = re.subn(r'(?ms)^SCREENS = \[.*?^\]', lambda m: block, src)
            if n == 0:
                src = src.rstrip('\n') + ('\n\n# telas do palco fisico (dash v2 > Saida): metros (x, y, w, h; origem em cima'
                                          ' a esquerda) + pixels (pw, ph). O canvas e\' o contorno delas\n' + block + '\n')
            _write_atomic(path, src)
    return clean


def set_out_analysis(enabled, tuning_path=None):
    """Reescreve OUT_ANALYSIS_ENABLED em tuning.py — checkbox "calcular" na tab Output Image
    (liga a leitura pos-shader pros mesmos medidores do Source Image, ver native_synth.main)."""
    enabled = 1 if enabled else 0
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^OUT_ANALYSIS_ENABLED = [01]', f'OUT_ANALYSIS_ENABLED = {enabled}', src)
        if n != 1:
            raise KeyError(f'tuning.py: OUT_ANALYSIS_ENABLED x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.OUT_ANALYSIS_ENABLED = enabled
    return enabled


GRADE_FRAG = 'calibrar.frag'   # shaders/calibrar.frag — calibracao da SAIDA (ultimo passe do loop GL)


def output_grade_defaults():
    """{knob: padrao} do cabecalho // fx: do calibrar.frag (o dash monta os knobs disso)."""
    try:
        with open(os.path.join(_SHADERS, GRADE_FRAG)) as f:
            return dash_data.parse_fx_defaults(f.read(4000))
    except OSError:
        return {}


def _current_output_grade():
    g = getattr(_tuning, 'OUTPUT_GRADE', None) or {}
    out = {'on': int(bool(g.get('on', 1))), 'test': int(bool(g.get('test', 0))),
           'fx': dict(g.get('fx') or {})}
    if 'master' in g:
        out['master'] = g['master']
    return out


def _grade_fx(grade):
    """{knob: 0..1} valido, so' o que foge do padrao do calibrar.frag (padrao = omitido)."""
    dflt = output_grade_defaults()
    fx = {}
    for n, v in dict((grade or {}).get('fx') or {}).items():
        n = str(n)
        if not re.fullmatch(r'[A-Za-z0-9_]+', n):
            raise ValueError(f'knob invalido: {n!r}')
        v = round(min(1.0, max(0.0, float(v))), 3)
        if n in dflt and v == dflt[n]:
            continue
        fx[n] = v
    return fx


def _current_scene_grade():
    g = getattr(_tuning, 'SCENE_GRADE', None) or {}
    return {'on': int(bool(g.get('on', 1))), 'fx': dict(g.get('fx') or {})}


def set_scene_grade(grade, save=True, tuning_path=None):
    """IMAGEM DA CENA (dash v2, Palco): mesmos knobs do calibrar.frag, aplicados na mistura da
    cena ANTES da transicao e da calibracao do telao. {'on': 0|1, 'fx': {knob: 0..1}} ->
    tuning.SCENE_GRADE (ao vivo) e, com save, no set ativo (campo 'grade'; neutro = sem campo).
    save=False = arrasto de knob (so' o modulo)."""
    out = {'on': int(bool((grade or {}).get('on', 1))), 'fx': _grade_fx(grade)}
    if _tuning is not None:
        _tuning.SCENE_GRADE = out
    if save:
        block = 'SCENE_GRADE = ' + json.dumps(out, indent=4, sort_keys=True)
        path = tuning_path or _cfg['tuning_path']
        with _knob_lock:
            src = open(path).read()
            src, n = re.subn(r'(?ms)^SCENE_GRADE = \{.*?^\}', lambda _: block, src)
            if n == 0:
                src = src.rstrip('\n') + ('\n\n# imagem da CENA ativa (calibrar.frag na mistura, antes da transicao);'
                                          ' copia do campo "grade" do set ativo\n') + block + '\n'
            _write_atomic(path, src)
        save_active_scene(tuning_path)
    return out


def set_output_grade(grade, save=True, tuning_path=None):
    """Calibracao da saida (aba Output Image): {'on': 0|1, 'test': 0|1 (padrao de teste no
    lugar da imagem), 'fx': {knob: 0..1}} -> tuning.OUTPUT_GRADE (patch na hora; o native le
    a cada frame). save=False = arrasto de knob (so' o modulo, sem gravar o tuning.py). So'
    guarda knob fora do padrao do calibrar.frag; ints, nao bools (o bloco sai via json.dumps)."""
    out = {'on': int(bool(grade.get('on', 1))), 'test': int(bool(grade.get('test', 0))), 'fx': _grade_fx(grade)}
    # master (dash v2: fader + blackout): 0..1, vale mesmo com a calibracao desligada; 1 = omitido
    master = round(min(1.0, max(0.0, float(grade.get('master', 1.0)))), 3)
    if master < 1.0:
        out['master'] = master
    if _tuning is not None:
        _tuning.OUTPUT_GRADE = out
    if save:
        block = 'OUTPUT_GRADE = ' + json.dumps(out, indent=4, sort_keys=True)
        path = tuning_path or _cfg['tuning_path']
        with _knob_lock:
            src = open(path).read()
            src, n = re.subn(r'(?ms)^OUTPUT_GRADE = \{.*?^\}', lambda _: block, src)
            if n == 0:
                src = src.rstrip('\n') + ('\n\n# calibracao da saida (telao): shaders/calibrar.frag, knobs na'
                                          ' aba Output Image. fx ausente = padrao do .frag\n') + block + '\n'
            _write_atomic(path, src)
    return out


def set_channels(channels, tuning_path=None):
    """Reescreve o bloco CHANNELS inteiro em tuning.py. `channels`: 0.._MAX_CHAN
    {"name","src","output"} — lista de TAMANHO LIVRE (add/remove pelo dash, sem slot fixo).
    "src": id de source do PulseAudio ou "" (canal ocioso). "output": nome de uma variavel
    existente (kick/amp/bass/mid/treble/subbass/.../air) que esse canal passa a alimentar
    ENQUANTO tiver src bound, ou "" (so aparece no array u_chan/u_chan_hit). Devolve a lista
    normalizada, no tamanho que veio (ate o teto)."""
    ch = [{'name': str(c.get('name', ''))[:24], 'src': str(c.get('src', '')),
           'output': str(c.get('output', ''))} for c in channels[:_MAX_CHAN]]
    body = '\n'.join('    ' + json.dumps(c) + ',' for c in ch)
    block = f'CHANNELS = [\n{body}\n]' if ch else 'CHANNELS = [\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^CHANNELS = \[.*?^\]', block, src)
        if n != 1:
            raise KeyError(f'tuning.py: CHANNELS x{n} (esperava 1)')
        _write_atomic(path, src)
    if _tuning is not None:
        _tuning.CHANNELS = [dict(c) for c in ch]
    return ch


def _read_knobs():
    return {k['name']: getattr(_tuning, k['name']) for k in KNOBS}


def _payload():
    return {
        'audio': _state.get('audio_dash', {}),   # kick / bands / spectrum — ver dash_data.audio_dash_data
        'image': _state.get('image', {}),
        'out_image': _state.get('out_image', {}),
        'out_analysis_enabled': int(getattr(_tuning, 'OUT_ANALYSIS_ENABLED', 0)),
        'output_grade': _current_output_grade(),   # calibracao da saida (knobs em /output-grade)
        'scene_grade': _current_scene_grade(),     # imagem da cena ativa (knobs no Palco, /scene-grade)
        'dominant': [round(c, 3) for c in _state.get('dominant', (0.0, 0.0, 0.0))],
        'knobs': _read_knobs(),
        'audio_source': _state.get('audio_source') or _cfg['audio_source'],  # muda ao vivo via set_input
        'audio_media': os.path.relpath(_state['audio_media'], _media_dir()).replace(os.sep, '/')
                       if _state.get('audio_media') else '',   # video 🔊 da mesa no lugar do PulseAudio
        'video_mode': _state.get('video_label') or _cfg['video_mode'],
        # ids no formato das opcoes dos <select> — pro dash sincronizar os dropdowns entre abas
        'inputs': {'audio': _state.get('audio_source', ''), 'video': _state.get('video_id', '')},
        'output': _state.get('output', {}),   # geometria/fps da janela de saida (imagem sintetizada)
        'health': _state.get('health', {}),   # audio_age (s sem chunk) + stale (fontes paradas) — saude v2
        'output_fps': int(getattr(_tuning, 'OUTPUT_FPS', 60) or 60),   # escolhido no dash v2 (Saida)
        'screens': list(getattr(_tuning, 'SCREENS', None) or []),   # telas do palco (dash v2, Saida)
        'bands_hz': {'overlap': int(getattr(_tuning, 'HZ_OVERLAP', 0)),
                     'enabled': int(getattr(_tuning, 'BANDS_ENABLED', 1)),
                     'ranges': [list(x) for x in getattr(_tuning, 'FREQ_BAND_HZ', [])],
                     'names': _BAND_NAMES},
        # dinamica por faixa (popup "engrenagem" de cada faixa) — 3 listas de 8, ordem de bands_hz
        'band_tweaks': {'names': _BAND_NAMES,
                        'smoothing': list(getattr(_tuning, 'BAND_SMOOTHING', [])),
                        'attack': list(getattr(_tuning, 'BAND_ATTACK', [])),
                        'peak_decay': list(getattr(_tuning, 'BAND_PEAK_DECAY', []))},
        # canais por instrumento (lista de tamanho livre, ver tuning.CHANNELS) — paralelo as
        # bands_hz acima. levels/hits vem de state['chan'/'chan_hit'] (tamanho fixo _MAX_CHAN
        # no Python) cortado pro tamanho de CHANNELS de verdade.
        'channels': {
            'names': [c.get('name', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'srcs': [c.get('src', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'outputs': [c.get('output', '') for c in getattr(_tuning, 'CHANNELS', [])],
            'levels': [round(v, 3) for v in _state.get('chan', [])[:len(getattr(_tuning, 'CHANNELS', []))]],
            'hits': [round(v, 3) for v in _state.get('chan_hit', [])[:len(getattr(_tuning, 'CHANNELS', []))]],
        },
        # galeria de midia (aba Visuals): so o item ATIVO vai no stream (pro highlight seguir
        # tecla/dropdown); a lista em si o dash busca em /media (init + apos cada edicao) — assim
        # o objeto que um <input> de renomear referencia nao e trocado embaixo dele a 20 Hz.
        'media_active': _media_active_name(),
        # videos com rebate sendo pre-renderizados agora (file relativo a media/, igual MEDIA)
        'overlays': _current_overlays(),   # camadas vivas (sincroniza abas/janelas do dash)
        'bindings': _current_bindings(),  # shaders + forcas por fonte (sincroniza abas do dash)
        'selected': _current_selected(),  # fonte selecionada (lista de efeitos mostra a dela)
        'source_fit': dict(getattr(_tuning, 'SOURCE_FIT', None) or {}),   # camera/tela em 'fit'
        'pool': _current_pool(),          # disponiveis no set ativo (None = tudo)
        'scene': _active_scene_name(),   # set ativo (a lista vem de /scenes)
        'bounce_busy': [os.path.relpath(p, _media_dir()).replace(os.sep, '/')
                        for p in _state.get('bounce_busy', [])],
        'html_mtime': os.path.getmtime(_HTML),   # cliente recarrega a aba quando muda
        'html2_mtime': os.path.getmtime(_HTML2) if os.path.exists(_HTML2) else 0,   # idem, v2
    }


def _media_active_name():
    """nome do item de midia tocando agora ('' se o input e webcam/tela). O video_id colapsa
    pra 'media' generico, entao o nome vem do dict state['video']."""
    v = _state.get('video') or {}
    return v.get('name', '') if v.get('mode') == 'media' else ''


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # sem spam de request no stdout do synth

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/dash.html'):
            self._send(200, 'text/html; charset=utf-8', open(_HTML, 'rb').read())
        elif path in ('/v2', '/dash2.html'):
            self._send(200, 'text/html; charset=utf-8', open(_HTML2, 'rb').read())
        elif path in ('/favicon.png', '/favicon.ico'):  # navegador tambem sonda /favicon.ico
            try:
                self._send(200, 'image/png', open(_FAVICON, 'rb').read())
            except FileNotFoundError:
                self._send(404, 'text/plain', b'nope')
        elif path == '/knobs':
            self._send(200, 'application/json', json.dumps(KNOBS).encode())
        elif path == '/thumb':
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            jpg = thumb((q.get('src') or [''])[0])
            if jpg:
                self._send(200, 'image/jpeg', jpg)
            else:
                self._send(404, 'text/plain', b'sem imagem')
        elif path == '/frame':   # dash v2: pixels crus reduzidos (rgb24) pra canvas, ~15 fps — ver native _preview_frame
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fn = _cfg.get('on_frame')
            got = fn((q.get('which') or ['src'])[0], (q.get('src') or [''])[0]) if fn else None
            if not got:
                self._send(204, 'text/plain', b'')
            else:
                data, w, h = got
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-W', str(w))
                self.send_header('X-H', str(h))
                self.end_headers()
                self.wfile.write(data)
        elif path == '/inputs':
            fn = _cfg.get('on_inputs')
            self._send(200, 'application/json', json.dumps(fn() if fn else {}).encode())
        elif path == '/output-grade':
            self._send(200, 'application/json', json.dumps(
                {'grade': _current_output_grade(), 'defaults': output_grade_defaults()}).encode())
        elif path == '/shaders':  # glob aqui, nao no _payload de 20 Hz (igual /inputs)
            s = _active_shader_set()
            self._send(200, 'application/json', json.dumps(
                {'list': _list_shaders(s), 'manifests': _shader_manifests(_list_shaders(s)),
                 'fxDefaults': _shader_manifests(_list_shaders(s), defaults=True),
                 'keys': _read_keys_for('SHADER_KEYS', s),
                 'set': s, 'sets': _list_shader_sets()}).encode())
        elif path == '/media':
            s = _active_media_set()
            self._send(200, 'application/json', json.dumps(
                {'list': _read_media(s), 'keys': _read_keys_for('MEDIA_KEYS', s),
                 'current': _media_active_name(), 'overlays': _current_overlays(),
                 'set': s, 'sets': _list_media_sets()}).encode())
        elif path == '/transitions':
            self._send(200, 'application/json', json.dumps(_transitions_payload()).encode())
        elif path == '/scenes':
            self._send(200, 'application/json', json.dumps(_scenes_payload()).encode())
        elif path == '/events':
            self._sse()
        else:
            self._send(404, 'text/plain', b'nope')

    def _sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        try:
            # `self.server is _cfg['srv']` deixa de bater quando um hot-reload troca o servidor
            # -> este loop sai, o EventSource do browser cai e reconecta sozinho no novo.
            while _cfg['is_running']() and self.server is _cfg.get('srv'):
                self.wfile.write(b'data: ' + json.dumps(_payload()).encode() + b'\n\n')
                self.wfile.flush()
                time.sleep(1 / 30)  # 30 Hz — audio novo a ~43 Hz; o dash v2 interpola a 60 fps
        except (BrokenPipeError, ConnectionResetError):
            pass  # aba fechou

    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length', 0))
        if path == '/media-add':  # body = bytes do arquivo; ?name=<orig> — vai direto pro disco
            body = _Body(self.rfile, length)
            try:
                q = urllib.parse.parse_qs(self.path.partition('?')[2])
                entry = add_media(q.get('name', [''])[0], stream=body, length=length)
                _pool_add('sources', entry['file'])
                self._send(200, 'application/json', json.dumps(entry).encode())
            except (KeyError, ValueError, TypeError, OSError) as e:
                body.drain()   # recusou antes de ler tudo: esvazia o socket pro navegador ver o erro
                self._send(400, 'text/plain', str(e).encode())
            return
        raw = self.rfile.read(length)
        if path == '/bands':
            try:
                b = json.loads(raw.decode())
                out = set_band_ranges(b.get('overlap'), b['ranges'], enabled=b.get('enabled'))
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/tweaks':
            try:
                b = json.loads(raw.decode())
                out = set_band_tweaks(b)
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/channels':
            try:
                b = json.loads(raw.decode())
                out = set_channels(b['channels'])
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/new-shader':
            try:
                b = json.loads(raw.decode())
                rel = new_shader(b['name'])
                _pool_add('shaders', rel)
                self._send(200, 'application/json', json.dumps({'shader': rel}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/rename-shader':
            try:
                b = json.loads(raw.decode())
                rel = rename_shader(b['name'], b['newname'])
                self._send(200, 'application/json', json.dumps({'shader': rel}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/delete-shader':
            try:
                b = json.loads(raw.decode())
                delete_shader(b['name'])
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/shader-key':
            try:
                b = json.loads(raw.decode())
                out = bind_shader_key(b['name'], b.get('key', ''))
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path in ('/transition-default', '/new-transition', '/rename-transition', '/delete-transition'):
            try:
                b = json.loads(raw.decode())
                if path == '/transition-default':
                    set_transition_default(b['name'])
                elif path == '/new-transition':
                    new_transition(b['name'])
                elif path == '/rename-transition':
                    rename_transition(b['name'], b['newname'])
                else:
                    delete_transition(b['name'])
                self._send(200, 'application/json', json.dumps(_transitions_payload()).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path in ('/shader-set', '/shader-set-new', '/shader-set-del',
                    '/media-set', '/media-set-new', '/media-set-del'):
            try:
                name = json.loads(raw.decode())['name']
                fn = {'/shader-set': set_active_shader_set, '/shader-set-new': create_shader_set,
                      '/shader-set-del': delete_shader_set, '/media-set': set_active_media_set,
                      '/media-set-new': create_media_set, '/media-set-del': delete_media_set}[path]
                out = fn(name)
                # trocar/apagar o set de midia ativo pode mudar o que toca -> reaplica
                if path.startswith('/media-set') and _cfg.get('on_set_input') \
                        and (_state.get('video') or {}).get('mode') == 'media':
                    _cfg['on_set_input']('video', 'media')
                self._send(200, 'application/json', json.dumps({'name': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/media':  # reescreve os itens do set ativo em MEDIA (fit toggle, rename)
            try:
                b = json.loads(raw.decode())
                out = set_media(b['media'], b.get('set'))
                # se o item TOCANDO agora mudou (fit sobretudo), reaplica pro ffmpeg respawnar —
                # set_media so mexe no tuning.py, nao no state['video'] que o video_thread observa
                fn = _cfg.get('on_set_input')
                if fn and (_state.get('video') or {}).get('mode') == 'media':
                    fn('video', 'media')
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/media-del':
            try:
                b = json.loads(raw.decode())
                delete_media(b['name'], b.get('set'))
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/media-key':
            try:
                b = json.loads(raw.decode())
                out = bind_media_key(b['name'], b.get('key', ''))
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/overlays':  # {overlays: [{file, opacity}], save: bool} — ao vivo; save grava
            try:
                b = json.loads(raw.decode())
                out = set_overlays(b['overlays'], save=bool(b.get('save')))
                if b.get('save'):
                    save_active_scene()
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path in ('/scene', '/scene-new', '/scene-rename', '/scene-del', '/scene-key', '/scene-transition'):
            try:
                b = json.loads(raw.decode())
                if path == '/scene':
                    request_scene(b['name'])
                elif path == '/scene-new':
                    create_scene(b['name'])
                elif path == '/scene-rename':
                    rename_scene(b['name'], b['newname'])
                elif path == '/scene-del':
                    delete_scene(b['name'])
                elif path == '/scene-key':
                    set_scene_key(b['name'], b.get('key', ''))
                else:
                    set_scene_transition(b['name'], b.get('transition', ''))
                self._send(200, 'application/json', json.dumps(_scenes_payload()).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/bindings':  # {bindings: {fonte: {shaders, fx}}, save: bool} — igual /overlays
            try:
                b = json.loads(raw.decode())
                out = set_bindings(b['bindings'], save=bool(b.get('save')))
                if b.get('save'):
                    save_active_scene()
                self._send(200, 'application/json', json.dumps(out).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/pool':  # {pool: {sources?: [...], shaders?: [...]}} — disponiveis no set ativo
            try:
                out = set_pool(json.loads(raw.decode())['pool'])
                self._send(200, 'application/json', json.dumps({'pool': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/source-fit':  # {src: 'webcam:..' | 'screen:..', fit: 'fill' | 'fit'}
            try:
                b = json.loads(raw.decode())
                out = set_source_fit(b['src'], b.get('fit'))
                self._send(200, 'application/json', json.dumps({'fit': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/select':  # {src: chave da fonte} — so a selecao (lista de efeitos + captura)
            try:
                out = select_source(json.loads(raw.decode())['src'])
                save_active_scene()
                self._send(200, 'application/json', json.dumps({'selected': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/scene-grade':  # {grade: {on, fx: {knob: 0..1}}, save}
            try:
                b = json.loads(raw.decode())
                out = set_scene_grade(b['grade'], save=bool(b.get('save', True)))
                self._send(200, 'application/json', json.dumps({'grade': out}).encode())
            except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/output-grade':  # {grade: {on, test, fx: {knob: 0..1}}, save}
            try:
                b = json.loads(raw.decode())
                out = set_output_grade(b['grade'], save=bool(b.get('save', True)))
                self._send(200, 'application/json', json.dumps({'grade': out}).encode())
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/screens':  # {screens: [{name, x, y, w, h, pw, ph}], save: bool}
            try:
                b = json.loads(raw.decode())
                out = set_screens(b['screens'], save=bool(b.get('save', True)))
                self._send(200, 'application/json', json.dumps({'screens': out}).encode())
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/output-fps':  # {fps: 24|30|50|60}
            try:
                out = set_output_fps(json.loads(raw.decode())['fps'])
                self._send(200, 'application/json', json.dumps({'fps': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/out-analysis':
            try:
                b = json.loads(raw.decode())
                out = set_out_analysis(b.get('enabled'))
                self._send(200, 'application/json', json.dumps({'enabled': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/quit':   # 3x Esc no dash = Alt+F4 em tudo: SIGTERM no proprio processo -> o
            # handle_sigterm do native zera running (sai pelo fluxo normal) e o atexit fecha o Brave
            self._send(200, 'application/json', b'{"ok":true}')
            threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGTERM)).start()
            return
        if path == '/output':
            fn = _cfg.get('on_set_output')
            try:
                fn(json.loads(raw.decode()))
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        q = urllib.parse.parse_qs(raw.decode())
        if path == '/knob':
            try:
                v = set_knob(q['name'][0], q['value'][0])
                self._send(200, 'application/json', json.dumps({'value': v}).encode())
            except (KeyError, ValueError, IndexError) as e:
                self._send(400, 'text/plain', str(e).encode())
        elif path == '/input':
            fn = _cfg.get('on_set_input')
            try:
                fn(q['kind'][0], q['id'][0])
                self._send(200, 'application/json', b'{"ok":true}')
            except (KeyError, ValueError, IndexError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
        else:
            self._send(404, 'text/plain', b'nope')


def stop():
    """Derruba o servidor atual (usado antes de um hot-reload). shutdown() precisa vir de
    outro thread que nao o do serve_forever — e o caso: quem chama e o audio_thread."""
    srv = _cfg.pop('srv', None)
    if srv is not None:
        srv.shutdown()
        srv.server_close()


def _migrate_default_to_folder(tuning_path=None):
    """One-shot idempotente: "default" era .frag/arquivo solto em presets/ e media/; virou
    pasta real (presets/default/, media/default/) como qualquer set. Move os soltos pra dentro
    e reescreve os caminhos em tuning.py (SHADER, SHADER_KEYS["default"], MEDIA)."""
    path = tuning_path or _cfg['tuning_path']
    sh_def = os.path.join(_SHADERS, 'presets', 'default')
    md_def = os.path.join(_MEDIA, 'default')
    os.makedirs(sh_def, exist_ok=True)
    os.makedirs(md_def, exist_ok=True)
    for f in glob.glob(os.path.join(_SHADERS, 'presets', '*.frag')):      # glob nao entra em subdir
        dest = os.path.join(sh_def, os.path.basename(f))
        os.remove(f) if os.path.exists(dest) else os.rename(f, dest)
    for f in glob.glob(os.path.join(_MEDIA, '*')):
        if os.path.isfile(f):
            dest = os.path.join(md_def, os.path.basename(f))
            os.remove(f) if os.path.exists(dest) else os.rename(f, dest)
    if _tuning is None:
        return
    cur = getattr(_tuning, 'SHADER', '')
    if re.fullmatch(r'presets/[^/]+\.frag', cur):
        set_shader('presets/default/' + os.path.basename(cur), path)
    keys = _read_keys('SHADER_KEYS')
    dflt = keys.get('default') or {}
    if any(re.fullmatch(r'presets/[^/]+\.frag', t) for t in dflt):
        keys['default'] = {('presets/default/' + os.path.basename(t)
                            if re.fullmatch(r'presets/[^/]+\.frag', t) else t): k
                           for t, k in dflt.items()}
        _write_keys('SHADER_KEYS', keys, path)
    media = [dict(m) for m in getattr(_tuning, 'MEDIA', [])]
    if any(m.get('file') and '/' not in str(m['file']).lstrip('/') for m in media):
        for m in media:
            f = str(m.get('file', '')).replace('\\', '/').lstrip('/')
            if f and '/' not in f:
                m['file'] = 'default/' + f
        _write_media(media, path)


def _migrate_to_scenes(tuning_path=None, media_dir=None, shaders_dir=None):
    """One-shot (roda se o tuning.py ainda nao tem SCENES): 'set' deixou de ser PASTA e virou
    CENA. 1) junta as pastas media/<x>/ e presets/<x>/ na default (Biblioteca unica; mesmo nome
    de arquivo = mesmo item, fica 1; .frag de mesmo nome com outro conteudo ganha sufixo -<x>) e
    reescreve MEDIA / SHADER / camadas; 2) cria os sets: 'default' = estado atual e um set por
    pasta de midia antiga (fonte = a midia tocando se era dela, senao a 1a dela)."""
    if _tuning is None or hasattr(_tuning, 'SCENES'):
        return
    path = tuning_path or _cfg['tuning_path']
    md = _media_dir(media_dir)
    sh = shaders_dir or _SHADERS
    was_set = getattr(_tuning, 'MEDIA_SET', 'default')   # antes de voltar pro 'default' la embaixo
    # --- midia
    folders = sorted(d for d in os.listdir(md) if os.path.isdir(os.path.join(md, d)) and d != 'default') \
        if os.path.isdir(md) else []
    os.makedirs(os.path.join(md, 'default'), exist_ok=True)
    fmap = {}                                       # file antigo -> file novo
    for d in folders:
        for f in sorted(os.listdir(os.path.join(md, d))):
            src = os.path.join(md, d, f)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(md, 'default', f)
            os.remove(src) if os.path.exists(dest) else os.rename(src, dest)
            fmap[f'{d}/{f}'] = f'default/{f}'
        shutil.rmtree(os.path.join(md, d), ignore_errors=True)
    old_media = [dict(m) for m in getattr(_tuning, 'MEDIA', [])]
    new_media, by_file, nmap, taken = [], {}, {}, set()
    folder_first = {}                               # pasta antiga -> nome (novo) da 1a midia dela
    for m in old_media:
        f = str(m.get('file', '')).replace('\\', '/').lstrip('/')
        nf = fmap.get(f, f)
        folder = f.split('/')[0] if '/' in f else 'default'
        if nf in by_file:                           # duplicata: vira o item que ja existe
            nmap[m.get('name', '')] = by_file[nf]['name']
        else:
            nm = base = str(m.get('name', '')) or os.path.splitext(os.path.basename(nf))[0]
            i = 2
            while nm in taken:
                nm, i = f'{base}-{i}', i + 1
            taken.add(nm)
            nmap[m.get('name', '')] = nm
            by_file[nf] = dict(m, name=nm, file=nf)
            new_media.append(by_file[nf])
        folder_first.setdefault(folder, by_file[nf]['name'])
    if fmap or len(new_media) != len(old_media):
        _write_media(new_media, path)
    # --- shaders
    pdir = os.path.join(sh, 'presets')
    smap = {}
    for d in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        if d == 'default' or not os.path.isdir(os.path.join(pdir, d)):
            continue
        os.makedirs(os.path.join(pdir, 'default'), exist_ok=True)
        for f in sorted(glob.glob(os.path.join(pdir, d, '*.frag'))):
            b = os.path.basename(f)
            dest = os.path.join(pdir, 'default', b)
            if os.path.exists(dest) and open(dest).read() == open(f).read():
                os.remove(f)
            else:
                if os.path.exists(dest):
                    b = f'{os.path.splitext(b)[0]}-{d}.frag'
                    dest = os.path.join(pdir, 'default', b)
                os.rename(f, dest)
            smap[f'presets/{d}/{os.path.basename(f)}'] = f'presets/default/{b}'
        shutil.rmtree(os.path.join(pdir, d), ignore_errors=True)
    if getattr(_tuning, 'SHADER', '') in smap:
        set_shader(smap[_tuning.SHADER], path)
    _remap_overlays(fmap, path)
    _remap_shader_layers(smap, path)
    for setter, var in ((set_active_media_set, 'MEDIA_SET'), (set_active_shader_set, 'SHADER_SET')):
        if getattr(_tuning, var, 'default') != 'default':
            try:
                setter('default', path)
            except (KeyError, ValueError):
                pass
    # --- sets
    v = (_state or {}).get('video') or {}
    main = 'media:' + nmap.get(v['name'], v['name']) if v.get('mode') == 'media' and v.get('name') \
        else ((_state or {}).get('video_id') or 'webcam:/dev/video0')
    old = {'overlays': _current_overlays(), 'shader': getattr(_tuning, 'SHADER', 'image.frag'),
           'shader_layers': _current_shader_layers(),
           'fx': {str(k): round(float(x), 4) for k, x in ((_state or {}).get('fx') or {}).items()}}
    scenes = [_upgrade_scene({'name': 'default', 'key': '', 'transition': '', 'video': main, **old})]
    for d in folders:
        vid = main if d == was_set and main.startswith('media:') else \
            ('media:' + folder_first[d] if d in folder_first else main)
        scenes.append(_upgrade_scene({'name': d, 'key': '', 'transition': '', 'video': vid, **old}))
    active = was_set if was_set in folders else 'default'
    _write_scenes(scenes, active=active, tuning_path=path)
    sc0 = next(sc for sc in scenes if sc['name'] == active)
    set_overlays(sc0['sources'], save=True, tuning_path=path)      # o vivo = o set ativo
    set_bindings(sc0['bindings'], save=True, tuning_path=path)
    print(f'dash: sets -> cenas ({", ".join(sc["name"] for sc in scenes)}); ativo: {active}')


def start(state, tuning_mod, tuning_path, is_running, audio_source='', video_mode='',
          port=8765, open_browser=True, on_inputs=None, on_set_input=None, on_set_output=None,
          on_thumb=None, on_frame=None):
    """Sobe o servidor num thread daemon. Degrada sem travar o synth se a porta estiver ocupada.
    open_browser=False num hot-reload pra nao reabrir as abas. on_inputs/on_set_input = callbacks
    do native_synth pra listar/trocar entrada de audio e video. on_set_output = pedido de troca
    da janela de SAIDA (monitor/tela cheia/dimensao — barra "saida" no topo do dash). on_thumb(chave)
    = frame atual de uma fonte viva (bytes rgb24, w, h) | None, pra miniatura da mesa."""
    global _state, _tuning
    _state, _tuning = state, tuning_mod
    _cfg.update(is_running=is_running, audio_source=audio_source, video_mode=video_mode,
                tuning_path=tuning_path, on_inputs=on_inputs, on_set_input=on_set_input,
                on_set_output=on_set_output, on_thumb=on_thumb, on_frame=on_frame)
    try:
        _migrate_default_to_folder()
    except (OSError, KeyError, ValueError) as e:
        print(f'dash: migracao default->pasta pulada ({e})')
    try:
        _migrate_to_scenes()
    except (OSError, KeyError, ValueError) as e:
        print(f'dash: migracao pastas->sets pulada ({e})')
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
    except OSError as e:
        print(f'dash desligado (porta {port}: {e})')
        return
    srv.daemon_threads = True
    _cfg['srv'] = srv  # o handler do SSE compara com isso pra sair quando um reload troca o srv
    # poll_interval curto: stop() (shutdown) volta em ~0.1s em vez de 0.5s -> hot-reload sem glitch
    threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.1), daemon=True).start()
    url = f'http://127.0.0.1:{port}'
    print(f'dash: {url}  (tabs Audio/Image no header, ou ?panel=audio | ?panel=image p/ popup)')
    if open_browser:
        _open_dash_window(url + '/v2')   # v2 (palco) e' o dash principal; v1 segue em /


# navegadores com --app/--user-data-dir (familia Chromium), na ordem de preferencia
_APP_BROWSERS = ('brave-browser', 'google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge')


def _no_translate(prof):
    """Desliga a oferta de traducao no perfil do dash (o Brave ignora --disable-features=Translate
    e o lang/notranslate da pagina). Grava no Preferences ANTES de abrir: com o navegador aberto
    ele sobrescreve o arquivo."""
    path = os.path.join(prof, 'Default', 'Preferences')
    try:
        with open(path) as f:
            prefs = json.load(f)
    except (OSError, ValueError):
        prefs = {}
    if prefs.get('translate', {}).get('enabled') is False:
        return
    prefs.setdefault('translate', {})['enabled'] = False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(prefs, f)
    except OSError:
        pass


def _raise_output_over_dash():
    """O Brave aparece ~1-2 s DEPOIS da saida e rouba o foco. Espera a janela do dash surgir e
    traz a saida (WM_CLASS prisma.prisma; o dash e' 127.0.0.1__v2.prisma) pra frente: dash fica
    de fundo, no monitor onde ja' abriu. Saida em tela cheia + com foco = barra escondida."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < 15:
        try:
            out = subprocess.run(['wmctrl', '-lx'], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            return
        if any('.prisma ' in l and not l.split()[2].startswith('prisma.') for l in out.splitlines()):
            time.sleep(0.6)   # deixa o Brave terminar de entrar em tela cheia
            subprocess.run(['wmctrl', '-x', '-a', 'prisma.prisma'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return
        time.sleep(0.25)


def _open_dash_window(url):
    """Abre o dash numa janela PROPRIA (--app, perfil separado = processo separado) e a fecha ao
    sair do programa: aba aberta pelo SO o navegador nao deixa o window.close() do JS fechar.
    O perfil fica em ~/.config/prisma/dash-browser (localStorage/permissao de MIDI persistem la).
    atexit (e nao _cfg) porque o hot-reload troca este modulo. Sem Chromium -> aba comum.
    PRISMA_NO_BROWSER=1 = nao abre nada (testes do app inteiro)."""
    if os.environ.get('PRISMA_NO_BROWSER'):
        return
    exe = next((shutil.which(b) for b in _APP_BROWSERS if shutil.which(b)), None)
    if exe:
        prof = os.path.join(os.path.expanduser('~'), '.config', 'prisma', 'dash-browser')
        try:
            os.makedirs(prof, exist_ok=True)
            _no_translate(prof)
            # --kiosk = tela cheia SEM o balao "aperte Esc pra sair" (o --start-fullscreen mostra);
            # sai com Alt+F4 (ou fechando o prisma). --class=prisma = mesmo WM_CLASS da janela de
            # saida (SDL_VIDEO_X11_WMCLASS no native) -> as duas empilham como UM app na barra
            p = subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + prof, '--kiosk', '--class=prisma',
                                  '--disable-features=Translate', '--no-first-run',
                                  '--no-default-browser-check'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)   # grupo proprio: mata o wrapper e os filhos
        except OSError:
            pass
        else:
            def _close():
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
            atexit.register(_close)
            threading.Thread(target=_raise_output_over_dash, daemon=True).start()
            return
    try:  # uma aba so; audio/image trocam por tab no header (botoes de popup continuam disponiveis)
        webbrowser.open(url, new=2)
    except webbrowser.Error:
        pass


if __name__ == '__main__':  # self-check do parser de linha (roda: python dash_server.py)
    import tempfile
    p = tempfile.mktemp(suffix='.py')
    open(p, 'w').write('KICK_THRESHOLD = 1.5      # grave cru passa X vezes a media\n'
                       'MID_TREBLE_HZ = 4000\n')
    assert set_knob('KICK_THRESHOLD', 2.0, p) == 2.0
    assert _norm_overlays([{'file': 'a.png'}, {'file': 'a.png', 'dup': 2}, {'file': 'a.png'}]) == \
        [{'file': 'a.png', 'opacity': 1.0}, {'file': 'a.png', 'opacity': 1.0, 'dup': 2}], 'mesma fonte 2x (dup)'
    assert _base_key('d/a.mp4#2') == 'd/a.mp4' and _base_key('screen:HDMI#x') == 'screen:HDMI#x'
    assert _remap_bindings({'d/a.png#2': {'shaders': []}}, files={'d/a.png': 'd/b.png'}) == \
        {'d/b.png#2': {'shaders': [], 'fx': {}}}
    two = _norm_bindings({'cam': {'shaders': [{'file': 'x.frag', 'fx': {'a': 0.2}}, {'file': 'x.frag'}]}})
    assert [o.get('fx') for o in two['cam']['shaders']] == [{'a': 0.2}, None], 'mesmo shader 2x na pilha'
    assert _norm_overlays([{'file': 'a.png', 'opacity': 1, 'off': True}, {'file': 'b.png', 'off': 0}]) == \
        [{'file': 'a.png', 'opacity': 1.0, 'off': 1}, {'file': 'b.png', 'opacity': 1.0}], 'off (desligada) se perdeu'
    assert [o.get('audio') for o in _norm_overlays([{'file': 'a.mp4', 'audio': 1}, {'file': 'b.mp4', 'audio': True},
                                                   {'file': 'c.mp4'}])] == [1, None, None], '🔊 e so 1 por mesa'
    txt = open(p).read()
    assert 'KICK_THRESHOLD = 2.0 ' in txt, txt
    assert '# grave cru passa X vezes a media' in txt, 'comentario perdido'
    assert set_knob('KICK_THRESHOLD', 99, p) == _SPEC['KICK_THRESHOLD']['max'], 'sem clamp'
    set_knob('MID_TREBLE_HZ', 3000.4, p)
    assert 'MID_TREBLE_HZ = 3000\n' in open(p).read(), 'int knob deve ficar inteiro'
    try:
        set_knob('NOPE', 1, p)
        assert False, 'aceitou nome desconhecido'
    except KeyError:
        pass

    # --- band ranges ---
    default = [[20, 250], [250, 500], [500, 2000], [2000, 4000],
              [4000, 6000], [6000, 10000], [10000, 16000], [16000, 20000]]
    # crossover: sem sobreposicao (empurra o lo do vizinho), mas mantem o buraco
    fixed = _clamp_ranges(0, [[20, 469], [90, 800]] + default[2:])
    assert fixed[0] == [20, 469], fixed                                  # respeitado
    assert fixed[1][0] == 469, fixed                                     # lo empurrado (nao invade)
    assert fixed[1] == [469, 800], fixed
    assert all(fixed[i][1] <= fixed[i + 1][0] for i in range(7)), fixed  # nao sobrepoe
    assert all(fixed[i][0] < fixed[i][1] for i in range(8)), fixed       # lo<hi
    gap = _clamp_ranges(0, [[20, 100], [300, 500]] + default[2:])
    assert gap[0] == [20, 100] and gap[1] == [300, 500], gap             # BURACO 100..300 preservado
    # faixas trocadas de lugar (Air no grave, Sub-bass no agudo): aceitas como vieram
    sw = [[20, 250] if i == 7 else [16000, 20000] if i == 0 else x for i, x in enumerate(default)]
    assert _clamp_ranges(0, sw) == sw, _clamp_ranges(0, sw)
    # overlap: mantem sobreposicao
    ov = _clamp_ranges(1, [[39, 469], [200, 500]] + default[2:])
    assert ov[0] == [39, 469] and ov[1] == [200, 500], ov
    # escrita no arquivo
    open(p, 'w').write('HZ_OVERLAP = 0\nBANDS_ENABLED = 1\nFREQ_BAND_HZ = [\n    [20, 250],  # Sub-bass\n]\n')
    out = set_band_ranges(1, [[39, 469], [200, 500]] + default[2:], p, enabled=0)
    txt = open(p).read()
    assert out['overlap'] == 1 and out['enabled'] == 0 and 'HZ_OVERLAP = 1' in txt, txt
    assert 'BANDS_ENABLED = 0' in txt, txt
    assert '[39, 469],  # Sub-bass' in txt and '[200, 500],  # Low-mid' in txt, txt
    assert txt.count('FREQ_BAND_HZ = [') == 1 and txt.rstrip().endswith(']'), txt
    out2 = set_band_ranges(1, default, p)  # enabled=None (default) -> nao mexe na linha
    assert 'enabled' not in out2 and 'BANDS_ENABLED = 0' in open(p).read(), out2

    # --- channels: lista de tamanho livre, sem slot fixo ---
    open(p, 'w').write('CHANNELS = [\n    {"name": "kick", "src": "", "output": ""},\n]\n')
    outc = set_channels([{'name': 'bumbo', 'src': 'alsa_input.foo.monitor', 'output': 'kick'}], p)
    txt = open(p).read()
    assert outc == [{'name': 'bumbo', 'src': 'alsa_input.foo.monitor', 'output': 'kick'}], outc
    assert '"bumbo"' in txt and '"alsa_input.foo.monitor"' in txt and '"output": "kick"' in txt, txt
    assert txt.count('CHANNELS = [') == 1 and txt.rstrip().endswith(']'), txt
    outc2 = set_channels([], p)  # lista vazia -> volta a nao ter canal nenhum, sem erro
    assert outc2 == [] and 'CHANNELS = [\n]' in open(p).read(), (outc2, open(p).read())
    outc3 = set_channels([{'name': 'a', 'src': '', 'output': ''}], p)  # reescreve de novo, sem sobra
    assert len(outc3) == 1, outc3

    # --- toggle Output Image ---
    open(p, 'w').write('OUT_ANALYSIS_ENABLED = 0\n')
    assert set_out_analysis(1, p) == 1
    assert 'OUT_ANALYSIS_ENABLED = 1' in open(p).read()
    assert set_out_analysis(0, p) == 0
    assert 'OUT_ANALYSIS_ENABLED = 0' in open(p).read()

    # --- shader select + potenciometros de efeito ---
    open(p, 'w').write('SHADER = "image.frag"\nFX = {\n}\n')
    assert set_shader('image.frag', p) == 'image.frag' and 'SHADER = "image.frag"' in open(p).read()
    try:
        set_shader('../tuning.py', p); assert False, 'aceitou path traversal / nome desconhecido'
    except KeyError:
        pass
    outf = set_fx({'grain': 0.5, 'wave': 2.0, 'vig': -1.0}, p)  # clamp 0..1
    assert outf == {'grain': 0.5, 'wave': 1.0, 'vig': 0.0}, outf
    txt = open(p).read()
    assert '"grain": 0.5' in txt and txt.count('FX = {') == 1 and txt.rstrip().endswith('}'), txt
    assert set_fx({}, p) == {} and 'FX = {\n}' in open(p).read()  # vazio -> bloco vazio, sem erro

    # --- new_shader: slug sanitizado, template, sem duplicar (dir temp) ---
    import shutil
    pd = tempfile.mkdtemp()
    assert new_shader('  My Cool FX!! ', p, pd) == 'presets/MyCoolFX.frag'
    assert '// fx: tint' in open(os.path.join(pd, 'MyCoolFX.frag')).read()
    assert new_shader('../../etc/x', p, pd) == 'presets/etcx.frag'  # traversal -> so o basename
    try:
        new_shader('MyCoolFX', p, pd); assert False, 'aceitou nome duplicado'
    except ValueError:
        pass
    try:
        new_shader('  !! ', p, pd); assert False, 'aceitou slug vazio'
    except ValueError:
        pass

    # --- rename / delete (dir temp, sem tocar SHADER/keys reais) ---
    assert rename_shader('presets/MyCoolFX.frag', ' novo nome ', p, pd) == 'presets/novonome.frag'
    assert os.path.isfile(os.path.join(pd, 'novonome.frag')) and not os.path.isfile(os.path.join(pd, 'MyCoolFX.frag'))
    try:
        rename_shader('presets/novonome.frag', 'etcx', p, pd); assert False, 'renomeou por cima de outro'
    except ValueError:
        pass
    try:
        rename_shader('image.frag', 'x', p, pd); assert False, 'deixou renomear a base'
    except ValueError:
        pass
    delete_shader('presets/etcx.frag', p, pd)
    assert not os.path.isfile(os.path.join(pd, 'etcx.frag'))
    try:
        delete_shader('image.frag', p, pd); assert False, 'deixou apagar a base'
    except ValueError:
        pass
    shutil.rmtree(pd)

    # --- *_KEYS por set: {set: {alvo: tecla}}, dedup POR set, migra flat antigo ---
    import types as _t
    globals()['_tuning'] = _t.SimpleNamespace(SHADER_KEYS={})
    open(p, 'w').write('SHADER_KEYS = {\n}\n')
    k = _write_keys('SHADER_KEYS', {'default': {'image.frag': 'J', 'a': 'j', 'b': 'k'},
                                    'show1': {'c': 'j'}}, p)
    assert k == {'default': {'image.frag': 'j', 'b': 'k'}, 'show1': {'c': 'j'}}, k  # 'a'='j' dup DENTRO do default; 'j' de novo ok em show1
    _tuning.SHADER_KEYS = k
    assert _read_keys_for('SHADER_KEYS', 'show1') == {'c': 'j'}
    # migracao: um dict flat antigo vira {"default": flat}
    _tuning.SHADER_KEYS = {'image.frag': '1', 'x': '2'}
    assert _read_keys('SHADER_KEYS') == {'default': {'image.frag': '1', 'x': '2'}}
    txt = open(p).read()
    assert txt.count('SHADER_KEYS = {') == 1 and '"show1"' in txt and txt.rstrip().endswith('}'), txt
    globals()['_tuning'] = None

    # --- band tweaks: 3 listas de 8, clamp, lista ausente intocada, alinhamento+comentario ---
    open(p, 'w').write(
        'BAND_SMOOTHING  = [0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95]  # RELEASE por faixa\n'
        'BAND_ATTACK     = [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4]\n'
        'BAND_PEAK_DECAY = [0.999, 0.999, 0.999, 0.999, 0.999, 0.999, 0.999, 0.999]\n')
    outt = set_band_tweaks({'BAND_SMOOTHING': [2.0] + [0.7] * 7, 'BAND_ATTACK': [0.5] * 8}, p)
    assert outt['BAND_SMOOTHING'][0] == 0.99 and outt['BAND_SMOOTHING'][1] == 0.7, outt   # clamp no teto
    txt = open(p).read()
    assert 'BAND_SMOOTHING  = [0.99, 0.7,' in txt and '# RELEASE por faixa' in txt, txt   # alinhamento + comentario
    assert 'BAND_ATTACK     = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]' in txt, txt
    assert 'BAND_PEAK_DECAY = [0.999,' in txt, 'lista ausente do dict foi mexida'
    try:
        set_band_tweaks({'BAND_ATTACK': [0.5] * 3}, p); assert False, 'aceitou != 8 valores'
    except ValueError:
        pass

    # --- "default" como PASTA real: _migrate_default_to_folder (idempotente) + wipe do default ---
    import types
    _SH0, _MD0 = _SHADERS, _MEDIA
    shd, mdd = tempfile.mkdtemp(), tempfile.mkdtemp()
    globals()['_SHADERS'], globals()['_MEDIA'] = shd, mdd
    os.makedirs(os.path.join(shd, 'presets'))
    open(os.path.join(shd, 'image.frag'), 'w').write('void main(){}')
    open(os.path.join(shd, 'presets', 'Loose.frag'), 'w').write('// fx: a\n')   # solto = era "default"
    open(os.path.join(mdd, 'pic.png'), 'wb').write(b'x')                        # solto = era "default"
    open(p, 'w').write('SHADER = "presets/Loose.frag"\nSHADER_SET = "default"\n'
                       'SHADER_KEYS = {\n    "default": {\n        "presets/Loose.frag": "2"\n    }\n}\n'
                       'MEDIA = [\n    {"name": "pic", "file": "pic.png", "kind": "image", "fit": "fill"},\n]\n'
                       'MEDIA_SET = "default"\nMEDIA_KEYS = {\n}\n')
    _tuning = types.SimpleNamespace()
    def _sync():
        ns = {}
        exec(compile(open(p).read(), p, 'exec'), ns)
        for a in ('SHADER', 'SHADER_SET', 'SHADER_KEYS', 'MEDIA', 'MEDIA_SET', 'MEDIA_KEYS'):
            if a in ns:
                setattr(_tuning, a, ns[a])
    _sync(); globals()['_tuning'] = _tuning

    _migrate_default_to_folder(p); _sync()
    assert os.path.isfile(os.path.join(shd, 'presets', 'default', 'Loose.frag')), 'shader solto nao migrou'
    assert not os.path.isfile(os.path.join(shd, 'presets', 'Loose.frag'))
    assert os.path.isfile(os.path.join(mdd, 'default', 'pic.png')), 'midia solta nao migrou'
    assert _tuning.SHADER == 'presets/default/Loose.frag', _tuning.SHADER
    assert _read_keys('SHADER_KEYS')['default'] == {'presets/default/Loose.frag': '2'}, _tuning.SHADER_KEYS
    assert _tuning.MEDIA[0]['file'] == 'default/pic.png', _tuning.MEDIA
    _migrate_default_to_folder(p)   # idempotente: 2a vez nao muda nada nem explode
    assert _tuning.SHADER == 'presets/default/Loose.frag'

    open(os.path.join(shd, 'presets', 'default', 'S.frag'), 'w').write('// x\n')
    delete_shader_set('default', p); _sync()          # esvazia; a pasta fica, segue ativo
    assert os.path.isdir(os.path.join(shd, 'presets', 'default'))
    assert not glob.glob(os.path.join(shd, 'presets', 'default', '*.frag')), 'default nao esvaziou'
    assert _tuning.SHADER == 'image.frag' and _tuning.SHADER_SET == 'default', _tuning.SHADER

    globals()['_SHADERS'], globals()['_MEDIA'] = _SH0, _MD0
    shutil.rmtree(shd); shutil.rmtree(mdd); globals()['_tuning'] = None

    # --- galeria de midia com SETS: add / set_media (fit) / key / delete-nomeado / wipe-default ---
    _tuning = types.SimpleNamespace(MEDIA=[], MEDIA_KEYS={}, MEDIA_SET='default')
    def _sync():
        ns = {}
        exec(compile(open(p).read(), p, 'exec'), ns)
        for a in ('MEDIA', 'MEDIA_KEYS', 'MEDIA_SET'):
            if a in ns:
                setattr(_tuning, a, ns[a])
    globals()['_tuning'] = _tuning
    md = tempfile.mkdtemp()   # faz as vezes de media/
    open(p, 'w').write('MEDIA = [\n]\nMEDIA_SET = "default"\nMEDIA_KEYS = {\n}\n')
    e1 = add_media('Minha Foto.PNG', data=b'x', tuning_path=p, media_dir=md); _sync()
    assert e1 == {'name': 'MinhaFoto', 'file': 'default/MinhaFoto.png', 'kind': 'image', 'fit': 'fill',
                  'transition': '', 'set': 'default'}, e1
    assert os.path.isfile(os.path.join(md, 'default', 'MinhaFoto.png'))   # default agora e' pasta
    add_media('clip.mp4', data=b'y', tuning_path=p, media_dir=md); _sync()
    import io   # upload em stream: blocos, sem sobrar .part; stream curto = erro e nada gravado
    big = os.urandom(_MEDIA_CHUNK * 2 + 7)
    add_media('big.webm', stream=_Body(io.BytesIO(big), len(big)), length=len(big), tuning_path=p, media_dir=md); _sync()
    assert open(os.path.join(md, 'default', 'big.webm'), 'rb').read() == big
    try:
        add_media('cut.webm', stream=_Body(io.BytesIO(b'abc'), 10), length=10, tuning_path=p, media_dir=md)
        assert False, 'stream curto'
    except ValueError:
        pass
    assert not [f for f in os.listdir(os.path.join(md, 'default')) if f.startswith('cut')]
    delete_media('big', tuning_path=p, media_dir=md); _sync()
    assert len(_read_media('default', md)) == 2 and _read_media('Show1', md) == []
    try:
        add_media('x.txt', data=b'', tuning_path=p, media_dir=md); assert False, 'extensao ruim'
    except ValueError:
        pass
    # novo set = subpasta; ativa; adiciona nela -> arquivo em md/Show1/, nao mistura com default
    assert create_media_set('  Show 1 ', md) == 'Show1' and os.path.isdir(os.path.join(md, 'Show1'))
    assert _list_media_sets(md) == ['default', 'Show1']
    set_active_media_set('Show1', p, md); _sync()
    add_media('other.png', data=b'z', tuning_path=p, media_dir=md); _sync()
    assert os.path.isfile(os.path.join(md, 'Show1', 'other.png'))
    assert [m['name'] for m in _read_media('Show1', md)] == ['other']
    assert len(_read_media('default', md)) == 2, 'add vazou pro default'
    # set_media casa por 'file'; renomear (name novo, file antigo) move o arquivo tambem
    out = set_media([{'name': 'outro', 'file': 'Show1/other.png', 'fit': 'fit', 'transition': 'wipe.glsl'}], None, p, md); _sync()
    assert out[0] == {'name': 'outro', 'file': 'Show1/outro.png', 'kind': 'image', 'fit': 'fit',
                      'transition': 'wipe.glsl', 'set': 'Show1'}, out
    assert os.path.isfile(os.path.join(md, 'Show1', 'outro.png')) and len(_read_media('default', md)) == 2
    # rebate: so em video, liga/desliga, e o tuning.py gravado continua sendo Python valido
    add_media('clip.mov', data=b'v', tuning_path=p, media_dir=md); _sync()
    out = set_media([{'name': 'outro', 'file': 'Show1/outro.png', 'bounce': True},
                     {'name': 'clip', 'file': 'Show1/clip.mov', 'bounce': True}], None, p, md); _sync()
    assert 'bounce' not in out[0] and out[1]['bounce'], out
    ns = {}; exec(open(p).read(), ns)
    assert [m.get('bounce') for m in ns['MEDIA'] if m['file'].startswith('Show1/')] == [None, 1], ns['MEDIA']
    assert _read_media('Show1', md)[1]['bounce'] is True
    set_media([{'name': 'outro', 'file': 'Show1/outro.png'}, {'name': 'clip', 'file': 'Show1/clip.mov'}], None, p, md); _sync()
    assert all('bounce' not in m for m in _read_media('Show1', md))
    # camadas: normaliza (clamp, sem duplicata), grava (acrescenta o bloco se o tuning.py e antigo),
    # segue o arquivo ao renomear e some ao apagar
    assert 'OVERLAYS' not in open(p).read()
    set_overlays([{'file': 'Show1/outro.png', 'opacity': 2}, {'file': 'Show1/clip.mov', 'opacity': 0.3},
                  {'file': 'Show1/outro.png'}], save=True, tuning_path=p); _sync()
    ns = {}; exec(open(p).read(), ns)
    assert ns['OVERLAYS'] == [{'file': 'Show1/outro.png', 'opacity': 1.0},
                              {'file': 'Show1/clip.mov', 'opacity': 0.3}], ns['OVERLAYS']
    set_overlays([{'file': 'Show1/clip.mov', 'opacity': 0.5}], tuning_path=p)   # so ao vivo
    assert _state['overlays'] == [{'file': 'Show1/clip.mov', 'opacity': 0.5}]
    assert 'Show1/outro.png' in open(p).read(), 'ao vivo nao devia gravar'
    set_overlays(ns['OVERLAYS'], save=True, tuning_path=p); _sync()
    set_media([{'name': 'outro', 'file': 'Show1/outro.png'}, {'name': 'clip2', 'file': 'Show1/clip.mov'}], None, p, md); _sync()
    assert [o['file'] for o in _current_overlays()] == ['Show1/outro.png', 'Show1/clip2.mov'], _current_overlays()
    delete_media('clip2', None, p, md); _sync()
    assert [o['file'] for o in _current_overlays()] == ['Show1/outro.png']
    assert 'clip2' not in open(p).read().split('OVERLAYS = [')[1]
    set_overlays([], save=True, tuning_path=p); _sync(); _state.pop('overlays', None)
    # camadas de SHADER: mesmo mecanismo, bloco proprio (SHADER_LAYERS); remap renomeia/tira
    set_shader_layers([{'file': 'presets/default/a.frag', 'opacity': 0.4},
                       {'file': '../x.frag'}, {'file': 'image.frag', 'opacity': -1}], save=True, tuning_path=p); _sync()
    ns = {}; exec(open(p).read(), ns)
    assert ns['SHADER_LAYERS'] == [{'file': 'presets/default/a.frag', 'opacity': 0.4},
                                   {'file': 'image.frag', 'opacity': 0.0}], ns['SHADER_LAYERS']
    assert ns['OVERLAYS'] == [], 'camada de shader nao pode mexer nas de midia'
    set_shader_layers([{'file': 'image.frag', 'opacity': 0.5, 'blend': 'tela'},
                       {'file': 'presets/default/a.frag', 'blend': 'xyz'}], tuning_path=p)
    assert _state['shader_layers'] == [{'file': 'image.frag', 'opacity': 0.5, 'blend': 'tela'},
                                       {'file': 'presets/default/a.frag', 'opacity': 1.0}], _state['shader_layers']
    set_shader_layers(ns['SHADER_LAYERS'], tuning_path=p)
    _remap_shader_layers({'presets/default/a.frag': 'presets/default/b.frag', 'image.frag': None}, p); _sync()
    assert _current_shader_layers() == [{'file': 'presets/default/b.frag', 'opacity': 0.4}], _current_shader_layers()
    set_shader_layers([], save=True, tuning_path=p); _sync(); _state.pop('shader_layers', None)
    # tecla no set ativo (Show1)
    _tuning.MEDIA_SET = 'Show1'
    assert bind_media_key('outro', 'n', p, md) == {'Show1': {'outro': 'n'}}; _sync()
    # apaga o set Show1 -> arquivos vao pra md/default/, tecla some, MEDIA_SET volta pra default
    delete_media_set('Show1', p, md); _sync()
    assert _tuning.MEDIA_SET == 'default' and not os.path.isdir(os.path.join(md, 'Show1'))
    assert os.path.isfile(os.path.join(md, 'default', 'outro.png'))
    assert any(m['name'] == 'outro' and m['file'] == 'default/outro.png' for m in _read_media(None, md)), _tuning.MEDIA
    assert 'Show1' not in _read_keys('MEDIA_KEYS')
    # apaga o set default -> esvazia (arquivos + entradas de MEDIA); a pasta fica, segue ativo
    delete_media_set('default', p, md); _sync()
    assert os.path.isdir(os.path.join(md, 'default')) and not glob.glob(os.path.join(md, 'default', '*'))
    assert _tuning.MEDIA == [] and _tuning.MEDIA_SET == 'default', _tuning.MEDIA
    shutil.rmtree(md)
    globals()['_tuning'] = None

    # --- galeria de transicoes: list / new / rename / default / delete (dir temp) ---
    import types as _tt
    td = tempfile.mkdtemp()
    globals()['_tuning'] = _tt.SimpleNamespace(MEDIA=[
        {'name': 'v', 'file': 'default/v.mp4', 'kind': 'video', 'fit': 'fill', 'transition': 'fx.glsl'}])
    open(p, 'w').write('TRANSITION_DEFAULT = "none"\nMEDIA = [\n]\n')
    assert new_transition(' My Fade!! ', td) == 'MyFade.glsl' and os.path.isfile(os.path.join(td, 'MyFade.glsl'))
    open(os.path.join(td, 'fx.glsl'), 'w').write('// x\n')
    assert _list_transitions(td) == ['MyFade.glsl', 'fx.glsl']
    assert set_transition_default('MyFade.glsl', p, td) == 'MyFade.glsl'
    assert 'TRANSITION_DEFAULT = "MyFade.glsl"' in open(p).read()
    try:
        set_transition_default('nope.glsl', p, td); assert False, 'aceitou transicao inexistente'
    except ValueError:
        pass
    # renomear 'fx.glsl' -> ajusta o item de MEDIA que aponta pra ela
    rename_transition('fx.glsl', 'glow', p, td)
    assert _tuning.MEDIA[0]['transition'] == 'glow.glsl', _tuning.MEDIA
    # apagar a que e' o default -> volta pra 'none'
    delete_transition('MyFade.glsl', p, td)
    assert not os.path.isfile(os.path.join(td, 'MyFade.glsl'))
    assert str(_tuning.TRANSITION_DEFAULT) == 'none', _tuning.TRANSITION_DEFAULT
    shutil.rmtree(td)
    globals()['_tuning'] = None

    # --- SETS (cenas): migracao pastas->sets, auto-save, apply, teclas, transicao, remap ---
    import types as _ts
    root = tempfile.mkdtemp()
    _g0 = (_SHADERS, _MEDIA, _TRANS, _cfg.get('on_set_input'))
    globals().update(_SHADERS=os.path.join(root, 'shaders'), _MEDIA=os.path.join(root, 'media'),
                     _TRANS=os.path.join(root, 'transitions'))
    for d in ('shaders/presets/default', 'shaders/presets/show', 'media/default', 'media/prn', 'transitions'):
        os.makedirs(os.path.join(root, d))
    for rel, txt in (('shaders/image.frag', 'i'), ('shaders/presets/default/a.frag', 'A'),
                     ('shaders/presets/show/a.frag', 'B'), ('shaders/presets/show/b.frag', 'b'),
                     ('media/default/v.mp4', 'v'), ('media/prn/v.mp4', 'v'), ('media/prn/w.png', 'w'),
                     ('transitions/fade.glsl', 'f')):
        open(os.path.join(root, rel), 'w').write(txt)
    p2 = tempfile.mktemp(suffix='.py')
    open(p2, 'w').write('SHADER = "presets/show/b.frag"\nSHADER_SET = "show"\nMEDIA_SET = "prn"\n'
                        'TRANSITION_DEFAULT = "none"\nFX = {\n}\nMEDIA = [\n]\n')
    globals()['_tuning'] = _ts.SimpleNamespace(
        SHADER='presets/show/b.frag', SHADER_SET='show', MEDIA_SET='prn', TRANSITION_DEFAULT='none', FX={},
        MEDIA=[{'name': 'v', 'file': 'default/v.mp4', 'kind': 'video'},
               {'name': 'v2', 'file': 'prn/v.mp4', 'kind': 'video'},
               {'name': 'w', 'file': 'prn/w.png', 'kind': 'image'}],
        OVERLAYS=[{'file': 'prn/w.png', 'opacity': 0.5}],
        SHADER_LAYERS=[{'file': 'presets/show/a.frag', 'opacity': 0.3}])
    st = {'video': {'mode': 'media', 'name': 'w'}, 'video_id': 'media', 'fx': {'tint': 0.5}}
    globals()['_state'] = st
    calls = []
    _cfg['on_set_input'] = lambda k, i: calls.append(i)
    _tp0, _cfg['tuning_path'] = _cfg['tuning_path'], p2   # setters sem tuning_path (set_pool...) -> temp
    _migrate_to_scenes(p2)
    assert sorted(os.listdir(_MEDIA)) == ['default'] and sorted(os.listdir(os.path.join(_MEDIA, 'default'))) == ['v.mp4', 'w.png']
    assert sorted(os.listdir(os.path.join(_SHADERS, 'presets'))) == ['default']
    assert sorted(os.listdir(os.path.join(_SHADERS, 'presets', 'default'))) == ['a-show.frag', 'a.frag', 'b.frag']
    ns = {}; exec(open(p2).read(), ns)
    assert [(m['name'], m['file']) for m in ns['MEDIA']] == [('v', 'default/v.mp4'), ('w', 'default/w.png')], ns['MEDIA']
    assert ns['SHADER'] == 'presets/default/b.frag' and ns['SHADER_SET'] == 'default' and ns['MEDIA_SET'] == 'default'
    assert ns['OVERLAYS'] == [{'file': 'default/w.png', 'opacity': 0.5}], ns['OVERLAYS']
    assert ns['SHADER_LAYERS'] == [{'file': 'presets/default/a-show.frag', 'opacity': 0.3}], ns['SHADER_LAYERS']
    assert [sc['name'] for sc in ns['SCENES']] == ['default', 'prn'] and ns['SCENE'] == 'prn', (ns['SCENES'], ns['SCENE'])
    # formato novo: a principal antiga (w) vira fonte marcada; a pilha antiga vai pra cada fonte
    prn = ns['SCENES'][1]
    assert prn['selected'] == 'default/w.png' and prn['sources'] == [{'file': 'default/w.png', 'opacity': 0.5}], prn
    stack = prn['bindings']['default/w.png']['shaders']
    assert stack == [{'file': 'presets/default/b.frag', 'opacity': 1.0},
                     {'file': 'presets/default/a-show.frag', 'opacity': 0.3}], stack
    assert prn['bindings']['default/w.png']['fx']['presets/default/b.frag'] == {'tint': 0.5}, prn['bindings']
    assert ns['OVERLAYS'] == prn['sources'] and ns['BINDINGS'] == prn['bindings'], 'o vivo devia ser o set ativo'
    _migrate_to_scenes(p2)                                  # idempotente: ja tem SCENES
    assert len(_tuning.SCENES) == 2
    # set no formato ANTIGO no tuning (sem 'sources') e' convertido na leitura
    legacy = _upgrade_scene({'name': 'L', 'video': 'webcam:/dev/video4', 'overlays': [],
                             'shader': 'image.frag', 'shader_layers': [], 'fx': {}})
    assert legacy['sources'] == [{'file': 'webcam:/dev/video4', 'opacity': 1.0}] and legacy['selected'] == 'webcam:/dev/video4'
    assert legacy['bindings'] == {'webcam:/dev/video4': {'shaders': [{'file': 'image.frag', 'opacity': 1.0}], 'fx': {}}}
    # auto-save so no ativo (prn): troca a pilha da fonte e a forca de um efeito
    bnd = _current_bindings()
    bnd['default/w.png']['fx']['presets/default/b.frag']['tint'] = 0.9
    bnd['webcam:/dev/video0'] = {'shaders': [{'file': 'presets/default/a.frag', 'opacity': 0.7, 'blend': 'tela'}], 'fx': {}}
    set_bindings(bnd, save=True, tuning_path=p2)
    save_active_scene(p2)
    assert _find_scene('prn')['bindings']['default/w.png']['fx']['presets/default/b.frag'] == {'tint': 0.9}
    assert 'webcam:/dev/video0' in _find_scene('prn')['bindings'], 'relacao de fonte desmarcada devia ser lembrada'
    assert _find_scene('default')['bindings']['default/w.png']['fx']['presets/default/b.frag'] == {'tint': 0.5}
    # calibracao da saida: so' knob fora do padrao vai pro bloco; save=False nao grava
    open(os.path.join(_SHADERS, GRADE_FRAG), 'w').write('// fx: gama=0.5, vermelho=0.5, x\n')
    assert output_grade_defaults() == {'gama': 0.5, 'vermelho': 0.5, 'x': 1.0}
    g = set_output_grade({'on': 1, 'test': 1, 'fx': {'gama': 0.7, 'vermelho': 0.5}}, tuning_path=p2)
    assert g == {'on': 1, 'test': 1, 'fx': {'gama': 0.7}}, g
    ns = {}; exec(open(p2).read(), ns); assert ns['OUTPUT_GRADE'] == g, ns['OUTPUT_GRADE']
    set_output_grade({'on': 0, 'fx': {'gama': 0.2}}, save=False, tuning_path=p2)
    assert _tuning.OUTPUT_GRADE['fx'] == {'gama': 0.2}
    ns = {}; exec(open(p2).read(), ns); assert ns['OUTPUT_GRADE'] == g
    set_output_grade({'on': 1, 'fx': {}}, tuning_path=p2)
    ns = {}; exec(open(p2).read(), ns); assert ns['OUTPUT_GRADE'] == {'on': 1, 'test': 0, 'fx': {}}
    assert set_output_fps(60, tuning_path=p2) == 60 and _tuning.OUTPUT_FPS == 60   # fps da saida (v2)
    set_output_fps(30, tuning_path=p2); assert open(p2).read().count('OUTPUT_FPS = 30') == 1
    # telas do palco: normaliza, grava o bloco 1x, save=False so' patcha
    t = set_screens([{'name': 'coluna', 'x': 0, 'y': 1, 'w': 1, 'h': 4, 'pw': 256, 'ph': 1024},
                     {'x': 'ruim'}, {'x': 3, 'y': 1, 'w': 0, 'h': 4, 'pw': 0, 'ph': 1024}], tuning_path=p2)
    assert t == [{'name': 'coluna', 'x': 0.0, 'y': 1.0, 'w': 1.0, 'h': 4.0, 'pw': 256, 'ph': 1024},
                 {'name': 'tela 3', 'x': 3.0, 'y': 1.0, 'w': 0.05, 'h': 4.0, 'pw': 1, 'ph': 1024}] == _tuning.SCREENS, t
    ns = {}; exec(open(p2).read(), ns); assert ns['SCREENS'] == t
    set_screens(t[:1], save=False, tuning_path=p2); assert len(_tuning.SCREENS) == 1
    set_screens([], tuning_path=p2)
    ns = {}; exec(open(p2).read(), ns); assert ns['SCREENS'] == [] and open(p2).read().count('SCREENS =') == 1
    # objeto no canvas: rect normalizado; canvas inteiro = sem campo
    r = _norm_overlays([{'file': 'a.png', 'rect': [0.1, 0.2, 0.5, 0.5]}, {'file': 'b.png', 'rect': [0, 0, 1, 1]},
                        {'file': 'c.png', 'rect': [9, 0, 0, 1]}, {'file': 'd.png', 'rect': 'x'}])
    assert [o.get('rect') for o in r] == [[0.1, 0.2, 0.5, 0.5], None, [2.0, 0.0, 0.02, 1.0], None], r
    try:
        set_output_fps(33, tuning_path=p2); raise AssertionError('33 fps devia falhar')
    except ValueError:
        pass
    g = set_output_grade({'on': 0, 'master': 0.25, 'fx': {}}, tuning_path=p2)   # master (v2)
    assert g == {'on': 0, 'test': 0, 'fx': {}, 'master': 0.25} and _current_output_grade() == g, g
    assert set_output_grade({'on': 1, 'master': 1, 'fx': {}}, tuning_path=p2) == {'on': 1, 'test': 0, 'fx': {}}
    assert open(p2).read().count('OUTPUT_GRADE =') == 1
    # imagem da CENA: vai pro set ativo (campo grade), volta ao trocar de set, neutra = sem campo
    act = _active_scene_name()
    other = next(sc['name'] for sc in _read_scenes() if sc['name'] != act)
    g = set_scene_grade({'on': 1, 'fx': {'gama': 0.8, 'vermelho': 0.5}}, tuning_path=p2)
    assert g == {'on': 1, 'fx': {'gama': 0.8}} and _find_scene(act)['grade'] == g, _find_scene(act)
    ns = {}; exec(open(p2).read(), ns); assert ns['SCENE_GRADE'] == g
    apply_scene(other, tuning_path=p2)
    assert _current_scene_grade() == {'on': 1, 'fx': {}} and 'grade' not in _find_scene(other)
    apply_scene(act, tuning_path=p2)
    assert _current_scene_grade() == g, _current_scene_grade()
    set_scene_grade({'on': 1, 'fx': {}}, tuning_path=p2)
    assert 'grade' not in _find_scene(act) and open(p2).read().count('SCENE_GRADE =') == 1
    # preencher/encaixar de camera/tela: bloco SOURCE_FIT so com os 'fit'; a capturada respawna
    st['video_id'] = 'webcam:/dev/video0'
    assert set_source_fit('webcam:/dev/video0', 'fit', p2) == 'fit' and calls[-1] == 'webcam:/dev/video0'
    set_source_fit('screen:HDMI-1', 'fit', p2)
    ns = {}; exec(open(p2).read(), ns)
    assert ns['SOURCE_FIT'] == {'screen:HDMI-1': 'fit', 'webcam:/dev/video0': 'fit'}, ns['SOURCE_FIT']
    set_source_fit('screen:HDMI-1', 'fill', p2)
    assert _tuning.SOURCE_FIT == {'webcam:/dev/video0': 'fit'}
    try:
        set_source_fit('default/w.png', 'fit', p2); assert False, 'midia nao usa SOURCE_FIT'
    except ValueError:
        pass
    # selecionar: so a lista/captura (on_set_input), nao a saida
    select_source('webcam:/dev/video0')
    assert calls[-1] == 'webcam:/dev/video0' and _current_overlays() == prn['sources']
    try:
        select_source('default/nao-existe.png'); assert False, 'selecionou fonte inexistente'
    except ValueError:
        pass
    save_active_scene(p2)
    assert _find_scene('prn')['selected'] == 'webcam:/dev/video0'
    # disponiveis por set: lista explicita some da tela/saida mas lembra; None = tudo (campo some)
    assert 'pool' not in _find_scene('prn'), 'set sem pool nao devia ganhar campo null'
    set_pool({'sources': ['default/w.png', 'default/w.png'], 'shaders': ['presets/default/a-show.frag']})
    assert _find_scene('prn')['pool'] == {'sources': ['default/w.png'], 'shaders': ['presets/default/a-show.frag']}
    assert 'webcam:/dev/video0' in _find_scene('prn')['bindings'], 'tirar do set nao apaga a ligacao'
    _pool_add('shaders', 'presets/default/novo.frag')
    assert _find_scene('prn')['pool']['shaders'][-1] == 'presets/default/novo.frag'
    assert 'pool' not in _find_scene('default')
    # criar = copia do vivo e vira ativo; tecla unica
    create_scene('B', p2)
    assert _active_scene_name() == 'B' and _find_scene('B')['bindings'] == _find_scene('prn')['bindings']
    set_scene_key('B', 'x', p2); set_scene_key('prn', 'X', p2)
    assert _find_scene('B')['key'] == '' and _find_scene('prn')['key'] == 'x'
    set_scene_transition('prn', 'fade.glsl', p2)
    assert scene_transition_name('prn') == 'fade.glsl' and scene_transition_name('B') == 'none'
    try:
        set_scene_transition('prn', 'nope.glsl', p2); assert False, 'aceitou transicao inexistente'
    except ValueError:
        pass
    # aplicar: fontes marcadas + ligacoes + selecao; o apply NAO auto-salva no caminho
    apply_scene('default', p2)
    assert _current_pool() is None, 'set sem pool = tudo'
    assert calls[-1] == 'media:w' and _active_scene_name() == 'default', calls
    assert _current_bindings() == _find_scene('default')['bindings'] and _current_overlays() == _find_scene('default')['sources']
    assert _find_scene('B')['selected'] == 'webcam:/dev/video0', 'apply nao devia gravar em outro set'
    # Biblioteca renomeia/apaga -> sets E ligacoes vivas seguem
    _remap_scenes(files={'default/w.png': 'default/w2.png'}, tuning_path=p2)
    sc = _find_scene('prn')
    assert sc['sources'][0]['file'] == 'default/w2.png' and 'default/w2.png' in sc['bindings'], sc
    assert 'default/w2.png' in _current_bindings()
    _remap_scenes(shaders={'presets/default/b.frag': None}, tuning_path=p2)
    assert [o['file'] for o in _find_scene('prn')['bindings']['default/w2.png']['shaders']] == ['presets/default/a-show.frag']
    assert 'presets/default/b.frag' not in _find_scene('prn')['bindings']['default/w2.png']['fx']
    assert _find_scene('prn')['pool']['sources'] == ['default/w2.png'], 'renomear segue no pool'
    assert 'presets/default/b.frag' not in _find_scene('prn')['pool']['shaders']
    rename_transition('fade.glsl', 'glow', p2, _TRANS)
    assert _find_scene('prn')['transition'] == 'glow.glsl'
    rename_scene('prn', 'Show 1', p2)
    assert _find_scene('Show 1')['key'] == 'x'
    delete_scene('B', p2); delete_scene('Show 1', p2)
    try:
        delete_scene('default', p2); assert False, 'apagou o ultimo set'
    except ValueError:
        pass
    ns = {}; exec(open(p2).read(), ns)               # o tuning.py continua Python valido
    assert [sc['name'] for sc in ns['SCENES']] == ['default'] and ns['SCENE'] == 'default'
    globals().update(_SHADERS=_g0[0], _MEDIA=_g0[1], _TRANS=_g0[2], _tuning=None, _state={})
    _cfg['on_set_input'] = _g0[3]
    _cfg['tuning_path'] = _tp0
    shutil.rmtree(root); os.remove(p2)

    os.remove(p)
    print('dash_server self-check ok')
