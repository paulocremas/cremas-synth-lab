"""REVISAO DE ESTETICA: fotografa TODAS as superficies do /v6 (1366x768, o notebook do usuario) numa pasta — o antes/depois de uma
rodada de pele. Sobe o dash isolado (= tests/dash_gestos.py: porta 8799, tuning temporario, cena fixa).

    .venv/bin/python tests/estetica.py design/revisao/antes            # todas
    .venv/bin/python tests/estetica.py design/revisao/depois roda painel   # so' as que tem essas palavras no nome
"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dash_gestos as T   # noqa: E402

FAMS = ['cor', 'luz', 'forma', 'geometria', 'distorcao', 'textura', 'tempo', 'gerador', 'mascara']

# um modulo de cada FAMILIA (o 1o atomo de cada uma), em grade, cada um lendo a fonte
VITRINE = """
  const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
  const keep = new Set([chKey(src)]); lastOverlays = lastOverlays.filter(o => keep.has(chKey(o)));
  for (const k of Object.keys(lastBindings)) if (k !== chKey(src) && k !== EV_KEY) delete lastBindings[k];
  const atoms = lastShaderList.filter(f => isAtomFile(f) && metaOf(f).atom), made = [];
  for (const fam of FAMS){ const f = atoms.find(a => catOf(a) === fam); if (!f) continue;
    const o = newNode(ref, [0, 0], newModule(f)); made.push(o); }
  let x = 40, y = 40, rowH = 0; const maxW = 1500;
  for (const o of made){ const w = boxW(chKey(o)), hh = boxH(chKey(o)); if (x + w > maxW){ x = 40; y += rowH + 50; rowH = 0; }
    o.xy = [x, y]; x += w + 50; rowH = Math.max(rowH, hh); }
  src.xy = [-460, 40];
  sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes(); return made.length"""


def shot(c, out, name, only):
    if only and not any(w in name for w in only):
        return
    png = base64.b64decode(c.send('Page.captureScreenshot', format='png')['data'])
    open(os.path.join(out, name + '.png'), 'wb').write(png)
    print('  foto:', name)


def esc(c):
    c.js("closeWheel(); document.querySelectorAll('.nmenu').forEach(x => x.remove()); if (typeof cablePop === 'function') cablePop(false);"
         " if (drawer) openDrawer(drawer); document.body.classList.remove('cn-open'); const t = document.getElementById('tpop'); if (t) t.remove(); return 1")
    time.sleep(0.3)


def main(out, only):
    os.makedirs(out, exist_ok=True)
    c, br, tmp, _ = T.boot()
    try:
        c.send('Emulation.setDeviceMetricsOverride', width=1366, height=768, deviceScaleFactor=1, mobile=False)
        T.v6_open(c)
        c.js("const n = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)); applyPreset(n.key, 0, knobsOf(n.an.file)[0], 'pulsa'); cvSig = ''; renderBoxes(); return 1")
        time.sleep(0.5)
        c.js("const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); applyPreset(n.key, 0, knobsOf(n.an.file)[1], 'drop'); cvSig = ''; renderBoxes(); return 1")
        time.sleep(0.5)
        c.js("const m = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), yb = Math.max(...G6.scene.nodes.map(n => n.y + n.h)); newEvm([m.x - 260, yb + 40]); return 1")
        time.sleep(0.5)
        c.js("G6.fit(true); return 1")
        time.sleep(1.0)
        shot(c, out, '01-tela', only)
        c.js("const a = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)), b = G6.scene.nodes.find(n => n.an && /Matiz/.test(n.an.file)), r = document.getElementById('gcv').getBoundingClientRect();"
             "G6.zoom(1); const cx = (a.x + b.x + b.w) / 2, cy = (a.y + b.y + b.h) / 2 + 60; G6.cam.x = cx - r.width / 2; G6.cam.y = cy - r.height / 2; G6.dirty(); return 1")
        time.sleep(1.0)
        shot(c, out, '02-perto', only)
        c.js("G6.fit(true); return 1")
        time.sleep(0.6)
        # a RODA e a LISTA de uma familia
        r = c.js("const r = document.getElementById('gcv').getBoundingClientRect(); return [r.left + r.width * 0.42, r.top + r.height * 0.55]")
        c.js(f"openWheel({{clientX: {r[0]}, clientY: {r[1]}}}); return 1")
        time.sleep(0.5)
        shot(c, out, '03-roda', only)
        c.js("const b = [...document.querySelectorAll('.wheel .wh-s')][1]; if (b) b.click(); return 1")
        time.sleep(0.5)
        shot(c, out, '04-roda-lista', only)
        esc(c)
        # o PAINEL de um modulo e o do alterador
        c.js("const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); openInsp(n.key, 0); return 1")
        time.sleep(0.6)
        shot(c, out, '05-painel', only)
        c.js("openInsp(CTL_KEY, 0); return 1")
        time.sleep(0.6)
        shot(c, out, '06-painel-alterador', only)
        c.js("inspClosed = selSig(); placeInsp(); return 1")
        time.sleep(0.3)
        # CENAS, PROGRAMA, CABOS, TEMPO
        c.click(*T.center(c, '#cn-btn'))
        time.sleep(0.5)
        shot(c, out, '07-cenas', only)
        esc(c)
        c.js("setPvw({ st: 'win' }); return 1")
        time.sleep(0.8)
        shot(c, out, '08-programa', only)
        c.js("setPvw({ st: 'off' }); return 1")
        c.click(*T.center(c, '#nav-more'))   # (repaginada 2026-11-27: arrumar, cabos e programa no menu ⋯ da pilula)
        time.sleep(0.4)
        shot(c, out, '09-cabos', only)
        esc(c)
        c.click(*T.center(c, '#music'))
        time.sleep(0.5)
        shot(c, out, '10-tempo', only)
        esc(c)
        # as GAVETAS
        for tab in ['entrada', 'saida', 'telao', 'luzes', 'lib', 'controle']:
            c.js(f"openDrawer('eq', '{tab}'); return 1")
            time.sleep(0.6)
            shot(c, out, '11-equip-' + tab, only)
        c.js("openDrawer('eq'); return 1")
        time.sleep(0.3)
        c.js("openDrawer('sos'); return 1")
        time.sleep(0.6)
        shot(c, out, '12-socorro', only)
        c.js("openDrawer('sos'); return 1")
        time.sleep(0.3)
        # a MAO (macros e pads) ligada num knob + o envelope E2, de perto (repaginada 2026-11-27)
        c.js("const yb = Math.max(...G6.scene.nodes.map(n => n.y + n.h)); newMao([40, yb + 40]); return 1")
        time.sleep(0.6)
        c.js("const n = G6.scene.nodes.find(n => n.an && /Contornar/.test(n.an.file)); linkMv(n.key, 0, knobsOf(n.an.file)[2], 'mao-m1'); cvSig = ''; renderBoxes(); return 1")
        time.sleep(0.6)
        c.js("const m = G6.scene.maos[0]; G6.zoom(1); G6.cam.x = m.x - 40; G6.cam.y = m.y - 420; G6.dirty(); return 1")
        time.sleep(1.0)
        shot(c, out, '14-mao-envelope', only)
                # a VITRINE: um modulo de cada familia
        n = c.js("const FAMS = " + repr(FAMS).replace("'", '"') + ";" + VITRINE)
        time.sleep(1.0)
        c.js("const ns = G6.scene.nodes.filter(n => n.an); let x0 = Math.min(...ns.map(n => n.x)), y0 = Math.min(...ns.map(n => n.y)), x1 = Math.max(...ns.map(n => n.x + n.w)), y1 = Math.max(...ns.map(n => n.y + n.h));"
             "const r = document.getElementById('gcv').getBoundingClientRect(), z = Math.min(1, (r.width - 40) / (x1 - x0), (r.height - 40) / (y1 - y0)); G6.zoom(z); G6.cam.x = x0 - 20 / z; G6.cam.y = y0 - 20 / z; G6.dirty(); return z")
        time.sleep(1.4)
        shot(c, out, '13-familias', only)
        print(f'  ({n} familias na vitrine)')
    finally:
        T.kill_browser(br)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
