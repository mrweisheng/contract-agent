#!/usr/bin/env bash
# 打开「收款结算单录入看板」：把 templates/录入看板.html 包成完整 HTML，
# 起一个本地 HTTP 服务并打印带时间戳的强刷地址（避免浏览器复用上一单的缓存）。
#
#   bash <skill包>/scripts/board.sh                     # 空白录入看板
#   bash <skill包>/scripts/board.sh --prefill <json>    # 用历史单回填
#   bash <skill包>/scripts/board.sh --port 8788
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(cd "${HERE}/.." && pwd)"

# shellcheck source=_python.sh
. "${HERE}/_python.sh"
PY="$(_pick_python "${PKG}")"

if [ -z "${PY}" ]; then
  echo "没有找到可用的 Python，请先运行：bash ${PKG}/install.sh" >&2
  exit 127
fi

exec "${PY}" "${HERE}/open_board.py" "$@"
