"""TESTES DE GESTO do dash5 (/v6, o canvas dos modulos como jogo; o canvas HTML de reserva e os testes dele sairam em 2026-11-26): o dash de verdade num navegador headless, mexido com mouse de verdade (CDP).

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


def fixture(c):
    """cena FIXA do teste (nao depende do tuning): camera -> Contornar -> Matiz -> saida"""
    ok = c.js("""lastOverlays = lastOverlays.filter(o => !isTapKey(o.file) && !o.kind && !o.dup);   // do zero: so' as fontes
      for (const k of Object.keys(lastBindings)) delete lastBindings[k];
      sel = { key: '', j: -1 }; msel.clear(); selWire = null; cable = null; closeWheel(); document.querySelectorAll('.nmenu').forEach(x => x.remove());
      if (!lastOverlays.some(o => !isTapKey(o.file))) lastOverlays.push({ file: 'webcam:/dev/video0', opacity: 1 });   // a semente do repo vem VAZIA (revisao geral R1)
      lastOverlays.forEach((o, i) => { o.xy = [40, 160 + i * 300]; });
      const src = lastOverlays.find(o => !isTapKey(o.file)); if (!src) return 'sem fonte';
      const A = 'presets/atomos/Contornar.frag', B = 'presets/atomos/Matiz.frag';
      if (!lastShaderList.includes(A) || !lastShaderList.includes(B)) return 'sem atomos';
      const a = newNode('@' + ensureRowId(src), [560, 160], newModule(A));   // (o filho do Contornar fica a' esquerda dele)
      const b = newNode('@' + a.id, [960, 160], newModule(B));
      newMix('out', '@' + b.id, [1340, 160]);
      const m = newMix('out', '@' + ensureRowId(src), [1340, 560]);
      inspClosed = selSig(); cvSig = ''; renderBoxes(); placeInsp(); return 'ok'""")
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


def mkb(c):
    return c.js("return mkBase(sel.key)")


FILHO = "Object.keys(lastBindings).find(k => tvNode(k) && boxEls[k] && boxEls[k].querySelector(':scope > .fil'))"


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
    for _ in range(40):   # (perfil novo abre no TOCAR: o canvas so' ganha tamanho no MONTAR)
        if c.js("return !!(G6 && G6.scene && G6.scene.nodes.length)"):
            break
        time.sleep(0.1)
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
def t6_cabo_clique_clique(c):
    """/v6 (2026-11-26, "arrastar os cabos no note e' muito ruim"): CLIQUE PEGA, CLIQUE SOLTA em todo cabo. Imagem: o clique tremido do
    touchpad (anda 6 px) deixa o cabo na mao; clique na entrada liga. Controle: clique no jack do alterador = cabo na mao; a roda so' faz
    zoom (o knob embaixo nao gira); clique no knob liga; direito cancela; clique no CENTRO do knob ligado pega a ponta, no vazio tira;
    Shift+clique junta knobs e o clique no vazio liga os juntados"""
    c.js("warpOK = false; return 1")
    mid, sk = c.js(f"return [rowOf({NK('Matiz')}.key).id, {SRC}.key]")
    o = scr(c, f"G6.outAt({SRC})")
    c.mods = 8   # Shift = cabo NOVO da saida
    c.drag([o, (o[0] + 6, o[1] + 2)])
    c.mods = 0
    time.sleep(0.3)
    assert c.js("return !!(cable && cable.sticky)"), 'o clique tremido (6 px) na saida nao deixou o cabo na mao'
    b = scr(c, f"G6.inAt({NK('Matiz')}, 'a', 0)")
    c.click(*b)
    time.sleep(0.5)
    assert c.js(f"return !cable && nodeKeyOfRef(rowById({json.dumps(mid)}).file) === {json.dumps(sk)}"), 'o 2o clique na entrada A nao ligou o cabo da mao'

    c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid = c.js("return G6.scene.ctls[0].id")
    uses = lambda: c.js(f"return mvUses({json.dumps(cid)}).length")
    n0 = uses()
    cout = "(c => [c.x + c.out[0], c.y + c.out[1]])(G6.scene.ctls[0])"
    c.click(*scr(c, cout))
    time.sleep(0.3)
    assert c.js("return !!(G6.hand() && G6.hand().sticky)"), 'clique no jack do alterador nao deixou o cabo na mao'
    K = NK('Matiz')
    v0, z0 = c.js(f"return [{CT(K, 'knob')}.get(), G6.cam.z]")
    x, y = scr(c, CTXY(K, 'knob'))
    for _ in range(3):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-100)
        time.sleep(0.03)
    time.sleep(0.5)
    v1, z1 = c.js(f"return [{CT(K, 'knob')}.get(), G6.cam.z]")
    assert z1 > z0 * 1.2 and abs(v1 - v0) < 1e-6, f'com o cabo na mao a roda devia so dar zoom: z {z0} -> {z1}, knob {v0} -> {v1}'
    assert c.js("return !!(G6.hand() && G6.hand().sticky)"), 'o zoom soltou o cabo da mao'
    c.click(*scr(c, CJXY(K)))
    time.sleep(0.5)
    assert uses() == n0 + 1 and not c.js("return G6.hand()"), f'o clique no knob nao ligou: {uses()} (era {n0})'

    c.click(*scr(c, cout))
    time.sleep(0.3)
    c.click(*c.js(f"return {FREE}"), button='right')
    time.sleep(0.3)
    assert not c.js("return G6.hand()") and uses() == n0 + 1, 'o direito nao cancelou o cabo da mao'

    c.click(*scr(c, CJXY(K)))   # o CENTRO do knob ligado = o jack: pega a ponta
    time.sleep(0.3)
    h = c.js("return G6.hand()")
    assert h and h['sticky'] and h['from'], f'clique no centro do knob ligado nao pegou a ponta: {h}'
    c.click(*c.js(f"return {FREE}"))
    time.sleep(0.5)
    assert uses() == n0 and not c.js("return G6.hand()"), 'clique no vazio com a ponta na mao nao tirou a ligacao'

    c.click(*scr(c, cout))
    time.sleep(0.3)
    c.mods = 8
    c.click(*scr(c, CJXY(K)))
    c.mods = 0
    time.sleep(0.3)
    h = c.js("return G6.hand()")
    assert h and h['sticky'] and h['n'] == 1 and uses() == n0, f'Shift+clique devia juntar o knob e manter o cabo na mao: {h}'
    c.click(*c.js(f"return {FREE}"))
    time.sleep(0.5)
    assert uses() == n0 + 1 and not c.js("return G6.hand()"), 'o clique no vazio nao ligou o knob juntado'



BODY = lambda node: f"(n => [n.x + n.G.sx + n.G.sw / 2, n.y + n.G.sy + n.G.sh / 2])({node})"   # o meio da TELA do modulo (arrasta; nao e' controle)


@v6
def t6_fio_recebe_modulo(c):
    """/v6 (fase 0): modulo SOLTO arrastado ate' um fio entra no MEIO dele (o fio acende antes); modulo LIGADO passando por cima de um fio
    so' anda (nao religa nada); quem estava em cima abre espaco (nada se sobrepoe depois)"""
    src_id, out_key = c.js("""const w = G6.scene.wires.find(w => w.a.kind === 'src' && w.b.kind === 'out'); return [rowOf(w.a.key).id || ensureRowId(rowOf(w.a.key)), w.b.key]""")
    mid = c.js(f"return rowOf({NK('Matiz')}.key).id")
    up0 = c.js(f"return rowById({json.dumps(mid)}).file")
    p = wire_pt(c, "w.a.kind === 'src' && w.b.kind === 'out'")
    assert p, 'sem trecho exposto do fio fonte -> saida'
    a = scr(c, BODY(NK('Matiz')))   # LIGADO por cima do fio: so' anda
    c.drag([a, ((a[0] + p[0]) / 2, (a[1] + p[1]) / 2), p])
    time.sleep(0.6)
    assert c.js(f"return rowById({json.dumps(mid)}).file") == up0, 'modulo LIGADO solto num fio religou (devia so andar)'
    c.js(f"G6.fit(true); return 1")
    time.sleep(0.3)
    lid = c.js("""const f = 'presets/atomos/Matiz.frag', w = G6.world({ clientX: 40, clientY: 40 });
      const ov = looseNode([Math.max(160, w[0]), Math.max(160, w[1])], prepItems([{ file: f }])); G6.dirty(); return ov.id""")
    time.sleep(0.6)
    assert c.js(f"const k = chKey(rowById({json.dumps(lid)})); return !!G6.scene.by[k]"), 'o modulo solto nao apareceu'
    p = wire_pt(c, "w.a.kind === 'src' && w.b.kind === 'out'")
    a = scr(c, BODY(f"G6.scene.by[chKey(rowById({json.dumps(lid)}))]"))
    hot = c.drag([a, ((a[0] + p[0]) / 2, (a[1] + p[1]) / 2), p, (p[0] + 1, p[1])], check=lambda i: c.js("return G6.hotWire()"))
    time.sleep(0.6)
    assert hot[-1], f'o fio nao acendeu com o modulo solto em cima: {hot}'
    r = c.js(f"""const o = rowById({json.dumps(lid)}), out = rowOf({json.dumps(out_key)}); return [o.file, (out.layers || []).map(L => L.from)]""")
    assert r[0] == '@' + src_id and '@' + lid in r[1], f'o modulo solto nao entrou no meio do fio fonte -> saida: {r}'
    over = c.js("""const R = G6.scene.nodes.map(n => [n.x, n.y, n.w, n.h]); let k = 0;
      for (let i = 0; i < R.length; i++) for (let j = i + 1; j < R.length; j++){ const a = R[i], b = R[j]; if (a[0] < b[0] + b[2] && a[0] + a[2] > b[0] && a[1] < b[1] + b[3] && a[1] + a[3] > b[1]) k++; } return k""")
    assert over == 0, f'{over} modulos se sobrepondo depois de entrar no fio (os vizinhos nao abriram espaco)'


