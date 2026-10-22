#!/usr/bin/env python3
"""LUZES: refletores DMX e fitas LED seguindo a SAIDA (cor da zona do canvas) + o som (faixas).

Sai por Art-Net (UDP 6454): no DMX/Art-Net, WLED (fita LED, aceita Art-Net nativo), mesas e
softwares de luz. So' stdlib. Configuracao em tuning.LIGHTS (dash: depois):

LIGHTS = {'on': 1, 'host': '255.255.255.255', 'fps': 40, 'fixtures': [
    {'name': 'par esq', 'ch': 'drgb', 'uni': 0, 'addr': 1, 'zone': [0, 0, 0.5, 1]},
    {'name': 'fita', 'ch': 'rgb', 'count': 60, 'uni': 1, 'addr': 1, 'zone': [0, 0.9, 1, 0.1],
     'mod': {'b': ['subbass', 'kick'], 'lo': 0.2, 'hi': 1.0}, 'smooth': 0.6},
]}

- ch: um canal DMX por letra: r g b w (branco = o comum do rgb) d (dimmer = brilho) x (fixo 0).
  'rgb' par simples, 'drgb' par com dimmer, 'rgbw', 'd' so' dimmer.
- count > 1 = FITA: repete o padrao `ch` count vezes (pixel i = fatia i da zona, no eixo maior);
  passou de 512 canais continua no universo seguinte (como o WLED espera).
- zone [x, y, w, h] 0..1 no canvas, origem em cima (= OVERLAYS rect). Ausente = canvas todo.
- cor: media da zona; 'color': [r, g, b] 0..255 = cor fixa (so' o brilho segue o som).
- mod = o mesmo ♪ dos knobs (native._mod_value): brilho vai de lo (silencio) a hi pela faixa
  marcada mais forte. Sem mod = brilho da imagem.
- smooth 0..0.95 (padrao 0.5): suaviza a cor no tempo — refletor piscando a cada frame cansa.
O master/blackout da saida (OUTPUT_GRADE.master) vale pras luzes tambem.
"""
import concurrent.futures
import json
import socket
import time
import urllib.request

import numpy as np

ARTNET_PORT = 6454
_HDR = b'Art-Net\x00' + (0x5000).to_bytes(2, 'little') + (14).to_bytes(2, 'big')
_POLL = b'Art-Net\x00' + (0x2000).to_bytes(2, 'little') + (14).to_bytes(2, 'big') + bytes([0x02, 0])


def artnet_packet(uni, data, seq=0):
    """ArtDmx: universo 15 bits (net/subnet/universe), ate' 512 canais (tamanho par)."""
    data = bytes(data[:512])
    if len(data) % 2:
        data += b'\x00'
    return _HDR + bytes([seq & 0xFF, 0]) + (uni & 0x7FFF).to_bytes(2, 'little') + len(data).to_bytes(2, 'big') + data


def _zone(img, zone):
    """recorte da zona (pelo menos 1 px) de img (h, w, 3) topo->baixo."""
    h, w = img.shape[:2]
    x, y, zw, zh = zone or (0, 0, 1, 1)
    x0, y0 = min(w - 1, max(0, int(x * w))), min(h - 1, max(0, int(y * h)))
    return img[y0:max(y0 + 1, min(h, int(round((y + zh) * h)))), x0:max(x0 + 1, min(w, int(round((x + zw) * w))))]


def _channels(rgb, ch, bright):
    """(r, g, b) 0..255 -> bytes na ordem de `ch`, ja' com o brilho 0..1."""
    r, g, b = rgb
    w = min(r, g, b)
    if 'w' in ch:   # rgbw: o branco sai pelo LED branco, nao misturado
        r, g, b = r - w, g - w, b - w
    if 'd' in ch:   # com dimmer: a cor vai cheia e o dimmer leva o brilho
        k = 255.0 / max(1.0, r, g, b, w)
        r, g, b, w = r * k, g * k, b * k, w * k
        d, bright = 255.0 * bright * max(rgb) / 255.0, 1.0
    else:
        d = 0.0
    v = {'r': r * bright, 'g': g * bright, 'b': b * bright, 'w': w * bright, 'd': d, 'x': 0.0}
    return bytes(min(255, max(0, int(round(v.get(c, 0.0))))) for c in ch)


