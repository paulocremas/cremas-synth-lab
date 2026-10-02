"""Checagem de atualizacao do app empacotado (roda no launcher, ANTES do prisma abrir).

  sem internet / GitHub fora / qualquer erro -> segue normal, calado (nunca trava a abertura:
                                                 a consulta roda numa thread com prazo de 2 s)
  mesma versao (ou mais nova: build de dev)  -> segue normal
  Release mais nova no GitHub                -> janelinha: "Atualizar" | "Agora nao"
      Atualizar: baixa o instalador da Release (Windows .exe | Linux .deb), roda e fecha o app
      (Windows: o instalador abre o PRISMA no fim; Linux: pkexec apt instala e reabre)

Versao = tag da Release (vMAIOR.MENOR.PATCH), gravada no arquivo VERSION ao lado do binario
pelo build (packaging/build.sh). PRISMA_NO_UPDATE=1 desliga. Sem VERSION (rodando do repo) nao
checa. Usa so' a stdlib + pygame (ja vai no binario) pra janela.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request

REPO = 'paulocremas/cremas-synth-lab'
API = os.environ.get('PRISMA_UPDATE_API') or f'https://api.github.com/repos/{REPO}/releases/latest'   # env: testes
IS_WIN = sys.platform == 'win32'


def parse_ver(s):
    """'v0.3.1' / '0.3' -> (0, 3, 1, 0) / (0, 3, 0, 0); pre-lancamento 'v0.3.1-beta.1' -> (0, 3, 1, -1)
    (vem ANTES da v0.3.1 final); outra coisa (ex. hash de dev) -> None."""
    m = re.fullmatch(r'v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.]+)?', (s or '').strip())
    return (*(int(g or 0) for g in m.groups()[:3]), -1 if m.group(4) else 0) if m else None


def is_newer(latest, current):
    a, b = parse_ver(latest), parse_ver(current)
    return bool(a and b and a > b)


def is_portable(here):
    """Zip portatil do Windows: `portable.txt` ao lado do binario (dados ficam na pasta)."""
    return os.path.exists(os.path.join(here, 'portable.txt'))


def install_kind(exe):
    """Como esta copia foi instalada -> qual asset da Release serve: 'exe' (Windows), 'deb'
    (.deb em /opt/prisma) | None (pasta solta ou zip portatil: so' abre a pagina da Release)."""
    if is_portable(os.path.dirname(os.path.realpath(exe))):
        return None
    if IS_WIN:
        return 'exe'
    return 'deb' if os.path.realpath(exe).startswith('/opt/prisma/') else None


def pick_asset(assets, kind):
    ext = {'exe': '.exe', 'deb': '.deb'}.get(kind)
    return next((a for a in assets or [] if ext and a.get('name', '').lower().endswith(ext)), None)


def fetch_latest(timeout=3.0):
    """Ultima Release: {'tag', 'notes', 'page', 'assets': [{name, url, size}]} | None (offline,
    sem Release, limite da API, JSON estranho...). Nunca levanta."""
    try:
        req = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'prisma-updater'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return {'tag': d['tag_name'], 'notes': d.get('body') or '', 'page': d.get('html_url') or '',
                'assets': [{'name': a['name'], 'url': a['browser_download_url'], 'size': a.get('size', 0)}
                           for a in d.get('assets') or []]}
    except Exception:                                       # noqa: BLE001 — offline = segue normal
        return None


def check(current, timeout=2.0):
    """Release mais nova que `current` | None. Roda numa thread com prazo: DNS travado sem rede
    nao segura a abertura do app alem de `timeout`."""
    box = []
    t = threading.Thread(target=lambda: box.append(fetch_latest(timeout)), daemon=True)
    t.start()
    t.join(timeout + 0.5)
    rel = box[0] if box else None
    return rel if rel and is_newer(rel['tag'], current) else None


def download(url, dst, progress=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'prisma-updater'})
    with urllib.request.urlopen(req, timeout=30) as r, open(dst, 'wb') as f:
        total, done = int(r.headers.get('Content-Length') or 0), 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            f.write(b)
            done += len(b)
            if progress:
                progress(done, total)


def run_installer(path, kind):
    """Dispara o instalador e devolve True se o app deve FECHAR (o instalador assume)."""
    if kind == 'exe':
        subprocess.Popen([path, '/SP-'], close_fds=True)      # assistente normal; no fim reabre o PRISMA
        return True
    if kind == 'deb':
        cmd = ['pkexec', 'apt-get', 'install', '-y', '--allow-downgrades', path]
        if subprocess.run(cmd).returncode == 0:
            subprocess.Popen(['prisma'], start_new_session=True)   # a versao nova, ja instalada
            return True
    return False


# ---------------------------------------------------------------- janela (pygame)

