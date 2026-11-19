"""TESTES DE GESTO do dash5 (/v5): o dash de verdade num navegador headless, mexido com mouse de verdade (CDP).

Por que: cada correcao de usabilidade era checada so' na sintaxe; o "conserta um, quebra outro" chegava no usuario.
Aqui cada gesto da revisao (Claude Doc "PRISMA — revisão de usabilidade") vira um teste: clique, direito, 2 cliques,
arrastar cabo, girar knob — com hover, captura de ponteiro e elementFromPoint iguais aos da mao.

Isolado: sobe o dash_server numa porta propria com uma COPIA temporaria do tuning.py (o do repo nao e' tocado) e um
perfil de navegador temporario. So' stdlib (cliente WebSocket minimo pro CDP). Precisa de Chromium/Brave/Chrome.

    .venv/bin/python tests/dash_gestos.py            # roda tudo; sai 1 se algum falhar
    .venv/bin/python tests/dash_gestos.py cabo knob  # so' os que tem essas palavras no nome
"""
import base64
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

_HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')   # o src/ do repo
sys.path.insert(0, _HERE)
PORT, CDP_PORT = 8799, 9333
BROWSERS = ('chromium', 'chromium-browser', 'google-chrome', 'brave-browser', 'microsoft-edge')


# ---------------------------------------------------------------- CDP (WebSocket minimo, so' stdlib)
class CDP:
    def __init__(self, ws_url):
        host_port, path = ws_url[len('ws://'):].split('/', 1)
        host, port = host_port.split(':')
        self.s = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.s.recv(4096)
        self.rest = buf.split(b'\r\n\r\n', 1)[1]
        self.n, self.events = 0, []

    def _recv(self, k):
        while len(self.rest) < k:
            d = self.s.recv(65536)
            if not d:
                raise ConnectionError('CDP fechou')
            self.rest += d
        out, self.rest = self.rest[:k], self.rest[k:]
        return out

    def _frame(self):
        msg = b''
        while True:
            b0, b1 = self._recv(2)
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack('>H', self._recv(2))[0]
            elif ln == 127:
                ln = struct.unpack('>Q', self._recv(8))[0]
            msg += self._recv(ln)
            if b0 & 0x80:
                return msg

    def send(self, method, **params):
        self.n += 1
        data = json.dumps({'id': self.n, 'method': method, 'params': params}).encode()
        hdr = bytes([0x81])
        ln = len(data)
        hdr += bytes([0x80 | ln]) if ln < 126 else (bytes([0x80 | 126]) + struct.pack('>H', ln) if ln < 65536
                                                   else bytes([0x80 | 127]) + struct.pack('>Q', ln))
        mask = os.urandom(4)
        self.s.sendall(hdr + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))
        while True:
            m = json.loads(self._frame())
            if m.get('id') == self.n:
                if 'error' in m:
                    raise RuntimeError(f'{method}: {m["error"]}')
                return m.get('result', {})
            self.events.append(m)

    def js(self, expr):
        """avalia na pagina (await ok) e devolve o valor JSON"""
        r = self.send('Runtime.evaluate', expression=f'(async () => {{ {expr} }})()', awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in r:
            raise RuntimeError('js: ' + json.dumps(r['exceptionDetails'].get('exception', {}).get('description', r['exceptionDetails']))[:600])
        return r.get('result', {}).get('value')

    mods = 0   # 2 = Ctrl, 8 = Shift (vale pro proximo gesto: c.mods = 2; ...; c.mods = 0)

    def mouse(self, kind, x, y, button='none', clicks=0, buttons=0):
        self.send('Input.dispatchMouseEvent', type=kind, x=x, y=y, button=button, clickCount=clicks, buttons=buttons, modifiers=self.mods)

    def click(self, x, y, button='left', clicks=1):
        b = {'left': 1, 'right': 2, 'middle': 4}[button]
        self.mouse('mouseMoved', x, y)
        self.mouse('mousePressed', x, y, button, clicks, b)
        self.mouse('mouseReleased', x, y, button, clicks, 0)

    def drag(self, pts, button='left', check=None, cancel=False):
        """aperta no 1o ponto, passa por todos (em passos), solta no ultimo; check(i) roda no meio de cada trecho"""
        b = {'left': 1, 'right': 2}[button]
        x, y = pts[0]
        self.mouse('mouseMoved', x, y)
        self.mouse('mousePressed', x, y, button, 1, b)
        out = []
        for i, (nx, ny) in enumerate(pts[1:]):
            for k in range(1, 9):
                self.mouse('mouseMoved', x + (nx - x) * k / 8, y + (ny - y) * k / 8, button, 0, b)
                if k == 4 and check:
                    out.append(check(i))
            x, y = nx, ny
        if cancel:   # Esc ANTES de soltar = o gesto e' cancelado (nao liga nada)
            self.key('Escape')
        self.mouse('mouseReleased', x, y, button, 1, 0)
        return out

    def key(self, k, mods=0):
        code = {'Escape': 'Escape', 'Delete': 'Delete'}.get(k, 'Key' + k.upper() if len(k) == 1 else k)
        vk = {'Escape': 27, 'Delete': 46}.get(k, ord(k.upper()) if len(k) == 1 else 0)
        for t in ('keyDown', 'keyUp'):
            self.send('Input.dispatchKeyEvent', type=t, key=k, code=code, windowsVirtualKeyCode=vk, modifiers=mods)


# ---------------------------------------------------------------- ambiente isolado
def boot():
    tmp = tempfile.mkdtemp(prefix='prisma-gestos-')
    tpath = os.path.join(tmp, 'tuning.py')
    shutil.copy(os.path.join(_HERE, 'tuning.py'), tpath)
    spec = importlib.util.spec_from_file_location('tuning', tpath)
    tun = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tun)
    sys.modules['tuning'] = tun
    import dash_server
    dash_server.start({}, tun, tpath, lambda: True, port=PORT, open_browser=False)
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json/version', timeout=0.5)
        sys.exit(f'a porta {CDP_PORT} ja tem um navegador (de uma rodada velha?): feche ele antes (pkill -f prisma-gestos-)')
    except OSError:
        pass
    exe = next((shutil.which(b) for b in BROWSERS if shutil.which(b)), None)
    if not exe:
        sys.exit('sem Chromium/Brave/Chrome no PATH')
    br = subprocess.Popen([exe, '--headless=new', f'--remote-debugging-port={CDP_PORT}', f'--user-data-dir={tmp}/perfil',
                           '--window-size=1366,768', '--no-first-run', '--no-default-browser-check', '--disable-gpu', 'about:blank'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)   # grupo proprio: sair mata TODOS os processos dele
    for _ in range(100):
        try:
            pages = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json/list', timeout=1))
            pg = next(p for p in pages if p.get('type') == 'page')
            break
        except Exception:
            time.sleep(0.1)
    else:
        br.kill()
        sys.exit('o navegador nao abriu o CDP')
    c = CDP(pg['webSocketDebuggerUrl'])
    c.send('Runtime.enable')
    c.send('Page.enable')
    return c, br, tmp, tpath


def kill_browser(br):
    """mata o navegador E os filhos dele (o Brave/Chrome do sistema e' um script que deixa o processo real orfao: ele ficava
    segurando a porta do CDP e a rodada seguinte conversava com o navegador VELHO -> falhas aleatorias)"""
    import signal
    try:
        os.killpg(br.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        br.kill()
    br.wait()


def load(c, sel=None):
    """abre o /v5?html (o canvas HTML de reserva) em MONTAR, espera os nos aparecerem; sel = v5sel guardado antes (pra testar o 'abre fechado')"""
    c.send('Page.navigate', url=f'http://127.0.0.1:{PORT}/v5?html')   # o canvas HTML (reserva): o principal e' o jogo (testes t6_*)
    time.sleep(0.4)
    c.js(f"localStorage.setItem('v5mode', JSON.stringify('montar')); {'localStorage.setItem(\"v5sel\", ' + json.dumps(json.dumps(sel)) + ');' if sel else ''} return 1")
    c.send('Page.reload')
    for _ in range(80):
        time.sleep(0.15)
        try:
            if c.js("return document.querySelectorAll('#cv-in .bx').length") > 0:
                break
        except RuntimeError:
            pass
    c.js("if (mode !== 'montar') setMode('montar'); return 1")
    time.sleep(0.4)


def fixture(c):
    """cena FIXA do teste (nao depende do tuning): camera -> Contornar -> Matiz -> saida"""
    ok = c.js("""lastOverlays = lastOverlays.filter(o => !isTapKey(o.file) && !o.kind && !o.dup);   // do zero: so' as fontes
      for (const k of Object.keys(lastBindings)) delete lastBindings[k];
      sel = { key: '', j: -1 }; msel.clear(); selWire = null; cable = null; closeWheel(); document.querySelectorAll('.nmenu').forEach(x => x.remove());
      lastOverlays.forEach((o, i) => { o.xy = [40, 160 + i * 300]; });
      const src = lastOverlays.find(o => !isTapKey(o.file)); if (!src) return 'sem fonte';
      const A = 'presets/atomos/Contornar.frag', B = 'presets/atomos/Matiz.frag';
      if (!lastShaderList.includes(A) || !lastShaderList.includes(B)) return 'sem atomos';
      const a = newNode('@' + ensureRowId(src), [560, 160], newModule(A));   // (o filho do Contornar fica a' esquerda dele)
      const b = newNode('@' + a.id, [960, 160], newModule(B));
      newMix('out', '@' + b.id, [1340, 160]);
      const m = newMix('out', '@' + ensureRowId(src), [1340, 560]);
      inspClosed = selSig(); cvSig = ''; renderBoxes(); placeInsp();
      zAnim = null; zForget(); setCvZoom(1); CV.scrollLeft = 0; CV.scrollTop = 0; return 'ok'""")   # a vista volta pro comeco (zoom/rolagem de um teste nao vaza pro outro)
    assert ok == 'ok', f'fixture: {ok}'
    time.sleep(0.5)


def center(c, css, i=0):
    r = c.js(f"const e = document.querySelectorAll({json.dumps(css)})[{i}]; if (!e) return null; e.scrollIntoView({{block: 'center', inline: 'center'}});"
             f" const b = e.getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]")
    if not r:
        raise AssertionError(f'nao achei {css}[{i}]')
    return r


def errors(c):
    return [e['params']['exceptionDetails'].get('exception', {}).get('description', '?')[:300]
            for e in c.events if e.get('method') == 'Runtime.exceptionThrown']


# ---------------------------------------------------------------- os testes (um por gesto da revisao)
T = []
def gesto(f):
    T.append(f)
    return f


ATOM = "Object.keys(lastBindings).find(k => atomNode(k) && rowOf(k) && rowOf(k).xy && boxEls[k])"


@gesto
def t_abre_sem_painel(c):
    """34: o app abre com o painel FECHADO, mesmo com um no' escolhido da ultima vez"""
    k = c.js(f"return {ATOM}")
    time.sleep(1.5)   # o dash grava a cena (debounce) antes de recarregar
    load(c, {'key': k, 'j': 0})
    assert c.js("return document.getElementById('insp').hidden"), 'o painel abriu sozinho'
    if not c.js(f"return {ATOM}"):
        fixture(c)


@gesto
def t_clique_so_escolhe(c):
    """7: clique no cabecalho escolhe o no' e NAO abre o painel"""
    k = c.js(f"return {ATOM}")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh')
    c.click(x, y)
    time.sleep(0.2)
    assert c.js("return sel.key") == k, 'nao escolheu'
    assert c.js("return document.getElementById('insp').hidden"), 'clique abriu o painel'
    time.sleep(0.6)   # senao os 2 cliques viram "2 cliques" (= painel)
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')   # o NOME tambem: so' escolhe (antes abria a lista de troca)
    c.click(x, y)
    time.sleep(0.2)
    assert not c.js("return document.querySelector('.nmenu, .wheel')"), 'clique no nome abriu um menu'
    assert c.js("return document.getElementById('insp').hidden"), 'clique no nome abriu o painel'


@gesto
def t_direito_abre_painel(c):
    """8 + 33: direito parado no no' abre o painel; o x nao cobre nenhum botao do cabecalho"""
    k = c.js(f"return {ATOM}")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh')
    c.click(x, y, 'right')
    time.sleep(0.3)
    assert not c.js("return document.getElementById('insp').hidden"), 'direito nao abriu o painel'
    hit = c.js("""const x = document.getElementById('insp-x').getBoundingClientRect();
      return [...document.querySelectorAll('#ctl > .ihead:first-child button')].filter(b => { const r = b.getBoundingClientRect();
        return r.width && !(r.right <= x.left || r.left >= x.right || r.bottom <= x.top || r.top >= x.bottom); }).map(b => b.title.slice(0, 30))""")
    assert not hit, f'o x cobre: {hit}'
    c.js("inspClosed = selSig(); placeInsp(); return 1")


@gesto
def t_dois_cliques_abre(c):
    """8: 2 cliques no corpo do no' (fora de knob/botao) abrem o painel"""
    c.js("document.getElementById('insp').hidden = true; inspClosed = selSig(); return 1")
    k = c.js(f"return {ATOM}")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    c.click(x, y, clicks=1)
    c.click(x, y, clicks=2)
    time.sleep(0.3)
    assert not c.js("return document.getElementById('insp').hidden"), '2 cliques nao abriram o painel'


@gesto
def t_escolher_nao_refaz(c):
    """FLUIDEZ: escolher um no' (ou um fio) NAO refaz o canvas — os mesmos elementos, so' o .sel muda de lugar (antes: o canvas inteiro a cada clique)"""
    ks = c.js("return Object.keys(boxEls).filter(k => rowOf(k) && rowOf(k).xy).slice(0, 2)")
    assert len(ks) == 2, f'cena sem 2 nos: {ks}'
    c.js(f"window.__els = Object.values(boxEls); setSel({json.dumps(ks[0])}, -1, true); return 1")
    x, y = center(c, f'.bx[data-key="{ks[1]}"] > .bh')
    c.click(x, y)
    time.sleep(0.25)
    r = c.js(f"""return {{ mesmos: Object.values(boxEls).every((e, i) => e === __els[i]) && Object.values(boxEls).length === __els.length,
      a: boxEls[{json.dumps(ks[0])}].classList.contains('sel'), b: boxEls[{json.dumps(ks[1])}].classList.contains('sel'), k: sel.key }}""")
    assert r['k'] == ks[1] and r['b'] and not r['a'], f'o .sel nao andou: {r}'
    assert r['mesmos'], 'escolher recriou os nos'
    ms = c.js(f"""const K = {json.dumps(ks)}, T = []; for (let i = 0; i < 8; i++){{ const t0 = performance.now(); setSel(K[i % 2], -1, true); document.body.offsetHeight; T.push(performance.now() - t0); }}
      T.sort((a, b) => a - b); return +T[4].toFixed(1)""")
    PERF['escolher_ms'] = ms
    print('      escolher:', ms, 'ms')
    assert ms < 25, f'escolher ficou pesado: {ms} ms'


@gesto
def t_osciloscopio_no_tempo(c):
    """ENVELOPE: o osciloscopio anda no TEMPO, nao por quadro desenhado — com o dash travado (zoom, layout) a onda nao desacelera nem
    muda de forma; toda mensagem entra (antes: 1 ponto por quadro processado, as do meio perdidas)"""
    k = c.js(f"return {ATOM}")
    n = c.js(f"const s = stackOf({json.dumps(k)})[0]; return knobsOf(s.file)[0]")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.5)
    r = c.js("""const id = ctlStore()[ctlStore().length - 1].id, el = CVI.querySelector(`.scope[data-mvs="${id}"]`); if (!el) return 'sem osciloscopio';
      delete SCOPE[id]; const t0 = performance.now();
      // 12 mensagens SEGUIDAS sem nenhum quadro no meio (o dash travado): todas entram
      for (let i = 0; i < 12; i++) scopeIn(`{"x": 1, "mv": {"${id}": ${i % 2}}, "y": 2}`);
      const n = SCOPE[id].length;
      SCOPE[id] = [[t0 - 1100, 1], [t0 - 1099, 0]];   // um pulso ha' 1,1 s = metade da janela
      drawScopes(t0); const p = el.firstChild.firstChild.getAttribute('points').trim().split(' ').map(q => q.split(',').map(Number));
      return { n, x: p[0][0], y: p[0][1], fim: p[p.length - 1][0] }""")
    assert r != 'sem osciloscopio', r
    assert r['n'] == 12, f'mensagens perdidas no osciloscopio: {r}'
    assert abs(r['x'] - 30) < 1 and r['y'] < 2, f'o pulso de 1,1 s atras nao ficou no meio da janela: {r}'
    assert r['fim'] == 60, f'o traco nao chega ate agora: {r}'
    # RAJADA (bug "animacao dos alteradores bugada"): 8 mensagens lidas pelo servidor a cada 33 ms mas ENTREGUES juntas = 8 amostras a 33 ms
    # (pela hora do servidor, mv_t), nao 8 no mesmo instante
    d = c.js("""const id = ctlStore()[ctlStore().length - 1].id; delete SCOPE[id]; mvOff = null; const T = performance.now();
      scopeIn(`{"mv": {"${id}": 0.1}, "mv_t": ${T - 5}}`);   // uma NORMAL: a demora do caminho (5 ms)
      for (let i = 0; i < 8; i++) scopeIn(`{"mv": {"${id}": ${i % 2}}, "mv_t": ${T - 300 + i * 33}}`);   // a RAJADA: lidas antes, chegando juntas
      const b = SCOPE[id].slice(-8); return b.slice(1).map((x, i) => +(x[0] - b[i][0]).toFixed(1))""")
    assert all(abs(x - 33) < 1.5 for x in d), f'rajada virou degrau (espacamento das amostras): {d}'


@gesto
def t_bolinha_liga_desliga(c):
    """12: a bolinha verde do no' de atomo liga/desliga"""
    k = c.js(f"return {ATOM}")
    off0 = bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0"))
    c.click(*center(c, f'.bx[data-key="{k}"] .led.pw'))
    time.sleep(0.3)
    off1 = bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0"))
    assert off1 != off0, 'clique na bolinha nao mudou'
    c.click(*center(c, f'.bx[data-key="{k}"] .led.pw'))
    time.sleep(0.3)
    assert bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0")) == off0, 'nao voltou'


@gesto
def t_cabo_sobre_outro_fio(c):
    """16: arrastar um cabo novo (Shift) por cima de outro fio NAO perde o cabo"""
    c.js("document.querySelectorAll('.nmenu').forEach(x => x.remove()); return 1")
    k = c.js(f"return {ATOM}")
    a = center(c, f'.bx[data-key="{k}"] > .port.out')
    mid = c.js("""const ps = [...document.querySelectorAll('#cv-wires path.w:not(.cv)')]; if (!ps.length) return null;
      const p = ps[ps.length - 1], L = p.getTotalLength(), q = p.getPointAtLength(L / 2), m = p.getScreenCTM(); return [q.x * m.a + m.e, q.y * m.d + m.f]""")
    assert mid, 'cena sem fio pra cruzar'
    g0 = graph(c)
    c.mods = 8   # SHIFT = cabo NOVO (clique sem Shift numa saida com cabo pega o cabo que existe)
    seen = c.drag([a, mid, (mid[0] + 40, mid[1] + 60)], check=lambda i: c.js("return !!document.querySelector('#cv-wires path.w.drag')"), cancel=True)
    c.mods = 0
    assert all(seen), f'o cabo sumiu no meio do arrasto: {seen}'
    time.sleep(0.2)
    assert not c.js("return !!cable || !!document.querySelector('#cv-wires path.w.drag')"), 'Esc nao soltou o cabo'
    assert graph(c) == g0, 'cancelar o cabo mudou a cena'


@gesto
def t_knob_alcance(c):
    """22: knob com ativador vira ALCANCE: arrastar pra cima aumenta hi, a base (lo) fica"""
    k = c.js(f"return {ATOM}")
    n = c.js(f"const s = stackOf({json.dumps(k)})[0]; return knobsOf(s.file)[0] || 'opacity'")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'respira'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.4)
    css = f'.bx[data-key="{k}"] .nkr[data-kr="{n}"] .knob'
    assert c.js(f"const e = document.querySelector({json.dumps(css)}); return !!e && e.classList.contains('alc')"), 'knob nao virou alcance'
    m0 = c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}]")
    x, y = center(c, css)
    c.js("warpOK = false; return 1")   # sem /warp no teste: o cursor nao volta pro lugar
    c.drag([(x, y), (x, y - 50)])
    time.sleep(0.3)
    m1 = c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}]")
    assert abs((m1.get('lo') or 0) - (m0.get('lo') or 0)) < 1e-6, f'a base mexeu: {m0} -> {m1}'
    assert (m1['hi'] - m1['lo']) > (m0['hi'] - m0['lo']) + 0.05, f'o alcance nao subiu: {m0} -> {m1}'