def fixture_colors(img, fx, prev=None):
    """[(r, g, b)] por pixel do aparelho (1, ou count na fita), suavizado com o frame anterior."""
    n = max(1, int(fx.get('count', 1)))
    z = _zone(img, fx.get('zone'))
    if fx.get('color'):
        cols = [tuple(float(c) for c in fx['color'][:3])] * n
    elif n == 1:
        cols = [tuple(z.reshape(-1, 3).mean(0))]
    else:   # fita: n fatias no eixo maior da zona
        horiz = z.shape[1] >= z.shape[0]
        L = z.shape[1] if horiz else z.shape[0]
        cols = []
        for i in range(n):
            a, b = int(i * L / n), max(int(i * L / n) + 1, int((i + 1) * L / n))
            s = z[:, a:b] if horiz else z[a:b]
            cols.append(tuple(s.reshape(-1, 3).mean(0)))
    if fx.get('rev'):   # fita que corre ao contrario da zona (mapeamento: o 1o pixel na direita/embaixo)
        cols = cols[::-1]
    k = min(0.95, max(0.0, float(fx.get('smooth', 0.5))))
    if prev and len(prev) == n:
        cols = [tuple(p + (c - p) * (1 - k) for p, c in zip(pc, cc)) for pc, cc in zip(prev, cols)]
    return cols


def dmx_frame(img, fixtures, bright_of, prev, master=1.0, host=''):
    """{(ip, universo): bytearray(512)} de todos os aparelhos (ip = fx['host'] ou o geral `host`).
    bright_of(fx) -> 0..1 (som/imagem); prev = {indice: cores} da chamada anterior (pro smooth)."""
    unis = {}
    for i, fx in enumerate(fixtures or []):
        cols = prev[i] = fixture_colors(img, fx, prev.get(i))
        ch = str(fx.get('ch', 'rgb')) or 'rgb'
        uni, pos = int(fx.get('uni', 0)), max(1, int(fx.get('addr', 1))) - 1
        br = max(0.0, min(1.0, bright_of(fx))) * master
        for c in cols:
            data = _channels(c, ch, br)
            if pos + len(data) > 512:   # nao cabe o pixel inteiro: comeca no universo seguinte
                uni, pos = uni + 1, 0
            unis.setdefault((fx.get('host') or host, uni), bytearray(512))[pos:pos + len(data)] = data
            pos += len(data)
    return unis


class Sender:
    """Socket UDP com broadcast; send(unis) manda um ArtDmx por universo (seq por universo)."""
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.seq = {}

    def send(self, unis):
        for (host, u), data in unis.items():
            s = self.seq[host, u] = self.seq.get((host, u), 0) % 255 + 1   # 0 = "sem sequencia" no Art-Net
            try:
                self.sock.sendto(artnet_packet(u, data, s), (host, ARTNET_PORT))
            except OSError:   # rede caiu / host invalido: luz congela, o video segue
                return False
        return True


# ---------------- DETECTOR (sem rider): quem esta' na rede ----------------

