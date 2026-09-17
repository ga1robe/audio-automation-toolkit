#!/usr/bin/env bash
set -euo pipefail

BASE_PY="${VENV_BASE:-/opt/venv311-base}/bin/python3.11"
TF_PY="${VENV_TF:-/opt/venv311-tf}/bin/python3.11"
ASR_PY="${VENV_ASR:-/opt/venv311-asr}/bin/python3.11"

for label in \
  "base:${BASE_PY}" \
  "tf:${TF_PY}" \
  "asr:${ASR_PY}"; do
  name="${label%%:*}"
  target="${label#*:}"

  echo "[audio-toolkit] using ${name} interpreter: ${target}"

  if [[ ! -x "${target}" ]]; then
    echo "[audio-toolkit] ERROR: missing interpreter for ${name} at ${target}" >&2
    exit 1
  fi

  echo "[audio-toolkit] ${name} will run: ${target} -V"
  "${target}" -V
 done

echo "[audio-toolkit] launcher: /workspace/src/audio_toolkit.py $*"
echo "[audio-toolkit] starting pipeline..."
exec /workspace/src/audio_toolkit.py "$@"