@v6
def t6_sacudir_solta(c):
    """/v6 (fase 0): SACUDIR um modulo arrastando = ele sai da corrente (quem lia ele passa a ler o que ele lia) e fica sem entrada;
    arrastar normal (sem sacudir) nao solta"""
    mid, cid = c.js(f"return [rowOf({NK('Matiz')}.key).id, rowOf({NK('Contornar')}.key).id]")
    out_key = c.js(f"return G6.scene.wires.find(w => w.b.kind === 'out' && w.a.key === {NK('Matiz')}.key).b.key")
    a = scr(c, BODY(NK('Matiz')))
    c.drag([a, (a[0] + 40, a[1] + 120)])   # arrastar sem sacudir: continua ligado
    time.sleep(0.5)
    assert c.js(f"return nodeKeyOfRef(rowById({json.dumps(mid)}).file) === chKey(rowById({json.dumps(cid)}))"), 'arrastar normal soltou o modulo'
    a = scr(c, BODY(NK('Matiz')))
    pts = [a] + [(a[0] + (60 if i % 2 == 0 else -10), a[1]) for i in range(6)] + [(a[0] + 20, a[1] + 160)]
    c.drag(pts)
    time.sleep(0.6)
    r = c.js(f"""const o = rowById({json.dumps(mid)}), out = rowOf({json.dumps(out_key)}); return [nodeKeyOfRef(o.file), (out.layers || []).map(L => L.from)]""")
    assert r[0] is None and '@' + cid in r[1], f'sacudir nao soltou da corrente / a corrente nao fechou: {r}'


@v6
def t6_touchpad_rola(c):
    """/v6 (fase 0): no TOUCHPAD dois dedos ROLAM a vista (o zoom fica); a PINCA (wheel + Ctrl, como o Chromium manda) da' zoom"""
    x, y = c.js(f"return {FREE}")
    x0, y0, z0 = c.js("return [G6.cam.x, G6.cam.y, G6.cam.z]")
    for _ in range(6):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=6, deltaY=9.5)
        time.sleep(0.02)
    time.sleep(0.4)
    x1, y1, z1 = c.js("return [G6.cam.x, G6.cam.y, G6.cam.z]")
    assert z1 == z0 and x1 > x0 and y1 > y0, f'dois dedos deviam rolar sem zoom: ({x0},{y0},{z0}) -> ({x1},{y1},{z1})'
    for _ in range(6):
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-8, modifiers=2)
        time.sleep(0.02)
    time.sleep(0.5)
    z2 = c.js("return G6.cam.z")
    assert z2 > z1 * 1.2, f'a pinca nao deu zoom: {z1} -> {z2}'



@v6
def t6_teclas_e_desfazer(c):
    """/v6 (os testes do canvas HTML portados): clique no VAZIO tira a escolha (Delete depois nao apaga nada); Delete apaga o escolhido e
    Ctrl+Z volta; Ctrl+D duplica sem fios (a copia fica escolhida); Ctrl+A escolhe todos e Esc tira"""
    k = c.js(f"return {NK('Matiz')}.key")
    c.click(*scr(c, BODY(NK('Matiz'))))
    time.sleep(0.4)
    assert c.js("return mkBase(sel.key)") == k, 'o clique nao escolheu o modulo'
    c.click(*c.js(f"return {FREE}"))
    time.sleep(0.3)
    assert not c.js("return sel.key"), 'clique no vazio nao tirou a escolha'
    g0 = graph(c)
    c.key('Delete')
    time.sleep(0.3)
    assert graph(c) == g0, 'Delete apagou algo sem nada escolhido'
    n0 = c.js("return lastOverlays.length")
    c.click(*scr(c, BODY(NK('Matiz'))))
    time.sleep(0.4)
    c.key('Delete')
    time.sleep(0.4)
    assert c.js("return lastOverlays.length") == n0 - 1, 'Delete nao apagou o modulo escolhido'
    c.key('z', 2)
    time.sleep(0.6)
    assert c.js("return lastOverlays.length") == n0, 'Ctrl+Z nao trouxe de volta'
    c.js("G6.dirty(); return 1")
    time.sleep(0.4)
    c.click(*scr(c, BODY(NK('Matiz'))))
    time.sleep(0.4)
    k = c.js("return mkBase(sel.key)")
    c.key('d', 2)
    time.sleep(0.5)
    nk = c.js("return sel.key")
    assert c.js("return lastOverlays.length") == n0 + 1 and nk and nk != k, f'Ctrl+D nao duplicou / a copia nao ficou escolhida: {nk}'
    assert c.js(f"return rowOf({json.dumps(nk)}).file").startswith('@-'), 'a copia veio com fio'
    c.click(*c.js(f"return {FREE}"))
    c.key('a', 2)
    time.sleep(0.3)
    assert c.js("return msel.size") >= c.js("return G6.scene.nodes.length"), 'Ctrl+A nao escolheu todos'
    c.key('Escape')
    time.sleep(0.2)
    assert c.js("return msel.size") == 0, 'Esc nao tirou a escolha'


@v6
def t6_desempenho(c):
    """/v6: o quadro do jogo com a cena fixa fica leve (a media do laco, medida pelo proprio G6)"""
    time.sleep(1.2)
    st = c.js("return G6.stats")
    print('      desempenho:', json.dumps(st))
    assert st and st['fps'] > 0 and st['ms'] < 16, f'quadro pesado: {st}'



SRCN = "G6.scene.nodes.find(n => n.kind === 'src' && rowOf(n.key) && rowOf(n.key).id === SID)"


@v6
def t6_fonte_cartucho(c):
    """/v6 (fase 2): a FONTE e' um LEITOR com BANDEJA de cartuchos embaixo da tela — Shift + tecla de avancar = o proximo na hora;
    clique num cartucho = ele entra (sem BPM a grade nao segura); Ctrl+clique tira da bandeja; o que toca nao sai; a corrente fica"""
    key, its, sid = c.js("""const n = G6.scene.nodes.find(n => n.kind === 'src'); return [n.key, srcItems().map(x => x[0]), ensureRowId(rowOf(n.key))]""")
    alts = ([f for f in its if f != key] + ['default/_teste_cartucho_a.png', 'default/_teste_cartucho_b.png'])[:2]   # (o ambiente pode ter 1 midia so')
    reader = c.js(f"""window.SID = {json.dumps(sid)}; const o = rowOf({json.dumps(key)}); o.tray = [o.file, ...{json.dumps(alts)}]; sendOverlays(true); cvSig = ''; renderBoxes(); return 1""")
    time.sleep(0.6)
    readers = c.js(f"return G6.scene.wires.filter(w => w.a.key === {SRCN}.key).length")
    assert c.js(f"return {SRCN}.ctrls.filter(c => c.kind === 'cart').length") == 3, 'a bandeja nao mostra os 3 cartuchos'
    adv = scr(c, f"(n => (c => [n.x + c.x, n.y + c.y])(n.ctrls.find(c => c.kind === 'adv')))({SRCN})")
    c.mods = 8
    c.click(*adv)
    c.mods = 0
    time.sleep(0.6)
    assert c.js(f"return rowById(SID).file") == alts[0], f'a tecla de avancar nao trocou pro proximo: {c.js("return rowById(SID).file")}'
    assert c.js(f"return G6.scene.wires.filter(w => w.a.key === {SRCN}.key).length") == readers, 'trocar o cartucho mexeu na corrente'
    third = scr(c, f"(n => (c => [n.x + c.x, n.y + c.y])(n.ctrls.filter(c => c.kind === 'cart')[2]))({SRCN})")
    c.click(*third)
    time.sleep(0.6)
    assert c.js("return rowById(SID).file") == alts[1], 'clique no cartucho nao fez ele entrar'
    cur = scr(c, f"(n => (c => [n.x + c.x, n.y + c.y])(n.ctrls.filter(c => c.kind === 'cart')[2]))({SRCN})")
    c.mods = 2
    c.click(*cur)   # o que toca: fica
    c.mods = 0
    time.sleep(0.4)
    assert c.js("return trayOf(rowById(SID)).length") == 3, 'Ctrl+clique tirou o cartucho que esta tocando'
    first = scr(c, f"(n => (c => [n.x + c.x, n.y + c.y])(n.ctrls.filter(c => c.kind === 'cart')[0]))({SRCN})")
    c.mods = 2
    c.click(*first)
    c.mods = 0
    time.sleep(0.5)
    assert c.js("return trayOf(rowById(SID)).length") == 2, 'Ctrl+clique nao tirou o cartucho da bandeja'



def _evt(c, pred):   # um ALVO de evento (G6.evTargets) na tela
    p = c.js(f"const t = G6.evTargets().find(t => {pred}); return t ? G6.scr(t.at[0], t.at[1]) : null")
    assert p, f'sem alvo de evento: {pred}'
    return p