@gesto
def t_mascara_vira_no(c):
    """26: mascara solta num no' vira um NO' de mascara ligado na 'másc' dele"""
    k = c.js(f"return {ATOM}")
    f = c.js("return lastShaderList.find(f => isMaskFile(f) && f !== LUMA && /Cor|Brilho/.test(f))")
    assert f, 'sem atomo de mascara'
    n0 = c.js("return lastOverlays.length")
    c.js(f"maskNode({json.dumps(k)}, {json.dumps(f)}); return 1")
    time.sleep(0.3)
    assert c.js("return lastOverlays.length") == n0 + 1, 'nao criou o no'
    ok = c.js(f"""const nv = lastOverlays[lastOverlays.length - 1], m = matteOf({json.dumps(k)}) || {{}};
      return (m.items || []).some(x => (x.ins || [])[0] === '@' + nv.id)""")
    assert ok, 'o no de mascara nao esta na másc do alvo'


# ---------------------------------------------------------------- rodada 1: nos e cabos (itens 1-19 da revisao)
def empty_pt(c):
    """um ponto VAZIO do canvas (nada embaixo alem do fundo/fios)"""
    p = c.js("""const R = CV.getBoundingClientRect();
      for (let y = R.top + 30; y < R.bottom - 20; y += 23) for (let x = R.left + 20; x < R.right - 20; x += 29){
        const t = document.elementFromPoint(x, y); if (t === CV || t === CVI || t === WIRES || (t && t.id === 'cv-empty')) return [x, y]; }
      return null""")
    assert p, 'canvas sem espaco vazio'
    return p


def graph(c):
    """o GRAFO, sem ordem de chave nem campo que o servidor acrescenta: nos (id, de onde le, camadas) + atomo/entrada B/mascara"""
    return c.js("""const B = k => (lastBindings[k] || {});
      return JSON.stringify(lastOverlays.map(o => { const k = chKey(o); return [o.id, o.file, (o.layers || []).map(L => L.from + (L.off ? '-' : '')),
        (B(k).shaders || []).map(x => [x.file, (x.ins || []).join(), x.off ? 1 : 0]), ((B(k).matte || {}).items || []).map(x => [x.file, (x.ins || []).join()])]; }).sort())""")


def wire_mid(c, port='a', margin=20):
    """meio de um fio de imagem (o 1o da lista) em coordenadas de tela + a assinatura dele (margin = longe das bordas da janela)"""
    return c.js("""const M = """ + str(margin) + """;for (const p of document.querySelectorAll('#cv-wires path.w:not(.cv)')){ if (!p._w) continue;
        const L = p.getTotalLength(), q0 = p.getPointAtLength(L / 2), z = cvZoom();   // leva a vista ate' o meio do fio
        CV.scrollLeft = q0.x * z - CV.clientWidth / 2; CV.scrollTop = q0.y * z - CV.clientHeight / 2; await new Promise(r => setTimeout(r, 60));
        const m = p.getScreenCTM();
        for (const f of [0.5, 0.4, 0.6, 0.3, 0.7]){ const q = p.getPointAtLength(L * f), x = q.x * m.a + m.e, y = q.y * m.d + m.f, t = document.elementFromPoint(x, y);
          if (x < M || y < M + 110 || x > innerWidth - M || y > innerHeight - M) continue;   // longe da borda (a roda abre centrada no ponto)
          if (t && t.classList && t.classList.contains('hit')) return [x, y, p._w.key, p._w.port]; } }
      return null""")


@gesto
def t_vazio_desescolhe(c):
    """2: clique no VAZIO tira a escolha — Delete depois disso nao apaga nada"""
    k = c.js(f"return {ATOM}")
    c.click(*center(c, f'.bx[data-key="{k}"] > .bh'))
    time.sleep(0.6)
    c.click(*empty_pt(c))
    time.sleep(0.3)
    assert not c.js("return sel.key"), f'continua escolhido: {c.js("return sel.key")}'
    g0 = graph(c)
    c.key('Delete')
    time.sleep(0.3)
    assert graph(c) == g0, 'Delete apagou algo sem nada escolhido'


@gesto
def t_apagar_desfazer(c):
    """11 + 5: Delete apaga o no' escolhido; Ctrl+Z volta"""
    k = c.js(f"return {ATOM}")
    n0 = c.js("return lastOverlays.length")
    c.click(*center(c, f'.bx[data-key="{k}"] > .bh'))
    time.sleep(0.6)
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 1, 'Delete nao apagou o no'
    c.key('z', 2)
    time.sleep(0.5)
    assert c.js("return lastOverlays.length") == n0, 'Ctrl+Z nao trouxe de volta'


@gesto
def t_delete_nao_pega_fio_do_mouse(c):
    """11: Delete apaga o ESCOLHIDO, nao o fio que estiver embaixo do mouse"""
    k = c.js(f"return {ATOM}")
    c.click(*center(c, f'.bx[data-key="{k}"] > .bh'))
    time.sleep(0.6)
    w = wire_mid(c)
    c.mouse('mouseMoved', w[0], w[1])
    time.sleep(0.2)
    n0, g0 = c.js("return lastOverlays.length"), graph(c)
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 1, 'Delete nao apagou o no escolhido (pegou o fio do mouse?)'
    c.key('z', 2)
    time.sleep(0.5)
    assert graph(c) == g0, 'Ctrl+Z nao voltou tudo'


@gesto
def t_retangulo(c):
    """2: retangulo no vazio pega varios; Delete apaga todos; Ctrl+Z volta todos"""
    c.js("setCvZoom(0.6); return 1")
    time.sleep(0.3)
    box = c.js("""const r = [...document.querySelectorAll('#cv-in .bx')].map(e => e.getBoundingClientRect()), R = CV.getBoundingClientRect();
      const x0 = Math.min(...r.map(b => b.left)) - 14, y0 = Math.min(...r.map(b => b.top)) - 14, x1 = Math.max(...r.map(b => b.right)) + 14, y1 = Math.max(...r.map(b => b.bottom)) + 14;
      return [Math.max(R.left + 2, x0), Math.max(R.top + 2, y0), Math.min(R.right - 2, x1), Math.min(R.bottom - 2, y1), r.length]""")
    t = c.js(f"const t = document.elementFromPoint({box[0]}, {box[1]}); return t === CV || t === CVI || t === WIRES")
    assert t, 'o canto do retangulo nao cai no vazio'
    c.drag([(box[0], box[1]), (box[2], box[3])])
    time.sleep(0.3)
    n = c.js("return msel.size")
    assert n >= 3, f'retangulo pegou {n}'
    n0, g0 = c.js("return lastOverlays.length"), graph(c)
    c.key('Delete')
    time.sleep(0.5)
    assert c.js("return lastOverlays.length") < n0 - 1, 'Delete nao apagou os escolhidos'
    c.key('z', 2)
    time.sleep(0.6)
    assert c.js("return lastOverlays.length") == n0, 'Ctrl+Z nao trouxe todos'
    c.js("msel.clear(); paintMsel(); setCvZoom(1); return 1")
    time.sleep(0.3)


@gesto
def t_mover(c):
    """9: arrastar o cabecalho move o no' (fios juntos), sem abrir painel nem menu"""
    k = c.js(f"return {ATOM}")
    xy0 = c.js(f"return rowOf({json.dumps(k)}).xy.slice()")
    g0 = graph(c)
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    c.drag([(x, y), (x + 60, y + 48)])
    time.sleep(0.4)
    xy1 = c.js(f"return rowOf({json.dumps(k)}).xy")
    assert xy1 != xy0, 'nao moveu'
    assert graph(c) == g0, 'mover mexeu nas ligacoes'
    assert c.js("return document.getElementById('insp').hidden && !document.querySelector('.nmenu, .wheel')"), 'mover abriu painel/menu'


@gesto
def t_duplicar_ctrl(c):
    """10: Ctrl+arrastar duplica o no' (copia solta, sem fios); o original fica"""
    k = c.js(f"return {ATOM}")
    n0 = c.js("return lastOverlays.length")
    xy0 = c.js(f"return rowOf({json.dumps(k)}).xy.slice()")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    c.mods = 2
    c.drag([(x, y), (x + 40, y + 160)])
    c.mods = 0
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 + 1, 'Ctrl+arrastar nao duplicou'
    assert c.js(f"return rowOf({json.dumps(k)}).xy") == xy0, 'o original saiu do lugar'
    c.key('z', 2)
    time.sleep(0.4)


@gesto
def t_tirar_fio(c):
    """17: clique no fio escolhe ele; Delete tira so' ele"""
    w = wire_mid(c)
    assert w, 'sem fio'
    c.click(w[0], w[1])
    time.sleep(0.3)
    assert c.js("return !!selWire"), 'clique no fio nao escolheu'
    n0 = c.js("return lastOverlays.length")
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0, 'Delete no fio apagou um no'
    assert c.js("return !selWire"), 'fio continua escolhido'
    c.key('z', 2)
    time.sleep(0.4)


@gesto
def t_fio_apaga_ao_sair(c):
    """16: mouse em cima do fio acende ele; tirar o mouse apaga (antes ficava aceso)"""
    w = wire_mid(c)
    assert w, 'sem fio exposto'
    c.mouse('mouseMoved', w[0], w[1])
    time.sleep(0.2)
    assert c.js("return document.querySelectorAll('#cv-wires path.w.hl').length") >= 1, 'o fio nao acendeu'
    c.mouse('mouseMoved', *empty_pt(c))
    time.sleep(0.2)
    lit = c.js("return document.querySelectorAll('#cv-wires path.w.hl, #cv-wires path.w.dim').length")
    assert lit == 0, f'{lit} fio(s) continuam acesos/apagados depois de tirar o mouse'


@gesto
def t_direito_arrasta_vista(c):
    """1: direito ARRASTANDO (mesmo em cima de um no') move a vista e NAO abre o painel"""
    k = c.js(f"return {ATOM}")
    c.js("inspClosed = selSig(); placeInsp(); return 1")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh')
    s0 = c.js("return [CV.scrollLeft, CV.scrollTop, lastOverlays.map(o => o.xy[0]).join()]")
    c.drag([(x, y), (x - 120, y - 80)], button='right')
    time.sleep(0.3)
    s1 = c.js("return [CV.scrollLeft, CV.scrollTop, lastOverlays.map(o => o.xy[0]).join()]")
    assert s1 != s0, 'a vista nao andou'
    assert c.js("return document.getElementById('insp').hidden"), 'arrastar com o direito abriu o painel'


@gesto
def t_cabo_dois_cliques_roda(c):
    """2 cliques no CABO abrem a roda de atomos, no fio"""
    w = wire_mid(c, margin=170)
    assert w, 'sem fio exposto'
    c.click(w[0], w[1])
    c.click(w[0], w[1], clicks=2)
    time.sleep(0.4)
    assert c.js("return !!document.querySelector('.wheel')"), '2 cliques no cabo nao abriram a roda'
    assert c.js("return document.querySelector('.wheel .wh-mid').textContent") == 'no fio', 'a roda nao esta no fio'
    c.key('Escape')
    c.js("closeWheel(); return 1")


@gesto
def t_shift_clique_soma(c):
    """2: Shift+clique em QUALQUER parte do no' soma (o ja' escolhido entra junto); Delete apaga os dois"""
    ks = c.js("return Object.keys(lastBindings).filter(k => atomNode(k) && boxEls[k]).slice(0, 2)")
    assert len(ks) == 2, 'precisa de 2 nos de atomo'
    c.click(*center(c, f'.bx[data-key="{ks[0]}"] > .bh .nm'))
    time.sleep(0.6)
    x, y = center(c, f'.bx[data-key="{ks[1]}"] .win')
    c.mods = 8
    c.click(x, y)
    c.mods = 0
    time.sleep(0.3)
    assert c.js("return [...msel].sort()") == sorted(ks), f'escolhidos: {c.js("return [...msel]")}'
    n0 = c.js("return lastOverlays.length")
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 2, 'Delete nao apagou os 2'
    c.key('z', 2)
    time.sleep(0.5)


@gesto
def t_ctrl_a_esc(c):
    """2: Ctrl+A escolhe todos; Esc tira; Delete depois nao apaga nada"""
    c.click(*empty_pt(c))
    c.key('a', 2)
    time.sleep(0.2)
    n = c.js("return [msel.size, document.querySelectorAll('#cv-in .bx.msel').length, document.querySelectorAll('#cv-in .bx').length]")
    assert n[0] == n[2] and n[1] == n[2], f'Ctrl+A: {n}'
    c.key('Escape')
    time.sleep(0.2)
    assert c.js("return msel.size + document.querySelectorAll('.bx.msel').length") == 0, 'Esc nao tirou'
    g0 = graph(c)
    c.key('Delete')
    time.sleep(0.3)
    assert graph(c) == g0, 'Delete apagou depois do Esc'


@gesto
def t_ctrl_d(c):
    """Ctrl+D duplica o escolhido (sem fios) e a copia fica escolhida"""
    k = c.js(f"return {ATOM}")
    c.click(*center(c, f'.bx[data-key="{k}"] > .bh .nm'))
    time.sleep(0.6)
    n0 = c.js("return lastOverlays.length")
    c.key('d', 2)
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 + 1, 'Ctrl+D nao duplicou'
    nk = c.js("return sel.key")
    assert nk and nk != k, 'a copia nao ficou escolhida'
    assert c.js(f"return rowOf({json.dumps(nk)}).file") == '@-', 'a copia veio com fio'


@gesto
def t_retangulo_um(c):
    """2: retangulo pegando UM no' + Delete apaga esse no' (o aceso e' o que sai)"""
    c.click(*empty_pt(c))
    k = c.js(f"return {ATOM}")
    r = c.js(f"const b = boxEls[{json.dumps(k)}]; b.scrollIntoView({{block: 'center'}}); const r = b.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]")
    vazio = lambda p: c.js(f"const t = document.elementFromPoint({p[0]}, {p[1]}); return t === CV || t === CVI || t === WIRES")
    cand = [(r[0] - 10, r[1] - 10), (r[0] - 6, r[1] - 22), (r[0] + 20, r[1] - 12), (r[0] + 60, r[1] - 14), (r[0] - 14, r[1] + 4)]   # um canto VAZIO (cabo de outro no' pode passar)
    a = next((p for p in cand if vazio(p)), None)
    assert a, 'canto nao vazio: ' + str(c.js(f"const t = document.elementFromPoint({cand[0][0]}, {cand[0][1]}); return t && (t.outerHTML || '').slice(0, 160)"))
    c.drag([a, (r[0] + 30, r[1] + 20)])
    time.sleep(0.3)
    assert c.js("return [...msel]") == [k], f'retangulo pegou {c.js("return [...msel]")}'
    n0 = c.js("return lastOverlays.length")
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 1, 'Delete nao apagou o no aceso'


@gesto
def t_saida_por_tela(c):
    """saidas = telas do palco: a roda lista uma por tela; tela que ja' tem saida nao cria outra"""
    n = c.js("return screenOuts().length")
    used = c.js("return screenOuts().filter(s => s.o).length")
    o0 = c.js("return outRows().length")
    for _ in range(n + 2):   # pede mais saidas do que telas
        c.js("const f = screenOuts().find(s => !s.o); if (f) outForScreen(f, [900, 600], null); return 1")
    assert c.js("return outRows().length") == o0 + (n - used), f'saidas: {c.js("return outRows().length")} (telas {n})'
    c.js("document.getElementById('cvadd-out').click(); return 1")
    time.sleep(0.2)
    assert c.js("return outRows().length") == o0 + (n - used), '"saída nova" passou do limite'


@gesto
def t_cards_identificaveis(c):
    """cards: pictograma do PROPRIO atomo, imagem viva, cor da familia; altura real = a do layout (fios e arrumar)"""
    r = c.js("""return Object.keys(lastBindings).filter(k => atomNode(k) && boxEls[k]).map(k => { const b = boxEls[k], u = b.querySelector('.bh .ai use');
      return [fxName(stackOf(k)[0].file), u && u.getAttribute('href'), !!b.querySelector('canvas.lv'), getComputedStyle(b).getPropertyValue('--cc').trim(), b.offsetHeight, boxH(k)]; })""")
    assert r, 'sem no de atomo'
    for nm, href, lv, cc, hh, bh in r:
        assert href and href.startswith('#i-at-'), f'{nm}: sem pictograma proprio ({href})'
        assert lv, f'{nm}: sem imagem viva'
        assert cc, f'{nm}: sem cor da familia'
        assert abs(hh - bh) <= 4, f'{nm}: altura {hh} != layout {bh}'
    assert len({x[1] for x in r}) == len(r), 'dois atomos com o mesmo pictograma'


@gesto
def t_escolhido_fica(c):
    """escolhido = contorno inconfundivel; mexer DENTRO dele (knob, bolinha, jack) nao tira; so' clicar FORA tira"""
    k = c.js(f"return {ATOM}")
    c.click(*center(c, f'.bx[data-key="{k}"] > .bh .nm'))
    time.sleep(0.6)
    st = c.js(f"const s = getComputedStyle(boxEls[{json.dumps(k)}]); return [s.outlineStyle, parseFloat(s.outlineWidth)]")
    assert st[0] == 'solid' and st[1] >= 2, f'escolhido sem contorno claro: {st}'
    c.js("warpOK = false; return 1")
    x, y = center(c, f'.bx[data-key="{k}"] .nkr .knob')
    c.drag([(x, y), (x, y - 20)])
    time.sleep(0.3)
    c.click(*center(c, f'.bx[data-key="{k}"] .led.pw')); time.sleep(0.3)
    c.click(*center(c, f'.bx[data-key="{k}"] .led.pw')); time.sleep(0.3)
    c.click(*center(c, f'.bx[data-key="{k}"] .kj')); time.sleep(0.3)
    c.key('Escape'); c.js("closeWheel(); document.querySelectorAll('.nmenu').forEach(x => x.remove()); return 1")
    assert mkb(c) == k, f'mexer dentro tirou a escolha: {mkb(c)}'
    c.click(*empty_pt(c))
    time.sleep(0.3)
    assert not c.js("return sel.key"), 'clique fora nao tirou'


def mkb(c):
    return c.js("return mkBase(sel.key)")


@gesto
def t_ativador_nasce_embaixo(c):
    """mini TV: o ativador (controlador) nasce EMBAIXO do no', com o jack de CV dele perto do jack do knob (o CV sai por baixo)"""
    k = c.js(f"return {ATOM}")
    n = c.js(f"const s = stackOf({json.dumps(k)})[0]; return knobsOf(s.file)[1] || knobsOf(s.file)[0]")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.5)
    r = c.js(f"""const o = rowOf({json.dumps(k)}), m = stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}], ct = ctlStore().find(x => x.id === m.id), e = cvEnd({{key: {json.dumps(k)}, j: 0, n: {json.dumps(n)}}});
      return [ct.xy[1], o.xy[1] + boxH({json.dumps(k)}), ct.xy[0] + CTL_W - 18, e[0], e[2] || '']""")
    assert r[0] > r[1], f'nao nasceu embaixo: {r}'
    assert abs(r[2] - r[3]) < 80, f'o jack do controlador longe do knob: {r}'
    assert r[4] == 'down', f'o cabo nao chega por baixo: {r}'


@gesto
def t_arrastar_envelope(c):
    """o envelope (controlador) arrasta por qualquer parte do corpo; o jack de CV fica no canto superior direito"""
    k = c.js(f"return {ATOM}")
    n = c.js(f"const s = stackOf({json.dumps(k)})[0]; return knobsOf(s.file)[0]")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.5)
    cid = c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}].id")
    xy0 = c.js(f"return ctlStore().find(x => x.id === {json.dumps(cid)}).xy.slice()")
    jk = c.js(f"""const b = ctlEls[{json.dumps(cid)}].getBoundingClientRect(), j = ctlEls[{json.dumps(cid)}].querySelector('.port.cout').getBoundingClientRect();
      return [j.right > b.right - 12, j.top < b.top + 12]""")
    assert all(jk), f'o jack do envelope nao esta no canto superior direito: {jk}'
    x, y = center(c, f'.bx.ctln[data-ctl="{cid}"] .scope')
    c.drag([(x, y), (x + 120, y + 60)])
    time.sleep(0.3)
    xy1 = c.js(f"return ctlStore().find(x => x.id === {json.dumps(cid)}).xy.slice()")
    assert xy1[0] - xy0[0] > 60 and xy1[1] - xy0[1] > 20, f'o envelope nao arrastou: {xy0} -> {xy1}'


