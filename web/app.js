/* 华星智能合同生成系统 · 前端
 * 布局：墨绿侧栏 + 米白主区，自写极简样式
 * 校验：必填项已填=绿光晕，未填=红光晕，AI回填=琥珀底
 * 双模式加载：Vite 开发服务器（npm run dev，改完即自动刷新）
 *            与 FastAPI 直出（start.bat，无需 Node）均适用
 */
import "/vendor/vue.global.prod.js";
const { createApp, reactive, ref, computed, onMounted, nextTick } = window.Vue;
if (import.meta.env?.DEV) import("/style.css");  // 开发态把样式纳入 Vite 模块图，改 CSS 也即时生效

/* ---------- 工具 ---------- */
const CN_D = "零壹贰叁肆伍陆柒捌玖";
const CN_U = ["", "拾", "佰", "仟"];
const CN_G = ["", "万", "亿", "兆"];
function fourDigits(n) {
  if (!n) return "";
  let parts = [], zero = false, started = false;
  for (let pos = 3; pos >= 0; pos--) {
    const d = Math.floor(n / 10 ** pos) % 10;
    if (!d) { if (started) zero = true; }
    else {
      if (zero) { parts.push("零"); zero = false; }
      parts.push(CN_D[d] + CN_U[pos]); started = true;
    }
  }
  return parts.join("");
}
function toCN(v) {
  const n = parseInt(v);
  if (isNaN(n) || n < 0) return "";
  if (n === 0) return "零元整";
  const segs = [];
  let x = n;
  while (x > 0) { segs.push(x % 10000); x = Math.floor(x / 10000); }
  segs.reverse();
  const parts = []; let pending = false;
  segs.forEach((seg, i) => {
    if (!seg) { pending = true; return; }
    let s = fourDigits(seg);
    if (parts.length && (pending || seg < 1000)) parts.push("零");
    parts.push(s + CN_G[segs.length - 1 - i]);
    pending = false;
  });
  return parts.join("") + "元整";
}
function commas(v) { const n = parseInt(v); return isNaN(n) ? "" : n.toLocaleString("en-US"); }
const SEQ_CN = i => i <= 10 ? "一二三四五六七八九十"[i - 1] : String(i);
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* ---------- Toast ---------- */
const toasts = ref([]);
function toast(msg, type = "ok", duration = 2800) {
  const id = Math.random().toString(36).slice(2);
  toasts.value.push({ id, msg, type });
  setTimeout(() => {
    toasts.value = toasts.value.filter(t => t.id !== id);
  }, duration);
}

