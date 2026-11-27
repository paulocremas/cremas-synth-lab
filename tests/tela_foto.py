"""FOTO DA TELA INTEIRA do /v6 (barra, canvas, painel, aviso) com a cena fixa dos testes — o antes/depois da pele (plano fase 4).
    .venv/bin/python tests/tela_foto.py design/fase4/depois.png [painel] [perto]   # painel = com o painel de um modulo aberto
    perto = a 100% em volta do Contornar e do Matiz (o acabamento dos modulos de perto)"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dash_gestos as T


def main(out, painel=False, perto=False):
    c, br, tmp, _ = T.boot()
    try:
        c.send('Emulation.setDeviceMetricsOverride', width=1366, height=768, deviceScaleFactor=1, mobile=False)
        T.v6_open(c)
        c.js("const n = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)); applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
        time.sleep(0.6)
        c.js("const m = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), yb = Math.max(...G6.scene.nodes.map(n => n.y + n.h)); newEvm([m.x - 260, yb + 40]); return 1")
        time.sleep(0.6)
        c.js("const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); applyPreset(n.key, 0, knobsOf(n.an.file)[1], 'drop'); cvSig = ''; renderBoxes(); return 1")   # um envelope pela SECAO (o evento sem modulo)
        time.sleep(0.6)
        if painel:
            c.js("const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); openInsp(n.key, 0); return 1")
        c.js("G6.fit(true); toast('exemplo de aviso no visor'); return 1")
        if perto:
            time.sleep(0.6)
            c.js("const a = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)), b = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), r = document.getElementById('gcv').getBoundingClientRect();"
                 "G6.zoom(1); const cx = (a.x + b.x + b.w) / 2, cy = (a.y + b.y + b.h) / 2; G6.cam.x = cx - r.width / 2; G6.cam.y = cy - r.height / 2; G6.dirty(); return 1")
        time.sleep(1.0)
        png = base64.b64decode(c.send('Page.captureScreenshot', format='png')['data'])
        open(out, 'wb').write(png)
        print('foto:', out)
    finally:
        T.kill_browser(br)


if __name__ == '__main__':
    main(sys.argv[1], 'painel' in sys.argv[2:], 'perto' in sys.argv[2:])