@gesto
def t_mixer(c):
    """MIXER de N jacks: um jack por linha, jack de cima = na frente; a SAIDA tem uma entrada (o cabo novo troca); saida antiga vira mixer"""
    r = c.js("""const src = lastOverlays.find(o => !o.kind && !isTapKey(o.file)), a = '@' + ensureRowId(src), b = '@' + Object.values(lastOverlays).find(o => isTapKey(o.file) && o.id).id;
      const m = newMix('mix', null, [700, 700], 4); cvSig = ''; renderBoxes();
      plug(b, { key: chKey(m), port: 'L', idx: 902 }); plug(a, { key: chKey(m), port: 'L', idx: 900 });
      const rows = [...boxEls[chKey(m)].querySelectorAll('.lr')].map(x => x.classList.contains('slot') ? '-' : 'x');
      const o = newMix('out', a, [1000, 700]); plug(b, { key: chKey(o), port: 'L', idx: 3 });
      const old = { kind: 'out', id: 'oz' + rid(), n: 9, xy: [1300, 700], layers: [{ from: a }, { from: b }] }; lastOverlays.push(old); graphFix();
      const mz = lastOverlays.find(x => x.kind === 'mix' && x.jacks && x !== m && old.layers[0].from === '@' + x.id);
      return { order: m.layers.map(L => [L.from === a ? 'a' : 'b', L.slot]), rows, out: o.layers.map(L => L.from === b ? 'b' : 'a'),
               mig: mz ? mz.layers.map(L => [L.from === a ? 'a' : 'b', L.slot]) : null, outrows: boxEls[chKey(o)] ? boxEls[chKey(o)].querySelectorAll('.lr').length : -1 }""")
    assert r['order'] == [['b', 2], ['a', 0]], f'ordem do mixer (de tras pra frente) errada: {r}'
    assert r['rows'] == ['x', '-', 'x', '-'], f'o mixer nao mostra os 4 jacks no lugar: {r}'
    assert r['out'] == ['b'], f'a saida nao ficou com UMA entrada (a nova): {r}'
    assert r['mig'] == [['a', 1], ['b', 0]], f'saida antiga nao virou mixer (a da frente no jack de cima): {r}'


@gesto
def t_hover_suave(c):
    """mouse num no': os cabos dos outros esmaecem SUAVE — os mesmos elementos (com transicao), nao um redesenho; mexendo em knob ficam fracos, nao somem"""
    k = c.js(f"return {ATOM}")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    for _ in range(6):   # espera os cabos pararem (um redesenho do SSE no meio nao e' o hover)
        c.js("window._w0 = [...document.querySelectorAll('#cv-wires path.w')]; return 1")
        time.sleep(0.35)
        if c.js("const ps = [...document.querySelectorAll('#cv-wires path.w')]; return ps.length === _w0.length && ps.every((p, i) => p === _w0[i])"):
            break
    c.mouse('mouseMoved', x, y)
    time.sleep(0.2)
    r = c.js(f"""const ps = [...document.querySelectorAll('#cv-wires path.w')];
      return [ps.length === _w0.length && ps.every((p, i) => p === _w0[i]), ps.some(p => p.classList.contains('dim')) || ps.every(p => p.dataset.k === {json.dumps(k)} || p.dataset.s === {json.dumps(k)}),
              parseFloat(getComputedStyle(ps[0]).transitionDuration) > 0]""")
    assert r[0], 'o hover refez os cabos (sem transicao: apaga seco) ' + str(c.js("return [_w0.length, document.querySelectorAll('#cv-wires path.w').length, cvZoom(), !!zAnim]"))
    assert r[1] and r[2], f'hover sem esmaecer suave: {r}'
    c.js("document.body.classList.add('kturn'); return 1")
    op = c.js("return +getComputedStyle(document.getElementById('cv-wires')).opacity")   # (a transicao anda: le o alvo pela regra)
    tgt = c.js("""for (const sh of document.styleSheets) for (const r of sh.cssRules) if (r.selectorText === 'body.kturn #cv-wires') return parseFloat(r.style.opacity); return -1""")
    c.js("document.body.classList.remove('kturn'); return 1")
    assert tgt >= 0.3, f'mexendo num knob os cabos somem demais: alvo {tgt} (agora {op})'


@gesto
def t_enter_lista(c):
    """ENTER no MONTAR abre a lista de modulos (como o VCV) onde o mouse esta'; Esc fecha"""
    c.click(*empty_pt(c))
    time.sleep(0.2)
    c.key('Enter')
    time.sleep(0.3)
    assert c.js("return !!document.querySelector('.wheel')"), 'Enter nao abriu a lista de modulos'
    c.key('Escape')
    c.js("closeWheel(); return 1")


@gesto
def t_previa_nao_pisca(c):
    """a imagem viva NAO pisca preta: o mesmo canvas sobrevive ao redesenho (clique, zoom) e o PROGRAMA "fundo" aparece atras do canvas"""
    k = c.js(f"return {ATOM}")
    same = c.js(f"""const a = boxEls[{json.dumps(k)}].querySelector('canvas.lv'); a.width = 7;   // marca o canvas (o conteudo vai junto)
      cvSig = ''; renderBoxes(); setCvZoom((cvzNow || 1) * 1.25); cvSig = ''; renderBoxes();
      const b = boxEls[{json.dumps(k)}].querySelector('canvas.lv'); const r = [a === b, b.width]; setCvZoom(null); return r""")
    assert same[0] and same[1] == 7, f'o canvas da previa foi trocado (pisca preto): {same}'
    bg = c.js("return getComputedStyle(CV).backgroundColor + ' | ' + getComputedStyle(CV).backgroundImage")
    assert bg.startswith('rgba(0, 0, 0, 0)') and bg.endswith('none'), f'o canvas tem fundo proprio (esconde o PROGRAMA "fundo"): {bg}'


@gesto
def t_clique_pega_cabo(c):
    """VCV: clique numa SAIDA com cabo PEGA o cabo (solto no vazio = tira; Ctrl+Z volta); Shift = cabo NOVO (os que existem ficam)"""
    k = c.js(f"return {ATOM}")
    n0 = c.js(f"const ref = '@' + rowOf({json.dumps(k)}).id; return rowsVisible().reduce((a, r) => a + inputsOf(r).filter(w => w.ref === ref).length, 0)")
    assert n0 >= 1, 'o no de teste nao tem cabo saindo'
    a = center(c, f'.bx[data-key="{k}"] > .port.out')
    e = empty_pt(c)
    c.mods = 8
    c.drag([a, ((a[0] + e[0]) / 2, (a[1] + e[1]) / 2)], cancel=True)
    c.mods = 0
    time.sleep(0.3)
    n1 = c.js(f"const ref = '@' + rowOf({json.dumps(k)}).id; return rowsVisible().reduce((a, r) => a + inputsOf(r).filter(w => w.ref === ref).length, 0)")
    assert n1 == n0, f'Shift mexeu nos cabos que existem: {n0} -> {n1}'
    a = center(c, f'.bx[data-key="{k}"] > .port.out')
    c.drag([a, e])
    time.sleep(0.4)
    c.js("document.querySelectorAll('.nmenu').forEach(x => x.remove()); closeWheel(); return 1")
    n2 = c.js(f"const ref = '@' + rowOf({json.dumps(k)}).id; return rowsVisible().reduce((a, r) => a + inputsOf(r).filter(w => w.ref === ref).length, 0)")
    assert n2 == n0 - 1, f'o clique nao pegou (e tirou) o cabo: {n0} -> {n2}'


@gesto
def t_mini_tv(c):
    """mini TV (rodada 4): liga + fader EM CIMA da tela; a TELA na largura toda; nome embaixo dela; IN/MASC a' ESQUERDA dos knobs (IN na
    altura do knob, MASC na dos CVs), OUT a' DIREITA na altura do knob (aba escura); jacks LONGE das bordas; knob SEM porcentagem"""
    k = c.js(f"return {ATOM}")
    r = c.js(f"""const b = boxEls[{json.dumps(k)}], B = b.getBoundingClientRect(), z = cvZoom(), R = q => {{ const e = b.querySelector(q); return e && e.getBoundingClientRect(); }};
      const crt = R('.crt'), win = R(':scope > .win'), i = R(':scope > .port.in'), m = R(':scope > .port.pm'), o = R(':scope > .port.out'), kj = R('.kj'), kw = R('.nkr .kw'), f = R('.r1 .fader'), pw = R('.r1 .led.pw'),
        nm = R(':scope > .bh .nm'), tab = R(':scope > .otab'), lb = [...b.querySelectorAll('.k-lb')], kv = b.querySelector('.k-val'), cy = r => (r.top + r.bottom) / 2;
      const borda = Math.min(...[i, m, o, kj].map(r => Math.min(r.left - B.left, B.right - r.right, B.bottom - r.bottom))) / z;
      return {{ tv: b.classList.contains('tv'), fam: [...b.classList].some(c => c.startsWith('fam-')), ar: crt && crt.width / crt.height, palco: tvAR(),
        tela_larga: (win.left - B.left) / z < 18 && (B.right - win.right) / z < 18,
        in_esq: i && i.right <= kw.left && Math.abs(cy(i) - cy(kw)) < 4, masc_esq: m && m.right <= kw.left && Math.abs(cy(m) - cy(kj)) < 4,
        out_dir: o && o.left >= kw.right && Math.abs(cy(o) - cy(kw)) < 4, out_na_aba: o && tab && o.top >= tab.top && o.bottom <= tab.bottom + 1,
        longe_da_borda: borda >= 12, borda, sem_pct: !kv || getComputedStyle(kv).display === 'none',
        fader_em_cima: !!f && f.bottom <= crt.top, liga_na_linha: !!pw && Math.abs((pw.top + pw.bottom) / 2 - (f.top + f.bottom) / 2) < 6,
        nome_embaixo: !!nm && nm.top >= crt.bottom && nm.top < crt.bottom + 30, sem_knob_opac: !b.querySelector('.nkr[data-kr="opacity"]'),
        rotulo_inteiro: lb.every(e => e.scrollWidth <= e.clientWidth + 1 && !/…/.test(e.textContent)) }}""")
    assert r['tv'] and r['fam'], f'nao e mini TV: {r}'
    assert abs(r['ar'] - r['palco']) < 0.05, f'tela fora da proporcao do palco: {r}'
    for chave in ('tela_larga', 'in_esq', 'masc_esq', 'out_dir', 'out_na_aba', 'longe_da_borda', 'sem_pct', 'fader_em_cima', 'liga_na_linha', 'nome_embaixo', 'sem_knob_opac', 'rotulo_inteiro'):
        assert r[chave], f'{chave}: {r}'
    o0 = c.js(f"return stackOf({json.dumps(k)})[0].opacity ?? 1")
    x, y = center(c, f'.bx[data-key="{k}"] .r1 .fader')
    c.js("warpOK = false; return 1")   # sem /warp no teste: o cursor nao volta pro lugar
    c.drag([(x, y), (x - 60, y)])
    time.sleep(0.3)
    o1 = c.js(f"return stackOf({json.dumps(k)})[0].opacity ?? 1")
    assert o1 < o0 - 0.1, f'o fader de opacidade nao mexeu: {o0} -> {o1}'


@gesto
def t_tema(c):
    """menu VISUAL: foto-real | cel e leve trocam o desenho (classe no body, cabo sem sombra no leve) e ficam lembrados ao reabrir"""
    c.click(*center(c, '#tema-btn'))
    time.sleep(0.3)
    assert c.js("return !!document.getElementById('tema-pop')"), 'o menu visual nao abriu'
    c.click(*center(c, '#tema-seg button[data-t="cel"]'))
    time.sleep(0.3)
    assert c.js("return document.body.classList.contains('cel') && JSON.parse(localStorage.getItem('v5tema')).t === 'cel'"), 'cel nao ligou/gravou'
    assert c.js("return document.querySelectorAll('#cv-wires path.ws').length") > 0, 'cabo sem contorno no cel'
    assert c.js("return [...document.querySelectorAll('#cv .lv, #pvw canvas, #pvw img')].every(e => getComputedStyle(e).filter === 'none')"), \
        'o tema cel mexeu na IMAGEM da previa (o tema muda so as pecas, nunca o que a tela mostra)'
    c.click(*center(c, '#tema-leve'))
    time.sleep(0.3)
    assert c.js("return document.body.classList.contains('leve') && !document.querySelector('#cv-wires path.ws, #cv-wires path.wh')"), 'leve deixou decoracao no cabo'
    load(c)
    assert c.js("return document.body.classList.contains('cel') && document.body.classList.contains('leve')"), 'o tema nao foi lembrado ao reabrir'
    c.js("tema = { t: 'foto', leve: 0 }; LS.set('v5tema', tema); applyTema(); return 1")
    fixture(c)


@gesto
def t_cabo_escolhido_por_cima(c):
    """cabo escolhido aparece POR CIMA dos nos; sem o x no cabo"""
    w = wire_mid(c)
    c.click(w[0], w[1])
    time.sleep(0.3)
    assert c.js("return document.querySelectorAll('#cv-wires-top path').length") >= 1, 'o escolhido nao foi pra cima'
    assert not c.js("return document.querySelector('.wx')"), 'o x do cabo ainda existe'
    z = c.js("return [+getComputedStyle(document.getElementById('cv-wires-top')).zIndex, +getComputedStyle(document.querySelector('#cv-in .bx')).zIndex]")
    assert z[0] > z[1], f'svg de cima nao esta acima dos nos: {z}'


@gesto
def t_sem_maozinha(c):
    """sem maozinha parada: canvas, titulo e corpo do no' com o cursor normal"""
    k = c.js(f"return {ATOM}")
    cur = c.js(f"""const b = boxEls[{json.dumps(k)}]; return [getComputedStyle(CV).cursor, getComputedStyle(b.querySelector('.bh')).cursor,
      getComputedStyle(b.querySelector('.bh .nm')).cursor, getComputedStyle(b.querySelector('.at') || b).cursor]""")
    assert all(x in ('default', 'auto') for x in cur), f'cursores: {cur}'


@gesto
def t_zoom_longe(c):
    """zoom out ate' o PISO (2%): niveis bloco/ponto (no' = bloco na cor da familia, sem pecas), cabos ainda nas bordas; roda = SUAVE e centrada no cursor"""
    k = c.js(f"return {ATOM}")
    c.js("setCvZoom(0.001); return 1")
    z = c.js("return cvZoom()")
    assert abs(z - 0.02) < 1e-6, f'o piso do zoom nao e 2%: {z}'
    r = c.js(f"""const b = boxEls[{json.dumps(k)}], n = b.querySelector('.blkn');
      return {{ cls: [...CVI.classList], knobs: !!b.querySelector('.nkr') && b.querySelector('.nkr').getClientRects().length, blk: getComputedStyle(b).backgroundColor,
        nome: n && getComputedStyle(n).display, wires: [...document.querySelectorAll('#cv-wires path.w')].map(p => p.getAttribute('d')).filter(d => /^M0 0|NaN/.test(d)).length }}""")
    assert 'zl-blk' in r['cls'] and 'zl-ponto' in r['cls'], f'nivel de longe: {r}'
    assert not r['knobs'], f'de longe o no ainda desenha knobs: {r}'
    assert r['nome'] == 'flex', f'o bloco nao mostra o nome: {r}'
    assert r['wires'] == 0, f'cabo sem ponta (jack escondido): {r}'
    c.js("setCvZoom(0.15); return 1")
    assert 'zl-blk' in c.js("return [...CVI.classList]") and 'zl-ponto' not in c.js("return [...CVI.classList]"), 'nivel bloco'
    assert c.js(f"return boxEls[{json.dumps(k)}].querySelector('.win').getClientRects().length") > 0, 'no bloco a tela (parada) deveria aparecer'
    c.js("setCvZoom(1); return 1")
    # RODA: suave (anda em varios quadros) e o ponto embaixo do cursor fica parado
    C = center(c, f'.bx[data-key="{k}"] .win')   # em cima de um no' (dentro do mundo: a rolagem nao bate no limite)
    w0 = c.js(f"const C = CV.getBoundingClientRect(), z = cvZoom(); return [(CV.scrollLeft + {C[0]} - C.left) / z, (CV.scrollTop + {C[1]} - C.top) / z]")
    c.send('Input.dispatchMouseEvent', type='mouseWheel', x=C[0], y=C[1], deltaX=0, deltaY=-120)
    z1 = c.js("return cvZoom()")
    time.sleep(0.6)
    z2 = c.js("return cvZoom()")
    assert z2 > 1.15 and z1 < z2, f'a roda nao foi suave ({z1} -> {z2})'
    w1 = c.js(f"const C = CV.getBoundingClientRect(), z = cvZoom(); return [(CV.scrollLeft + {C[0]} - C.left) / z, (CV.scrollTop + {C[1]} - C.top) / z]")
    assert abs(w1[0] - w0[0]) < 3 and abs(w1[1] - w0[1]) < 3, f'o zoom nao ficou centrado no cursor: {w0} -> {w1}'
    c.js("setCvZoom(1); return 1")


@gesto
def t_caber_tudo(c):
    """H = CABER TUDO: todos os nos dentro da vista; H de novo = volta pro zoom e o lugar de antes"""
    c.js("const o = lastOverlays.find(x => x.xy && !x.kind); o.xy = [4200, 2600]; cvSig = ''; renderBoxes(); setCvZoom(1.2); CV.scrollLeft = 0; CV.scrollTop = 0; return 1")
    time.sleep(0.3)
    z0, s0 = c.js("return [cvZoom(), [CV.scrollLeft, CV.scrollTop]]")
    c.js("document.activeElement && document.activeElement.blur(); return 1")
    c.key('h')
    time.sleep(1.2)
    r = c.js("""const C = CV.getBoundingClientRect(); return Object.values(boxEls).filter(e => e.isConnected).map(e => { const b = e.getBoundingClientRect();
      return b.left >= C.left - 1 && b.right <= C.right + 1 && b.top >= C.top - 1 && b.bottom <= C.bottom + 1; })""")
    assert r and all(r), f'caber tudo deixou no fora da vista: {r}'
    assert c.js("return document.getElementById('cvz-fit').classList.contains('on')"), 'o botao caber tudo nao acendeu'
    c.key('h')
    time.sleep(1.2)
    z1, s1 = c.js("return [cvZoom(), [CV.scrollLeft, CV.scrollTop]]")
    assert abs(z1 - z0) < 0.01, f'H de novo nao voltou o zoom: {z0} -> {z1}'
    assert abs(s1[0] - s0[0]) < 30 and abs(s1[1] - s0[1]) < 30, f'H de novo nao voltou o lugar: {s0} -> {s1}'
    c.js("setCvZoom(1); return 1")


FILHO = "Object.keys(lastBindings).find(k => tvNode(k) && boxEls[k] && boxEls[k].querySelector(':scope > .fil'))"


@gesto
def t_filho(c):
    """MODULO FILHO: a escolha do atomo (fundo do Contornar) sai do card e vira modulo A' ESQUERDA, NA CORRENTE: o fio de antes chega
    no IN do filho e o OUT do filho chega no IN do pai por uma LIGACAO FIXA (trilha, sem plugue redondo); teclas mudam o valor"""
    k = c.js(f"return {FILHO}")
    assert k, 'nenhum no com filho (o Contornar tem a escolha "fundo")'
    r = c.js(f"""const b = boxEls[{json.dumps(k)}], f = b.querySelector(':scope > .fil'), B = b.getBoundingClientRect(), F = f.getBoundingClientRect();
      const fin = f.querySelector('.port.in'), pin = b.querySelector(':scope > .port.in');
      return {{ esq: F.right <= B.left, n: f.dataset.n, dentro: !!b.querySelector('.nkw, .chseg'), opj: !!b.querySelector('.port.opj'), fin: !!fin, lk: pin && pin.classList.contains('lk'),
        trilha: document.querySelectorAll('#cv-wires path.lkc').length, teclas: f.querySelectorAll('.fkey').length,
        chega: inPortEl({json.dumps(k)}, {{ port: 'a' }}) === fin }}""")
    assert r['esq'], f'o filho nao nasceu a esquerda do pai: {r}'
    assert not r['dentro'] and not r['opj'], f'a escolha ainda esta dentro do card / jack da opcao velho: {r}'
    assert r['fin'] and r['lk'] and r['chega'], f'o filho nao esta na corrente (IN do filho = entrada do pai; IN do pai = ligacao fixa): {r}'
    assert r['trilha'] >= 1, f'sem a ligacao fixa: {r}'
    assert r['teclas'] == 2, f'escolha de 2 = duas teclas: {r}'
    v0 = c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, {json.dumps(r['n'])})")
    c.click(*center(c, f'.bx[data-key="{k}"] > .fil .fkey', 1))
    time.sleep(0.3)
    v1 = c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, {json.dumps(r['n'])})")
    assert abs(v1 - 0.75) < 0.01 and abs(v0 - 0.75) > 0.1, f'a tecla "preto" nao escolheu (valor da opcao 2 de 2 = 0.75): {v0} -> {v1}'
    assert c.js(f"return boxEls[{json.dumps(k)}].querySelectorAll(':scope > .fil .fkey')[1].classList.contains('on')"), 'a tecla escolhida nao afundou/acendeu'
    # a LIGACAO FIXA nao se pega e as pontas dela NAO arrastam nada (antes: pegar a ponta arrastava o pai ou o filho)
    g0 = graph(c)
    P = lambda: c.js(f"const b = boxEls[{json.dumps(k)}], f = b.querySelector(':scope > .fil'); return [b.offsetLeft, b.offsetTop, f.offsetLeft, f.offsetTop]")
    for css in (f'.bx[data-key="{k}"] > .port.in', f'.bx[data-key="{k}"] > .fil .fjk'):
        a = P()
        x, y = center(c, css)
        c.drag([(x, y), (x - 70, y + 60)])
        time.sleep(0.3)
        assert P() == a, f'puxar a ponta da ligacao fixa ({css}) arrastou um modulo: {a} -> {P()}'
        assert graph(c) == g0 and not c.js("return !!document.querySelector('.nmenu, .flist, .wheel')"), f'a ligacao fixa se mexeu ({css})'
    # o IN do filho e' a entrada de verdade: puxar a ponta dali pega o fio que chega no pai
    x, y = center(c, f'.bx[data-key="{k}"] > .fil .port.in')
    mid = c.drag([(x, y), (x - 80, y + 90)], check=lambda i: c.js("return wireDrag"), cancel=True)
    assert mid == ['cable'], f'o IN do filho nao pegou o fio da corrente: {mid}'
    time.sleep(0.3)
    assert graph(c) == g0, 'Esc no meio nao devolveu o fio'


