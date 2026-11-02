#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
if [ -n "${OPEN_CINEMA_PYTHON:-}" ]; then
  exec "$OPEN_CINEMA_PYTHON" app/launcher.py "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 app/launcher.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python app/launcher.py "$@"
else
  printf '%s\n' 'Python 3.10 or newer is required. Install Python, then run this launcher again.' >&2
  exit 1
fi
