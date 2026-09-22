# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 华星智能合同生成系统

按业务类型（卖车 / 现牌过户·高新 / 现牌过户·纳税 / 粤Z新办）生成客户合同 docx：选类型 → 填信息（支持自然语言，AI 回填）→ 确认付款计划 → 自动生成并三重核对 → 浏览器下载。
**核心约束**：模板只读、排版零变化、固定内容锁定、付款表/条款确定式生成（不依赖 LLM 写条款文字）、LLM 仅做软复核与自然语言抽取。

完整使用说明见 `README.md`；Ubuntu + Nginx + HTTPS 部署见 `DEPLOY.md`；上线必做的访问控制与数据备份见 README 第六节与 DEPLOY.md 第七/十章。

完整使用说明见 `README.md`；Ubuntu + Nginx + HTTPS 部署见 `DEPLOY.md`。

## 常用命令

### Windows 启动（最常见，生产/演示都用这个）
```
pip install -r requirements.txt     # 锁版本依赖，必跑回归测试通过的版本
start.bat                           # 已纳入仓库（.gitattributes 锁 CRLF）；双击或在 bash 里运行；前台 uvicorn --reload
# 仅有 start.bat 被改坏或路径不对时，才需要运行：python scripts/make_startbat.py
```
浏览器访问 `http://127.0.0.1:8300`（start.bat 监听 0.0.0.0，局域网内可用本机 IP 访问）。

### Linux（直跑）
```
cd server && python3 -m uvicorn main:app --host 0.0.0.0 --port 8300
```

### 开发模式（前后端分离 + 热更新）
终端 1：后端 `cd server && python3 -m uvicorn main:app --host 0.0.0.0 --port 8300 --reload`
终端 2：前端 `cd web && npm install && npm run dev` → 浏览器 `http://localhost:5173`（API 自动代理到 8300）
两种模式共用同一份代码。

### 回归测试（必跑，不调 LLM、不花钱）
```
python scripts/test_pipeline.py
```
覆盖：4 类业务 × 3 种付款模式（含 default/one_time/custom + 卖车事件句改写 + 自定义多期）。**改模板或改 builder 后必须跑此测试**，用例全部 PASS 才算通过。

### 前端原型
`prototypes/` 目录下归档早期 HTML 原型，仅参考，不参与构建。

## 架构（关键路径，必读）

### 请求生命周期
```
浏览器 ─▶ /api/extract (LLM 抽取自然语言 → 表单字段)
       ─▶ /api/parse-payment (LLM 解析付款描述 → 期次)
       ─▶ /api/generate:
            store.reserve_no()        # SQLite 占位，11位编号
            engine.builder.build_contract()  # 复制模板 → 程序级填表/改条款
            engine.checker.check_rules()     # 必填/残留空位/大写=数字/分期合计/币种唯一/编号
            engine.checker.check_fingerprint()  # 逐表逐段 vs 模板 diff
            llm.review_messages()      # 软校验（失败不拦截，只 warning）
            store.confirm_no()         # ok/failed；崩了走 release_no
       ─▶ /api/download/{no}
```

### 服务端模块边界（`server/`）
- `main.py` —— 入口；挂载 `web/` 为 StaticFiles；中间件关闭首页与 `app.js/style.css` 缓存（`no_cache_html`）。
- `api/routes.py` —— 所有 `/api/*` 路由；唯一对外层。注意 `_filter_notes` / `_is_confirmation` 是 LLM 噪音过滤。
- `api/store.py` —— SQLite 编号流水 + 生成历史；并发模型是 **进程内 Lock + `BEGIN IMMEDIATE` + 分配即 pending 占位**，编号永不回补（最大号+1）。崩溃残留 pending 由 `reserve_no` 启动时清扫（默认 15 分钟）。
- `engine/types_config.py` —— **单一事实来源**。`TYPES` 字典同时承载前端表单结构（`groups`/`fee_fields`/`pay_preset`/`client_side`）与落盘引擎锚点（`party_table_anchor`/`fee_table_anchor`/`payment_section`/`fee_cell_style`）。**改字段/锚点只改这里**。
- `engine/builder.py` —— 合同组装器。所有条款文字由模板句式生成，LLM 不参与落盘。`derive_payment()` 把付款输入归一为 `default` / `one_time` / `custom` 三模式；其他三个 `_*_mode` 函数执行对应改写。`_archive_existing()` 防静默覆盖。
- `engine/checker.py` —— **两层硬校验**：`check_rules`（必填/残留空位/大写=数字/分期合计/币种唯一/编号格式，错了就 422/500）+ `check_fingerprint`（格式指纹，逐段逐表比对模板，**非修改点必须零差异**）。LLM 复核在 `api/routes.py` 里，是第三层软校验（失败不拦截）。
- `engine/writer.py` —— docx 低层操作（按段落填空 / 改写条款段 / 删行 / 插列）；签名一律 `W.set_cell_text`、`W.fill_blanks_in_paragraph`、`W.rewrite_section`、`W.append_section_paras`、`W.is_valid_iso_date`。
- `engine/car_extras.py` —— 卖车可选内容（附赠项 / 发动机质保）的**文字单一事实来源**：builder 落盘与 checker 校验共用同一推导函数，保证表单所见即合同所得。原则：客户信息没提到就完全不落盘（默认全关）；附赠项只记一行「附赠：…」；质保期限用户给的条件在前、默认（半年/3万公里）补后。
- `engine/money.py` —— 数字 ↔ 大写 / 千分位 / 币种标签短语 / 金额清理。
- `llm/client.py` —— MiniMax 中国版 OpenAI 兼容接口；抛 `LLMError`；默认 5~40s，慢属正常。
- `llm/prompts.py` —— 三套提示词工厂：`extract_messages` / `parse_payment_messages` / `review_messages` + `build_summary`。

