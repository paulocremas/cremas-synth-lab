"""FOTO do canvas do /v6 (rodada 6: "mostre antes de fechar"): sobe o dash isolado (= tests/dash_gestos.py: porta 8799, tuning
temporario), abre o /v6 com a cena fixa, monta uma cena de mostruario e salva PNGs do canvas a 100%.

    .venv/bin/python tests/v6_foto.py design/rodada6/antes   # grava <prefixo>-modulos.png (+ as outras cenas)
    .venv/bin/python tests/v6_foto.py <prefixo> modulos roda   # so' essas
"""
import base64
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dash_gestos as D   # noqa: E402

# 4 modulos do pedido (Contornar, Polar, Misturar, mixer) + o alterador: lado a lado, sem fios cruzando
MODULOS = """
  const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
  const keep = new Set([chKey(src)]); lastOverlays = lastOverlays.filter(o => keep.has(chKey(o)));
  for (const k of Object.keys(lastBindings)) if (k !== chKey(src)) delete lastBindings[k];
  const mk = (f, xy) => newNode(ref, xy, newModule('presets/atomos/' + f + '.frag'));
  const a = mk('Contornar', [0, 0]), b = mk('Polar', [0, 0]), m = mk('Misturar', [0, 0]);
  const x = newMix('mix', '@' + a.id, [0, 0], 2); plug('@' + b.id, { key: chKey(x), port: 'L', idx: 901 });
  applyPreset(chKey(b), 0, 'giro', 'anda');
  const mid = stackOf(chKey(b))[0].mod.giro.id; linkMv(chKey(m), 0, 'opacity', mid); linkLayerMv(chKey(x), 0, mid);   // opacidade do Misturar e da camada 1 do mixer no alterador
  const L = [[a, b], [m, x]]; let y = 40;
  for (const row of L){ let xx = 40, hh = 0; for (const o of row){ o.xy = [xx, y]; xx += boxW(chKey(o)) + 60; hh = Math.max(hh, boxH(chKey(o))); } y += hh + 60; }
  src.xy = [-420, 60]; for (const o of lastOverlays) if (![a, b, m, x, src].includes(o)) o.xy = [3000, 3000];
  const c = ctlStore()[0]; if (c) c.xy = [40, y];
  sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes();
  return [chKey(a), chKey(b), chKey(m), chKey(x)].concat(c ? ['ctl:' + c.id] : [])"""

# item 1: o KNOB-JACK — Contornar (knobs livres) + Matiz (1 knob LIGADO no alterador), lado a lado
KNOBS = """
  const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
  const keep = new Set([chKey(src)]); lastOverlays = lastOverlays.filter(o => keep.has(chKey(o)));
  for (const k of Object.keys(lastBindings)) if (k !== chKey(src)) delete lastBindings[k];
  const mk = (f, xy) => newNode(ref, xy, newModule('presets/atomos/' + f + '.frag'));
  const a = mk('Contornar', [40, 40]), b = mk('Matiz', [0, 0]); b.xy = [40, 40 + boxH(chKey(a)) + 60];
  applyPreset(chKey(b), 0, knobsOf(stackOf(chKey(b))[0].file)[0], 'pulsa');
  src.xy = [-420, 60];
  sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes();
  const c = ctlStore()[0]; if (c){ c.xy = [40 + boxW(chKey(b)) + 80, 40 + boxH(chKey(a)) + 60]; sendOverlays(true); cvSig = ''; renderBoxes(); }
  return [chKey(a), chKey(b)].concat(c ? ['ctl:' + c.id] : [])"""

# item 8: os SELETORES — Misturar (5 opcoes), Fluido (4), Contornar (2) e um atomo com CHAVE, no estilo SEL_FORCE (null = a regra)
SELETORES = """
  SEL_FORCE = %s;
  const src = lastOverlays.find(o => !isTapKey(o.file) && !o.kind), ref = '@' + ensureRowId(src);
  const keep = new Set([chKey(src)]); lastOverlays = lastOverlays.filter(o => keep.has(chKey(o)));
  for (const k of Object.keys(lastBindings)) if (k !== chKey(src)) delete lastBindings[k];
  const sw = lastShaderList.find(f => /presets\\/atomos\\//.test(f) && !isMaskFile(f) && (metaOf(f).knobs || knobsOf(f)).some(n => isSwitch(f, n)))
          || lastShaderList.find(f => /presets\\/atomos\\//.test(f) && knobsOf(f).some(n => isSwitch(f, n)));
  const mk = f => newNode(ref, [0, 0], newModule(f.includes('/') ? f : 'presets/atomos/' + f + '.frag'));
  const L = [mk('Misturar'), mk('Fluido'), mk('Contornar')].concat(sw ? [mk(sw)] : []);
  %s
  let y = 40; for (const o of L){ o.xy = [40, y]; y += boxH(chKey(o)) + 40; }
  src.xy = [-420, 60];
  sendOverlays(true); sendBindings(true); cvSig = ''; renderBoxes(); G6.dirty();
  const c = ctlStore()[0]; if (c){ c.xy = [80 + Math.max(...L.map(o => boxW(chKey(o)))), 40]; sendOverlays(true); cvSig = ''; renderBoxes(); }
  return L.map(chKey).concat(c ? ['ctl:' + c.id] : [])"""
