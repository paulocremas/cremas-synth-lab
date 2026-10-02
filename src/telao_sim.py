#!/usr/bin/env python3
"""TELÃO VIRTUAL: a processadora de LED de mentira. Aqui se MONTA o telão (as telas em metros,
LEDs, giro, forma) e, como um telão de verdade, ele só anuncia UMA resolução — o "todo" (EDID): os
blocos, o lugar de cada um no raster e o espaço entre eles ficam aqui dentro, como na processadora
(NovaLCT, Tessera). Enquanto aberto (e "plugado"), anuncia a saída SIM-1 no formato escolhido
(dash_data.VIRTUAL_OUTPUTS — o native e o dash leem junto com o xrandr). O dash v2 avisa "telão
detectado"; "⚡ mapear agora" faz do raster o canvas do prisma e abre a saída "nela" (janela do tamanho
do formato, fora da tela — o WM deixa uma tira à direita). Lá se divide o raster em blocos (pixel map)
copiando o mapa daqui (Tab = raster, com x,y e tamanho em px de cada bloco).

Como uma processadora: cada tela tem o seu lugar no RASTER (ox, oy; reempacotado sozinho a cada
mudança, dash_data.pack_raster) e daqui se recorta a janela capturada por esse mapa, remontando o
PALCO em metros na resolução nativa de cada painel. Se o prisma mandar outro mapa, aparece errado.
Padrão de teste: shaders/presets/default/Teste.frag (linha com degrau = mapa errado).

Uso: .venv/bin/python src/telao_sim.py [--prisma] [--formato 3840x2160] [--nome SIM-1] [--desplugado]
     [--arquivo PATH] [--janela TITULO] [--vista palco|raster] [--fps N] [--selfcheck]
  --prisma = abre o prisma do repo (src/native_synth.py) DEPOIS de anunciar o telão: ele já nasce
  vendo o SIM-1. Fechar o simulador fecha esse prisma junto.
  --arquivo = onde o telão montado fica salvo (padrão ~/.config/prisma/telao_sim.json).
Teclas: 1-8 / clique = formato · E = formato próprio (digita LxA, Enter) · D = plugar/desplugar ·
Tab = palco / raster · N = nomes · P = pixelado · Esc = solta a seleção / sai.
MONTAR (vista palco): botões + coluna/faixa/16:9/painel · L = ✎ desenhar (clique = ponto; 1º ponto
/ Enter fecha; ⌫ desfaz; Esc cancela) · arrastar = move (gruda; Alt = solto) · cantos = tamanho
(Shift = proporção) · bolinha de cima = gira (Shift = 15°) · bolinhas brancas = vértices · R / Shift+R
= gira 15° · F = troca a forma · C = duplica · Del = tira · setas = empurra 5 cm (Shift = 1 cm).
"""
import argparse
import atexit
import copy
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time

import numpy as np

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dash_data  # noqa: E402  (VIRTUAL_OUTPUTS: o mesmo caminho que o prisma le)
WALL_FILE = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'prisma', 'telao_sim.json')


# ---------- funções puras (testadas no --selfcheck) ----------

def fit_box(win_w, win_h, w, h):
    """Onde um retângulo w x h cai ENCAIXADO (barras no que sobra) numa janela win_w x win_h,
    em pixels com origem em cima: (x, y, w, h). Mesma regra do _canvas_box do native."""
    if not (win_w and win_h and w and h):
        return (0.0, 0.0, float(win_w), float(win_h))
    k = min(win_w / w, win_h / h)
    return ((win_w - w * k) / 2, (win_h - h * k) / 2, w * k, h * k)


def stage_bounds(screens):
    """Contorno das telas válidas em metros (já giradas/recortadas): (x0, y0, W, H) ou None."""
    v = [dash_data.screen_bbox(t) for t in screens if t['w'] > 0 and t['h'] > 0]
    if not v:
        return None
    x0, y0 = min(b[0] for b in v), min(b[1] for b in v)
    return (x0, y0, max(b[2] for b in v) - x0, max(b[3] for b in v) - y0)


def clean_screens(raw):
    """tuning.SCREENS -> lista de dicts normalizados; descarta o que não tem x/y/w/h numérico."""
    out = []
    for t in raw or []:
        try:
            s = {k: float(t[k]) for k in ('x', 'y', 'w', 'h')}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if s['w'] <= 0 or s['h'] <= 0:
            continue
        s['name'] = str(t.get('name') or f'tela {len(out) + 1}')
        s['pw'], s['ph'] = int(t.get('pw') or 0), int(t.get('ph') or 0)
        s['ox'] = int(t['ox']) if t.get('ox') is not None else None
        s['oy'] = int(t['oy']) if t.get('oy') is not None else None
        try:
            s['rot'] = float(t.get('rot') or 0.0)
        except (TypeError, ValueError):
            s['rot'] = 0.0
        s['poly'] = dash_data.screen_poly(t)                # forma livre (dash_data.screen_axes)
        out.append(s)
    return out


def pmap_on(pm):
    """(rw, rh) se o PIXEL_MAP está ligado e válido, senão None."""
    try:
        if isinstance(pm, dict) and pm.get('on') and int(pm['w']) >= 16 and int(pm['h']) >= 16:
            return int(pm['w']), int(pm['h'])
    except (KeyError, TypeError, ValueError):
        pass
    return None


