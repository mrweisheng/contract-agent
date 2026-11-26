/* UI 页面×区块 冒烟测试（无构建架构下的前端回归红线）
 * ============================================================
 * 背景：2026-11-26 结算单页误渲染合同（发票页提交把合同预览块的
 * v-else 错挂到发票底栏）。此类「共享栏条件链错配」的回归靠人眼盯不住，
 * 本脚本把「哪种页面该显示哪些区块」钉成矩阵逐格断言，任何一页多了/少了
 * 区块即红。规约与矩阵说明见 docs/ui-pages.md。
 *
 * ⚠ 事实源 = 本文件的 MATRIX。新增页面类型或增删共享区块时，
 *   必须同改 MATRIX 与 docs/ui-pages.md 的矩阵表，并跑通本脚本。
 *
 * 运行前提：
 *   1. 本地服务已启动（http://127.0.0.1:8300，start.bat）
 *   2. agent-browser CLI 在 PATH（npm i -g agent-browser；首次需 agent-browser install）
 *   3. 动过 web/ 共享区域的提交，提交前必跑：node scripts/test_ui_smoke.mjs
 *
 * 注意：跑「电子收据」页会自动取號（未存檔佔號 30 分鐘自動回收），
 *       反复跑会滚动消耗编号段，属正常现象。
 */
import { execSync } from "node:child_process";

const BASE = process.env.UI_SMOKE_BASE || "http://127.0.0.1:8300";
const POLL_MS = 700;
const POLL_TIMEOUT_MS = 20000;

/* ---------- 页面×区块期望矩阵（事实源） ----------
 * 字段语义：
 *   previewPane      右栏预览区是否应存在（合同管理/用户管理为全宽页，无右栏）
 *   pvHead           右栏标题文案
 *   leftPane         左栏应渲染哪个 pane-body（contract/settlement/invoice）
 *   leftHead         左栏 h2 文案（leftHeadIncludes=包含匹配）
 *   barsInclude      右栏底栏文案必须包含的片段（数组逐项）
 *   barsForbidden    右栏底栏文案必须不包含的片段（他页底栏串页即红）
 *   contractCellsMin 合同 docx 表格单元格最少数量（>0 = 合同预览已渲染）
 *   contractCellsZero 合同表格单元格必须为 0（他页 docx 串页即红）
 *   stImg / invSvg   结算单成品图 / 发票 SVG 是否应存在 */
const MATRIX = [
  {
    name: "合同（卖车·落地页）", nav: null,
    expect: {
      previewPane: true, pvHead: "合同实时预览", leftPane: "contract",
      leftHeadIncludes: "卖车", barsInclude: ["生成合同"],
      barsForbidden: ["生成结算单", "下載發票"],
      contractCellsMin: 1, stImg: false, invSvg: false,
    },
  },
  {
    name: "结算单（原始 bug 页：右栏曾串入合同预览+底栏）", nav: "结算单",
    expect: {
      previewPane: true, pvHead: "结算单成品", leftPane: "settlement",
      leftHead: "收款结算单", barsInclude: ["生成结算单"],
      barsForbidden: ["生成合同", "下載發票"],
      contractCellsZero: true, stImg: true, invSvg: false,
    },
  },
  {
    name: "电子收据", nav: "电子收据",
    expect: {
      previewPane: true, pvHead: "發票實時預覽", leftPane: "invoice",
      leftHead: "电子收据", barsInclude: ["下載發票"],
      barsForbidden: ["生成合同", "生成结算单"],
      contractCellsZero: true, stImg: false, invSvg: true,
      invPayee: "陳煥明",
    },
  },
  {
    name: "合同管理（全宽页，无右栏）", nav: "合同管理",
    expect: { previewPane: false, ctChips: ["近7天", "近30天", "本月"] },
  },
  {
    name: "用户管理（全宽页，无右栏）", nav: "用户管理",
    expect: { previewPane: false },
  },
  {
    name: "切回合同（结算单→车务，覆盖原始 bug 的切换路径）", nav: "车务",
    expect: {
      previewPane: true, pvHead: "合同实时预览", leftPane: "contract",
      barsInclude: ["生成合同"], barsForbidden: ["生成结算单", "下載發票"],
      contractCellsMin: 1, stImg: false, invSvg: false,
    },
  },
];