LIGA = "applyPreset(chKey(L[1]), 0, 'direcao', 'anda'); applyPreset(chKey(L[0]), 0, 'modo', 'anda');"

CENAS = {'modulos': MODULOS, 'knobs': KNOBS, 'roda': None,
         'S1': SELETORES % ("'S1'", ''), 'S2': SELETORES % ("'S2'", ''), 'S3': SELETORES % ("'S3'", ''),
         'regra': SELETORES % ('null', ''), 'regra-ligado': SELETORES % ('null', LIGA)}


def roda(c, path):
    """item 6: a RODA de modulos (2 cliques no vazio = openWheel) — a tela toda; depois uma fatia aberta (a lista)"""
    c.send('Emulation.setDeviceMetricsOverride', width=1366, height=900, deviceScaleFactor=1, mobile=False)
    time.sleep(0.5)
    c.js("closeWheel(); const r = document.getElementById('gcv').getBoundingClientRect(); openWheel({ clientX: r.left + r.width * 0.4, clientY: r.top + r.height * 0.5 }); return 1")
    time.sleep(0.6)
    for suf, js in (('', None), ('-aberta', "const b = [...document.querySelectorAll('.wheel .wh-s')][1]; b.click(); return 1")):
        if js:
            c.js(js)
            time.sleep(0.5)
        img = c.send('Page.captureScreenshot', format='png')
        with open(f'{path}{suf}.png', 'wb') as f:
            f.write(base64.b64decode(img['data']))
        print('gravado', f'{path}{suf}.png')
    print('fatias:', c.js("return [...document.querySelectorAll('.wheel .wh-s')].map(b => b.textContent)"))
    c.js("closeWheel(); return 1")
    c.send('Emulation.clearDeviceMetricsOverride')
VARIANTES = {'knobs': [('A', 1.0, ''), ('B', 1.0, '-B'), ('A', 0.5, '-longe'), ('B', 0.5, '-B-longe')]}


def shot(c, keys, path, pad=24, z=1.0):
    """enquadra as pecas `keys` a z (100%) e grava o PNG so' delas"""
    r = c.js(f"""G6.dirty(); await new Promise(r => setTimeout(r, 300)); const S = G6.scene, ks = {json.dumps(keys)};
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const k of ks){{ const n = k.startsWith('ctl:') ? S.ctls.find(c => 'ctl:' + c.id === k) : S.by[k]; if (!n) continue;
        x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x + n.w); y1 = Math.max(y1, n.y + n.h); }}
      return [x0 - {pad}, y0 - {pad}, x1 + {pad}, y1 + {pad}]""")
    w, h = int((r[2] - r[0]) * z) + 2, int((r[3] - r[1]) * z) + 2
    c.send('Emulation.setDeviceMetricsOverride', width=max(1366, w + 420), height=max(768, h + 260), deviceScaleFactor=1, mobile=False)
    time.sleep(0.6)
    c.js(f"G6.zoom({z}); G6.cam.x = {r[0]}; G6.cam.y = {r[1]}; G6.dirty(); return 1")
    time.sleep(1.2)   # sprites refeitos na escala nova (3 por quadro) + previas
    o = c.js("const r = document.getElementById('gcv').getBoundingClientRect(); return [r.left, r.top]")
    img = c.send('Page.captureScreenshot', format='png', clip={'x': o[0], 'y': o[1], 'width': w, 'height': h, 'scale': 1})
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'wb') as f:
        f.write(base64.b64decode(img['data']))
    c.send('Emulation.clearDeviceMetricsOverride')
    print('gravado', path, f'{w}x{h}')


def main(prefix, names):
    c, br, tmp, _ = D.boot()
    try:
        for nm in names or list(CENAS):
            D.v6_open(c)
            c.js("warpOK = false; return 1")
            if CENAS[nm] is None:
                roda(c, f'{prefix}-{nm}')
                continue
            keys = c.js(CENAS[nm])
            time.sleep(0.8)
            for (ks, z, suf) in VARIANTES.get(nm, [(None, 1.0, '')]):
                if ks:
                    c.js(f"G6.knobStyle('{ks}'); return 1")
                shot(c, keys, f'{prefix}-{nm}{suf}.png', z=z)
            c.js("G6.knobStyle && G6.knobStyle('A'); return 1")
            err = D.errors(c)
            if err:
                print('ERRO de JS:', err[0])
    finally:
        D.kill_browser(br)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
