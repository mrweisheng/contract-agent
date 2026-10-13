#!/usr/bin/env bash
# 结算单统一入口：自动挑 Python 解释器（包内 .venv 优先，其次系统 python3），
# 然后调用 make_settlement.py。用法与 python 版完全一致，可直接接 heredoc。
#
#   bash <skill>/scripts/settle.sh --input - --png --clipboard --brief <<'JSON'
#   {...业务 JSON...}
#   JSON
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(cd "$HERE/.." && pwd)"

PY="$PKG/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "${PY:-}" ]; then
  PY="$(command -v python || true)"
fi
if [ -z "${PY:-}" ]; then
  echo "找不到 Python。请先运行 bash $PKG/install.sh 安装环境。" >&2
  exit 127
fi

exec "$PY" "$HERE/make_settlement.py" "$@"