### 前端（`web/`）
- 纯静态单页：Vue 3 本地文件（`vendor/vue.global.prod.js`），**生产环境不需要 Node**。
- `app.js`（≈38K）+ `style.css`（≈40K）—— 整个应用在这里。
- `index.html` 入口；版本号 `?v=YYYYMMDD` 用于绕过缓存（改一次加一次）。
- `vite.config.js` 仅开发用：5173 端口，`/api` 代理到 8300。
- 前端表单/分期表/AI 提取/下载 全部依赖后端 `/api/types` 一次拿配置，**不要在前端硬编码业务字段**。

### 模板（`server/templates/`）
7 份只读 docx；`new_port` 类型按 `port` 字段挑模板（template_map）。**仓库内的主源是 `server/templates/`；开发者本地另有一份 `E:\华星客服\简体\` 下的同名 7 份作为非 git 备份（仅开发机可见），改模板后两边同步**，改后必跑 `scripts/test_pipeline.py`。

### 数据（`server/data/`，git 忽略）
- `contracts.db`（SQLite）+ `out/`（成品 docx）；
- 含客户隐私，**生产必须每日打包备份**（DEPLOY.md 第七章 cron）。

## 修改模板 / 字段须知

| 改什么 | 改哪 |
|---|---|
| 字段、锚点、付款预设、表单分组 | `server/engine/types_config.py`（一处即可，前端和引擎都从这里读） |
| 模板 docx 排版/文字 | `server/templates/`（仓库主源；同步到本地 `E:\华星客服\简体\` 非 git 备份） |
| 提示词 | `server/llm/prompts.py` |
| 落盘逻辑（付款表 / 条款改写） | `server/engine/builder.py` |
| 核对规则 | `server/engine/checker.py` |
| 编号/历史 | `server/api/store.py` |
| 模型 / API Key / 端口 | `.env`（勿提交，chmod 600） |

**改完必跑** `python scripts/test_pipeline.py`，全部 PASS 才算通过。

## 业务硬约束（违反会让合同不可用）

- **编号 11 位**：`YYYYMMDD` + 当日 3 位流水（>999 自动 4 位），**永不回补**；服务器时区必须 `Asia/Shanghai`（影响凌晨生成的编号日期）。
- **币种单一**：每份合同单一货币，金额标签随之替换（HKD / CNY）。
- **分期合计 = 总费用**：在 `derive_payment()` 入口硬校验（default/one_time/custom 全模式）；写错就 422，不入历史。
- **格式指纹**：核对器将生成文件 vs 模板逐段逐表比对，**非修改点必须零差异**；改模板后立刻重跑测试。
- **签署栏（手写签名、盖章、日期）保持空白**，由人工线下签。
- **模板固定文字**（2026-08-31 核实）：模板 4~7 号新办合同的"第二期款于 1 个工作日内支付"为模板原文，不可改。
- **生成失败不入历史下载列表**：核对未通过时 `status=failed`，下载路径返回 403。

## 环境/部署硬约束（运维必读）

- `.env` 路径必须在 `/opt/contract-agent/.env`（或本机项目根），含 `SILICONFLOW_API_KEY` / `SILICONFLOW_BASE_URL` / `LLM_MODEL` / `HOST` / `PORT`。
- systemd `WorkingDirectory=/opt/contract-agent/server`（代码以相对路径导入 `api/engine/llm` 包）。
- Nginx `proxy_read_timeout 300s`（AI 调用可达 2 分钟，默认 60s 会 504）。
- **8300 仅绑 127.0.0.1**（公网服务器）；Nginx 反代对外 80/443。
- `start.bat` 强制 CRLF（`.gitattributes` 锁死）；前端缓存关闭（`no_cache_html` 中间件）。
- 系统**无登录鉴权**——上线前必须加 Nginx Basic Auth 或 IP 白名单（DEPLOY.md 第十章）。