@gesto
def t_filho_arrasta(c):
    """arrastar o FILHO move so' ele (o lugar fica guardado, relativo ao pai); arrastar o PAI leva o filho junto"""
    k = c.js(f"return {FILHO}")
    P = lambda: c.js(f"const b = boxEls[{json.dumps(k)}], f = b.querySelector(':scope > .fil'), B = b.getBoundingClientRect(), F = f.getBoundingClientRect(); return [B.left, B.top, F.left, F.top]")
    a = P()
    x, y = center(c, f'.bx[data-key="{k}"] > .fil .fnm')
    a = P()
    c.drag([(x, y), (x - 60, y + 48)])
    time.sleep(0.4)
    b = P()
    assert abs(b[0] - a[0]) < 2 and abs(b[1] - a[1]) < 2, f'arrastar o filho moveu o pai: {a} -> {b}'
    assert b[2] < a[2] - 30 and b[3] > a[3] + 30, f'o filho nao andou: {a} -> {b}'
    off = c.js(f"return (stackOf({json.dumps(k)})[0].filhos || {{}})")
    assert off and list(off.values())[0][1] > 0 or off, f'o lugar do filho nao foi guardado: {off}'
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    a = P()
    c.drag([(x, y), (x + 96, y + 60)])
    time.sleep(0.4)
    b = P()
    dx, dy = b[0] - a[0], b[1] - a[1]
    assert dx > 40 and dy > 30, f'o pai nao andou: {a} -> {b}'
    assert abs((b[2] - a[2]) - dx) < 2 and abs((b[3] - a[3]) - dy) < 2, f'o filho nao foi junto com o pai: {a} -> {b}'


@gesto
def t_zoom_liso(c):
    """ZOOM LISO (rodada 3: "travando pra dar zoom" e os envelopes paravam): no meio da animacao o zoom do CSS NAO muda (so' o transform,
    sem refazer o layout) e o ponto do cursor fica parado; no fim o zoom de verdade entra uma vez e o transform sai sem pulo"""
    k = c.js(f"return {ATOM}")
    C = center(c, f'.bx[data-key="{k}"] .win')
    r = c.js(f"""const el = boxEls[{json.dumps(k)}], raf = () => new Promise(r => requestAnimationFrame(r)), R = () => el.getBoundingClientRect();
      const z0 = cvZoom(), a = R(), px = {C[0]}, py = {C[1]}, fx = (px - a.left) / a.width, fy = (py - a.top) / a.height;
      setCvZoom(1.5, {{ clientX: px, clientY: py }}, true); await raf(); await raf(); await raf();   // (aproximando: afastando no canto a rolagem bate no 0)
      const m = R(), meio = {{ css: cvZoom(), tf: CVI.style.transform, dx: m.left + fx * m.width - px, dy: m.top + fy * m.height - py }};
      let ult = null; while (zAnim){{ await raf(); if (zAnim) ult = R(); }}
      await raf(); const f = R();
      return {{ z0, meio, fim: {{ css: cvZoom(), tf: CVI.style.transform, pulo: ult ? Math.hypot(f.left - ult.left, f.top - ult.top) : 0, dx: f.left + fx * f.width - px, dy: f.top + fy * f.height - py }} }}""")
    assert r['meio']['css'] == r['z0'] and 'scale' in r['meio']['tf'], f'no meio da animacao o zoom do CSS mudou (refaz o layout a cada quadro): {r}'
    assert abs(r['meio']['dx']) < 2 and abs(r['meio']['dy']) < 2, f'no meio o ponto do cursor andou: {r}'
    c.js("setCvZoom(1); return 1")
    assert abs(r['fim']['css'] - 1.5) < 1e-3 and not r['fim']['tf'], f'o fim nao aplicou o zoom / ficou transform: {r}'
    assert r['fim']['pulo'] < 3 and abs(r['fim']['dx']) < 2 and abs(r['fim']['dy']) < 2, f'o fim pulou: {r}'
    c.js("setCvZoom(1); return 1")


@gesto
def t_arrasto_leve(c):
    """ARRASTO LEVE (rodada 3: "arrastar os modulos esta muito ruim"): andando, NADA de redesenhar todos os fios — so' os do no' que anda
    seguem (a ponta do cabo continua no jack a cada passo); soltar = um redesenho"""
    k = c.js(f"return {ATOM}")
    c.js("window.__dbw = 0; const o = drawBoxWires; window.drawBoxWires = function(){ __dbw++; return o.apply(this, arguments); }; return 1")
    x, y = center(c, f'.bx[data-key="{k}"] > .bh .nm')
    def chk(i):
        return c.js(f"""const b = boxEls[{json.dumps(k)}], p = b.querySelector(':scope > .port.out').getBoundingClientRect(), cx = p.left + p.width / 2, cy = p.top + p.height / 2;
          const g = [...document.querySelectorAll('#cv-wires g.pg')].map(g => g.getBoundingClientRect()).map(r => Math.hypot(r.left + r.width / 2 - cx, r.top + r.height / 2 - cy));
          return [__dbw, Math.min(...g)]""")
    mid = c.drag([(x, y), (x + 80, y + 40), (x + 160, y - 20)], check=chk)
    time.sleep(0.4)
    n = c.js("const n = __dbw; return n")
    assert all(m[0] == 0 for m in mid), f'andando, os fios todos foram redesenhados: {mid}'
    assert all(m[1] < 3 for m in mid), f'o plugue nao acompanhou o jack do no que anda: {mid}'
    assert n >= 1, 'soltar nao redesenhou'


@gesto
def t_nomes_e_etiquetas(c):
    """LEITURA (rodada 3): nome do mixer sem numero ("MIXER", nao "mixer 16"); entrada vazia = "livre" (sem numero, pedido); todo texto do
    gabinete numa placa lisa (a textura nunca atras da letra); o valor do knob inteiro, fora do jack de CV"""
    r = c.js("""const m = newMix('mix', null, [1300, 160]); if (m) m.jacks = 4; cvSig = ''; renderBoxes();
      const b = Object.values(boxEls).find(e => e.classList.contains('jk')), nm = b && b.querySelector('.bh .nm').textContent;
      const k = [...document.querySelectorAll('#cv .bx.tv .nkr')][0], lb = k.querySelector('.k-lb'), v = k.querySelector('.k-val'), j = k.querySelector('.kj');
      const bg = e => getComputedStyle(e).backgroundImage;
      return { nm, livre: b && [...b.querySelectorAll('.lr.slot .hint')].map(x => x.textContent), lb: bg(lb), val: bg(v), pct: getComputedStyle(v).display }""")
    assert r['nm'] and not any(ch.isdigit() for ch in r['nm']), f'o nome do mixer ainda tem numero: {r}'
    assert r['livre'] and r['livre'][0] == 'livre', f'entrada vazia sem etiqueta "livre" (sem numero: pedido): {r}'
    assert 'gradient' in r['lb'] and 'gradient' in r['val'], f'o texto do knob nao tem plaqueta (com relevo): {r}'
    assert r['pct'] == 'none', f'o knob parado mostra a porcentagem (rodada 4: so girando): {r}'


@gesto
def t_arrumar_setores(c):
    """ARRUMAR por SETOR: fonte 1 em cima com a corrente dela, fonte 2 embaixo; quem mistura as duas fica ENTRE os setores; a fonte no
    meio do setor dela; a saida na ultima coluna, centrada com o que ela mostra"""
    r = c.js("""const S = lastOverlays.filter(o => !isTapKey(o.file) && !o.kind && !o.dup);
      if (S.length < 2){ const f = lastMedia.map(m => m.file).find(f => !S.some(o => o.file === f)) || (lastMedia[0] || {}).file; if (!f) return 'sem 2 fontes'; newBox(f, [40, 900]); }
      const [s1, s2] = lastOverlays.filter(o => !isTapKey(o.file) && !o.kind).slice(0, 2); s1.xy = [40, 100]; s2.xy = [40, 700];
      const A = 'presets/atomos/Contornar.frag', B = 'presets/atomos/Matiz.frag';
      const a1 = newNode('@' + ensureRowId(s1), [400, 900], newModule(A)), a2 = newNode('@' + ensureRowId(s2), [400, 50], newModule(B));
      const m = newMix('mix', '@' + a1.id, [700, 700], 2); plug('@' + a2.id, { key: chKey(m), port: 'L', idx: 901 });
      const o = newMix('out', '@' + m.id, [500, 1400]);
      tidy();
      const R = x => { const k = chKey(x); return [x.xy[0], x.xy[1] + boxH(k) / 2]; };
      const mid = (f) => { const L = lastOverlays.filter(x => x.kind !== 'out' && x.xy && f(R(x)[1])); const t = Math.min(...L.map(x => x.xy[1])), b = Math.max(...L.map(x => x.xy[1] + boxH(chKey(x)))); return (t + b) / 2; };
      return { s1: R(s1), s2: R(s2), a1: R(a1), a2: R(a2), m: R(m), o: R(o), meio1: mid(y => y < R(m)[1] - 60), meio2: mid(y => y > R(m)[1] + 60), maxX: Math.max(...lastOverlays.filter(x => x.kind !== 'out').map(x => x.xy[0])), mL: (m.layers || []).length }""")
    assert isinstance(r, dict), r
    assert r['mL'] == 2, f'o mixer de teste nao ficou com as 2 fontes: {r}'
    assert r['s1'][1] < r['m'][1] < r['s2'][1], f'o que mistura as duas nao ficou ENTRE os setores: {r}'
    assert r['a1'][1] < r['m'][1] < r['a2'][1], f'a corrente de cada fonte nao ficou no setor dela: {r}'
    assert abs(r['s1'][1] - r['meio1']) < 30 and abs(r['s2'][1] - r['meio2']) < 30, f'a fonte nao ficou no meio do setor dela: {r}'
    assert r['o'][0] > r['maxX'] and abs(r['o'][1] - r['m'][1]) < 30, f'a saida nao ficou na direita, centrada com o que mostra: {r}'


@gesto
def t_arrasta_por_qualquer_parte(c):
    """rodada 4: o modulo arrasta por QUALQUER parte — a TELA (previa), o gabinete; clique parado na tela so' escolhe"""
    k = c.js(f"return {ATOM}")
    for css in ('.win', ':scope > .skin'):
        xy0 = c.js(f"return rowOf({json.dumps(k)}).xy.slice()")
        center(c, f'.bx[data-key="{k}"] .win')   # (leva a vista ate' o no')
        x, y = c.js(f"""const b = boxEls[{json.dumps(k)}], e = {'b.querySelector(' + json.dumps(css) + ')' if css != ':scope > .skin' else 'b'}, r = e.getBoundingClientRect();
          return {'[r.left + r.width / 2, r.top + r.height / 2]' if css == '.win' else '[r.left + r.width - 8, r.top + r.height * 0.55]'}""")
        c.drag([(x, y), (x + 60, y + 36)])
        time.sleep(0.4)
        xy1 = c.js(f"return rowOf({json.dumps(k)}).xy")
        assert xy1 != xy0 and xy1[0] > xy0[0], f'arrastar por {css} nao moveu o no: {xy0} -> {xy1}'
    c.js("selectNone(); return 1")
    time.sleep(0.2)
    c.click(*center(c, f'.bx[data-key="{k}"] .win'))
    time.sleep(0.3)
    assert c.js(f"return mkBase(sel.key) === {json.dumps(k)}"), 'clique parado na tela nao escolheu o no'


@gesto
def t_pct_so_girando(c):
    """rodada 4: o knob parado NAO mostra porcentagem; girando, o valor aparece (plaqueta solta) e some ao soltar"""
    k = c.js(f"return {ATOM}")
    x, y = center(c, f'.bx[data-key="{k}"] .nkr .kw')
    c.js("warpOK = false; return 1")
    vis = lambda: c.js(f"return getComputedStyle(boxEls[{json.dumps(k)}].querySelector('.nkr .k-val')).display")
    assert vis() == 'none', 'parado mostra a porcentagem'
    mid = c.drag([(x, y), (x, y - 40)], check=lambda i: c.js(f"const v = document.querySelector('.knob.nk.drag .k-val'); return v ? getComputedStyle(v).display : 'sem drag'"))
    time.sleep(0.3)
    assert mid and mid[0] == 'block', f'girando o valor nao apareceu: {mid}'
    assert vis() == 'none', 'soltou e a porcentagem ficou'


PERF = {}


# ---------------------------------------------------------------- /v6: os MESMOS gestos no canvas de jogo (migracao 1: arrastar + cabos)
FREE = """(() => { const r = document.getElementById('gcv').getBoundingClientRect(), g = document.getElementById('gcv');   // um VAZIO do canvas
  for (let fy = 0.85; fy > 0.15; fy -= 0.05) for (let fx = 0.1; fx < 0.9; fx += 0.05){ const x = r.left + r.width * fx, y = r.top + r.height * fy;
    const w = G6.world({ clientX: x, clientY: y }); if (w[0] < 150 || w[1] < 150) continue;   // dentro do mundo (o dash5 guarda tudo >= 0)
    if (document.elementFromPoint(x, y) === g && !G6.pick({ clientX: x, clientY: y }) && !G6.wireNear(w, '', 60)) return [x, y]; } return null })()"""


def v6_open(c):
    """abre o /v6 com a cena fixa inteira na vista (camera a 55%)"""
    c.send('Page.navigate', url=f'http://127.0.0.1:{PORT}/v6')
    for _ in range(80):
        time.sleep(0.15)
        try:
            if c.js("return !!(G6 && G6.scene && G6.scene.nodes.length && lastShaderList.length && Object.keys(lastMeta).length)"):
                break
        except RuntimeError:
            pass
    c.js("if (mode !== 'montar') setMode('montar'); return 1")
    fixture(c)
    c.js("document.getElementById('insp').hidden = true; const p = document.getElementById('pvw'); if (p) p.hidden = true; return 1")
    c.js("tidy(); return 1")   # os modulos HORIZONTAIS sao mais largos: a cena fixa (posicoes do v5) se sobrepoe — arrumada, como no uso
    time.sleep(0.4)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    assert c.js("return G6.scene.nodes.length === rowsVisible().filter(o => o.xy).length"), 'cena do jogo nao bateu com a fixa'


def v6(f):
    """teste do /v6: abre, roda, e SEMPRE volta pro /v5 (o resto da suite e' do v5)"""
    def run(c):
        v6_open(c)
        try:
            f(c)
            err = errors(c)
            if err:
                raise AssertionError('erro de JS no /v6: ' + err[0])
        finally:
            c.mods = 0
            load(c)
    run.__name__, run.__doc__ = f.__name__, f.__doc__
    return gesto(run)


def scr(c, js):   # um ponto do mundo (expressao JS que da' [x, y]) na tela
    return c.js(f"const p = ({js}); return G6.scr(p[0], p[1])")


def wire_pt(c, cond):
    """um ponto de um fio (cond = expressao JS sobre w) que esta' EXPOSTO: o jogo acha o fio ali e nada do HTML cobre"""
    return c.js(f"""const w = G6.scene.wires.find(w => {cond}); if (!w) return null;
      const A = [w.a.x + w.ap[0], w.a.y + w.ap[1]], B = [w.b.x + w.bp[0], w.b.y + w.bp[1]], t = cableCfg().t, sag = t * (150 + Math.hypot(B[0] - A[0], B[1] - A[1])) * 0.8, C = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2 + sag];
      for (let u = 0.15; u < 0.9; u += 0.025){{ const a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, q = u * u, p = G6.scr(a * A[0] + b * C[0] + q * B[0], a * A[1] + b * C[1] + q * B[1]);
        const k = G6.pick({{ clientX: p[0], clientY: p[1] }}); if (k && k.kind === 'wire' && k.w === w && document.elementFromPoint(p[0], p[1]) === document.getElementById('gcv')) return p; }} return null""")


NK = lambda f: f"G6.scene.nodes.find(n => n.an && /{f}/.test(n.an.file))"   # o no' do atomo f (Contornar | Matiz)
SRC = "G6.scene.wires.find(w => (w.par || w.b).an && /Contornar/.test((w.par || w.b).an.file)).a"   # a fonte que alimenta a corrente


@v6
def t_v6_jogo(c):
    """/v6 (o canvas dos modulos como jogo): a MESMA cena, sem DOM de nos; roda = zoom na camera (sem layout); clique escolhe"""
    r = c.js("return { nos: G6.scene.nodes.length, cabos: G6.scene.wires.length, dom: document.querySelectorAll('#cv-in .bx').length }")
    assert r['cabos'] > 0 and r['dom'] == 0, f'cena do jogo: {r}'
    c.js("G6.fit(true); G6.zoom(0.3); return 1")
    z0 = c.js("return G6.cam.z")
    x, y = c.js("""const r = document.getElementById('gcv').getBoundingClientRect();   // um ponto onde o JOGO esta' embaixo (sem inspetor/programa por cima)
      for (let fy = 0.5; fy < 0.95; fy += 0.1) for (let fx = 0.2; fx < 0.9; fx += 0.1){ const x = r.left + r.width * fx, y = r.top + r.height * fy;
        if (document.elementFromPoint(x, y) === document.getElementById('gcv')) return [x, y]; } return [r.left + 60, r.bottom - 60]""")
    for _ in range(4):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-120)
        time.sleep(0.03)
    time.sleep(0.5)
    z1 = c.js("return G6.cam.z")
    assert z1 > z0 * 1.5, f'a roda nao aproximou: {z0} -> {z1}'
    k = c.js("const n = G6.scene.nodes[0]; G6.zoom(1); G6.cam.x = n.x - 40; G6.cam.y = n.y - 40; return n.key")
    time.sleep(0.2)
    x0, y0 = c.js("const r = document.getElementById('gcv').getBoundingClientRect(); return [r.left + 80, r.top + 80]")
    c.click(x0, y0)
    time.sleep(0.3)
    assert c.js("return mkBase(sel.key)") == k, 'clique nao escolheu o no'
    assert c.js("return G6.stats && G6.stats.fps > 0"), 'o laco nao esta desenhando'


@v6
def t6_mover(c):
    """/v6: arrastar o no' por qualquer parte move ele (grade de 12), os cabos vao junto, e grava (o stream nao desfaz)"""
    k, x0, y0 = c.js(f"const n = {NK('Matiz')}; return [n.key, n.x, n.y]")
    a = scr(c, f"[{x0} + 120, {y0} + 60]")
    c.drag([a, (a[0] + 90, a[1] + 50), (a[0] + 150, a[1] + 75)])
    time.sleep(0.6)
    r = c.js(f"const o = rowOf({json.dumps(k)}), n = G6.scene.by[{json.dumps(k)}]; return [o.xy, [n.x, n.y]]")
    z = c.js("return G6.cam.z")
    assert abs(r[0][0] - (x0 + 150 / z)) <= 12 and abs(r[0][1] - (y0 + 75 / z)) <= 12, f'nao andou como o mouse: {r} (de {x0},{y0}, z {z})'
    assert r[1] == r[0], f'o desenho nao seguiu os dados: {r}'
    assert c.js(f"return mkBase(sel.key)") != k, 'arrastar nao deveria escolher'


