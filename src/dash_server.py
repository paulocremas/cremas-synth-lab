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
import glob
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))          # src/
_ROOT = os.path.dirname(_HERE)                              # raiz do repo
_HTML = os.path.join(_ROOT, 'dash.html')
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
        open(path, 'w').write(new)
    return value


def _clamp_ranges(overlap, ranges):
    """8 pares [lo, hi] -> versao consistente. Sempre: int, dentro de [20, 20000], lo < hi.
    overlap=1: cada faixa independente (podem se sobrepor). overlap=0 (crossover): faixas
    ordenadas e SEM sobreposicao (band[k].lo >= band[k-1].hi), mas BURACOS sao permitidos
    (band[k].lo pode ser > band[k-1].hi -> essas frequencias nao entram em nenhuma faixa)."""
    r = [[int(round(float(lo))), int(round(float(hi)))] for lo, hi in ranges[:8]]
    r = [[max(_HZ_MIN, min(_HZ_MAX, lo)), max(_HZ_MIN, min(_HZ_MAX, hi))] for lo, hi in r]
    if overlap:
        return [[lo, max(lo + 1, min(_HZ_MAX, hi))] for lo, hi in r]
    out, prev_hi = [], _HZ_MIN
    for lo, hi in r:
        lo = max(lo, prev_hi)               # nao invade a faixa anterior (buraco ok)
        hi = min(max(hi, lo + 1), _HZ_MAX)  # lo < hi, dentro do teto
        lo = min(lo, hi - 1)
        out.append([lo, hi])
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
        open(path, 'w').write(src)
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
        open(path, 'w').write(src)
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
        open(path, 'w').write(new)
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
        open(path, 'w').write(src)
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
        open(path, 'w').write(src)
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
_MEDIA_MAX = 400 * 1024 * 1024  # teto do upload (bytes) — leitura do body inteira na memoria


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
                    'transition': str(m.get('transition', '') or '')})
    return out


def _write_media(allm, tuning_path=None):
    """Reescreve o bloco MEDIA inteiro (lista ja normalizada: name, file (relativo a media/,
    pode ter subpasta do set), kind, fit)."""
    clean = [{'name': m['name'], 'file': m['file'],
              'kind': 'video' if m.get('kind') == 'video' else 'image',
              'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
              'transition': str(m.get('transition', '') or '')} for m in allm]
    body = '\n'.join('    ' + json.dumps(m) + ',' for m in clean)
    block = f'MEDIA = [\n{body}\n]' if clean else 'MEDIA = [\n]'
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?ms)^MEDIA = \[.*?^\]', block, src)
        if n != 1:
            raise KeyError(f'tuning.py: MEDIA x{n} (esperava 1)')
        open(path, 'w').write(src)
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
        clean.append({'name': nm, 'file': file, 'kind': m.get('kind') or src_item['kind'],
                      'fit': 'fit' if m.get('fit') == 'fit' else 'fill',
                      'transition': str(m.get('transition', '') or '')})
    _write_media(keep + clean, tuning_path)
    return [dict(m, set=setname) for m in clean]


def add_media(orig_name, kind=None, data=b'', setname=None, tuning_path=None, media_dir=None):
    """Grava `data` em media/<set>/<slug><ext> e adiciona a MEDIA no set `setname` (ativo se
    None). `kind` opcional — sai da extensao."""
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
    entry = {'name': slug, 'file': _media_rel(setname, fname), 'kind': kind, 'fit': 'fill', 'transition': ''}
    with open(fpath, 'wb') as f:
        f.write(data)
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
    fn = _cfg.get('on_set_input')
    if fn and (_state.get('video') or {}).get('mode') == 'media' \
            and (_state.get('video') or {}).get('name') == name:
        fn('video', 'webcam:/dev/video0')
    return name


def set_active_media_set(name, tuning_path=None, media_dir=None):
    if name not in _list_media_sets(media_dir):
        raise ValueError(f'set de midia desconhecido: {name!r}')
    path = tuning_path or _cfg['tuning_path']
    with _knob_lock:
        src = open(path).read()
        src, n = re.subn(r'(?m)^MEDIA_SET = "[^"]*"', f'MEDIA_SET = "{name}"', src)
        if n != 1:
            raise KeyError(f'tuning.py: MEDIA_SET x{n} (esperava 1)')
        open(path, 'w').write(src)
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
        open(path, 'w').write(src)
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
    """Troca `old` por `new` em TRANSITION_DEFAULT e nos itens de MEDIA (apagar -> '')."""
    path = tuning_path or _cfg['tuning_path']
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
        open(path, 'w').write(src)
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
        open(path, 'w').write(src)
    return enabled


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
        open(path, 'w').write(src)
    return ch


def _read_knobs():
    return {k['name']: getattr(_tuning, k['name']) for k in KNOBS}


