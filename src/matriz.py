"""MATRIZ DE EMERGENCIA (shaders/ATOMO.md §11): o teste do Eurorack automatizado. Todo atomo de
shaders/presets/atomos/ e' compilado COM o preludio (dash_data.atom_source) e renderizado pequeno, offscreen:
  - sozinho: sem NaN/Inf, sem tela chapada (salvo mascara sem deteccao), mesma forma em 2 tamanhos;
  - NEUTRO: principal no neutro (0, ou 0.5 se // bipolar:) + todo bipolar em 0.5 = a entrada (quem desenha,
    alfa < 1, tem o "quanto" na opacidade da peca — fica de fora);
  - todo par A -> B (B le o resultado de A composto na corrente) e todo atomo como entrada B de todo leitor de B;
  - TRANSPARENCIA (o fio leva o alfa): filtro nao fura a corrente opaca; entrada com vazio -> sem NaN, cor nao mexe na
    cobertura; junta como o motor (dash_data.atom_replaces: filtro = TROCA, quem desenha = POR CIMA);
  - ESTADO: 300 passos com a entrada andando -> nao satura nem morre; limpar zera; todo filtro no loop RETORNO;
  - EM CIMA (PLANO_CONVERSA.md §2): todo par X ↑ Y (Y solto em cima de X age so' na MARCA de X): sem NaN; cor/luz em cima
    deixa o FUNDO intacto (onde X nao mexeu sai a entrada); Y no neutro = X sozinho; com memoria em cima roda.
Falhou = buraco no CONTRATO (ou o atomo quebra o contrato), nao "combinacao proibida".
Sem GL (CI sem tela/GPU) -> run() devolve None e o selfcheck so' avisa. `python src/matriz.py [pasta]` roda
sozinho e, com pasta, grava PNGs de cada atomo (olhar a forma)."""
import glob
import os
import re
import sys

import numpy as np

import dash_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATOM_DIR = os.path.join(ROOT, 'shaders', 'presets', 'atomos')
VERT = 'attribute vec2 a_pos;\nvoid main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n'
UNITS = {'u_texture_0': 0, 'u_texture_1': 1, 'u_texture_2': 2, 'u_texture_src': 3, 'u_state': 4, 'u_subject': 5}
STEPS = 300


class Ctx:
    """Contexto GL escondido (pygame) + o minimo pra desenhar um atomo numa textura RGBA16F."""

    def __init__(self):
        import pygame
        os.environ.setdefault('SDL_VIDEO_WINDOW_POS', '-4000,-4000')
        pygame.display.init()
        pygame.display.set_mode((16, 16), pygame.OPENGL | pygame.DOUBLEBUF | pygame.HIDDEN)
        from OpenGL import GL
        self.gl = GL
        ver = GL.glGetString(GL.GL_VERSION).decode(errors='replace')
        if int(re.match(r'(\d+)', ver).group(1)) < 3:
            raise RuntimeError('OpenGL ' + ver)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, np.array([-1, -1, 3, -1, -1, 3], np.float32), GL.GL_STATIC_DRAW)
        self.fbo = GL.glGenFramebuffers(1)
        self.progs = {}

    def compile(self, rel, src):
        GL = self.gl
        prog = GL.glCreateProgram()
        for kind, code in ((GL.GL_VERTEX_SHADER, VERT), (GL.GL_FRAGMENT_SHADER, dash_data.atom_source(rel, src))):
            sh = GL.glCreateShader(kind)
            GL.glShaderSource(sh, code)
            GL.glCompileShader(sh)
            if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(sh).decode(errors='replace'))
            GL.glAttachShader(prog, sh)
        GL.glBindAttribLocation(prog, 0, 'a_pos')
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode(errors='replace'))
        return prog

    def tex(self, w, h, img=None):
        """Textura RGBA16F; img = float32 (h, w, 4) com a linha 0 = a de CIMA (topo->baixo, como as fontes do motor)."""
        GL = self.gl
        t = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, t)
        for pn, pv in ((GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE),
                       (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, pn, pv)
        data = None if img is None else np.ascontiguousarray(img, np.float32)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA16F, w, h, 0, GL.GL_RGBA, GL.GL_FLOAT, data)
        if img is None:
            self.clear(t)
        return t

    def clear(self, t):
        GL = self.gl
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, t, 0)
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

    def draw(self, prog, dst, w, h, uni, texs):
        GL = self.gl
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, dst, 0)
        GL.glViewport(0, 0, w, h)
        GL.glUseProgram(prog)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
        for n, v in uni.items():
            loc = GL.glGetUniformLocation(prog, n)
            if loc >= 0:
                (GL.glUniform2f(loc, *v) if isinstance(v, tuple) else GL.glUniform1f(loc, float(v)))
        for n, unit in UNITS.items():
            loc = GL.glGetUniformLocation(prog, n)
            if loc >= 0:
                GL.glUniform1i(loc, unit)
                GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
                GL.glBindTexture(GL.GL_TEXTURE_2D, texs.get(n, texs['blank']))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)

    def read(self, t, w, h):
        """-> float32 (h, w, 4), linha 0 = a de CIMA (o atomo escreve em gl_FragCoord: vira aqui)."""
        GL = self.gl
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, t, 0)
        a = GL.glReadPixels(0, 0, w, h, GL.GL_RGBA, GL.GL_FLOAT)
        return np.frombuffer(a, np.float32).reshape(h, w, 4)[::-1].copy()

    def free(self, *ts):
        self.gl.glDeleteTextures(list(ts))


