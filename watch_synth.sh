#!/bin/bash
# Roda native_synth.py e reinicia sozinho toda vez que o arquivo for salvo.
# Uso: ./watch_synth.sh [mesmos argumentos do native_synth.py]
# ponytail: poll de mtime a cada 1s (sem inotify-tools instalado) — se quiser reagir
# na hora em vez de ate 1s de atraso, "sudo apt install inotify-tools" e trocar o
# "sleep 1" por um "inotifywait -e modify native_synth.py".
cd "$(dirname "$0")"
FILE=native_synth.py
last=$(stat -c %Y "$FILE")

while true; do
  .venv/bin/python "$FILE" "$@" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    cur=$(stat -c %Y "$FILE")
    if [ "$cur" != "$last" ]; then
      last=$cur
      echo "native_synth.py mudou — reiniciando..."
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      continue 2
    fi
    sleep 1
  done
  break  # processo saiu sozinho (janela fechada/ESC) — para o watcher tambem
done
