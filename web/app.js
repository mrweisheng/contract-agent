/* 华星智能合同生成系统 · 双栏工作台（方案 E）
 * 布局：墨绿侧栏 | 录入核对栏 | 合同实时预览栏
 * 预览：POST /api/preview → 真实 docx 字节 → docx-preview 渲染——所见即下载所得
 * 字段三态：待填红 / AI 金底未核（点一下标记已核）/ 已填中性
 */
import "/vendor/vue.global.prod.js";
const { createApp, reactive, ref, computed, watch, onMounted, nextTick } = window.Vue;
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
      stopReviewPoll();   // 切换类型：旧单的后台复核轮询作废（结论仍在历史里可查）
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

    /* ---------- 实时约合提示（费用输入行） ----------
     * 汇率与落盘同源（/api/fx → fx.get_hkd_cny，含 1.01 加成），换算口径与
     * builder.convert_amount 一致；拉取失败/兜底时在录入栏顶部醒目提醒。 */
    const fxRate = ref(null);
    const fxSource = ref("loading");
    fetch("/api/fx")
      .then(r => r.json())
      .then(d => { fxRate.value = d.rate; fxSource.value = d.source; })
      .catch(() => { fxSource.value = "error"; });
    const fxNotice = computed(() => {
      const s = fxSource.value;
      if (s === "error") return "汇率获取失败：暂时无法换算港币/人民币金额，请检查网络后刷新页面再生成。";
      if (s === "fallback") return "市场汇率获取失败：第二币种金额按兜底汇率估算，仅供参考，请核对后再生成。";
      if (s === "stale") return "未能连接市场汇率源：使用最近一次汇率，可能非最新，请核对后再生成。";
      return "";
    });
    function fxAbout(v) {
      const n = parseInt(v);
      if (!fxRate.value || isNaN(n) || n <= 0) return "";
      const other = form.currency === "HKD" ? "CNY" : "HKD";
      const amt = other === "HKD" ? Math.floor(n / fxRate.value * 1.01 + 0.5)
                                  : Math.floor(n * fxRate.value * 1.01 + 0.5);
      const lab = currencyLabel(other).split(" ")[0];
      return `（约合${lab}${other === "HKD" ? "HK$" : "¥"}${commas(amt)}）`;
    }

    /* ---------- 侧栏手风琴导航：一级（车务/现牌/新办/移民/对账单）+ 二级，同开一个 ----------
       单子业务做叶子直达；多子业务（现牌/新办）点一级展开二级，展开唯一。 */
    const openGroup = ref(null);   // 当前展开的一级组名（null＝全折叠）
    const menu = computed(() => {
      const get = k => types.value.find(t => t.key === k);
      const groups = [];
      if (get("car")) groups.push({ title: "车务", glyph: "车", leaf: { key: "car", port: "", label: "车务" } });
      if (get("transfer_gx") && get("transfer_ns")) groups.push({
        title: "现牌", glyph: "牌", children: [
          { key: "transfer_gx", port: "", label: "高新", _g: "现牌" },
          { key: "transfer_ns", port: "", label: "纳税", _g: "现牌" },
        ]
      });
      const np = get("new_port");
      if (np && np.ports) groups.push({
        title: "新办", glyph: "新",
        children: np.ports.map(p => ({
          key: "new_port", port: p, label: p.replace("口岸", "").replace("大桥", ""), _g: "新办",
        })),
      });
      if (get("immigration")) groups.push({ title: "移民", glyph: "移", leaf: { key: "immigration", port: "", label: "高才移民" } });
      groups.push({ title: "对账单", glyph: "账", leaf: { key: "settlement", port: "", label: "收款结算单" } });
      return groups;
    });
    const isActive = it => selected.type === it.key && selected.port === it.port;
    function toggleGroup(g) {
      // 窄屏侧栏收缩成图标条，没有宽度展开二级：点组直达第一个子项
      if (window.matchMedia("(max-width: 1100px)").matches) {
        if (g.children?.length) selectMenu(g.children[0]);
        return;
      }
      openGroup.value = openGroup.value === g.title ? null : g.title;
    }

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
          seq: i + 1, label: f.label || p.label,
          // 预设自带模板金额（移民类）时预填，客户描述/AI 解析值优先
          amount: f.amount != null ? f.amount : (p.amount != null ? p.amount : null),
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

    /* ---------- 业务草稿快照：Tab 切走再切回，填过的字不丢 ----------
       结算单状态（st）本就常驻不重置，不参与快照；快照只覆盖共用
       form/payment 的合同类业务，切换成本与旧版一致（预览照常重渲）。 */
    const drafts = new Map();   // "type|port" → 快照
    function saveDraft() {
      if (!selected.type || selected.type === "settlement") return;
      drafts.set(selected.type + "|" + selected.port, {
        form: JSON.parse(JSON.stringify(form)),
        aiFilled: { ...aiFilled },
        nlText: nlText.value,
        extractNotes: [...extractNotes.value], warnNotes: [...warnNotes.value], payNotes: [...payNotes.value],
        payRows: JSON.parse(JSON.stringify(payment.rows)), customText: payment.customText,
        result: result.value ? JSON.parse(JSON.stringify(result.value)) : null,
      });
    }
    function restoreDraft(d) {
      Object.keys(form).forEach(k => delete form[k]);
      Object.assign(form, d.form);
      Object.keys(aiFilled).forEach(k => delete aiFilled[k]);
      Object.assign(aiFilled, d.aiFilled);
      nlText.value = d.nlText;
      extractNotes.value = [...d.extractNotes];
      warnNotes.value = [...d.warnNotes];
      payNotes.value = [...d.payNotes];
      payment.rows = JSON.parse(JSON.stringify(d.payRows));
      payment.customText = d.customText;
      result.value = d.result;
      syncExtraShown();     // 「提到才显示」按恢复后的值重算显隐
      extraFoldOpen.value = false;
    }
    function selectMenu(it) {
      if (isActive(it)) return;
      cancelPending();
      saveDraft();   // 切走前存当前业务草稿
      selected.type = it.key; selected.port = it.port;
      openGroup.value = it._g || null;   // 手风琴：进组内业务展开该组，点叶子全收拢
      notesModal.value = false; resultModal.value = false; genBlock.value = null;
      if (it.key === "settlement") {
        result.value = null; extractNotes.value = []; warnNotes.value = []; payNotes.value = [];
        if (!st.tRows.length) stDefaults();      // 常规项目模板：金额留空
        stFetchRate();
      } else {
        const d = drafts.get(it.key + "|" + it.port);
        if (d) restoreDraft(d);
        else {
          result.value = null; extractNotes.value = []; warnNotes.value = []; payNotes.value = [];
          nlText.value = "";  // 不残留上一类型的业务描述，避免误点 AI 提取按新类型抽旧文本
          initForm(); initPayment();
        }
      }
      onlyIssue.value = false; openPay.value = 0; aiOpen.value = false;   // 台账视图态复位
      clearTimeout(pvHitTimer); clearPvHit(); pvHit = null;  // 切类型清联动：旧 key 在新锚点表里语义已失效
      clearTimeout(pvTimer); pvFresh = false;   // 在途的旧类型预览定时器作废
      if (it.key !== "settlement") schedulePreview(30, true);
      else stSchedulePreview();                 // 右侧立即出模板稿
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
      const rows = payment.rows;
      const row = { seq: 1, label: "", amount: null, date: "", event: "", lockDate: false };
      // 「尾款」永远最后一期：新行插到它前面，否则追加到末尾；按落位自动命名「第N期」
      // （前面已有第一/二/三期时，插在尾款前的新行自动叫「第三期」，以此类推；
      //   名字被占（删过中间期再加）就往后顺延，绝不重名）
      const last = rows[rows.length - 1];
      const at = last && (last.label || "").trim() === "尾款" ? rows.length - 1 : rows.length;
      const taken = new Set(rows.map(r => (r.label || "").trim()));
      let n = at + 1;
      while (taken.has(`第${SEQ_CN(n)}期`)) n += 1;
      row.label = `第${SEQ_CN(n)}期`;
      rows.splice(at, 0, row);
      rows.forEach((r, j) => r.seq = j + 1);
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

    /* ---------- 事实台账（ui_mode=ledger，试点：高新现牌 · 原型 06） ----------
     * 布局按「合同骨架」组织：分节编号与合同条款对应，事实行内编辑，付款为时间轴。
     * 只换皮：数据/AI/联动/生成全部复用既有状态——字段 id（f-<key>）、付款卡
     * （.pay-card[data-pfield]）、签署条（.sign-bar）与常规表单一致，
     * hitFromTarget 的预览定位逻辑不感知布局差异。 */
    const onlyIssue = ref(false);   // 只看待补：无缺失且无 AI 待核的行/期整行隐藏
    const openPay = ref(0);         // 时间轴展开的期索引（-1＝全部收起）
    const aiOpen = ref(false);      // AI 快速导入默认收起，点按钮展开
    const ledgerMode = computed(() => cfg.value?.ui_mode === "ledger");
    const shortLabel = s => String(s || "").replace(/（[^）]*）/g, "");   // 「换车费用（可为0…）」→「换车费用」
    function inpSize(v) {   // 行内输入框按内容估宽（CJK 记 2 单位）；number/date 由 CSS 定宽
      const s = String(v ?? "");
      const w = [...s].reduce((a, ch) => a + (ch.charCodeAt(0) > 255 ? 2 : 1), 0);
      return Math.min(48, Math.max(10, w + 1));
    }
    // 行标图标：按行标签取内置描边 SVG（跟随分节色），未登记的行走通用回退
    const ROW_ICONS = {
      "主体": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
      "联络": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
      "地址": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
      "车牌": '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H8c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 3 14v2c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
      "受让公司": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
      "申请人": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
      "随行家属": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>',
      "附赠": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.5 8a2.5 2.5 0 0 1 0-5A4.8 8 0 0 1 12 8a4.8 8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5"/>',
      "质保": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
      "其他费用": '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8M8 11h8M8 15h5"/>',
      "_default": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
    };
    function rowIcon(label) {
      const p = ROW_ICONS[String(label || "").trim()] || ROW_ICONS._default;
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
    }
    // 台账分节：组配置 + ledger_rows 行组织（按组标题匹配，未匹配的组平铺一行一字段）
    const ledgerSections = computed(() => {
      const c = cfg.value;
      if (!c) return [];
      return (c.groups || []).filter(g => g.reveal !== "on_fill").map((g, i) => {
        const def = (c.ledger_rows || []).find(r => r.title === g.title);
        const byKey = Object.fromEntries(g.fields.map(f => [f.key, f]));
        const rows = def
          ? def.rows.map(r => ({ label: r.label, facts: r.fields.map(k => byKey[k]).filter(Boolean) }))
          : g.fields.map(f => ({ label: "", facts: [f] }));
        const req = g.fields.filter(f => f.required && !f.auto);
        const done = req.filter(f => String(form[f.key] ?? "").trim()).length;
        return { no: String(i + 1).padStart(2, "0"), en: def?.en || "", title: shortLabel(g.title), rows, done, total: req.length, pct: req.length ? Math.round(done / req.length * 100) : 100 };
      });
    });
    // 「提到才显示」组的台账分节：行组织同上，但字段是否渲染由 extraShown 决定（模板层过滤）
    const revealLedgerSections = computed(() => {
      const c = cfg.value;
      if (!c) return [];
      return (c.groups || []).filter(g => g.reveal === "on_fill").map(g => {
        const def = (c.ledger_rows || []).find(r => r.title === g.title);
        const byKey = Object.fromEntries(g.fields.map(f => [f.key, f]));
        const rows = def
          ? def.rows.map(r => ({ label: r.label, facts: r.fields.map(k => byKey[k]).filter(Boolean) }))
          : g.fields.map(f => ({ label: "", facts: [f] }));
        return { title: shortLabel(g.title), en: def?.en || "", rows, total: 0, done: 0, pct: 0 };
      });
    });
    // 行问题态：miss 优先于 ai（红点压金点）；「只看待补」据此过滤
    function rowIssue(r) {
      const st = r.facts.map(f => fieldState(f));
      if (st.includes("miss")) return "miss";
      return st.includes("ai") ? "ai" : "";
    }
    function stepIssue(r) {
      return !(parseInt(r.amount) > 0) ||
        (!r.lockDate && !String(r.date || "").trim() && !String(r.event || "").trim());
    }
    function condText(r) {
      if (r.lockDate) return "签约当日" + (form.sign_date ? `（${form.sign_date}）` : "");
      const d = String(r.date || "").trim(), e = String(r.event || "").trim();
      return (d && e) ? `${d} · ${e}` : (d || e || "待填付款条件");
    }
    // 事件条件占位示例按业务与期次给：签约当日期不给「过户完成」这类张冠李戴的示例
    function eventPlaceholder(it, idx) {
      if (it.lockDate) return "签约当日支付，无需另填事件条件";
      const last = idx === payment.rows.length - 1;
      if (cfg.value?.car_default) return last ? "如：车辆完成香港过户登记当日" : "如：签约当日支付";
      if (cfg.value?.imm_fee) return last ? "如：获得入境处批准函后 3 个工作日内" : "如：公司过户完成后 3 个工作日内";
      if (selected.type === "new_port") return last ? "如：领取铁牌等通关资料当日" : "如：省厅提交并获编号后 1 个工作日内";
      return last ? "如：过户完成、交付铁牌资料当日" : "如：提交过户资料后 3 日内";
    }
    function togglePay(i) { openPay.value = openPay.value === i ? -1 : i; }
    // 付款计划问题诊断：生成栏与合计行共用的一句人话；fixDiff＝可一键补进尾款的差额
    const payIssue = computed(() => {
      const rows = payment.rows;
      if (!rows.length) return { text: "还没有付款计划，点「＋ 加一期」或「恢复模板预设」", short: "无付款计划" };
      const noAmt = rows.map((r, i) => parseInt(r.amount) > 0 ? null : i + 1).filter(Boolean);
      if (noAmt.length) {
        const w = noAmt.map(n => `第${SEQ_CN(n)}期`).join("、");
        return { text: `${w}还没填金额`, short: `${w}未填金额` };
      }
      const noWhen = rows.map((r, i) => (r.lockDate || String(r.date || "").trim() || String(r.event || "").trim()) ? null : i + 1).filter(Boolean);
      if (noWhen.length) {
        const w = noWhen.map(n => `第${SEQ_CN(n)}期`).join("、");
        return { text: `${w}还没填付款日期或事件条件`, short: `${w}缺日期/事件` };
      }
      if (total.value > 0) {
        const diff = total.value - paySum.value;
        const sym = form.currency === "HKD" ? "HK$" : "¥";
        if (diff !== 0) return {
          text: `分期合计 ${sym}${commas(paySum.value)}，与总${totalKey.value === "total_price" ? "售价" : "费用"} ${sym}${commas(total.value)} 相差 ${sym}${commas(Math.abs(diff))}`,
          short: `分期合计 ${sym}${commas(paySum.value)} ≠ 总价 ${sym}${commas(total.value)}`,
          fixDiff: diff,
        };
      }
      return null;
    });
    function fixDiffToLast() {
      const rows = payment.rows;
      if (!rows.length || total.value <= 0) return;
      const others = rows.slice(0, -1).reduce((s, r) => s + (parseInt(r.amount) || 0), 0);
      const last = rows[rows.length - 1];
      last.amount = Math.max(0, total.value - others);
      toast(`已把差额补进「${last.label || "尾款"}」，请核对`, "ok");
      schedulePreview();
    }
    // 价款区：totalKey 主费用进价款条，其余费用字段（换车费用/名目）排一行
    const feeMain = computed(() => (cfg.value?.fee_fields || []).find(f => f.key === totalKey.value) || null);
    const feeRest = computed(() => (cfg.value?.fee_fields || []).filter(f => f.key !== totalKey.value));
    const payDone = computed(() => payment.rows.filter(r => parseInt(r.amount) > 0).length);
    const overall = computed(() => {
      const factTotal = ledgerSections.value.reduce((s, x) => s + x.total, 0);
      const factDone = ledgerSections.value.reduce((s, x) => s + x.done, 0);
      const total = factTotal + payment.rows.length, done = factDone + payDone.value;
      return { done, total, pct: total ? Math.round(done / total * 100) : 0 };
    });

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
     * 分期卡片：款项名/金额→费用表行；事件条件、日期（无日期列模式）→表格下方逐期条款段。
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

    // 卖车默认模式：费用表带「订金支付日期」行，日期落在表里（其余模式日期只在条款文字）
    const carDateInTable = () => payModeNow() === "default" && !!cfg.value?.car_default;

    // 分期卡片 → 费用表行号（0=总费用行；-1=末行）。卖车默认模式错位：
    // 订金金额→行1、订金日期→行2、尾款→末行（购车尾款）；其余模式统一 行1+期号；
    // 移民式分期表（imm_fee）无总费用行，行号=期号
    function installmentRowIdx(idx, pfield) {
      if (cfg.value?.imm_fee) return idx;
      if (carDateInTable()) {
        if (idx === 0) return pfield === "date" ? 2 : 1;
        return -1;
      }
      return 1 + idx;
    }

    // 事件条件/日期聚焦的目标条款段：取费用表目标行行名（服务端兜底名，卡片 label 留空也有），
    // 找正文以「行名：」开头的段落（条款行与表行一一对应，见 builder._custom_mode）。
    // 行名含「｜」时（默认模式模板行名如「第三期｜尾款」）依次尝试：原样→去「｜」拼接
    // （「第三期尾款：」）→各段（「尾款：」），覆盖模板条款措辞；同名多期按卡片序号取第 N 个。
    // 全部不中（如卖车模板尾款是「剩余购车尾款港币…」句式）→ 返回 null 回退高亮费用表行。
    function clauseTarget(cardIdx, instIdx) {
      const a = cfg.value.field_anchors?.installment;
      const tbl = a && resolveAnchor(a);
      const row = tbl?.rows?.[instIdx === -1 ? tbl.rows.length - 1 : instIdx];
      const label = row?.cells?.[0]?.textContent?.trim();
      if (!tbl || !label) return null;
      const cands = [label];
      if (label.includes("｜")) {
        cands.push(label.replace(/｜/g, ""));
        for (const seg of label.split("｜")) if (seg) cands.push(seg);
      }
      const ps = [...sheetEl.value.querySelectorAll("p")];
      const texts = ps.map(p => (p.textContent || "").trim());
      for (const cand of cands) {
        const hits = ps.filter((_, i) => texts[i].startsWith(`${cand}：`) || texts[i].startsWith(`${cand}:`));
        if (hits.length) return hits[cardIdx % hits.length];
      }
      return null;
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
      let a = null, instIdx, el = null;
      if (pvHit.key === "__inst") {
        a = cfg.value.field_anchors?.installment;
        instIdx = installmentRowIdx(pvHit.cardIdx, pvHit.pfield);
        // 事件条件、无日期列模式的日期：内容落在表格下方逐期条款行，优先抓条款段
        if (pvHit.pfield === "event" || (pvHit.pfield === "date" && !carDateInTable()))
          el = clauseTarget(pvHit.cardIdx, instIdx);
      } else {
        a = cfg.value.field_anchors?.[pvHit.key];
      }
      if (!el) el = a && resolveAnchor(a, instIdx);
      if (!el) return;
      el.classList.add("pv-hit");
      pinBeacon(el);
      if (scroll) pvScrollTo(el);
    }

    // 定位滚动：目标中心一律对齐预览视口垂直中线（偏下的要滚到正中）；
    // 滚动条已到底时目标已顶到可视区最上，无从再居中，保持不动
    function pvScrollTo(el) {
      const c = pvScroll.value;
      if (!c) return;
      const cr = c.getBoundingClientRect(), tr = el.getBoundingClientRect();
      const maxTop = Math.max(0, c.scrollHeight - c.clientHeight);
      if (c.scrollTop >= maxTop - 2) return;
      const top = c.scrollTop + (tr.top + tr.height / 2 - cr.top) - c.clientHeight / 2;
      const clamped = Math.max(0, Math.min(top, maxTop));
      if (Math.abs(clamped - c.scrollTop) < 2) return;
      c.scrollTo({ top: clamped, behavior: REDUCED_MOTION.matches ? "auto" : "smooth" });
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
    const genBlock = ref(null);   // 必填齐了按钮就可点；点了若付款校验没过 → 弹窗列问题（人话），不发起实际生成
    function tryGenerate() {
      if (generating.value || extracting.value || parsing.value) return;
      const problems = [];
      if (missing.value.length) problems.push("必填信息还没填全：" + missing.value.map(m => m.label).join("、"));
      if (!payOk.value && payIssue.value) problems.push("付款计划还没对齐：" + payIssue.value.text);
      if (problems.length) { genBlock.value = problems; return; }
      generate();
    }
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
        // AI 语义复核已改后台异步：硬校验通过即返回可下载；复核结论轮询补显（见 pollReview）
        if (data.ok) {
          toast(`合同 ${data.no} 生成完成，AI 复核后台进行中`, "ok", 3500);
          pollReview(myGen, data.no);
        } else {
          toast("生成完成，但核对未通过，请查看问题清单", "error", 4000);
          resultModal.value = true;
        }
      } catch (e) {
        if (e.name === "AbortError") return;
        toast(String(e.message || e), "error");
      } finally { if (myGen === reqGen) generating.value = false; }
    }
    /* 后台复核轮询：结论写库后补显（通过→安静提醒；有提示→过眼弹窗；跳过→不挡人） */
    const reviewPending = ref(false);
    let reviewTimer = null;
    function stopReviewPoll() {
      reviewPending.value = false;
      clearTimeout(reviewTimer);
    }
    function pollReview(myGen, no, tries = 0) {
      reviewPending.value = true;
      clearTimeout(reviewTimer);
      const tick = async () => {
        if (myGen !== reqGen) return stopReviewPoll();   // 切换业务/重新生成：旧单轮询作废
        try {
          const r = await fetch(`/api/review/${no}`);
          const d = await r.json();
          if (d.review_status) {
            reviewPending.value = false;
            const issues = d.issues || [];
            if (result.value?.no === no) result.value.warnings = issues;
            if (d.review_status === "warn") {
              toast(`AI 复核完成：${issues.length} 条提示`, "warn", 5000);
              resultModal.value = true;
            } else if (d.review_status === "pass") {
              toast("AI 复核通过，未发现问题", "ok", 3000);
            } else {
              toast(issues[0] || "AI 复核未完成（不影响合同使用）", "warn", 4500);
            }
            return;
          }
        } catch { /* 网络抖动：下一轮再询 */ }
        if (tries < 24) reviewTimer = setTimeout(() => pollReview(myGen, no, tries + 1), 5000);
        else reviewPending.value = false;   // ~2 分钟无结论：放弃轮询，历史里仍可查
      };
      tick();
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
      // 数字输入框聚焦时滚轮会改数值：滚动页面即自动失焦，滚轮只滚页面不改数
      document.addEventListener("wheel", e => {
        const el = e.target;
        if (el && el.tagName === "INPUT" && el.type === "number" && document.activeElement === el) el.blur();
      }, { passive: true });
      try {
        const r = await fetch("/api/types");
        const d = await r.json();
        types.value = d.types;
        currencies.value = d.currencies;
        const g0 = menu.value[0];
        const first = g0 ? (g0.leaf || g0.children?.[0]) : null;
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
      immigration: "示例：客户赵六（身份证 440000000000000000，电话 13800001234，邮箱 zhaoliu@xx.com）办理香港高才计划，主申请人赵六，配偶钱七随行，未成年子女 1 人共计 3 人；服务费人民币 40 万分三期，定金 10 万签约后 3 个工作日内付，第二期 20 万公司过户后付，第三期 10 万获入境处批准函后付。",
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
      immigration: "高才移民服务合约",
    };
    const templateName = computed(() => {
      if (selected.type === "new_port") return TEMPLATE_NAMES[form.port] || "粤Z新办协议";
      return TEMPLATE_NAMES[selected.type] || "";
    });

    /* ---------- 收款结算单（账单式 v6：合同内双币矩阵 + 杂费清单） ----------
       模型：tRows/rRows/uRows（总价/已收/未收，每行双币）+ fees（杂费，赠/双币）+ paid（实收总收）。
       生成映射：两框都填 → 人民币为主、港币为等值（铁律：人民币列示为常态）；
       只填一边 → 该边为主币种。金额算术全部在确定性引擎，前端只搬运。 */
    const st = reactive({
      text: "", notes: [], rate: null, parsing: false, parseSec: 0, generating: false,
      result: null, preview: null,
      group: "", customer: "", date: "", port: "", settle_type: "收尾款",
      settle_custom: "",   // 解析出的结算类型不在快捷选项里时，原样存这里供回显
      tRows: [], rRows: [], uRows: [], fees: [], deds: [], paid: [],
    });
    // 与抬头那 5 枚单选牌取值一一对应（模板里的 v-model 同源，改动需同步）
    const ST_PRESETS = ["收定金", "收第二期款", "收尾款", "杂费结算", "其他"];
    const isSettlement = computed(() => selected.type === "settlement");
    const stPlaceholder = `0908许兰坛深圳湾现牌粤ZLT27港，客户许兰坛
10月9号，深圳湾口岸，收尾款

总价 228000 人民币
定金已经收了 50000 人民币
尾款 178000 人民币 / 210044 港币

杂费这边：
换车费 5000 人民币，我们送
批文卡 260 港币 免
……`;

    function stBlankRow(label) { return { label, cny: null, hkd: null, cnyAuto: false, hkdAuto: false }; }
    function stDefaults() {
      const d = new Date();
      st.group = ""; st.customer = ""; st.port = ""; st.settle_type = "收尾款";
      st.settle_custom = "";
      st.date = `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
      st.tRows = [stBlankRow("总价")];
      st.rRows = [stBlankRow("已收")];
      st.uRows = [stBlankRow("尾款")];
      st.fees = ["换车费", "批文卡", "禁区纸", "核证本", "中检验车", "大陆保险"]
        .map(name => ({ name, cny: null, hkd: null, gift: false, cnyAuto: false, hkdAuto: false }));
      st.deds = [];   // 减免区：解析到才显示，空则整区隐藏
      st.paid = [{ name: "", amount: null, currency: "HKD" }];
    }

    async function stFetchRate() {
      try {
        const r = await fetch("/api/settlement/rate");
        if (r.ok) st.rate = String((await r.json()).cny_to_hkd);
      } catch { /* 取不到就留空，生成时服务端再取 */ }
    }

    /* 双币联动：改一边，另一边为空或仍是自动值时按抬头汇率补齐。
       双向折算一律 ×1.01（与引擎同口径，只做不说）。 */
    function stSync(row, which) {
      row[which + "Auto"] = false;
      const rate = parseFloat(st.rate);
      if (!Number.isFinite(rate) || rate <= 0) return;
      const other = which === "cny" ? "hkd" : "cny";
      const v = parseFloat(row[which]);
      if (!Number.isFinite(v)) return;
      if (row[other] !== null && row[other] !== "" && !row[other + "Auto"]) return;   // 对面手填过，不动
      row[other] = Math.round((which === "cny" ? v * rate * 1.01 : v / rate * 1.01) * 100) / 100;
      row[other + "Auto"] = true;
    }

    /* UI 模型 → 引擎表结构。draft=true 时空金额行保留为留白行（模板稿用）。 */
    function stToEngine(draft) {
      const num = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };
      const pair = (label, cny, hkd, extra) => {
        if (!String(label || "").trim()) return null;
        const c = num(cny), h = num(hkd);
        if (c === null && h === null) return draft ? { item: label.trim(), amount: 0, blank: true } : null;
        if (c !== null) return { item: label.trim(), amount: c, currency: "CNY",
                                 ...(h !== null && h !== 0 ? { hkd_equiv: h } : {}), ...extra };
        return { item: label.trim(), amount: h, currency: "HKD", ...extra };
      };
      const fee = f => {
        const name = String(f.name || "").trim();
        if (!name) return null;
        const c = num(f.cny), h = num(f.hkd);
        if (c === null && h === null) return draft ? { item: name, amount: 0, blank: true, ...(f.gift ? { gift: true } : {}) } : null;
        return { item: name, amount: c !== null ? c : h, currency: c !== null ? "CNY" : "HKD",
                 ...(f.gift ? { gift: true } : {}) };
      };
      // 实收/减免：什么币种就在哪个汇总里直接减，不做任何换算（也无第二框可填）
      const paid = p => {
        const name = String(p.name || "").trim();
        const a = num(p.amount);
        if (!name && a === null) return null;
        if (draft && a === null) return { item: name || "实收", amount: 0, blank: true };
        return { item: name || "实收", amount: a, currency: p.currency === "CNY" ? "CNY" : "HKD" };
      };
      // 减免行与实收行同落 extra_paid（引擎同一个扣减口径），只是编辑区分开展示
      const ded = d => {
        const name = String(d.name || "").trim();
        const a = num(d.amount);
        if (!name && a === null) return null;
        return { item: name || "减免", amount: a, currency: d.currency === "CNY" ? "CNY" : "HKD" };
      };
      const data = { group: st.group, customer: st.customer, date: st.date,
                     port: st.port, settle_type: st.settle_type };
      data.contract_total  = st.tRows.map(r => pair(r.label, r.cny, r.hkd)).filter(Boolean);
      data.contract_paid   = st.rRows.map(r => pair(r.label, r.cny, r.hkd)).filter(Boolean);
      data.contract_unpaid = st.uRows.map(r => pair(r.label, r.cny, r.hkd, { status: "today" })).filter(Boolean);
      data.extra_fees      = st.fees.map(fee).filter(Boolean);
      data.extra_paid      = [...st.deds.map(ded), ...st.paid.map(paid)].filter(Boolean);
      return data;
    }

    /* 底栏实时合计（与引擎今日需付同源口径） */
    const stTotals = computed(() => {
      const num = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
      let inC = 0, inH = 0, outC = 0, outH = 0;
      st.rRows.forEach(r => { inC += num(r.cny); inH += num(r.hkd); });
      st.uRows.forEach(r => { outC += num(r.cny); outH += num(r.hkd); });
      st.fees.forEach(f => { if (!f.gift) { outC += num(f.cny); outH += num(f.hkd); } });
      st.paid.forEach(p => { if (p.currency === "CNY") inC += num(p.amount); else inH += num(p.amount); });
      // 减免不是收到的现金，不计入「已收」；真正数字以引擎生成为准
      const f2 = n => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      return `已收 ¥${f2(inC)} / HK$${f2(inH)} · 应收 ¥${f2(outC)} / HK$${f2(outH)}`;
    });

    /* 解析结果（引擎表结构）→ UI 模型回填 */
    function stFromParsed(p) {
      const pair = e => {
        const amt = Number(e?.amount) || null;
        if (e?.currency === "HKD") return { cny: Number(e.cny_equiv) || null, hkd: amt };
        return { cny: amt, hkd: Number(e.hkd_equiv) || null };
      };
      const mk = (label, e) => ({ label: (e?.item || label || "").trim() || label,
                                  ...pair(e), cnyAuto: false, hkdAuto: false });
      const fill = (arr, cur, def) => {
        if ((arr || []).length) return arr.map(e => mk(def, e));
        const kept = cur.filter(r => Number.isFinite(parseFloat(r.cny)) || Number.isFinite(parseFloat(r.hkd)) || String(r.label || "").trim());
        return kept.length ? kept : [stBlankRow(def)];
      };
      // 抬头：规则解析逐字优先（routes.py），AI 只补口语串联没标签的情况，这里只管接收。
      // 结算类型存原文不归一成 5 个选项——引擎按原文划本次收款范围（compute.SCOPE_RULES）。
      st.group = String(p.group || st.group || "").trim();
      st.customer = String(p.customer || st.customer || "").trim();
      st.port = String(p.port || st.port || "").trim();
      st.date = String(p.date || st.date || "").trim();
      const stType = String(p.settle_type || "").trim();
      if (stType) {
        st.settle_type = stType;
        st.settle_custom = ST_PRESETS.includes(stType) ? "" : stType;
      }
      st.tRows = fill(p.contract_total, st.tRows, "总价");
      st.rRows = fill(p.contract_paid, st.rRows, "已收");
      st.uRows = fill(p.contract_unpaid, st.uRows, "尾款").map(r => ({ ...r, status: "today" }));
      st.fees = (p.extra_fees || []).map(e => ({
        name: e.item || "", ...pair(e), gift: !!e.gift, cnyAuto: false, hkdAuto: false,
      }));
      // 解析出的 extra_paid 全进「减免」区（最常见来源）；真收到的杂费现金在实收区手填。
      // 两区生成时都落回引擎 extra_paid，数字不受分区影响。
      st.deds = (p.extra_paid || []).map(e => ({ name: e.item || "", amount: Number(e.amount) || null,
        currency: e.currency === "CNY" ? "CNY" : "HKD" }));
      st.paid = [];
      if (!st.fees.length) st.fees = [{ name: "", cny: null, hkd: null, gift: false, cnyAuto: false, hkdAuto: false }];
      if (!st.paid.length) st.paid = [{ name: "", amount: null, currency: "HKD" }];
    }

    let stParseTimer = null;
    async function stParse() {
      st.parsing = true; st.parseSec = 0; st.notes = [];
      clearInterval(stParseTimer);
      const t0 = Date.now();
      stParseTimer = setInterval(() => { st.parseSec = Math.floor((Date.now() - t0) / 1000); }, 1000);
      try {
        const d = await postJSON("/api/settlement/parse", { text: st.text });
        stFromParsed(d.data);
        st.notes = d.notes || [];
        st.result = null;
        stSchedulePreview();
        toast(d.source === "llm" ? "已按 AI 整理出明细，请逐行核对" : "解析完成，请核对金额与币种", "ok");
      } catch (e) {
        toast(e.message || "解析失败", "error", 6000);
      } finally { clearInterval(stParseTimer); st.parsing = false; }
    }

    let stPvTimer = null;
    function stSchedulePreview() {
      if (!isSettlement.value) return;
      clearTimeout(stPvTimer);
      stPvTimer = setTimeout(stPreview, 350);
    }
    watch(() => [st.tRows, st.rRows, st.uRows, st.fees, st.deds, st.paid,
                 st.group, st.customer, st.date, st.port, st.settle_type],
          stSchedulePreview, { deep: true });
    async function stPreview() {
      try {
        const d = await postJSON("/api/settlement/preview", { data: stToEngine(true) });
        st.preview = { url: d.png_url, t: Date.now() };
      } catch { /* 预览失败静默：右栏保留上一张或占位 */ }
    }
    async function stGenerate() {
      const missing = [["群名", st.group], ["客户", st.customer]]
        .filter(([, v]) => !String(v || "").trim());
      if (missing.length) {
        toast(`「${missing.map(m => m[0]).join("」「")}」还没填，填一下才能出单`, "error", 4500);
        const inputs = [...document.querySelectorAll('.st-head-row input:not([type="radio"])')];
        const first = missing[0][0] === "群名" ? inputs[0] : inputs[1];
        first?.focus();
        first?.classList.add("st-miss");
        setTimeout(() => first?.classList.remove("st-miss"), 2500);
        return;
      }
      const payload = stToEngine(false);
      if (!["contract_total", "contract_paid", "contract_unpaid", "extra_fees", "extra_paid"]
            .some(k => (payload[k] || []).length)) {
        toast("请先填金额，或粘贴资料点「解析」", "warn");
        return;
      }
      st.generating = true;
      try {
        st.result = await postJSON("/api/settlement/generate", { data: payload });
        st.result.t = Date.now();
        const n = (st.result.warnings || []).length;
        toast(n ? `已出单，有 ${n} 项请核对（见右侧）` : "结算单已生成", n ? "warn" : "ok");
      } catch (e) {
        toast(e.message || "生成失败", "error", 6000);
      } finally { st.generating = false; }
    }
    function stAddFee() { st.fees.push({ name: "", cny: null, hkd: null, gift: false, cnyAuto: false, hkdAuto: false }); }
    function stAddPaid() { st.paid.push({ name: "", amount: null, currency: "HKD" }); }
    function stReset() {
      st.text = ""; st.notes = []; st.result = null; st.preview = null;
      stDefaults();
    }

    return {
      toasts,
      types, currencies, selected, form, aiFilled, nlText, extractNotes, warnNotes, payNotes, notesModal,
      extraShownList, extraFoldList, extraFoldOpen, toggleExtraFold, extraShown, revealLedgerSections,
      extracting, parsing, generating, result, resultModal, historyOpen, historyItems, elapsed, pipe, reviewPending,
      cfg, currencyLabel, totalKey, total, payment, menu, openGroup, toggleGroup, isActive, paneKey,
      selectMenu, runExtract, addRow, delRow, resetPayRows, onAmount, paySum, payOk,
      missing, missingTotal, canGenerate, jumpMissing,
      fieldState, onFieldInput, confirmAI,
      onlyIssue, openPay, ledgerMode, ledgerSections,
      shortLabel, inpSize, rowIssue, rowIcon, stepIssue, condText, togglePay, eventPlaceholder, aiOpen,
      feeMain, feeRest, payDone, overall, payIssue, fixDiffToLast, genBlock, tryGenerate,
      pvState, pvError, pvIssues, pvIssuesOpen, pvHasContent, sheetEl, pvScroll, renderPreview,
      onPaneFocusin, onPaneFocusout, onPanePointerdown, onPreviewPanePointerdown, onHitDateChange,
      isToday, setSignToday,
      generate, download, openHistory, viewHistoryResult,
      toCN, commas, SEQ_CN, todayISO, nlPlaceholder, templateName, fxAbout, fxNotice,
      isSettlement, st, stPlaceholder, stTotals,
      stParse, stGenerate, stSync, stAddFee, stAddPaid, stReset, stFetchRate, saveAs, icon,
    };
  },

  template: /* html */ `
  <div class="app">
    <!-- ================= 侧栏：手风琴菜单（一级同开一个，叶子直达） ================= -->
    <aside class="side">
      <div class="brand">
        <div class="logo">華星</div>
        <div class="sub">CONTRACT · AGENT</div>
      </div>
      <div class="side-scroll">
        <template v-for="g in menu" :key="g.title">
          <div v-if="g.leaf" class="side-item" :class="{active: isActive(g.leaf)}"
               :title="g.leaf.label" @click="selectMenu(g.leaf)">
            <span class="glyph">{{ g.glyph }}</span><span>{{ g.title }}</span>
          </div>
          <template v-else>
            <div class="side-group" :class="{open: openGroup === g.title, 'has-active': g.children.some(isActive)}"
                 :title="g.title" @click="toggleGroup(g)">
              <span class="glyph">{{ g.glyph }}</span><span class="gt">{{ g.title }}</span><span class="chev">▸</span>
            </div>
            <div class="side-sub" v-show="openGroup === g.title">
              <div v-for="it in g.children" :key="it.key + it.port" class="side-item sub"
                   :class="{active: isActive(it)}" :title="it.label" @click="selectMenu(it)">{{ it.label }}</div>
            </div>
          </template>
        </template>
      </div>
      <div class="side-foot">
        <div class="today-dot"><i></i>{{ todayISO() }}</div>
        <button class="side-btn" @click="openHistory">生成历史</button>
      </div>
    </aside>

    <!-- ================= 录入核对栏 ================= -->
    <section class="pane"
             @focusin="onPaneFocusin" @focusout="onPaneFocusout" @pointerdown="onPanePointerdown">
      <div class="pane-top">
        <h2>{{ isSettlement ? '收款结算单' : (cfg?.label || '华星智能合同') }}</h2>
        <span class="tpl-name" v-if="cfg">{{ templateName }}</span>
        <template v-if="ledgerMode">
          <span class="spacer"></span>
          <button class="chip" :class="{on: onlyIssue}" @click="onlyIssue = !onlyIssue">只看待补</button>
        </template>
      </div>
      <div class="overall" v-if="ledgerMode">
        <div class="overall-bar"><i :style="{width: overall.pct + '%'}"></i></div>
        <span>合同完成度 {{ overall.done }}/{{ overall.total }}</span>
      </div>
      <transition name="pfade" mode="out-in">
      <!-- ================ 收款结算单：粘贴 → 解析 → 可改 → 生成 ================ -->
      <!-- ================ 收款结算单：账单式 v6 ================ -->
      <div class="pane-body st-pane" v-if="isSettlement" key="settlement">
        <div class="card">
          <div class="card-head"><span class="dot"></span><h3>业务资料</h3></div>
          <div class="card-body">
            <div class="st-paste-wrap">
              <textarea class="paste" :class="{ dim: st.parsing }" v-model="st.text" spellcheck="false" :placeholder="stPlaceholder"></textarea>
              <div class="st-parse-mask" v-if="st.parsing">
                <span class="spin dark lg"></span>
                <b>AI 整理中 · {{ st.parseSec }}s</b>
                <i class="bar"></i>
              </div>
            </div>
            <div class="row-btns">
              <button class="btn" :disabled="st.parsing || !st.text.trim()" @click="stParse">
                <span v-if="st.parsing" class="spin dark"></span><span v-else v-html="icon('sparkles','st-ic sm')"></span>{{ st.parsing ? '解析中' : '解析' }}
              </button>
              <button class="btn ghost" @click="stReset">
                <span v-html="icon('eraser','st-ic sm')"></span>清空
              </button>
            </div>
            <div class="note-strip" v-if="st.notes.length">
              <div v-for="(n, i) in st.notes" :key="i">{{ n }}</div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span class="dot" style="background:var(--gold)"></span><h3>抬头与汇率</h3></div>
          <div class="card-body st-head-compact">
            <div class="st-head-row">
              <span class="hl" title="结算类型"><span v-html="icon('tag','st-ic')" style="color:#8b5cf6"></span></span>
              <div class="st-chips">
                <span class="st-chip"><input type="radio" value="收定金" v-model="st.settle_type" id="st-t1"><label for="st-t1">收定金</label></span>
                <span class="st-chip"><input type="radio" value="收第二期款" v-model="st.settle_type" id="st-t2"><label for="st-t2">收第二期款</label></span>
                <span class="st-chip"><input type="radio" value="收尾款" v-model="st.settle_type" id="st-t3"><label for="st-t3">收尾款</label></span>
                <span class="st-chip"><input type="radio" value="杂费结算" v-model="st.settle_type" id="st-t4"><label for="st-t4">杂费结算</label></span>
                <span class="st-chip"><input type="radio" value="其他" v-model="st.settle_type" id="st-t5"><label for="st-t5">其他</label></span>
                <span class="st-chip" v-if="st.settle_custom && st.settle_type === st.settle_custom" title="解析出的结算类型，按原文计收范围"><input type="radio" :value="st.settle_custom" v-model="st.settle_type" id="st-t0"><label for="st-t0">{{ st.settle_custom }}</label></span>
              </div>
              <span class="st-rate" title="实时汇率，与百度同口径"><span v-html="icon('exchange','st-ic')" style="color:#d97706"></span>1¥＝<b>{{ st.rate || '…' }}</b> HK$</span>
            </div>
            <div class="st-head-row">
              <span class="hl" title="微信群名"><span v-html="icon('wechat','st-ic')" style="color:#07c160"></span></span><input v-model.trim="st.group" style="flex:1" placeholder="微信群名">
            </div>
            <div class="st-head-row">
              <span class="hl" title="客户"><span v-html="icon('user','st-ic')" style="color:#3b82f6"></span></span><input v-model.trim="st.customer" style="flex:1" placeholder="客户">
              <span class="hl" title="日期"><span v-html="icon('calendar','st-ic')" style="color:#f59e0b"></span></span><input v-model.trim="st.date" style="flex:1.2" placeholder="日期">
              <span class="hl" title="口岸"><span v-html="icon('anchor','st-ic')" style="color:#0e9aa7"></span></span><input v-model.trim="st.port" style="flex:1" placeholder="口岸">
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span class="dot" style="background:var(--ink-2)"></span><h3>合同内款项</h3></div>
          <div class="card-body">
            <div class="st-ct">
              <span class="col-h">项目</span><span class="col-h">人民币</span><span class="col-h">港币</span>
              <template v-for="(r, i) in st.tRows" :key="'t' + i">
                <span class="row-label"><span class="sdot" style="background:var(--ink-2)"></span><input v-model.trim="r.label"></span>
                <span class="st-amt"><span class="pfx">¥</span><input type="number" v-model.number="r.cny" @input="stSync(r, 'cny')" placeholder="金额"></span>
                <span class="st-amt"><span class="pfx">HK$</span><input type="number" v-model.number="r.hkd" @input="stSync(r, 'hkd')" placeholder="金额"></span>
              </template>
              <template v-for="(r, i) in st.rRows" :key="'r' + i">
                <span class="row-label in"><span class="sdot" style="background:var(--green)"></span><input v-model.trim="r.label"></span>
                <span class="st-amt"><span class="pfx">¥</span><input type="number" v-model.number="r.cny" @input="stSync(r, 'cny')" placeholder="金额"></span>
                <span class="st-amt"><span class="pfx">HK$</span><input type="number" v-model.number="r.hkd" @input="stSync(r, 'hkd')" placeholder="金额"></span>
              </template>
              <template v-for="(r, i) in st.uRows" :key="'u' + i">
                <span class="row-label out"><span class="sdot" style="background:var(--red)"></span><input v-model.trim="r.label"></span>
                <span class="st-amt"><span class="pfx">¥</span><input type="number" v-model.number="r.cny" @input="stSync(r, 'cny')" placeholder="金额"></span>
                <span class="st-amt"><span class="pfx">HK$</span><input type="number" v-model.number="r.hkd" @input="stSync(r, 'hkd')" placeholder="金额"></span>
              </template>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><span class="dot" :style="{ background: st.fees.length && st.fees.every(f => f.gift) ? 'var(--green)' : '#4a6e8f' }"></span><h3>合同外杂费</h3></div>
          <div class="card-body">
            <div class="st-fee">
              <span class="col-h" style="text-align:left">杂费项目</span><span class="col-h">人民币</span><span class="col-h">港币</span><span></span><span></span>
            </div>
            <div v-for="(f, i) in st.fees" :key="'f' + i" class="st-fee" :class="{ gifted: f.gift }">
              <input class="name" list="fee-names" v-model.trim="f.name" placeholder="杂费名称">
              <span class="st-amt"><span class="pfx">¥</span><input type="number" v-model.number="f.cny" @input="stSync(f, 'cny')" placeholder="—"></span>
              <span class="st-amt"><span class="pfx">HK$</span><input type="number" v-model.number="f.hkd" @input="stSync(f, 'hkd')" placeholder="—"></span>
              <button class="st-gift" :class="{ on: f.gift }" title="赠送：单据照显示，不计入应收" @click="f.gift = !f.gift"><span v-html="icon('gift','st-ic')"></span></button>
              <button class="st-row-x" title="删这一行" @click="st.fees.splice(i, 1)"><span v-html="icon('x','st-ic')"></span></button>
            </div>
            <datalist id="fee-names"><option value="换车费"></option><option value="批文卡"></option><option value="禁区纸"></option><option value="核证本"></option><option value="中检验车"></option><option value="大陆保险"></option></datalist>
            <button class="add-row" @click="stAddFee"><span v-html="icon('plus','st-ic sm')"></span>加一项杂费</button>

            <div class="st-ded-sec" v-if="st.deds.length">
              <div class="st-ded-head"><span class="sdot"></span>减免</div>
              <div v-for="(d, i) in st.deds" :key="'d' + i" class="st-fee">
                <input class="name" v-model.trim="d.name" placeholder="减免项目">
                <span class="st-amt st-amt-wide"><span class="pfx st-cur-pfx" title="点此切换币种：减免在对应币种的汇总里直接扣" @click="d.currency = d.currency === 'HKD' ? 'CNY' : 'HKD'">{{ d.currency === 'HKD' ? 'HK$' : '¥' }}</span><input type="number" v-model.number="d.amount" placeholder="金额"></span>
                <span></span>
                <button class="st-row-x" title="删这一行" @click="st.deds.splice(i, 1)"><span v-html="icon('x','st-ic')"></span></button>
              </div>
              <button class="add-row" @click="st.deds.push({ name: '', amount: null, currency: 'HKD' })"><span v-html="icon('plus','st-ic sm')"></span>加一项减免</button>
            </div>

            <div class="st-paid-sec">
              <div class="st-paid-head"><span class="sdot"></span>杂费实收<span class="note">只记总收，不逐项对应杂费</span></div>
              <div v-for="(p, i) in st.paid" :key="'p' + i" class="st-fee paid">
                <input class="name" v-model.trim="p.name" placeholder="收款方式">
                <span class="st-amt st-amt-wide"><span class="pfx st-cur-pfx" title="点此切换币种：减免在对应币种的汇总里直接扣" @click="p.currency = p.currency === 'HKD' ? 'CNY' : 'HKD'">{{ p.currency === 'HKD' ? 'HK$' : '¥' }}</span><input type="number" v-model.number="p.amount" placeholder="金额"></span>
                <span></span>
                <button class="st-row-x" title="删这一行" @click="st.paid.splice(i, 1)"><span v-html="icon('x','st-ic')"></span></button>
              </div>
              <button class="add-row" @click="stAddPaid"><span v-html="icon('plus','st-ic sm')"></span>加一笔实收</button>
            </div>
          </div>
        </div>
      </div>
      <div class="pane-body" v-else :key="paneKey">
        <div v-if="fxNotice" class="fx-warn"><span class="fx-warn-ic">⚠</span>{{ fxNotice }}</div>

        <!-- 智能录入：台账模式＝默认收起的金色细条，点开才是输入区；常规模式＝原卡片 -->
        <div v-if="ledgerMode" class="ai-bar" :class="{open: aiOpen}">
          <button v-if="!aiOpen" type="button" class="ai-toggle" @click="aiOpen = true">
            <span class="ai-toggle-star">✦</span>AI 快速导入<span class="ai-toggle-hint">粘贴客户原文，自动填表</span>
          </button>
          <template v-else>
            <div class="ai-row">
              <textarea class="nl" v-model="nlText" rows="2" :placeholder="nlPlaceholder()"></textarea>
              <button class="btn primary" :disabled="extracting || parsing" @click="runExtract">
                <span v-if="extracting || parsing" class="spin"></span>{{ extracting ? '提取中…' : parsing ? '解析付款中…' : 'AI 提取' }}
              </button>
              <button class="ai-collapse" title="收起" @click="aiOpen = false">▾</button>
            </div>
            <div class="pipeline" :class="{show: extracting || parsing || pipe.extract || pipe.pay}">
              <div class="stage" :class="pipe.extract">{{ {run:'提取字段中…',done:'✓ 字段提取',fail:'✗ 提取失败'}[pipe.extract] || '待提取' }}</div>
              <div class="stage" :class="pipe.pay">{{ {run:'解析付款中…',done:'✓ 付款解析',fail:'✗ 付款解析'}[pipe.pay] || '跳过' }}</div>
            </div>
          </template>
        </div>
        <div v-else class="sec">
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

        <!-- ================= 事实台账（ledger 布局 · 试点：高新现牌） ================= -->
        <template v-if="ledgerMode">
        <div class="ledger" :class="{'only-issue': onlyIssue}">
          <div class="ledger-sheet">

            <section class="led-sec" v-for="(s, si) in ledgerSections" :key="s.title" :class="'sec-' + (si + 1)">
              <div class="led-sec-head">
                <span class="led-no">{{ s.no }}</span>
                <div class="led-sec-title"><h3>{{ s.title }}</h3><div class="led-en" v-if="s.en">{{ s.en }}</div></div>
                <span class="led-count" :class="s.done === s.total ? 'ok' : 'warn'">
                  <span class="track"><i :style="{width: s.pct + '%'}"></i></span><b class="cnt">{{ s.done }}/{{ s.total }}</b>
                </span>
              </div>
              <div class="led-body">
                <div class="led-row" v-for="(r, ri) in s.rows" :key="ri"
                     :class="rowIssue(r) ? 'has-' + rowIssue(r) : ''">
                  <div class="led-row-label"><span class="led-ico" v-html="rowIcon(r.label)" :title="r.label"></span></div>
                  <div class="led-facts">
                    <span class="led-fact" v-for="f in r.facts" :key="f.key"
                          :class="fieldState(f)" :title="f.label">
                      <span class="lf-label">{{ shortLabel(f.label) }}<em v-if="f.required && !f.auto">*</em></span>
                      <span class="lf-auto" v-if="f.auto">{{ form[f.key] }}</span>
                      <select v-else-if="f.type === 'select'" :id="'f-' + f.key" class="lf-in lf-sel"
                              v-model="form[f.key]" @change="onFieldInput(f.key)">
                        <option value="" disabled>请选择</option>
                        <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                      </select>
                      <input v-else :id="'f-' + f.key" class="lf-in" v-model="form[f.key]"
                             :size="inpSize(form[f.key])"
                             :placeholder="fieldState(f) === 'miss' ? '必填 · 待填' : (f.hint || '待填')"
                             @input="onFieldInput(f.key)"/>
                      <button v-if="aiFilled[f.key] && !f.auto" class="lf-badge" title="AI 回填、尚未核对，点此确认"
                              @click="confirmAI(f.key)">AI·未核</button>
                    </span>
                  </div>
                  <i class="led-badge"></i>
                </div>
              </div>
            </section>

            <!-- 提到才显示组（如卖车附赠与售后）：没提到的字段不渲染，隐私优先；折叠区点开才见 -->
            <section class="led-sec sec-2" v-for="g in revealLedgerSections" :key="'rv-' + g.title">
              <div class="led-sec-head">
                <span class="led-no">+</span>
                <div class="led-sec-title"><h3>{{ g.title }}</h3><div class="led-en" v-if="g.en">{{ g.en }}</div></div>
              </div>
              <div class="led-body">
                <template v-for="r in g.rows" :key="r.label">
                  <div class="led-row" v-show="r.facts.some(f => extraShown[f.key])"
                       :class="rowIssue(r) ? 'has-' + rowIssue(r) : ''">
                    <div class="led-row-label"><span class="led-ico" v-html="rowIcon(r.label)"></span></div>
                    <div class="led-facts">
                      <span class="led-fact" v-for="f in r.facts" :key="f.key" v-show="extraShown[f.key]"
                            :class="fieldState(f)" :title="f.label">
                        <span class="lf-label">{{ shortLabel(f.label) }}<em v-if="f.required && !f.auto">*</em></span>
                        <select v-if="f.type === 'select'" :id="'f-' + f.key" class="lf-in lf-sel"
                                v-model="form[f.key]" @change="onFieldInput(f.key)">
                          <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                        </select>
                        <input v-else :id="'f-' + f.key" class="lf-in" v-model="form[f.key]"
                               :size="inpSize(form[f.key])"
                               :placeholder="fieldState(f) === 'miss' ? '必填 · 待填' : (f.hint || '待填')"
                               @input="onFieldInput(f.key)"/>
                        <button v-if="aiFilled[f.key] && !f.auto" class="lf-badge" title="AI 回填、尚未核对，点此确认"
                                @click="confirmAI(f.key)">AI·未核</button>
                      </span>
                    </div>
                    <i class="led-badge"></i>
                  </div>
                </template>
                <template v-if="extraFoldOpen">
                  <template v-for="r in g.rows" :key="'fold-' + r.label">
                    <div class="led-row" v-show="r.facts.some(f => extraFoldList.some(x => x.key === f.key))">
                      <div class="led-row-label"><span class="led-ico" v-html="rowIcon(r.label)"></span></div>
                      <div class="led-facts">
                        <span class="led-fact" v-for="f in r.facts" :key="f.key" v-show="extraFoldList.some(x => x.key === f.key)"
                              :class="fieldState(f)" :title="f.label">
                          <span class="lf-label">{{ shortLabel(f.label) }}</span>
                          <select v-if="f.type === 'select'" :id="'f-' + f.key" class="lf-in lf-sel"
                                  v-model="form[f.key]" @change="onFieldInput(f.key)">
                            <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                          </select>
                          <input v-else :id="'f-' + f.key" class="lf-in" v-model="form[f.key]"
                                 :size="inpSize(form[f.key])"
                                 :placeholder="f.hint || '待填'" @input="onFieldInput(f.key)"/>
                          <button v-if="aiFilled[f.key] && !f.auto" class="lf-badge" title="AI 回填、尚未核对，点此确认"
                                  @click="confirmAI(f.key)">AI·未核</button>
                        </span>
                      </div>
                      <i class="led-badge"></i>
                    </div>
                  </template>
                </template>
                <button class="extra-fold-bar edit-only" v-if="extraFoldList.length" @click="toggleExtraFold">{{ extraFoldOpen ? '▾ 收起' : '＋ ' + g.title + '（客户提到才填）' }}</button>
              </div>
            </section>

            <section class="led-sec" :class="'sec-' + (ledgerSections.length + 1)">
              <div class="led-sec-head">
                <span class="led-no">{{ String(ledgerSections.length + 1).padStart(2, '0') }}</span>
                <div class="led-sec-title"><h3>价款与付款</h3><div class="led-en">Fees &amp; Payment</div></div>
                <span class="led-count" :class="payDone === payment.rows.length ? 'ok' : 'warn'">
                  <span class="track"><i :style="{width: (payment.rows.length ? Math.round(payDone / payment.rows.length * 100) : 0) + '%'}"></i></span><b class="cnt">{{ payDone }}/{{ payment.rows.length }}</b>
                </span>
              </div>

              <!-- 价款条：总费用 + 币种切换 -->
              <div class="led-price" v-if="feeMain">
                <div class="lp-main">
                  <span class="lf-label">{{ shortLabel(feeMain.label) }}<em>*</em></span>
                  <select v-if="!cfg.currency_locked" id="f-currency" class="lf-in lf-sel lp-cur" v-model="form.currency"
                          @change="onFieldInput('currency')" title="币种">
                    <option v-for="c in currencies" :key="c.value" :value="c.value">{{ c.label }}</option>
                  </select>
                  <span v-else class="lf-auto">{{ currencyLabel(form.currency) }}</span>
                  <input :id="'f-' + feeMain.key" class="lf-in lp-money" :class="{miss: !form[feeMain.key]}" type="number" min="0" step="1000"
                         v-model.number="form[feeMain.key]" placeholder="待填" @input="onFieldInput(feeMain.key)"/>
                </div>
                <div class="fee-cn lp-cn" v-if="form[feeMain.key] > 0">{{ currencyLabel(form.currency).split(' ')[0] }}{{ toCN(form[feeMain.key]) }}{{ fxAbout(form[feeMain.key]) }}</div>
              </div>

              <div class="led-body">
                <div class="led-row" :class="rowIssue({ facts: feeRest }) ? 'has-' + rowIssue({ facts: feeRest }) : ''">
                  <div class="led-row-label"><span class="led-ico" v-html="rowIcon('其他费用')" title="其他费用"></span></div>
                  <div class="led-facts">
                    <span class="led-fact" v-for="f in feeRest" :key="f.key"
                          :class="fieldState({ key: f.key, required: f.required, auto: false })" :title="f.label">
                      <span class="lf-label">{{ shortLabel(f.label) }}<em v-if="f.required">*</em></span>
                      <select v-if="f.type === 'select'" :id="'f-' + f.key" class="lf-in lf-sel"
                              v-model="form[f.key]" @change="onFieldInput(f.key)">
                        <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                      </select>
                      <input v-else :id="'f-' + f.key" class="lf-in lp-money" type="number" min="0" step="1000"
                             v-model.number="form[f.key]" placeholder="待填" @input="onFieldInput(f.key)"/>
                      <button v-if="aiFilled[f.key]" class="lf-badge" title="AI 回填、尚未核对，点此确认"
                              @click="confirmAI(f.key)">AI·未核</button>
                    </span>
                  </div>
                  <i class="led-badge"></i>
                </div>
              </div>

              <div class="led-pay-hint">
                <span>付款顺序＝实际履约顺序，点某一期展开编辑</span>
                <span class="spacer"></span>
                <button class="text-act edit-only" @click="addRow">＋ 加一期</button>
                <button class="text-act edit-only" @click="resetPayRows">恢复模板预设</button>
              </div>
              <div class="led-timeline">
                <div class="pay-card led-step" v-for="(it, idx) in payment.rows" :key="idx"
                     :class="{open: openPay === idx, 'step-issue': stepIssue(it)}" :data-n="idx + 1">
                  <div class="led-step-main" @click="togglePay(idx)">
                    <input class="led-step-name" v-model="it.label" maxlength="6" placeholder="款项名"
                           data-pfield="label" @click.stop/>
                    <input class="led-step-amount" type="number" min="0" step="1000" v-model.number="it.amount"
                           placeholder="金额" data-pfield="amount" @input="onAmount(idx)" @focus="openPay = idx" @click.stop/>
                    <span class="led-step-cond" :title="condText(it)">{{ condText(it) }}</span>
                    <button class="led-step-x edit-only" title="删除这一期" @click.stop="delRow(idx)">✕</button>
                    <span class="led-chev">⌄</span>
                  </div>
                  <div class="led-step-detail">
                    <div class="lsd-row">
                      <label>付款日期{{ it.lockDate ? '（锁定签约当日）' : '' }}</label>
                      <input v-if="it.lockDate" type="date" :value="form.sign_date" disabled/>
                      <input v-else type="date" v-model="it.date" data-pfield="date" @change="onHitDateChange"/>
                    </div>
                    <div class="lsd-row">
                      <label>付款事件条件</label>
                      <textarea v-model="it.event" :placeholder="eventPlaceholder(it, idx)" data-pfield="event" rows="2"></textarea>
                    </div>
                  </div>
                </div>
              </div>
              <div class="total-line" :class="payOk ? 'ok' : (total > 0 ? 'bad' : '')">
                <template v-if="total === 0">先在上方填写服务总{{ totalKey === 'total_price' ? '售价' : '费用' }}</template>
                <template v-else-if="payOk">✓ 分期合计 {{ currencyLabel(form.currency) }} {{ commas(paySum) }} ＝ 总{{ totalKey === 'total_price' ? '售价' : '费用' }} · 两讫（共 {{ payment.rows.length }} 期）</template>
                <template v-else>
                  <span>{{ payIssue.text }}</span>
                  <button v-if="payIssue.fixDiff > 0" class="text-act edit-only" @click="fixDiffToLast">差额 {{ commas(payIssue.fixDiff) }} 一键补进尾款</button>
                </template>
              </div>
              <div class="note-strip" v-if="payNotes.length || extractNotes.length">
                <div v-for="(n, i) in [...payNotes, ...extractNotes]" :key="i">{{ n }}</div>
              </div>
            </section>

            <div class="sign-bar led-sign">
              <span class="sb-label">签署日期</span>
              <input id="f-sign_date" class="f-inp date" type="date" v-model="form.sign_date" @change="onHitDateChange"/>
              <button class="chip edit-only" :class="{on: isToday}" @click="setSignToday">今日</button>
              <span class="sb-hint">合同顶部、签署块双方日期、"签约当日"各期均以此为准</span>
            </div>
          </div>
        </div>
        </template>

        <template v-else>
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
              <div class="field" v-if="!cfg.currency_locked">
                <label>币种<em>*</em></label>
                <select id="f-currency" class="f-inp" v-model="form.currency" @change="onFieldInput('currency')">
                  <option v-for="c in currencies" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
                <button v-if="aiFilled.currency" class="badge ai" @click="confirmAI('currency')">AI · 未核</button>
              </div>
              <div class="field" v-else>
                <label>币种</label>
                <input class="f-inp" :value="currencyLabel(form.currency) + '（随模板固定）'" disabled/>
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
                <div class="fee-cn" v-if="form[f.key] > 0">{{ currencyLabel(form.currency).split(' ')[0] }}{{ toCN(form[f.key]) }}{{ fxAbout(form[f.key]) }}</div>
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
        </template>

      </div>
      </transition>
    </section>

    <!-- ================= 成品栏：结算单成品 / 合同实时预览 ================= -->
    <section class="pane preview-pane" @pointerdown="onPreviewPanePointerdown">
      <div class="pv-head">
        <b>{{ isSettlement ? '结算单成品' : '合同实时预览' }}</b>
        <span class="pv-sub" v-if="!isSettlement">与下载文件 1:1 同源</span>
        <span class="spacer"></span>
        <span v-if="!isSettlement && pvState==='loading'" class="pv-status">渲染中…</span>
        <span v-else-if="!isSettlement && pvState==='ready'" class="pv-status ok">✓ 已同步</span>
        <button v-if="!isSettlement && pvIssues.length" class="chip ai" @click="pvIssuesOpen=!pvIssuesOpen">
          预览提示 {{ pvIssues.length }}
        </button>
        <button v-if="!isSettlement" class="btn sm ghost" @click="renderPreview">重渲</button>
      </div>
      <div class="pv-issues" v-if="!isSettlement && pvIssuesOpen">
        <div v-for="(n, i) in pvIssues" :key="i">· {{ n }}</div>
      </div>
      <!-- 结算单成品：正式单 > 实时模板稿 > 占位 -->
      <div class="pv-scroll st-result" v-if="isSettlement">
        <template v-if="st.result">
          <div class="st-warn" v-if="st.result.warnings.length">
            <div v-for="(w, i) in st.result.warnings" :key="i">⚠ {{ w }}</div>
          </div>
          <img class="st-img" :key="st.result.t" :src="st.result.png_url + '?t=' + st.result.t" alt="结算单成品" />
          <div class="st-dl">
            <button class="btn gold" @click="saveAs(st.result.pdf_url + '?t=' + st.result.t, st.result.filename)">下载 PDF</button>
            <button class="btn ghost" @click="saveAs(st.result.png_url + '?t=' + st.result.t, st.result.filename.replace(/\.pdf$/, '.png'))">下载 PNG</button>
          </div>
          <div class="st-check" v-if="st.result.selfcheck && st.result.selfcheck.expr">自检：{{ st.result.selfcheck.expr }}</div>
        </template>
        <template v-else-if="st.preview">
          <img class="st-img st-draft" :key="st.preview.t" :src="st.preview.url + '?t=' + st.preview.t" alt="模板预览" />
        </template>
        <div class="pv-placeholder" v-else>
          <div class="pv-ph-mark">結</div>
          <div>正在渲染模板预览…</div>
        </div>
      </div>
      <template v-else>
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
        <span class="gb-list" v-else-if="!payOk && payIssue">{{ payIssue.short }}</span>
        <span class="spacer"></span>
        <span v-if="generating" class="gb-timer">生成中 {{ elapsed.gen }}s</span>
        <span v-else-if="reviewPending" class="gb-timer">AI 复核中…（不挡下载）</span>
        <button v-if="result && result.ok" class="btn gold" @click="download()">✓ 下载合同</button>
        <!-- 必填齐了就可点；付款没对齐不禁用——点了弹窗说明，不实际生成 -->
        <button v-else class="btn accent" :disabled="missing.length > 0 || generating || extracting || parsing" @click="tryGenerate">
          <span v-if="generating" class="spin light"></span>{{ generating ? '生成中…' : '生成合同 →' }}
        </button>
      </div>
      </template>
      <!-- 结算单底栏：实时合计 + 生成 -->
      <div class="gen-bar" v-if="isSettlement">
        <span class="spacer"></span>
        <span class="gb-list">{{ stTotals }}</span>
        <button class="btn accent" :disabled="st.generating" @click="stGenerate">
          <span v-if="st.generating" class="spin light"></span>{{ st.generating ? '生成中…' : '生成结算单 →' }}
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
                <td><span class="tag" :class="h.status === 'ok' ? 'ok' : 'bad'">{{ h.status === 'ok' ? '通过' : '失败' }}</span>
                    <span v-if="h.review_status === 'warn'" class="tag warn" title="AI 复核有提示">复核提醒</span>
                    <span v-else-if="h.review_status === 'pass'" class="tag ok" title="AI 复核通过">复核过</span></td>
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
          <span class="tag" :class="!result.ok ? 'bad' : (result.warnings || []).length ? 'warn' : (reviewPending ? 'warn' : 'ok')">
            {{ !result.ok ? '核对未通过'
              : (result.warnings || []).length ? 'AI 复核 · ' + result.warnings.length + ' 条提示'
              : reviewPending ? '生成完成 · AI 复核中' : '核对与 AI 复核均通过' }}</span>
        </div>
        <div class="modal-body">
          <div v-for="(e, i) in result.errors || []" :key="'e'+i" class="note error">⚠ {{ e }}</div>
          <div v-for="(w, i) in result.warnings || []" :key="'w'+i" class="note">⚠ {{ w }}</div>
          <div v-if="result.ok && !(result.warnings||[]).length && !reviewPending" class="note good">全部规则与指纹核对通过，AI 复核亦未发现问题</div>
        </div>
        <div class="modal-foot">
          <button v-if="result.ok" class="btn primary" @click="download">下载合同 (.docx)</button>
          <button class="btn ghost" @click="resultModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- ================= 生成校验弹窗（点了生成但没过校验） ================= -->
    <div class="modal-mask" v-if="genBlock" @click.self="genBlock = null">
      <div class="modal-card">
        <div class="modal-head"><h3>还差这些，补齐就能生成</h3></div>
        <div class="modal-body">
          <div v-for="(p, i) in genBlock" :key="i" class="note error">⚠ {{ p }}</div>
        </div>
        <div class="modal-foot">
          <button v-if="payIssue && payIssue.fixDiff > 0" class="btn primary" @click="fixDiffToLast(); genBlock = null">差额一键补进尾款</button>
          <button class="btn ghost" @click="genBlock = null">知道了，去补齐</button>
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
