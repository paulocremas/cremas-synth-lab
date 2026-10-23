"""Checagem de atualizacao do app empacotado (roda no launcher, ANTES do prisma abrir).

  sem internet / GitHub fora / qualquer erro -> segue normal, calado (nunca trava a abertura:
                                                 a consulta roda numa thread com prazo de 2 s)
  mesma versao (ou mais nova: build de dev)  -> segue normal
  Release mais nova no GitHub                -> janelinha: "Atualizar" | "Agora nao"
      Atualizar: baixa o instalador da Release (Windows .exe | Linux .deb), roda e fecha o app
      (Windows: o instalador abre o PRISMA no fim; Linux: pkexec apt instala e reabre)
      Portatil: baixa o zip, extrai e um .bat espera o app fechar, troca a pasta (menos `dados`)
      e reabre

Versao = tag da Release (vMAIOR.MENOR.PATCH), gravada no arquivo VERSION ao lado do binario
pelo build (packaging/build.sh). Quem esta numa beta tambem ve as betas novas; versao final so'
ve finais. PRISMA_NO_UPDATE=1 desliga. Sem VERSION (rodando do repo) nao checa. Usa so' a
stdlib + pygame (ja vai no binario) pra janela.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile

REPO = 'paulocremas/cremas-synth-lab'
API = os.environ.get('PRISMA_UPDATE_API') or f'https://api.github.com/repos/{REPO}/releases?per_page=20'   # env: testes
IS_WIN = sys.platform == 'win32'


def parse_ver(s):
    """'v0.3.1' / '0.3' -> (0, 3, 1, 0, 0) / (0, 3, 0, 0, 0); pre-lancamento 'v0.3.1-beta.2' ->
    (0, 3, 1, -1, 2) (vem ANTES da v0.3.1 final, depois da beta.1); outra coisa (hash de dev) -> None."""
    m = re.fullmatch(r'v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.]+)?', (s or '').strip())
    if not m:
        return None
    n = re.findall(r'\d+', m.group(4) or '')
    return (*(int(g or 0) for g in m.groups()[:3]), -1 if m.group(4) else 0, int(n[-1]) if n else 0)


def is_newer(latest, current):
    a, b = parse_ver(latest), parse_ver(current)
    return bool(a and b and a > b)


def is_portable(here):
    """Zip portatil do Windows: `portable.txt` ao lado do binario (dados ficam na pasta)."""
    return os.path.exists(os.path.join(here, 'portable.txt'))


def install_kind(exe):
    """Como esta copia foi instalada -> qual asset da Release serve: 'zip' (portatil do Windows),
    'exe' (Windows), 'deb' (.deb em /opt/prisma) | None (pasta solta: so' abre a pagina da Release)."""
    if is_portable(os.path.dirname(os.path.realpath(exe))):
        return 'zip' if IS_WIN else None
    if IS_WIN:
        return 'exe'
    return 'deb' if os.path.realpath(exe).startswith('/opt/prisma/') else None


def pick_asset(assets, kind):
    ext = {'exe': '.exe', 'deb': '.deb', 'zip': '-windows-portatil.zip'}.get(kind)
    return next((a for a in assets or [] if ext and a.get('name', '').lower().endswith(ext)), None)


def pick_release(rels, current):
    """A Release mais nova que `current` | None. Beta (tag com '-') so' conta se `current` ja' e'
    beta — quem esta na final nao e' empurrado pra pre-lancamento."""
    pre_ok = (parse_ver(current) or (0, 0, 0, 0, 0))[3] < 0
    ok = [r for r in rels if (pre_ok or not r['pre']) and is_newer(r['tag'], current)]
    return max(ok, key=lambda r: parse_ver(r['tag']), default=None)


def fetch_releases(timeout=3.0):
    """Releases publicadas: [{'tag', 'pre', 'notes', 'page', 'assets': [{name, url, size}]}] | []
    (offline, limite da API, JSON estranho...). Nunca levanta."""
    try:
        req = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'prisma-updater'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return [{'tag': x['tag_name'], 'pre': bool(x.get('prerelease')), 'notes': x.get('body') or '',
                 'page': x.get('html_url') or '',
                 'assets': [{'name': a['name'], 'url': a['browser_download_url'], 'size': a.get('size', 0)}
                            for a in x.get('assets') or []]}
                for x in (d if isinstance(d, list) else [d]) if not x.get('draft')]
    except Exception:                                       # noqa: BLE001 — offline = segue normal
        return []


def check(current, timeout=2.0):
    """Release mais nova que `current` | None. Roda numa thread com prazo: DNS travado sem rede
    nao segura a abertura do app alem de `timeout`."""
    box = []
    t = threading.Thread(target=lambda: box.append(fetch_releases(timeout)), daemon=True)
    t.start()
    t.join(timeout + 0.5)
    return pick_release(box[0] if box else [], current)


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


def swap_script(pid, src, here, exe):
    """.bat do portatil: espera o app (pid) fechar, espelha `src` (a pasta nova) em `here` sem
    tocar em `dados`, reabre. /MIR apaga o que a versao nova nao tem; /XD poupa os dados.
    chcp 65001 = caminho com acento (o .bat vai em UTF-8)."""
    return '\r\n'.join([
        '@echo off', 'chcp 65001 >nul',
        ':w', f'tasklist /FI "PID eq {pid}" /NH | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto w)',
        f'robocopy "{src}" "{here}" /MIR /XD "{os.path.join(here, "dados")}" /R:10 /W:1 >nul',
        f'start "" "{os.path.join(here, exe)}"',
        f'rmdir /S /Q "{os.path.dirname(src)}"', ''])


def run_installer(path, kind):
    """Dispara o instalador e devolve True se o app deve FECHAR (o instalador assume)."""
    if kind == 'zip':   # o .exe rodando nao pode ser sobrescrito: o .bat troca depois que fechamos
        tmp = tempfile.mkdtemp(prefix='prisma-up-')
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        os.remove(path)
        exe = os.path.realpath(sys.executable)
        bat = os.path.join(tmp, 'atualizar.bat')
        with open(bat, 'w', encoding='utf-8') as fh:
            fh.write(swap_script(os.getpid(), os.path.join(tmp, 'PRISMA'), os.path.dirname(exe), os.path.basename(exe)))
        subprocess.Popen(['cmd', '/c', bat], creationflags=0x08000000, close_fds=True)   # CREATE_NO_WINDOW
        return True
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


def sync_data(files, home):
    """Dados que o app ENTREGA (shaders, transicoes, modelos) -> pasta do usuario, sem pisar no que e' dele.
    files = [(origem, relativo)]. O registro .entregue.json guarda o hash do que foi entregue: arquivo
    igual ao entregue = intocado -> recebe a versao nova; editado -> fica; apagado pelo usuario -> nao volta;
    novo -> chega. ponytail: instalacao antiga (sem registro) so' ganha os arquivos novos nessa 1a vez."""
    reg_p = os.path.join(home, '.entregue.json')
    try:
        with open(reg_p, encoding='utf-8') as f:
            reg = json.load(f)
    except (OSError, ValueError):
        reg = {}
    h = lambda p: hashlib.sha1(open(p, 'rb').read()).hexdigest()
    out = {}
    for src, rel in files:
        dst, new, old = os.path.join(home, rel), h(src), reg.get(rel)
        if not os.path.exists(dst):
            if old is not None:             # entregue antes e sumiu = o usuario apagou
                out[rel] = old
                continue
        elif old is None or new == old or h(dst) != old:
            out[rel] = old or new            # dele (sem registro / editado) ou ja' atual
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        out[rel] = new
    with open(reg_p, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=0, sort_keys=True)


if __name__ == '__main__':  # self-check (roda: python packaging/updater.py)
    assert parse_ver('v0.3.1') == (0, 3, 1, 0, 0) and parse_ver('1.2') == (1, 2, 0, 0, 0) and parse_ver('abc1234') is None
    assert is_newer('v0.1.0-beta.4', 'v0.1.0-beta.3') and is_newer('v0.1.0-beta.10', 'v0.1.0-beta.9')
    assert is_newer('v0.1.0', 'v0.1.0-beta.1') and not is_newer('v0.1.0-beta.1', 'v0.1.0')   # beta < final
    assert is_newer('v0.10.0', 'v0.9.9') and not is_newer('v0.3.0', 'v0.3.0') and not is_newer('v0.2', 'v0.3')
    assert not is_newer('v1.0', 'abc1234')                  # dev nunca "atrasado"
    a = [{'name': 'prisma_0.3.0_amd64.deb'}, {'name': 'PRISMA-0.3.0-setup.exe'}]
    assert pick_asset(a, 'exe')['name'].endswith('.exe') and pick_asset(a, 'deb')['name'].endswith('.deb')
    assert pick_asset(a, None) is None
    assert install_kind('/opt/prisma/prisma') == ('exe' if IS_WIN else 'deb')
    assert pick_asset(a + [{'name': 'PRISMA-0.3.0-windows-portatil.zip'}], 'zip')['name'].endswith('.zip')
    rels = [{'tag': 'v0.2.0', 'pre': False}, {'tag': 'v0.3.0-beta.2', 'pre': True}, {'tag': 'v0.1.0', 'pre': False}]
    assert pick_release(rels, 'v0.1.0')['tag'] == 'v0.2.0'               # final nao ve beta
    assert pick_release(rels, 'v0.3.0-beta.1')['tag'] == 'v0.3.0-beta.2'  # beta ve beta nova
    assert pick_release(rels, 'v0.3.0-beta.2') is None and pick_release([], 'v0.1.0') is None
    s = swap_script(42, r'C:\t\PRISMA', r'C:\Users\é\PRISMA', 'prisma.exe')
    assert '/MIR' in s and '/XD "' in s and 'dados' in s and 'PID eq 42' in s and s.endswith('\r\n')
    with tempfile.TemporaryDirectory() as t:   # sync_data: novo chega, intocado atualiza, editado fica, apagado nao volta
        b, u = os.path.join(t, 'b'), os.path.join(t, 'u'); os.makedirs(b)
        w = lambda p, x: (os.makedirs(os.path.dirname(p), exist_ok=True), open(p, 'w').write(x))
        r = lambda p: open(p).read()
        for n in 'abcd':
            w(os.path.join(b, n), n + '1')
        fs = [(os.path.join(b, n), os.path.join('sh', n)) for n in 'abcd']
        w(os.path.join(u, 'sh', 'a'), 'meu')                  # instalacao antiga: ja' existia, sem registro
        sync_data(fs, u)
        assert r(os.path.join(u, 'sh', 'a')) == 'meu' and r(os.path.join(u, 'sh', 'b')) == 'b1'
        w(os.path.join(u, 'sh', 'c'), 'editado'); os.remove(os.path.join(u, 'sh', 'd'))
        for n in 'abcd':
            w(os.path.join(b, n), n + '2')                   # versao nova do app
        sync_data(fs, u)
        assert r(os.path.join(u, 'sh', 'a')) == 'meu' and r(os.path.join(u, 'sh', 'b')) == 'b2'
        assert r(os.path.join(u, 'sh', 'c')) == 'editado' and not os.path.exists(os.path.join(u, 'sh', 'd'))
    print('updater self-check ok')