def plan(screens, pm, win_w, win_h):
    """O que a processadora recorta da janela: (modo, box, [(tela, (x, y, w, h) na janela | None,
    aviso)]). box = área útil (raster/canvas) dentro da janela, sem as barras."""
    rr = pmap_on(pm)
    st = stage_bounds(screens)
    out = []
    if rr:
        rw, rh = rr
        box = fit_box(win_w, win_h, rw, rh)
        sx, sy = box[2] / rw, box[3] / rh
        for s in screens:
            if s['ox'] is None or s['oy'] is None or s['pw'] <= 0 or s['ph'] <= 0:
                out.append((s, None, 'sem ox/oy/pw/ph: fora do raster'))
                continue
            warn = ''
            if s['ox'] < 0 or s['oy'] < 0 or s['ox'] + s['pw'] > rw or s['oy'] + s['ph'] > rh:
                warn = 'passa da borda do raster'
            for o in screens:
                if o is not s and o['ox'] is not None and o['oy'] is not None and o['pw'] > 0 and o['ph'] > 0 \
                        and s['ox'] < o['ox'] + o['pw'] and o['ox'] < s['ox'] + s['pw'] \
                        and s['oy'] < o['oy'] + o['ph'] and o['oy'] < s['oy'] + s['ph']:
                    warn = (warn + ' · ' if warn else '') + f"sobrepõe {o['name']}"
            out.append((s, (box[0] + s['ox'] * sx, box[1] + s['oy'] * sy, s['pw'] * sx, s['ph'] * sy), warn))
        return 'raster', box, out
    if not st:
        return 'janela', (0.0, 0.0, float(win_w), float(win_h)), []
    x0, y0, W, H = st
    box = fit_box(win_w, win_h, W, H)
    for s in screens:                                  # o contorno (girado) da tela no canvas
        bx0, by0, bx1, by1 = dash_data.screen_bbox(s)
        out.append((s, (box[0] + (bx0 - x0) / W * box[2], box[1] + (by0 - y0) / H * box[3],
                         (bx1 - bx0) / W * box[2], (by1 - by0) / H * box[3]), ''))
    return 'canvas', box, out


# ---------- janela / captura ----------

def find_window(title):
    """(id, w, h) da janela de saída: WM_CLASS do native (prisma.prisma — SDL_VIDEO_X11_WMCLASS) com
    `title` no título; o dash (Brave) também diz "Saída" no título com a aba aberta, então classe
    de navegador nunca vale. Tamanho do cliente pelo xwininfo."""
    try:
        out = subprocess.check_output(['wmctrl', '-lx'], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    rows = [p for p in (line.split(None, 4) for line in out.splitlines())
            if len(p) == 5 and title.lower() in p[4].lower() and not re.search(r'brave|chrom|firefox', p[2], re.I)]
    rows.sort(key=lambda p: not p[2].lower().startswith('prisma.'))
    if not rows:
        return None
    try:
        info = subprocess.check_output(['xwininfo', '-id', rows[0][0]], text=True, stderr=subprocess.DEVNULL)
        w = int(re.search(r'Width:\s+(\d+)', info).group(1))
        h = int(re.search(r'Height:\s+(\d+)', info).group(1))
    except (OSError, subprocess.CalledProcessError, AttributeError):
        return None
    return rows[0][0], w, h


class Grabber:
    """ffmpeg x11grab -window_id: segue a janela (com compositor, mesmo coberta). Reinicia
    sozinho se a janela muda de id/tamanho. self.frame = (np rgb h x w x 3) mais recente."""

    def __init__(self, title, fps):
        self.title, self.fps = title, fps
        self.win, self.proc, self.frame, self.status = None, None, None, 'procurando janela...'
        self.lock = threading.Lock()
        self.alive = True
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        while self.alive:
            w = find_window(self.title)
            if w != self.win or (self.proc and self.proc.poll() is not None):
                self._stop()
                self.win = w
                if w:
                    self._start(*w)
                else:
                    self.frame, self.status = None, f'nenhuma janela com "{self.title}" no título'
            time.sleep(1.0)

    def _start(self, wid, w, h):
        cmd = ['ffmpeg', '-loglevel', 'error', '-f', 'x11grab', '-draw_mouse', '0',
               '-window_id', str(int(wid, 16)), '-framerate', str(self.fps), '-i', os.environ.get('DISPLAY', ':0'),
               '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.status = f'janela {wid} {w}x{h}'
        threading.Thread(target=self._read, args=(self.proc, w, h), daemon=True).start()

    def _read(self, proc, w, h):
        n = w * h * 3
        while self.alive and proc.poll() is None:
            buf = b''
            while len(buf) < n:
                c = proc.stdout.read(n - len(buf))
                if not c:
                    return
                buf += c
            with self.lock:
                self.frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def close(self):
        self.alive = False
        self._stop()


# ---------- telão virtual: formatos + anúncio ----------

# formatos que uma processadora costuma aceitar na entrada (EDID): nome, w, h
FORMATS = [('HD', 1920, 1080), ('WUXGA', 1920, 1200), ('2K', 2560, 1440), ('4K×1K', 3840, 1080),
           ('largo HDMI 1.4', 4092, 1136), ('4K UHD', 3840, 2160), ('DCI 4K', 4096, 2160), ('vertical', 1080, 1920)]


def parse_fmt(txt):
    """'3840x2160' / '3840×2160' / '3840 2160' -> (w, h) ou None (16..16384)."""
    m = re.fullmatch(r'\s*(\d+)\s*[x×X* ]\s*(\d+)\s*', txt or '')
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if 16 <= w <= 16384 and 16 <= h <= 16384 else None


def fmt_label(w, h):
    return next((n for n, a, b in FORMATS if (a, b) == (w, h)), 'próprio')


class Announce:
    """Escreve/apaga o anúncio do telão virtual (dash_data.VIRTUAL_OUTPUTS). Atômico; some no exit."""

    def __init__(self, name, path=None):
        self.name, self.path = name, path or dash_data.VIRTUAL_OUTPUTS
        atexit.register(self.clear)

    def set(self, w, h):
        out = {'name': self.name, 'w': w, 'h': h, 'label': fmt_label(w, h)}   # só o "todo", como o EDID
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'pid': os.getpid(), 'outputs': [out]}, f)
        os.replace(tmp, self.path)

    def clear(self):
        try:
            with open(self.path) as f:
                if json.load(f).get('pid') != os.getpid():
                    return                    # outro simulador assumiu: não é meu
            os.remove(self.path)
        except (OSError, ValueError, AttributeError):
            pass


# ---------- o telão MONTADO aqui ----------

ADD = [('coluna', 1, 4, 256, 1024), ('faixa', 4, 1, 1024, 256), ('tela 16:9', 3.2, 1.8, 1920, 1080), ('painel', 0.5, 0.5, 128, 128)]


def _ngon(n, a0=-90):
    return [[round(0.5 + 0.5 * math.cos(math.radians(a0 + i * 360 / n)), 4),
             round(0.5 + 0.5 * math.sin(math.radians(a0 + i * 360 / n)), 4)] for i in range(n)]


def _arc(r, n, a0, a1):   # meio anel, base embaixo
    return [[round(0.5 + r * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))), 4),
             round(1 + 2 * r * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1))), 4)] for i in range(n)]