@v6
def t6_puxar_ponta_e_ligar(c):
    """/v6: puxar a ENTRADA ligada solta a ponta (no vazio = fio tirado); da SAIDA com Shift sai um cabo NOVO que liga numa entrada"""
    mid = c.js(f"return rowOf({NK('Matiz')}.key).id")
    a = scr(c, f"G6.inAt({NK('Matiz')}, 'a', 0)")
    e = c.js(f"return {FREE}")
    c.drag([a, ((a[0] + e[0]) / 2, (a[1] + e[1]) / 2), e])
    time.sleep(0.5)
    assert c.js(f"return !nodeKeyOfRef(rowById({json.dumps(mid)}).file)"), 'soltar a ponta no vazio nao tirou o fio'
    assert c.js("return !document.querySelector('.nmenu')"), 'fio PEGO solto no vazio abriu o menu (devia so tirar)'
    o = scr(c, f"G6.outAt({SRC})")
    b = scr(c, f"G6.inAt(G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), 'a', 0)")
    c.mods = 8
    c.drag([o, ((o[0] + b[0]) / 2, (o[1] + b[1]) / 2 + 40), b])
    c.mods = 0
    time.sleep(0.5)
    r = c.js(f"return nodeKeyOfRef(rowById({json.dumps(mid)}).file) === {SRC}.key")
    assert r, 'o cabo novo da fonte nao ligou na entrada A do Matiz'


@v6
def t6_clique_pega_cabo(c):
    """/v6 (VCV): CLIQUE numa saida com cabo PEGA o cabo (fica grudado); clicar no vazio = tira; Esc no meio = volta"""
    o = scr(c, f"G6.outAt({NK('Matiz')})")
    n0 = c.js("return outRows().filter(o => (o.layers || []).length).length")
    c.click(*o)
    time.sleep(0.3)
    assert c.js("return !!(cable && cable.sticky)"), 'o clique nao deixou o cabo grudado'
    c.key('Escape')
    time.sleep(0.3)
    assert not c.js("return !!cable") and c.js("return outRows().filter(o => (o.layers || []).length).length") == n0, 'Esc nao voltou o cabo'
    c.click(*o)
    time.sleep(0.3)
    e = scr(c, f"[{NK('Matiz')}.x + 120, {NK('Matiz')}.y + 640]")
    c.click(*e)
    time.sleep(0.5)
    assert c.js("return outRows().filter(o => (o.layers || []).length).length") == n0 - 1, 'clicar no vazio nao tirou o cabo pego'


@v6
def t6_fio_escolhe_delete(c):
    """/v6: clique no cabo ESCOLHE ele (por cima, grosso); Delete tira so' ele; clicar no vazio solta a escolha"""
    p = wire_pt(c, "w.a.kind === 'src' && w.b.kind === 'out'")
    assert p, 'sem trecho exposto do fio fonte -> saida'
    c.click(*p)
    time.sleep(0.3)
    assert c.js("return !!selWire && selWire.t === 'L'"), f'clique no cabo nao escolheu: {c.js("return selWire")}'
    n0 = c.js("return lastOverlays.length")
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return !selWire") and c.js("return lastOverlays.length") == n0, 'Delete no fio apagou um no ou o fio ficou escolhido'
    assert c.js("return !G6.scene.wires.some(w => w.a.kind === 'src' && w.b.kind === 'out')"), 'o fio nao saiu'


@v6
def t6_retangulo_grupo(c):
    """/v6: retangulo no VAZIO pega varios; arrastar um = o grupo anda junto"""
    r = c.js(f"const a = {NK('Contornar')}, b = {NK('Matiz')}; return [a.key, b.key, a.x, a.y, b.x, b.y, b.x + b.w, b.y + b.h]")
    p0 = scr(c, f"[{r[2]} - 30, {r[3]} - 30]")
    p1 = scr(c, f"[{r[6]} + 20, {r[7]} + 20]")
    c.drag([p0, ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2), p1])
    time.sleep(0.3)
    ms = c.js("return [...msel]")
    assert r[0] in ms and r[1] in ms, f'o retangulo nao pegou os dois: {ms}'
    g = scr(c, f"[{r[4]} + 120, {r[5]} + 60]")
    c.drag([g, (g[0] + 60, g[1] + 60), (g[0] + 120, g[1] + 120)])
    time.sleep(0.5)
    a, b = c.js(f"return [rowOf({json.dumps(r[0])}).xy, rowOf({json.dumps(r[1])}).xy]")
    assert a[0] - r[2] == b[0] - r[4] and a[1] - r[3] == b[1] - r[5] and a[0] != r[2], f'o grupo nao andou junto: {a} {b} (de {r[2:6]})'


@v6
def t6_ctrl_duplica(c):
    """/v6: Ctrl+arrastar = copia SEM fios; o original fica no lugar"""
    k, x0, y0 = c.js(f"const n = {NK('Matiz')}; return [n.key, n.x, n.y]")
    n0 = c.js("return lastOverlays.length")
    a = scr(c, f"[{x0} + 120, {y0} + 60]")
    c.mods = 2
    c.drag([a, (a[0] + 60, a[1] + 150), (a[0] + 80, a[1] + 300)])
    c.mods = 0
    time.sleep(0.5)
    assert c.js("return lastOverlays.length") == n0 + 1, 'nao copiou'
    assert c.js(f"return rowOf({json.dumps(k)}).xy") == [x0, y0], 'o original saiu do lugar'
    cp = c.js("return lastOverlays[lastOverlays.length - 1]")
    assert c.js(f"return inputsOf(rowOf(chKey(lastOverlays[lastOverlays.length - 1]))).filter(w => nodeKeyOfRef(w.ref)).length") == 0, f'a copia veio com fio: {cp}'


@v6
def t6_cabo_de_controle(c):
    """/v6: do jack do CONTROLADOR ate' um knob = o knob passa a seguir ele (o cabo aparece)"""
    k = c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return n.key")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")   # o controlador nasce embaixo: tudo na vista
    time.sleep(0.3)
    cid, kn = c.js(f"const c = G6.scene.ctls[0], n = {NK('Matiz')}; return [c.id, n.knobs[0].n]")
    n0 = c.js(f"return mvUses({json.dumps(cid)}).length")
    a = scr(c, f"(c => [c.x + c.out[0], c.y + c.out[1]])(G6.scene.ctls[0])")
    b = scr(c, f"(n => [n.x + n.knobs[0].x, n.y + n.knobs[0].y])({NK('Matiz')})")
    c.drag([a, ((a[0] + b[0]) / 2, a[1] - 80), b])
    time.sleep(0.6)
    assert c.js(f"return mvUses({json.dumps(cid)}).length") == n0 + 1, 'o knob nao ligou no controlador'
    assert c.js(f"return G6.scene.cvs.filter(v => v.c.id === {json.dumps(cid)}).length") == n0 + 1, 'o cabo de controle nao aparece'


@v6
def t6_vazio_abre_menu(c):
    """/v6: cabo NOVO solto no VAZIO abre o menu (o no' nasce ali, ja' ligado)"""
    o = scr(c, f"G6.outAt({SRC})")
    e = c.js(f"return {FREE}")
    assert e, 'sem vazio no canvas'
    c.mods = 8
    c.drag([o, ((o[0] + e[0]) / 2, (o[1] + e[1]) / 2 + 60), e])
    c.mods = 0
    time.sleep(0.4)
    m = c.js("const m = document.querySelector('.nmenu'); if (!m) return null; const r = m.getBoundingClientRect(); return [r.left, r.top]")
    assert m, 'soltar no vazio nao abriu o menu'
    w = c.js(f"return G6.world({{clientX: {e[0]}, clientY: {e[1]}}})")
    n0 = c.js("return lastOverlays.length")
    c.js("document.querySelector('.nmenu .nm-list > *').click(); return 1")
    time.sleep(0.5)
    r = c.js("const o = lastOverlays[lastOverlays.length - 1]; return [lastOverlays.length, o.xy, (inputsOf(o).map(w => nodeKeyOfRef(w.ref)))[0] || null]")
    assert r[0] == n0 + 1, f'escolher no menu nao criou o no: {r}'
    assert abs(r[1][0] - w[0]) < 60 and abs(r[1][1] - w[1]) < 60, f'o no nao nasceu onde o cabo foi solto: {r[1]} x {w}'
    assert r[2] == c.js(f"return {SRC}.key"), f'o no novo nao veio ligado na fonte: {r}'


@v6
def t6_borda_rola(c):
    """/v6: arrastando, SEGURAR na borda faz a vista andar (e o no' vai junto); so' passar perto (< 200 ms) nao rola"""
    k, x0, y0 = c.js(f"const n = {NK('Matiz')}; return [n.key, n.x, n.y]")
    a = scr(c, f"[{x0} + 120, {y0} + 60]")
    R = c.js("const r = document.getElementById('gcv').getBoundingClientRect(); return [r.right, r.top + r.height / 2]")
    cx0 = c.js("return G6.cam.x")
    c.mouse('mouseMoved', *a)
    c.mouse('mousePressed', a[0], a[1], 'left', 1, 1)
    for i in range(1, 9):
        c.mouse('mouseMoved', a[0] + (R[0] - 10 - a[0]) * i / 8, a[1] + (R[1] - a[1]) * i / 8, 'left', 0, 1)
        time.sleep(0.02)
    time.sleep(0.8)
    c.mouse('mouseMoved', R[0] - 11, R[1], 'left', 0, 1)
    time.sleep(0.05)
    c.mouse('mouseReleased', R[0] - 11, R[1], 'left', 1, 0)
    time.sleep(0.4)
    cx1, xy = c.js(f"return [G6.cam.x, rowOf({json.dumps(k)}).xy]")
    assert cx1 > cx0 + 100, f'segurar na borda nao rolou a vista: {cx0} -> {cx1}'
    sx = c.js(f"return G6.scr(...rowOf({json.dumps(k)}).xy)[0]")
    z = c.js("return G6.cam.z")
    assert abs(sx - (R[0] - 11 - 120 * z)) < 20, f'o no nao foi junto com a vista (ficou pra tras): tela x {sx}, mouse {R[0] - 11}, pega a {120 * z:.0f} px'


# ---------------------------------------------------------------- /v6 migracao 2: knobs, fader, liga
CT = lambda node, kind, extra='': f"(n => n.ctrls.find(c => c.kind === '{kind}'{extra}))({node})"   # um controle do no'
CTXY = lambda node, kind, extra='': f"(n => {{ const c = n.ctrls.find(c => c.kind === '{kind}'{extra}); return c.kind === 'fader' && c.vert ? [n.x + c.x, n.y + c.y1 - (c.y1 - c.y0) * c.get()] : c.kind === 'fader' ? [n.x + c.x0 + (c.x1 - c.x0) * c.get(), n.y + c.y] : c.kind === 'knob' ? [n.x + c.x, n.y + c.y + 18] : [n.x + c.x, n.y + c.y]; }})({node})"   # knob: a SAIA (o centro e' o jack)
CJXY = lambda node, extra='': f"(n => {{ const c = n.ctrls.find(c => c.kind === 'knob'{extra}); return [n.x + c.x, n.y + c.y]; }})({node})"   # o JACK no centro do knob


@v6
def t6_knob_gira(c):
    """/v6: knob = arrasto RELATIVO pra cima (200 px = tudo, como o dash5); grava; o valor so' aparece girando; 2 cliques = padrao"""
    c.js("warpOK = false; return 1")   # sem /warp no teste
    n = c.js(f"return {CT(NK('Matiz'), 'knob')}.kn.n")
    v0 = c.js(f"return {CT(NK('Matiz'), 'knob')}.get()")
    x, y = scr(c, CTXY(NK('Matiz'), 'knob'))
    mid = c.drag([(x, y), (x, y - 20), (x, y - 40)], check=lambda i: c.js("return activeDrag"))
    time.sleep(0.4)
    v1 = c.js(f"return {CT(NK('Matiz'), 'knob')}.get()")
    assert abs((v1 - v0) - min(0.2, 1 - v0)) < 0.02, f'40 px pra cima nao deu +0.2: {v0} -> {v1}'
    assert mid and mid[0].startswith('bar:'), f'girando, o knob nao estava ativo: {mid}'
    assert c.js("return activeDrag") == '', 'soltou e continuou ativo'
    assert c.js(f"const k = {NK('Matiz')}.key, s = stackOf(k)[0]; return fxVal(k, s, {json.dumps(n)})") == round(v1, 3), 'nao gravou no atomo'
    c.click(x, y)
    c.click(x, y)
    time.sleep(0.3)
    assert abs(c.js(f"return {CT(NK('Matiz'), 'knob')}.get()") - c.js(f"return {CT(NK('Matiz'), 'knob')}.dflt")) < 1e-3, '2 cliques nao voltou ao padrao'


@v6
def t6_knob_jack(c):
    """/v6: o KNOB e' o JACK do cabo de controle: ligado, vira jack (nao gira); apertar e arrastar PEGA o cabo — noutro knob a ligacao muda
    de knob, no vazio sai"""
    k, n = c.js(f"const nd = {NK('Matiz')}, s = stackOf(nd.key)[0]; return [nd.key, knobsOf(s.file)[0]]")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'respira'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.5)
    mid = c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}].id")
    assert c.js(f"return !!{CT(NK('Matiz'), 'knob', f' && c.kn.n === {json.dumps(n)}')}.md"), 'knob ligado nao virou jack'
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    k2, n2 = c.js(f"const nd = {NK('Contornar')}; return [nd.key, nd.knobs[0].n]")
    a = scr(c, CJXY(NK('Matiz'), f' && c.kn.n === {json.dumps(n)}'))
    b = scr(c, f"(nd => [nd.x + nd.knobs[0].x, nd.y + nd.knobs[0].y])({NK('Contornar')})")
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 40), b])
    time.sleep(0.6)
    r = c.js(f"return [!!(stackOf({json.dumps(k)})[0].mod || {{}})[{json.dumps(n)}], ((stackOf({json.dumps(k2)})[0].mod || {{}})[{json.dumps(n2)}] || {{}}).id]")
    assert not r[0] and r[1] == mid, f'arrastar o knob-jack nao levou a ligacao pro outro knob: {r} (id {mid})'
    a = scr(c, f"(nd => [nd.x + nd.knobs[0].x, nd.y + nd.knobs[0].y])({NK('Contornar')})")
    e = c.js(f"return {FREE}")
    c.drag([a, ((a[0] + e[0]) / 2, (a[1] + e[1]) / 2), e])
    time.sleep(0.6)
    assert not c.js(f"return !!(stackOf({json.dumps(k2)})[0].mod || {{}})[{json.dumps(n2)}]"), 'solto no vazio, o cabo nao saiu'


@v6
def t6_fader_liga(c):
    """/v6: o fader de opacidade (HORIZONTAL, embaixo da tela) vai pra esquerda e grava; a bolinha LIGA (canto de cima) desliga/liga; a roda no knob mexe o knob"""
    c.js("warpOK = false; return 1")
    k = c.js(f"return {NK('Matiz')}.key")
    assert c.js(f"return !{CT(NK('Matiz'), 'fader')}.vert && {CT(NK('Matiz'), 'led')}.x < 30 && {CT(NK('Matiz'), 'led')}.y < 30"), 'liga fora do canto / fader nao horizontal'
    x, y = scr(c, CTXY(NK('Matiz'), 'fader'))
    c.drag([(x, y), (x - 40, y), (x - 80, y)])
    time.sleep(0.4)
    op = c.js(f"return stackOf({json.dumps(k)})[0].opacity")
    assert op is not None and op < 0.8, f'o fader nao baixou a opacidade: {op}'
    lx, ly = scr(c, CTXY(NK('Matiz'), 'led'))
    off0 = bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0"))
    c.click(lx, ly)
    time.sleep(0.3)
    assert bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0")) != off0, 'clique no liga nao mudou'
    c.click(lx, ly)
    time.sleep(0.3)
    assert bool(c.js(f"return stackOf({json.dumps(k)})[0].off || 0")) == off0, 'o liga nao voltou'
    z0, v0 = c.js(f"return [G6.cam.z, {CT(NK('Matiz'), 'knob')}.get()]")
    kx, ky = scr(c, CTXY(NK('Matiz'), 'knob'))
    for _ in range(3):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=kx, y=ky, deltaX=0, deltaY=-100)
        time.sleep(0.03)
    time.sleep(0.5)
    z1, v1 = c.js(f"return [G6.cam.z, {CT(NK('Matiz'), 'knob')}.get()]")
    assert z1 == z0 and v1 > v0, f'a roda no knob: zoom {z0}->{z1}, valor {v0}->{v1}'


@v6
def t6_saida_fader_olho(c):
    """/v6: a entrada da SAIDA tem fader (quanto entra) e olho (liga/desliga) como no dash5; MIDI: o knob do no' esta' registrado (CTRL)"""
    c.js("warpOK = false; return 1")
    ok = c.js("return G6.scene.nodes.some(n => n.kind === 'out' && n.ctrls.some(c => c.kind === 'eye'))")
    assert ok, 'a saida nao tem fader/olho'
    OUT = "G6.scene.nodes.find(n => n.kind === 'out' && n.ctrls.some(c => c.kind === 'eye'))"
    k = c.js(f"return {OUT}.key")
    x, y = scr(c, CTXY(OUT, 'fader'))
    c.drag([(x, y), (x - 40, y), (x - 70, y)])
    time.sleep(0.4)
    op = c.js(f"return rowOf({json.dumps(k)}).layers[0].opacity")
    assert op is not None and op < 0.9, f'o fader da entrada nao mexeu: {op}'
    ex, ey = scr(c, CTXY(OUT, 'eye'))
    c.click(ex, ey)
    time.sleep(0.3)
    assert c.js(f"return !!rowOf({json.dumps(k)}).layers[0].off"), 'o olho nao desligou a entrada'
    ids = c.js(f"return {NK('Matiz')}.ctrls.filter(c => c.id).map(c => c.id)")
    assert ids and all(c.js(f"return !!CTRL[{json.dumps(i)}]") for i in ids), f'os controles do no nao estao no CTRL (MIDI): {ids}'
    c.js(f"CTRL[{json.dumps(ids[-1])}].set(0.25); return 1")
    assert abs(c.js(f"return {NK('Matiz')}.ctrls.find(c => c.id === {json.dumps(ids[-1])}).get()") - 0.25) < 1e-3, 'o MIDI (CTRL.set) nao mexeu o controle'


# ---------------------------------------------------------------- /v6 migracao 3: o inspetor
INSP = "(() => { const r = document.getElementById('insp').getBoundingClientRect(); return document.getElementById('insp').hidden ? null : [r.left, r.top, r.right, r.bottom]; })()"


@v6
def t6_painel(c):
    """/v6: clique so' ESCOLHE; 2 cliques no corpo abrem o painel AO LADO do no'; mexer dentro (knob) nao fecha; a vista anda e o painel
    vai junto; clique no vazio fecha; DIREITO parado noutro no' abre o dele"""
    c.js("warpOK = false; return 1")
    k = c.js(f"return {NK('Matiz')}.key")
    b = scr(c, f"(n => [n.x + n.w / 2, n.y + n.G.sy + 30])({NK('Matiz')})")   # a tela do no' (corpo, sem controle)
    c.click(*b)
    time.sleep(0.6)
    assert c.js("return mkBase(sel.key)") == k, 'clique nao escolheu'
    assert c.js(f"return {INSP}") is None, 'um clique abriu o painel'
    c.click(*b)
    time.sleep(0.12)
    c.click(*b)
    time.sleep(0.4)
    r = c.js(f"return {INSP}")
    nr = c.js("const r = G6.selRect(); return [r.left, r.right]")
    assert r, '2 cliques nao abriram o painel'
    assert r[0] >= nr[1] - 1 or r[2] <= nr[0] + 1, f'o painel cobre o no: painel {r}, no {nr}'
    x, y = scr(c, CTXY(NK('Matiz'), 'knob'))
    c.drag([(x, y), (x, y - 20)])
    time.sleep(0.3)
    assert c.js(f"return {INSP}"), 'girar um knob do proprio no fechou o painel'
    p0 = c.js(f"return {INSP}")
    e = c.js("""const r = document.getElementById('gcv').getBoundingClientRect(), g = document.getElementById('gcv');   // um VAZIO do canvas (sem painel/no' por cima)
      for (let fy = 0.9; fy > 0.1; fy -= 0.05) for (let fx = 0.05; fx < 0.6; fx += 0.05){ const x = r.left + r.width * fx, y = r.top + r.height * fy;
        if (document.elementFromPoint(x, y) === g && !G6.pick({ clientX: x, clientY: y })) return [x, y]; } return null""")
    assert e, 'sem vazio no canvas'
    c.mouse('mouseMoved', *e)
    c.mouse('mousePressed', e[0], e[1], 'middle', 1, 4)
    for i in range(1, 7):
        c.mouse('mouseMoved', e[0] - i * 10, e[1], 'middle', 0, 4)
        time.sleep(0.03)
    c.mouse('mouseReleased', e[0] - 60, e[1], 'middle', 1, 0)
    time.sleep(0.3)
    p1 = c.js(f"return {INSP}")
    assert p1 and abs((p0[0] - p1[0]) - 60) < 4, f'a vista andou 60 px e o painel nao foi junto: {p0} -> {p1}'
    c.click(*e)
    time.sleep(0.3)
    assert c.js(f"return {INSP}") is None, 'clique no vazio nao fechou o painel'
    k2 = c.js(f"return {NK('Contornar')}.key")
    c.click(*scr(c, f"(n => [n.x + n.w / 2, n.y + n.G.sy + 30])({NK('Contornar')})"), 'right')
    time.sleep(0.4)
    assert c.js("return mkBase(sel.key)") == k2 and c.js(f"return {INSP}"), 'direito parado nao abriu o painel do outro no'
    c.key('Escape')
    time.sleep(0.3)
    assert c.js(f"return {INSP}") is None, 'Esc nao fechou o painel'


