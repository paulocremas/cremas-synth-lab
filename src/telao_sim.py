#!/usr/bin/env python3
"""TELÃO VIRTUAL: deixa aberto e o prisma passa a ver um telão conectado. Enquanto aberto (e
"plugado"), anuncia a saída SIM-1 no formato escolhido (dash_data.VIRTUAL_OUTPUTS — o native e o
dash leem junto com o xrandr); o dash v2 reconhece sozinho (aba Saída > Telas do palco: telão
novo = "mapear agora"; formato trocado com a saída já nele = remapeia). O prisma abre a saída
"nela" (janela do tamanho do formato, fora da tela — o WM deixa uma tira à direita) e este app
captura a janela pelo id e faz o papel da processadora: confere a ENTRADA (sinal 1:1 com o
formato?), recorta cada tela de tuning.SCREENS e remonta o PALCO em metros, na resolução nativa
de cada painel. Padrão de teste: shaders/presets/default/Teste.frag (linha com degrau = mapa errado).

  PIXEL_MAP ligado   -> a janela é o RASTER w x h (encaixado com barras): recorta (ox, oy, pw, ph)
  PIXEL_MAP desligado -> a janela é o CANVAS (contorno das telas, encaixado): recorta pelos metros

Uso: .venv/bin/python src/telao_sim.py [--formato 3840x2160] [--nome SIM-1] [--desplugado]
     [--janela TITULO] [--tuning PATH] [--vista palco|raster] [--fps N] [--selfcheck]
Teclas: 1-8 / clique = formato · E = formato próprio (digita LxA, Enter) · D = plugar/desplugar ·
Tab = palco / raster capturado · N = nomes · P = pixelado · Esc = sair.
tuning.py: o MAIS RECENTE entre o do repo e o do app (~/.local/share/prisma/src), relido por mtime.
"""
import argparse
import atexit
import json
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
APP_TUNING = os.path.expanduser('~/.local/share/prisma/src/tuning.py')


# ---------- funções puras (testadas no --selfcheck) ----------

def fit_box(win_w, win_h, w, h):
    """Onde um retângulo w x h cai ENCAIXADO (barras no que sobra) numa janela win_w x win_h,
    em pixels com origem em cima: (x, y, w, h). Mesma regra do _canvas_box do native."""
    if not (win_w and win_h and w and h):
        return (0.0, 0.0, float(win_w), float(win_h))
    k = min(win_w / w, win_h / h)
    return ((win_w - w * k) / 2, (win_h - h * k) / 2, w * k, h * k)


def stage_bounds(screens):
    """Contorno das telas válidas em metros: (x0, y0, W, H) ou None."""
    v = [t for t in screens if t['w'] > 0 and t['h'] > 0]
    if not v:
        return None
    x0, y0 = min(t['x'] for t in v), min(t['y'] for t in v)
    return (x0, y0, max(t['x'] + t['w'] for t in v) - x0, max(t['y'] + t['h'] for t in v) - y0)


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
    for s in screens:
        out.append((s, (box[0] + (s['x'] - x0) / W * box[2], box[1] + (s['y'] - y0) / H * box[3],
                         s['w'] / W * box[2], s['h'] / H * box[3]), ''))
    return 'canvas', box, out


# ---------- tuning / janela / captura ----------

def pick_tuning(path):
    if path:
        return path
    cands = [p for p in (os.path.join(HERE, 'tuning.py'), APP_TUNING) if os.path.exists(p)]
    return max(cands, key=os.path.getmtime)


class Tuning:
    """SCREENS + PIXEL_MAP lidos do arquivo (exec num dict, sem importar), relidos por mtime."""

    def __init__(self, path):
        self.path, self.mtime, self.screens, self.pm, self.err = path, 0, [], None, ''

    def poll(self):
        try:
            m = os.path.getmtime(self.path)
            if m == self.mtime:
                return False
            self.mtime = m
            ns = {}
            exec(compile(open(self.path).read(), self.path, 'exec'), ns)
            self.screens, self.pm, self.err = clean_screens(ns.get('SCREENS')), ns.get('PIXEL_MAP'), ''
        except Exception as e:          # arquivo no meio de uma gravação: tenta de novo no próximo
            self.err, self.mtime = f'tuning: {e}', 0
        return True


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
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'pid': os.getpid(), 'outputs': [{'name': self.name, 'w': w, 'h': h, 'label': fmt_label(w, h)}]}, f)
        os.replace(tmp, self.path)

    def clear(self):
        try:
            with open(self.path) as f:
                if json.load(f).get('pid') != os.getpid():
                    return                    # outro simulador assumiu: não é meu
            os.remove(self.path)
        except (OSError, ValueError, AttributeError):
            pass


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


