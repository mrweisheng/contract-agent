#!/usr/bin/env bash
# 供 settle.sh / board.sh 引用：解析出一个「能跑起来」的 Python。
# 判定标准不是存在与否，而是真的能 import reportlab + pypdfium2。
#
# 候选顺序：
#   1. $SETTLEMENT_PYTHON（手动指定）
#   2. <skill包>/.venv/bin/python（install.sh 建的自带环境，最稳）
#   3. $HOME/.workbuddy/binaries/python/envs/default/bin/python（WorkBuddy 受管环境）
#   4. PATH 里的 python3 / python
_pick_python() {
  local skill_dir="$1"
  local cand
  for cand in \
    "${SETTLEMENT_PYTHON:-}" \
    "${skill_dir}/.venv/bin/python" \
    "${HOME}/.workbuddy/binaries/python/envs/default/bin/python" \
    "$(command -v python3 2>/dev/null || true)" \
    "$(command -v python 2>/dev/null || true)"
  do
    [ -n "${cand}" ] || continue
    [ -x "${cand}" ] || continue
    if "${cand}" -c "import reportlab, pypdfium2" >/dev/null 2>&1; then
      echo "${cand}"
      return 0
    fi
  done
  echo ""
}