def test_image(w, h, t=0.0, kind=0):
    """Imagem de teste CONTINUA em uv (a mesma forma em qualquer tamanho): degrade + disco + listras suaves;
    t anda a imagem pra direita (fracao da largura). kind 1 = outra (pra B). float32 (h, w, 4), topo->baixo."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = (x + 0.5) / w - t, (y + 0.5) / h
    asp = w / h
    d = np.hypot((u - 0.45) * asp, v - 0.5)
    disc = 1.0 / (1.0 + np.exp((d - 0.28) * 40.0))
    if kind:
        r = 0.5 + 0.5 * np.sin(u * 9.0 + v * 4.0)
        g = 0.5 + 0.5 * np.cos(v * 7.0 - u * 3.0)
        b = disc
    else:
        r = np.clip(u * 0.8 + disc * 0.5, 0, 1)
        g = np.clip(0.3 + 0.4 * np.sin(v * 6.0) * (1 - disc) + disc * 0.6, 0, 1)
        b = np.clip(1.0 - v * 0.7 + 0.2 * np.sin(u * 12.0), 0, 1)
    return np.dstack([r, g, b, np.ones_like(r)]).astype(np.float32)


def atoms():
    """[(nome, rel, src, meta, fx padrao)] de todos os atomos da pasta."""
    out = []
    for f in sorted(glob.glob(os.path.join(ATOM_DIR, '*.frag'))):
        src = open(f, encoding='utf-8').read()
        out.append((os.path.basename(f)[:-5], 'presets/atomos/' + os.path.basename(f), src, dash_data.parse_meta(src),
                    dash_data.parse_fx_defaults(src)))
    return out


def comp(base, layer, a=1.0, troca=True):
    """Junta a camada na corrente como o motor (blend modo normal, alfa DIRETO: o fio leva a transparencia).
    troca = FILTRO (u_aout 5: a saida substitui a entrada, o alfa e' o dela); False = quem DESENHA (u_aout 3: por cima).
    Base opaca = o mesmo resultado nos dois."""
    ba, la = np.clip(base[..., 3:4], 0, 1), np.clip(layer[..., 3:4], 0, 1)
    bc, lc = base[..., :3], np.clip(layer[..., :3], 0, 1)
    if troca:
        oa = ba * (1 - a) + la * a
        pre = bc * ba * (1 - a) + lc * la * a
    else:
        k = la * a
        oa = k + ba * (1 - k)
        pre = lc * k + bc * ba * (1 - k)
    out = np.empty_like(base)
    out[..., :3] = np.where(oa > 0, pre / np.maximum(oa, 1e-6), 0.0)
    out[..., 3:4] = oa
    return out


def marca(inp, out):
    """MARCA de um FILTRO (STACK_SRC op 0): a saida onde ela difere da entrada (pre-multiplicada, o maior canal)."""
    d = np.abs(np.concatenate([out[..., :3] * out[..., 3:4], out[..., 3:4]], -1) -
               np.concatenate([inp[..., :3] * inp[..., 3:4], inp[..., 3:4]], -1)).max(-1, keepdims=True)
    t = np.clip((d - dash_data.MARCA_LO) / (dash_data.MARCA_HI - dash_data.MARCA_LO), 0, 1)
    o = out.copy()
    o[..., 3:4] = out[..., 3:4] * t * t * (3 - 2 * t)
    return o


def em_cima(lay, top, a=1.0, troca=True):
    """Junta o de cima na marca (STACK_SRC): troca = op 2 (cor/espaco/memoria, opacidade a); senao op 1 (DENTRO)."""
    o = np.empty_like(lay)
    if not troca:
        k = np.clip(top[..., 3:4] * a, 0, 1)
        o[..., :3] = lay[..., :3] * (1 - k) + top[..., :3] * k
        o[..., 3:4] = lay[..., 3:4]
        return o
    oa = lay[..., 3:4] * (1 - a) + top[..., 3:4] * a
    c = lay[..., :3] * lay[..., 3:4] * (1 - a) + top[..., :3] * top[..., 3:4] * a
    o[..., :3] = np.where(oa > 0, c / np.maximum(oa, 1e-6), 0.0)
    o[..., 3:4] = oa
    return o


class Matriz:
    def __init__(self, ctx):
        self.c = ctx
        self.at = {n: (rel, src, meta, fx) for n, rel, src, meta, fx in atoms()}
        self.fail = []
        self.warn = []
        self.blank = None
        self.tx = {}

    def prog(self, n):
        if n not in self.c.progs:
            rel, src = self.at[n][:2]
            self.c.progs[n] = self.c.compile(rel, src)
        return self.c.progs[n]

    def render(self, n, a_img, b_img=None, fx=None, steps=0, move=0.0, ret=None, keep=None):
        """Atomo n sobre a imagem A (topo->baixo) -> camada RGBA topo->baixo. Com // estado: roda `steps` passos
        (a entrada anda `move` por passo) e mostra. ret = atomo no loop RETORNO. keep = {} guarda o estado."""
        c = self.c
        h, w = a_img.shape[:2]
        rel, src, meta, dfx = self.at[n]
        fx = dict(dfx, **(fx or {}))
        uni = {'u_resolution': (float(w), float(h)), 'u_time': 1.25, 'u_dt': 1.0 / 60.0, 'u_seed': 0.37,
               'u_beat': 0.25, 'u_bar': 0.5, 'u_phrase': 0.1, 'u_vista': 0.0, 'u_agl': 0.0}
        uni.update({'u_fx_' + k: v for k, v in fx.items()})
        texs = {'blank': self.blank_tex(w, h)}
        made = []

        def up(img):
            t = c.tex(w, h, img)
            made.append(t)
            return t
        texs['u_texture_0'] = up(a_img)
        texs['u_texture_src'] = texs['u_texture_0']
        texs['u_texture_1'] = up(b_img if b_img is not None else a_img)
        out_t = c.tex(w, h)
        made.append(out_t)
        est = meta.get('estado')
        if est:                                           # como o motor: linhas do estado = escala x referencia FIXA
            sh = max(8, int(round(108 * est['escala'])))  # (108 = 1080 / 10), nao o tamanho do render
            sw = max(8, int(round(sh * w / h)))
            st = keep.get('st') if keep is not None and keep.get('st') else [c.tex(sw, sh), c.tex(sw, sh)]
            cur = keep.get('cur', 0) if keep is not None else 0
            sdt = 1.0 / (60.0 * est['passos'])
            for i in range(steps):
                if move:
                    c.free(texs['u_texture_0'])
                    made.remove(texs['u_texture_0'])
                    texs['u_texture_0'] = texs['u_texture_src'] = up(test_image(w, h, move * i))
                if ret:
                    rp = self.prog(ret)
                    ru = dict(uni, u_agl=1.0, u_dt=sdt, u_resolution=(float(sw), float(sh)), **{'u_fx_' + k: v for k, v in self.at[ret][3].items()})
                    c.draw(rp, st[1 - cur], sw, sh, ru, dict(texs, u_texture_0=st[cur]))
                    cur = 1 - cur
                for f in range(est['fases']):
                    c.draw(self.prog(n), st[1 - cur], sw, sh, dict(uni, u_dt=sdt, u_fase=float(f), u_semear=float(i == 0),
                                                                   u_resolution=(float(sw), float(sh))), dict(texs, u_state=st[cur]))
                    cur = 1 - cur
            c.draw(self.prog(n), out_t, w, h, dict(uni, u_vista=1.0), dict(texs, u_state=st[cur]))
            if keep is not None:
                keep.update(st=st, cur=cur)
            else:
                c.free(*st)
        else:
            c.draw(self.prog(n), out_t, w, h, uni, texs)
        out = c.read(out_t, w, h)
        c.free(*made)
        return out

    def blank_tex(self, w, h):
        if (w, h) not in self.tx:
            self.tx[(w, h)] = self.c.tex(w, h, np.zeros((h, w, 4), np.float32))
        return self.tx[(w, h)]

    def comp(self, n, base, layer, a=1.0):
        """comp com a regra do atomo n (dash_data.atom_replaces)."""
        return comp(base, layer, a, troca=self.troca(n))

    def troca(self, n):
        """filtro (TROCA) ou desenha (POR CIMA): a mesma deducao do motor, com o // entra: do desenvolvedor."""
        return dash_data.atom_replaces(self.at[n][0], self.at[n][1])

    def bad(self, what, why):
        self.fail.append(f'{what}: {why}')

    def check_img(self, what, img, flat_ok=False):
        if not np.isfinite(img).all():
            self.bad(what, 'NaN/Inf')
            return False
        if not flat_ok and img[..., :3].std() < 1e-3 and img[..., 3].std() < 1e-3:
            self.bad(what, f'tela chapada ({img[..., :3].mean():.3f})')
            return False
        return True

    def run(self, png_dir=None):
        W, H = 64, 36
        A, B = test_image(W, H), test_image(W, H, kind=1)
        names = sorted(self.at)
        for n in names:                                   # compila
            try:
                self.prog(n)
            except RuntimeError as e:
                self.bad(n, 'nao compila: ' + str(e).strip().splitlines()[0][:200])
        names = [n for n in names if n in self.c.progs]
        for n in names:                                   # contrato: QUEBRA reprova; FORA DO PADRAO so' avisa (PLANO_CONVERSA §9.3)
            ck = dash_data.atom_check(self.at[n][1])
            for q in ck['quebra']:
                self.bad(n, q)
            self.warn += [f'{n}: {w}' for w in ck['avisos']]
        masks = [n for n in names if self.at[n][2]['cat'] == 'mascara']
        flt = [n for n in names if n not in masks]
        solo = {}
        for n in names:                                   # sozinho + 2 tamanhos
            meta = self.at[n][2]
            steps = 60 if meta.get('estado') else 0
            o = self.render(n, A, B, steps=steps, move=0.004)
            solo[n] = o
            if not self.check_img(n, o, flat_ok=n in masks):
                continue
            if png_dir:
                _png(os.path.join(png_dir, n + '.png'), self.comp(n, A, o) if n not in masks else o)
            big = self.render(n, test_image(W * 2, H * 2), test_image(W * 2, H * 2, kind=1), steps=steps, move=0.004)
            d = np.abs(_blocks(self.comp(n, A, o)) - _blocks(self.comp(n, test_image(W * 2, H * 2), big))).mean()
            if d > 0.05:
                self.bad(n, f'forma muda com a resolucao (diferenca {d:.3f}: pixel fixo?)')
        for n in flt:                                     # NEUTRO = identidade
            rel, src, meta, fx = self.at[n]
            if not fx or meta['cat'] == 'gerador' or solo[n][..., 3].mean() < 0.98:
                continue                                  # sem knob / gerador / quem desenha: o "quanto" e' a opacidade
            k = next(iter(fx))
            if k in (meta.get('escolha') or {}) or k in (meta.get('chave') or []):
                continue
            bip = meta.get('bipolar') or []
            nfx = {b: 0.5 for b in bip}
            nfx[k] = 0.5 if k in bip else 0.0
            o = self.render(n, A, B, fx=nfx, steps=10 if meta.get('estado') else 0)
            d = np.abs(self.comp(n, A, o)[..., :3] - A[..., :3])
            if d.mean() > 2.0 / 255 or d.max() > 0.08:
                self.bad(n, f'principal {k}={nfx[k]} nao e\' neutro (media {d.mean() * 255:.1f}/255)')
        TA = A.copy()                                     # TRANSPARENCIA (§1): o fio leva o alfa — 40% da direita vazio
        TA[:, int(W * 0.6):, 3] = 0.0
        for n in flt:
            draws = not self.troca(n)
            if not draws and solo[n][..., 3].min() < 0.98:   # filtro na corrente opaca: tem que continuar opaca (TROCA)
                self.bad(n, f'filtro FURA a corrente opaca (alfa min {solo[n][..., 3].min():.2f}): devolva o alfa que leu')
            if self.at[n][2].get('estado'):
                continue                                  # (o teste de estado anda a entrada: fica de fora)
            o = self.render(n, TA, B)
            if not self.check_img(f'{n} na transparencia', o, flat_ok=True):
                continue
            if self.at[n][2]['cat'] == 'cor' and np.abs(o[..., 3] - TA[..., 3]).max() > 0.01:
                self.bad(n, 'cor mexeu na cobertura (transparente nao continuou transparente)')
            self.check_img(f'{n} na transparencia (junto)', self.comp(n, TA, o), flat_ok=True)
        readers = [n for n in flt if self.at[n][2]['ins']]
        for a in flt:                                     # todo par A -> B; todo atomo como B de todo leitor de B
            ca = self.comp(a, A, solo[a])
            for b in flt:
                o = self.render(b, ca, B, steps=8 if self.at[b][2].get('estado') else 0)
                self.check_img(f'{a} -> {b}', self.comp(b, ca, o), flat_ok=True)
            for r in readers:
                o = self.render(r, A, ca)
                self.check_img(f'{a} como B de {r}', self.comp(r, A, o), flat_ok=True)
        draws = lambda n: not self.troca(n)
        for x in flt:                                     # EM CIMA: Y age so' na MARCA de X (PLANO_CONVERSA §2)
            if self.at[x][2].get('estado'):
                continue                                  # (em cima de quem tem memoria = loop RETORNO, testado abaixo)
            mudou = dash_data.atom_marca(self.at[x][0], self.at[x][1]) == 'mudanca'
            m = np.clip(marca(A, solo[x]) if mudou else solo[x], 0, 1)   # o de cima le a marca pelo fio de 8 bits (lt['chain'])
            alone = self.comp(x, A, solo[x])
            for y in flt:
                ym = self.at[y][2]
                st = 8 if ym.get('estado') else 0
                o = self.render(y, m, B, steps=st)
                out = comp(A, em_cima(m, o, troca=not draws(y)), troca=False)
                if not self.check_img(f'{x} ↑ {y}', out, flat_ok=True):
                    continue
                if ym['cat'] in ('cor', 'luz') and y != 'Brilhar':   # (Brilhar espalha: o halo sai da marca, de proposito)
                    calm = m[..., 3] < 1e-3
                    if calm.any() and np.abs(out[..., :3] - A[..., :3])[calm].max() > 2.0 / 255:
                        self.bad(f'{x} ↑ {y}', 'mexeu no FUNDO (onde o de baixo nao fez nada)')
                fx = self.at[y][3]
                if not fx or ym['cat'] == 'gerador' or draws(y) or st:
                    continue
                k = next(iter(fx))
                if k in (ym.get('escolha') or {}) or k in (ym.get('chave') or []):
                    continue
                bip = ym.get('bipolar') or []
                nfx = {b: 0.5 for b in bip}
                nfx[k] = 0.5 if k in bip else 0.0
                o = self.render(y, m, B, fx=nfx)
                d = np.abs(comp(A, em_cima(m, o), troca=False)[..., :3] - alone[..., :3])
                if d.mean() > 2.0 / 255 or d.max() > 0.05:
                    self.bad(f'{x} ↑ {y}', f'{y} no neutro nao some (media {d.mean() * 255:.1f}/255, max {d.max():.3f})')
        for n in [n for n in flt if self.at[n][2].get('estado')]:   # ESTADO: 300 passos, limpar, loop retorno
            keep = {}
            o = self.render(n, A, B, steps=STEPS, move=0.003, keep=keep)
            v = self.comp(n, A, o)
            if self.check_img(f'{n} {STEPS} passos', o, flat_ok=True):
                if o[..., :3].min() > 0.98 and o[..., 3].min() > 0.98:
                    self.bad(n, f'estado SATUROU em {STEPS} passos')
                if v.std() < 1e-3:
                    self.bad(n, f'estado MORREU em {STEPS} passos')
            for t in keep['st']:
                self.c.clear(t)                           # limpar = o motor zera o buffer
            sh = max(8, int(round(108 * self.at[n][2]['estado']['escala'])))
            z = self.c.read(keep['st'][keep['cur']], max(8, int(round(sh * W / H))), sh)
            if np.abs(z).max() > 0:
                self.bad(n, 'limpar nao zerou')
            self.c.free(*keep['st'])
            for r in flt:
                if self.at[r][2].get('estado'):
                    continue
                o = self.render(n, A, B, steps=30, move=0.003, ret=r)
                self.check_img(f'{n} ↻ {r}', self.comp(n, A, o), flat_ok=True)
        return self.fail


def _blocks(img, bw=16, bh=9):
    h, w = img.shape[:2]
    return img[:h // bh * bh, :w // bw * bw, :3].reshape(bh, h // bh, bw, w // bw, 3).mean(axis=(1, 3))


def _png(path, img):
    try:
        import pygame
        a = (np.clip(img[..., :3], 0, 1) * 255).astype(np.uint8)
        pygame.image.save(pygame.surfarray.make_surface(a.transpose(1, 0, 2)), path)
    except Exception as e:   # PNG e' so' pra olhar; nao derruba a matriz
        print('png ->', e)


def run(png_dir=None):
    """-> lista de falhas ([] = ok) ou None sem GL."""
    try:
        ctx = Ctx()
    except Exception as e:
        print('matriz de emergencia: sem GL aqui (' + str(e).splitlines()[0][:80] + ') — pulada')
        return None
    m = Matriz(ctx)
    fails = m.run(png_dir)
    n = len(m.at)
    print(f'matriz de emergencia: {n} atomos, {n * n} pares, {len(fails)} falhas, {len(m.warn)} fora do padrao')
    for w in m.warn:
        print('  ⚠', w)
    return fails


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else None
    if d:
        os.makedirs(d, exist_ok=True)
    f = run(d)
    for x in f or ():
        print('  -', x)
    sys.exit(1 if f else 0)