/* ---------- agent-browser 驱动 ----------
 * 每次调用硬超时：agent-browser 个别等待条件（如 load 态）可能永不满足，
 * 无超时会静默挂死整条流水线（2026-11-26 实测）。150s 兼顾浏览器冷启动。 */
const AB_TIMEOUT_MS = 150000;
function ab(args, input) {
  return execSync(`agent-browser ${args}`, {
    input, encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
    timeout: AB_TIMEOUT_MS,
  });
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* 顶栏点击：找 .nav-item 下文字精确相等的叶子 span，dispatchEvent 冒泡触发 @click。
 * 「车务」类下拉组点叶子=直选第一个子项（卖车），正好覆盖跨组切回路径。
 * 全程 stdin 传中文，避开 Windows cmd 命令行参数编码坑。 */
function clickNav(label) {
  const js = `(() => {
    const label = ${JSON.stringify(label)};
    const spans = [...document.querySelectorAll("header.topbar nav .nav-item > span")]
      .filter(s => s.textContent.trim() === label);
    if (!spans.length) return "NAV-NOT-FOUND";
    spans[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    return "CLICKED";
  })()`;
  const out = ab("eval --stdin", js).trim();
  if (out.includes("NAV-NOT-FOUND")) throw new Error(`顶栏找不到「${label}」`);
  if (!out.includes("CLICKED")) throw new Error(`点击「${label}」失败：${out}`);
}

/* 采集右栏+左栏结构快照 */
function probe() {
  const js = `(() => {
    const pv = document.querySelector(".preview-pane");
    const bars = pv ? [...pv.querySelectorAll(".gen-bar")]
      .map(g => g.textContent.trim().replace(/\\s+/g, " ")) : [];
    return JSON.stringify({
      previewPane: !!pv,
      pvHead: pv ? (pv.querySelector(".pv-head b")?.textContent.trim() ?? null) : null,
      bars,
      contractCells: pv ? pv.querySelectorAll("table td").length : -1,
      stImg: !!(pv && pv.querySelector(".st-result img.st-img")),
      invSvg: !!(pv && pv.querySelector(".inv-scroll svg")),
      leftHead: document.querySelector(".pane .pane-top h2")?.textContent.trim() ?? null,
      leftPane: document.querySelector(".pane .st-pane") ? "settlement"
              : document.querySelector(".pane .inv-pane") ? "invoice" : "contract",
      /* 收款人固定（業務要求 2026-11-26）：值必須是陳煥明且只讀，杜絕再被改回可編輯 */
      invPayee: (() => {
        const i = document.querySelector("#inv-payee");
        return i ? { value: i.value, readonly: i.readOnly } : null;
      })(),
      /* 合同管理快捷日期標籤（業務要求只留三個：近7天/近30天/本月） */
      ctChips: [...document.querySelectorAll(".ct-quick .chip")].map(b => b.textContent.trim()),
    });
  })()`;
  /* agent-browser 会把 JS 返回值再做一层 JSON 编码（字符串带引号）：
     先解它那层，再解我们的 JSON，兼容两种形态 */
  let val = JSON.parse(ab("eval --stdin", js).trim());
  return typeof val === "string" ? JSON.parse(val) : val;
}

/* ---------- 断言 ---------- */
function checkPage(expect, act) {
  const fails = [];
  const has = (k) => expect[k] !== undefined;
  if (has("previewPane") && act.previewPane !== expect.previewPane)
    fails.push(`右栏存在=${act.previewPane}，期望 ${expect.previewPane}`);
  /* 全宽页（合同管理）没有右栏，但左栏筛选区的断言照样要跑，所以放在早退之前 */
  if (has("ctChips")) {
    const want = JSON.stringify(expect.ctChips), got = JSON.stringify(act.ctChips || []);
    if (want !== got) fails.push(`快捷日期标签 ${got}，期望 ${want}`);
  }
  if (!act.previewPane) return fails;   // 全宽页只断言以上几条
  if (has("pvHead") && act.pvHead !== expect.pvHead)
    fails.push(`右栏标题「${act.pvHead}」≠「${expect.pvHead}」`);
  if (has("leftPane") && act.leftPane !== expect.leftPane)
    fails.push(`左栏渲染=${act.leftPane}，期望 ${expect.leftPane}`);
  if (has("leftHead") && act.leftHead !== expect.leftHead)
    fails.push(`左栏标题「${act.leftHead}」≠「${expect.leftHead}」`);
  if (has("leftHeadIncludes") && !(act.leftHead || "").includes(expect.leftHeadIncludes))
    fails.push(`左栏标题「${act.leftHead}」不含「${expect.leftHeadIncludes}」`);
  for (const frag of expect.barsInclude || [])
    if (!act.bars.some(b => b.includes(frag))) fails.push(`底栏缺「${frag}」（实际：${JSON.stringify(act.bars)}）`);
  for (const frag of expect.barsForbidden || [])
    if (act.bars.some(b => b.includes(frag))) fails.push(`底栏串入他页内容「${frag}」（实际：${JSON.stringify(act.bars)}）`);
  if (has("contractCellsZero") && expect.contractCellsZero && act.contractCells !== 0)
    fails.push(`合同 docx 串入右栏（${act.contractCells} 个表格单元格）`);
  if (has("contractCellsMin") && act.contractCells < expect.contractCellsMin)
    fails.push(`合同预览未渲染（${act.contractCells} 个单元格 < ${expect.contractCellsMin}）`);
  if (has("stImg") && act.stImg !== expect.stImg)
    fails.push(`结算单成品图存在=${act.stImg}，期望 ${expect.stImg}`);
  if (has("invSvg") && act.invSvg !== expect.invSvg)
    fails.push(`发票 SVG 存在=${act.invSvg}，期望 ${expect.invSvg}`);
  if (has("invPayee")) {
    if (!act.invPayee) fails.push("找不到收款人字段 #inv-payee");
    else {
      if (act.invPayee.value !== expect.invPayee)
        fails.push(`收款人「${act.invPayee.value}」≠「${expect.invPayee}」`);
      if (act.invPayee.readonly !== true) fails.push("收款人字段可编辑（应固定只读）");
    }
  }
  return fails;
}

/* ---------- 主流程 ---------- */
let failed = 0;
try {
  ab(`open ${BASE}`);
  await sleep(1500);   // 不用 wait --load networkidle：SPA 上该条件可能永不满足（有 per-call 硬超时兜底，这里纯轮询等渲染）

  for (const page of MATRIX) {
    process.stderr.write(`… ${page.name}\n`);
    if (page.nav) clickNav(page.nav);
    const t0 = Date.now();
    let act = null, fails = null;
    while (Date.now() - t0 < POLL_TIMEOUT_MS) {
      await sleep(POLL_MS);
      try { act = probe(); } catch { continue; }   // 过渡动画中 DOM 缺失：重试
      fails = checkPage(page.expect, act);
      if (!fails.length) break;
    }
    if (fails && fails.length) {
      failed++;
      console.log(`❌ ${page.name}`);
      for (const f of fails) console.log(`   · ${f}`);
      console.log(`   快照：${JSON.stringify(act)}`);
    } else {
      console.log(`✅ ${page.name}`);
    }
  }
} catch (e) {
  console.error(`💥 驱动失败（检查本地服务与 agent-browser）：${e.message}`);
  process.exit(2);
} finally {
  try { ab("close"); } catch { /* 幂等 */ }
}

if (failed) {
  console.log(`\n${failed} 页不达标——共享区块串页/缺失，禁止提交（规约见 docs/ui-pages.md）`);
  process.exit(1);
}
console.log("\n全部页面区块矩阵达标。");
