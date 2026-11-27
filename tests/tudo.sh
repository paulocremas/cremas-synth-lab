#!/usr/bin/env bash
# TODOS OS TESTES num comando (revisao geral E3, 2026-11-27).
#   tests/tudo.sh           = os RAPIDOS (self-checks puros, ~1 min; nao abrem janela nem navegador)
#   tests/tudo.sh --lento   = + o motor com GL (native --selfcheck: matriz de emergencia, padrao de teste) e os GESTOS do painel
#                             (tests/dash_gestos.py, Chromium sem tela, ~6 min). Rodar antes de entregar mudanca no dash5.html.
# Nenhum grava no src/tuning.py do repositorio (usam tuning temporario); o script confere isso no fim.
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
antes=$(sha1sum src/tuning.py)
falhou=()
roda(){ echo "== $*"; if ! "$PY" "$@" > /tmp/prisma-teste.log 2>&1; then tail -15 /tmp/prisma-teste.log; falhou+=("$*"); fi; }
roda src/dash_data.py
roda src/ritmo.py
roda src/plat.py
roda src/dash_server.py
roda src/telao_sim.py --selfcheck
roda packaging/updater.py
roda packaging/check_imports.py
if [ "${1:-}" = "--lento" ]; then
  roda src/native_synth.py --selfcheck
  echo "== tests/dash_gestos.py (gestos; alguns falham as vezes so' na suite: rode o que falhou sozinho)"
  "$PY" tests/dash_gestos.py | tail -3 || falhou+=("tests/dash_gestos.py")
fi
[ "$antes" = "$(sha1sum src/tuning.py)" ] || falhou+=("um teste MUDOU o src/tuning.py do repositorio")
if [ ${#falhou[@]} -eq 0 ]; then echo "tudo ok"; else printf 'FALHOU: %s\n' "${falhou[@]}"; exit 1; fi