@v6
def t6_evento_cabo(c):
    """/v6 (fase 3): RELOGIO E SOM = os eventos como jacks QUADRADOS. Clique no jack + clique no LIGA = liga/desliga a cada kick; arrastar
    do jack ate' o gatilho de um alterador = ele dispara nesse evento (o knob que ele move tambem); no ▶▶ da fonte = troca de cartucho;
    num seletor = a proxima opcao; clique no cabo de evento + Delete tira; Esc cancela o cabo na mao"""
    c.js("warpOK = false; return 1")
    k = c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return n.key")
    time.sleep(0.6)
    c.js(f"const m = {NK('Matiz')}, yb = Math.max(...G6.scene.nodes.map(n => n.y + n.h), ...G6.scene.ctls.map(c => c.y + c.h)); newEvm([m.x, yb + 220]); return 1")   # embaixo de tudo: o cabo passa no vazio
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.5)
    mk = c.js(f"return {NK('Matiz')}.key")
    c.js("const t = document.getElementById('toast'); t.style.pointerEvents = 'none'; t.className = ''; return 1")   # o aviso nao cobre o jack
    j0 = scr(c, "G6.evJack(0)")
    assert c.js(f"const k = G6.pick({{ clientX: {j0[0]}, clientY: {j0[1]} }}); return [k && k.kind, document.elementFromPoint({j0[0]}, {j0[1]}).id]") == ['evj', 'gcv'], \
        c.js(f"const k = G6.pick({{ clientX: {j0[0]}, clientY: {j0[1]} }}); return [k && k.kind, document.elementFromPoint({j0[0]}, {j0[1]}).id, G6.cam.z]")
    c.click(*scr(c, "G6.evJack(0)"))   # kick
    time.sleep(0.3)
    assert c.js("return G6.evHandOn()"), 'clique no jack quadrado nao deixou o cabo de evento na mao'
    c.key('Escape')
    time.sleep(0.2)
    assert not c.js("return G6.evHandOn()"), 'Esc nao cancelou o cabo de evento'
    c.click(*scr(c, "G6.evJack(0)"))
    time.sleep(0.3)
    c.click(*_evt(c, f"t.t === 'led' && t.key === {json.dumps(mk)}"))
    time.sleep(0.5)
    assert c.js(f"return (stackOf({json.dumps(mk)})[0].acao || {{}}).alterna") == 'kick', 'o LIGA nao ficou ligado no kick'
    a = scr(c, "G6.evJack(4)")   # batida -> o gatilho do alterador (arrastando)
    b = _evt(c, "t.t === 'ctl'")
    c.drag([a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 30), b])
    time.sleep(0.6)
    r = c.js(f"const s = ctlStore()[0].mod.sinal, m = stackOf({json.dumps(k)})[0].mod[knobsOf(stackOf({json.dumps(k)})[0].file)[0]]; return [s.modo, s.ev.src, m.ev.src]")
    assert r == ['disparo', 'batida', 'batida'], f'o alterador (e o knob dele) nao passou a disparar na batida: {r}'
    sk = c.js("return G6.scene.nodes.find(n => n.kind === 'src').key")
    c.click(*scr(c, "G6.evJack(6)"))   # frase -> o leitor da fonte
    time.sleep(0.3)
    c.click(*_evt(c, f"t.t === 'adv' && t.key === {json.dumps(sk)}"))
    time.sleep(0.5)
    assert c.js(f"return (rowOf({json.dumps(sk)}).acao || {{}}).proximo") == 'frase', 'o leitor da fonte nao ficou ligado na frase'
    has_opt = c.js("return G6.evTargets().some(t => t.t === 'opt')")
    if has_opt:
        okey, on = c.js("const t = G6.evTargets().find(t => t.t === 'opt'); return [t.key, t.n]")
        c.click(*scr(c, "G6.evJack(5)"))   # compasso -> um seletor
        time.sleep(0.3)
        c.click(*_evt(c, f"t.t === 'opt' && t.key === {json.dumps(okey)} && t.n === {json.dumps(on)}"))
        time.sleep(0.5)
        assert c.js(f"return (stackOf({json.dumps(okey)})[0].acao || {{}})['opcao:' + {json.dumps(on)}]") == 'compasso', 'o seletor nao ficou ligado no compasso'
    p = c.js(f"""const l = G6.evLinks().find(l => l.del && l.del.t === 'led' && l.del.key === {json.dumps(mk)}), a = G6.evJack(0), b = l.at;
      const t = cableCfg().t, sag = t * (150 + Math.hypot(b[0] - a[0], b[1] - a[1])) * 0.8, C = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + sag];
      for (let u = 0.3; u < 0.8; u += 0.02){{ const q = [(1 - u) * (1 - u) * a[0] + 2 * (1 - u) * u * C[0] + u * u * b[0], (1 - u) * (1 - u) * a[1] + 2 * (1 - u) * u * C[1] + u * u * b[1]], s = G6.scr(q[0], q[1]);
        const k = G6.pick({{ clientX: s[0], clientY: s[1] }}); if (k && k.kind === 'ewire' && k.l.del.t === 'led' && document.elementFromPoint(s[0], s[1]) === document.getElementById('gcv')) return s; }} return null""")
    assert p, 'nao achei um trecho exposto do cabo de evento do LIGA'
    c.click(*p)
    time.sleep(0.3)
    c.key('Delete')
    time.sleep(0.5)
    assert not c.js(f"return (stackOf({json.dumps(mk)})[0].acao || {{}}).alterna"), 'clique no cabo de evento + Delete nao tirou a ligacao'
    assert c.js(f"return rowOf({json.dumps(mk)}) !== null"), 'Delete apagou o modulo em vez do cabo'
    cid = c.js("return G6.scene.ctls[0].id")   # o COMPARADOR do alterador (saida quadrada da direita) -> o LIGA do Matiz
    c.click(*scr(c, "(c => [c.x + c.L.cmp[0], c.y + c.L.cmp[1]])(G6.scene.ctls[0])"))   # (E2: o ½ mora na placa OUT)
    time.sleep(0.3)
    assert c.js("return G6.evHandOn()"), 'clique no comparador nao deixou o cabo de evento na mao'
    c.click(*_evt(c, f"t.t === 'led' && t.key === {json.dumps(mk)}"))
    time.sleep(0.5)
    assert c.js(f"return (stackOf({json.dumps(mk)})[0].acao || {{}}).alterna") == 'cmp:' + cid, 'o comparador nao ligou no LIGA'



