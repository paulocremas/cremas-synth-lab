"""O app roda dos .py SOLTOS (src/) — o PyInstaller so' empacota o que o launcher importa. Este
teste falha se algum import de src/*.py nao esta' no bloco `if False:` do launcher.py (o app
instalado quebraria ao abrir com ImportError — aconteceu com ctypes.wintypes no Windows).
Roda: python packaging/check_imports.py   (o CI roda antes do build)"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROOT, 'src', '*.py'))} | {'updater'}
mods = set()
for f in glob.glob(os.path.join(ROOT, 'src', '*.py')):
    for n in ast.walk(ast.parse(open(f, encoding='utf-8').read())):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module)
            if n.module in ('ctypes', 'urllib', 'http'):        # submodulos importados por "from x import y"
                mods |= {f'{n.module}.{a.name}' for a in n.names}
src = open(os.path.join(ROOT, 'packaging', 'launcher.py'), encoding='utf-8').read()
listed = set(re.findall(r'[A-Za-z_][\w.]*', src[src.index('if False:'):src.index('\nIS_WIN')]))
listed |= {m.split()[1] for m in re.findall(r'(?m)^import \w+', src)}
missing = sorted(m for m in mods - LOCAL if m not in listed)
if missing:
    sys.exit('faltam no bloco `if False:` do packaging/launcher.py: ' + ', '.join(missing))
print('check_imports ok')