def local_ip():
    """IP desta maquina na rede local (a rota padrao; nada e' enviado)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def parse_poll_reply(d, sender_ip=''):
    """ArtPollReply -> {kind, ip, name, long, unis} | None (offsets do Art-Net 4)."""
    if len(d) < 207 or d[:8] != b'Art-Net\x00' or int.from_bytes(d[8:10], 'little') != 0x2100:
        return None
    ip = '.'.join(str(b) for b in d[10:14]) or sender_ip
    net, sub = d[18] & 0x7F, d[19] & 0x0F
    nports = min(4, int.from_bytes(d[172:174], 'big'))
    unis = [(net << 8) | (sub << 4) | (d[190 + i] & 0x0F) for i in range(nports) if d[174 + i] & 0x80]   # porta de SAIDA DMX
    txt = lambda b: b.split(b'\x00')[0].decode('latin-1').strip()
    return {'kind': 'artnet', 'ip': ip, 'name': txt(d[26:44]), 'long': txt(d[44:108]), 'unis': unis}


def artnet_poll(timeout=1.5):
    """ArtPoll em broadcast; junta as respostas (nos DMX, WLED com Art-Net, consoles). Precisa
    escutar a porta 6454 (o no' responde nela); ocupada por outro programa = so' o que chegar."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(('', ARTNET_PORT))
    except OSError:
        s.bind(('', 0))
    found = {}
    try:
        me = local_ip()
        for host in {'255.255.255.255', me.rsplit('.', 1)[0] + '.255', '2.255.255.255'}:
            try:
                s.sendto(_POLL, (host, ARTNET_PORT))
            except OSError:
                pass
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s.settimeout(max(0.01, end - time.monotonic()))
            try:
                d, addr = s.recvfrom(2048)
            except (socket.timeout, OSError):
                break
            r = parse_poll_reply(d, addr[0])
            if r:
                old = found.get(r['ip'])
                if old:   # no' com varias "bind" responde 1x por grupo de 4 portas
                    old['unis'] = sorted(set(old['unis']) | set(r['unis']))
                else:
                    found[r['ip']] = r
    finally:
        s.close()
    return list(found.values())


def wled_probe(ip, timeout=0.5):
    """WLED em `ip`? (API JSON) -> {kind, ip, name, leds, live, uni, addr, fixture} | None. O
    `fixture` sai pronto pro LIGHTS: fita com os LEDs dela no universo/endereco do DMX do WLED."""
    try:
        with urllib.request.urlopen(f'http://{ip}/json/info', timeout=timeout) as r:
            info = json.loads(r.read(65536))
    except Exception:
        return None
    if not isinstance(info, dict) or 'leds' not in info or 'ver' not in info:
        return None
    try:
        with urllib.request.urlopen(f'http://{ip}/json/cfg', timeout=timeout) as r:
            live = (json.loads(r.read(262144)).get('if') or {}).get('live') or {}
    except Exception:
        live = {}
    dmx = live.get('dmx') or {}
    n = int((info.get('leds') or {}).get('count') or 0)
    uni, addr, mode = int(dmx.get('uni', 1)), int(dmx.get('addr', 1)), dmx.get('mode', 4)
    out = {'kind': 'wled', 'ip': ip, 'name': info.get('name') or 'WLED', 'leds': n, 'live': bool(live.get('en')),
           'uni': uni, 'addr': addr, 'mode': mode,
           'fixture': {'name': info.get('name') or 'WLED', 'ch': 'rgbw' if mode == 6 else 'rgb', 'count': n,
                       'uni': uni, 'addr': addr, 'host': ip}}
    if not out['live'] or mode not in (4, 6):   # 4 = Multi RGB, 6 = Multi RGBW (WLED > Sync > DMX)
        out['aviso'] = 'no WLED: Sync > Realtime "Art-Net" ligado e DMX mode "Multi RGB"'
    return out


def wled_scan(timeout=0.4):
    """Procura WLED na sub-rede /24 desta maquina (254 IPs em paralelo, ~2 s)."""
    pre = local_ip().rsplit('.', 1)[0]
    with concurrent.futures.ThreadPoolExecutor(64) as ex:
        return [r for r in ex.map(lambda i: wled_probe(f'{pre}.{i}', timeout), range(1, 255)) if r]


def discover():
    """{ip, artnet: [...], wled: [...]} — o que respondeu na rede agora."""
    with concurrent.futures.ThreadPoolExecutor(2) as ex:
        a, w = ex.submit(artnet_poll), ex.submit(wled_scan)
        return {'ip': local_ip(), 'artnet': a.result(), 'wled': w.result()}


# ---------------- MAPEAMENTO pela camera: acende canal a canal e ve onde a luz cai ----------------

NEAR = 0.08   # duas manchas mais perto que isso (0..1 da foto) = o mesmo aparelho


def spot(base, lit, min_gain=25):
    """Onde uma luz ACENDEU entre duas fotos (h, w, 3 uint8): (x, y, forca, (r, g, b)) — centro
    0..1 pesado pelo brilho, forca = pico 0..255 da diferenca, cor = media da diferenca na mancha.
    None se nada passou de min_gain (ruido da camera fica abaixo)."""
    d = np.clip(lit.astype(np.int16) - base.astype(np.int16), 0, 255)
    h2, w2 = d.shape[0] // 2 * 2, d.shape[1] // 2 * 2   # media 2x2: pixel solto (ruido) nao vira mancha
    d = d[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2, 3).mean((1, 3))
    l = d.max(2)                       # canal mais forte: vermelho puro tem luma baixa
    pk = int(l.max())
    if pk < min_gain:
        return None
    m = l >= pk * 0.5
    ys, xs = np.nonzero(m)
    w = l[m].astype(np.float64)
    return ((xs * w).sum() / w.sum() / l.shape[1], (ys * w).sum() / w.sum() / l.shape[0], pk,
            tuple(float(c) for c in d[m].mean(0)))


def _near(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) < NEAR


def _letter(col):
    """cor da mancha -> canal: pouca saturacao = branco, senao o primario mais forte."""
    mx, mn = max(col), min(col)
    if mx <= 0 or (mx - mn) / mx < 0.35:
        return 'w'
    return 'rgb'[col.index(mx)]


def group_fixtures(uni, lit, dim):
    """Canais acesos -> aparelhos. lit = {endereco: spot | None}; dim = {endereco do dimmer}.
    Canais vizinhos acendendo no mesmo lugar = um aparelho; 4+ aparelhos iguais em fila de
    enderecos e lugares diferentes = FITA (count, zone, rev)."""
    out, a, n = [], 1, max(list(lit) + [0])
    while a <= n:
        if a not in dim and not lit.get(a):
            a += 1
            continue
        start, ch, sps = a, '', []
        if a in dim:
            ch, a = 'd', a + 1
        while a <= n and lit.get(a) and (not sps or _near(sps[0], lit[a])):
            ch += _letter(lit[a][3])
            sps.append(lit[a])
            a += 1
        if not sps:
            continue
        out.append({'uni': uni, 'addr': start, 'ch': ch, 'pos': [round(sum(s[0] for s in sps) / len(sps), 3),
                                                                  round(sum(s[1] for s in sps) / len(sps), 3)]})
    fx, i = [], 0
    while i < len(out):
        j = i + 1
        while j < len(out) and out[j]['ch'] == out[i]['ch'] and out[j]['addr'] == out[j - 1]['addr'] + len(out[i]['ch']):
            j += 1
        if j - i >= 4:   # fita: zona = caixa das manchas (com folga), eixo maior; rev se corre ao contrario
            ps = [o['pos'] for o in out[i:j]]
            x0, x1 = min(p[0] for p in ps), max(p[0] for p in ps)
            y0, y1 = min(p[1] for p in ps), max(p[1] for p in ps)
            horiz = x1 - x0 >= y1 - y0
            k = (j - i)
            px = ((x1 - x0) if horiz else (y1 - y0)) / max(1, k - 1) / 2   # meia distancia entre pixels
            z = [x0 - px, y0 - 0.02, x1 - x0 + 2 * px, y1 - y0 + 0.04] if horiz else \
                [x0 - 0.02, y0 - px, x1 - x0 + 0.04, y1 - y0 + 2 * px]
            st = dict(out[i], count=k, zone=[round(max(0.0, v), 3) for v in z], pos=[round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)])
            if (ps[0][0] > ps[-1][0]) if horiz else (ps[0][1] > ps[-1][1]):
                st['rev'] = 1
            fx.append(st)
            i = j
        else:
            fx.append(out[i])
            i += 1
    return fx