def _hatch(surf, r):
    surf.fill(C_STAGE, r)
    clip = surf.get_clip()
    surf.set_clip(r)
    for i in range(-r.h, r.w, 14):
        pygame.draw.line(surf, (60, 60, 70), (r.x + i, r.bottom), (r.x + i + r.h, r.y))
    surf.set_clip(clip)


def draw_stage(scr, font, fr, mode, items, screens, names, pixelado):
    vw, vh = scr.get_size()
    st = stage_bounds(screens)
    if not st:
        scr.blit(font.render('tuning.SCREENS vazio: cadastre as telas no dash v2 > Saída', True, C_TXT), (16, 16))
        return
    x0, y0, W, H = st
    m = 24
    k = min((vw - 2 * m) / W, (vh - 2 * m - 22) / H)
    ox, oy = (vw - W * k) / 2, (vh - 22 - H * k) / 2
    src = pygame.surfarray.make_surface(fr.swapaxes(0, 1)) if fr is not None else None
    fh, fw = (fr.shape[:2] if fr is not None else (0, 0))
    for s, rect, warn in items:
        d = pygame.Rect(round(ox + (s['x'] - x0) * k), round(oy + (s['y'] - y0) * k),
                        max(1, round(s['w'] * k)), max(1, round(s['h'] * k)))
        if rect is None or src is None:
            _hatch(scr, d)
        else:
            c = pygame.Rect(round(rect[0]), round(rect[1]), max(1, round(rect[2])), max(1, round(rect[3])))
            cc = c.clip(pygame.Rect(0, 0, fw, fh))
            if cc.w and cc.h:
                piece = pygame.Surface(c.size)
                piece.fill((0, 0, 0))                      # o que cai fora da janela = preto no painel
                piece.blit(src.subsurface(cc), (cc.x - c.x, cc.y - c.y))
                if s['pw'] > 0 and s['ph'] > 0:            # o painel só tem pw x ph LEDs
                    piece = pygame.transform.smoothscale(piece, (s['pw'], s['ph']))
                scale = pygame.transform.scale if pixelado else pygame.transform.smoothscale
                scr.blit(scale(piece, d.size), d)
            else:
                _hatch(scr, d)
        pygame.draw.rect(scr, C_WARN if (warn or rect is None) else C_LINE, d, 1)
        if names:
            lab = f"{s['name']}  {s['pw']}x{s['ph']}" + (f"  @{s['ox']},{s['oy']}" if s['ox'] is not None else '')
            scr.blit(font.render(lab, True, C_TXT, C_BG), (d.x + 3, d.y + 3))
            if warn or rect is None:
                scr.blit(font.render(warn or 'sem ox/oy/pw/ph: fora do raster', True, C_WARN, C_BG), (d.x + 3, d.y + 19))
    # régua: 1 m
    pygame.draw.line(scr, C_DIM, (m, vh - 30), (m + k, vh - 30), 2)
    scr.blit(font.render('1 m', True, C_DIM), (m + k + 6, vh - 38))


def draw_raster(scr, font, fr, box, items, names):
    vw, vh = scr.get_size()
    if fr is None:
        return
    fh, fw = fr.shape[:2]
    k = min(vw / fw, (vh - 22) / fh)
    dx, dy = (vw - fw * k) / 2, (vh - 22 - fh * k) / 2
    img = pygame.transform.smoothscale(pygame.surfarray.make_surface(fr.swapaxes(0, 1)), (round(fw * k), round(fh * k)))
    scr.blit(img, (dx, dy))
    pygame.draw.rect(scr, C_DIM, (dx + box[0] * k, dy + box[1] * k, box[2] * k, box[3] * k), 1)
    for s, rect, warn in items:
        if rect is None:
            continue
        r = pygame.Rect(round(dx + rect[0] * k), round(dy + rect[1] * k), round(rect[2] * k), round(rect[3] * k))
        pygame.draw.rect(scr, C_WARN if warn else (255, 220, 0), r, 1)
        if names:
            scr.blit(font.render(s['name'], True, C_TXT, C_BG), (r.x + 3, r.y + 3))


C_OK, C_YEL = (63, 208, 143), (232, 193, 74)


