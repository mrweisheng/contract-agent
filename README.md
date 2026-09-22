# 华星智能合同生成系统

根据业务类型自动生成客户合同：选类型 → 填信息（支持自然语言，AI 回填）→ 确认付款计划 → 自动生成并三重核对 → 浏览器下载 docx。**模板只读、排版零变化、固定内容锁定。**

## 一、启动（Windows 服务器）

1. 安装 Python 3.10+ 和**锁版本**的依赖（只需一次；版本已经过回归测试，避免装出未验证的新版本）：
   ```
   pip install -r requirements.txt
   ```
2. 双击 `start.bat`（已纳入版本仓库，`.gitattributes` 强制 CRLF；如被改坏或路径不对，可运行 `python scripts/make_startbat.py` 重建）；
3. 团队成员浏览器访问 `http://服务器IP:8300`（本机即 http://127.0.0.1:8300；start.bat 监听 0.0.0.0，局域网内可用本机 IP 访问）。

Linux 服务器：`cd server && python3 -m uvicorn main:app --host 0.0.0.0 --port 8300`

**Ubuntu + Nginx + HTTPS 正式部署（域名 contract.eazycar.top）见 [DEPLOY.md](DEPLOY.md)。**

## 二、使用流程

1. **选业务类型**：卖车 / 现牌过户·高新 / 现牌过户·纳税 / 粤Z新办（选口岸：莲塘、深圳湾、港珠澳大桥、沙头角）；
2. **录入信息**（两种方式，可结合）：
   - 表单录入：逐项填写，金额自动显示大写；
   - 智能录入：一段自然语言 → AI 提取回填表单（高亮+AI标记）→ 核对修改；
   - **结合使用**：表单先填已知字段，未填项留空；调用 AI 提取时只会回填空字段，已填值不会被覆盖（前端按字段合并）。
3. **付款计划**三选一：
   - 按合同默认（模板原分期，只填金额/日期）；
   - 一次性付清（日期或事件条件）；
   - 自定义分期：自然语言描述 → AI 解析成每期"金额+触发条件"（支持具体日期/事件触发/混合）→ 界面逐期确认（合计必须等于总费用）→ 自动改写合同条款和付款表格；
4. **币种**：每单选港币或人民币（一份合同单一货币），金额标签随之替换；
5. **生成 → 三重核对**：
   - **规则校验（硬拦截）**：必填完整、无残留空位、大写=数字、分期合计=总价、币种唯一、编号格式；
   - **格式指纹（硬拦截）**：生成文件与模板逐段逐表比对样式与文字，**非修改点必须零变化**；
   - **AI 复核（提示性）**：语义比对客户约定与成品合同；不通过只标黄字警告，不阻断下载；
6. **合约编号**：服务端自动分配 11 位（日期8位+当日3位流水），分配即占位、永不重复；生成历史可查、可重复下载。

## 三、目录结构

```
contract-agent/
├─ .env                # LLM 配置（MiniMax API Key、模型）——勿外传，chmod 600
├─ .env.example        # .env 模板（提交用）
├─ .gitattributes      # 强制 *.bat 为 CRLF（cmd 对 LF 会截断解析）
├─ .gitignore
├─ requirements.txt    # 锁版本的依赖
├─ start.bat           # Windows 启动脚本（CRLF）
├─ web/                # 前端（Vue3 本地单页，含 vendor/vue.global.prod.js，无需联网CDN）
├─ server/
│  ├─ main.py          # 服务入口（uvicorn server.main:app）
│  ├─ templates/       # 7 份合同模板母版（只读，勿改）
│  ├─ engine/          # 落盘(builder) / 格式指纹+规则核对(checker) / 类型配置(types_config) / 金额大写(money) / docx底层操作(writer)
│  ├─ llm/             # LLM 客户端(client)与提示词(prompts)
│  ├─ api/             # 路由(routes) + 编号流水+SQLite历史(store)
│  └─ data/            # 运行时生成：contracts.db + out/ 成品合同（★含客户隐私，必备份）+ test_out/ 测试残留
├─ scripts/
│  ├─ test_pipeline.py # 回归测试（不调LLM，4类业务×3种付款模式）
│  └─ make_startbat.py # 重建 start.bat（CRLF）
├─ prototypes/         # 前端原型归档（HTML+research.md，不参与构建）
├─ DEPLOY.md           # Ubuntu + Nginx + HTTPS 部署手册
└─ README.md           # 本文件
```

## 四、修改模板 / 字段须知

- **模板**：`server/templates/` 是仓库内的主源；开发者本地另有一份 `E:\华星客服\简体\` 下的同名7 份作为非 git 备份（仅开发机可见），改模板后**两边同步**并重跑 `python scripts/test_pipeline.py` 验证；
- **表单字段 / 锚点**：全部在 `server/engine/types_config.py`，改一处即可（前端表单和落盘锚点都由它驱动）；
- **换模型/Key**：改 `.env` 即可，无需动代码。

## 五、注意事项

- **AI 响应有波动（重要）**：AI 提取/解析/复核依赖大模型，通常 5~40 秒，偶尔更久；界面上有"已等待 N 秒"提示，后台窗口会实时打印 `[LLM] 调用开始/成功，耗时 X 秒`。**uvicorn 的 POST 访问日志是请求完成后才打印的**，等待期间日志空白属正常，不代表卡死；若单次超过 2 分钟仍无结果，Ctrl+C 重启后重试（重启前确认 8300 端口未被旧进程占用）；
- 模板第 4~7 号新办合同的"第二期款于 1 个工作日内支付"为固定文字（2026-08-31 核实）；
- 签署栏（手写签名、盖章、日期）保持空白，供线下签署；
- 生成失败（核对未通过）时文件不入历史下载列表，按红色问题清单修正后重新生成。

## 六、上线必做（部署到公网域名后）

- **访问控制（无鉴权，必须补）**：系统当前**没有登录鉴权**——任何拿到网址的人都能生成合同、查看历史、下载合同（历史记录含客户姓名证件等隐私）。至少选其一：Nginx Basic Auth / 公司出口 IP 白名单。配置方法见 [DEPLOY.md 第十章](DEPLOY.md#十访问控制必做)；
- **数据备份（必做）**：`server/data/`（SQLite 历史 + 已生成合同 docx，含客户隐私）是**唯一**需要备份的目录，代码和模板可随时从仓库恢复。每日 cron 打包脚本见 [DEPLOY.md 第七章](DEPLOY.md#七数据备份必做)；
- **证书 / Nginx 超时 / 时区**：见 DEPLOY.md 第三、六章（AI 调用最长可达 2 分钟以上，Nginx 默认 60s 超时需调大；时区必须是 Asia/Shanghai 否则凌晨编号日期会算成前一天）。

## 开发模式（热更新）

```bash
# 终端 1：后端（改 Python 即时生效；先确认 8300 端口未被 start.bat 占用，否则冲突）
cd server
E:/Espressif/tools/python/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8300 --reload

# 终端 2：前端（改 app.js / style.css 自动刷新，API 自动代理到 8300）
cd web
npm install   # 首次
npm run dev   # 打开 http://localhost:5173
```

双击 start.bat 仍是免 Node 的直出模式（给非开发场景用），两种模式共用同一份代码。