# = SHAPES do dash v2 (u, v no painel sem giro; None = o painel inteiro)
SHAPES = [('retângulo', None), ('triângulo', [[0.5, 0], [1, 1], [0, 1]]), ('losango', [[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]]),
          ('trapézio', [[0.2, 0], [0.8, 0], [1, 1], [0, 1]]), ('hexágono', _ngon(6, 0)), ('círculo', _ngon(32)),
          ('L', [[0, 0], [0.4, 0], [0.4, 0.6], [1, 0.6], [1, 1], [0, 1]]), ('arco', _arc(0.5, 16, 180, 360) + _arc(0.25, 16, 360, 180))]


def shape_name(t):
    return next((n for n, p in SHAPES if p == (t.get('poly') or None)), 'livre')


def norm_rot(a):
    r = round(((a + 180) % 360 + 360) % 360 - 180, 1)
    return 180.0 if r == -180 else r


def set_rot(t, a):
    a = norm_rot(a)
    if a:
        t['rot'] = a
    else:
        t.pop('rot', None)


def corner_world(t, u, v):
    o, ex, ey = dash_data.screen_axes(t)
    return o[0] + u * ex[0] + v * ey[0], o[1] + u * ex[1] + v * ey[1]


def resize_corner(t0, key, dx, dy, keep=False):
    """Arrasta o canto `key` (nw/ne/se/sw) de t0 por (dx, dy) metros no palco: o arrasto vale no
    eixo do painel girado e o canto OPOSTO fica parado. Mantém a densidade (px/m). -> tela nova."""
    a = math.radians(t0.get('rot') or 0)
    lx, ly = dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)
    L, T = key[1] == 'w', key[0] == 'n'
    w, h = max(0.05, t0['w'] + (-lx if L else lx)), max(0.05, t0['h'] + (-ly if T else ly))
    if keep:
        r = t0['w'] / t0['h']
        w, h = (w, w / r) if w / h > r else (h * r, h)
    fu, fv = (1 if L else 0), (1 if T else 0)
    p0, p1 = corner_world(t0, fu, fv), corner_world(dict(t0, x=0, y=0, w=w, h=h), fu, fv)
    t = dict(t0, x=round(p0[0] - p1[0], 3), y=round(p0[1] - p1[1], 3), w=round(w, 2), h=round(h, 2))
    t['pw'] = max(1, round(t['w'] * t0['pw'] / t0['w']))
    t['ph'] = max(1, round(t['h'] * t0['ph'] / t0['h']))
    return t


def screen_uv(t, x, y):
    """Ponto do palco (m) -> (u, v) no painel."""
    o, ex, ey = dash_data.screen_axes(t)
    d = (x - o[0], y - o[1])
    return (d[0] * ex[0] + d[1] * ex[1]) / (t['w'] ** 2), (d[0] * ey[0] + d[1] * ey[1]) / (t['h'] ** 2)


def pen_screen(pts, dens, name):
    """Desenho do lápis (metros) -> tela: o retângulo que o envolve + o polígono. None = fino demais."""
    if len(pts) < 3:
        return None
    x, y = round(min(p[0] for p in pts), 3), round(min(p[1] for p in pts), 3)
    w, h = round(max(p[0] for p in pts) - x, 2), round(max(p[1] for p in pts) - y, 2)
    if w < 0.05 or h < 0.05:
        return None
    return {'name': name, 'x': x, 'y': y, 'w': w, 'h': h, 'pw': max(1, round(w * dens)), 'ph': max(1, round(h * dens)),
            'poly': [[round(min(1, max(0, (px - x) / w)), 4), round(min(1, max(0, (py - y) / h)), 4)] for px, py in pts[:32]]}


class Wall:
    """O telão montado: {'formato': [w, h], 'telas': [SCREENS com ox/oy]} em `path`."""

    def __init__(self, path):
        self.path, self.screens, self.fmt = path, [], None
        try:
            with open(path) as f:
                d = json.load(f)
            self.screens = [t for t in d.get('telas') or [] if isinstance(t, dict)]
            self.fmt = parse_fmt('%sx%s' % tuple(d['formato'])) if d.get('formato') else None
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def commit(self, fmt):
        """Reempacota o raster no formato e salva. -> as que não couberam."""
        out = dash_data.pack_raster(self.screens, *fmt)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'formato': list(fmt), 'telas': self.screens}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        return out


def stage_xf(screens, vw, vh, bottom=22):
    """Palco -> tela do simulador: (x0, y0, k px/m, ox, oy), com folga em volta pra montar."""
    x0, y0, W, H = stage_bounds(screens) or (0.0, 0.0, 4.0, 3.0)
    pad = max(0.5, max(W, H) * 0.15)
    k = max(1e-3, min((vw - 16) / (W + 2 * pad), (vh - bottom - 16) / (H + 2 * pad)))
    return x0, y0, k, (vw - W * k) / 2, (vh - bottom - H * k) / 2


def to_px(xf, x, y):
    return xf[3] + (x - xf[0]) * xf[2], xf[4] + (y - xf[1]) * xf[2]


def handles(t, xf):
    """Alças da tela selecionada: [(tipo, chave, (px, py))] — v = vértice, r = giro, c = canto."""
    P = lambda u, v: to_px(xf, *corner_world(t, u, v))
    out = [('v', j, P(u, v)) for j, (u, v) in enumerate(dash_data.screen_poly(t) or [])]
    top, cen = P(0.5, 0), P(0.5, 0.5)
    n = math.hypot(top[0] - cen[0], top[1] - cen[1]) or 1
    out.append(('r', None, (top[0] + (top[0] - cen[0]) / n * 24, top[1] + (top[1] - cen[1]) / n * 24)))
    return out + [('c', c, P(u, v)) for c, (u, v) in (('nw', (0, 0)), ('ne', (1, 0)), ('se', (1, 1)), ('sw', (0, 1)))]


