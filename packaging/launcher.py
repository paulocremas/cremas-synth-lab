"""Entry point do binario (PyInstaller), Linux e Windows. So o runtime vai congelado (Python +
numpy + pygame + PyOpenGL + cv2; no Windows + PyAudioWPatch e o ffmpeg ao lado); o app em si
roda dos .py soltos em src/ (mesmo layout do repo: src/, shaders/, transitions/, media/,
models/, dash*.html), pra manter o hot-reload por mtime e o dashboard gravando no tuning.py /
nas galerias.

Onde roda: na pasta de dados do usuario (plat.data_dir: ~/.local/share/prisma |
%LOCALAPPDATA%\\prisma | $PRISMA_HOME), nunca na pasta do binario — dist/prisma/ e recriado a
cada build, /opt/prisma (.deb) e Program Files so' admin grava. A cada abertura: codigo (CODE) e
sobrescrito com o da versao do binario; dados do usuario (DATA: tuning, shaders, transicoes,
midia) so sao copiados se ainda nao existirem.

PORTATIL (zip do Windows): `portable.txt` ao lado do binario -> dados em <pasta>/dados (apagou a
pasta, sumiu tudo; nada no %LOCALAPPDATA%).

Antes de abrir: checagem de atualizacao (packaging/updater.py — offline/mesma versao = segue).
"""
import glob
import os
import runpy
import shutil
import sys

import updater

# imports so pra o PyInstaller enxergar e empacotar o que o native_synth.py/dash_*/plat usam
# (o app roda dos .py soltos; packaging/check_imports.py confere que nada falta aqui)
if False:
    import argparse, atexit, collections, colorsys, concurrent.futures, copy, ctypes, ctypes.wintypes, glob, hashlib, importlib  # noqa
    import io, json, math, re, select, signal, socket, subprocess  # noqa
    import msvcrt  # noqa  (so' existe no Windows: plat.readable)
    import tempfile, threading, types, time, urllib.parse, urllib.request, webbrowser, http.server  # noqa
    import numpy, pygame, OpenGL, OpenGL.GL, cv2  # noqa
    import pyaudiowpatch  # noqa  (so' existe no build do Windows)

IS_WIN = sys.platform == 'win32'
CODE_FILES = ['dash.html', 'dash2.html', 'favicon.png']        # + src/*.py menos o tuning.py
DATA = ['src/tuning.py', 'shaders', 'transitions', 'media', 'models']


def _user_copy(bundle, home):
    code = CODE_FILES + [os.path.relpath(p, bundle) for p in glob.glob(os.path.join(bundle, 'src', '*.py'))
                         if os.path.basename(p) != 'tuning.py']
    for rel in code:
        dst = os.path.join(home, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(bundle, rel), dst)
    for rel in DATA:
        src = os.path.join(bundle, rel)
        if os.path.isfile(src):
            files = [(src, os.path.join(home, rel))]
        else:
            files = [(os.path.join(d, f), os.path.join(home, rel, os.path.relpath(os.path.join(d, f), src)))
                     for d, _, fs in os.walk(src) for f in fs]
        for s, d in files:
            if not os.path.exists(d):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(s, d)
    os.makedirs(os.path.join(home, 'media'), exist_ok=True)


def _tuning_ok(path):
    try:
        with open(path, 'rb') as f:
            compile(f.read(), path, 'exec')
        return True
    except (OSError, SyntaxError, ValueError):
        return False


def _guard_tuning(bundle, home):
    """tuning.py estragado (PC caiu no meio da gravacao -> bytes nulos; edicao a mao errada) nao
    abre o app: guarda o ruim como tuning.py.quebrado e volta o ultimo que abriu (tuning.py.bom)
    ou o padrao do binario. Abriu bem -> vira o novo .bom."""
    t = os.path.join(home, 'src', 'tuning.py')
    good = t + '.bom'
    if _tuning_ok(t):
        shutil.copyfile(t, good)
        return
    if os.path.exists(t):
        os.replace(t, t + '.quebrado')
        print('tuning.py estragado -> tuning.py.quebrado; voltando o ultimo bom', flush=True)
    shutil.copyfile(good if _tuning_ok(good) else os.path.join(bundle, 'src', 'tuning.py'), t)


def _data_dir(here):   # = plat.data_dir (o plat.py ainda nao esta no path aqui)
    if os.environ.get('PRISMA_HOME'):
        return os.environ['PRISMA_HOME']
    if updater.is_portable(here):   # zip portatil: dados dentro da propria pasta
        return os.path.join(here, 'dados')
    if IS_WIN:
        return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'prisma')
    return os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'prisma')


here = os.path.dirname(os.path.realpath(sys.executable))
root = _data_dir(here)
os.makedirs(root, exist_ok=True)
if IS_WIN:
    # --windowed: sem console -> o que o app imprime vai pro log; o ffmpeg vem junto no instalador
    sys.stdout = sys.stderr = open(os.path.join(root, 'prisma.log'), 'w', encoding='utf-8', buffering=1)
    os.environ['PATH'] = os.path.join(here, 'ffmpeg') + os.pathsep + os.environ.get('PATH', '')

if updater.maybe_update(here, sys.executable):
    sys.exit(0)                     # o instalador da versao nova assumiu

_user_copy(here, root)
_guard_tuning(here, root)
app = os.path.join(root, 'src', 'native_synth.py')
sys.path.insert(0, os.path.dirname(app))
sys.argv[0] = app
runpy.run_path(app, run_name='__main__')
