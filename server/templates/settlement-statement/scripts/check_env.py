#!/usr/bin/env python3
"""安装自检：字体、依赖、版式引擎、样板出单，四步一次跑完。

用法：
    python scripts/check_env.py            # 只检查
    python scripts/check_env.py --sample   # 额外生成一张样板单（写入 output/pdf、output/image）
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PKG = Path(__file__).resolve().parent.parent
OK = "  [OK]  "
BAD = "  [FAIL]"

SAMPLE = {
    "customer": "測試客戶",
    "group": "0000測試客戶蓮塘新办粤Z0000",
    "port": "莲塘口岸",
    "settle_type": "收尾款",
    "date": "2026年10月10日",
    "date_iso": "20261010",
    "contract_total": [{"item": "车牌总价", "amount": 160000, "currency": "CNY"}],
    "contract_paid": [{"item": "定金", "amount": 130000, "currency": "CNY"}],
    "contract_unpaid": [{"item": "车牌尾款", "amount": 30000, "currency": "CNY"}],
    "extra_fees": [{"item": "批文卡", "amount": 260, "currency": "HKD"}],
    # 汇率：默认按百度实时汇率口径取当日值；合同有约定汇率时改用合同汇率。
    # apply_101 恒为 true —— 人民币折港币一律 ×1.01，不要关。
    "rate": {"cny_to_hkd": 1.1726, "apply_101": True, "basis": "today",
             "source": "百度实时汇率"},
}


def check_imports() -> bool:
    ok = True
    for mod in ("reportlab", "pypdfium2"):
        try:
            __import__(mod)
            print(f"{OK}依赖 {mod}")
        except ImportError:
            print(f"{BAD}依赖 {mod} 未安装：pip install -r requirements.txt")
            ok = False
    return ok


def check_font() -> bool:
    try:
        from settlement_engine import FONT_PATH
        print(f"{OK}中文字体 {FONT_PATH}")
        return True
    except FileNotFoundError as exc:
        print(f"{BAD}{exc}")
        return False


def check_assets() -> bool:
    ok = True
    for rel in ("assets/明哥中港牌-logo.png",
                "assets/收款结算单统一版式基准.pdf",
                "templates/录入看板.html"):
        if (PKG / rel).exists():
            print(f"{OK}资源 {rel}")
        else:
            print(f"{BAD}缺少资源 {rel}")
            ok = False
    return ok


def check_sample() -> bool:
    from settlement_compute import build_spec
    from settlement_engine import PKG as _PKG  # noqa: F401
    from settlement_engine import build_output_path, plan_layout, register_font, Renderer

    started = time.time()
    spec, detail = build_spec(dict(SAMPLE))
    register_font()
    # 样板单写到临时目录，不污染 output/（那里放的是真实客户成品）
    out_dir = Path(tempfile.mkdtemp(prefix="settlement-selftest-"))
    pdf_path = build_output_path(spec, out_dir)
    renderer = Renderer(spec, plan_layout(spec))
    renderer.render(pdf_path)
    elapsed = time.time() - started
    pay = " / ".join(detail["today_pay"].values())
    print(f"{OK}样板单已生成 {pdf_path.name}（需付 {pay}，耗时 {elapsed:.2f}s）")
    for w in detail.get("warnings", []) + renderer.warnings:
        print(f"       警告：{w}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="结算单环境自检")
    ap.add_argument("--sample", action="store_true", help="额外生成一张样板结算单")
    args = ap.parse_args()

    print(f"Python {sys.version.split()[0]}  |  包目录 {PKG}")
    ok = check_imports() and check_font() and check_assets()
    if args.sample and ok:
        ok = check_sample() and ok
    print("全部通过，可以开始制单。" if ok else "存在未通过项，按上面的提示处理后重跑。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