class Editor:
    """Montar o telão na vista palco (mouse em px do corpo). commit() = salva + reempacota + anuncia."""

    def __init__(self, wall, commit):
        self.wall, self.commit = wall, commit
        self.sel, self.drag, self.pen, self.hover, self.xf = None, None, None, None, None

    @property
    def screens(self):
        return self.wall.screens

    def to_m(self, p):
        x0, y0, k, ox, oy = self.xf
        return (p[0] - ox) / k + x0, (p[1] - oy) / k + y0

    def hit(self, p):
        if self.sel is not None:
            for typ, key, q in handles(self.screens[self.sel], self.xf):
                if math.hypot(q[0] - p[0], q[1] - p[1]) <= 9:
                    return typ, key, self.sel
        m = self.to_m(p)
        for i in reversed(range(len(self.screens))):
            if dash_data.in_poly(dash_data.screen_pts(self.screens[i]), *m):
                return 's', None, i
        return None

    def dens(self):
        return max((max(t['pw'] / t['w'], t['ph'] / t['h']) for t in self.screens), default=256)

    def add(self, name, w, h, pw, ph):
        st = stage_bounds(clean_screens(self.screens))
        n = sum(1 for t in self.screens if t['name'].startswith(name)) + 1
        self.screens.append({'name': f'{name} {n}', 'x': round(st[0] + st[2] + 0.2, 3) if st else 0.0,
                             'y': round(st[1], 3) if st else 0.0, 'w': w, 'h': h, 'pw': pw, 'ph': ph})
        self.sel = len(self.screens) - 1
        self.commit()

    def down(self, p, mods):
        if self.pen is not None:
            return self.pen_click(p, mods)
        h = self.hit(p)
        self.sel = h[2] if h else None
        if h:
            self.drag = {'typ': h[0], 'key': h[1], 'p0': p, 't0': copy.deepcopy(self.screens[h[2]])}

    def motion(self, p, mods):
        if self.pen is not None:
            self.hover = self.snap(self.to_m(p), mods)
        d = self.drag
        if not d:
            return
        t0, k, free = d['t0'], self.xf[2], bool(mods & pygame.KMOD_ALT)
        dx, dy = (p[0] - d['p0'][0]) / k, (p[1] - d['p0'][1]) / k
        if d['typ'] == 's':
            x, y = t0['x'] + dx, t0['y'] + dy
            sx = sy = None
            if not free and not t0.get('rot'):          # ímã: bordas/meio das outras (girada: sem ímã)
                ob = [dash_data.screen_bbox(t) for i, t in enumerate(self.screens) if i != self.sel]
                near = lambda vals, ts: min(((tt - v, abs(tt - v)) for v in vals for tt in ts if abs(tt - v) < 8 / k), key=lambda q: q[1], default=None)
                sx = near([x, x + t0['w'] / 2, x + t0['w']], [c for b in ob for c in (b[0], b[2])])
                sy = near([y, y + t0['h'] / 2, y + t0['h']], [c for b in ob for c in (b[1], b[3])])
            x = x + sx[0] if sx else (x if free else round(x * 20) / 20)
            y = y + sy[0] if sy else (y if free else round(y * 20) / 20)
            self.screens[self.sel].update(x=round(x, 3), y=round(y, 3))
        elif d['typ'] == 'c':
            self.screens[self.sel] = resize_corner(t0, d['key'], dx, dy, bool(mods & pygame.KMOD_SHIFT))
        elif d['typ'] == 'r':
            cx, cy = to_px(self.xf, *corner_world(t0, 0.5, 0.5))
            a = math.degrees(math.atan2(p[1] - cy, p[0] - cx)) + 90
            if mods & pygame.KMOD_SHIFT:
                a = round(a / 15) * 15
            elif not free:
                a = next((g for g in (-180, -90, 0, 90, 180, 270) if abs(a - g) < 4), round(a))
            set_rot(self.screens[self.sel], a)
        elif d['typ'] == 'v':
            t = self.screens[self.sel]
            u, v = screen_uv(t0, *self.to_m(p))
            if not free:
                others = [q for j, q in enumerate(t['poly']) if j != d['key']]
                pick = lambda x, ts, thr: min((q for q in ts if abs(q - x) < thr), key=lambda q: abs(q - x), default=x)
                u = pick(u, [0, 0.5, 1] + [q[0] for q in others], 8 / (t['w'] * k))
                v = pick(v, [0, 0.5, 1] + [q[1] for q in others], 8 / (t['h'] * k))
            t['poly'][d['key']] = [round(min(1, max(0, u)), 4), round(min(1, max(0, v)), 4)]

    def up(self):
        if self.drag:
            self.drag = None
            self.commit()

    # --- lápis
    def snap(self, m, mods):
        return m if mods & pygame.KMOD_ALT else (round(m[0] * 20) / 20, round(m[1] * 20) / 20)

    def pen_click(self, p, mods):
        m, pts, k = self.snap(self.to_m(p), mods), self.pen, self.xf[2]
        at = lambda q: math.hypot((q[0] - m[0]) * k, (q[1] - m[1]) * k) < 10
        if len(pts) >= 3 and at(pts[0]):
            return self.pen_finish()
        if pts and at(pts[-1]):
            return
        if len(pts) < 32:
            pts.append(m)

    def pen_finish(self):
        n = sum(1 for t in self.screens if t['name'].startswith('forma')) + 1
        t = pen_screen(self.pen or [], self.dens(), f'forma {n}')
        self.pen = None
        if t:
            self.screens.append(t)
            self.sel = len(self.screens) - 1
            self.commit()

    def key(self, e):
        """Tecla do MONTAR. -> True se usou."""
        shift = bool(e.mod & pygame.KMOD_SHIFT)
        if self.pen is not None:
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.pen_finish()
            elif e.key == pygame.K_BACKSPACE:
                self.pen = self.pen[:-1]
            elif e.key == pygame.K_ESCAPE:
                self.pen = None
            else:
                return False
            return True
        if e.key == pygame.K_l:
            self.pen, self.sel = [], None
            return True
        if self.sel is None:
            return False
        t = self.screens[self.sel]
        if e.key == pygame.K_ESCAPE:
            self.sel = None
            return True
        if e.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self.screens.pop(self.sel)
            self.sel = None
        elif e.key == pygame.K_r:
            set_rot(t, (t.get('rot') or 0) + (-15 if shift else 15))
        elif e.key == pygame.K_f:
            self.cycle_shape(-1 if shift else 1)
            return True
        elif e.key == pygame.K_c:
            c = copy.deepcopy(t)
            c.update(name=t['name'] + ' b', x=round(t['x'] + t['w'], 3))
            self.screens.append(c)
            self.sel = len(self.screens) - 1
        elif e.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            st = 0.01 if shift else 0.05
            t['x'] = round(t['x'] + st * ((e.key == pygame.K_RIGHT) - (e.key == pygame.K_LEFT)), 3)
            t['y'] = round(t['y'] + st * ((e.key == pygame.K_DOWN) - (e.key == pygame.K_UP)), 3)
        else:
            return False
        self.commit()
        return True

    def cycle_shape(self, step):
        t = self.screens[self.sel]
        names = [n for n, _ in SHAPES]
        cur = shape_name(t)
        p = SHAPES[(names.index(cur) + step) % len(SHAPES) if cur in names else 0][1]
        if p:
            t['poly'] = copy.deepcopy(p)
        else:
            t.pop('poly', None)
        self.commit()

    def draw(self, scr, font):
        """Seleção, alças e o lápis por cima do palco."""
        xf = self.xf
        if self.sel is not None:
            t = self.screens[self.sel]
            pygame.draw.polygon(scr, C_SEL, [to_px(xf, *q) for q in dash_data.screen_pts(t)], 2)
            if dash_data.screen_poly(t):                 # o painel inteiro, tracejado de leve
                pygame.draw.polygon(scr, (120, 80, 50), [to_px(xf, *corner_world(t, u, v)) for u, v in ((0, 0), (1, 0), (1, 1), (0, 1))], 1)
            for typ, _, q in handles(t, xf):
                if typ == 'r':
                    pygame.draw.line(scr, C_SEL, to_px(xf, *corner_world(t, 0.5, 0)), q, 1)
                    pygame.draw.circle(scr, C_SEL, q, 7)
                elif typ == 'v':
                    pygame.draw.circle(scr, (255, 255, 255), q, 5)
                    pygame.draw.circle(scr, (0, 0, 0), q, 5, 1)
                else:
                    pygame.draw.rect(scr, C_SEL, (q[0] - 5, q[1] - 5, 10, 10))
            info = f"{t['name']} · {t['w']}×{t['h']} m · {t['pw']}×{t['ph']} px · {t.get('rot') or 0}° · {shape_name(t)}"
            scr.blit(font.render(info, True, C_SEL, C_BG), (8, 4))
        if self.pen is not None:
            pts = [to_px(xf, *q) for q in self.pen] + ([to_px(xf, *self.hover)] if self.hover else [])
            if len(pts) >= 2:
                pygame.draw.lines(scr, C_SEL, False, pts, 2)
            for j, q in enumerate(pts[:len(self.pen)]):
                pygame.draw.circle(scr, (255, 255, 255) if j == 0 else C_SEL, q, 6 if j == 0 else 4)
            scr.blit(font.render('✎ clique = ponto · 1º ponto / Enter = fecha · ⌫ desfaz · Esc cancela · Alt = fora da grade',
                                 True, C_SEL, C_BG), (8, 4))


