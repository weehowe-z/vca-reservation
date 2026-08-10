#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${PYTHON:-python3}"
PACKAGE_DIR="$ROOT/dist/fc"
ZIP_PATH="$ROOT/dist/fc-package.zip"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

"$PYTHON" -m pip install --quiet --target "$PACKAGE_DIR" "$ROOT[fc]"

cat > "$PACKAGE_DIR/handler.py" <<'PY'
from vca_reservation.faas import handler

__all__ = ["handler"]
PY

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -f "$ZIP_PATH"

(
    cd "$PACKAGE_DIR"
    zip -q -r "$ZIP_PATH" .
)

echo "Function Compute package built: $ZIP_PATH"
echo "Deploy with runtime=python3.12, handler=handler.handler"