@v6
def t6_pele_unica(c):
    """/v6 (fase 4): BLACKOUT sob TAMPA (1o clique levanta, o 2o aperta; ligado, 1 clique desliga); segurar Esc e soltar antes de 2 s NAO
    fecha (o anel some); cabo de IMAGEM = azuis, de SINAL = ambar; o visual tem um tema so' (o botao saiu)"""
    b = c.js("const r = document.getElementById('blk').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]")
    c.click(*b)
    time.sleep(0.2)
    assert c.js("const x = document.getElementById('blk'); return [!!x.dataset.open, x.classList.contains('on')]") == [True, False], 'o 1o clique devia so levantar a tampa'
    c.click(*b)
    time.sleep(0.4)
    assert c.js("return document.getElementById('blk').classList.contains('on')"), 'o 2o clique (tampa levantada) nao ligou o blackout'
    c.click(*b)
    time.sleep(0.4)
    assert not c.js("return document.getElementById('blk').classList.contains('on')"), 'blackout ligado: 1 clique devia desligar (a tampa nao segura a volta)'
    c.send('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.5)
    assert c.js("return !!document.getElementById('esc-ring')"), 'segurando Esc o anel nao apareceu'
    c.send('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.2)
    assert not c.js("return !!document.getElementById('esc-ring')"), 'soltar o Esc antes de 2 s nao cancelou'
    c.js(f"const n = {NK('Matiz')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    r = c.js("return [G6.scene.wires.every(w => CABLE_IMG.includes(w.col)), G6.scene.cvs.length > 0 && G6.scene.cvs.every(v => CABLE_CV.includes(v.col))]")
    assert r == [True, True], f'cor do cabo por tipo (imagem azul, sinal ambar): {r}'
    assert c.js("return !document.getElementById('tema-btn')"), 'o botao de tema continua na tela'   # (repaginada: saiu do arquivo)


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
    b = c.js("const b = document.querySelector('.nmenu .nm-list .nm-it'); const r = b.getBoundingClientRect(); return [r.left + 30, r.top + r.height / 2]")   # a MESMA lista da roda (C11)
    c.click(*b)
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
    for _ in range(3):   # (fase 0) ALT + roda no knob = gira; a vista fica
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=kx, y=ky, deltaX=0, deltaY=-100, modifiers=1)
        time.sleep(0.03)
    time.sleep(0.5)
    z1, v1 = c.js(f"return [G6.cam.z, {CT(NK('Matiz'), 'knob')}.get()]")
    assert z1 == z0 and v1 > v0, f'Alt + roda no knob: zoom {z0}->{z1}, valor {v0}->{v1}'
    for _ in range(3):   # SEM Alt a roda nunca mexe no show: zoom
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=kx, y=ky, deltaX=0, deltaY=-100)
        time.sleep(0.03)
    time.sleep(0.5)
    z2, v2 = c.js(f"return [G6.cam.z, {CT(NK('Matiz'), 'knob')}.get()]")
    assert z2 > z1 * 1.2 and abs(v2 - v1) < 1e-6, f'roda sem Alt em cima do knob devia dar zoom e nao girar: zoom {z1}->{z2}, valor {v1}->{v2}'


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
    time.sleep(0.15)
    assert c.js("return G6.flying()"), 'o caber tudo devia VOAR (animado), nao pular'
    time.sleep(0.8)
    r = c.js("""const r = document.getElementById('gcv').getBoundingClientRect(); return G6.scene.nodes.every(n => { const a = G6.scr(n.x, n.y), b = G6.scr(n.x + n.w, n.y + n.h);
      return a[0] >= r.left - 1 && a[1] >= r.top - 1 && b[0] <= r.right + 1 && b[1] <= r.bottom + 1; })""")
    assert r, 'caber tudo deixou no fora da vista'


@v6
def t6_botoes_parados(c):
    """/v6 (REPAGINADA 2026-11-27, B "cantos"): a barra do canvas SAIU; a VISTA e' uma pilula no canto de baixo a' direita (desfazer, zoom,
    caber, ⋯). O ⋯ abre POR CIMA dela (arrumar, cabos, programa) sem mexer em nenhum botao; o zoom muda o rotulo sem empurrar; clicar fora fecha"""
    assert c.js("return !document.getElementById('cv-h') && !document.getElementById('cable-btn') && !document.getElementById('pv-btn')"), 'a barra do canvas devia ter saido'
    r = c.js("const n = document.getElementById('cv-nav').getBoundingClientRect(), w = document.getElementById('gcv').getBoundingClientRect(); return [n.right <= w.right, n.bottom <= w.bottom, n.bottom > w.bottom - 40, n.left > w.left + w.width / 2]")
    assert r == [True] * 4, f'a pilula devia morar no canto de baixo a direita: {r}'
    pos = "return ['undo-btn', 'cvz-out', 'cvz-in', 'cvz-fit', 'nav-more'].map(i => { const r = document.getElementById(i).getBoundingClientRect(); return [Math.round(r.left), Math.round(r.width)]; })"
    p0 = c.js(pos)
    c.click(*center(c, '#nav-more'))
    time.sleep(0.3)
    assert c.js("return !document.getElementById('nav-menu').hidden"), 'o menu ⋯ nao abriu'
    assert c.js(pos) == p0, f'abrir o menu mexeu nos botoes: {p0} -> {c.js(pos)}'
    r = c.js("const a = document.getElementById('nav-menu').getBoundingClientRect(), b = document.getElementById('cv-nav').getBoundingClientRect(); return [a.bottom <= b.top + 1, a.right <= b.right + 1, a.width > 200, !!document.querySelector('#nav-menu #tidy-btn'), !!document.querySelector('#nav-menu #cable-t'), document.querySelectorAll('#pv-seg button').length]")
    assert r == [True, True, True, True, True, 3], f'o menu devia abrir em cima da pilula com arrumar, cabos e programa: {r}'
    c.js("G6.zoom(0.3); return 1")
    time.sleep(0.4)
    c.js("G6.zoom(1); return 1")
    time.sleep(0.4)
    assert c.js(pos) == p0, 'o rotulo do zoom mudou de largura e empurrou os botoes'
    c.click(40, 140)   # o vazio do canvas, longe do menu
    time.sleep(0.3)
    assert c.js("return document.getElementById('nav-menu').hidden"), 'clicar fora nao fechou o menu'


@v6
def t6_programa_monitor(c):
    """/v6 (REPAGINADA 2026-11-27): o PROGRAMA = um monitor preso no canto de BAIXO a' direita, EM CIMA da pilula (nao cobre a pilula);
    ▾ recolhe numa aba NO AR no mesmo canto; clicar na aba traz de volta; "fundo" pelo menu ⋯"""
    c.js("setPvw({ st: 'win' }); return 1")
    time.sleep(0.6)
    r = c.js("const a = document.getElementById('pvw').getBoundingClientRect(), b = document.getElementById('cv-nav').getBoundingClientRect(); return [!document.getElementById('pvw').hidden, a.bottom <= b.top + 1, Math.abs(a.right - b.right) < 3, a.width > 150]")
    assert r == [True, True, True, True], f'o monitor devia ficar no canto de baixo, em cima da pilula: {r}'
    c.click(*center(c, '#pvw-x'))
    time.sleep(0.4)
    r = c.js("const t = document.getElementById('pvw-tab'), a = t.getBoundingClientRect(), b = document.getElementById('cv-nav').getBoundingClientRect(); return [document.getElementById('pvw').hidden, !t.hidden, a.bottom <= b.top + 1]")
    assert r == [True, True, True], f'▾ devia recolher numa aba NO AR em cima da pilula: {r}'
    c.click(*center(c, '#pvw-tab'))
    time.sleep(0.4)
    assert c.js("return !document.getElementById('pvw').hidden && document.getElementById('pvw-tab').hidden"), 'a aba nao trouxe o monitor de volta'
    c.click(*center(c, '#nav-more'))
    time.sleep(0.3)
    c.click(*center(c, '#pv-seg button[data-st="bg"]'))
    time.sleep(0.4)
    assert c.js("return document.getElementById('pvw').classList.contains('bg')"), 'o menu ⋯ nao pos o programa de fundo'
    c.js("setPvw({ st: 'off' }); navPop(false); return 1")


@v6
def t6_cena_vai_volta(c):
    """/v6 (REPAGINADA 2026-11-27, pedido: "controle de cena tipo vai e volta e atribuir cenas pro MIDI"): ◀ / ▶ na barra de cima trocam pra
    cena de antes / a seguinte da lista (da' a volta); a PROXIMA aparece do lado e acende o GO; Equipamento › Controle tem um botao de
    MIDI learn por cena (e ◀ ▶ GO) que arma o learn sem fechar a gaveta"""
    for nm in ('vv-a', 'vv-b'):
        if not c.js(f"return lastScenes.some(s => s.name === {json.dumps(nm)})"):
            c.js(f"scenePost('/scene-new', {{ name: {json.dumps(nm)} }}); return 1")
            time.sleep(0.8)
    names = c.js("return lastScenes.map(s => s.name)")
    assert len(names) >= 2, f'precisava de 2 cenas: {names}'
    a0 = c.js("return activeScene")
    i0 = names.index(a0) if a0 in names else -1
    c.click(*center(c, '#sc-next'))
    for _ in range(20):
        time.sleep(0.15)
        if c.js("return activeScene") != a0:
            break
    a1 = c.js("return activeScene")
    assert a1 == names[(i0 + 1) % len(names)], f'▶ devia ir pra seguinte: {a0} -> {a1} ({names})'
    c.click(*center(c, '#sc-prev'))
    for _ in range(20):
        time.sleep(0.15)
        if c.js("return activeScene") != a1:
            break
    assert c.js("return activeScene") == names[i0 % len(names)], '◀ devia voltar'
    c.js(f"cueScene({json.dumps(names[-1])}); return 1")
    time.sleep(0.5)
    r = c.js("return [document.getElementById('cue-name').textContent, document.getElementById('go-top').classList.contains('ready')]")
    assert r == [names[-1], True], f'a PROXIMA devia aparecer na barra e acender o GO: {r}'
    c.js("cueScene(''); openDrawer('eq', 'controle'); return 1")
    time.sleep(0.6)
    n = c.js("return document.querySelectorAll('#midi-box .mscenes button').length")
    assert n == 3 + len(names), f'um botao de MIDI por cena + ◀ ▶ GO: {n}'
    c.click(*center(c, '#midi-box .mscenes button', 0))
    time.sleep(0.3)
    r = c.js("return [MIDI.learn, MIDI.armed, drawer]")
    assert r == [True, 'scene:prev', 'eq'], f'o botao devia armar o learn pra ◀ sem fechar a gaveta: {r}'
    c.js("setLearn(false); openDrawer(''); return 1")


@v6
def t6_saude_na_boia(c):
    """/v6 (REPAGINADA 2026-11-27): os avisos de saude sairam da barra (os chips) e moram NA BOIA: o numero de problemas em cima dela e a
    lista no titulo; clique = o diagnostico"""
    assert c.js("return !document.getElementById('ann') && !document.querySelector('#top .hc')"), 'os chips de saude deviam ter saido da barra'
    r = c.js("renderHealth.sig = ''; renderHealth(); const bad = healthRows.filter(r => SEV[r.sev] > 0).length, n = document.querySelector('#sos-btn .cnt'); return [bad, n ? n.textContent : null, n ? n.hidden : null]")
    assert r[1] == (str(r[0]) if r[0] else '') and r[2] == (not r[0]), f'a boia devia mostrar quantos problemas: {r}'


@v6
def t6_mao(c):
    """/v6 (REPAGINADA 2026-11-27, as macros: "viram o modulo MAO"): o modulo da roda (Mao) tem 4 faders M1-M4 e 4 pads. Arrastar o fader
    muda a macro; clique no jack do fader + clique num knob = o knob segue a macro (faixa de/ate' dentro da MAO); o pad manda pad:N na hora;
    escolher + Delete tira a MAO e solta os knobs"""
    c.js("const yb = Math.max(...G6.scene.nodes.map(n => n.y + n.h)); newMao([40, yb + 40]); G6.fit(true); return 1")
    time.sleep(0.8)
    assert c.js("return [maoStore().length, ctlStore().filter(c => isMaoId(c.id)).length, G6.scene.maos.length, G6.scene.ctls.filter(c => c.mao).length].join()") == '1,4,1,4', 'a MAO nao nasceu inteira'
    c.js("newMao([0, 0]); return 1")
    assert c.js("return maoStore().length") == 1, 'so\' uma MAO por cena'
    c.js("G6.zoom(1); const m = G6.scene.maos[0], r = document.getElementById('gcv').getBoundingClientRect(); G6.cam.x = m.x - 200; G6.cam.y = m.y - 200; G6.dirty(); return 1")
    time.sleep(0.5)
    a = scr(c, "(m => [m.x + 85, m.y + 118])(G6.scene.maos[0])")
    b = scr(c, "(m => [m.x + 85, m.y + 52])(G6.scene.maos[0])")
    c.drag([a, b])
    time.sleep(0.4)
    assert c.js("return macroV[1]") > 0.8, f'arrastar o fader M2 pra cima devia subir a macro: {c.js("return macroV")}'
    c.js("window.__grid = []; const f0 = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/grid')) __grid.push(o && o.body); return f0(u, o); }; return 1")
    c.click(*scr(c, "(m => [m.x + 230, m.y + 60])(G6.scene.maos[0])"))
    time.sleep(0.3)
    assert any('pad:1' in (x or '') for x in c.js("return __grid")), 'o pad 1 nao mandou o evento'
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    K = NK('Matiz')
    c.click(*scr(c, "(m => [m.x + 39, m.y + 166])(G6.scene.maos[0])"))
    time.sleep(0.3)
    assert c.js("return !!(G6.hand() && G6.hand().sticky)"), 'clique no jack do fader nao deixou o cabo na mao'
    c.click(*scr(c, CTXY(K, 'knob')))
    time.sleep(0.6)
    kn = c.js(f"const n = {K}; return ((stackOf(n.key)[0].mod || {{}})[knobsOf(n.an.file)[0]] || {{}}).id || ''")
    assert kn == 'mao-m1', f'o knob devia seguir o M1: {kn!r}'
    assert c.js("return G6.scene.maos[0].rows.length === 1 && G6.scene.cvs.some(v => v.c.id === 'mao-m1')"), 'a faixa/cabo do M1 nao apareceu'
    c.click(*scr(c, "(m => [m.x + 150, m.y + 20])(G6.scene.maos[0])"))
    time.sleep(0.3)
    assert c.js("return msel.has('mao:' + G6.scene.maos[0].id)"), 'clicar no corpo devia escolher a MAO'
    c.key('Delete')
    time.sleep(0.6)
    r = c.js(f"const n = {K}; return [maoStore().length, ctlStore().filter(c => isMaoId(c.id)).length, !!((stackOf(n.key)[0].mod || {{}})[knobsOf(n.an.file)[0]])]")
    assert r == [0, 0, False], f'Delete devia tirar a MAO e soltar o knob: {r}'


@v6
def t6_envelope_e2(c):
    """/v6 (REPAGINADA 2026-11-27, E2): o GATILHO (entrada de evento) mora na coluna da esquerda com o nome em plaqueta; as DUAS saidas
    (sinal redondo e o ½ quadrado) juntas na placa OUT da direita; o evento sem modulo (secao) vira o NOME do gatilho; o gatilho e' alvo"""
    c.js(f"const n = {NK('Matiz')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.5)
    c.js(f"const n = {NK('Contornar')}; applyPreset(n.key, 0, knobsOf(n.an.file)[1], 'drop'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    r = c.js("""return G6.scene.ctls.filter(c => !c.mao).map(c => [c.L.gin[0] > 0 && c.L.gin[0] < 50, c.L.out[0] === c.L.cmp[0], c.L.out[0] > c.w - 40, c.L.cmp[1] > c.L.out[1],
      c.L.gin[0] < c.L.scr.x && c.L.out[0] > c.L.scr.x + c.L.scr.w, c.trig])""")
    assert len(r) == 2 and all(x[:5] == [True] * 5 for x in r), f'gatilho a esquerda, sinal e ½ juntos na placa OUT: {r}'
    assert sorted(x[5] for x in r) == ['drop', 'gatilho'], f'o evento sem modulo (secao drop) devia virar o nome do gatilho: {r}'
    assert c.js("const c = G6.scene.ctls.find(c => !c.mao); return G6.evTargets().some(t => t.t === 'ctl' && t.id === c.id && Math.abs(t.at[0] - c.x - c.L.gin[0]) < 1)"), 'o gatilho devia ser alvo de cabo de evento'



@v6
def t6_peles(c):
    """/v6 (PELES 2026-11-27, "faça todas podendo mudar" + "faça tudo escuro"): o menu ⋯ troca a pele na hora (lembrada); cada pele desenha sem
    erro, e' ESCURA (corpo dos modulos e mesa) e cumpre o contraste prometido (texto >= 4,5:1, ponteiro >= 3:1); 'Hoje' volta ao de sempre"""
    ids = c.js("return Object.keys(SKINS)")
    assert len(ids) >= 10, ids
    c.click(*center(c, '#nav-more'))
    time.sleep(0.3)
    assert c.js("return document.querySelectorAll('#skin-list button').length") == len(ids), 'o menu devia listar as peles'
    c.click(*center(c, '#skin-list button[data-skin="neon"]'))
    time.sleep(0.6)
    assert c.js("return [document.body.dataset.skin, document.body.classList.contains('skinned'), LS.get('v6skin', '')].join()") == 'neon,true,neon', 'o clique nao trocou a pele'
    c.js("navPop(false); return 1")
    for sk in ids:
        c.js(f"setSkin({json.dumps(sk)}); return 1")
        time.sleep(0.5)
        bad = c.js("return skinContrast(SK.id).filter(r => r[1] < r[2])")
        assert not bad, f'{sk}: contraste abaixo do minimo: {bad}'
        if sk != 'atual':
            dk = c.js("return [relL(SK.mod.base[0]), relL(SK.mod.base[1])]")
            assert max(dk) < 0.2, f'{sk}: os modulos deviam ser escuros: {dk}'
        assert c.js("return G6.stats.fps > 0 && G6.scene.nodes.length > 0"), f'{sk}: o quadro parou'
    c.js("setSkin('atual'); return 1")
    time.sleep(0.4)
    assert c.js("return [document.body.dataset.skin, document.body.classList.contains('skinned'), !!SK.mod].join()") == 'atual,false,false', 'Hoje devia voltar ao de sempre'


OUT_SRC = "G6.scene.nodes.find(n => n.kind === 'out' && inputsOf(rowOf(n.key)).some(w => nodeKeyOfRef(w.ref) === ({SRC}).key))".replace('{SRC}', SRC)


@v6
def t6_cabo_cor_fixa(c):
    """/v6 (2026-11-26, pedido: "ao pegar um cabo ele muda de cor, isso nao deve acontecer"): pegar a ponta de um cabo de IMAGEM = a mao tem
    a cor DELE; ligado noutra entrada, continua com ela. Cabo de CONTROLE: pegar no centro do knob = a mao com a cor dele; noutro knob, a mesma"""
    w0 = f"G6.scene.wires.find(w => w.b === {NK('Matiz')} && w.wid.t === 'a')"
    col0 = c.js(f"return {w0}.col")
    c.click(*scr(c, f"G6.inAt({NK('Matiz')}, 'a', 0)"))
    time.sleep(0.3)
    assert c.js("return !!(cable && cable.sticky)"), 'clique na entrada ligada nao pegou a ponta'
    assert c.js("return cable.col") == col0, f'a mao mudou a cor do cabo: {col0} -> {c.js("return cable.col")}'
    out2 = c.js(f"return {OUT_SRC}.key")
    c.click(*scr(c, f"(n => [n.x + n.ports.L[0][0], n.y + n.ports.L[0][1]])(G6.scene.by[{json.dumps(out2)}])"))
    time.sleep(0.6)
    col1 = c.js(f"return (G6.scene.wires.find(w => w.b.key === {json.dumps(out2)} && w.a === {NK('Contornar')}) || {{}}).col")
    assert col1 == col0, f'ligado noutra entrada o cabo trocou de cor: {col0} -> {col1}'

    c.js(f"const n = {NK('Matiz')}; applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cc0 = c.js(f"return G6.scene.cvs.find(v => v.n === {NK('Matiz')}).col")
    c.click(*scr(c, CJXY(NK('Matiz'))))
    time.sleep(0.3)
    assert c.js("return G6.hand() && G6.hand().col") == cc0, f'a mao do cabo de controle mudou de cor: {cc0} -> {c.js("return G6.hand() && G6.hand().col")}'
    c.click(*scr(c, CJXY(NK('Contornar'))))
    time.sleep(0.6)
    cc1 = c.js(f"return (G6.scene.cvs.find(v => v.n === {NK('Contornar')}) || {{}}).col")
    assert cc1 == cc0, f'o cabo de controle ligado noutro knob trocou de cor: {cc0} -> {cc1}'


@v6
def t6_inverter_alterador(c):
    """/v6 (2026-11-26, pedido: "botao no envelope pra inverter o sinal: o que sobe no kick passa a descer"): a tecla do alterador vira a faixa
    de TODAS as ligacoes (de > ate'); ligacao nova de um invertido ja' nasce invertida; de novo = volta"""
    kn = c.js(f"const n = {NK('Matiz')}, k = knobsOf(n.an.file)[0]; applyPreset(n.key, 0, k, 'pulsa'); cvSig = ''; renderBoxes(); return k")
    time.sleep(0.6)
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    cid = c.js("return G6.scene.ctls[0].id")
    lohi = lambda: c.js(f"return mvUseLoHi(ctlRowsOf({json.dumps(cid)})[0])")
    lo, hi = lohi()
    assert lo < hi, f'o pulsa devia nascer subindo: {lo} {hi}'
    b = scr(c, "(c => [c.x + c.L.inv[0], c.y + c.L.inv[1]])(G6.scene.ctls[0])")
    c.click(*b)
    time.sleep(0.5)
    lo2, hi2 = lohi()
    assert abs(lo2 - hi) < 1e-3 and abs(hi2 - lo) < 1e-3, f'a tecla nao inverteu a faixa: {lo},{hi} -> {lo2},{hi2}'
    assert c.js(f"return ctlInverted({json.dumps(cid)})"), 'o alterador nao ficou invertido'
    c.js(f"const n = {NK('Contornar')}; linkMv(n.key, 0, knobsOf(n.an.file)[0], {json.dumps(cid)}); return 1")
    time.sleep(0.4)
    r = c.js(f"return ctlRowsOf({json.dumps(cid)}).map(u => mvUseLoHi(u))")
    assert len(r) == 2 and all(a > b_ for a, b_ in r), f'a ligacao nova de um invertido devia nascer invertida: {r}'
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    c.click(*scr(c, "(c => [c.x + c.L.inv[0], c.y + c.L.inv[1]])(G6.scene.ctls[0])"))
    time.sleep(0.5)
    r = c.js(f"return ctlRowsOf({json.dumps(cid)}).map(u => mvUseLoHi(u))")
    assert all(a < b_ for a, b_ in r), f'a 2a vez nao voltou ao normal: {r}'


@v6
def t6_trocar_fonte(c):
    """/v6 (2026-11-26, pedido: "trocar a fonte de algo que ja' existe direto no canvas"): o "+" no fim da bandeja abre ali a lista de
    fontes (a que toca marcada); escolher outra = o leitor passa a tocar ela (e ela entra na bandeja); Esc fecha"""
    ADD = f"(n => {{ const q = n.ctrls.find(c => c.kind === 'addc'); return [n.x + q.x, n.y + q.y]; }})({SRC})"
    c.click(*scr(c, ADD))
    time.sleep(0.4)
    r = c.js("const l = document.querySelector('.nmenu.wh-list'); return l ? [l.querySelector('.nm-h').textContent, l.querySelectorAll('.nm-it').length, l.querySelectorAll('.nm-it.cur').length] : null")
    n_src, has = c.js(f"return [srcItems().length, srcItems().some(x => x[0] === rowOf({SRC}.key).file)]")
    assert r and r[0] == 'trocar a fonte' and r[1] == n_src and r[2] == (1 if has else 0), f'o "+" devia abrir a lista de TODAS as fontes ({n_src}), a que toca marcada ({has}): {r}'
    if r[1] - r[2] >= 1:
        sid, f0 = c.js(f"const o = rowOf({SRC}.key); return [o.id, o.file]")
        c.js("tpCfg.quant = ''; return 1")
        i = c.js("return [...document.querySelectorAll('.nmenu.wh-list .nm-it')].findIndex(b => !b.classList.contains('cur'))")
        c.click(*center(c, '.nmenu.wh-list .nm-it', i))
        time.sleep(0.6)
        f1 = c.js(f"return rowById({json.dumps(sid)}).file")
        assert f1 != f0, 'escolher outra fonte nao trocou o leitor'
        assert c.js(f"return trayOf(rowById({json.dumps(sid)})).includes({json.dumps(f0)})"), 'a fonte de antes devia ficar na bandeja'
    else:
        print("      (nenhuma outra fonte no ambiente: a troca em si nao foi testada)")
        c.key('Escape')
        time.sleep(0.3)
        assert not c.js("return !!document.querySelector('.nmenu.wh-list')"), 'Esc nao fechou a lista'


@v6
def t6_modo_unico(c):
    """/v6 (2026-11-26, pedido: "abandonar o TOCAR: toca nessa tela mesmo, tipo um VCV"): sem TOCAR|MONTAR, F1 nao muda nada, sem o botao
    MISTURA (o mixer vem da roda), SOCORRO = so' o icone sem tampa"""
    r = c.js("return [document.body.dataset.mode, !!document.getElementById('mode-seg'), !!document.getElementById('add-mix'), document.getElementById('sos-btn').textContent.replace(/\\d+/g, '').trim(), !!document.getElementById('sos-btn').dataset.guard]")
    assert r == ['montar', False, False, '', False], f'modo unico / barra: {r}'
    c.key('F1')
    time.sleep(0.3)
    assert c.js("return document.body.dataset.mode === 'montar' && document.getElementById('gcv').getBoundingClientRect().width > 300"), 'F1 mexeu na tela'


@v6
def t6_equipamento_abas(c):
    """/v6 (revisao 2026-11-26): as 5 abas do EQUIPAMENTO desenham o que mostram — o CONTROLE abria VAZIO (o onEqShow esperava os nomes
    velhos 'midi'/'teclas'); a ajuda das teclas sem TOCAR; na BIBLIOTECA o cartao de grupos legado some vazio e renomear/apagar so' com o mouse"""
    c.js("openDrawer('eq', 'controle'); return 1")
    time.sleep(0.5)
    r = c.js("return [document.getElementById('midi-box').children.length, document.getElementById('keyhelp').children.length, document.getElementById('keyhelp').textContent]")
    assert r[0] > 0 and r[1] > 5, f'a aba CONTROLE abriu vazia: midi {r[0]}, teclas {r[1]}'
    assert 'TOCAR' not in r[2] and 'MONTAR' not in r[2], 'a ajuda das teclas ainda fala de TOCAR/MONTAR'
    c.js("openDrawer('eq', 'lib'); return 1")
    time.sleep(0.6)
    r = c.js("""const b = document.querySelector('#eq .lrow .btn'); return [!!document.getElementById('group-admin'), b ? getComputedStyle(b).opacity : null]""")
    assert not r[0], 'o cartao de GRUPOS (v4) saiu na limpeza (revisao geral, Frente 6)'
    assert r[1] in (None, '0'), f'renomear/apagar deviam aparecer so com o mouse em cima: opacidade {r[1]}'
    c.js("openDrawer(''); return 1")


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
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-100, modifiers=1)
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
        c.send('Input.dispatchMouseEvent', type='mouseWheel', x=m[0], y=m[1], deltaX=0, deltaY=-100, modifiers=1)   # (fase 0) Alt = a roda mexe no controle
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
    c.send('Input.dispatchMouseEvent', type='mouseWheel', x=x, y=y, deltaX=0, deltaY=-100, modifiers=1)
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
    r = c.js("""const S = wheelSectors(), B = [...document.querySelectorAll('.wheel .wh-s:not(.in)')], BI = [...document.querySelectorAll('.wheel .wh-s.in')];
      const all = lastShaderList.filter(f => isAtomFile(f) && metaOf(f).atom && f !== LUMA && !metaOf(f).oculto), seen = {};   // // oculto: (B3) fica fora de proposito
      for (const s of S) for (const it of s.items()) if (it.spec && it.spec.kind === 'mod') seen[it.spec.file] = (seen[it.spec.file] || 0) + 1;
      for (const s of S) if (s.id === 'cat:mascara') for (const it of s.items()) seen[lastShaderList.find(f => fxName(f) === it.t && catOf(f) === 'mascara')] = 1;
      const ctr = BI.map(b => { const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }), mid = document.querySelector('.wheel .wh-mid').getBoundingClientRect();
      const dist = ([x, y]) => Math.hypot(x - mid.left - mid.width / 2, y - mid.top - mid.height / 2), dOut = B.map(b => { const r = b.getBoundingClientRect(); return dist([r.left + r.width / 2, r.top + r.height / 2]); });
      return { l: S.map(s => s.l), n: S.map(s => s.items().length), mat: B.map(b => b.classList.contains('mat')), bg: B.map(b => !!b.style.backgroundImage),
        inn: BI.map(b => b.textContent), dIn: Math.max(...ctr.map(dist)), dOut: Math.min(...dOut),
        falta: all.filter(f => !seen[f]).map(fxName), dup: Object.entries(seen).filter(([f, n]) => n > 1).map(([f]) => f) }""")
    c.js("closeWheel(); return 1")
    L = r['l']
    assert len(L) == len(set(L)), f'fatia duplicada: {L}'
    assert all(n > 0 for n in r['n']), f'fatia vazia: {list(zip(L, r["n"]))}'
    assert L[0] == 'Fontes' and 'mistura e saída' in L and 'máscaras' in L, f'fatias: {L}'
    assert r['inn'] == ['Relógio', 'Som', 'Imagem e corpo', 'Mão'], f'anel de dentro (alteradores por familia): {r["inn"]}'
    assert r['dIn'] + 70 <= r['dOut'], f'os aneis se encostam: dentro {r["dIn"]:.0f} px, fora {r["dOut"]:.0f} px'
    assert not ({'Movimentos', 'Misturas', 'mistura', 'outros', 'alteradores'} & set(L)), f'categoria antiga na roda: {L}'
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
    r = c.js("""const S = wheelSectors().filter(s => s.ring === 'in'), it = S.flatMap(s => s.items());
      return { hs: S.map(s => s.l), n: S.map(s => s.items().length), semG: ctlItems().filter(x => !FAMS.some(f => f[0] === x.g)).map(x => x.name), nomes: it.map(x => x.t) }""")
    assert r['hs'] == ['Relógio', 'Som', 'Imagem e corpo', 'Mão'] and all(r['n']), f'familias na roda: {r["hs"]} {r["n"]}'
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
    c.send('Input.dispatchMouseEvent', type='mouseWheel', x=rx, y=ry, deltaX=0, deltaY=100, modifiers=1)   # (fase 0) Alt = a roda mexe no controle
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


@v6
def t6_fader_rotulo(c):
    """/v6 (revisao geral R4, 2026-11-27): o rotulo de um fader nunca quebra em 2 linhas nem cobre o valor ('BRILHO MAXIMO' em cima do 100%)"""
    c.js("openDrawer('eq', 'saida'); return 1")
    time.sleep(0.6)
    r = c.js("""return [...document.querySelectorAll('.fader')].filter(f => f.offsetParent && !f.classList.contains('mini')).map(f => {
        const l = f.querySelector('.f-lb'), v = f.querySelector('.f-val'); if (!l || !l.textContent || !v) return null;
        const a = l.getBoundingClientRect(), b = v.getBoundingClientRect();
        return [l.textContent, Math.round(a.height), a.right > b.left + 1 ? 1 : 0, Math.round(f.getBoundingClientRect().width)]; }).filter(Boolean)""")
    c.js("openDrawer(''); return 1")
    assert r, 'nenhum fader com rotulo visivel na aba Saida'
    bad = [x for x in r if x[1] > 16 or x[2]]
    assert not bad, f'rotulo de fader quebrado ou por cima do valor: {bad}'
    lim = [x for x in r if 'brilho' in x[0].lower()]
    assert lim and lim[0][3] >= 200, f'o fader do brilho maximo encolheu: {lim}'


@v6
def t6_desfazer_por_cena(c):
    """/v6 (revisao geral C4): trocar de cena GUARDA o desfazer daquela cena (antes zerava) e Ctrl+Shift+Z / Ctrl+Y refaz"""
    k0 = c.js("return undoStack.length")
    c.js("const o = lastOverlays.find(o => !o.kind && !isTapKey(o.file)); o.opacity = 0.42; sendOverlays(true); return 1")
    time.sleep(0.3)
    assert c.js("return undoStack.length") == k0 + 1, 'a mudanca nao entrou no desfazer'
    c.key('z', 2)   # Ctrl+Z
    time.sleep(0.3)
    assert c.js("return [undoStack.length, redoStack.length, lastOverlays.find(o => !o.kind && !isTapKey(o.file)).opacity]")[:2] == [k0, 1], 'Ctrl+Z nao foi pro refazer'
    c.key('z', 2 | 8)   # Ctrl+Shift+Z
    time.sleep(0.3)
    r = c.js("return [undoStack.length, redoStack.length, lastOverlays.find(o => !o.kind && !isTapKey(o.file)).opacity]")
    assert r == [k0 + 1, 0, 0.42], f'Ctrl+Shift+Z nao refez: {r}'
    c.js("window._cena0 = activeScene; sceneLeft(_cena0, 'outra cena'); return 1")   # sai pra outra cena: a pilha dela (vazia)
    assert c.js("return undoStack.length") == 0, 'a cena nova herdou o desfazer da outra'
    c.js("sceneLeft('outra cena', _cena0); return 1")   # volta: a pilha de antes
    assert c.js("return undoStack.length") == k0 + 1, 'voltar pra cena perdeu o desfazer dela'


@v6
def t6_cena_segurar(c):
    """/v6 (revisao geral C5): a LETRA de uma cena so' poe no ar SEGURADA (como 1-9); tocada sem querer so' avisa"""
    c.js("window._went = []; window._goScene0 = goScene; goScene = n => _went.push(n); lastScenes.push({name: 'teste q', key: 'q'}); return 1")
    try:
        c.key('q')   # toque rapido
        time.sleep(0.7)
        assert c.js("return _went.length") == 0, 'uma letra TOCADA pos a cena no ar'
        assert 'segure Q' in c.js("return document.getElementById('toast').textContent"), 'o toque nao avisou que e pra segurar'
        c.send('Input.dispatchKeyEvent', type='keyDown', key='q', code='KeyQ', windowsVirtualKeyCode=81)
        time.sleep(0.7)
        c.send('Input.dispatchKeyEvent', type='keyUp', key='q', code='KeyQ', windowsVirtualKeyCode=81)
        assert c.js("return _went") == ['teste q'], 'segurar a letra nao pos a cena no ar'
    finally:
        c.js("goScene = _goScene0; lastScenes = lastScenes.filter(s => s.name !== 'teste q'); return 1")


def _wheel_pick(c, x, y, typed):
    """abre a roda em (x, y) pelo Enter (o mouse la'), digita e clica no 1o item da lista"""
    c.mouse('mouseMoved', x, y)
    time.sleep(0.1)
    c.key('Enter')
    time.sleep(0.3)
    mid = c.js("const m = document.querySelector('.wheel .wh-mid'); return m ? m.textContent : null")
    c.send('Input.insertText', text=typed)   # (revisao geral B1-A) a lista ja' abre com o cursor no campo
    time.sleep(0.4)
    b = c.js("const b = document.querySelector('.wh-list .nm-it'); if (!b) return null; const r = b.getBoundingClientRect(); return [r.left + 30, r.top + r.height / 2]")
    assert b, 'a lista da roda nao mostrou nada pra ' + typed
    c.click(*b)
    time.sleep(0.6)
    return mid


@v6
def t6_ir_ate(c):
    """/v6 (revisao geral C1): Ctrl+F abre o IR ATE'; digitar o nome + Enter escolhe o modulo e a vista VOA ate' ele (de longe ate' perto)"""
    c.js("G6.zoomTo(0.25); return 1")
    time.sleep(0.6)
    c.key('f', 2)
    time.sleep(0.3)
    assert c.js("return !!document.querySelector('.cfind')"), 'Ctrl+F nao abriu o ir ate'
    c.send('Input.insertText', text='matiz')
    time.sleep(0.2)
    assert c.js("return document.querySelectorAll('.cfind .nm-it').length") >= 1, 'a busca nao achou o Matiz'
    c.key('Enter')
    time.sleep(1.0)
    r = c.js("""const n = G6.scene.by[mkBase(sel.key)], R = document.getElementById('gcv').getBoundingClientRect(), [sx, sy] = G6.scr(n.x + n.w / 2, n.y + n.h / 2);
      return [visName(mkBase(sel.key)), Math.round(sx - (R.left + R.width / 2)), Math.round(sy - (R.top + R.height / 2)), G6.cam.z, !!document.querySelector('.cfind')]""")
    assert r[0] == 'Matiz' and abs(r[1]) < 40 and abs(r[2]) < 40 and r[3] > 0.5 and not r[4], f'nao voou ate o Matiz: {r}'
    c.js("selectNone(); G6.fit(true); return 1")


@v6
def t6_roda_depois_do_escolhido(c):
    """/v6 (revisao geral C2): com um modulo escolhido, o atomo da roda ENTRA DEPOIS dele (no fio que sai dele, se for um so'); antes nascia solto"""
    k = c.js("const n = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)); setSel(n.key, 0, true); return n.key")
    nw = c.js(f"return G6.outWires(mkBase({json.dumps(k)})).length")
    e = c.js(f"return {FREE}")
    mid = _wheel_pick(c, *e, 'desfocar')
    r = c.js(f"""const o = rowOf(mkBase(sel.key)); return [visName(mkBase(sel.key)), o.file, '@' + rowOf(mkBase({json.dumps(k)})).id,
      G6.outWires(mkBase({json.dumps(k)})).length, G6.outWires(mkBase(sel.key)).length]""")
    assert r[0] != 'Matiz' and r[1] == r[2], f'o novo nao le o escolhido: {r}'
    if nw == 1:
        assert r[3] == 1 and r[4] == 1, f'com um fio saindo, o novo devia entrar NO fio (quem lia o Matiz le o novo): {r}'
    c.js("undo(); selectNone(); return 1")
    time.sleep(0.4)


@v6
def t6_alvo_24px(c):
    """/v6 (revisao geral C6): na abertura (~60%) a area de pegar um JACK tem >= 24 px na tela (WCAG 2.5.8; antes ~18 px a 68%)"""
    c.js("G6.zoomTo(0.58); return 1")
    time.sleep(0.6)
    r = c.js("""const n = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), o = G6.outAt(n), [sx, sy] = G6.scr(o[0], o[1]);
      const hit = dx => { const p = G6.pick({ clientX: sx + dx, clientY: sy }); return !!(p && p.kind === 'out'); }; return [hit(11), hit(-11), hit(0)]""")
    c.js("G6.fit(true); return 1")
    assert all(r), f'o jack OUT nao pega a 11 px do centro (alvo < 24 px): {r}'


@v6
def t6_enquadrar_e_nome_longe(c):
    """/v6 (revisao geral C7, C8): G enquadra o ESCOLHIDO (de novo = volta); de longe (< 42%) o nome do modulo continua escrito (plaqueta fixa)"""
    c.js("G6.fit(true); const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); setSel(n.key, 0, true); return 1")
    z0 = c.js("return G6.cam.z")
    c.key('g')
    time.sleep(0.9)
    z1 = c.js("return G6.cam.z")
    assert z1 > z0 * 1.2, f'G nao enquadrou o escolhido: {z0} -> {z1}'
    c.key('g')
    time.sleep(0.9)
    assert abs(c.js("return G6.cam.z") - z0) < 0.02, 'G de novo nao voltou pra vista de antes'
    c.js("selectNone(); G6.zoomTo(0.25); return 1")
    time.sleep(0.8)
    # a plaqueta: um pixel CLARO no topo do modulo (texto branco sobre fundo escuro)
    r = c.js("""const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)), [sx, sy] = G6.scr(n.x + n.w / 2, n.y), cv = document.getElementById('gcv'),
      R = cv.getBoundingClientRect(), d = devicePixelRatio, px = cv.getContext('2d').getImageData(Math.round((sx - R.left - 30) * d), Math.round((sy - R.top + 4) * d), Math.round(60 * d), Math.round(14 * d)).data;
      let hi = 0; for (let i = 0; i < px.length; i += 4) if (px[i] > 220 && px[i + 1] > 220 && px[i + 2] > 220) hi++; return hi""")
    c.js("G6.fit(true); return 1")
    assert r > 8, f'de longe o nome do modulo sumiu (pixels de texto: {r})'


@v6
def t6_menu_direito(c):
    """/v6 (revisao geral C9, C10): DIREITO num fio = ir a' origem / ao destino / tirar; DIREITO num knob = aprender MIDI ali mesmo"""
    p = wire_pt(c, "w.b.an && /Matiz/.test(w.b.an.file)")
    assert p, 'sem um ponto exposto do fio que chega no Matiz'
    c.click(*p, button='right')
    time.sleep(0.3)
    its = c.js("return [...document.querySelectorAll('.ctxm .nm-it b')].map(b => b.textContent)")
    assert its == ['ir à origem', 'ir ao destino', 'tirar o fio'], f'o menu do fio veio errado: {its}'
    c.js("[...document.querySelectorAll('.ctxm .nm-it')][1].click(); return 1")
    time.sleep(0.9)
    r = c.js("""const n = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), R = document.getElementById('gcv').getBoundingClientRect(), [sx, sy] = G6.scr(n.x + n.w / 2, n.y + n.h / 2);
      return [Math.round(sx - (R.left + R.width / 2)), Math.round(sy - (R.top + R.height / 2))]""")
    assert abs(r[0]) < 40 and abs(r[1]) < 40, f'"ir ao destino" nao levou a vista ate o Matiz: {r}'
    c.js("G6.fit(true); return 1")
    time.sleep(0.4)
    k = scr(c, "(() => { const n = " + NK('Contornar') + ", kn = n.ctrls.find(q => q.kind === 'knob' || q.kind === 'rot'); return [n.x + kn.x, n.y + kn.y]; })()")
    c.click(*k, button='right')
    time.sleep(0.3)
    its = c.js("return [...document.querySelectorAll('.ctxm .nm-it b')].map(b => b.textContent)")
    assert its and its[0] == 'aprender MIDI', f'o menu do knob nao oferece aprender MIDI: {its}'
    c.js("[...document.querySelectorAll('.ctxm .nm-it')][0].click(); return 1")
    time.sleep(0.2)
    r = c.js("return [MIDI.learn, MIDI.armed]")
    c.js("setLearn(false); return 1")
    assert r[0] and r[1], f'aprender MIDI nao armou o knob: {r}'


@v6
def t6_proxima_visivel(c):
    """/v6 (revisao geral R3): cada cena que NAO esta' no ar tem a tecla "próx" a' vista (antes marcar a PROXIMA era so' clique direito)"""
    c.js("lastScenes.push({name: 'outra q', key: ''}); sceneSig = ''; renderScenes(); document.body.classList.add('cn-open'); return 1")
    time.sleep(0.2)
    r = c.js("""const b = [...document.querySelectorAll('#scenes .pad')].map(p => [p.querySelector('.nm').textContent, !!p.querySelector('.nx'), p.querySelector('.nx') ? Math.round(p.querySelector('.nx').getBoundingClientRect().height) : 0]); return b""")
    c.js("lastScenes = lastScenes.filter(s => s.name !== 'outra q'); sceneSig = ''; renderScenes(); document.body.classList.remove('cn-open'); return 1")
    o = [x for x in r if x[0] == 'outra q']
    assert o and o[0][1] and o[0][2] >= 22, f'a cena fora do ar nao tem o "próx" a vista (ou e pequeno): {r}'
    act = c.js("return activeScene")
    assert not [x for x in r if x[0] == act and x[1]], f'a cena NO AR nao devia ter "próx": {r} (no ar: {act})'


@v6
def t6_lista_unica(c):
    """/v6 (revisao geral B1-A, B3, B5): a roda abre JA' com a lista "procurar em tudo" e o cursor no campo; a ★ fixa o item no topo
    (favoritos) e o usado entra em recentes; sem o Fundo (= Assunto invertido, oculto) e sem alterador de nome repetido"""
    c.js("libFav = []; libRec = []; LS.set('v6fav', []); LS.set('v6rec', []); return 1")
    e = c.js(f"return {FREE}")
    c.mouse('mouseMoved', *e)
    c.key('Enter')
    time.sleep(0.4)
    r = c.js("const q = document.querySelector('.wh-list input'); return [!!q, document.activeElement === q]")
    assert r == [True, True], f'a roda nao abriu com a busca em foco: {r}'
    c.js("const st = [...document.querySelectorAll('.wh-list .nm-it')].find(b => b.querySelector('.nm-t').textContent === 'Matiz').querySelector('.star'); st.click(); return 1")
    time.sleep(0.2)
    top = c.js("const g = document.querySelector('.wh-list .pgt'), b = document.querySelector('.wh-list .nm-it .nm-t'); return [g && g.textContent, b && b.textContent]")
    assert top == ['★ favoritos', 'Matiz'], f'a estrela nao pos o Matiz no topo: {top}'
    c.key('Escape')
    c.js("closeWheel(); return 1")
    names = c.js("return wheelSectors().flatMap(s => s.items().map(i => i.t))")
    assert 'Fundo' not in names and 'Assunto' in names, 'o Fundo (oculto) ainda aparece pra montar'
    ct = c.js("return ctlItems().map(c => c.name)")
    assert len(ct) == len(set(ct)), f'alterador com nome repetido: {sorted(ct)}'
    c.js("libFav = []; LS.set('v6fav', []); return 1")


@v6
def t6_entrada_simples(c):
    """/v6 (revisao geral A1-A5): a ENTRADA abre SIMPLES (volume, kick, grave, medio, agudo + auto-ganho); o medidor cheio = o que o ALTERADOR
    recebe (depois do limiar), o claro = o que entra; AVANCADO mostra as 8 faixas com nome em portugues; PERFIL salva e lista"""
    c.js("LS.set('v6audio', 'simples'); setAudModo('simples'); openDrawer('eq', 'entrada'); return 1")
    time.sleep(0.6)
    r = c.js("""return [document.getElementById('eq-audio').classList.contains('simples'), document.querySelectorAll('#aud-simple .asc').length,
      !!document.querySelector('#aud-ag'), document.getElementById('cols').offsetParent === null, [...document.querySelectorAll('#aud-simple .asc .cn')].map(e => e.textContent)]""")
    assert r[:4] == [True, 5, True, True] and r[4] == ['volume', 'kick', 'grave', 'médio', 'agudo'], f'a entrada simples veio errada: {r}'
    c.js("""bandGate['Sub-bass'] = {m: 'ativa', th: 0.7}; renderSimple({bands: [{name: 'amp', raw_level: 0.5, final: 0.5}, {name: 'Sub-bass', raw_level: 0.8, final: 0.6},
      {name: 'Low-mid', raw_level: 0.1, final: 0.1}], kick: {decay: 0.3, final: 0.9}}); return 1""")
    r = c.js("return [ASC.grave.iIn.tgt, ASC.grave.iOut.tgt, ASC.kick.iOut.tgt, ASC.grave.th.hidden]")
    assert abs(r[0] - 0.8) < 1e-6 and abs(r[1] - 0.1) < 1e-6 and abs(r[2] - 0.9) < 1e-6 and r[3] is False, f'o medidor nao mostra o que entra x o que o alterador recebe: {r}'
    c.js("delete bandGate['Sub-bass']; setAudModo('avancado'); return 1")
    time.sleep(0.3)
    r = c.js("return [document.getElementById('cols').offsetParent !== null, [...document.querySelectorAll('#cols .cn')].map(e => e.textContent)]")
    assert r[0] and 'sub' in r[1] and 'Sub-bass' not in r[1] and 'volume' in r[1], f'o avancado nao mostrou as faixas em portugues: {r}'
    c.js("setAudModo('simples'); window._pf = null; perfilPost('salvar', 'mic da casa').then(x => window._pf = x); return 1")
    time.sleep(0.6)
    r = c.js("return [window._pf && window._pf.perfis, [...document.querySelectorAll('#aud-perfil option')].map(o => o.value)]")
    assert r[0] == ['mic da casa'] and 'mic da casa' in r[1], f'o perfil nao salvou/listou: {r}'
    c.js("perfilPost('apagar', 'mic da casa'); openDrawer(''); return 1")
    time.sleep(0.3)


@v6
def t6_telao(c):
    """/v6 (revisao geral P1-P5): TELAO = aba propria com os passos 1 Palco / 2 Raster / 3 Saidas e a barra de LOAD-IN (teste por bloco,
    identificar, exportar PNG, casa); setas movem a tela escolhida 1 px no raster (Shift = 10); a casa salva e lista"""
    c.js("openDrawer('eq', 'telao'); return 1")
    time.sleep(0.6)
    r = c.js("""return [document.getElementById('eq-telas').offsetParent !== null, document.getElementById('eq-saida').offsetParent === null,
      [...document.querySelectorAll('#stg-view button')].map(b => b.textContent), !!document.getElementById('tl-loadin').offsetParent]""")
    assert r[0] and r[1] and r[2] == ['1 · Palco', '2 · Raster', '3 · Saídas no palco'] and r[3], f'a aba Telao veio errada: {r}'
    c.js("""lastScreens = [{name: 'esq', x: 0, y: 0, w: 2, h: 1, pw: 400, ph: 200, ox: 10, oy: 20}, {name: 'dir', x: 2.2, y: 0, w: 2, h: 1, pw: 400, ph: 200, ox: 410, oy: 20}];
      lastPM = {on: 1, w: 820, h: 240}; pmTouched = scrTouched = now(); sendScreens(false); scrSel = 0; setStgView('raster'); return 1""")
    time.sleep(0.3)
    c.send('Input.dispatchKeyEvent', type='keyDown', key='ArrowRight', code='ArrowRight', windowsVirtualKeyCode=39)
    c.send('Input.dispatchKeyEvent', type='keyUp', key='ArrowRight', code='ArrowRight', windowsVirtualKeyCode=39)
    c.send('Input.dispatchKeyEvent', type='keyDown', key='ArrowDown', code='ArrowDown', windowsVirtualKeyCode=40, modifiers=8)
    c.send('Input.dispatchKeyEvent', type='keyUp', key='ArrowDown', code='ArrowDown', windowsVirtualKeyCode=40, modifiers=8)
    time.sleep(0.2)
    r = c.js("return [lastScreens[0].ox, lastScreens[0].oy]")
    assert r == [11, 30], f'as setas nao moveram o bloco 1 px (Shift = 10): {r}'
    r = c.js("const cv = mapPng(); return [cv.width, cv.height]")
    assert r[0] == 1600 and r[1] > 300, f'o PNG do mapa nao saiu: {r}'
    c.js("window._cs = null; casaPost('salvar', 'galpao').then(x => window._cs = x); return 1")
    time.sleep(0.6)
    r = c.js("return [window._cs && window._cs.casas, [...document.querySelectorAll('#tl-casa option')].map(o => o.value)]")
    assert r[0] == ['galpao'] and 'galpao' in r[1], f'a casa nao salvou/listou: {r}'
    c.js("casaPost('apagar', 'galpao'); scrSel = -1; openDrawer(''); return 1")
    time.sleep(0.3)


@v6
def t6_js_python_concordam(c):
    """(revisao geral F4) o que o PAINEL (JS) e o MOTOR (Python) precisam concordar: ids estaveis, migracao de cena antiga, eixos da tela
    girada, nomes de faixa/evento/forma de LFO/presets/modos de mistura — antes ~20 pares copiados a mao sem teste"""
    import dash_data as D, dash_server as DS
    keys = ['webcam:/dev/video0', 'default/a.mp4#2', 'presets/atomos/Matiz.frag', 'ção']
    assert c.js(f"return {json.dumps(keys)}.map(stableId)") == [D.stable_id(k) for k in keys], 'stableId != dash_data.stable_id'
    old = [{'file': 'webcam:/dev/video0', 'opacity': 0.5}, {'file': 'default/a.mp4', 'off': 1}, {'file': 'default/b.png', 'blend': 'soma'}]
    js = c.js(f"const o0 = lastOverlays; lastOverlays = {json.dumps(old)}; migrateGraph(); const r = JSON.parse(JSON.stringify(lastOverlays)); lastOverlays = o0; return r")
    py = D.migrate_graph(json.loads(json.dumps(old)))
    strip = lambda L: [{k: v for k, v in o.items() if k not in ('xy', 'n', 'nome')} for o in L]
    assert strip(js) == strip(py), f'migrateGraph != migrate_graph:\n JS {js}\n PY {py}'
    t = {'x': 1, 'y': 0.5, 'w': 2, 'h': 1, 'rot': 30}
    ax = c.js(f"const a = shapeAxes({json.dumps(t)}); return [a.o || a[0], a.ex || a[1], a.ey || a[2]]")
    py = D.screen_axes(t)
    flat = lambda v: [round(float(x), 6) for p in v for x in (p if isinstance(p, (list, tuple)) else [p['x'] if isinstance(p, dict) else p])]
    jsf = [round(float(x), 6) for p in ax for x in (p if isinstance(p, list) else [p[k] for k in ('x', 'y')] if isinstance(p, dict) else [p])]
    assert jsf == flat(py), f'shapeAxes != screen_axes: {ax} x {py}'
    r = c.js("return [BAND_NAMES, SOUND_EV, LFO_SHAPES.map(x => x[0]), Object.keys(PRESET_TXT), LAYER_BLENDS.map(x => x[0]), GRP_BANDS]")
    assert r[0] == list(D.BAND_NAMES), f'faixas: {r[0]}'
    assert r[1] == list(D.SOUND_EVENTS), f'eventos do som: {r[1]}'
    assert r[2] == list(D.LFO_SHAPES), f'formas de LFO: {r[2]}'
    assert set(D.MOV_PRESETS) <= set(r[3]), f'preset sem texto no painel: {set(D.MOV_PRESETS) - set(r[3])}'
    assert r[4] == list(DS.LAYER_BLENDS), f'modos de mistura: {r[4]}'
    uni = dict(zip(D.BAND_NAMES, ('subbass', 'lowmid', 'midrange', 'highmid', 'presence', 'treble_hi', 'brilho', 'air')))
    assert {g: [uni[b] for b in bs] for g, bs in r[5].items()} == {g: list(v) for g, v in D.SOUND_GROUPS.items()}, f'grupos grave/medio/agudo: {r[5]}'


@v6
def t6_canvas_vazio(c):
    """/v6 (revisao geral R1): canvas VAZIO diz por onde comecar (antes: preto, sem dica; a 1a abertura do app vinha com a webcam e um video
    que nao existiam); a gaveta do Equipamento deixa o canvas a' vista (<= 640 px)"""
    c.js("lastOverlays = []; for (const k of Object.keys(lastBindings)) delete lastBindings[k]; sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes(); G6.dirty(); return 1")
    time.sleep(1.2)
    r = c.js("""const cv = document.getElementById('gcv'), d = devicePixelRatio, R = cv.getBoundingClientRect(), px = cv.getContext('2d').getImageData(Math.round(R.width / 2 * d - 150 * d), Math.round(R.height / 2 * d - 26 * d), Math.round(300 * d), Math.round(20 * d)).data;
      let hi = 0; for (let i = 0; i < px.length; i += 4) if (px[i] > 200 && px[i + 1] > 200 && px[i + 2] > 200) hi++; return [G6.scene.nodes.filter(n => n.an || (n.L && n.L.kind === 'src')).length, hi]""")
    assert r[0] == 0 and r[1] > 40, f'o canvas vazio nao mostrou a dica: {r}'
    c.js("openDrawer('eq', 'entrada'); return 1")
    time.sleep(0.4)
    w = c.js("return Math.round(document.getElementById('eq').getBoundingClientRect().width)")
    c.js("openDrawer(''); return 1")
    assert w <= 640, f'a gaveta do Equipamento cobre o canvas: {w} px'


@v6
def t6_hud_motor(c):
    """/v6 (revisao geral R5): o HUD do canvas mostra o MOTOR (fps de verdade da saida e os ms de trabalho por quadro), nao so' o painel"""
    c.js("renderTop({output: {fps: 41.5, fps_target: 60, ms: 21.3}}); return 1")
    r = c.js("return motorHud && [motorHud.fps, motorHud.tgt, motorHud.ms]")
    assert r == [41.5, 60, 21.3], f'o HUD nao recebeu o motor: {r}'


def main(filt):
    c, br, tmp, tpath = boot()
    fails = 0
    try:
        for t in T:
            if filt and not any(w in t.__name__ for w in filt):
                continue
            c.events.clear()
            try:
                c.mods = 0
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