def entrada(fr_size, fmt, plugged):
    """O que a processadora mostraria na ENTRADA: (nível, texto). nível: ok | warn | bad."""
    if not plugged:
        return 'bad', 'desplugado — o prisma não vê o telão'
    if not fr_size:
        return 'bad', 'sem sinal — no dash: Saída > Telas do palco > mapear'
    if tuple(fr_size) == tuple(fmt):
        return 'ok', f'sinal {fr_size[0]}×{fr_size[1]} · 1:1 com o formato'
    return 'warn', f'sinal {fr_size[0]}×{fr_size[1]} ≠ formato {fmt[0]}×{fmt[1]} — escalado (prisma ainda não remapeou?)'


# ---------- desenho ----------

C_BG, C_STAGE, C_LINE, C_TXT, C_WARN, C_DIM = (14, 14, 18), (30, 30, 36), (90, 90, 110), (220, 220, 230), (255, 80, 70), (130, 130, 145)
C_SEL, C_GRID = (255, 157, 82), (26, 30, 35)


def _hatch(surf, r):
    surf.fill(C_STAGE, r)
    clip = surf.get_clip()
    surf.set_clip(r)
    for i in range(-r.h, r.w, 14):
        pygame.draw.line(surf, (60, 60, 70), (r.x + i, r.bottom), (r.x + i + r.h, r.y))
    surf.set_clip(clip)