# ---------------------------------------------------------------- /v6 migracao 4: sem filhos (teclas no card) + a roda
def press_item(c, i=0):   # um item da lista da roda, com o mouse de verdade (o item escuta pointerdown)
    x, y = c.js(f"const r = document.querySelectorAll('.wh-list .nm-it')[{i}].getBoundingClientRect(); return [r.left + 40, r.top + r.height / 2]")
    c.click(x, y)


def open_sector(c):   # o 1o setor de atomos (o 0 e' Fontes)
    c.js("[...document.querySelectorAll('.wheel .wh-s')][1].click(); return 1")
    time.sleep(0.3)


@v6
def t6_teclas_no_card(c):
    """/v6: SEM filhos — a escolha do Contornar (fundo: imagem | preto) vira TECLAS no proprio card (maior); clique troca o valor; o MIDI (trig) segue"""
    r = c.js(f"const n = {NK('Contornar')}; return [n.w, n.wide ? n.wide.items.map(i => i.n) : null, n.ctrls.filter(c => c.kind === 'btn').map(c => c.t), n.key]")
    assert r[1], f'o Contornar nao tem a area de teclas: {r}'
    assert r[0] >= 350, f'o card nao alargou pras teclas: {r[0]}'
    assert c.js("return !document.querySelector('.fil')"), 'tem filho no /v6'
    k, n = r[3], r[1][0]
    v0 = c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, {json.dumps(n)})")
    other = c.js(f"const n = {NK('Contornar')}, b = n.ctrls.filter(c => c.kind === 'btn'), i = b.findIndex(c => !c.on()); return i")
    x, y = scr(c, f"(n => {{ const c = n.ctrls.filter(c => c.kind === 'btn')[{other}]; return [n.x + c.x, n.y + c.y]; }})({NK('Contornar')})")
    c.click(x, y)
    time.sleep(0.3)
    v1 = c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, {json.dumps(n)})")
    assert v1 != v0, f'a tecla nao trocou a escolha: {v0} -> {v1}'
    assert c.js(f"return {NK('Contornar')}.ctrls.filter(c => c.kind === 'btn')[{other}].on()"), 'a tecla clicada nao acendeu'
    sid = c.js(f"return stackOf({json.dumps(k)})[0].id || 0")
    tid = f"bar:{k}:{sid}:{n}"
    assert c.js(f"return (CTRL[{json.dumps(tid)}] || {{}}).kind") == 'trig', f'a escolha nao esta no MIDI: {tid}'


@v6
def t6_roda_vazio(c):
    """/v6: 2 cliques no VAZIO abrem a roda; escolher um atomo = no' novo ALI (sem entrada)"""
    e = c.js(f"return {FREE}")
    assert e, 'sem vazio'
    w = c.js(f"return G6.world({{clientX: {e[0]}, clientY: {e[1]}}})")
    c.click(*e)
    c.click(*e)
    time.sleep(0.4)
    assert c.js("return !!document.querySelector('.wheel')"), '2 cliques no vazio nao abriram a roda'
    assert c.js("return document.querySelector('.wheel .wh-mid').textContent") != 'no fio', 'a roda achou um fio no vazio'
    open_sector(c)
    n0 = c.js("return lastOverlays.length")
    press_item(c)
    time.sleep(0.5)
    r = c.js("const o = lastOverlays[lastOverlays.length - 1]; return [lastOverlays.length, o.xy]")
    assert r[0] == n0 + 1, 'escolher na roda nao criou o no'
    assert abs(r[1][0] + BOX_W / 2 - w[0]) < 140 and abs(r[1][1] - w[1]) < 140, f'o no nao nasceu onde a roda abriu: {r[1]} x {w}'


BOX_W = 232


@v6
def t6_roda_no_fio(c):
    """/v6: 2 cliques no CABO abrem a roda "no fio"; o atomo escolhido entra NO MEIO do fio"""
    m = c.js("""const w = G6.scene.wires.find(w => w.a.kind === 'src' && w.b.kind === 'out'); if (!w) return null;   // um trecho do cabo que NAO esta' embaixo de um no'
      const A = [w.a.x + w.ap[0], w.a.y + w.ap[1]], B = [w.b.x + w.bp[0], w.b.y + w.bp[1]], t = cableCfg().t, sag = t * (150 + Math.hypot(B[0] - A[0], B[1] - A[1])) * 0.8, C = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2 + sag];
      for (let u = 0.15; u < 0.9; u += 0.025){ const a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, q = u * u, p = G6.scr(a * A[0] + b * C[0] + q * B[0], a * A[1] + b * C[1] + q * B[1]);
        const k = G6.pick({ clientX: p[0], clientY: p[1] }); if (k && k.kind === 'wire' && document.elementFromPoint(p[0], p[1]) === document.getElementById('gcv')) return p; } return null""")
    assert m, 'sem o fio fonte -> saida'
    out = c.js("return G6.scene.wires.find(w => w.a.kind === 'src' && w.b.kind === 'out').b.key")
    c.click(*m)
    c.click(*m)
    time.sleep(0.4)
    assert c.js("return !!document.querySelector('.wheel')"), '2 cliques no cabo nao abriram a roda'
    assert c.js("return document.querySelector('.wheel .wh-mid').textContent") == 'no fio', 'a roda nao esta no fio'
    open_sector(c)
    press_item(c)
    time.sleep(0.5)
    r = c.js(f"const o = rowOf({json.dumps(out)}), sk = nodeKeyOfRef(o.layers[0].from); return [sk, atomNode(sk), nodeKeyOfRef(rowOf(sk).file)]")
    assert r[1] and r[2] == c.js(f"return {SRC}.key"), f'o atomo nao entrou no meio do fio (fonte -> atomo -> saida): {r}'


@v6
def t6_lista_arrasta_pro_card(c):
    """/v6: um atomo da lista ARRASTADO ate' um card (zona acesa) = no' novo DEPOIS dele"""
    e = c.js(f"return {FREE}")
    c.click(*e)
    c.click(*e)
    time.sleep(0.4)
    open_sector(c)
    mid = c.js(f"return rowOf({NK('Matiz')}.key).id")
    x, y = c.js("const r = document.querySelectorAll('.wh-list .nm-it')[0].getBoundingClientRect(); return [r.left + 40, r.top + r.height / 2]")
    t = scr(c, f"(n => [n.x + n.w / 2, n.y + n.G.sy + 40])({NK('Matiz')})")
    n0 = c.js("return lastOverlays.length")
    hot = c.drag([(x, y), ((x + t[0]) / 2, (y + t[1]) / 2), t], check=lambda i: c.js("return drag && drag.hot ? drag.hot.type : null"))
    time.sleep(0.5)
    assert hot and hot[-1] == 'after', f'a zona do card nao acendeu: {hot}'
    r = c.js(f"const o = lastOverlays[lastOverlays.length - 1]; return [lastOverlays.length, o.file]")
    assert r[0] == n0 + 1 and r[1] == '@' + mid, f'nao virou um no depois do Matiz: {r}'


# ---------------------------------------------------------------- o JOGO e' o principal: os gestos do v5 que faltavam no t6
def click_node(c, nk):   # clique no corpo (a tela) do no' nk (expressao JS)
    c.click(*scr(c, f"(n => [n.x + n.G.sx + n.G.sw / 2, n.y + n.G.sy + n.G.sh / 2])({nk})"))


@v6
def t6_teclado(c):
    """/v6: Delete apaga o escolhido e Ctrl+Z volta; Ctrl+A escolhe todos e Esc tira (Delete depois nao apaga); Ctrl+D copia o escolhido (sem fios)"""
    n0 = c.js("return lastOverlays.length")
    k = c.js(f"return {NK('Matiz')}.key")
    click_node(c, NK('Matiz'))
    time.sleep(0.6)
    assert c.js("return mkBase(sel.key)") == k, 'clique nao escolheu'
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 1, 'Delete nao apagou o no'
    c.key('z', 2)
    time.sleep(0.5)
    assert c.js("return lastOverlays.length") == n0, 'Ctrl+Z nao trouxe de volta'
    c.key('a', 2)
    time.sleep(0.3)
    m = c.js("return msel.size")
    assert m == c.js("return G6.scene.nodes.length + G6.scene.ctls.length"), f'Ctrl+A nao pegou todos: {m}'
    c.key('Escape')
    time.sleep(0.2)
    c.key('Delete')
    time.sleep(0.3)
    assert c.js("return msel.size") == 0 and c.js("return lastOverlays.length") == n0, 'Esc nao tirou a escolha (ou Delete apagou)'
    click_node(c, NK('Matiz'))
    time.sleep(0.6)
    c.key('d', 2)
    time.sleep(0.5)
    assert c.js("return lastOverlays.length") == n0 + 1, 'Ctrl+D nao copiou'
    assert c.js("return mkBase(sel.key)") not in ('', k), 'a copia nao ficou escolhida'


@v6
def t6_barra_zoom(c):
    """/v6: os botoes da barra (- / + / % / caber tudo) e as teclas +/- mexem a CAMERA do jogo; o rotulo mostra o zoom"""
    c.js("G6.zoom(0.5); return 1")
    time.sleep(0.3)
    c.js("document.getElementById('cvz-in').click(); return 1")
    time.sleep(0.6)
    z1 = c.js("return G6.cam.z")
    assert abs(z1 - 0.625) < 0.02, f'+ da barra nao aproximou 25%: {z1}'
    assert c.js("return document.getElementById('cvz-n').textContent").startswith(str(round(z1 * 100))), 'o rotulo nao acompanhou'
    c.js("document.getElementById('cvz-n').click(); return 1")
    time.sleep(0.6)
    assert abs(c.js("return G6.cam.z") - 1) < 0.02, 'clique no % nao voltou a 100%'
    c.key('-')
    time.sleep(0.6)
    assert abs(c.js("return G6.cam.z") - 0.8) < 0.02, 'tecla - nao afastou'
    c.js("document.getElementById('cvz-fit').click(); return 1")
    time.sleep(0.4)
    r = c.js("""const r = document.getElementById('gcv').getBoundingClientRect(); return G6.scene.nodes.every(n => { const a = G6.scr(n.x, n.y), b = G6.scr(n.x + n.w, n.y + n.h);
      return a[0] >= r.left - 1 && a[1] >= r.top - 1 && b[0] <= r.right + 1 && b[1] <= r.bottom + 1; })""")
    assert r, 'caber tudo deixou no fora da vista'


@v6
def t6_enter_lista(c):
    """/v6: ENTER abre a lista de modulos ONDE ESTA' O MOUSE; Esc fecha; escolher = o no' nasce ali"""
    e = c.js(f"return {FREE}")
    c.mouse('mouseMoved', *e)
    time.sleep(0.1)
    c.key('Enter')
    time.sleep(0.3)
    w = c.js("const w = document.querySelector('.wheel'); if (!w) return null; const r = w.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]")
    assert w, 'Enter nao abriu a lista'
    assert abs(w[0] - e[0]) < 260 and abs(w[1] - e[1]) < 260, f'a lista nao abriu onde esta o mouse: {w} x {e}'
    c.key('Escape')
    c.js("closeWheel(); return 1")


@v6
def t6_mascara_vira_no(c):
    """/v6: o no' tem a zona de MASCARA (soltar um atomo de mascara nele); solto = no' de mascara ligado na 'másc' dele"""
    k = c.js(f"return {NK('Matiz')}.key")
    f = c.js("return lastShaderList.find(f => isMaskFile(f) && f !== LUMA && /Cor|Brilho/.test(f))")
    assert f, 'sem atomo de mascara'
    z = c.js(f"return G6.zones({{ kind: 'mask', file: {json.dumps(f)} }}).filter(z => z.key === {json.dumps(k)}).length")
    assert z == 1, 'o jogo nao monta a zona de mascara no no'
    n0 = c.js("return lastOverlays.length")
    c.js(f"maskNode({json.dumps(k)}, {json.dumps(f)}); return 1")   # (= o soltar na zona: dragDrop -> maskNode)
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 + 1, 'nao criou o no de mascara'
    ok = c.js(f"""const nv = lastOverlays[lastOverlays.length - 1], m = matteOf({json.dumps(k)}) || {{}}; return (m.items || []).some(x => (x.ins || [])[0] === '@' + nv.id)""")
    assert ok, 'o no de mascara nao esta na másc do alvo'
    assert c.js(f"return !!G6.scene.wires.find(w => w.b.key === {json.dumps(k)} && w.wid.t === 'm')"), 'o cabo da mascara nao aparece na másc'


@v6
def t6_abre_sem_painel(c):
    """/v6: abrir o app = painel FECHADO, mesmo com um no' escolhido da ultima vez (a escolha volta)"""
    k = c.js(f"return {NK('Matiz')}.key")
    c.js(f"localStorage.setItem('v5sel', JSON.stringify({{ key: {json.dumps(k)}, j: 0 }})); return 1")
    c.send('Page.reload')
    for _ in range(60):
        time.sleep(0.15)
        try:
            if c.js("return !!(G6 && G6.scene && G6.scene.nodes.length)"):
                break
        except RuntimeError:
            pass
    time.sleep(0.6)
    assert c.js("return mkBase(sel.key)") == k, 'a escolha nao voltou'
    assert c.js("return document.getElementById('insp').hidden"), 'abriu com o painel aberto'


def slow_drag(c, a, b, wait=0.25, steps=15):
    """arrasto com RITMO DE GENTE: aperta, ESPERA (o stream chega no meio), e so' entao anda (os testes rapidos nao pegavam o bug)"""
    c.mouse('mouseMoved', *a)
    c.mouse('mousePressed', a[0], a[1], 'left', 1, 1)
    time.sleep(wait)
    for i in range(1, steps + 1):
        c.mouse('mouseMoved', a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps, 'left', 0, 1)
        time.sleep(0.03)
    c.mouse('mouseReleased', b[0], b[1], 'left', 1, 0)


@v6
def t6_ritmo_humano(c):
    """/v6 (bug "drag and drop bugado"): arrastando com ritmo de gente (o stream chega entre apertar e andar), o no' e o controlador FICAM
    onde foram soltos e o cabo LIGA — antes o no' voltava pro lugar"""
    for i in range(3):
        k, x0, y0 = c.js(f"const n = {NK('Matiz')}; return [n.key, n.x, n.y]")
        a = scr(c, f"(n => [n.x + n.G.sx + n.G.sw / 2, n.y + n.G.sy + n.G.sh / 2])({NK('Matiz')})")
        slow_drag(c, a, (a[0] + 50, a[1] + 30))
        time.sleep(0.7)   # mais stream depois de soltar
        xy = c.js(f"return rowOf({json.dumps(k)}).xy")
        assert xy != [x0, y0], f'tentativa {i}: o no voltou pro lugar'
    c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid, cx0 = c.js("const k = G6.scene.ctls[0]; return [k.id, k.x]")
    a = scr(c, "(k => [k.x + 60, k.y + 80])(G6.scene.ctls[0])")
    slow_drag(c, a, (a[0] + 40, a[1] + 10))
    time.sleep(0.7)
    assert c.js(f"return ctlStore().find(x => x.id === {json.dumps(cid)}).xy[0]") != cx0, 'o controlador voltou pro lugar'
    mid = c.js(f"return rowOf({NK('Matiz')}.key).id")
    o = scr(c, f"G6.outAt({SRC})")
    b = scr(c, f"G6.inAt({NK('Matiz')}, 'm', 0)")
    c.mods = 8
    slow_drag(c, o, b)
    c.mods = 0
    time.sleep(0.7)
    ok = c.js(f"const m = matteOf({NK('Matiz')}.key) || {{}}; return (m.items || []).some(x => nodeKeyOfRef((x.ins || [])[0] || '') === {SRC}.key)")
    assert ok, 'o cabo em ritmo de gente nao ligou na másc'


@v6
def t6_oscilador_opacidade(c):
    """/v6: o cabo de um CONTROLADOR (oscilador) liga no FADER de opacidade do atomo (ele vira knob-jack "opacidade") e no fader de uma
    ENTRADA da saida/mixer (vira jack: faixa + valor vivo); arrastar dali pro vazio tira"""
    c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid = c.js("return G6.scene.ctls[0].id")
    k = c.js(f"return {NK('Matiz')}.key")
    a = scr(c, "(k => [k.x + k.out[0], k.y + k.out[1]])(G6.scene.ctls[0])")
    b = scr(c, CTXY(NK('Matiz'), 'fader'))
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 60), b])
    time.sleep(0.6)
    r = c.js(f"const s = stackOf({json.dumps(k)})[0], n = {NK('Matiz')}; return [((s.mod || {{}}).opacity || {{}}).id, n.knobs.some(q => q.n === 'opacity'), !!(n.ctrls.find(c => c.kind === 'fader') || {{}}).md]")
    assert r[0] == cid, f'o fader de opacidade do atomo nao recebeu o oscilador: {r}'
    assert not r[1] and r[2], f'ligada, a opacidade tem que continuar FADER (com a faixa), sem virar knob: {r}'
    OUT = "G6.scene.nodes.find(n => n.kind === 'out' && n.ctrls.some(c => c.kind === 'fader' && c.lay))"
    ok_ = c.js(f"return !!{OUT}")
    assert ok_, 'sem saida com entrada ligada'
    ok_ = c.js(f"const n = {OUT}; return n.key")
    a = scr(c, "(k => [k.x + k.out[0], k.y + k.out[1]])(G6.scene.ctls[0])")
    b = scr(c, f"(n => {{ const f = n.ctrls.find(c => c.kind === 'fader' && c.lay); return [n.x + (f.x0 + f.x1) / 2, n.y + f.y]; }})(G6.scene.by[{json.dumps(ok_)}])")
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 60), b])
    time.sleep(0.6)
    r = c.js(f"const o = rowOf({json.dumps(ok_)}); return [((o.layers[0].mod || {{}}).opacity || {{}}).id, G6.scene.cvs.filter(v => v.kn.layer != null).length]")
    assert r[0] == cid and r[1] >= 1, f'a entrada da saida nao recebeu o oscilador (ou o cabo nao aparece): {r}'
    j = scr(c, f"(n => {{ const f = n.ctrls.find(c => c.kind === 'cvj' && c.lay); return [n.x + f.x, n.y + f.y]; }})(G6.scene.by[{json.dumps(ok_)}])")
    e = c.js(f"return {FREE}")
    c.drag([j, ((j[0] + e[0]) / 2, (j[1] + e[1]) / 2), e])
    time.sleep(0.6)
    assert not c.js(f"return !!(rowOf({json.dumps(ok_)}).layers[0].mod || {{}}).opacity"), 'arrastar o jack da entrada pro vazio nao tirou o oscilador'