def ask(current, rel, kind):
    """Janelinha de atualizacao. True = o app deve fechar (instalador rodando)."""
    import webbrowser
    import pygame
    pygame.init()
    W, H = 520, 250
    scr = pygame.display.set_mode((W, H))
    pygame.display.set_caption('PRISMA! — atualização')
    f, fb, fs = pygame.font.SysFont(None, 24), pygame.font.SysFont(None, 30, bold=True), pygame.font.SysFont(None, 20)
    asset = pick_asset(rel['assets'], kind)
    notes = [l.strip('-* ').strip() for l in rel['notes'].splitlines() if l.strip()][:3]
    state, msg, prog = 'ask', '', 0.0
    b_yes, b_no = pygame.Rect(W - 300, H - 56, 150, 38), pygame.Rect(W - 140, H - 56, 120, 38)

    def draw():
        scr.fill((20, 22, 26))
        scr.blit(fb.render('Nova versão disponível', True, (232, 234, 237)), (20, 18))
        scr.blit(f.render(f"{rel['tag']}  (você tem {current})", True, (63, 208, 143)), (20, 56))
        for i, n in enumerate(notes):
            scr.blit(fs.render('• ' + n[:70], True, (170, 177, 185)), (20, 90 + i * 20))
        if state == 'ask':
            for r, t, c in ((b_yes, 'Atualizar' if asset else 'Abrir página', (63, 208, 143)), (b_no, 'Agora não', (60, 66, 74))):
                pygame.draw.rect(scr, c, r, border_radius=8)
                s = f.render(t, True, (14, 14, 18) if c[0] < 100 and c[1] > 150 else (232, 234, 237))
                scr.blit(s, s.get_rect(center=r.center))
        else:
            pygame.draw.rect(scr, (44, 50, 58), (20, H - 50, W - 40, 14), border_radius=7)
            pygame.draw.rect(scr, (63, 208, 143), (20, H - 50, int((W - 40) * prog), 14), border_radius=7)
            scr.blit(fs.render(msg, True, (170, 177, 185)), (20, H - 76))
        pygame.display.flip()

    try:
        while True:
            draw()
            ev = pygame.event.wait(100)
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE) or \
                    (ev.type == pygame.MOUSEBUTTONDOWN and b_no.collidepoint(ev.pos) and state == 'ask'):
                return False
            if not (ev.type == pygame.MOUSEBUTTONDOWN and b_yes.collidepoint(ev.pos) and state == 'ask'):
                continue
            if not asset:                                   # copia solta: so' a pagina
                webbrowser.open(rel['page'])
                return False
            state, msg = 'busy', 'baixando…'
            dst = os.path.join(tempfile.gettempdir(), asset['name'])

            def prog_cb(done, total):
                nonlocal prog, msg
                prog = done / total if total else 0.0
                msg = f'baixando… {done / 1e6:.1f} de {total / 1e6:.1f} MB'
                draw()
                pygame.event.pump()
            try:
                download(asset['url'], dst, prog_cb)
                msg, prog = 'instalando…', 1.0
                draw()
                if run_installer(dst, kind):
                    return True
                msg = 'não instalou — seguindo com a versão atual'
            except Exception as e:                          # noqa: BLE001
                msg = f'falhou ({e.__class__.__name__}) — seguindo com a versão atual'
            draw()
            pygame.time.wait(2500)
            return False
    finally:
        pygame.display.quit()


def maybe_update(here, exe):
    """Chamado pelo launcher. True = fechar o app agora (o instalador assumiu)."""
    if os.environ.get('PRISMA_NO_UPDATE'):
        return False
    try:
        with open(os.path.join(here, 'VERSION')) as fh:
            current = fh.read().strip()
    except OSError:
        return False
    if not parse_ver(current):
        return False                                       # build de dev (hash): nao compara
    rel = check(current)
    if not rel:
        return False
    try:
        return ask(current, rel, install_kind(exe))
    except Exception:                                       # noqa: BLE001 — sem janela: segue
        return False


if __name__ == '__main__':  # self-check (roda: python packaging/updater.py)
    assert parse_ver('v0.3.1') == (0, 3, 1, 0) and parse_ver('1.2') == (1, 2, 0, 0) and parse_ver('abc1234') is None
    assert is_newer('v0.1.0', 'v0.1.0-beta.1') and not is_newer('v0.1.0-beta.1', 'v0.1.0')   # beta < final
    assert is_newer('v0.10.0', 'v0.9.9') and not is_newer('v0.3.0', 'v0.3.0') and not is_newer('v0.2', 'v0.3')
    assert not is_newer('v1.0', 'abc1234')                  # dev nunca "atrasado"
    a = [{'name': 'prisma_0.3.0_amd64.deb'}, {'name': 'PRISMA-0.3.0-setup.exe'}]
    assert pick_asset(a, 'exe')['name'].endswith('.exe') and pick_asset(a, 'deb')['name'].endswith('.deb')
    assert pick_asset(a, None) is None
    assert install_kind('/opt/prisma/prisma') == ('exe' if IS_WIN else 'deb')
    print('updater self-check ok')