def _payload():
    return {
        'audio': _state.get('audio_dash', {}),   # kick / bands / spectrum — ver dash_data.audio_dash_data
        'image': _state.get('image', {}),
        'out_image': _state.get('out_image', {}),
        'out_analysis_enabled': int(getattr(_tuning, 'OUT_ANALYSIS_ENABLED', 0)),
        'dominant': [round(c, 3) for c in _state.get('dominant', (0.0, 0.0, 0.0))],
        'knobs': _read_knobs(),
        'audio_source': _state.get('audio_source') or _cfg['audio_source'],  # muda ao vivo via set_input
        'video_mode': _state.get('video_label') or _cfg['video_mode'],
        # ids no formato das opcoes dos <select> — pro dash sincronizar os dropdowns entre abas
        'inputs': {'audio': _state.get('audio_source', ''), 'video': _state.get('video_id', '')},
        'output': _state.get('output', {}),   # geometria/fps da janela de saida (imagem sintetizada)
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
        # potenciometros de efeito (aba Efeitos): manifest = nomes do shader ativo,
        # levels = valor 0..1 ao vivo por nome, saved = o que esta gravado em tuning.FX.
        'shader': getattr(_tuning, 'SHADER', 'image.frag'),
        'fx': {'manifest': _state.get('fx_manifest', []),
               'levels': {k: round(v, 4) for k, v in _state.get('fx', {}).items()},
               'saved': dict(getattr(_tuning, 'FX', {}))},
        # galeria de midia (aba Visuals): so o item ATIVO vai no stream (pro highlight seguir
        # tecla/dropdown); a lista em si o dash busca em /media (init + apos cada edicao) — assim
        # o objeto que um <input> de renomear referencia nao e trocado embaixo dele a 20 Hz.
        'media_active': _media_active_name(),
        'html_mtime': os.path.getmtime(_HTML),   # cliente recarrega a aba quando muda
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
        elif path in ('/favicon.png', '/favicon.ico'):  # navegador tambem sonda /favicon.ico
            try:
                self._send(200, 'image/png', open(_FAVICON, 'rb').read())
            except FileNotFoundError:
                self._send(404, 'text/plain', b'nope')
        elif path == '/knobs':
            self._send(200, 'application/json', json.dumps(KNOBS).encode())
        elif path == '/inputs':
            fn = _cfg.get('on_inputs')
            self._send(200, 'application/json', json.dumps(fn() if fn else {}).encode())
        elif path == '/shaders':  # glob aqui, nao no _payload de 20 Hz (igual /inputs)
            s = _active_shader_set()
            self._send(200, 'application/json', json.dumps(
                {'list': _list_shaders(s), 'current': getattr(_tuning, 'SHADER', 'image.frag'),
                 'keys': _read_keys_for('SHADER_KEYS', s),
                 'set': s, 'sets': _list_shader_sets()}).encode())
        elif path == '/media':
            s = _active_media_set()
            self._send(200, 'application/json', json.dumps(
                {'list': _read_media(s), 'keys': _read_keys_for('MEDIA_KEYS', s),
                 'current': _media_active_name(),
                 'set': s, 'sets': _list_media_sets()}).encode())
        elif path == '/transitions':
            self._send(200, 'application/json', json.dumps(_transitions_payload()).encode())
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
                time.sleep(0.05)  # 20 Hz — o dado novo vem a ~14 Hz (DASH_EVERY_N_CHUNKS)
        except (BrokenPipeError, ConnectionResetError):
            pass  # aba fechou

    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length', 0))
        if path == '/media-add' and length > _MEDIA_MAX:
            self._send(413, 'text/plain', f'arquivo grande demais (> {_MEDIA_MAX // (1024 * 1024)} MB)'.encode())
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
        if path == '/shader':
            try:
                b = json.loads(raw.decode())
                out = set_shader(b['name'])
                self._send(200, 'application/json', json.dumps({'shader': out}).encode())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, 'text/plain', str(e).encode())
            return
        if path == '/new-shader':
            try:
                b = json.loads(raw.decode())
                rel = new_shader(b['name'])
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
        if path == '/media-add':  # body = bytes do arquivo; ?name=<orig> (kind sai da extensao)
            try:
                q = urllib.parse.parse_qs(self.path.partition('?')[2])
                entry = add_media(q.get('name', [''])[0], data=raw)
                self._send(200, 'application/json', json.dumps(entry).encode())
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
        if path == '/fx':
            try:
                b = json.loads(raw.decode())
                out = set_fx(b['fx'])
                _state.setdefault('fx', {}).update(out)  # aplica ja, sem esperar o reload do tuning.py
                self._send(200, 'application/json', json.dumps(out).encode())
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


def start(state, tuning_mod, tuning_path, is_running, audio_source='', video_mode='',
          port=8765, open_browser=True, on_inputs=None, on_set_input=None, on_set_output=None):
    """Sobe o servidor num thread daemon. Degrada sem travar o synth se a porta estiver ocupada.
    open_browser=False num hot-reload pra nao reabrir as abas. on_inputs/on_set_input = callbacks
    do native_synth pra listar/trocar entrada de audio e video. on_set_output = pedido de troca
    da janela de SAIDA (monitor/tela cheia/dimensao — barra "saida" no topo do dash)."""
    global _state, _tuning
    _state, _tuning = state, tuning_mod
    _cfg.update(is_running=is_running, audio_source=audio_source, video_mode=video_mode,
                tuning_path=tuning_path, on_inputs=on_inputs, on_set_input=on_set_input,
                on_set_output=on_set_output)
    try:
        _migrate_default_to_folder()
    except (OSError, KeyError, ValueError) as e:
        print(f'dash: migracao default->pasta pulada ({e})')
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

    os.remove(p)
    print('dash_server self-check ok')