def _shape_mask(piece, pts):
    """Apaga (preto) o que cai fora do polígono `pts` (px da peça)."""
    m = pygame.Surface(piece.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(m, (255, 255, 255, 255), pts)
    piece = piece.convert_alpha()
    piece.blit(m, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return piece


def draw_stage(scr, font, fr, mode, items, xf, names, pixelado):
    vw, vh = scr.get_size()
    x0, y0, k, ox, oy = xf
    m = 24
    step = 1 if k >= 40 else 5 if k >= 12 else 10        # grade de 1 m (5/10 m se o palco é grande)
    mx = math.floor((x0 - ox / k) / step) * step              # 1a linha (m) a esquerda/em cima da tela
    while ox + (mx - x0) * k < vw:
        pygame.draw.line(scr, C_GRID, (ox + (mx - x0) * k, 0), (ox + (mx - x0) * k, vh - 22))
        mx += step
    my = math.floor((y0 - oy / k) / step) * step
    while oy + (my - y0) * k < vh - 22:
        pygame.draw.line(scr, C_GRID, (0, oy + (my - y0) * k), (vw, oy + (my - y0) * k))
        my += step
    if not items:
        scr.blit(font.render('telão vazio: monte com + coluna / + faixa / + 16:9 / + painel, ou ✎ desenhar (L)', True, C_TXT), (16, 30))
    src = pygame.surfarray.make_surface(fr.swapaxes(0, 1)) if fr is not None else None
    fh, fw = (fr.shape[:2] if fr is not None else (0, 0))
    for s, rect, warn in items:
        free = bool(s['rot'] or s['poly'])
        world = [(ox + (px - x0) * k, oy + (py - y0) * k) for px, py in dash_data.screen_pts(s)]   # contorno no palco
        bx0, by0, bx1, by1 = dash_data.screen_bbox(s)
        d = pygame.Rect(round(ox + (bx0 - x0) * k), round(oy + (by0 - y0) * k),
                        max(1, round((bx1 - bx0) * k)), max(1, round((by1 - by0) * k)))
        if rect is None or src is None:
            _hatch(scr, d) if not free else pygame.draw.polygon(scr, C_STAGE, world)
        else:
            c = pygame.Rect(round(rect[0]), round(rect[1]), max(1, round(rect[2])), max(1, round(rect[3])))
            cc = c.clip(pygame.Rect(0, 0, fw, fh))
            if cc.w and cc.h:
                piece = pygame.Surface(c.size)
                piece.fill((0, 0, 0))                      # o que cai fora da janela = preto no painel
                piece.blit(src.subsurface(cc), (cc.x - c.x, cc.y - c.y))
                scale = pygame.transform.scale if pixelado else pygame.transform.smoothscale
                if mode == 'raster':                       # a fatia = o painel sem giro (pw x ph LEDs)
                    if s['pw'] > 0 and s['ph'] > 0:
                        piece = pygame.transform.smoothscale(piece, (s['pw'], s['ph']))
                    lw, lh = max(1, round(s['w'] * k)), max(1, round(s['h'] * k))
                    piece = scale(piece, (lw, lh))
                    if s['poly']:
                        piece = _shape_mask(piece, [(u * lw, v * lh) for u, v in s['poly']])
                    if s['rot']:
                        piece = pygame.transform.rotate(piece.convert_alpha(), -s['rot'])
                    cx, cy = ox + (s['x'] + s['w'] / 2 - x0) * k, oy + (s['y'] + s['h'] / 2 - y0) * k
                    scr.blit(piece, piece.get_rect(center=(round(cx), round(cy))))
                else:                                      # canvas: a janela já está na forma física
                    if s['pw'] > 0 and s['ph'] > 0 and not free:
                        piece = pygame.transform.smoothscale(piece, (s['pw'], s['ph']))
                    piece = scale(piece, d.size)
                    if free:
                        piece = _shape_mask(piece, [(px - d.x, py - d.y) for px, py in world])
                    scr.blit(piece, d)
            else:
                _hatch(scr, d) if not free else pygame.draw.polygon(scr, C_STAGE, world)
        col = C_WARN if (warn or rect is None) else C_LINE
        if free:
            pygame.draw.polygon(scr, col, world, 1)
        else:
            pygame.draw.rect(scr, col, d, 1)
        if names:
            lab = f"{s['name']}  {s['pw']}x{s['ph']}" + (f"  @{s['ox']},{s['oy']}" if s['ox'] is not None else '')
            scr.blit(font.render(lab, True, C_TXT, C_BG), (d.x + 3, d.y + 3))
            if warn or rect is None:
                scr.blit(font.render(warn or 'sem ox/oy/pw/ph: fora do raster', True, C_WARN, C_BG), (d.x + 3, d.y + 19))
    # régua: 1 m
    pygame.draw.line(scr, C_DIM, (m, vh - 30), (m + k, vh - 30), 2)
    scr.blit(font.render('1 m', True, C_DIM), (m + k + 6, vh - 38))


def draw_raster(scr, font, fr, box, items, names, fmt):
    vw, vh = scr.get_size()
    fh, fw = fr.shape[:2] if fr is not None else (fmt[1], fmt[0])   # sem sinal: o mapa no raster vazio
    k = min(vw / fw, (vh - 22) / fh)
    dx, dy = (vw - fw * k) / 2, (vh - 22 - fh * k) / 2
    if fr is not None:
        img = pygame.transform.smoothscale(pygame.surfarray.make_surface(fr.swapaxes(0, 1)), (round(fw * k), round(fh * k)))
        scr.blit(img, (dx, dy))
    else:
        scr.fill((0, 0, 0), (dx, dy, fw * k, fh * k))
    pygame.draw.rect(scr, C_DIM, (dx + box[0] * k, dy + box[1] * k, box[2] * k, box[3] * k), 1)
    for s, rect, warn in items:
        if rect is None:
            continue
        r = pygame.Rect(round(dx + rect[0] * k), round(dy + rect[1] * k), round(rect[2] * k), round(rect[3] * k))
        pygame.draw.rect(scr, C_WARN if warn else (255, 220, 0), r, 1)
        if s['poly']:                                      # a forma acesa dentro do painel
            pygame.draw.polygon(scr, (255, 220, 0), [(r.x + u * r.w, r.y + v * r.h) for u, v in s['poly']], 1)
        if names:                                          # o mapa pra copiar no pixel map do prisma
            scr.blit(font.render(s['name'], True, C_TXT, C_BG), (r.x + 3, r.y + 3))
            scr.blit(font.render(f"{s['ox']},{s['oy']}  {s['pw']}×{s['ph']}", True, (255, 220, 0), C_BG), (r.x + 3, r.y + 19))


C_OK, C_YEL = (63, 208, 143), (232, 193, 74)


def run(args):
    wall = Wall(args.arquivo)
    fmt = parse_fmt(args.formato or '') or wall.fmt or (3840, 2160)
    plugged = not args.desplugado
    ann = Announce(args.nome)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # atexit apaga o anúncio
    state = {'fora': []}

    def commit():                                              # mudou o telão: raster, arquivo, anúncio
        state['fora'] = [t['name'] for t in wall.commit(fmt)]
        if plugged:
            ann.set(*fmt)
    commit()
    if args.prisma:                                            # depois do anúncio: o prisma lista as saídas ao abrir
        child = subprocess.Popen([sys.executable, os.path.join(HERE, 'native_synth.py')], cwd=os.path.dirname(HERE))
        atexit.register(lambda: child.poll() is None and child.terminate())
    grab = Grabber(args.janela, args.fps)
    pygame.init()
    scr = pygame.display.set_mode((args.largura, int(args.largura * 9 / 16)), pygame.RESIZABLE)
    font = pygame.font.SysFont('monospace', 13)
    big = pygame.font.SysFont('monospace', 15, bold=True)
    clock = pygame.time.Clock()
    view, names, pixelado, typing = args.vista, True, False, None
    ed = Editor(wall, commit)
    chips, top = [], 0

    def choose(w, h):
        nonlocal fmt
        fmt = (w, h)
        commit()

    def toggle_plug():
        nonlocal plugged
        plugged = not plugged
        commit() if plugged else ann.clear()

    try:
        while True:
            pygame.display.set_caption(f"telão simulado — {args.nome} {fmt[0]}×{fmt[1]}" + ('' if plugged else ' (desplugado)'))
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                body_pos = (e.pos[0], e.pos[1] - top) if hasattr(e, 'pos') else None
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    hit = next((act for r, act in chips if r.collidepoint(e.pos)), None)
                    if hit:
                        hit()
                    elif view == 'palco' and body_pos[1] >= 0 and ed.xf:
                        ed.down(body_pos, pygame.key.get_mods())
                    continue
                if e.type == pygame.MOUSEMOTION and view == 'palco' and ed.xf:
                    ed.motion(body_pos, pygame.key.get_mods())
                    continue
                if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    ed.up()
                    continue
                if e.type != pygame.KEYDOWN:
                    continue
                if typing is not None:                   # digitando o formato próprio
                    if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        f = parse_fmt(typing)
                        if f:
                            choose(*f)
                        typing = None
                    elif e.key == pygame.K_ESCAPE:
                        typing = None
                    elif e.key == pygame.K_BACKSPACE:
                        typing = typing[:-1]
                    elif e.unicode and e.unicode in '0123456789xX ':
                        typing += e.unicode
                    continue
                if view == 'palco' and ed.key(e):         # montar: lápis, seleção (Esc solta antes de sair)
                    continue
                if e.key == pygame.K_ESCAPE:
                    return
                if pygame.K_1 <= e.key <= pygame.K_8:
                    choose(*FORMATS[e.key - pygame.K_1][1:])
                elif e.key == pygame.K_e:
                    typing = ''
                elif e.key == pygame.K_d:
                    toggle_plug()
                elif e.key == pygame.K_TAB:
                    view = 'raster' if view == 'palco' else 'palco'
                    ed.pen = ed.drag = None
                elif e.key == pygame.K_n:
                    names = not names
                elif e.key == pygame.K_p:
                    pixelado = not pixelado
            with grab.lock:
                fr = grab.frame
            fh, fw = (fr.shape[:2] if fr is not None else (fmt[1], fmt[0]))
            vw, vh = scr.get_size()
            scr.fill(C_BG)

            # --- cabeçalho: tomada + formatos (clicáveis) + montar + ENTRADA
            chips, x, y = [], 8, 6
            def chip(txt, on, act, col=C_TXT):
                nonlocal x, y
                t = font.render(txt, True, (14, 14, 18) if on else col)
                if x > 8 and x + t.get_width() + 14 > vw - 8:     # quebra de linha
                    x, y = 8, y + 26
                r = pygame.Rect(x, y, t.get_width() + 14, 22)
                pygame.draw.rect(scr, col if on else (40, 40, 48), r, border_radius=5)
                scr.blit(t, (x + 7, y + 3))
                chips.append((r, act))
                x += r.w + 6
            def newline():
                nonlocal x, y
                x, y = 8, y + 26
            chip(f"{'●' if plugged else '○'} {args.nome} {'plugado' if plugged else 'desplugado'} [D]", plugged, toggle_plug, C_OK if plugged else C_WARN)
            for k, (n, w, h) in enumerate(FORMATS):
                chip(f"{k + 1} {n} {w}×{h}", fmt == (w, h), lambda w=w, h=h: choose(w, h))
            own = fmt not in [(w, h) for _, w, h in FORMATS]
            chip(f"E {typing + '▏' if typing is not None else (f'{fmt[0]}×{fmt[1]}' if own else 'próprio…')}",
                 own or typing is not None, lambda: None)
            newline()
            chip(f"{'▣ palco' if view == 'palco' else '▦ raster'} [Tab]", False, lambda: None, C_DIM)
            if view == 'palco':                          # montar o telão
                for n, w, h, pw, ph in ADD:
                    chip(f'+ {n}', False, lambda a=(n, w, h, pw, ph): ed.add(*a), C_YEL)
                chip('✎ desenhar [L]', ed.pen is not None, lambda: setattr(ed, 'pen', None if ed.pen is not None else []), C_YEL)
                if ed.sel is not None:
                    chip(f'forma: {shape_name(wall.screens[ed.sel])} [F]', False, lambda: ed.cycle_shape(1), C_SEL)
                    chip('↻ 15° [R]', False, lambda: (set_rot(wall.screens[ed.sel], (wall.screens[ed.sel].get('rot') or 0) + 15), commit()), C_SEL)
                    chip('⧉ [C]', False, lambda: ed.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c, mod=0)), C_SEL)
                    chip('× tirar [Del]', False, lambda: ed.key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE, mod=0)), C_WARN)
            lvl, txt = entrada((fw, fh) if fr is not None else None, fmt, plugged)
            col = {'ok': C_OK, 'warn': C_YEL, 'bad': C_WARN}[lvl]
            ey = y + 28
            pygame.draw.circle(scr, col, (16, ey + 9), 6)
            scr.blit(big.render('ENTRADA  ' + txt, True, col), (28, ey))
            top = ey + 24

            # --- corpo: palco montado (com o que chega recortado pelo mapa daqui) / raster
            body = scr.subsurface(pygame.Rect(0, top, vw, max(1, vh - top)))
            screens = clean_screens(wall.screens)
            mode, box, items = plan(screens, {'on': 1, 'w': fmt[0], 'h': fmt[1]}, fw, fh)
            if view == 'palco':
                if not ed.drag:                           # enquadramento parado durante o arrasto
                    ed.xf = stage_xf(screens, *body.get_size())
                draw_stage(body, font, fr, mode, items, ed.xf, names, pixelado)
                ed.draw(body, font)
            else:
                draw_raster(body, font, fr, box, items, names, fmt)
            hint = f"{len(screens)} tela(s) · raster {fmt[0]}×{fmt[1]}"
            if state['fora']:
                hint += ' · NÃO COUBE: ' + ', '.join(state['fora'])
            if fr is not None and abs(box[2] / fmt[0] - 1) > 1e-3:   # processadora mapeia pixel a pixel
                hint += f' · ESCALA x{box[2] / fmt[0]:.2f}, não 1:1'
            line = f"{hint} · {grab.status} · {clock.get_fps():.0f} fps · {wall.path}"
            scr.blit(font.render(line, True, C_WARN if state['fora'] else C_DIM), (8, vh - 18))
            pygame.display.flip()
            clock.tick(args.fps)
    finally:
        grab.close()
        ann.clear()
        pygame.quit()