def scan(send, grab, unis=(0,), n=128, progress=None, stop=lambda: False, min_gain=25):
    """Mapeia o rig SEM rider: send(uni, bytes512) manda o DMX, grab() devolve uma foto NOVA da
    camera (h, w, 3 uint8, ja' depois da luz assentar). Fase 1: cada canal sozinho a 255 (aparelho
    rgb/rgbw/fita). Fase 2: par de canais apagados (a, a+1) que acende JUNTO = dimmer em `a` e cor
    em a+1 -> varre as cores seguintes com o dimmer aceso. Devolve {fixtures, base} | None (parou).
    ponytail: 1 canal por foto (~0.35 s cada: 128 canais ~1 min); dimmer DEPOIS das cores (rgbd)
    sai trocado; cabeca movel (pan/tilt) nao e' entendida. Upgrade: varrer varios canais por foto
    (codigo binario) e testar dimmer nas duas pontas."""
    def shot(uni, chans):
        d = bytearray(512)
        for a, v in chans.items():
            d[a - 1] = v
        send(uni, bytes(d))
        return grab()
    fixtures, first, total, done = [], None, max(1, len(unis) * n), 0
    for uni in unis:
        base = shot(uni, {})
        first = base if first is None else first
        # RUIDO da camera: duas fotos sem mudar nada; so' vale mancha bem acima do que ela treme sozinha
        nz = max((spot(base, shot(uni, {}), 1) or (0, 0, 0))[2] for _ in range(3))
        gain = max(min_gain, nz * 2 + 10)

        def hit(chans, b):
            """spot que se REPETE: acende, apaga, acende de novo — tem que cair no mesmo lugar."""
            sp = spot(b, shot(uni, chans), gain)
            if not sp:
                return None
            b2 = shot(uni, {})
            sp2 = spot(b2, shot(uni, chans), gain)
            return sp if sp2 and _near(sp, sp2) else None
        lit = {}
        for a in range(1, n + 1):
            if stop():
                return None
            if a % 32 == 0:   # luz ambiente / auto-exposicao da camera andam: base nova
                base = shot(uni, {})
            lit[a] = hit({a: 255}, base)
            done += 1
            if progress:
                progress(done / total * 0.8, f'universo {uni} · canal {a}/{n}')
        dim, a = set(), 1
        while a < n:
            if stop():
                return None
            if not lit.get(a) and not lit.get(a + 1):
                sp = hit({a: 255, a + 1: 255}, base)
                if sp:
                    dim.add(a)
                    lit[a + 1] = sp
                    j = a + 2
                    while j <= n and j - a <= 8:
                        s2 = spot(base, shot(uni, {a: 255, j: 255}), gain)
                        if not s2 or not _near(s2, sp):
                            break
                        lit[j] = s2
                        j += 1
                    a = j
                    continue
            a += 1
            if progress and a % 8 == 0:
                progress(0.8 + 0.2 * (uni - unis[0] + a / n) / max(1, len(unis)), f'universo {uni} · dimmers {a}/{n}')
        fixtures += group_fixtures(uni, lit, dim)
        send(uni, bytes(512))
    for i, f in enumerate(fixtures):
        f['name'] = f"{'fita' if f.get('count') else 'luz'} {i + 1}"
        f.setdefault('zone', [round(max(0.0, f['pos'][0] - 0.1), 3), round(max(0.0, f['pos'][1] - 0.1), 3), 0.2, 0.2])
    return {'fixtures': fixtures, 'base': first}


