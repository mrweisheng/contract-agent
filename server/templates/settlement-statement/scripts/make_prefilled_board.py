#!/usr/bin/env python3
"""把一份历史结算单（business.json）还原成可编辑的预填录入面板。

用法：
    python make_prefilled_board.py --input data/statements/许兰坛_收尾款_20261009.json \
        --out <会话目录>/board/xulantan.html

输出的是一个完整 HTML：打开即可看到该单所有字段已回填，改完点「生成业务资料」重新出单。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
TEMPLATE = PKG / "templates/录入看板.html"

PRELOAD = """
<script>
(function () {
  var DATA = __DATA__;
  var root = document.getElementById('settlement-entry-board');
  var $ = function (sel) { return root.querySelector(sel); };
  var all = function (sel) { return Array.prototype.slice.call(root.querySelectorAll(sel)); };
  var fire = function (el, ev) { el.dispatchEvent(new Event(ev, { bubbles: true })); };
  var cur = function (c) { return c === 'CNY' ? '人民币' : '港币'; };

  // 业务类型
  var bizMap = { '现牌结算单': '#seb-existing', '新办结算单': '#seb-new', '车辆买卖结算单': '#seb-car' };
  var bizSel = bizMap[DATA.business] || '#seb-new';
  var biz = $(bizSel); if (biz) { biz.checked = true; fire(biz, 'change'); }

  // 结算类型
  var typeMap = { '收定金': '#seb-deposit-type', '收第二期款': '#seb-second-type',
                  '收尾款': '#seb-tail-type', '补款': '#seb-extra-type', '其他': '#seb-other-type' };
  var tSel = typeMap[DATA.settle_type];
  if (tSel) { var t = $(tSel); t.checked = true; fire(t, 'change'); }
  else { var o = $('#seb-other-type'); o.checked = true; fire(o, 'change');
         $('#seb-other-type-text').value = DATA.settle_type || ''; }

  $('#seb-group').value = DATA.group || '';
  $('#seb-customer').value = DATA.customer || '';
  $('#seb-date').value = DATA.date || '';
  $('#seb-subject').value = DATA.vehicle || DATA.port || '';

  // 合同总价
  var total = (DATA.contract_total || [])[0];
  if (total) {
    var txt = String(total.amount);
    $('#seb-total').value = txt + (total.currency === 'CNY' ? '人民币' : '港币');
  }

  function fillRow(row, name, amount, currency, status, equivalent) {
    row.querySelector('[data-field="name"]').value = name;
    row.querySelector('[data-field="amount"]').value = String(amount);
    row.querySelector('[data-field="currency"]').value = currency;
    row.querySelector('[data-field="status"]').value = status;
    if (equivalent !== undefined && row.querySelector('[data-field="equivalent"]')) {
      row.querySelector('[data-field="equivalent"]').value = equivalent;
    }
  }

  function rebuild(sel, addBtn, entries, filler) {
    all(sel).forEach(function (r) { r.remove(); });
    entries.forEach(function (e) {
      $(addBtn).click();
      var rows = all(sel);
      filler(rows[rows.length - 1], e);
    });
  }

  // 合同内已收款项
  rebuild('#seb-contract-rows .seb-repeat-row', '#seb-add-contract', DATA.contract_paid || [],
    function (row, e) {
      var eq = '';
      if (e.currency === 'HKD' && e.cny_equiv) eq = '¥' + e.cny_equiv + '/$' + e.amount;
      else if (e.currency === 'CNY' && e.hkd_equiv) eq = '¥' + e.amount + '/$' + e.hkd_equiv;
      fillRow(row, e.item, e.amount, cur(e.currency), '已收', eq);
    });

  // 合同内未收款项
  rebuild('#seb-unpaid-rows .seb-unpaid-item', '#seb-add-unpaid', DATA.contract_unpaid || [],
    function (item, e) {
      var name = e.item;
      var typeSel = item.querySelector('[data-field="type"]');
      var opts = Array.prototype.map.call(typeSel.options, function (o) { return o.value; });
      if (opts.indexOf(name) >= 0) typeSel.value = name;
      else { typeSel.value = '其他'; fire(typeSel, 'change');
             item.querySelector('[data-field="other"]').value = name; }
      var eq = '';
      if (e.currency === 'CNY' && e.hkd_equiv) eq = '¥' + e.amount + '/$' + e.hkd_equiv;
      else if (e.currency === 'HKD' && e.cny_equiv) eq = '¥' + e.cny_equiv + '/$' + e.amount;
      item.querySelector('[data-field="amount"]').value = String(e.amount);
      item.querySelector('[data-field="currency"]').value = cur(e.currency);
      item.querySelector('[data-field="equivalent"]').value = eq;
      item.querySelector('[data-field="status"]').value =
        e.status === 'next' ? '下次收款' : (e.gift ? '赠送' : '应收');
    });

  // 合同外杂费（含赠送项；extra_paid 还原成标「减免」的杂费行）
  var fees = (DATA.extra_fees || []).slice();
  (DATA.extra_paid || []).forEach(function (p) {
    fees.push({ item: p.item, amount: p.amount, currency: p.currency, deduct: true });
  });
  rebuild('#seb-expense-rows .seb-repeat-row', '#seb-add-expense', fees,
    function (row, e) {
      fillRow(row, e.item, e.amount, cur(e.currency),
              e.deduct ? '减免' : (e.gift ? '赠送' : '应收'));
    });

  $('#seb-expense-paid').value = '0';
  $('#seb-expense-paid-name').value = '';

  // 合同汇率或签订日（有则回填）
  if (DATA.rate && DATA.rate.basis === 'contract' && DATA.rate.cny_to_hkd) {
    $('#seb-contract-date').value = String(DATA.rate.cny_to_hkd);
  }
})();
</script>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="历史结算单还原为可编辑录入面板")
    ap.add_argument("--input", required=True, help="business.json 路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    ap.add_argument("--title", default="收款结算单 · 历史单编辑")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    body = io.open(TEMPLATE, encoding="utf-8").read()
    payload = PRELOAD.replace("__DATA__", json.dumps(data, ensure_ascii=False))

    html = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>" + args.title + "</title>\n"
        "<style>html,body{margin:0;padding:0;background:#f2f5f9;}</style>\n</head>\n<body>\n"
        + body + "\n" + payload + "\n</body>\n</html>\n"
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
