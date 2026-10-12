#!/usr/bin/env bash
# Single entry point from an extracted archive or checkout; no curl | sh.
set -Eeuo pipefail
[[ $EUID != 0 ]] || { echo 'Запустите ./setup.sh от обычного пользователя.'; exit 1; }
if ! command -v python3 >/dev/null; then
    sudo pacman -S --needed python
fi
project_dir=$(cd -- "$(dirname -- "$0")" && pwd)
python3 "$project_dir/scripts/bootstrap.py" --prefix "$HOME/.local/share/waybridge/venv"
exec "$HOME/.local/share/waybridge/venv/bin/waybridge" setup "$@"