if __name__ == '__main__':   # self-check: python src/luzes.py
    p = artnet_packet(0x0102, b'\x0a\x0b\x0c', seq=7)
    assert p[:8] == b'Art-Net\x00' and p[8:10] == b'\x00\x50' and p[10:12] == b'\x00\x0e', p[:12]
    assert p[12] == 7 and p[14:16] == b'\x02\x01' and p[16:18] == b'\x00\x04' and p[18:] == b'\x0a\x0b\x0c\x00', p
    img = np.zeros((10, 20, 3), np.uint8)
    img[:, :10] = (255, 0, 0)       # esquerda vermelha, direita azul
    img[:, 10:] = (0, 0, 200)
    one = lambda fx: 1.0
    u = dmx_frame(img, [{'ch': 'rgb', 'zone': [0, 0, 0.5, 1]}, {'ch': 'drgb', 'addr': 4, 'zone': [0.5, 0, 0.5, 1]}], one, {})
    u = {k[1]: v for k, v in u.items()}
    assert bytes(u[0][:7]) == bytes([255, 0, 0, 200, 0, 0, 255]), list(u[0][:7])   # dimmer leva o brilho, cor cheia
    u = dmx_frame(img, [{'ch': 'rgb', 'count': 2}], lambda fx: 0.5, {})
    u = {k[1]: v for k, v in u.items()}
    assert bytes(u[0][:6]) == bytes([128, 0, 0, 0, 0, 100]), list(u[0][:6])        # fita: 2 fatias no eixo maior
    u = dmx_frame(img, [{'ch': 'rgb', 'count': 171, 'uni': 3}], one, {})
    u = {k[1]: v for k, v in u.items()}
    assert 3 in u and 4 in u and bytes(u[4][:3]) == bytes([0, 0, 200]), sorted(u)   # 171 px: o ultimo vai pro universo 4
    assert bytes(_channels((200, 200, 100), 'rgbw', 1.0)) == bytes([100, 100, 0, 100])
    assert bytes(dmx_frame(img, [{'ch': 'rgb'}], one, {}, master=0.0)[('', 0)][:3]) == b'\x00\x00\x00', 'blackout apaga'
    prev = {}
    dmx_frame(img, [{'ch': 'rgb', 'color': [0, 0, 0], 'smooth': 0.5}], one, prev)
    u = dmx_frame(img, [{'ch': 'rgb', 'color': [200, 0, 0], 'smooth': 0.5}], one, prev)
    assert u[('', 0)][0] == 100, 'smooth: metade do caminho por frame'
    assert list(dmx_frame(img, [{'ch': 'rgb', 'host': '10.0.0.9'}], one, {}, host='h')) == [('10.0.0.9', 0)], 'ip por aparelho'
    assert [c[0] for c in fixture_colors(img, {'count': 2, 'rev': 1, 'smooth': 0})] == [0.0, 255.0], 'fita rev'
    r = parse_poll_reply(b'Art-Net\x00' + b'\x00\x21' + bytes([10, 0, 0, 7]) + bytes(4) + bytes([0, 1]) + bytes(6)
                         + b'NoDMX'.ljust(18, b'\x00') + b'No DMX longo'.ljust(64, b'\x00') + bytes(64)
                         + (2).to_bytes(2, 'big') + bytes([0x80, 0x80, 0, 0]) + bytes(12) + bytes([2, 3, 0, 0]) + bytes(13))
    assert r == {'kind': 'artnet', 'ip': '10.0.0.7', 'name': 'NoDMX', 'long': 'No DMX longo', 'unis': [18, 19]}, r

    # palco SIMULADO: camera 40x30, aparelhos = manchas; a varredura tem que achar cada um
    rig = [('rgb', 1, (0.2, 0.5)), ('drgb', 10, (0.7, 0.3))] + [('rgb', 20 + 3 * i, (0.1 + 0.2 * i, 0.85)) for i in range(5)]
    dmx = {0: bytes(512)}
    yy, xx = np.mgrid[0:30, 0:40]

    def grab():
        im = np.full((30, 40, 3), 12.0)
        for ch, a, (x, y) in rig:
            v = {c: dmx[0][a - 1 + k] / 255.0 for k, c in enumerate(ch)}
            col = np.array([v.get('r', 0), v.get('g', 0), v.get('b', 0)]) * v.get('d', 1.0) * 200
            g = np.exp(-((xx / 40 - x) ** 2 + (yy / 30 - y) ** 2) / 0.002)
            im += g[..., None] * col
        return np.clip(im + np.random.default_rng(len(dmx)).normal(0, 3, im.shape), 0, 255).astype(np.uint8)

    def send(u, d):
        dmx[0] = d
    res = scan(send, grab, unis=(0,), n=40)
    got = [(f['addr'], f['ch'], f.get('count')) for f in res['fixtures']]
    assert got == [(1, 'rgb', None), (10, 'drgb', None), (20, 'rgb', 5)], got
    assert abs(res['fixtures'][1]['pos'][0] - 0.7) < 0.05 and abs(res['fixtures'][1]['pos'][1] - 0.3) < 0.05, res['fixtures'][1]
    rig.clear()
    rng = np.random.default_rng(5)

    def grab_noisy():   # palco VAZIO: ruido forte + auto-exposicao pulando de foto em foto
        im = np.full((30, 40, 3), 40.0) * rng.uniform(0.85, 1.15) + rng.normal(0, 9, (30, 40, 3))
        return np.clip(im, 0, 255).astype(np.uint8)
    res = scan(send, grab_noisy, unis=(0,), n=24)
    assert res['fixtures'] == [], [(f['addr'], f['ch']) for f in res['fixtures']]
    print('luzes self-check ok')
