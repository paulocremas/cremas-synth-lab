"""Entry point do binario (PyInstaller). So o runtime vai congelado (Python + numpy + pygame +
PyOpenGL); o app em si roda dos .py soltos em src/ ao lado do executavel (mesmo layout do repo:
src/, shaders/, transitions/, media/, dash.html), pra manter o hot-reload por mtime e o
dashboard gravando no tuning.py / nas galerias.
"""
import os
import runpy
import sys

# imports so pra o PyInstaller enxergar e empacotar o que o native_synth.py/dash_* usam
if False:
    import argparse, colorsys, glob, importlib, json, re, select, signal, subprocess  # noqa
    import shutil, tempfile, threading, types, time, urllib.parse, webbrowser, http.server  # noqa
    import numpy, pygame, OpenGL.GL  # noqa

here = os.path.dirname(os.path.realpath(sys.executable))
app = os.path.join(here, 'src', 'native_synth.py')
sys.path.insert(0, os.path.dirname(app))
sys.argv[0] = app
runpy.run_path(app, run_name='__main__')