const app = createApp({
  setup() {
    /* ---------- 状态 ---------- */
    const types = ref([]);
    const currencies = ref([]);
    const selected = reactive({ type: "", port: "" });
    const form = reactive({});
    const aiFilled = reactive({});
    const nlText = ref("");
    const extractNotes = ref([]);
    const warnNotes = ref([]);   // 问题类提示（未提及/币种不明等），只有它驱动弹窗
    const extracting = ref(false);
    const parsing = ref(false);
    const generating = ref(false);
    const notesModal = ref(false);   // 解析提示弹窗（有遗漏/提示时自动弹出）
    const result = ref(null);
    const historyOpen = ref(false);
    const historyItems = ref([]);
    const resultBox = ref(null);
    const elapsed = reactive({ extract: 0, parse: 0, gen: 0 });
    setInterval(() => {
      if (extracting.value) elapsed.extract++; else elapsed.extract = 0;
      if (parsing.value) elapsed.parse++; else elapsed.parse = 0;
      if (generating.value) elapsed.gen++; else elapsed.gen = 0;
    }, 1000);

    // 智能录入全屏进度：两个任务各自 run|done|skip|fail
    const nlProg = reactive({ show: false, extract: "run", pay: "skip" });
    // 派生态：总完成 / 任一失败 / 当前计时 / 轮播阶段文案
    const allDone = computed(() => nlProg.extract === "done" && (nlProg.pay === "done" || nlProg.pay === "skip"));
    const anyFail = computed(() => nlProg.extract === "fail" || nlProg.pay === "fail");
    const activeSecs = computed(() => (nlProg.extract === "run" ? elapsed.extract : elapsed.parse));
    const EXTRACT_PHRASES = ["正在理解客户描述", "正在识别主体信息", "正在提取业务字段", "正在核对口岸要素"];
    const PAY_PHRASES = ["正在解析付款约定", "正在推算付款日期", "正在核对分期合计", "正在对齐模板条款"];
    const loadingPhrase = computed(() => {
      if (anyFail.value) return "解析未成功";
      if (allDone.value) return "解析完成";
      if (nlProg.extract === "run") return EXTRACT_PHRASES[elapsed.extract % EXTRACT_PHRASES.length];
      return PAY_PHRASES[elapsed.parse % PAY_PHRASES.length];
    });

    /* ---------- 在途请求管理（P1-1：防止切换业务类型后旧响应回填新表单）---------- */
    // reqGen 每次切换业务类型自增；在途请求回调发现代次不符即丢弃结果
    let reqGen = 0;
    const pendingCtrls = new Set();

    function cancelPending() {
      reqGen += 1;
      pendingCtrls.forEach(c => c.abort());
      pendingCtrls.clear();
      nlProg.show = false;
      extracting.value = false;
      parsing.value = false;
    }

    async function postJSON(url, body) {
      const ctrl = new AbortController();
      pendingCtrls.add(ctrl);
      try {
        const r = await fetch(url, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body), signal: ctrl.signal,
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || "请求失败");
        return data;
      } finally {
        pendingCtrls.delete(ctrl);
      }
    }

    const payment = reactive({ rows: [], customText: "", parsedRaw: "" });
    const payNotes = ref([]);

    const cfg = computed(() => types.value.find(t => t.key === selected.type) || null);
    const currencyLabel = c => ({ HKD: "港币 HK$", CNY: "人民币 ¥" }[c] || c);
    const totalKey = computed(() => selected.type === "car" ? "total_price" : "total_fee");
    const total = computed(() => parseInt(form[totalKey.value]) || 0);

    /* ---------- 左侧导航 ---------- */
    const menu = computed(() => {
      const get = k => types.value.find(t => t.key === k);
      const items = [];
      if (get("car")) items.push({ title: "车辆买卖", list: [{ key: "car", port: "", label: "香港车辆买卖" }] });
      if (get("transfer_gx") && get("transfer_ns")) items.push({
        title: "现牌过户", list: [
          { key: "transfer_gx", port: "", label: "高新两地牌过户" },
          { key: "transfer_ns", port: "", label: "纳税两地牌过户" },
        ]
      });
      const np = get("new_port");
      if (np && np.ports) items.push({
        title: "粤 Z 新办", list: np.ports.map(p => ({ key: "new_port", port: p, label: p.replace("口岸", "") }))
      });
      return items;
    });
    const isActive = it => selected.type === it.key && selected.port === it.port;

    function initForm() {
      Object.keys(form).forEach(k => delete form[k]);
      Object.keys(aiFilled).forEach(k => delete aiFilled[k]);
      const c = cfg.value;
      if (!c) return;
      form.currency = c.currency_default;
      form.sign_date = todayISO();
      form.agreement_no = "";
      c.groups.forEach(g => g.fields.forEach(f => {
        form[f.key] = f.auto || (f.default !== undefined ? f.default : "");
      }));
      c.fee_fields.forEach(f => { form[f.key] = f.default !== undefined ? f.default : null; });
      form.port = selected.port;
    }
    // 按合同模板预置分期行（金额待填；签约当日期预填签署日期，非卖车定金行锁定为签署日期）
    function mkPresetRows(fill) {
      return (cfg.value?.pay_preset || []).map((p, i) => {
        const f = fill(i);
        return {
          seq: i + 1, label: f.label || p.label, amount: f.amount,
          // 日期兜底仅限"签约当日"行（无事件的定金/订金行）；其余行客户没给就留空，绝不代填
          date: (p.dated && !p.event) ? (f.date || form.sign_date || "") : (f.date || ""),
          event: p.event || "",
          preset: true,
          lockDate: !!(p.dated && !p.event && !cfg.value?.car_default),
        };
      });
    }
    function initPayment() {
      payment.rows = mkPresetRows(() => ({ amount: null, date: "", label: "" }));
      payment.customText = ""; payment.parsedRaw = "";
      payNotes.value = [];
    }
    function selectMenu(it) {
      if (isActive(it)) return;
      cancelPending();  // 作废在途的抽取/解析响应，避免旧类型数据回填新表单
      selected.type = it.key; selected.port = it.port;
      result.value = null; extractNotes.value = []; warnNotes.value = [];
      initForm(); initPayment();
    }

    /* ---------- 必填字段校验 ---------- */
    const requiredKeys = computed(() => {
      const c = cfg.value;
      if (!c) return new Set();
      const s = new Set();
      c.groups.forEach(g => g.fields.forEach(f => {
        if (f.required && !f.auto) s.add(f.key);
      }));
      c.fee_fields.forEach(f => { if (f.required) s.add(f.key); });
      if (c.port_required) s.add("port");
      return s;
    });

    /* ---------- 智能抽取 ---------- */
    async function runExtract() {
      if (nlText.value.trim().length < 5) { toast("请先输入业务描述", "warn"); return; }
      extracting.value = true; extractNotes.value = []; warnNotes.value = [];
      result.value = null;   // 新一轮解析开始：上一次的生成结果（含下载按钮）随之作废
      const raw = nlText.value.trim();
      const myGen = reqGen;  // 本次请求所属代次
      // 付款约定就在原文里：与字段抽取并行解析，付款表可与表单回填同时出现
      const payPromise = /付|款|分期|订金|定金|尾款/.test(raw) ? parseCustomText(raw, true) : null;
      nlProg.show = true; nlProg.extract = "run"; nlProg.pay = payPromise ? "run" : "skip";
      try {
        const data = await postJSON("/api/extract", { type: selected.type, text: raw });
        if (myGen !== reqGen) return;  // 期间切换了业务类型：丢弃旧响应，不回填新表单
        Object.entries(data.fields || {}).forEach(([k, v]) => {
          if (v === null || v === undefined) return;
          if (k === "quota_type") return;
          form[k] = v; aiFilled[k] = true;
        });
        if (data.currency && ["HKD", "CNY"].includes(data.currency)) {
          form.currency = data.currency; aiFilled.currency = true;
        }
        if (data.total) { form[totalKey.value] = data.total; aiFilled[totalKey.value] = true; }
        if (data.payment_text) {
          payment.customText = data.payment_text;
          extractNotes.value.push("已自动解析付款约定为分期表，请核对金额与条件");
          // 并行解析未覆盖时（原文无付款关键词）退回串行解析
          if (!payPromise) {
            nlProg.pay = "run";
            nlProg.pay = (await parseCustomText(data.payment_text, true)) ? "done" : "fail";
          }
        }
        (data.notes || []).forEach(n => { extractNotes.value.push(n); warnNotes.value.push(n); });
        toast("已回填表单，请核对高亮字段", "ok");
      } catch (e) {
        if (e.name === "AbortError") return;  // 主动取消（切换类型），不提示
        toast(String(e.message || e), "error");
        nlProg.extract = "fail";
      } finally {
        extracting.value = false;  // 提取状态到此结束，付款解析由付款卡片自己的状态展示
        if (myGen === reqGen && nlProg.extract === "run") nlProg.extract = "done";
      }
      if (myGen !== reqGen) return;  // 已切换类型，后续回填与遮罩收起都不再执行
      if (payPromise) nlProg.pay = (await payPromise) ? "done" : "fail";
      // 先展示印章、收起遮罩，再集中弹窗提示遗漏
      const delay = nlProg.pay === "fail" ? 1600 : 1100;
      setTimeout(() => {
        nlProg.show = false;
        if ([...warnNotes.value, ...payNotes.value].length) notesModal.value = true;
      }, delay);
    }

    /* ---------- 付款解析 ---------- */
    async function parseCustomText(t, silent = false) {
      t = (t || "").trim();
      if (t.length < 3) { if (!silent) toast("请先填写付款约定的自然语言描述", "warn"); return false; }
      parsing.value = true;
      payment.parsedRaw = t;
      payNotes.value = [];
      result.value = null;   // 付款计划即将变化：旧合同不再对应，清掉生成结果
      const myGen = reqGen;  // 本次请求所属代次
      try {
        const data = await postJSON("/api/parse-payment", {
          type: selected.type,
          currency: form.currency,
          total: total.value,
          text: t,
          sign_date: form.sign_date || "",
        });
        if (myGen !== reqGen) return false;  // 期间切换了业务类型：丢弃旧响应
        const c = cfg.value?.pay_preset || [];
        const inst = data.installments || [];
        if (data.matches_preset && inst.length === c.length) {
          // 与模板预设一致：保留预设行，只填金额与日期
          payment.rows = mkPresetRows(i => ({
            amount: inst[i].amount === null || inst[i].amount === undefined
              ? null : parseInt(inst[i].amount),
            date: inst[i].trigger_date || "",
            label: (inst[i].label || "").trim().slice(0, 6),
          }));
          if (!silent) toast("付款安排与合同模板一致，已填入各期金额，请核对", "ok");
        } else {
          payment.rows = inst.map((x, i) => ({
            seq: i + 1,
            label: (x.label || "").trim().slice(0, 6),
            // 后端解析失败时 amount 为 null，此处保持空值让用户手动补（不再变成 NaN）
            amount: x.amount === null || x.amount === undefined ? null : parseInt(x.amount),
            date: x.trigger_date || "",
            event: x.trigger || "",
            preset: false,
          }));
          if (!silent) toast(`已按客户约定解析出 ${payment.rows.length} 期付款计划，请核对`, "ok");
        }
        (data.notes || []).forEach(n => {
          payNotes.value.push(n);
          if (!silent) toast(n, "warn", 4500);
        });
        return true;
      } catch (e) {
        if (e.name === "AbortError") return false;  // 主动取消（切换类型），不提示
        if (!silent) toast(String(e.message || e), "error");
        else {
          const msg = `付款约定自动解析未成功：${e.message || e}，请在付款计划中手动填写`;
          extractNotes.value.push(msg); warnNotes.value.push(msg);
        }
        return false;
      } finally { if (myGen === reqGen) parsing.value = false; }
    }
    function parseCustom() { return parseCustomText(payment.customText, false); }
    function addRow() {
      payment.rows.push({ seq: payment.rows.length + 1, label: "", amount: null, date: "", event: "", preset: false });
    }
    function delRow(i) {
      payment.rows.splice(i, 1);
      payment.rows.forEach((r, j) => r.seq = j + 1);
    }
    function resetPayRows() { initPayment(); }
    function onAmount(i) {
      // 卖车预设两期：改订金后尾款自动 = 总费用 − 订金
      const r = payment.rows;
      if (cfg.value?.car_default && r.length === 2 && i === 0 && (parseInt(r[0].amount) > 0)) {
        r[1].amount = total.value - parseInt(r[0].amount);
      }
    }
    const paySum = computed(() => payment.rows.reduce((s, r) => s + (parseInt(r.amount) || 0), 0));
    const payOk = computed(() =>
      payment.rows.length > 0 && total.value > 0 && paySum.value === total.value &&
      payment.rows.every(r => (parseInt(r.amount) || 0) > 0 &&
        (String(r.date || "").trim() || String(r.event || "").trim()))
    );

    /* ---------- 校验 ---------- */
    const missing = computed(() => {
      const m = [];
      const c = cfg.value;
      if (!c) return m;
      c.groups.forEach(g => g.fields.forEach(f => {
        if (!f.required || f.auto) return;
        if (!String(form[f.key] ?? "").trim()) m.push(f.label);
      }));
      c.fee_fields.forEach(f => { if (f.required && !form[f.key]) m.push(f.label); });
      if (c.port_required && !form.port) m.push("口岸");
      return m;
    });
    const canGenerate = computed(() => missing.value.length === 0 && payOk.value);

    /* ---------- 生成 ---------- */
    async function generate() {
      generating.value = true;
      const myGen = reqGen;  // 同上：生成期间切换类型则丢弃结果
      try {
        const rows = payment.rows.map(r => ({
          seq: r.seq,
          label: (r.label || "").trim(),
          amount: parseInt(r.amount),
          date: (r.lockDate ? (form.sign_date || null) : (r.date || null)),
          event: (r.event || "").trim(),
        }));
        const payload = {
          type: selected.type,
          form: JSON.parse(JSON.stringify(form)),
          // 统一分期表直发，模式（模板预设/一次性/自定义）由后端 derive_payment 判定
          payment: { installments: rows, source_text: payment.customText || null },
        };
        const data = await postJSON("/api/generate", payload);
        if (myGen !== reqGen) return;  // 期间切换了业务类型：丢弃旧响应
        result.value = data;
        await nextTick();
        resultBox.value?.scrollIntoView({ behavior: "smooth", block: "start" });
        if (data.ok) toast(`合同 ${data.no} 生成并核对通过`, "ok", 3500);
        else toast("生成完成，但核对未通过，请查看问题清单", "error", 4000);
      } catch (e) {
        if (e.name === "AbortError") return;  // 主动取消（切换生成类型），不提示
        toast(String(e.message || e), "error");
      } finally { if (myGen === reqGen) generating.value = false; }
    }
    function download() { if (result.value?.download_url) window.open(result.value.download_url); }

    async function openHistory() {
      historyOpen.value = true;
      try {
        const r = await fetch("/api/history");
        const d = await r.json();
        historyItems.value = d.items || [];
      } catch (e) { toast("加载历史失败", "error"); }
    }
    function historyDownload(no) { window.open(`/api/download/${no}`); }

    onMounted(async () => {
      try {
        const r = await fetch("/api/types");
        const d = await r.json();
        types.value = d.types;
        currencies.value = d.currencies;
        const first = menu.value[0]?.list[0];
        if (first) selectMenu(first);
      } catch (e) {
        toast("无法加载业务类型：" + (e.message || e), "error", 5000);
      }
    });

    /* ---------- 视图辅助 ---------- */
    function fmtDate(s) { return s || "—"; }

    // 各业务类型的智能录入示例文案(根据业务真实场景)
    const NL_PLACEHOLDERS = {
      car: "示例：客户张三（证件 H1234567，电话 91234567）买车牌 LN1234 的 2022 款丰田 Alphard，VIN WBA…，港币 50 万；分 5 期付款，每期 10 万，签约当日付第一期，之后每月 10 号付一期。",
      transfer_gx: "示例：客户鸿达投资有限公司（证件 91110000MA0000000X，联络人李四，电话 13800001234）委托高新过户车牌 LN1234，目标香港公司 XX 物流有限公司，通行莲塘口岸，服务总费用港币 30 万；分三期支付，每期 10 万，第一期签约当日付，第二期提交资料后 3 日内付，尾款过户完成后付。",
      transfer_ns: "示例：客户鸿达投资有限公司（证件 91110000MA0000000X，联络人李四，电话 13800001234）委托纳税过户车牌 LN1234，目标香港公司 XX 物流有限公司、目标内地公司 XX 国际货运代理有限公司，通行深圳湾口岸，服务总费用港币 30 万；分三期支付，每期 10 万。",
      new_port: "示例：客户王五（身份证 440000000000000000，电话 13800001234）通过莲塘口岸新办粤 Z 两地牌，服务总费用人民币 25 万；分三期支付，第一期签约当日付，第二期省厅获编号后 1 个工作日内付，第三期领取铁牌等通关资料时付。",
    };
    function nlPlaceholder() {
      return NL_PLACEHOLDERS[selected.type] || NL_PLACEHOLDERS.car;
    }
    // 各业务类型(及粤 Z 口岸)对应的合同模板名
    const TEMPLATE_NAMES = {
      car: "香港车辆买卖合约",
      transfer_gx: "高新两地牌现牌过户",
      transfer_ns: "纳税两地牌现牌过户(两家公司)",
      "莲塘口岸": "莲塘口岸粤Z新办协议",
      "深圳湾口岸": "深圳湾口岸粤Z新办协议",
      "港珠澳大桥口岸": "港珠澳大桥口岸粤Z新办协议",
      "沙头角口岸": "沙头角口岸粤Z新办协议",
    };
    const templateName = computed(() => {
      if (selected.type === "new_port") return TEMPLATE_NAMES[form.port] || "粤Z新办协议";
      return TEMPLATE_NAMES[selected.type] || "";
    });
    return {
      toasts,  // 模板 v-for 渲染 Toast；漏返回会因模板取不到模块作用域而静默不显示
      types, currencies, selected, form, aiFilled, nlText, extractNotes, warnNotes, payNotes, notesModal,
      extracting, parsing, generating, result, historyOpen, historyItems, resultBox, elapsed, nlProg,
      allDone, anyFail, activeSecs, loadingPhrase,
      cfg, currencyLabel, totalKey, total, payment, menu, isActive,
      selectMenu, runExtract, parseCustom, addRow, delRow, resetPayRows, onAmount, paySum, payOk,
      missing, canGenerate, generate, download,
      openHistory, historyDownload, toCN, commas, SEQ_CN,
      fmtDate, todayISO, requiredKeys,
      nlPlaceholder, templateName,
    };
  },

  template: /* html */ `
  <div class="shell">
    <!-- ================= 侧栏 ================= -->
    <aside class="side">
      <div class="brand">
        <div class="logo">華星</div>
        <div class="sub">CONTRACT · AGENT</div>
      </div>
      <div class="side-groups">
        <template v-for="(g, gi) in menu" :key="g.title">
          <div class="side-group-label">{{ g.title }}</div>
          <div v-for="(it, ii) in g.list" :key="it.key + it.port"
               class="side-item" :class="{active: isActive(it)}"
               @click="selectMenu(it)">
            <span class="num">{{ String(ii + 1).padStart(2, '0') }}</span>
            <span>{{ it.label }}</span>
          </div>
        </template>
      </div>
    </aside>

    <!-- ================= 主区 ================= -->
    <section class="main">
      <header class="topbar">
        <div class="crumb">
          {{ cfg?.label || '华星智能合同' }}
          <span class="meta" v-if="cfg">
            <template v-if="form.port"> · {{ form.port }}</template>
          </span>
        </div>
        <div class="spacer"></div>
        <button class="btn ghost" @click="openHistory">生成历史</button>
      </header>

      <div class="scroll">
        <!-- ===== 智能录入（单行紧凑） ===== -->
        <div class="card">
          <div class="card-head">
            <h3>智能录入</h3>
          </div>
          <div class="card-body">
            <div class="nl-compact">
              <textarea class="ctrl" v-model="nlText" :placeholder="nlPlaceholder()"></textarea>
              <button class="btn primary" :disabled="extracting" @click="runExtract">
                <span v-if="extracting" class="spin"></span>
                {{ extracting ? '提取中…' : 'AI 提取' }}
              </button>
            </div>
          </div>
        </div>

        <!-- ===== 合同信息（合并：基础信息 + 业务字段分组 + 价款） ===== -->
        <div class="card" v-if="cfg">
          <div class="card-head">
            <h3>合同信息</h3>
            <div class="basic-bar" style="margin-left:auto">
              <span class="lbl">编号</span>
              <input class="h-inp num" value="" placeholder="自动分配" disabled title="编号由服务端统一分配，生成后在「生成结果」中展示">
              <span class="lbl">签署</span>
              <input class="h-inp date" type="date" v-model="form.sign_date">
            </div>
          </div>
          <div class="card-body">
            <!-- 档案证件式：每组一张档案卡（宋体栏位+水印+印章角标）；价款并入最后一组（商品/标的信息） -->
            <div class="id-cards">
              <div class="idcard" v-for="(g, gi) in cfg.groups" :key="g.title"
                   :data-wm="g.title.replace(/（.*）/, '').slice(0, 2)">
                <div class="id-head">
                  <span class="t">{{ g.title }}</span>
                  <span class="stamp">{{ SEQ_CN(gi + 1) }}</span>
                </div>
                <div class="id-row" v-for="f in g.fields" :key="f.key"
                     :class="{
                       ai: aiFilled[f.key] && !f.auto,
                       done: requiredKeys.has(f.key) && !f.auto && String(form[f.key] ?? '').trim() !== '',
                       miss: requiredKeys.has(f.key) && !f.auto && String(form[f.key] ?? '').trim() === ''
                     }">
                  <label>{{ f.label }}<span class="req" v-if="f.required && !f.auto">*</span></label>
                  <input v-if="f.auto" class="ctrl-id" :value="f.auto" disabled/>
                  <select v-else-if="f.type==='select'" class="ctrl-id" v-model="form[f.key]">
                    <option value="" disabled>请选择</option>
                    <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                  </select>
                  <input v-else class="ctrl-id" v-model="form[f.key]" :placeholder="f.auto ? '' : '待填'"/>
                  <span v-if="aiFilled[f.key] && !f.auto" class="st-ai">AI</span>
                </div>

                <!-- 价款：商品信息的一部分，并入最后一张档案卡；币种在编辑区、金额前 -->
                <template v-if="gi === cfg.groups.length - 1">
                  <div class="id-row fee" v-for="(f, fi) in cfg.fee_fields" :key="f.key"
                       :class="{
                         ai: aiFilled[f.key],
                         done: requiredKeys.has(f.key) && !!form[f.key],
                         miss: requiredKeys.has(f.key) && !form[f.key]
                       }">
                    <label>{{ f.label }}<span class="req" v-if="f.required">*</span></label>
                    <select v-if="fi === 0" class="cur-inline" v-model="form.currency">
                      <option v-for="c in currencies" :key="c.value" :value="c.value">{{ c.label }}</option>
                    </select>
                    <input class="ctrl-id money" type="number" min="0" step="1000"
                           v-model.number="form[f.key]" placeholder="待补"/>
                    <span v-if="aiFilled[f.key]" class="st-ai">AI</span>
                    <div v-if="form[f.key] > 0" class="fee-cn">
                      {{ form.currency === 'HKD' ? '港币' : '人民币' }}{{ toCN(form[f.key]) }}
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== 付款计划（紧凑表，移除独立 AI 解析） ===== -->
        <div class="card" v-if="cfg">
          <div class="card-head">
            <h3>付款计划</h3>
            <span style="font-size:12px;color:var(--muted);margin-left:8px">各期合计须等于{{ totalKey === 'total_price' ? '总售价' : '总费用' }}</span>
            <button class="btn sm" style="margin-left:auto" @click="addRow">＋ 加一期</button>
          </div>
          <div class="card-body">
            <div style="overflow-x:auto">
              <table class="pay-table">
                <thead>
                  <tr>
                    <th style="width:110px">期数</th>
                    <th style="width:130px">款项名称</th>
                    <th style="width:170px">金额</th>
                    <th style="width:150px">付款日期</th>
                    <th>付款事件条件</th>
                    <th style="width:60px"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(it, idx) in payment.rows" :key="idx"
                      :class="{ ai: it.preset && !it.edited }">
                    <td class="seq">
                      <span class="seq-n">{{ SEQ_CN(idx + 1) }}</span>第{{ SEQ_CN(idx + 1) }}期
                    </td>
                    <td>
                      <input class="p-in" v-model="it.label" maxlength="6"
                             placeholder="如：定金"
                             @input="it.edited = true; it.preset = false"/>
                    </td>
                    <td class="amt">
                      <input class="p-in" type="number" min="1" step="1000"
                             v-model.number="it.amount"
                             @input="onAmount(idx); it.edited = true; it.preset = false"/>
                      <span class="p-cn" v-if="it.amount > 0">{{ toCN(it.amount) }}</span>
                    </td>
                    <td>
                      <input v-if="it.lockDate" class="p-in" type="date" :value="form.sign_date" disabled/>
                      <input v-else class="p-in" type="date" v-model="it.date" @input="it.edited = true; it.preset = false"/>
                    </td>
                    <td>
                      <input class="p-in" v-model="it.event"
                             placeholder="付款日期或触发条件"
                             @input="it.edited = true; it.preset = false"/>
                    </td>
                    <td>
                      <button class="btn ghost sm" @click="delRow(idx)">删除</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="sum-line" :class="payOk ? 'ok' : (total > 0 ? 'bad' : '')">
              <template v-if="total === 0">
                <span style="color:var(--muted)">请先在上方「合同信息」填写总费用</span>
              </template>
              <template v-else-if="payOk">
                <span style="color:var(--muted);font-size:13px;letter-spacing:1px">分期合计</span>
                <span class="big">{{ currencyLabel(form.currency) }} {{ commas(paySum) }}</span>
                <span class="big-cn">＝ {{ totalKey === 'total_price' ? '总售价' : '服务总费用' }} · 两讫</span>
                <span style="color:var(--muted);font-size:12.5px;margin-left:auto">共 {{ payment.rows.length }} 期</span>
                <span class="seal-mini">讫</span>
              </template>
              <template v-else>
                <div style="width:100%">
                  <div>分期需满足：每期金额 &gt; 0、有付款日期或事件条件、各期合计 = 总费用</div>
                  <div style="margin-top:4px;font-size:12.5px">
                    当前合计 <b style="color:var(--accent)">{{ currencyLabel(form.currency) }} {{ commas(paySum) }}</b>
                    <span style="margin:0 6px">/</span> 需 <b style="color:var(--accent)">{{ commas(total) }}</b>
                  </div>
                </div>
              </template>
            </div>

            <div class="note-strip-in-card" v-if="payNotes.length || extractNotes.length">
              <span v-for="(n, i) in [...payNotes, ...extractNotes]" :key="i">{{ n }}</span>
            </div>
          </div>
        </div>

      <!-- ===== 生成结果 ===== -->
        <div class="card" v-if="result" ref="resultBox">
          <div class="card-head">
            <h3>生成结果</h3>
            <span class="result-no">{{ result.no }}</span>
            <span class="tag" :class="result.ok ? 'ok' : 'bad'">
              {{ result.ok ? '核对通过' : '核对未通过' }}
            </span>
            <div class="spacer" style="flex:1"></div>
            <button class="btn primary" v-if="result.ok" @click="download">下载合同 (.docx)</button>
          </div>
          <div class="card-body">
            <div v-if="result.errors?.length">
              <div v-for="(e, i) in result.errors" :key="i" class="note error" style="margin-bottom:6px">
                ⚠ {{ e }}
              </div>
            </div>
            <div v-if="result.warnings?.length">
              <div v-for="(w, i) in result.warnings" :key="i" class="note" style="margin-bottom:6px">
                ⚠ {{ w }}
              </div>
            </div>
            <details style="margin-top:8px">
              <summary style="cursor:pointer;font-family:'Noto Serif SC',serif;font-weight:600;color:#1d3a2f;letter-spacing:1px;padding:6px 0">
                展开预览合同正文
              </summary>
              <div class="contract-text" style="margin-top:10px">{{ result.text }}</div>
            </details>
          </div>
        </div>

      </div>
      <!-- ===== 底部操作栏（主区常驻底栏） ===== -->
      <!-- ===== 底部操作栏（内容主体内，跟随表单） ===== -->
      <div class="action-bar" v-if="cfg">
        <div class="status">
          <span class="pill" :class="missing.length ? 'bad' : 'ok'">
            {{ missing.length ? '未完成 ' + missing.length + ' 项' : '全部就绪' }}
          </span>
          <span class="list" v-if="missing.length">
            {{ missing.slice(0,5).join('、') }}{{ missing.length > 5 ? ' 等' + missing.length + ' 项' : '' }}
          </span>
        </div>
        <div class="spacer"></div>
        <span v-if="generating" style="font-size:12px;color:#8a8276">
          生成与 AI 复核中（已等 {{ elapsed.gen }} 秒，通常 10~60 秒）
        </span>
        <button class="btn accent lg" :disabled="!canGenerate" @click="generate">
          <span v-if="generating" class="spin"></span>
          {{ generating ? '生成中…' : '生成合同 →' }}
        </button>
      </div>
    </section>

    <!-- ===== 历史抽屉 ===== -->
    <div class="drawer-mask" v-if="historyOpen" @click.self="historyOpen=false">
      <div class="drawer">
        <div class="drawer-head">
          生成历史
          <span style="font-family:'Noto Sans SC',sans-serif;font-size:12px;color:#8a8276;letter-spacing:0;margin-left:6px">
            （最近 50 条）
          </span>
          <div class="spacer"></div>
          <button class="btn ghost" @click="historyOpen=false">关闭</button>
        </div>
        <div class="drawer-body">
          <table class="drawer-list" v-if="historyItems.length">
            <thead>
              <tr>
                <th>编号</th><th>类型</th><th>客户</th><th>付款</th>
                <th>币种</th><th>时间</th><th>状态</th><th>文件</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in historyItems" :key="h.no">
                <td style="font-family:'Noto Serif SC',serif">{{ h.no }}</td>
                <td>{{ h.type }}</td>
                <td>{{ h.client || '—' }}</td>
                <td>{{ h.mode || '—' }}</td>
                <td>{{ h.currency || '—' }}</td>
                <td style="font-size:12px;color:#8a8276">{{ h.created_at }}</td>
                <td>
                  <span class="tag" :class="h.status === 'ok' ? 'ok' : 'bad'">
                    {{ h.status === 'ok' ? '通过' : '失败' }}
                  </span>
                </td>
                <td>
                  <button v-if="h.status==='ok'" class="btn sm" @click="historyDownload(h.no)">下载</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="drawer-empty">暂无生成记录</div>
        </div>
      </div>
    </div>

    <!-- ===== Toast ===== -->
    <!-- ===== AI 提取全屏进度（v3.3 · 深墨幕布 + 纸面仪式感） ===== -->
    <div class="fs-mask" v-if="nlProg.show" :class="{done: allDone, fail: anyFail}">
      <span class="fs-wm w1">契</span><span class="fs-wm w2">約</span>
      <div class="fs-paper">
        <i class="fs-c tl"></i><i class="fs-c tr"></i><i class="fs-c bl"></i><i class="fs-c br"></i>
        <div class="fs-head">
          <span class="fs-brand">華星 · 智能解析</span>
          <span class="fs-timer" v-if="!allDone && !anyFail">已等 <b>{{ activeSecs }}</b> 秒 · 通常 5~40 秒</span>
        </div>
        <div class="fs-center">
          <div class="fs-seal-big" v-if="allDone">成</div>
          <div class="fs-seal-big bad" v-else-if="anyFail">待</div>
          <transition name="fsfade" v-else>
            <div class="fs-phrase" :key="loadingPhrase">{{ loadingPhrase }}</div>
          </transition>
        </div>
        <div class="fs-ink"><span :class="{run: !allDone && !anyFail, ok: allDone, bad: anyFail}"></span></div>
        <div class="fs-steps">
          <div class="fs-step" :class="nlProg.extract">
            <i class="fs-si"></i><span>客户与业务信息</span>
            <em v-if="nlProg.extract === 'run'">{{ elapsed.extract }}s</em>
            <em v-else-if="nlProg.extract === 'done'">完成</em>
            <em v-else-if="nlProg.extract === 'fail'">失败</em>
            <em v-else>—</em>
          </div>
          <div class="fs-step" :class="nlProg.pay">
            <i class="fs-si"></i><span>付款约定</span>
            <em v-if="nlProg.pay === 'run'">{{ elapsed.parse }}s</em>
            <em v-else-if="nlProg.pay === 'done'">完成</em>
            <em v-else-if="nlProg.pay === 'fail'">失败</em>
            <em v-else>跳过</em>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== 解析提示弹窗（有遗漏/提示时弹出，可关闭） ===== -->
    <div class="modal-mask" v-if="notesModal" @click.self="notesModal = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>解析完成 · 共 {{ warnNotes.length + payNotes.length }} 条提示</h3>
        </div>
        <div class="modal-body">
          <div v-for="(n, i) in [...warnNotes, ...payNotes]" :key="i" class="note">{{ n }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn primary" @click="notesModal = false">知道了，去核对</button>
        </div>
      </div>
    </div>

    <div class="toast-wrap">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">{{ t.msg }}</div>
    </div>
  </div>
  `,
});

app.mount("#app");