def selfcheck():
    assert fit_box(200, 100, 100, 100) == (50.0, 0.0, 100.0, 100.0)
    assert fit_box(100, 200, 100, 100) == (0.0, 50.0, 100.0, 100.0)
    scr = clean_screens([
        {'name': 'a', 'x': 0, 'y': 0, 'w': 2, 'h': 1, 'pw': 200, 'ph': 100, 'ox': 0, 'oy': 0},
        {'name': 'b', 'x': 2, 'y': 0, 'w': 1, 'h': 1, 'pw': 100, 'ph': 100, 'ox': 200, 'oy': 0},
        {'name': 'c', 'x': 0, 'y': 1, 'w': 3, 'h': 1, 'pw': 300, 'ph': 100},
        {'name': 'lixo', 'x': 'q'},
    ])
    assert [s['name'] for s in scr] == ['a', 'b', 'c']
    assert stage_bounds(scr) == (0, 0, 3, 2)
    mode, box, it = plan(scr, {'on': 1, 'w': 400, 'h': 100}, 800, 400)   # raster 4:1 em janela 2:1
    assert mode == 'raster' and box == (0.0, 100.0, 800.0, 200.0)
    assert it[0][1] == (0.0, 100.0, 400.0, 200.0) and it[1][1] == (400.0, 100.0, 200.0, 200.0)
    assert it[2][1] is None
    _, _, it = plan(scr, {'on': 1, 'w': 250, 'h': 100}, 250, 100)         # b passa da borda
    assert 'borda' in it[1][2]
    scr[1]['ox'] = 100
    _, _, it = plan(scr, {'on': 1, 'w': 400, 'h': 100}, 400, 100)
    assert 'sobrepõe b' in it[0][2] and 'sobrepõe a' in it[1][2]
    mode, box, it = plan(scr, {'on': 0, 'w': 400, 'h': 100}, 300, 200)   # canvas 3:2 = janela
    assert mode == 'canvas' and box == (0.0, 0.0, 300.0, 200.0)
    assert it[1][1] == (200.0, 0.0, 100.0, 100.0) and it[2][1] == (0.0, 100.0, 300.0, 100.0)
    # forma livre: contorno girado no canvas
    fr = clean_screens([{'name': 'g', 'x': 0, 'y': 0, 'w': 2, 'h': 1, 'pw': 200, 'ph': 100, 'rot': 90,
                         'poly': [[0, 0], [1, 0], [0, 1]]}])
    assert fr[0]['rot'] == 90 and fr[0]['poly'] == [(0, 0), (1, 0), (0, 1)]
    assert [round(v, 6) for v in stage_bounds(fr)] == [0.5, -0.5, 1, 2]
    _, _, it = plan(fr, None, 100, 200)
    assert [round(v, 6) for v in it[0][1]] == [0, 0, 100, 200], it
    assert plan([], None, 10, 10)[0] == 'janela'
    # montar: canto girado segura o oposto; densidade mantida; lápis; telão salvo + raster
    t0 = {'name': 'a', 'x': 0, 'y': 0, 'w': 2, 'h': 1, 'pw': 200, 'ph': 100, 'rot': 30}
    t = resize_corner(t0, 'se', 0.5, 0.3)
    assert all(abs(a - b) < 2e-3 for a, b in zip(corner_world(t, 0, 0), corner_world(t0, 0, 0))), t
    assert t['pw'] == round(t['w'] * 100) and t['ph'] == round(t['h'] * 100)
    assert resize_corner(dict(t0, rot=0), 'nw', -1, 0)['x'] == -1 and resize_corner(dict(t0, rot=0), 'nw', -1, 0)['w'] == 3
    assert all(abs(a - b) < 1e-9 for a, b in zip(screen_uv(t0, *corner_world(t0, 0.25, 0.75)), (0.25, 0.75)))
    pn = pen_screen([(1, 1), (3, 1), (2, 2)], 100, 'f')
    assert (pn['x'], pn['y'], pn['w'], pn['h'], pn['pw']) == (1, 1, 2, 1, 200) and pn['poly'] == [[0, 0], [1, 0], [0.5, 1]], pn
    assert pen_screen([(0, 0), (1, 0)], 100, 'f') is None and pen_screen([(0, 0), (1, 0), (2, 0.01)], 100, 'f') is None
    assert norm_rot(190) == -170 and norm_rot(-180) == 180 and shape_name({'poly': SHAPES[1][1]}) == 'triângulo'
    import tempfile
    wp = os.path.join(tempfile.mkdtemp(), 'sub', 'w.json')
    w = Wall(wp)
    assert w.screens == [] and w.fmt is None
    w.screens = [dict(t0), {'name': 'b', 'x': 2, 'y': 0, 'w': 1, 'h': 1, 'pw': 5000, 'ph': 100}]
    assert [x['name'] for x in w.commit((1920, 1080))] == ['b'] and 'ox' in w.screens[0]
    w2 = Wall(wp)
    assert w2.fmt == (1920, 1080) and w2.screens == w.screens
    assert parse_fmt('3840x2160') == (3840, 2160) and parse_fmt(' 1080 × 1920 ') == (1080, 1920)
    assert parse_fmt('9x9') is None and parse_fmt('abc') is None
    assert entrada((3840, 2160), (3840, 2160), True)[0] == 'ok' and entrada((1366, 768), (3840, 2160), True)[0] == 'warn'
    assert entrada(None, (3840, 2160), True)[0] == 'bad' and entrada((3840, 2160), (3840, 2160), False)[0] == 'bad'
    import tempfile
    a = Announce('SIM-T', os.path.join(tempfile.gettempdir(), 'prisma-vo-sim-test.json'))
    a.set(4092, 1136)
    vo = dash_data.virtual_outputs(1366, a.path)
    assert vo and vo[0]['name'] == 'SIM-T' and (vo[0]['w'], vo[0]['h'], vo[0]['label']) == (4092, 1136, 'largo HDMI 1.4'), vo
    a.clear(); assert not os.path.exists(a.path)
    print('selfcheck ok')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--formato', help='formato do telão, LxA (padrão: o salvo, senão 3840x2160)')
    ap.add_argument('--nome', default='SIM-1', help='nome da saída virtual (padrão SIM-1)')
    ap.add_argument('--desplugado', action='store_true', help='abre sem anunciar (D pluga)')
    ap.add_argument('--janela', default='saída', help='trecho do título da janela de saída (padrão: "saída")')
    ap.add_argument('--arquivo', default=WALL_FILE, help=f'onde o telão montado fica salvo (padrão {WALL_FILE})')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--largura', type=int, default=1100, help='largura inicial da janela do simulador')
    ap.add_argument('--vista', choices=('palco', 'raster'), default='palco', help='vista inicial (Tab alterna)')
    ap.add_argument('--prisma', action='store_true', help='abre o prisma do repo junto, já vendo o telão')
    ap.add_argument('--selfcheck', action='store_true')
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        sys.exit(0)
    run(a)
