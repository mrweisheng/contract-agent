#!/usr/bin/env bash
# 明哥中港牌 · 收款结算单 Skill —— 一键安装
#
#   bash install.sh              # 只装运行环境（在包内建 .venv + 装依赖）
#   bash install.sh --install-skill  # 同时把本包安装到 ~/.workbuddy/skills/settlement-statement
#
# 装完会跑一遍自检（check_env.py），确认字体、依赖、样板生成全部 OK。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
INSTALL_SKILL=0
for arg in "$@"; do
  [ "$arg" = "--install-skill" ] && INSTALL_SKILL=1
done

echo "==> 1/4 检查 Python"
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "未找到 Python 3，请先安装（https://www.python.org/downloads/ 或 brew install python3）" >&2
  exit 127
fi
echo "    使用：${PY} 版本 $(${PY} -V 2>&1)"

echo "==> 2/4 建立独立虚拟环境 $VENV"
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

echo "==> 3/4 安装依赖（reportlab / pypdfium2）"
"$VPY" -m pip install --upgrade pip --quiet
"$VPY" -m pip install -r "$HERE/requirements.txt" --quiet

echo "==> 4/4 自检"
"$VPY" "$HERE/scripts/check_env.py"

if [ "$INSTALL_SKILL" = "1" ]; then
  DEST="$HOME/.workbuddy/skills/settlement-statement"
  echo "==> 安装 Skill 到 $DEST"
  mkdir -p "$HOME/.workbuddy/skills"
  if [ -e "$DEST" ]; then
    echo "    已存在同名目录，未覆盖：${DEST} (请手动确认后自行替换)"
  else
    cp -R "$HERE" "$DEST"
    echo "    已安装。重启 AI 客户端后即可使用。"
  fi
fi

echo
echo "安装完成。日常制单命令（一条命令出 PDF+PNG 并进剪贴板）："
echo "  bash $HERE/scripts/settle.sh --input - --png --clipboard --brief <<'JSON'"
echo "  {...业务 JSON...}"
echo "  JSON"
echo
echo "打开录入看板：bash $HERE/scripts/board.sh"