# ---------------------------------------------------------------- /v6 rodada 6
# AS PECAS de cada modulo (o desenho: circulo = [x, y, r] | retangulo = [x, y, w, h], no mundo relativo ao modulo) e a AREA UTIL (hzUseful)
PARTS = r"""const parts = (n) => { const P = [], C = (x, y, r, t) => P.push({ t, c: [x, y, r] }), R = (x, y, w, h, t) => P.push({ t, r: [x, y, w, h] });
    const L = n.L || {};
    for (const c of n.ctrls){
      if (c.kind === 'knob'){ C(c.x, c.y, HZ.KRING, 'knob ' + c.kn.n); const w = lblW(knobLabel(c.kn.n).slice(0, 11)); R(c.x - w / 2, c.kn.lblY, w, HZ.LBL, 'rotulo ' + c.kn.n); }
      else if (c.kind === 'fader' && c.vert){ R(c.x - 11, c.y0 - 9, 22, c.y1 - c.y0 + 18, 'fader'); }
      else if (c.kind === 'fader'){ R(c.x0 - 9, c.y - 11, c.x1 - c.x0 + 18, 22, 'fader'); }
      else if (c.kind === 'btn') R(c.x - c.bw / 2, c.y - c.bh / 2, c.bw, c.bh + 1, 'tecla ' + c.t);
      else if (c.kind === 'notch') R(c.x0 - 9, c.y - 11, c.x1 - c.x0 + 18, 22, 'fader de entalhes');
      else C(c.x, c.y, c.r, c.kind); }
    for (const [p, q] of Object.entries(n.ports)) if (p !== 'L' && q) C(q[0], q[1], HZ.JR + 1, 'jack ' + p);
    for (const q of n.ports.L || []) C(q[0], q[1], HZ.JR + 1, 'jack L');
    for (const r_ of L.rail || []){ const w = lblW({ a: 'in', b: 'B', m: 'másc' }[r_.p]); R(r_.x - w / 2, r_.y - HZ.JR - 3 - HZ.LBL, w, HZ.LBL, 'rotulo ' + r_.p); }
    if (L.tab) R(L.tab.x, L.tab.y, L.tab.w, L.tab.h, 'aba OUT');
    if (L.scr) for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) C(L.scr.x + 9 + dx * (L.scr.w - 18), L.scr.y + 9 + dy * (L.scr.h - 18), 9, 'tela (canto de raio 9)');
    if (L.wide) R(L.wide.x - 8, L.wide.y, L.wide.w + 16, L.wide.h - 4, 'teclas');
    if (L.vu) R(L.vu[0] - 2, L.vu[1] - 2, 62, 34, 'VU');
    return P; };
  const ctlParts = (c) => { const L = c.L, P = [{ t: 'jack', c: [c.out[0], c.out[1], HZ.JR + 1] }, { t: 'osciloscopio', r: [L.scr.x - 3, L.scr.y - 3, L.scr.w + 6, L.scr.h + 6] }];
    L.rows.forEach((r_, i) => P.push({ t: 'faixa ' + i, r: [r_.lx, r_.y - 8, r_.x1 - r_.lx, 16] })); return P; };
  const inside = (U, p) => { const e = 0.5;
    const pts = p.c ? null : [[p.r[0], p.r[1]], [p.r[0] + p.r[2], p.r[1]], [p.r[0], p.r[1] + p.r[3]], [p.r[0] + p.r[2], p.r[1] + p.r[3]]];
    const inRR = (x, y, r) => { if (x - r < U.x - e || y - r < U.y - e || x + r > U.x + U.w + e || y + r > U.y + U.h + e) return false;
      const cx = Math.max(U.x + U.r, Math.min(U.x + U.w - U.r, x)), cy = Math.max(U.y + U.r, Math.min(U.y + U.h - U.r, y));
      return Math.hypot(x - cx, y - cy) + r <= U.r + e || (x >= U.x + U.r && x <= U.x + U.w - U.r) || (y >= U.y + U.r && y <= U.y + U.h - U.r); };
    return p.c ? inRR(p.c[0], p.c[1], p.c[2]) : pts.every(([x, y]) => inRR(x, y, 0)); };
  const bad = [];
  for (const n of G6.scene.nodes){ if (!n.L) continue; const U = hzUseful(n.fam, n.w, n.h);
    for (const p of parts(n)) if (!inside(U, p)) bad.push(`${n.name} (${n.fam}): ${p.t} ${JSON.stringify(p.c || p.r)} fora de ${JSON.stringify(U)}`); }
  for (const c of G6.scene.ctls){ const U = hzUseful('fonte', c.w, c.h); for (const p of ctlParts(c)) if (!inside(U, p)) bad.push(`alterador ${c.name}: ${p.t} fora`); }"""


@v6
def t6_dentro_do_relevo(c):
    """/v6 (rodada 6, item 4): NADA invade o relevo — todo knob/jack/fader/tecla/rotulo de TODO modulo (cada atomo da biblioteca, fonte,
    mixer 2/4/8, saida, alterador com 0, 1 e 3 ligacoes) cabe na AREA UTIL (gabinete - bisel da familia - 8 px); grade de 4 px; texto >= 10 px"""
    r = c.js("""const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
      const files = lastShaderList.filter(f => /presets\\/atomos\\//.test(f)); let i = 0, made = [];
      for (const f of files){ const o = newNode(ref, [40 + (i % 6) * 700, 900 + Math.floor(i / 6) * 420], newModule(f)); made.push(o); i++; }
      const m2 = newMix('mix', ref, [40, 9000], 2), m8 = newMix('mix', ref, [800, 9000], 8), m4 = newMix('mix', ref, [1600, 9000], 4);
      const mz = made.find(o => tvKnobs(stackOf(chKey(o))[0]).length >= 3) || made[0], ks = tvKnobs(stackOf(chKey(mz))[0]);
      applyPreset(chKey(mz), 0, ks[0], 'respira');   // alterador com 1 ligacao (e o knob ligado)
      const m1 = made.find(o => o !== mz && tvKnobs(stackOf(chKey(o))[0]).length >= 1); applyPreset(chKey(m1), 0, tvKnobs(stackOf(chKey(m1))[0])[0], 'pulsa');
      const id = stackOf(chKey(m1))[0].mod[tvKnobs(stackOf(chKey(m1))[0])[0]].id; linkMv(chKey(mz), 0, ks[1], id); linkLayerMv(chKey(m2), 0, id);   // 3 ligacoes
      binding(CTL_KEY, true).shaders.push({ file: 'ctl', opacity: 1, id: 'vsolto', xy: [40, 9600], mod: { sinal: { b: ['lfo'], lfo: { forma: 'seno', bat: 4 } } } });   // 0 ligacoes
      tidy(); sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes(); G6.dirty(); return files.length""")
    time.sleep(1.0)
    n = c.js("return G6.scene.nodes.length")
    assert n >= r + 5, f'cena incompleta: {n} nos pra {r} atomos'
    res = c.js(PARTS + """
      const counts = G6.scene.ctls.map(c => c.rg.length).sort(), fams = [...new Set(G6.scene.nodes.map(n => n.fam))].sort();
      const kn = [...new Set(G6.scene.nodes.filter(n => n.kind === 'atom').map(n => n.knobs.length))].sort(), wide = G6.scene.nodes.some(n => n.wide), B = G6.scene.nodes.some(n => n.ports.b);
      const off4 = G6.scene.nodes.filter(n => n.L && (n.w % 4 || n.h % 4)).map(n => n.name);
      return { bad: bad.slice(0, 12), nbad: bad.length, counts, fams, kn, wide, B, off4 }""")
    assert not res['nbad'], f"{res['nbad']} pecas invadem o relevo:\n        " + '\n        '.join(res['bad'])
    assert {0, 1, 3} <= set(res['counts']), f'faltou alterador com 0/1/3 ligacoes: {res["counts"]}'
    assert {0, 1, 2, 3} <= set(res['kn']) and res['wide'] and res['B'], f'faltou variante (knobs {res["kn"]}, teclas {res["wide"]}, B {res["B"]})'
    assert len(res['fams']) >= 9, f'familias: {res["fams"]}'
    assert not res['off4'], f'tamanho fora da grade de 4 px: {res["off4"]}'
    ov = c.js("""const R = [...lastOverlays.filter(o => o.xy).map(rectOfNode), ...ctlStore().filter(c => c.xy).map(c => [c.xy[0], c.xy[1], ...ctlWH(c)])], out = [];
      for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++){ const a = R[i], b = R[j];
        if (a[0] < b[0] + b[2] && a[0] + a[2] > b[0] && a[1] < b[1] + b[3] && a[1] + a[3] > b[1]) out.push([a, b]); } return out.length""")
    assert ov == 0, f'depois de ARRUMAR, {ov} pares de modulos se sobrepoem'


@v6
def t6_fader_ao_lado_da_tela(c):
    """/v6 (2026-11-18): o fader de opacidade e' HORIZONTAL, embaixo da tela (a largura dela), e o JACK do alterador fica na COLUNA das
    entradas (in/másc), na altura do fader, abaixo da másc; o cabo do alterador solto no JACK liga a opacidade (o cabo chega NO jack); ligado,
    o fader NAO arrasta (mostra a faixa); mixer: o jack da camada fica na ponta do fader, antes do olho; MIDI: o id bar:...:opacity continua"""
    c.js("warpOK = false; return 1")
    g = c.js(f"""const n = {NK('Matiz')}, f = n.ctrls.find(c => c.kind === 'fader'), j = n.ctrls.find(c => c.kind === 'cvj'), S = n.L.scr;
      return {{ vert: !!f.vert, l: f.x0 - S.x, r: S.x + S.w - f.x1, dy: f.y - (S.y + S.h), jx: j && j.x - n.ports.a[0], jy: j && j.y - f.y, jm: j && j.y - n.ports.m[1], id: f.id, midi: !!CTRL[f.id] }}""")
    assert not g['vert'] and 0 <= g['l'] <= 16 and 0 <= g['r'] <= 16 and 0 < g['dy'] <= 20, f'o fader nao esta embaixo da tela, na largura dela: {g}'
    assert g['jx'] == 0 and g['jy'] == 0 and g['jm'] >= 40, f'o jack nao esta na coluna do in/másc, na altura do fader: {g}'
    assert g['id'].endswith(':opacity') and g['midi'], f'o id do fader mudou ou saiu do MIDI: {g}'
    c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    k = c.js(f"return {NK('Matiz')}.key")
    a = scr(c, "(k => [k.x + k.out[0], k.y + k.out[1]])(G6.scene.ctls[0])")
    b = scr(c, f"(n => {{ const j = n.ctrls.find(c => c.kind === 'cvj'); return [n.x + j.x, n.y + j.y]; }})({NK('Matiz')})")
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 60), b])
    time.sleep(0.6)
    r = c.js(f"""const n = {NK('Matiz')}, j = n.ctrls.find(c => c.kind === 'cvj'), v = G6.scene.cvs.find(v => v.n === n && v.kn.n === 'opacity');
      return [!!((stackOf({json.dumps(k)})[0].mod || {{}}).opacity), v ? [v.kn.x - j.x, v.kn.y - j.y] : null]""")
    assert r[0] and r[1] == [0, 0], f'o cabo nao ligou/nao chega no jack embaixo do fader: {r}'
    op0 = c.js(f"return stackOf({json.dumps(k)})[0].opacity ?? 1")
    x, y = scr(c, CTXY(NK('Matiz'), 'fader'))
    c.drag([(x, y), (x - 30, y), (x - 60, y)])
    time.sleep(0.4)
    assert c.js(f"return stackOf({json.dumps(k)})[0].opacity ?? 1") == op0, 'ligado, o fader ainda arrasta'
    m = c.js("""const n = G6.scene.nodes.find(n => n.kind === 'out' && n.ctrls.some(c => c.kind === 'eye')), f = n.ctrls.find(c => c.kind === 'fader'),
      j = n.ctrls.find(c => c.kind === 'cvj'), e = n.ctrls.find(c => c.kind === 'eye'); return [f.x1, j.x, e.x, j.y === e.y]""")
    assert m[0] < m[1] < m[2] and m[3], f'mixer/saida: o jack da camada tem que ficar entre o fader e o olho: {m}'


@v6
def t6_knob_jack_peca(c):
    """/v6 (rodada 6, item 1): KNOB + JACK numa peca so' (variante A) — arrastar na SAIA gira; o cabo so' vem DE FORA (do alterador) PRA
    DENTRO do knob (2026-11-18): arrastar do CENTRO de um knob livre NAO solta cabo (gira); ligado, a saia NAO gira (a faixa e' do
    alterador) e a roda nao mexe; o cabo chega no centro; as duas zonas tem alvo >= 24 px a 100%"""
    c.js("warpOK = false; return 1")
    assert c.js("return 2 * HZ.KJ >= 24 && 2 * (HZ.KR - HZ.KJ) >= 24"), 'zonas do knob-jack pequenas demais'
    K = NK('Contornar')
    n = c.js(f"return {K}.knobs[1].n")
    sel = f" && c.kn.n === {json.dumps(n)}"
    v0 = c.js(f"return {CT(K, 'knob', sel)}.get()")
    x, y = scr(c, CTXY(K, 'knob', sel))
    c.drag([(x, y), (x, y - 20), (x, y - 40)])
    time.sleep(0.3)
    v1 = c.js(f"return {CT(K, 'knob', sel)}.get()")
    assert v1 > v0 + 0.1, f'arrastar na saia nao girou: {v0} -> {v1}'
    c.js(f"const n = {NK('Matiz')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid = c.js("return G6.scene.ctls[0].id")
    k = c.js(f"return {K}.key")
    a = scr(c, CJXY(K, sel))
    b = scr(c, "(k => [k.x + k.w / 2, k.y + k.L.scr.y + 10])(G6.scene.ctls[0])")
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 40), b])   # DE DENTRO do knob pra fora: nao liga
    time.sleep(0.6)
    assert not c.js(f"return !!((stackOf({json.dumps(k)})[0].mod || {{}})[{json.dumps(n)}])"), 'arrastar de dentro do knob ate o alterador ligou (so de fora pra dentro)'
    a, b = scr(c, "(k => [k.x + k.out[0], k.y + k.out[1]])(G6.scene.ctls[0])"), scr(c, CJXY(K, sel))
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 40), b])   # DE FORA (o jack do alterador) PRA DENTRO: liga
    time.sleep(0.6)
    r = c.js(f"return [((stackOf({json.dumps(k)})[0].mod || {{}})[{json.dumps(n)}] || {{}}).id, (G6.scene.cvs.find(v => v.n.key === {json.dumps(k)} && v.kn.n === {json.dumps(n)}) || {{}}).kn]")
    assert r[0] == cid, f'puxar do alterador ate o knob nao ligou: {r}'
    kn = c.js(f"return {CT(K, 'knob', sel)}")
    assert r[1] and abs(r[1]['cvy'] - r[1]['y']) < 1, f'o cabo nao chega no CENTRO do knob: {r[1]}'
    lohi0 = c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}]")
    c.js(f"const p = {CTXY(K, 'knob', sel)}; G6.zoom(1); G6.cam.x = p[0] - 300; G6.cam.y = p[1] - 200; G6.dirty(); return 1")   # a 100%: a SAIA e o centro (jack) separados
    time.sleep(0.3)
    x, y = scr(c, CTXY(K, 'knob', sel))
    assert c.js(f"const k = G6.pick({{ clientX: {x}, clientY: {y} }}); return k && k.kind === 'ctrl' && k.c.kind === 'knob' && k.zone !== 'jack'"), 'a saia nao e a zona de girar'
    c.drag([(x, y), (x, y - 30), (x, y - 60)])
    for _ in range(3):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-100)
        time.sleep(0.03)
    time.sleep(0.4)
    assert c.js(f"return stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}]") == lohi0, 'ligado, o knob ainda edita a faixa (saia ou roda)'



def _alt_setup(c):
    """Matiz com o 1o knob ligado (pulsa) -> o alterador; camera a 100% nele. Devolve (key, knob, ctl id)"""
    c.js("warpOK = false; return 1")
    k, n = c.js(f"const nd = {NK('Matiz')}; return [nd.key, knobsOf(nd.an.file)[0]]")
    c.js(f"applyPreset({json.dumps(k)}, 0, {json.dumps(n)}, 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    cid = c.js("const c = G6.scene.ctls[0]; G6.zoom(1); G6.cam.x = c.x - 200; G6.cam.y = c.y - 160; G6.dirty(); return c.id")
    time.sleep(0.4)
    return k, n, cid


RG = lambda: "(c => [c, c.L.rows[0]])(G6.scene.ctls[0])"


def _rg(c, k, n):
    return c.js(f"const m = stackOf({json.dumps(k)})[0].mod[{json.dumps(n)}]; return [m.lo, m.hi]")


def _rgpt(c, v):   # o ponto da linha 0 do alterador no valor v (0..1), na tela
    return scr(c, f"(([c, R]) => [c.x + R.x0 + (R.x1 - R.x0) * {v}, c.y + R.y])({RG()})")


@v6
def t6_alterador_faixa(c):
    """/v6 (rodada 6, item 3): a FAIXA de/ate muda NO ALTERADOR — ponta esquerda = de, direita = ate, MEIO = as duas juntas (a largura
    fica), roda = abre/fecha em volta do meio, 2 cliques = a padrao; o knob ligado e o painel dele so' MOSTRAM"""
    k, n, cid = _alt_setup(c)
    c.js(f"const s = stackOf({json.dumps(k)})[0]; s.mod[{json.dumps(n)}] = Object.assign({{}}, s.mod[{json.dumps(n)}], {{ lo: 0.3, hi: 0.7 }}); sendBindings(true); return 1")
    time.sleep(0.5)
    assert _rg(c, k, n) == [0.3, 0.7], f'faixa inicial: {_rg(c, k, n)}'
    ww = c.js(f"const [c, R] = {RG()}; return (R.x1 - R.x0) * G6.cam.z")
    assert c.js(f"const [c, R] = {RG()}; return R.y + {11} <= c.h") and c.js("return CTL6.ROW >= 12"), 'linha da faixa sem alvo'
    a = _rgpt(c, 0.3)
    assert c.js(f"const k = G6.pick({{ clientX: {a[0]}, clientY: {a[1]} }}); return k.kind === 'ctl' && k.row && k.row.which") == 'lo', 'a ponta esquerda nao e o DE'
    c.drag([a, (a[0] + ww * 0.05, a[1]), (a[0] + ww * 0.1, a[1])])
    time.sleep(0.3)
    lo, hi = _rg(c, k, n)
    assert abs(lo - 0.4) < 0.03 and abs(hi - 0.7) < 1e-6, f'arrastar a ponta esquerda: {lo, hi}'
    b = _rgpt(c, hi)
    c.drag([b, (b[0] + ww * 0.05, b[1]), (b[0] + ww * 0.15, b[1])])
    time.sleep(0.3)
    lo2, hi2 = _rg(c, k, n)
    assert abs(lo2 - lo) < 1e-6 and abs(hi2 - 0.85) < 0.03, f'arrastar a ponta direita: {lo2, hi2}'
    m = _rgpt(c, (lo2 + hi2) / 2)
    assert c.js(f"const k = G6.pick({{ clientX: {m[0]}, clientY: {m[1]} }}); return k.row.which") == 'mid', 'o meio nao pega as duas'
    c.drag([m, (m[0] - ww * 0.05, m[1]), (m[0] - ww * 0.2, m[1])])
    time.sleep(0.3)
    lo3, hi3 = _rg(c, k, n)
    assert abs((hi3 - lo3) - (hi2 - lo2)) < 0.005 and lo3 < lo2 - 0.15, f'arrastar o MEIO nao moveu as duas juntas: {lo2, hi2} -> {lo3, hi3}'
    m = _rgpt(c, (lo3 + hi3) / 2)
    for _ in range(3):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=m[0], y=m[1], deltaX=0, deltaY=-100)
        time.sleep(0.03)
    time.sleep(0.5)
    lo4, hi4 = _rg(c, k, n)
    assert hi4 - lo4 > hi3 - lo3 + 0.03 and abs((lo4 + hi4) / 2 - (lo3 + hi3) / 2) < 0.01, f'a roda nao abriu em volta do meio: {lo3, hi3} -> {lo4, hi4}'
    c.click(*m)
    time.sleep(0.08)
    c.click(*m)
    time.sleep(0.4)
    d = c.js(f"const s = stackOf({json.dumps(k)})[0]; return presetRange('pulsa', knobV({json.dumps(k)}, s, {json.dumps(n)}))")
    assert _rg(c, k, n) == d, f'2 cliques nao voltou a faixa padrao: {_rg(c, k, n)} != {d}'
    # o KNOB ligado nao edita (saia e roda) e o painel dele so' mostra
    x, y = scr(c, CTXY(NK('Matiz'), 'knob', f' && c.kn.n === {json.dumps(n)}'))
    c.js(f"const p = {CTXY(NK('Matiz'), 'knob', f' && c.kn.n === {json.dumps(n)}')}; G6.zoom(1); G6.cam.x = p[0] - 300; G6.cam.y = p[1] - 200; G6.dirty(); return 1")
    time.sleep(0.3)
    x, y = scr(c, CTXY(NK('Matiz'), 'knob', f' && c.kn.n === {json.dumps(n)}'))
    r0 = _rg(c, k, n)
    c.drag([(x, y), (x, y - 30), (x, y - 60)])
    c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-100)
    time.sleep(0.4)
    assert _rg(c, k, n) == r0, 'o knob ligado editou a faixa'
    assert c.js(f"return pieceCtl({json.dumps(k)}, 0, {json.dumps(n)}).classList.contains('ro')"), 'o painel do knob ainda edita a faixa'
    assert c.js(f"return !{CT(NK('Matiz'), 'knob', f' && c.kn.n === {json.dumps(n)}')}.label.includes('alcance')"), 'o knob ligado ainda vira ALCANCE'


