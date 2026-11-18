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
    """abre o /v5 em MONTAR, espera os nos aparecerem; sel = v5sel guardado antes (pra testar o 'abre fechado')"""
    c.send('Page.navigate', url=f'http://127.0.0.1:{PORT}/v5')
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
