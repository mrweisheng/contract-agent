/* 华星智能合同生成系统 · 双栏工作台（方案 E）
 * 布局：墨绿侧栏 | 录入核对栏 | 合同实时预览栏
 * 预览：POST /api/preview → 真实 docx 字节 → docx-preview 渲染——所见即下载所得
 * 字段三态：待填红 / AI 金底未核（点一下标记已核）/ 已填中性
 */
import "/vendor/vue.global.prod.js";
const { createApp, reactive, ref, computed, watch, onMounted } = window.Vue;
if (import.meta.env?.DEV) import("/workbench.css");

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
    const extraShown = reactive({});   // 「提到才显示」组：已显示字段 key 集合（客户在旁边看屏幕，没提到的不渲染）
    const extraFoldOpen = ref(false);  // 未提及字段折叠条展开态（默认合上，不暴露字段名）
    const nlText = ref("");
    const extractNotes = ref([]);
    const warnNotes = ref([]);
    const extracting = ref(false);
    const parsing = ref(false);
    const generating = ref(false);
    const notesModal = ref(false);
    const resultModal = ref(false);
    const result = ref(null);
    const historyOpen = ref(false);
    const historyItems = ref([]);
    const elapsed = reactive({ gen: 0 });
    setInterval(() => {
      if (generating.value) elapsed.gen++; else elapsed.gen = 0;
    }, 1000);
    // 录入管线阶段（内联在智能录入卡内，不再全屏遮罩）
    const pipe = reactive({ extract: "", pay: "" });

    /* ---------- 在途请求管理（切换业务类型作废旧响应） ---------- */
    let reqGen = 0;
    const pendingCtrls = new Set();
    function cancelPending() {
      reqGen += 1;
      pendingCtrls.forEach(c => c.abort());
      pendingCtrls.clear();
      extracting.value = false;
      parsing.value = false;
      generating.value = false;  // 切换类型作废在途生成：被 abort 的 generate 走 AbortError 提前 return，不会自复位，必须在这里复位
      pipe.extract = ""; pipe.pay = "";
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

    const payment = reactive({ rows: [], customText: "" });
    const payNotes = ref([]);

    const cfg = computed(() => types.value.find(t => t.key === selected.type) || null);
    const currencyLabel = c => ({ HKD: "港币 HK$", CNY: "人民币 ¥" }[c] || c);
    const totalKey = computed(() => selected.type === "car" ? "total_price" : "total_fee");
    const total = computed(() => parseInt(form[totalKey.value]) || 0);
    const paneKey = computed(() => selected.type + "|" + selected.port);  // 切换业务时录入栏淡出淡入

    /* ---------- 侧栏导航 ---------- */
    const menu = computed(() => {
      const get = k => types.value.find(t => t.key === k);
      const items = [];
      if (get("car")) items.push({ title: "车辆买卖", list: [{ key: "car", port: "", label: "车务" }] });
      if (get("transfer_gx") && get("transfer_ns")) items.push({
        title: "现牌过户", list: [
          { key: "transfer_gx", port: "", label: "高新现牌" },
          { key: "transfer_ns", port: "", label: "纳税现牌" },
        ]
      });
      const np = get("new_port");
      if (np && np.ports) items.push({
        title: "粤 Z 新办", list: np.ports.map(p => ({ key: "new_port", port: p, label: p.replace("口岸", "").replace("大桥", "") }))
      });
      return items;
    });
    const isActive = it => selected.type === it.key && selected.port === it.port;

    function initForm() {
      Object.keys(form).forEach(k => delete form[k]);
      Object.keys(aiFilled).forEach(k => delete aiFilled[k]);
      Object.keys(extraShown).forEach(k => delete extraShown[k]);  // 换类型清显隐集合
      extraFoldOpen.value = false;
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
          lockDate: !!(p.dated && !p.event && !cfg.value?.car_default),
        };
      });
    }
    function initPayment() {
      payment.rows = mkPresetRows(() => ({ amount: null, date: "", label: "" }));
      payment.customText = "";
      payNotes.value = [];
    }
    function selectMenu(it) {
      if (isActive(it)) return;
      cancelPending();
      selected.type = it.key; selected.port = it.port;
      result.value = null; extractNotes.value = []; warnNotes.value = [];
      nlText.value = "";  // 不残留上一类型的业务描述，避免误点 AI 提取按新类型抽旧文本
      initForm(); initPayment();
      clearTimeout(pvHitTimer); clearPvHit(); pvHit = null;  // 切类型清联动：旧 key 在新锚点表里语义已失效
      schedulePreview(30, true);
    }

    /* ---------- 字段三态 ---------- */
    function fieldState(f) {
      if (f.auto) return "auto";
      const v = String(form[f.key] ?? "").trim();
      if (aiFilled[f.key]) return v ? "ai" : "miss";
      if (f.required && !v) return "miss";
      return v ? "done" : "";
    }
    // 用户改动即视为已核对：清 AI 未核标记（修 badge 永不清除的老 bug）
    function onFieldInput(key) { delete aiFilled[key]; }
    function confirmAI(key) { delete aiFilled[key]; }

    /* ---------- 提到才显示（reveal:on_fill 组的字段级显隐）----------
     * 场景：录入时客户在旁边看屏幕。没提到的可选字段整行不渲染（含 AI 回填的显式默认值，
     * 「不赠送/不承诺/不含」＝没提到），只留一行不含字段名的中性折叠条。
     * 显隐集合只在「AI 提取完成」和「字段失焦」两个时刻重算——编辑中搬家会重挂载
     * 输入框，打断焦点与中文输入法，所以值变化本身不触发搬家。 */
    const extraGroup = computed(() => (cfg.value?.groups || []).find(g => g.reveal === "on_fill") || null);
    const extraShownList = computed(() => (extraGroup.value?.fields || []).filter(f => extraShown[f.key]));
    const extraFoldList = computed(() => (extraGroup.value?.fields || []).filter(f => !extraShown[f.key]));
    function extraMentioned(f) {
      const v = String(form[f.key] ?? "").trim();
      return !!v && v !== String(f.default ?? "").trim();
    }
    function syncExtraShown() {
      (extraGroup.value?.fields || []).forEach(f => {
        if (extraMentioned(f)) extraShown[f.key] = true;
        else delete extraShown[f.key];
      });
    }
    function toggleExtraFold() { extraFoldOpen.value = !extraFoldOpen.value; }

    /* ---------- 智能抽取 ---------- */
    async function runExtract() {
      if (nlText.value.trim().length < 5) { toast("请先输入业务描述", "warn"); return; }
      extracting.value = true; extractNotes.value = []; warnNotes.value = [];
      result.value = null;
      pipe.extract = "run"; pipe.pay = "";
      const raw = nlText.value.trim();
      const myGen = reqGen;
      const payPromise = /付|款|分期|订金|定金|尾款/.test(raw) ? (pipe.pay = "run", parseCustomText(raw, true)) : null;
      try {
        const data = await postJSON("/api/extract", { type: selected.type, text: raw });
        if (myGen !== reqGen) return;
        Object.entries(data.fields || {}).forEach(([k, v]) => {
          if (v === null || v === undefined) return;
          if (k === "quota_type") return;
          form[k] = v; aiFilled[k] = true;
        });
        syncExtraShown();               // 提取完重算显隐：只亮提到的字段
        extraFoldOpen.value = false;    // 折叠条保持合上，未提及项继续隐藏
        if (data.currency && ["HKD", "CNY"].includes(data.currency)) {
          form.currency = data.currency; aiFilled.currency = true;
        }
        if (data.total) { form[totalKey.value] = data.total; aiFilled[totalKey.value] = true; }
        if (data.payment_text) {
          payment.customText = data.payment_text;
          extractNotes.value.push("已自动解析付款约定为分期表，请核对金额与条件");
          if (!payPromise) {
            pipe.pay = "run";
            pipe.pay = (await parseCustomText(data.payment_text, true)) ? "done" : "fail";
          }
        }
        (data.notes || []).forEach(n => { extractNotes.value.push(n); warnNotes.value.push(n); });
        toast("已回填表单，金色字段请逐一核对", "ok");
      } catch (e) {
        if (e.name === "AbortError") return;
        toast(String(e.message || e), "error");
        pipe.extract = "fail";
      } finally {
        extracting.value = false;
        if (myGen === reqGen && pipe.extract === "run") pipe.extract = "done";
      }
      if (myGen !== reqGen) return;
      if (payPromise) pipe.pay = (await payPromise) ? "done" : "fail";
      if ([...warnNotes.value, ...payNotes.value].length) notesModal.value = true;
    }

    /* ---------- 付款解析 ---------- */
    async function parseCustomText(t, silent = false) {
      t = (t || "").trim();
      if (t.length < 3) { if (!silent) toast("请先填写付款约定的自然语言描述", "warn"); return false; }
      parsing.value = true;
      payNotes.value = [];
      result.value = null;
      const myGen = reqGen;
      try {
        const data = await postJSON("/api/parse-payment", {
          type: selected.type,
          currency: form.currency,
          total: total.value,
          text: t,
          sign_date: form.sign_date || "",
        });
        if (myGen !== reqGen) return false;
        const c = cfg.value?.pay_preset || [];
        const inst = data.installments || [];
        if (data.matches_preset && inst.length === c.length) {
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
            amount: x.amount === null || x.amount === undefined ? null : parseInt(x.amount),
            date: x.trigger_date || "",
            event: x.trigger || "",
            lockDate: false,
          }));
          if (!silent) toast(`已按客户约定解析出 ${payment.rows.length} 期付款计划，请核对`, "ok");
        }
        (data.notes || []).forEach(n => {
          payNotes.value.push(n);
          if (!silent) toast(n, "warn", 4500);
        });
        return true;
      } catch (e) {
        if (e.name === "AbortError") return false;
        if (!silent) toast(String(e.message || e), "error");
        else {
          const msg = `付款约定自动解析未成功：${e.message || e}，请在付款计划中手动填写`;
          extractNotes.value.push(msg); warnNotes.value.push(msg);
        }
        return false;
      } finally {
        if (myGen === reqGen) { parsing.value = false; if (pipe.pay === "run") pipe.pay = "done"; }
      }
    }
    function addRow() {
      const row = { seq: 1, label: "", amount: null, date: "", event: "", lockDate: false };
      // 「尾款」语义上永远是最后一期：新加的一期插到它前面（倒数第二）
      const last = payment.rows[payment.rows.length - 1];
      if (last && (last.label || "").trim() === "尾款") {
        payment.rows.splice(payment.rows.length - 1, 0, row);
      } else {
        payment.rows.push(row);
      }
      payment.rows.forEach((r, j) => r.seq = j + 1);
      schedulePreview();
    }
    function delRow(i) {
      payment.rows.splice(i, 1);
      payment.rows.forEach((r, j) => r.seq = j + 1);
    }
    function resetPayRows() { initPayment(); schedulePreview(0); }
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

    /* ---------- 完整性 ---------- */
    const missing = computed(() => {
      const m = [];
      const c = cfg.value;
      if (!c) return m;
      c.groups.forEach(g => g.fields.forEach(f => {
        if (!f.required || f.auto) return;
        if (!String(form[f.key] ?? "").trim()) m.push({ key: f.key, label: f.label });
      }));
      c.fee_fields.forEach(f => {
        if (f.required && !form[f.key]) m.push({ key: f.key, label: f.label });
      });
      if (c.port_required && !form.port) m.push({ key: "port", label: "口岸" });
      return m;
    });
    const missingTotal = computed(() => missing.value.length + (payOk.value ? 0 : 1));
    const canGenerate = computed(() => missingTotal.value === 0);
    function jumpMissing() {
      const first = missing.value[0];
      if (!first) return;
      const el = document.getElementById("f-" + first.key);
      if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.focus(); }
    }

    /* ---------- 实时 1:1 预览 ---------- */
    const pvState = ref("idle");   // idle | loading | ready | error
    const pvError = ref("");
    const pvIssues = ref([]);
    const pvIssuesOpen = ref(false);
    const pvHasContent = ref(false);   // 是否已有渲染内容：决定加载占位是否覆盖（有旧内容时保留旧合同）
    const sheetEl = ref(null);
    const pvScroll = ref(null);
    let pvTimer = null, pvCtrl = null, pvSeq = 0, pvFresh = false;
    function rowPayload(r) {
      return {
        label: (r.label || "").trim(),
        amount: r.amount === "" || r.amount === null || r.amount === undefined || Number.isNaN(r.amount)
          ? null : r.amount,
        date: (r.lockDate ? form.sign_date : r.date) || null,
        event: (r.event || "").trim(),
      };
    }
    function schedulePreview(delay = 450, fresh = false) {
      if (fresh) pvFresh = true;
      else if (pvFresh) return;   // 已有待执行的「切换类型」预览：忽略同批增量重排，避免把它的短延时顶掉
      clearTimeout(pvTimer);
      pvTimer = setTimeout(renderPreview, delay);
    }
    async function renderPreview() {
      const fresh = pvFresh; pvFresh = false;   // 先消费 fresh，避免早退（docx 未就绪）时护栏把后续预览全部吞掉
      if (!cfg.value || !window.docx) return;
      const mySeq = ++pvSeq;
      if (pvCtrl) pvCtrl.abort();
      pvCtrl = new AbortController();
      pvState.value = "loading";
      if (fresh) {
        // 切换业务类型：立即清空并回到顶部，避免残留上一类型合同造成"整页瞬切"
        pvHasContent.value = false;
        pvIssues.value = [];
        if (sheetEl.value) sheetEl.value.innerHTML = "";
        if (pvScroll.value) pvScroll.value.scrollTop = 0;
      }
      try {
        const r = await fetch("/api/preview", {
          method: "POST", headers: { "Content-Type": "application/json" },
          signal: pvCtrl.signal,
          body: JSON.stringify({
            type: selected.type,
            form: JSON.parse(JSON.stringify(form)),
            payment: { installments: payment.rows.map(rowPayload), source_text: payment.customText || null },
          }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) {
          if (mySeq === pvSeq) { pvState.value = "error"; pvError.value = d.detail || `预览失败（HTTP ${r.status}）`; pvIssues.value = []; }
          return;
        }
        const bin = atob(d.docx_b64);
        const buf = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        if (mySeq !== pvSeq || !sheetEl.value) return;
        // 双缓冲：渲进离屏容器，完成后同帧整体换入——旧纸面（含联动高亮）保持可见
        // 到换入那一刻，编辑打字不再出现「清空白屏→重渲→淡入」的闪烁
        const savedTop = pvScroll.value ? pvScroll.value.scrollTop : 0;
        const stage = document.createElement("div");
        await window.docx.renderAsync(buf, stage, null,
          { inWrapper: true, breakPages: true });
        if (mySeq !== pvSeq || !sheetEl.value) return;  // 渲染期间又有新请求：整张丢弃
        sheetEl.value.replaceChildren(...Array.from(stage.childNodes));
        if (fresh) {
          // 整页换新（切业务类型）才淡入；增量重渲不播动画
          const el = sheetEl.value;
          el.style.transition = "none";
          el.style.opacity = "0";
          void el.offsetHeight;
          el.style.transition = "opacity .28s ease";
          el.style.opacity = "1";
        }
        if (pvScroll.value) pvScroll.value.scrollTop = savedTop;
        pvState.value = "ready";
        pvHasContent.value = true;
        pvIssues.value = d.draft_issues || [];
        if (pvHit) applyPvHit(false);   // 重渲后 DOM 重建：重贴水洗并重新校准光环位置，巡游不中断
      } catch (e) {
        if (e.name === "AbortError") return;
        if (mySeq === pvSeq) { pvState.value = "error"; pvError.value = String(e.message || e); pvIssues.value = []; }
      }
    }
    watch(form, () => schedulePreview(), { deep: true });
    watch(() => payment.rows, () => schedulePreview(), { deep: true });

    /* ---------- 字段聚焦 → 预览联动定位 ----------
     * 结构定位（表格锚文本+行标签子串+列号，或段落子串），不用值匹配——
     * 金额在合同里是「港币（大写）零元整（HK$0）」，拿表单原值搜文本必失败。
     * 锚点配置在 server/engine/types_config.py field_anchors，经 /api/types 下发。
     * 生命周期为「激活信号」驱动（focusin / pointerdown / 日期 change 均可激活）：
     * 焦点仍在字段内就一直保持，移到非字段区域后缓冲 PV_HIT_HIDE_MS 再隐藏，无硬超时。 */
    const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
    let pvHit = null;            // { key, cardIdx?, pfield? } 当前联动字段
    let pvHitTimer = null;
    let pvBeacon = null;         // 巡游光环覆盖层（单例，重渲不销毁，动效无缝连续）
    const PV_HIT_HIDE_MS = 1800; // 焦点移出联动字段后的隐藏缓冲
    const isoOk = s => /^\d{4}-\d{2}-\d{2}$/.test(String(s || "")) && !Number.isNaN(Date.parse(s));

    // 当前分期表对应的服务端付款模式（与 builder.derive_payment 同口径，仅用于算行号）
    function payModeNow() {
      const rows = payment.rows, preset = cfg.value?.pay_preset || [];
      if (rows.length === 1) return "one_time";
      const matched = preset.length > 0 && rows.length === preset.length && rows.every((r, i) => {
        const pe = String(preset[i].event || "").trim(), ev = String(r.event || "").trim();
        if (pe) return ev === pe;
        if (ev && !ev.includes("签约")) return false;
        return isoOk(r.date) || !!ev;
      });
      return matched ? "default" : "custom";
    }

    // 分期卡片 → 费用表行号（0=总费用行；-1=末行）。卖车默认模式错位：
    // 订金金额→行1、订金支付日期→行2、尾款→末行（购车尾款）；其余模式统一 行1+期号
    function installmentRowIdx(idx, pfield) {
      if (payModeNow() === "default" && cfg.value?.car_default) {
        if (idx === 0) return pfield === "date" ? 2 : 1;
        return -1;
      }
      return 1 + idx;
    }

    function resolveAnchor(a, instIdx) {
      const sheet = sheetEl.value;
      if (!sheet || !a) return null;
      const paras = a.para === undefined ? null : (Array.isArray(a.para) ? a.para : [a.para]);
      try {
        if (paras) {
          for (const kw of paras)
            for (const p of sheet.querySelectorAll("p"))
              if ((p.textContent || "").includes(kw)) return p;
          return null;
        }
        for (const t of sheet.querySelectorAll("table")) {
          // 表名/行名都支持数组（如换车费用行名随客户用词在「换车费用/上车费用」间切换）
          const tKeys = Array.isArray(a.table) ? a.table : [a.table];
          if (!tKeys.some(k => (t.textContent || "").includes(k))) continue;
          const rows = t.rows;
          if (instIdx !== undefined)
            return (instIdx === -1 ? rows[rows.length - 1] : rows[instIdx]) || null;
          if (a.row === undefined) return t;   // 无行锚：整表高亮（如签署确认块/换车费用小表）
          const rKeys = Array.isArray(a.row) ? a.row : [a.row];
          for (const tr of rows)
            if (rKeys.some(k => (tr.textContent || "").includes(k)))
              return tr.cells?.[a.col ?? 1] || tr;
          return null;   // 表命中但行不在（条件节未启用等）→ 不再尝试其余表
        }
      } catch { /* docx-preview 结构变化等：静默降级，不影响预览 */ }
      return null;
    }

    function clearPvHit() {
      sheetEl.value?.querySelectorAll(".pv-hit").forEach(el => el.classList.remove("pv-hit"));
      pvBeacon?.classList.add("off");   // 渐隐；元素保留，同字段复用时动效不中断
    }

    // 光环覆盖层定位到锚点元素（内容坐标，随滚动移动）；±3px 外扩让环不贴字
    function pinBeacon(el) {
      const c = pvScroll.value, s = sheetEl.value;
      if (!c || !s) return;
      if (!pvBeacon) {
        pvBeacon = document.createElement("div");
        pvBeacon.className = "pv-beacon";
        c.appendChild(pvBeacon);
      }
      const r = el.getBoundingClientRect(), cr = c.getBoundingClientRect();
      pvBeacon.style.left = (r.left - cr.left + c.scrollLeft - 3) + "px";
      pvBeacon.style.top = (r.top - cr.top + c.scrollTop - 3) + "px";
      pvBeacon.style.width = (r.width + 6) + "px";
      pvBeacon.style.height = (r.height + 6) + "px";
      pvBeacon.classList.remove("off");
    }

    // scroll=定位后滚动到目标；重渲重贴走同一入口，光环位置随新内容重新校准
    function applyPvHit(scroll) {
      clearPvHit();
      if (!pvHit || !cfg.value) return;
      let a = null, instIdx;
      if (pvHit.key === "__inst") {
        a = cfg.value.field_anchors?.installment;
        instIdx = installmentRowIdx(pvHit.cardIdx, pvHit.pfield);
      } else {
        a = cfg.value.field_anchors?.[pvHit.key];
      }
      const el = a && resolveAnchor(a, instIdx);
      if (!el) return;
      el.classList.add("pv-hit");
      pinBeacon(el);
      if (scroll) pvScrollTo(el);
    }

    // 定位滚动：目标未完整可见就滚到垂直居中（签署块等在合同底部，必须保证滚到位）；
    // 已完整可见则不动，靠脉冲引导视线
    function pvScrollTo(el) {
      const c = pvScroll.value;
      if (!c) return;
      const cr = c.getBoundingClientRect(), tr = el.getBoundingClientRect();
      if (tr.top >= cr.top && tr.bottom <= cr.bottom) return;
      const top = c.scrollTop + (tr.top + tr.height / 2 - cr.top) - c.clientHeight / 2;
      c.scrollTo({ top: Math.max(0, top), behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
    }

    // 目标元素 → 联动字段：f-* 输入 / 签署日期条（含「今日」快捷钮）/ 付款卡片内子字段
    function hitFromTarget(t) {
      if (typeof t?.id === "string" && t.id.startsWith("f-"))
        return { key: t.id.slice(2) };
      if (t?.closest?.(".pc-del")) return null;         // 删除按钮不是在编辑字段
      if (t?.closest?.(".sign-bar")) return { key: "sign_date" };
      const card = t?.closest?.(".pay-card");
      if (card) {
        const idx = Array.prototype.indexOf.call(card.parentElement.children, card);
        return { key: "__inst", cardIdx: idx, pfield: t.dataset?.pfield || "" };
      }
      return null;
    }

    const sameHit = (a, b) => !!a && !!b && a.key === b.key && a.cardIdx === b.cardIdx && a.pfield === b.pfield;

    function activateHit(hit, scroll = true) {
      clearTimeout(pvHitTimer);
      // 同一字段且高亮仍在贴：不重播动画、不再滚动
      if (sameHit(pvHit, hit) && sheetEl.value?.querySelector(".pv-hit")) return;
      pvHit = hit;
      applyPvHit(scroll);
    }

    function hideHit() {
      clearTimeout(pvHitTimer);
      pvHitTimer = setTimeout(() => { clearPvHit(); pvHit = null; }, PV_HIT_HIDE_MS);
    }

    function onPaneFocusin(e) {
      const hit = hitFromTarget(e.target);
      if (hit) activateHit(hit);
    }

    function onPaneFocusout(e) {
      // 「提到才显示」搬家时机＝失焦：值非默认→升到显示区，回到默认→折回折叠区
      const key = typeof e.target?.id === "string" && e.target.id.startsWith("f-") ? e.target.id.slice(2) : null;
      if (key && extraGroup.value?.fields.some(f => f.key === key)) syncExtraShown();
      if (!pvHit) return;
      if (e.relatedTarget && hitFromTarget(e.relatedTarget)) return;  // 字段间直切：交给 focusin 重定位
      hideHit();
    }

    // 日期框点日历图标、禁用输入等场景焦点未必落上：pointerdown 兜底激活
    function onPanePointerdown(e) {
      const hit = hitFromTarget(e.target);
      if (hit) activateHit(hit);
    }

    // 日历面板选定日期后，签署块与「签约当日」各期行可能移位：重新定位并滚动
    function onHitDateChange(e) {
      if (sameHit(pvHit, hitFromTarget(e.target))) {
        clearTimeout(pvHitTimer);
        applyPvHit(true);
      }
    }

    // 注意力移到预览区：立即撤联动
    function onPreviewPanePointerdown() {
      if (!pvHit) return;
      clearTimeout(pvHitTimer);
      clearPvHit();
      pvHit = null;
    }

    // 预览是流式排版（最宽 780px）：窗口缩放会让合同重排、锚点移位，重校准光环
    window.addEventListener("resize", () => { if (pvHit) applyPvHit(false); });

    /* ---------- 签署日期 ---------- */
    const isToday = computed(() => form.sign_date === todayISO());
    function setSignToday() { form.sign_date = todayISO(); }

    /* ---------- 生成 ---------- */
    async function generate() {
      generating.value = true;
      const myGen = reqGen;
      try {
        const rows = payment.rows.map(r => ({
          seq: r.seq,
          label: (r.label || "").trim(),
          amount: parseInt(r.amount),
          date: (r.lockDate ? (form.sign_date || null) : (r.date || null)),
          event: (r.event || "").trim(),
        }));
        const data = await postJSON("/api/generate", {
          type: selected.type,
          form: JSON.parse(JSON.stringify(form)),
          payment: { installments: rows, source_text: payment.customText || null },
        });
        if (myGen !== reqGen) return;
        result.value = data;
        // ok 仅代表规则校验通过；LLM 软复核提示存于 warnings，有提示就强制过眼一次弹窗
        if (data.ok && !(data.warnings || []).length) {
          toast(`合同 ${data.no} 生成并核对通过`, "ok", 3500);
        } else {
          toast(data.ok ? `合同 ${data.no} 已生成，但有 ${data.warnings.length} 条复核提示`
                        : "生成完成，但核对未通过，请查看问题清单",
                data.ok ? "warn" : "error", 4000);
          resultModal.value = true;
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        toast(String(e.message || e), "error");
      } finally { if (myGen === reqGen) generating.value = false; }
    }
    function saveAs(url, name) {
      const a = document.createElement("a");
      a.href = url;
      if (name) a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    function download() { if (result.value?.download_url) saveAs(result.value.download_url, result.value.filename); }
    function viewHistoryResult(h) { saveAs(`/api/download/${h.no}`, h.filename); }

    async function openHistory() {
      historyOpen.value = true;
      try {
        const r = await fetch("/api/history");
        if (!r.ok) { toast(`加载历史失败（HTTP ${r.status}）`, "error"); return; }
        const d = await r.json();
        historyItems.value = d.items || [];
      } catch (e) { toast("加载历史失败", "error"); }
    }

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

    const NL_PLACEHOLDERS = {
      car: "示例：客户张三（证件 H1234567，电话 91234567）买车牌 LN1234 的 2022 款丰田 Alphard，VIN WBA…，港币 50 万；当天付订金 10 万，过户完成付尾款。附赠与质保（客户提到才写）：送 4 个月牌费、包过户费、送全保，质保 1 年。",
      transfer_gx: "示例：客户鸿达投资有限公司（证件 91110000MA0000000X，联络人李四，电话 13800001234）委托高新过户车牌 LN1234，目标香港公司 XX 物流有限公司，通行莲塘口岸，服务总费用人民币 30 万；分三期支付，每期 10 万，第一期签约当日付，第二期提交资料后 3 日内付，尾款过户完成后付。",
      transfer_ns: "示例：客户鸿达投资有限公司（证件 91110000MA0000000X，联络人李四，电话 13800001234）委托纳税过户车牌 LN1234，目标香港公司 XX 物流有限公司、目标内地公司 XX 国际货运代理有限公司，通行深圳湾口岸，服务总费用人民币 30 万；分三期支付，每期 10 万。",
      new_port: "示例：客户王五（身份证 440000000000000000，电话 13800001234）通过莲塘口岸新办粤 Z 两地牌，服务总费用人民币 25 万；分三期支付，第一期签约当日付，第二期省厅获编号后 1 个工作日内付，第三期领取铁牌等通关资料时付。",
    };
    function nlPlaceholder() { return NL_PLACEHOLDERS[selected.type] || NL_PLACEHOLDERS.car; }
    const TEMPLATE_NAMES = {
      car: "香港车辆买卖合约",
      transfer_gx: "高新两地牌现牌过户",
      transfer_ns: "纳税两地牌现牌过户（两家公司）",
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
      toasts,
      types, currencies, selected, form, aiFilled, nlText, extractNotes, warnNotes, payNotes, notesModal,
      extraShownList, extraFoldList, extraFoldOpen, toggleExtraFold,
      extracting, parsing, generating, result, resultModal, historyOpen, historyItems, elapsed, pipe,
      cfg, currencyLabel, totalKey, total, payment, menu, isActive, paneKey,
      selectMenu, runExtract, addRow, delRow, resetPayRows, onAmount, paySum, payOk,
      missing, missingTotal, canGenerate, jumpMissing,
      fieldState, onFieldInput, confirmAI,
      pvState, pvError, pvIssues, pvIssuesOpen, pvHasContent, sheetEl, pvScroll, renderPreview,
      onPaneFocusin, onPaneFocusout, onPanePointerdown, onPreviewPanePointerdown, onHitDateChange,
      isToday, setSignToday,
      generate, download, openHistory, viewHistoryResult,
      toCN, commas, SEQ_CN, todayISO, nlPlaceholder, templateName,
    };
  },

  template: /* html */ `
  <div class="app">
    <!-- ================= 侧栏 ================= -->
    <aside class="side">
      <div class="brand">
        <div class="logo">華星</div>
        <div class="sub">CONTRACT · AGENT</div>
      </div>
      <div class="side-scroll">
        <template v-for="g in menu" :key="g.title">
          <div class="side-label">{{ g.title }}</div>
          <div v-for="(it, ii) in g.list" :key="it.key + it.port"
               class="side-item" :class="{active: isActive(it)}" :title="it.label" @click="selectMenu(it)">
            <span class="num">{{ String(ii + 1).padStart(2, '0') }}</span>
            <span>{{ it.label }}</span>
          </div>
        </template>
      </div>
      <div class="side-foot">
        <div class="today-dot"><i></i>{{ todayISO() }}</div>
        <button class="side-btn" @click="openHistory">生成历史</button>
      </div>
    </aside>

    <!-- ================= 录入核对栏 ================= -->
    <section class="pane" @focusin="onPaneFocusin" @focusout="onPaneFocusout" @pointerdown="onPanePointerdown">
      <div class="pane-top">
        <h2>{{ cfg?.label || '华星智能合同' }}</h2>
        <span class="tpl-name" v-if="cfg">{{ templateName }}</span>
      </div>
      <transition name="pfade" mode="out-in">
      <div class="pane-body" :key="paneKey">

        <!-- 智能录入 -->
        <div class="sec">
          <div class="sec-head"><span class="dot"></span>智能录入<span class="sec-hint">粘贴客户沟通原文，AI 自动回填，金色字段需核对</span></div>
          <div class="sec-body">
            <textarea class="nl" v-model="nlText" rows="3" :placeholder="nlPlaceholder()"></textarea>
            <div class="extract-row">
              <button class="btn primary" :disabled="extracting || parsing" @click="runExtract">
                <span v-if="extracting || parsing" class="spin"></span>{{ extracting ? '提取中…' : parsing ? '解析付款中…' : 'AI 提取' }}
              </button>
              <div class="pipeline" :class="{show: extracting || parsing || pipe.extract || pipe.pay}">
                <div class="stage" :class="pipe.extract">{{ {run:'提取字段中…',done:'✓ 字段提取',fail:'✗ 提取失败'}[pipe.extract] || '待提取' }}</div>
                <div class="stage" :class="pipe.pay">{{ {run:'解析付款中…',done:'✓ 付款解析',fail:'✗ 付款解析'}[pipe.pay] || '跳过' }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 合同信息 -->
        <div class="sec" v-if="cfg">
          <div class="sec-head"><span class="dot"></span>合同信息
            <span class="sec-hint">币种 {{ currencyLabel(form.currency) }}</span>
          </div>
          <div class="sec-body">
            <template v-for="g in cfg.groups" :key="g.title">
              <template v-if="g.reveal === 'on_fill'">
                <!-- 提到才显示：只渲染提到的字段；未提及的收进中性折叠条，点开才见内容 -->
                <div class="group-label" v-if="extraShownList.length">{{ g.title }}</div>
                <div class="fields">
                  <div class="field" v-for="f in extraShownList" :key="f.key" :class="fieldState(f)">
                    <label>{{ f.label }}<em v-if="f.required && !f.auto">*</em></label>
                    <input v-if="f.auto" :id="'f-' + f.key" class="f-inp" :value="f.auto" disabled/>
                    <select v-else-if="f.type==='select'" :id="'f-' + f.key" class="f-inp"
                            v-model="form[f.key]" @change="onFieldInput(f.key)">
                      <option value="" disabled>请选择</option>
                      <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <input v-else :id="'f-' + f.key" class="f-inp" v-model="form[f.key]"
                           :placeholder="fieldState(f)==='miss' ? '必填 · 待填' : (f.hint || '待填')"
                           @input="onFieldInput(f.key)"/>
                    <button v-if="aiFilled[f.key] && !f.auto" class="badge ai" title="AI 回填、尚未核对，点此确认"
                            @click="confirmAI(f.key)">AI · 未核</button>
                    <span v-else-if="fieldState(f)==='done' && f.required" class="badge ok">✓</span>
                  </div>
                  <button type="button" class="extra-fold-bar" v-if="extraFoldList.length"
                          @click="toggleExtraFold">{{ extraFoldOpen ? '▾ 收起' : '＋ 附赠与售后（客户提到才填）' }}</button>
                  <div class="field" v-for="f in extraFoldList" :key="'xf-' + f.key"
                       v-show="extraFoldOpen" :class="fieldState(f)">
                    <label>{{ f.label }}<em v-if="f.required && !f.auto">*</em></label>
                    <input v-if="f.auto" :id="'f-' + f.key" class="f-inp" :value="f.auto" disabled/>
                    <select v-else-if="f.type==='select'" :id="'f-' + f.key" class="f-inp"
                            v-model="form[f.key]" @change="onFieldInput(f.key)">
                      <option value="" disabled>请选择</option>
                      <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <input v-else :id="'f-' + f.key" class="f-inp" v-model="form[f.key]"
                           :placeholder="fieldState(f)==='miss' ? '必填 · 待填' : (f.hint || '待填')"
                           @input="onFieldInput(f.key)"/>
                    <button v-if="aiFilled[f.key] && !f.auto" class="badge ai" title="AI 回填、尚未核对，点此确认"
                            @click="confirmAI(f.key)">AI · 未核</button>
                    <span v-else-if="fieldState(f)==='done' && f.required" class="badge ok">✓</span>
                  </div>
                </div>
              </template>
              <template v-else>
                <div class="group-label">{{ g.title }}</div>
                <div class="fields">
                  <div class="field" v-for="f in g.fields" :key="f.key" :class="fieldState(f)">
                    <label>{{ f.label }}<em v-if="f.required && !f.auto">*</em></label>
                    <input v-if="f.auto" :id="'f-' + f.key" class="f-inp" :value="f.auto" disabled/>
                    <select v-else-if="f.type==='select'" :id="'f-' + f.key" class="f-inp"
                            v-model="form[f.key]" @change="onFieldInput(f.key)">
                      <option value="" disabled>请选择</option>
                      <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <input v-else :id="'f-' + f.key" class="f-inp" v-model="form[f.key]"
                           :placeholder="fieldState(f)==='miss' ? '必填 · 待填' : (f.hint || '待填')"
                           @input="onFieldInput(f.key)"/>
                    <button v-if="aiFilled[f.key] && !f.auto" class="badge ai" title="AI 回填、尚未核对，点此确认"
                            @click="confirmAI(f.key)">AI · 未核</button>
                    <span v-else-if="fieldState(f)==='done' && f.required" class="badge ok">✓</span>
                  </div>
                </div>
              </template>
            </template>

            <!-- 签署日期条 -->
            <div class="sign-bar">
              <span class="sb-label">签署日期</span>
              <input id="f-sign_date" class="f-inp date" type="date" v-model="form.sign_date" @change="onHitDateChange"/>
              <button class="chip" :class="{on: isToday}" @click="setSignToday">今日</button>
              <span class="sb-hint">合同顶部、签署块双方日期、"签约当日"各期均以此为准</span>
            </div>
          </div>
        </div>

        <!-- 付款计划（总价与币种并入此处：编辑总价/切币种时与各期、合计校验同屏对照） -->
        <div class="sec" v-if="cfg">
          <div class="sec-head"><span class="dot"></span>价款与付款
            <span class="sec-hint">各期合计须＝{{ totalKey === 'total_price' ? '总售价' : '总费用' }}</span>
            <span class="spacer"></span>
            <button class="btn sm" @click="addRow">＋ 加一期</button>
            <button class="btn sm ghost" @click="resetPayRows">恢复模板预设</button>
          </div>
          <div class="sec-body">
            <div class="group-label">价款与币种</div>
            <div class="fields">
              <div class="field">
                <label>币种<em>*</em></label>
                <select id="f-currency" class="f-inp" v-model="form.currency" @change="onFieldInput('currency')">
                  <option v-for="c in currencies" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
                <button v-if="aiFilled.currency" class="badge ai" @click="confirmAI('currency')">AI · 未核</button>
              </div>
              <div class="field" v-for="f in cfg.fee_fields" :key="f.key"
                   :class="fieldState({key: f.key, required: f.required, auto: false})">
                <label>{{ f.label }}<em v-if="f.required">*</em></label>
                <select v-if="f.type==='select'" :id="'f-' + f.key" class="f-inp"
                        v-model="form[f.key]" @change="onFieldInput(f.key)">
                  <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                </select>
                <input v-else :id="'f-' + f.key" class="f-inp" type="number" min="0" step="1000"
                       v-model.number="form[f.key]" placeholder="待填" @input="onFieldInput(f.key)"/>
                <button v-if="aiFilled[f.key]" class="badge ai" @click="confirmAI(f.key)">AI · 未核</button>
                <div class="fee-cn" v-if="form[f.key] > 0">{{ currencyLabel(form.currency).split(' ')[0] }}{{ toCN(form[f.key]) }}</div>
              </div>
            </div>

            <div class="pay-cards">
              <div class="pay-card" v-for="(it, idx) in payment.rows" :key="idx">
                <div class="pc-seq">
                  <b>第{{ SEQ_CN(idx + 1) }}期</b>
                  <input class="pc-name" v-model="it.label" maxlength="6" placeholder="款项名" data-pfield="label"/>
                  <button class="pc-del" @click="delRow(idx)">删除</button>
                </div>
                <div class="pc-grid">
                  <div class="pc-cell">
                    <label>金额 *</label>
                    <input type="number" min="1" step="1000" v-model.number="it.amount" @input="onAmount(idx)" data-pfield="amount"/>
                    <span class="pc-cn" v-if="it.amount > 0">{{ toCN(it.amount) }}</span>
                  </div>
                  <div class="pc-cell">
                    <label>付款日期{{ it.lockDate ? '（锁定签约当日）' : '' }}</label>
                    <input v-if="it.lockDate" type="date" :value="form.sign_date" disabled/>
                    <input v-else type="date" v-model="it.date" data-pfield="date" @change="onHitDateChange"/>
                  </div>
                </div>
                <div class="pc-cell wide pc-event">
                  <label>付款事件条件</label>
                  <textarea v-model="it.event" placeholder="如：过户完成后 3 日内" data-pfield="event" rows="2"></textarea>
                </div>
              </div>
            </div>
            <div class="total-line" :class="payOk ? 'ok' : (total > 0 ? 'bad' : '')">
              <template v-if="total === 0">请先在「价款与币种」填写总{{ totalKey === 'total_price' ? '售价' : '费用' }}</template>
              <template v-else-if="payOk">✓ 分期合计 {{ currencyLabel(form.currency) }} {{ commas(paySum) }} ＝ 总价 · 两讫（共 {{ payment.rows.length }} 期）</template>
              <template v-else>各期需：金额＞0、有日期或事件、合计＝总价 ｜ 当前 {{ commas(paySum) }} / 需 {{ commas(total) }}</template>
            </div>
            <div class="note-strip" v-if="payNotes.length || extractNotes.length">
              <div v-for="(n, i) in [...payNotes, ...extractNotes]" :key="i">{{ n }}</div>
            </div>
          </div>
        </div>

      </div>
      </transition>
    </section>

    <!-- ================= 合同预览栏 ================= -->
    <section class="pane preview-pane" @pointerdown="onPreviewPanePointerdown">
      <div class="pv-head">
        <b>合同实时预览</b>
        <span class="pv-sub">与下载文件 1:1 同源</span>
        <span class="spacer"></span>
        <span v-if="pvState==='loading'" class="pv-status">渲染中…</span>
        <span v-else-if="pvState==='ready'" class="pv-status ok">✓ 已同步</span>
        <button v-if="pvIssues.length" class="chip ai" @click="pvIssuesOpen=!pvIssuesOpen">
          预览提示 {{ pvIssues.length }}
        </button>
        <button class="btn sm ghost" @click="renderPreview">重渲</button>
      </div>
      <div class="pv-issues" v-if="pvIssuesOpen">
        <div v-for="(n, i) in pvIssues" :key="i">· {{ n }}</div>
      </div>
      <div class="pv-scroll" ref="pvScroll">
        <div class="pv-sheet" ref="sheetEl"></div>
        <div class="pv-placeholder" v-if="pvState==='idle'">
          <div class="pv-ph-mark">契</div>
          <div>填写左侧信息，合同将在这里实时成形</div>
        </div>
        <div class="pv-placeholder loading" v-else-if="pvState==='loading' && !pvHasContent">
          <span class="spin dark"></span>
          <div>正在渲染合同…</div>
        </div>
        <div class="pv-placeholder bad" v-else-if="pvState==='error'">
          ⚠ {{ pvError }}
        </div>
      </div>
      <div class="gen-bar">
        <button class="gb-pill" :class="missingTotal ? 'bad' : 'ok'" @click="jumpMissing">
          {{ missingTotal ? '还差 ' + missingTotal + ' 项' : '全部就绪' }}
        </button>
        <span class="gb-list" v-if="missing.length">{{ missing.slice(0,4).map(m => m.label).join('、') }}{{ missing.length > 4 ? ' 等' : '' }}</span>
        <span class="gb-list" v-else-if="!payOk">分期待对齐</span>
        <span class="spacer"></span>
        <span v-if="generating" class="gb-timer">AI 复核中 {{ elapsed.gen }}s（通常 10~60 秒）</span>
        <button v-if="result && result.ok" class="btn gold" @click="download()">✓ 下载合同</button>
        <button v-else class="btn accent" :disabled="!canGenerate || generating || extracting || parsing" @click="generate">
          <span v-if="generating" class="spin light"></span>{{ generating ? '生成中…' : '生成合同 →' }}
        </button>
      </div>
    </section>

    <!-- ================= 历史抽屉 ================= -->
    <div class="drawer-mask" v-if="historyOpen" @click.self="historyOpen=false">
      <div class="drawer">
        <div class="drawer-head">生成历史
          <span class="drawer-sub">（最近 50 条）</span>
          <span class="spacer"></span>
          <button class="btn ghost sm" @click="historyOpen=false">关闭</button>
        </div>
        <div class="drawer-body">
          <table class="drawer-list" v-if="historyItems.length">
            <thead><tr><th>编号</th><th>类型</th><th>客户</th><th>时间</th><th>状态</th><th></th></tr></thead>
            <tbody>
              <tr v-for="h in historyItems" :key="h.no">
                <td class="mono">{{ h.no }}</td>
                <td>{{ h.type }}</td>
                <td>{{ h.client || '—' }}</td>
                <td class="dim">{{ h.created_at }}</td>
                <td><span class="tag" :class="h.status === 'ok' ? 'ok' : 'bad'">{{ h.status === 'ok' ? '通过' : '失败' }}</span></td>
                <td><button v-if="h.status==='ok'" class="btn sm" @click="viewHistoryResult(h)">下载</button></td>
              </tr>
            </tbody>
          </table>
          <div v-else class="drawer-empty">暂无生成记录</div>
        </div>
      </div>
    </div>

    <!-- ================= 解析提示弹窗 ================= -->
    <div class="modal-mask" v-if="notesModal" @click.self="notesModal = false">
      <div class="modal-card">
        <div class="modal-head"><h3>解析完成 · {{ warnNotes.length + payNotes.length }} 条提示</h3></div>
        <div class="modal-body">
          <div v-for="(n, i) in [...warnNotes, ...payNotes]" :key="i" class="note">{{ n }}</div>
        </div>
        <div class="modal-foot"><button class="btn primary" @click="notesModal = false">知道了，去核对</button></div>
      </div>
    </div>

    <!-- ================= 生成结果弹窗 ================= -->
    <div class="modal-mask" v-if="resultModal && result" @click.self="resultModal = false">
      <div class="modal-card wide">
        <div class="modal-head">
          <h3>合同 {{ result.no }}</h3>
          <span class="tag" :class="!result.ok ? 'bad' : (result.warnings || []).length ? 'warn' : 'ok'">
            {{ !result.ok ? '核对未通过' : (result.warnings || []).length ? '核对通过 · ' + result.warnings.length + ' 条提示' : '核对通过' }}</span>
        </div>
        <div class="modal-body">
          <div v-for="(e, i) in result.errors || []" :key="'e'+i" class="note error">⚠ {{ e }}</div>
          <div v-for="(w, i) in result.warnings || []" :key="'w'+i" class="note">⚠ {{ w }}</div>
          <div v-if="result.ok && !(result.warnings||[]).length" class="note good">全部规则与指纹核对通过</div>
        </div>
        <div class="modal-foot">
          <button v-if="result.ok" class="btn primary" @click="download">下载合同 (.docx)</button>
          <button class="btn ghost" @click="resultModal = false">关闭</button>
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