@v6
def t6_alterador_arrasta(c):
    """/v6 (rodada 6, item 3): o ALTERADOR arrasta por qualquer parte que nao e' controle (o osciloscopio, o nome) — a linha da faixa nao arrasta"""
    k, n, cid = _alt_setup(c)
    xy0 = c.js(f"return ctlStore().find(c => c.id === {json.dumps(cid)}).xy.slice()")
    a = scr(c, "(c => [c.x + c.L.scr.x + c.L.scr.w / 2, c.y + c.L.scr.y + c.L.scr.h / 2])(G6.scene.ctls[0])")
    assert c.js(f"const k = G6.pick({{ clientX: {a[0]}, clientY: {a[1]} }}); return k.kind === 'ctl' && !k.row"), 'o osciloscopio nao e corpo do alterador'
    c.drag([a, (a[0] + 30, a[1] + 10), (a[0] + 80, a[1] + 40)])
    time.sleep(0.5)
    xy1 = c.js(f"return ctlStore().find(c => c.id === {json.dumps(cid)}).xy")
    assert abs(xy1[0] - xy0[0] - 80) < 12 and abs(xy1[1] - xy0[1] - 40) < 12, f'arrastar pelo osciloscopio nao moveu: {xy0} -> {xy1}'
    r0 = _rg(c, k, n)
    m = _rgpt(c, (r0[0] + r0[1]) / 2)
    c.drag([m, (m[0], m[1] + 30), (m[0], m[1] + 60)])
    time.sleep(0.4)
    assert c.js(f"return ctlStore().find(c => c.id === {json.dumps(cid)}).xy") == xy1, 'a linha da faixa arrastou o alterador'



@v6
def t6_roda_categorias(c):
    """/v6 (rodada 6, item 6): a RODA = as familias dos gabinetes — Fontes, cada familia com atomo (com o MATERIAL dela), mascaras,
    Alteradores, mistura e saida; nenhuma duplicada, nenhuma vazia, todo atomo em UMA fatia"""
    c.js("const r = document.getElementById('gcv').getBoundingClientRect(); openWheel({ clientX: r.left + r.width * 0.4, clientY: r.top + r.height * 0.5 }); return 1")
    time.sleep(0.5)
    r = c.js("""const S = wheelSectors(), B = [...document.querySelectorAll('.wheel .wh-s')];
      const all = lastShaderList.filter(f => isAtomFile(f) && metaOf(f).atom && f !== LUMA), seen = {};
      for (const s of S) for (const it of s.items()) if (it.spec && it.spec.kind === 'mod') seen[it.spec.file] = (seen[it.spec.file] || 0) + 1;
      for (const s of S) if (s.id === 'cat:mascara') for (const it of s.items()) seen[lastShaderList.find(f => fxName(f) === it.t && catOf(f) === 'mascara')] = 1;
      return { l: S.map(s => s.l), n: S.map(s => s.items().length), mat: B.map(b => b.classList.contains('mat')), bg: B.map(b => !!b.style.backgroundImage),
        falta: all.filter(f => !seen[f]).map(fxName), dup: Object.entries(seen).filter(([f, n]) => n > 1).map(([f]) => f) }""")
    c.js("closeWheel(); return 1")
    L = r['l']
    assert len(L) == len(set(L)), f'fatia duplicada: {L}'
    assert all(n > 0 for n in r['n']), f'fatia vazia: {list(zip(L, r["n"]))}'
    assert L[0] == 'Fontes' and 'alteradores' in L and 'mistura e saída' in L and 'máscaras' in L, f'fatias: {L}'
    assert not ({'Movimentos', 'Misturas', 'mistura', 'outros'} & set(L)), f'categoria antiga na roda: {L}'
    assert all(r['mat']) and all(r['bg']), f'fatia sem o material da familia: {list(zip(L, r["mat"]))}'
    assert not r['falta'] and not r['dup'], f'atomo fora da roda {r["falta"]} ou em 2 fatias {r["dup"]}'


@v6
def t6_protecao_na_barra(c):
    """"a tela escurece do nada" (2026-11-19) = a PROTECAO (anti-estrobo) baixando o master: agora acende na BARRA enquanto age e
    voltando, some depois de LIM_HOLD; clique abre Equipamento > Saida"""
    r = c.js("renderLimit({ g: 0.35, why: 'flash' }); const b = document.getElementById('lim-top'); return [b.hidden, b.textContent]")
    assert not r[0] and 'PROTEÇÃO −65%' in r[1] and 'pisca' in r[1], f'protecao agindo nao apareceu: {r}'
    r = c.js("renderLimit({ g: 0.6, why: '' }); return document.getElementById('lim-top').textContent")
    assert 'voltando' in r, f'voltando (ainda escuro) sumiu: {r}'
    time.sleep(1.8)
    r = c.js("renderLimit({ g: 1, why: '' }); return document.getElementById('lim-top').hidden")
    assert r, 'protecao parada e o aviso continua'
    c.js("renderLimit({ g: 0.35, why: 'flash' }); document.getElementById('lim-top').click(); return 1")
    time.sleep(0.4)
    r = c.js("return [drawer, eqTab]")
    assert r == ['eq', 'saida'], f'clique nao abriu Equipamento > Saida: {r}'
    c.js("openDrawer(''); return 1")


@v6
def t6_calibrar_silencio(c):
    """CALIBRAR SILENCIO (2026-11-19): o botao (Audio e popup do tempo) pede a medicao — vira "ouvindo… N s" e trava enquanto o
    native ouve; "limpar" volta ao "sem calibracao". Aqui nao ha native: a medicao fica pendurada ate' o limpar"""
    c.js("document.getElementById('sil-btn').click(); return 1")
    time.sleep(1.2)
    r = c.js("const b = document.getElementById('sil-btn'); return [b.disabled, b.textContent, document.getElementById('sil-st').textContent]")
    assert r[0] and r[1].startswith('ouvindo') and r[2] == 'silêncio, por favor', f'medindo: {r}'
    c.js("silCal('limpar'); return 1")
    time.sleep(1.2)
    r = c.js("const b = document.getElementById('sil-btn'); return [b.disabled, b.textContent, document.getElementById('sil-st').textContent]")
    assert not r[0] and r[1] == 'calibrar silêncio' and r[2] == 'sem calibração', f'limpar: {r}'


@v6
def t6_alteradores_familias(c):
    """/v6 (2026-11-19, "como podemos reorganizar os alteradores"): a lista dos ALTERADORES vem por FAMILIA (Relogio, Som, Imagem e
    corpo, Mao) com cabecalho; o envelope num ATAQUE por faixa (chimbal) nasce controlador e PASSA pelo servidor; o "quando" do
    editor agrupa os eventos (optgroup) e mostra "sem som" nos do som (caixa/chimbal inclusive)"""
    r = c.js("""const S = wheelSectors().find(s => s.id === 'ctl'), it = S.items();
      const fl = floatList(80, 80, 'teste', it, () => {}), hs = [...fl.el.querySelectorAll('.pgt')].map(x => x.textContent); fl.el.remove();
      return { hs, semG: ctlItems().filter(x => !FAMS.some(f => f[0] === x.g)).map(x => x.name), nomes: it.map(x => x.t) }""")
    assert r['hs'] == ['Relógio', 'Som', 'Imagem e corpo', 'Mão'], f'familias na lista: {r["hs"]}'
    assert not r['semG'], f'alterador sem familia: {r["semG"]}'
    assert 'envelope: chimbal' in r['nomes'] and 'envelope: caixa' in r['nomes'] and 'segue o grave' in r['nomes'], r['nomes']
    c.js("newCtl({ kind: 'ev', src: 'chimbal' }, [40, 40]); return 1")
    time.sleep(1.2)
    m = c.js("const x = ctlStore()[ctlStore().length - 1]; return x && x.mod && x.mod.sinal")
    assert m and m.get('modo') == 'disparo' and m['ev']['src'] == 'chimbal', f'envelope no chimbal nao voltou do servidor: {m}'
    e = c.js("""const j = ctlStore().length - 1, md = ctlStore()[j].mod.sinal, box = modEditor(CTL_KEY, j, 'sinal', md, true);
      const sel = box.querySelector('select optgroup') && box.querySelector('select optgroup').parentElement;
      return { g: [...sel.querySelectorAll('optgroup')].map(o => o.label), v: sel.value,
        semSom: [...box.querySelectorAll('.irow .t')].some(t => t.textContent === 'sem som') }""")
    assert e['g'][:2] == ['Relógio', 'Som'] and e['v'] == 'chimbal', f'"quando" sem grupos: {e}'
    assert e['semSom'], 'evento do som (chimbal) sem a linha "sem som"'
    c.js("removeCtl(ctlStore().length - 1); return 1")



def _fx(c, nk, n):
    return c.js(f"const nd = {nk}, s = stackOf(nd.key)[0]; return Math.floor(fxVal(nd.key, s, {json.dumps(n)}) * metaOf(s.file).escolha[{json.dumps(n)}].length)")


@v6
def t6_seletores(c):
    """/v6 (rodada 6, item 8): ESCOLHA = seletor que APONTA — 5+ opcoes = ROTATIVO (rotulo = direto, arrastar = entalhes, roda = proxima,
    Shift+clique = volta uma); 2-4 = FADER DE ENTALHES (o cursor pula pro entalhe); chave = UMA tecla; alvo >= 24 px; o MESMO id bar: (MIDI);
    o ALTERADOR liga no jack (centro do rotativo) e a escolha CONTINUA seletor, acendendo a opcao viva"""
    c.js("warpOK = false; return 1")
    k = c.js("""const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
      const n = newNode(ref, [G6.scene.nodes.reduce((m, n) => Math.max(m, n.x + n.w), 0) + 200, 40], newModule('presets/atomos/Misturar.frag')); cvSig = ''; renderBoxes(); G6.dirty(); return chKey(n)""")
    time.sleep(0.6)
    MX = f"G6.scene.by[{json.dumps(k)}]"
    r = c.js(f"const n = {MX}; return [n.ctrls.filter(c => c.kind === 'rot').length, n.ctrls.filter(c => c.kind === 'btn').map(c => [c.t, c.bw, c.bh, c.sty])]")
    assert r[0] == 1 and len(r[1]) == 5 and all(b[3] == 'S1' for b in r[1]), f'Misturar (5 opcoes) nao virou ROTATIVO: {r}'
    assert all(b[2] >= 24 for b in r[1]), f'opcao com alvo < 24 px: {r[1]}'
    st = c.js(f"const n = {NK('Contornar')}; return [n.ctrls.filter(c => c.kind === 'notch').length, n.ctrls.filter(c => c.kind === 'btn').map(c => c.sty)]")
    assert st[0] == 1 and set(st[1]) == {'S2'}, f'Contornar (2 opcoes) nao virou FADER DE ENTALHES: {st}'
    c.js(f"const n = {MX}; G6.zoom(1); G6.cam.x = n.x - 100; G6.cam.y = n.y - 100; G6.dirty(); return 1")
    time.sleep(0.4)
    BT = lambda t: scr(c, f"(n => {{ const b = n.ctrls.find(c => c.kind === 'btn' && c.t === {json.dumps(t)}); return [n.x + b.x, n.y + b.y]; }})({MX})")
    c.click(*BT('multiplicar'))   # rotulo = direto
    time.sleep(0.3)
    assert _fx(c, MX, 'modo') == 3, f'clique no rotulo nao foi direto: {_fx(c, MX, "modo")}'
    x, y = BT('soma')
    c.send('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button='left', clickCount=1, modifiers=8)
    c.send('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button='left', clickCount=1, modifiers=8)
    time.sleep(0.3)
    assert _fx(c, MX, 'modo') == 2, f'Shift+clique nao voltou uma: {_fx(c, MX, "modo")}'
    rx, ry = scr(c, f"(n => {{ const r = n.ctrls.find(c => c.kind === 'rot'); return [n.x + r.x, n.y + r.y + 19]; }})({MX})")   # na SAIA (o centro = jack)
    c.send('Input.dispatchMouseEvent', type='mouseWheel', x=rx, y=ry, deltaX=0, deltaY=100)
    time.sleep(0.3)
    assert _fx(c, MX, 'modo') == 3, f'a roda nao passou pra proxima: {_fx(c, MX, "modo")}'
    c.drag([(rx, ry), (rx, ry - 25), (rx, ry - 50)])   # arrastar pra cima = passa por entalhes (pra frente)
    time.sleep(0.3)
    assert _fx(c, MX, 'modo') == 4, f'arrastar o rotativo nao passou pelo entalhe: {_fx(c, MX, "modo")}'
    sid = c.js(f"return stackOf({json.dumps(k)})[0].id || 0")
    assert c.js(f"return (CTRL['bar:{k}:{sid}:modo'] || {{}}).kind") == 'trig', 'o seletor saiu do MIDI'
    # FADER DE ENTALHES: arrastar o cursor = pula pro entalhe mais perto
    CK = NK('Contornar')
    c.js(f"const n = {CK}; G6.zoom(1); G6.cam.x = n.x - 100; G6.cam.y = n.y - 100; G6.dirty(); return 1")
    time.sleep(0.4)
    v0 = _fx(c, CK, 'fundo')
    a = scr(c, f"(n => {{ const t = n.ctrls.find(c => c.kind === 'notch'); return [n.x + t.stops[t.live()], n.y + t.y]; }})({CK})")
    b = scr(c, f"(n => {{ const t = n.ctrls.find(c => c.kind === 'notch'); return [n.x + t.stops[1 - t.live()] + 6, n.y + t.y + 4]; }})({CK})")
    c.drag([a, ((a[0] + b[0]) / 2, a[1]), b])
    time.sleep(0.3)
    assert _fx(c, CK, 'fundo') == 1 - v0, f'o cursor nao pulou de entalhe: {v0} -> {_fx(c, CK, "fundo")}'
    # ALTERADOR liga no CENTRO do rotativo; a escolha continua SELETOR e nao muda na mao
    c.js(f"const n = {NK('Matiz')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid = c.js("return G6.scene.ctls[0].id")
    b = scr(c, f"(n => {{ const r = n.ctrls.find(c => c.kind === 'rot'); return [n.x + r.x, n.y + r.y]; }})({MX})")
    a = scr(c, "(k => [k.x + k.out[0], k.y + k.out[1]])(G6.scene.ctls[0])")   # de FORA (o alterador) PRA DENTRO
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 40), b])
    time.sleep(0.6)
    assert c.js(f"return ((stackOf({json.dumps(k)})[0].mod || {{}}).modo || {{}}).id") == cid, 'o jack do rotativo nao ligou no alterador'
    r = c.js(f"const n = {MX}; return [n.ctrls.some(c => c.kind === 'rot' && c.md), n.knobs.map(k => k.n), (G6.scene.cvs.find(v => v.n === n && v.kn.n === 'modo') || {{}}).kn]")
    assert r[0] and 'modo' not in r[1], f'ligada, a escolha deixou de ser seletor: {r}'
    rot = c.js(f"const n = {MX}, q = n.ctrls.find(c => c.kind === 'rot'); return [q.x, q.y]")
    assert r[2] and abs(r[2]['x'] - rot[0]) < 1 and abs(r[2]['y'] - rot[1]) < 1, f'o cabo nao chega no centro do rotativo: {r[2]} x {rot}'
    v1 = c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, 'modo')")
    c.js(f"const n = {MX}; G6.zoom(1); G6.cam.x = n.x - 100; G6.cam.y = n.y - 100; G6.dirty(); return 1")
    time.sleep(0.4)
    c.click(*BT('soma'))
    time.sleep(0.3)
    assert c.js(f"const s = stackOf({json.dumps(k)})[0]; return fxVal({json.dumps(k)}, s, 'modo')") == v1, 'ligada, o rotulo ainda troca a opcao na mao'


@gesto
def t_desempenho(c):
    """desempenho: 40 nos (8 correntes x 5 atomos) — redesenhar e arrastar a vista sem travar (mede e guarda)"""
    ok = c.js("""const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind); if (!src) return 'sem fonte';
      const A = lastShaderList.filter(f => /presets\\/atomos\\//.test(f) && !isMaskFile(f)).slice(0, 12); if (A.length < 5) return 'sem atomos';
      for (let r = 0; r < 8; r++){ let prev = '@' + ensureRowId(src);
        for (let i = 0; i < 5; i++){ const n = newNode(prev, [360 + i * 300, 40 + r * 420], newModule(A[(r + i) % A.length])); prev = '@' + n.id; } }
      cvSig = ''; renderBoxes(); return 'ok'""")
    assert ok == 'ok', f'cena de desempenho: {ok}'
    time.sleep(0.6)
    r = c.js("""const T = []; for (let i = 0; i < 6; i++){ const t0 = performance.now(); cvSig = ''; renderBoxes(); document.body.offsetHeight; drawBoxWires(); document.body.offsetHeight; T.push(performance.now() - t0); }
      T.shift(); T.sort((a, b) => a - b);
      return { nos: document.querySelectorAll('#cv-in .bx').length, render_ms: +T[Math.floor(T.length / 2)].toFixed(1),
               tema: document.body.classList.contains('cel') ? 'cel' : 'foto', leve: document.body.classList.contains('leve') }""")
    c.send('Performance.enable')
    met = lambda: {m['name']: m['value'] for m in c.send('Performance.getMetrics')['metrics']}
    m0 = met()   # ARRASTAR A VISTA: 90 quadros rolando o canvas; o custo = trabalho da linha principal (script + estilo + layout + pintura)
    c.js("""await new Promise(res => { let n = 0; const step = () => { CV.scrollLeft += 4; CV.scrollTop += 2; if (++n < 90) requestAnimationFrame(step); else res(); };
      requestAnimationFrame(step); }); return 1""")
    m1 = met()
    r['quadro_ms'] = round((m1['TaskDuration'] - m0['TaskDuration']) * 1000 / 90, 2)
    r['pintura_ms'] = round(((m1.get('LayoutDuration', 0) - m0.get('LayoutDuration', 0)) + (m1.get('RecalcStyleDuration', 0) - m0.get('RecalcStyleDuration', 0))) * 1000 / 90, 2)
    c.js("setCvZoom(0.02); return 1")   # ZOOM MINIMO: todos os nos na vista, de bloco
    time.sleep(0.3)
    r2 = c.js("""const T = []; for (let i = 0; i < 6; i++){ const t0 = performance.now(); cvSig = ''; renderBoxes(); document.body.offsetHeight; drawBoxWires(); document.body.offsetHeight; T.push(performance.now() - t0); }
      T.shift(); T.sort((a, b) => a - b); return +T[Math.floor(T.length / 2)].toFixed(1)""")
    m0 = met()
    c.js("""await new Promise(res => { let n = 0; const step = () => { zoomFrame(0.02 + (n % 2) * 0.002, 300, 200, 4000, 3000); CV.scrollLeft += 2; if (++n < 60) requestAnimationFrame(step); else res(); };
      requestAnimationFrame(step); }); return 1""")   # = um quadro do zoom suave (zoomFrame) + rolar, de longe
    m1 = met()
    r['longe_render_ms'] = r2
    r['longe_quadro_ms'] = round((m1['TaskDuration'] - m0['TaskDuration']) * 1000 / 60, 2)
    c.js("setCvZoom(1); return 1")
    PERF.update(r)
    print('      desempenho:', json.dumps(r))
    assert r['nos'] >= 40, f'cena pequena: {r}'
    assert r['render_ms'] < 600, f'redesenho lento: {r}'
    assert r['longe_quadro_ms'] < 40, f'zoom de longe pesado: {r}'
    assert r['quadro_ms'] < 40, f'arrastar a vista ficou pesado (base antes da mini TV: ~23 ms headless sem GPU): {r}'


def main(filt):
    c, br, tmp, tpath = boot()
    fails = 0
    try:
        load(c)
        for t in T:
            if filt and not any(w in t.__name__ for w in filt):
                continue
            c.events.clear()
            try:
                c.mods = 0
                fixture(c)
                t(c)
                err = errors(c)
                if err:
                    raise AssertionError('erro de JS: ' + err[0])
                print(f'ok    {t.__name__[2:]:24} {t.__doc__.strip().splitlines()[0]}')
            except Exception as e:
                fails += 1
                print(f'FALHA {t.__name__[2:]:24} {t.__doc__.strip().splitlines()[0]}\n      -> {e}')
    finally:
        kill_browser(br)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'{len([t for t in T if not filt or any(w in t.__name__ for w in filt)]) - fails} ok, {fails} falha(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
