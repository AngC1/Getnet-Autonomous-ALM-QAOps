#!/usr/bin/env bash
# Instala .githooks/pre-commit en .git/hooks (sin tocar git config).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
hooks_dir="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks_dir"
install -m 755 "$root/.githooks/pre-commit" "$hooks_dir/pre-commit"
echo "Hook pre-commit instalado en $hooks_dir/pre-commit"