def run(args):
    tun = Tuning(pick_tuning(args.tuning))
    tun.poll()
    fmt = parse_fmt(args.formato) or (3840, 2160)
    plugged = not args.desplugado
    ann = Announce(args.nome)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # atexit apaga o anúncio
    if plugged:
        ann.set(*fmt)
    grab = Grabber(args.janela, args.fps)
    pygame.init()
    scr = pygame.display.set_mode((args.largura, int(args.largura * 9 / 16)), pygame.RESIZABLE)
    font = pygame.font.SysFont('monospace', 13)
    big = pygame.font.SysFont('monospace', 15, bold=True)
    clock = pygame.time.Clock()
    view, names, pixelado, typing = args.vista, True, False, None
    where = 'app' if tun.path == APP_TUNING else 'repo' if tun.path == os.path.join(HERE, 'tuning.py') else tun.path
    chips = []

    def choose(w, h):
        nonlocal fmt
        fmt = (w, h)
        if plugged:
            ann.set(*fmt)

    try:
        while True:
            pygame.display.set_caption(f"telão simulado — {args.nome} {fmt[0]}×{fmt[1]}" + ('' if plugged else ' (desplugado)'))
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    for r, act in chips:
                        if r.collidepoint(e.pos):
                            act()
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
                if e.key == pygame.K_ESCAPE:
                    return
                if pygame.K_1 <= e.key <= pygame.K_8:
                    choose(*FORMATS[e.key - pygame.K_1][1:])
                elif e.key == pygame.K_e:
                    typing = ''
                elif e.key == pygame.K_d:
                    plugged = not plugged
                    ann.set(*fmt) if plugged else ann.clear()
                elif e.key == pygame.K_TAB:
                    view = 'raster' if view == 'palco' else 'palco'
                elif e.key == pygame.K_n:
                    names = not names
                elif e.key == pygame.K_p:
                    pixelado = not pixelado
            tun.poll()
            with grab.lock:
                fr = grab.frame
            fh, fw = (fr.shape[:2] if fr is not None else (1, 1))
            vw, vh = scr.get_size()
            scr.fill(C_BG)

            # --- cabeçalho: tomada + formatos (clicáveis) + ENTRADA
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
            def toggle_plug():
                nonlocal plugged
                plugged = not plugged
                ann.set(*fmt) if plugged else ann.clear()
            chip(f"{'●' if plugged else '○'} {args.nome} {'plugado' if plugged else 'desplugado'} [D]", plugged, toggle_plug, C_OK if plugged else C_WARN)
            for k, (n, w, h) in enumerate(FORMATS):
                chip(f"{k + 1} {n} {w}×{h}", fmt == (w, h), lambda w=w, h=h: choose(w, h))
            own = fmt not in [(w, h) for _, w, h in FORMATS]
            chip(f"E {typing + '▏' if typing is not None else (f'{fmt[0]}×{fmt[1]}' if own else 'próprio…')}",
                 own or typing is not None, lambda: None)
            lvl, txt = entrada((fw, fh) if fr is not None else None, fmt, plugged)
            col = {'ok': C_OK, 'warn': C_YEL, 'bad': C_WARN}[lvl]
            ey = y + 28
            pygame.draw.circle(scr, col, (16, ey + 9), 6)
            scr.blit(big.render('ENTRADA  ' + txt, True, col), (28, ey))
            top = ey + 24

            # --- corpo: palco remontado / raster capturado
            body = scr.subsurface(pygame.Rect(0, top, vw, max(1, vh - top)))
            mode, box, items = plan(tun.screens, tun.pm, fw, fh)
            if fr is not None:
                if view == 'palco':
                    draw_stage(body, font, fr, mode, items, tun.screens, names, pixelado)
                else:
                    draw_raster(body, font, fr, box, items, names)
            hint = {'raster': 'pixel map %dx%d' % pmap_on(tun.pm) if pmap_on(tun.pm) else '',
                    'canvas': 'PIXEL_MAP desligado: chega o CANVAS (telão real precisa do raster)',
                    'janela': 'sem telas no palco'}[mode]
            if mode == 'raster' and fr is not None:
                k = box[2] / pmap_on(tun.pm)[0]
                if abs(k - 1) > 1e-3:          # processadora mapeia pixel a pixel: janela tem que ser = raster
                    hint += f' · ESCALA x{k:.2f}, não 1:1'
            line = f"{view} [Tab] · {hint} · {grab.status} · {clock.get_fps():.0f} fps · tuning: {where}"
            scr.blit(font.render(tun.err or line, True, C_WARN if tun.err else C_DIM), (8, vh - 18))
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
    assert plan([], None, 10, 10)[0] == 'janela'
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
    ap.add_argument('--formato', default='3840x2160', help='formato inicial do telão, LxA (padrão 3840x2160)')
    ap.add_argument('--nome', default='SIM-1', help='nome da saída virtual (padrão SIM-1)')
    ap.add_argument('--desplugado', action='store_true', help='abre sem anunciar (D pluga)')
    ap.add_argument('--janela', default='saída', help='trecho do título da janela de saída (padrão: "saída")')
    ap.add_argument('--tuning', help='caminho do tuning.py (padrão: o mais recente entre repo e app)')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--largura', type=int, default=1100, help='largura inicial da janela do simulador')
    ap.add_argument('--vista', choices=('palco', 'raster'), default='palco', help='vista inicial (Tab alterna)')
    ap.add_argument('--selfcheck', action='store_true')
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        sys.exit(0)
    run(a)
