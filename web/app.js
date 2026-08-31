/* 华星智能合同生成系统 · 前端
 * 布局：墨绿侧栏 + 米白主区，自写极简样式
 * 校验：必填项已填=绿光晕，未填=红光晕，AI回填=琥珀底
 */
const { createApp, reactive, ref, computed, onMounted, nextTick } = Vue;

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
    const extracting = ref(false);
    const parsing = ref(false);
    const generating = ref(false);
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

    const payment = reactive({
      mode: "default",
      deposit_amount: null, deposit_date: "", balance_date: "", choice: "较早者",
      pay1: null, pay2: null, pay3: null,
      pay_date: "", pay_event: "", one_choice: "较早者",
      customText: "", installments: [],
      parsedFromNL: false,    // 标记：是否经自然语言解析
      parsedRaw: "",          // 解析时的原文
    });

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
    function resetPayment() {
      Object.assign(payment, {
        mode: "default", deposit_amount: null, deposit_date: "", balance_date: "",
        choice: "较早者", pay1: null, pay2: null, pay3: null,
        pay_date: "", pay_event: "", one_choice: "较早者",
        customText: "", installments: [],
        parsedFromNL: false, parsedRaw: "",
      });
    }
    function selectMenu(it) {
      if (isActive(it)) return;
      selected.type = it.key; selected.port = it.port;
      result.value = null; extractNotes.value = [];
      initForm(); resetPayment();
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
    // 返回字段的 css class: { filled, missing, ai }
    function fieldCls(key) {
      const req = requiredKeys.value.has(key);
      const val = form[key];
      const filled = String(val ?? "").trim() !== "";
      const ai = !!aiFilled[key];
      return {
        "is-required": req,
        "is-filled": req && filled,
        "is-missing": req && !filled,
        "is-ai": ai,
      };
    }

    /* ---------- 智能抽取 ---------- */
    async function runExtract() {
      if (nlText.value.trim().length < 5) { toast("请先输入业务描述", "warn"); return; }
      extracting.value = true; extractNotes.value = [];
      try {
        const r = await fetch("/api/extract", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: selected.type, text: nlText.value.trim() }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "抽取失败");
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
          payment.parsedRaw = data.payment_text;
          extractNotes.value.push("已自动解析付款约定为分期表，请核对金额与条件");
          // 自动调用付款解析(静默,不弹中间 toast)
          await parseCustom(true);
        }
        (data.notes || []).forEach(n => extractNotes.value.push(n));
        toast("已回填表单，请核对高亮字段", "ok");
      } catch (e) {
        toast(String(e.message || e), "error");
      } finally { extracting.value = false; }
    }

    /* ---------- 付款解析 ---------- */
    async function parseCustom(silent = false) {
      const t = payment.customText.trim();
      if (t.length < 3) { if (!silent) toast("请先填写付款约定的自然语言描述", "warn"); return; }
      parsing.value = true;
      payment.parsedRaw = t;
      try {
        const r = await fetch("/api/parse-payment", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: selected.type,
            currency: form.currency,
            total: total.value,
            text: t,
            sign_date: form.sign_date || "",
          }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "解析失败");
        if (data.mode === "default") {
          payment.mode = "default";
          if (!silent) toast("按合同默认分期处理", "ok");
        } else if (data.mode === "one_time") {
          payment.mode = "one_time";
          const ot = data.one_time || {};
          payment.pay_date = ot.pay_date || "";
          payment.pay_event = ot.pay_event || "";
          if (!silent) toast("已按一次性付清填充，请核对", "ok");
        } else {
          payment.mode = "custom";
          payment.installments = (data.installments || []).map(x => ({
            seq: x.seq, amount: parseInt(x.amount),
            trigger: x.trigger || "",
            trigger_date: x.trigger_date || "",
            trigger_type: x.trigger_type || "event",
            fromAI: true,
          }));
          payment.parsedFromNL = true;
          if (!silent) toast(`已解析 ${payment.installments.length} 期（已基于签署日期展开为绝对日期）`, "ok");
        }
        if (!silent) {
          (data.notes || []).forEach(n => toast(n, "warn", 4500));
        }
      } catch (e) {
        if (!silent) toast(String(e.message || e), "error");
      } finally { parsing.value = false; }
    }
    function addInst() {
      payment.installments.push({
        seq: payment.installments.length + 1, amount: null, trigger: "", trigger_type: "event"
      });
    }
    function delInst(i) {
      payment.installments.splice(i, 1);
      payment.installments.forEach((x, j) => x.seq = j + 1);
      payment.parsedFromNL = false;   // 手动改动后不再是单纯解析结果
    }
    function resetInst() {
      payment.installments = [];
      payment.parsedFromNL = false;
    }
    const instSum = computed(() => payment.installments.reduce((s, x) => s + (parseInt(x.amount) || 0), 0));
    const instOk = computed(() =>
      payment.installments.length > 0 &&
      instSum.value === total.value && total.value > 0 &&
      payment.installments.every(x => (parseInt(x.amount) || 0) > 0 && (x.trigger || "").trim())
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
      const p = payment;
      if (p.mode === "default") {
        if (c.car_default) {
          if (!(p.deposit_amount > 0)) m.push("订金金额");
          if (!p.deposit_date) m.push("订金支付日期");
          if (!p.balance_date) m.push("尾款支付日期");
        } else {
          ["pay1", "pay2", "pay3"].forEach((k, i) => {
            if (!(p[k] > 0)) m.push(c.default_pay_fields[i].label);
          });
        }
      } else if (p.mode === "one_time") {
        if (!p.pay_date && !String(p.pay_event || "").trim()) m.push("一次性支付日期或条件");
      } else {
        if (!instOk.value) m.push("自定义分期（期数/金额/条件完整且合计=总费用）");
      }
      return m;
    });
    const defaultSumOk = computed(() => {
      const p = payment;
      if (cfg.value && cfg.value.car_default) return true;
      const s = ["pay1", "pay2", "pay3"].reduce((a, k) => a + (parseInt(p[k]) || 0), 0);
      return total.value > 0 && s === total.value;
    });
    const canGenerate = computed(() => missing.value.length === 0 && defaultSumOk.value && (payment.mode !== "custom" || instOk.value));

    /* ---------- 生成 ---------- */
    async function generate() {
      generating.value = true;
      try {
        const payload = {
          type: selected.type,
          form: JSON.parse(JSON.stringify(form)),
          payment: {
            mode: payment.mode,
            deposit_amount: parseInt(payment.deposit_amount) || null,
            deposit_date: payment.deposit_date || null,
            balance_date: payment.balance_date || null,
            choice: payment.mode === "one_time" ? payment.one_choice : payment.choice,
            pay1: parseInt(payment.pay1) || null,
            pay2: parseInt(payment.pay2) || null,
            pay3: parseInt(payment.pay3) || null,
            pay_date: payment.pay_date || null,
            pay_event: payment.pay_event || null,
            installments: payment.installments.map(x => ({
              seq: x.seq, amount: parseInt(x.amount), trigger: x.trigger, trigger_type: x.trigger_type
            })),
            source_text: payment.customText || null,
          },
        };
        const r = await fetch("/api/generate", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "生成失败");
        result.value = data;
        await nextTick();
        resultBox.value?.scrollIntoView({ behavior: "smooth", block: "start" });
        if (data.ok) toast(`合同 ${data.no} 生成并核对通过`, "ok", 3500);
        else toast("生成完成，但核对未通过，请查看问题清单", "error", 4000);
      } catch (e) {
        toast(String(e.message || e), "error");
      } finally { generating.value = false; }
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
    function choiceLabel(v) { return v === "较早者" ? "以较早者为准" : "以较晚者为准"; }

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
    // 各业务类型的简短说明(用于粤 Z 新办的引导说明)
    const TYPE_HINT = {
      new_port: "新办流程：①签约交资料 → ②省厅审批获编号 → ③制铁牌 → ④激活通关；四阶段对应三期付款节奏。",
      transfer_gx: "高新过户：客户已持有高新指标，本次仅办理两地牌主体变更(港→港)手续。",
      transfer_ns: "纳税过户：客户需把两地牌过户至另一家香港公司及对应的内地公司(港+内地双变更)。",
      car: "卖车：甲方(卖方)将车辆卖给乙方(买方),双方按合约条款完成产权转移及款项交收。",
    };
    const typeHint = computed(() => TYPE_HINT[selected.type] || "");

    return {
      types, currencies, selected, form, aiFilled, nlText, extractNotes,
      extracting, parsing, generating, result, historyOpen, historyItems, resultBox, elapsed,
      cfg, currencyLabel, totalKey, total, payment, menu, isActive,
      selectMenu, runExtract, parseCustom, addInst, delInst, resetInst, instSum, instOk,
      missing, defaultSumOk, canGenerate, generate, download,
      openHistory, historyDownload, toCN, commas, SEQ_CN,
      fieldCls, fmtDate, choiceLabel, todayISO,
      nlPlaceholder, templateName, typeHint,
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
      <div class="side-foot">
        切换业务类型<br/>将自动重置表单
      </div>
    </aside>

    <!-- ================= 主区 ================= -->
    <section class="main">
      <header class="topbar">
        <div class="crumb">
          {{ cfg?.label || '华星智能合同' }}
          <span class="meta" v-if="cfg">
            · 客户方：{{ cfg.client_side }}
            <template v-if="form.port"> · 口岸：{{ form.port }}</template>
          </span>
        </div>
        <div class="topbar-form" v-if="cfg">
          <div class="bit">
            <label>合约编号</label>
            <input class="ctrl" v-model="form.agreement_no" placeholder="留空自动生成"/>
          </div>
          <div class="bit">
            <label>签署日期</label>
            <input class="ctrl" type="date" v-model="form.sign_date"/>
          </div>
        </div>
        <div class="spacer"></div>
        <div class="meta-pill" v-if="templateName">模板 <b>{{ templateName }}</b></div>
        <div class="meta-pill">币种 <b>{{ currencyLabel(form.currency) }}</b></div>
        <div class="meta-pill">总费用 <b>{{ commas(total) }}</b></div>
        <button class="btn ghost" @click="openHistory">生成历史</button>
      </header>

      <div class="scroll">
        <!-- ===== 智能录入 ===== -->
        <div class="card">
          <div class="card-head">
            <h3>智能录入</h3>
            <span class="lead">一段话描述本单业务，AI 自动回填到下方表单（高亮字段=AI 提取）；解析后仍可任意修改</span>
          </div>
          <div class="card-body">
            <div class="type-hint" v-if="typeHint">
              <span class="dot"></span>{{ typeHint }}
            </div>
            <div class="nl-box">
              <textarea class="ctrl" v-model="nlText" :placeholder="nlPlaceholder()"></textarea>
              <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                <button class="btn primary" :disabled="extracting" @click="runExtract">
                  <span v-if="extracting" class="spin"></span>
                  {{ extracting ? 'AI 提取中…' : 'AI 提取并回填' }}
                </button>
                <span v-if="extracting" class="muted" style="font-size:12px;color:#8a8276">
                  AI 正在理解（已等 {{ elapsed.extract }} 秒，请勿重复点击）
                </span>
              </div>
              <div class="notes" v-if="extractNotes.length">
                <div v-for="(n, i) in extractNotes" :key="i" class="note info">{{ n }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== 业务字段 ===== -->
        <div class="card" v-if="cfg" v-for="g in cfg.groups" :key="g.title">
          <div class="card-head">
            <h3>{{ g.title }}</h3>
          </div>
          <div class="card-body">
            <div class="field-grid">
              <div class="field" v-for="f in g.fields" :key="f.key">
                <label>
                  {{ f.label }}
                  <span class="req" v-if="f.required && !f.auto">*</span>
                  <span class="ai-tag" v-if="!f.auto && aiFilled[f.key]">AI</span>
                </label>
                <input v-if="f.auto" class="ctrl" :value="f.auto" disabled/>
                <select v-else-if="f.type==='select'"
                        class="ctrl" :class="fieldCls(f.key)"
                        v-model="form[f.key]">
                  <option value="" disabled>请选择</option>
                  <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                </select>
                <input v-else class="ctrl" :class="fieldCls(f.key)"
                       v-model="form[f.key]" :placeholder="f.label"/>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== 费用 ===== -->
        <div class="card" v-if="cfg">
          <div class="card-head">
            <h3>费用信息</h3>
            <span class="lead">合计：<b style="color:#b04a3e;font-family:'Noto Serif SC',serif;font-size:16px;letter-spacing:1px">
              {{ currencyLabel(form.currency) }} {{ commas(total) }}
            </b></span>
          </div>
          <div class="card-body">
            <div class="field-grid">
              <div class="field" v-for="f in cfg.fee_fields" :key="f.key">
                <label>
                  {{ f.label }}
                  <span class="req" v-if="f.required">*</span>
                  <span class="ai-tag" v-if="aiFilled[f.key]">AI</span>
                </label>
                <input class="ctrl" type="number" min="0" step="1000"
                       :class="fieldCls(f.key)"
                       v-model.number="form[f.key]"
                       placeholder="请输入金额"/>
                <div v-if="form[f.key] > 0" style="font-size:11.5px;color:#3d5e44;margin-top:-2px">
                  {{ toCN(form[f.key]) }}（{{ currencyLabel(form.currency) }} {{ commas(form[f.key]) }}）
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== 付款计划 ===== -->
        <div class="card" v-if="cfg">
          <div class="card-head">
            <h3>付款计划</h3>
            <span class="lead">总费用 = {{ currencyLabel(form.currency) }} {{ commas(total) }}（{{ toCN(total) }}）</span>
          </div>
          <div class="card-body">
            <div class="pay-tabs">
              <button :class="{on: payment.mode==='default'}" @click="payment.mode='default'">按合同默认</button>
              <button :class="{on: payment.mode==='one_time'}" @click="payment.mode='one_time'">一次性付清</button>
              <button :class="{on: payment.mode==='custom'}" @click="payment.mode='custom'">自定义分期</button>
            </div>

            <!-- 默认模式 -->
            <div v-if="payment.mode==='default'">
              <p class="pay-mode-desc">
                <template v-if="cfg.car_default">
                  按车辆买卖模板：订金 + 尾款两段式支付。请填写订金金额与日期、尾款日期。
                </template>
                <template v-else>
                  按合同模板的三期付款。请填写每期金额，合计须等于总费用。
                </template>
              </p>

              <div v-if="cfg.car_default" class="field-grid">
                <div class="field">
                  <label>订金金额 <span class="req">*</span></label>
                  <input class="ctrl" type="number" min="1" step="1000"
                         :class="{'is-filled': payment.deposit_amount > 0, 'is-missing': !(payment.deposit_amount > 0)}"
                         v-model.number="payment.deposit_amount"/>
                </div>
                <div class="field">
                  <label>订金支付日期 <span class="req">*</span></label>
                  <input class="ctrl" type="date"
                         :class="{'is-filled': !!payment.deposit_date, 'is-missing': !payment.deposit_date}"
                         v-model="payment.deposit_date"/>
                </div>
                <div class="field">
                  <label>尾款支付日期 <span class="req">*</span></label>
                  <input class="ctrl" type="date"
                         :class="{'is-filled': !!payment.balance_date, 'is-missing': !payment.balance_date}"
                         v-model="payment.balance_date"/>
                </div>
                <div class="field">
                  <label>日期与过户日以何者为准 <span class="req">*</span></label>
                  <select class="ctrl" v-model="payment.choice">
                    <option value="较早者">较早者</option>
                    <option value="较晚者">较晚者</option>
                  </select>
                </div>
                <div class="field full" v-if="payment.deposit_amount > 0 && total > 0">
                  <div class="sum-line ok">
                    尾款 = <span class="big">{{ currencyLabel(form.currency) }} {{ commas(total - payment.deposit_amount) }}</span>
                    <span style="margin-left:10px;color:#8a8276;font-size:12px">
                      （{{ toCN(total - payment.deposit_amount) }}）
                    </span>
                  </div>
                </div>
              </div>

              <div v-else class="field-grid">
                <div class="field" v-for="f in cfg.default_pay_fields" :key="f.key">
                  <label>{{ f.label }} <span class="req">*</span></label>
                  <input class="ctrl" type="number" min="1" step="1000"
                         :class="{'is-filled': payment[f.key] > 0, 'is-missing': !(payment[f.key] > 0)}"
                         v-model.number="payment[f.key]"/>
                </div>
                <div class="field full">
                  <div v-if="total === 0" class="sum-line">
                    <span style="color:#8a8276">请先在上方「费用信息」填写总费用</span>
                  </div>
                  <div v-else-if="defaultSumOk" class="sum-line ok">
                    三期合计 <span class="big">= 总费用</span> ✔
                    <span style="margin-left:10px;color:#8a8276;font-size:12px">
                      当前合计 {{ commas(total) }}（{{ toCN(total) }}）
                    </span>
                  </div>
                  <div v-else class="sum-line bad">
                    三期合计须等于总费用：当前 <b style="color:#b04a3e">{{ commas((payment.pay1||0)+(payment.pay2||0)+(payment.pay3||0)) }}</b>
                    <span style="margin:0 6px">/</span> 需 <b style="color:#b04a3e">{{ commas(total) }}</b>
                  </div>
                </div>
              </div>
            </div>

            <!-- 一次性付清 -->
            <div v-if="payment.mode==='one_time'">
              <p class="pay-mode-desc">
                一次性支付全部 {{ currencyLabel(form.currency) }} {{ commas(total) }}（{{ toCN(total) }}）。可指定日期，也可描述事件条件，二者并存时取所选项。
              </p>
              <div class="pay-oneline">
                <div class="field">
                  <label>支付日期</label>
                  <input class="ctrl" type="date"
                         :class="{'is-filled': !!payment.pay_date}"
                         v-model="payment.pay_date"/>
                </div>
                <div class="field" v-if="cfg.car_default">
                  <label>日期与事件以何者为准</label>
                  <select class="ctrl" v-model="payment.one_choice">
                    <option value="较早者">较早者</option>
                    <option value="较晚者">较晚者</option>
                  </select>
                </div>
                <div class="field full">
                  <label>或事件条件（可与日期并存）</label>
                  <input class="ctrl" v-model="payment.pay_event"
                         placeholder="如：车辆完成香港运输署过户登记手续当日"/>
                </div>
              </div>
            </div>

            <!-- 自定义分期 -->
            <div v-if="payment.mode==='custom'">
              <p class="pay-mode-desc">
                用自然语言描述分期约定，AI 将解析为分期表；解析后可在表格中直接调整金额、条件或类型。
              </p>

              <!-- 解析摘要 -->
              <div class="parse-summary" v-if="payment.parsedRaw">
                <div>
                  <span style="color:#1d3a2f;font-weight:600">📜 原文</span>
                  <span style="color:#8a8276;margin-left:6px;font-size:11.5px">（已由 AI 解析，可点击「重新解析」刷新）</span>
                </div>
                <div class="src">{{ payment.parsedRaw }}</div>
                <div v-if="payment.parsedFromNL" style="margin-top:8px;font-size:12px;color:#3d5e44">
                  ✓ 共解析出 <b style="color:#1d3a2f">{{ payment.installments.length }} 期</b>，
                  合计 {{ currencyLabel(form.currency) }} {{ commas(instSum) }}（{{ toCN(instSum) }}）
                </div>
              </div>

              <div class="nl-box">
                <textarea class="ctrl" v-model="payment.customText" rows="2"
                  placeholder="示例：分五期，每期合同金额五分之一，签完下个月起每月 10 号付一期；最后一期于车辆过户完成后支付。"></textarea>
                <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                  <button class="btn primary" :disabled="parsing" @click="parseCustom">
                    <span v-if="parsing" class="spin"></span>
                    {{ parsing ? 'AI 解析中…' : 'AI 解析付款约定' }}
                  </button>
                  <button class="btn" @click="addInst">手动加一期</button>
                  <button class="btn ghost" v-if="payment.installments.length" @click="resetInst">清空分期</button>
                  <span v-if="parsing" style="font-size:12px;color:#8a8276">
                    解析中（已等 {{ elapsed.parse }} 秒）
                  </span>
                  <span v-else-if="payment.installments.length" style="font-size:12.5px;color:#8a8276">
                    合计 <b :style="{color: instSum===total?'#4f8a5b':'#c75a3e'}">
                      {{ currencyLabel(form.currency) }} {{ commas(instSum) }}
                    </b>
                    / 总费用 {{ commas(total) }}
                  </span>
                </div>
              </div>

              <!-- 分期表 -->
              <div v-if="payment.installments.length" style="margin-top:14px;overflow-x:auto">
                <table class="pay-table">
                  <thead>
                    <tr>
                      <th style="width:80px">期数</th>
                      <th style="width:200px">金额</th>
                      <th>付款条件（日期 / 事件 / 混合）</th>
                      <th style="width:120px">类型</th>
                      <th style="width:80px">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(it, idx) in payment.installments" :key="idx">
                      <td class="seq">
                        第 {{ SEQ_CN(it.seq) }} 期
                        <span v-if="it.fromAI" class="ai-tag" style="margin-left:6px;font-size:9.5px;vertical-align:middle">AI</span>
                      </td>
                      <td>
                        <input class="ctrl" type="number" min="1" step="1000"
                               :class="{'is-filled': it.amount > 0, 'is-missing': !(it.amount > 0), 'is-ai': it.fromAI}"
                               v-model.number="it.amount"
                               @input="it.fromAI = false"/>
                      </td>
                      <td>
                        <input class="ctrl" v-model="it.trigger"
                               :class="{'is-filled': !!it.trigger.trim(), 'is-missing': !it.trigger.trim(), 'is-ai': it.fromAI}"
                               :placeholder="'如：签约当日 / 2026年10月10日 / 完成股权转让后3日内'"
                               @input="it.fromAI = false"/>
                        <div v-if="it.trigger_date" class="trigger-date" :title="'AI 基于签署日期推算的绝对日期'">
                          📅 {{ it.trigger_date }}
                        </div>
                      </td>
                      <td>
                        <select class="ctrl" v-model="it.trigger_type" @change="it.fromAI = false">
                          <option value="date">日期</option>
                          <option value="event">事件</option>
                          <option value="mixed">混合</option>
                        </select>
                      </td>
                      <td>
                        <button class="btn ghost sm" @click="delInst(idx)">删除</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- 合计校验 -->
              <div v-if="payment.installments.length" style="margin-top:14px">
                <div v-if="total === 0" class="sum-line">
                  <span style="color:#8a8276">请先在上方「费用信息」填写总费用</span>
                </div>
                <div v-else-if="instOk" class="sum-line ok">
                  分期合计 <span class="big">= 总费用</span> ✔
                  <span style="margin-left:10px;color:#8a8276;font-size:12px">
                    共 {{ payment.installments.length }} 期 · {{ commas(instSum) }}（{{ toCN(instSum) }}）
                  </span>
                </div>
                <div v-else class="sum-line bad">
                  <div>分期需满足：每期金额 &gt; 0、付款条件不为空、各期合计 = 总费用</div>
                  <div style="margin-top:4px;font-size:12px">
                    当前合计 <b style="color:#b04a3e">{{ currencyLabel(form.currency) }} {{ commas(instSum) }}</b>
                    <span style="margin:0 6px">/</span> 需 <b style="color:#b04a3e">{{ commas(total) }}</b>
                  </div>
                </div>
              </div>
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

      <!-- ===== 底部操作栏（固定） ===== -->
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
    <div class="toast-wrap">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">{{ t.msg }}</div>
    </div>
  </div>
  `,
});

app.mount("#app");