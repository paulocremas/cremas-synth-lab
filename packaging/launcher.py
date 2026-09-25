"""Entry point do binario (PyInstaller). So o runtime vai congelado (Python + numpy + pygame +
PyOpenGL); o app em si roda dos .py soltos em src/ (mesmo layout do repo: src/, shaders/,
transitions/, media/, dash.html), pra manter o hot-reload por mtime e o dashboard gravando no
tuning.py / nas galerias.

Onde roda: sempre em ~/.local/share/prisma/ (ou $PRISMA_HOME), nunca na pasta do binario —
dist/prisma/ e recriado do zero a cada build (PyInstaller apaga a pasta) e /opt/prisma (.deb) so
root grava. A cada abertura: codigo (CODE) e sobrescrito com o da versao do binario; dados do
usuario (DATA: tuning, shaders, transicoes, midia) so sao copiados se ainda nao existirem.
"""
import os
import runpy
import shutil
import sys

# imports so pra o PyInstaller enxergar e empacotar o que o native_synth.py/dash_* usam
if False:
    import argparse, colorsys, glob, importlib, json, re, select, signal, subprocess  # noqa
    import tempfile, threading, types, time, urllib.parse, webbrowser, http.server  # noqa
    import numpy, pygame, OpenGL.GL  # noqa

CODE = ['src/native_synth.py', 'src/dash_server.py', 'src/dash_data.py', 'dash.html', 'dash2.html', 'favicon.png']
DATA = ['src/tuning.py', 'shaders', 'transitions', 'media']


def _user_copy(bundle, home):
    for rel in CODE:
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


here = os.path.dirname(os.path.realpath(sys.executable))
root = os.environ.get('PRISMA_HOME') or os.path.join(
    os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'prisma')
_user_copy(here, root)

app = os.path.join(root, 'src', 'native_synth.py')
sys.path.insert(0, os.path.dirname(app))
sys.argv[0] = app
runpy.run_path(app, run_name='__main__')
