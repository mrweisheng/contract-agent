# 部署文档：华星智能合同生成系统（Ubuntu 服务器）

> 面向运维的完整部署手册。目标环境：Ubuntu 22.04 / 24.04 LTS（自带 Python 3.10+；20.04 已 EOL 不再支持），域名 `contract.eazycar.top`（A 记录已解析到本服务器公网 IP）。
>
> 全程按章节顺序复制粘贴命令即可，每一步都附有验证方法。预计 30~40 分钟（含证书签发）。

---

## 一、系统概况（先了解再动手）

```
浏览器 ──HTTPS 443──▶ Nginx ──HTTP──▶ uvicorn / FastAPI（127.0.0.1:8300）──出站 HTTPS──▶ 硅基流动 LLM API
                     （反向代理+证书）        │
                                              ├─ web/            前端页面（由 FastAPI 直接托管，无需 Node.js）
                                              ├─ server/templates 7 份合同模板（只读）
                                              ├─ server/data/    SQLite 历史 + 生成的合同 docx（★需备份）
                                              └─ .env            LLM API Key（★敏感，勿外传）
```

| 项 | 说明 |
|---|---|
| 技术栈 | Python 3.10+ · FastAPI · SQLite（零外部数据库） |
| 进程模型 | 单进程 uvicorn（业务路由跑线程池，够内部团队用），由 systemd 常驻 |
| 前端 | 纯静态（Vue 本地文件），生产环境**不需要安装 Node/npm** |
| 外部依赖 | 仅需出站访问 `api.siliconflow.cn:443`（大模型接口） |
| 端口 | 对外只开 80/443；应用端口 8300 只绑 127.0.0.1，外网不可达 |

**两个必须提前知道的业务特性：**

1. **LLM 响应慢是正常的**：AI 提取/复核一次调用通常 5~40 秒、偶尔 2 分钟以上。Nginx 默认 60 秒超时会报 504，第六章配置里已调大，**不要删**。
2. **合同编号按日期+当日流水生成**（如 `20260904` + `001`），服务器时区必须是**东八区**，否则北京时间凌晨 0~8 点生成的编号日期会算成前一天。第三章第 1 步会设置。

---

## 二、服务器要求

- Ubuntu 22.04 / 24.04 LTS，1 核 2G 内存起步（无数据库、无编译，很轻）。20.04 已 EOL，且自带 Python 3.8 装不动新版依赖，不再支持。
- 磁盘：系统之外预留几 GB 即可（每份合同 docx 约几十 KB）。
- 入站：80、443 对公网开放；22 按贵司惯例。
- 出站：443（LLM API、apt 源、证书续期）。
- DNS：确认 `contract.eazycar.top` 的 A 记录已指向本机公网 IP：

```bash
dig +short contract.eazycar.top
# 应返回本机公网 IP。若未生效先处理 DNS，否则第六章证书签发会失败。
```

---

## 三、基础环境准备

以下命令均以 root（或 sudo）执行。

### 1. 时区（必做，影响合同编号）

```bash
timedatectl set-timezone Asia/Shanghai
timedatectl   # 确认 Time zone: Asia/Shanghai (CST, +0800)
```

### 2. 安装系统软件

```bash
apt update
apt install -y python3 python3-venv python3-pip nginx git curl unzip
```

### 3. 创建运行用户和目录

```bash
# -M 不建家目录：/opt/contract-agent 留给第四章 git clone 自行创建。
# 若用 -m，skel 会往该目录拷入 .bashrc 等文件，git clone 会因「目录非空」直接失败。
useradd -r -M -d /opt/contract-agent -s /usr/sbin/nologin contract
```

---

## 四、部署应用代码

### 1. 上传代码到 /opt/contract-agent

方式 A（推荐，代码在 Git 仓库）：

```bash
cd /opt
git clone <你们的仓库地址> contract-agent
```

方式 B（没有仓库，从开发机打包上传）：在开发机把项目打包（**排除 `server/data/out/`、`server/data/*.db`、`.env`），
上传后在服务器解压到 `/opt/contract-agent`，例如：

```bash
# 开发机（Windows PowerShell）打包：
#   tar -a -c -f contract-agent.zip --exclude=server/data --exclude=.env --exclude=node_modules .
# 上传后在服务器：
cd /opt && unzip /root/contract-agent.zip -d contract-agent
```

目录结构应如下（重点确认 `server/`、`web/`、`requirements.txt` 都在）：

```bash
ls /opt/contract-agent
# README.md  DEPLOY.md  requirements.txt  server  web  ...
```

### 2. Python 虚拟环境 + 依赖

```bash
python3 -m venv /opt/contract-agent/venv
/opt/contract-agent/venv/bin/pip install -r /opt/contract-agent/requirements.txt
# 国内服务器若下载慢，可用镜像：
# /opt/contract-agent/venv/bin/pip install -r /opt/contract-agent/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 创建 .env（敏感配置，git 里没有，必须手工建）

```bash
cat > /opt/contract-agent/.env <<'EOF'
# LLM 配置（硅基流动 SiliconFlow，OpenAI 兼容接口）
SILICONFLOW_API_KEY=<向开发负责人索取真实的_API_KEY>
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash

# 服务配置（systemd 启动参数已显式指定，这里的 HOST/PORT 仅直跑时生效）
HOST=127.0.0.1
PORT=8300
EOF
chmod 600 /opt/contract-agent/.env
```

### 4. 目录属主（应用运行用户必须可写 data 目录）

```bash
chown -R contract:contract /opt/contract-agent
```

### 5. 冒烟测试（手动跑一次，确认能起来）

```bash
cd /opt/contract-agent/server
sudo -u contract /opt/contract-agent/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8300
```

另开一个终端验证（Ctrl+C 停止前台进程后再继续下一步）：

```bash
curl -s http://127.0.0.1:8300/api/health
# 期望输出：{"status":"ok","model":"deepseek-ai/DeepSeek-V4-Flash","key_set":true}
# key_set 为 false 说明 .env 没建好或路径不对（必须在 /opt/contract-agent/.env）

# 可选：跑一遍离线回归测试（不调用 LLM、不花钱，22 个用例应全部 PASS）
cd /opt/contract-agent && venv/bin/python scripts/test_pipeline.py
```

---

## 五、systemd 常驻服务

```bash
cat > /etc/systemd/system/contract-agent.service <<'EOF'
[Unit]
Description=Huaxing Contract Generation System (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=contract
Group=contract
# ★ 工作目录必须是 server/：代码以相对路径导入 api/engine/llm 包
WorkingDirectory=/opt/contract-agent/server
ExecStart=/opt/contract-agent/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8300
Restart=always
RestartSec=3
# 崩溃后自动拉起；开机自启由此实现
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now contract-agent
systemctl status contract-agent --no-pager    # 应显示 active (running)
```

常用运维命令：

```bash
systemctl restart contract-agent      # 重启
systemctl stop contract-agent         # 停止
journalctl -u contract-agent -f       # 实时看日志（LLM 调用开始/耗时都会打在这里）
journalctl -u contract-agent --since "1 hour ago"
```

---

## 六、Nginx + HTTPS（contract.eazycar.top）

### 1. 站点配置

```bash
cat > /etc/nginx/sites-available/contract-agent <<'EOF'
server {
    listen 80;
    server_name contract.eazycar.top;

    # 上传的文本描述很小，10m 足够
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8300;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # ★ 关键：AI 生成一次最长可达 2 分钟以上，Nginx 默认 60s 会中途断开报 504
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/contract-agent /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default        # 移除默认站点（可选，避免端口冲突歧义）
nginx -t && systemctl reload nginx
```

先验证 HTTP 可用（此时用 IP 或域名均可）：

```bash
curl -s http://contract.eazycar.top/api/health
# 期望：{"status":"ok",...}
```

### 2. 签发 HTTPS 证书（Let's Encrypt 免费证书，自动续期）

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d contract.eazycar.top
# 按提示输入邮箱、同意条款；询问是否跳转 HTTPS 时选 2（强制 HTTPS）
# certbot 会自动改写上面的 server 块并加 301 跳转，无需手工处理
```

续期验证（certbot 装好后自带 systemd 定时器，一般无需管）：

```bash
certbot renew --dry-run    # 输出 Congratulations 类似字样即正常
```

### 3. 防火墙

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
# 8300 不放行：应用只监听 127.0.0.1，本就外部不可达
```

### 4. 最终验收

```bash
curl -s https://contract.eazycar.top/api/health
# 期望：{"status":"ok","model":"...","key_set":true}
```

浏览器打开 `https://contract.eazycar.top`：应看到「華星 · 智能合同生成系统」页面，
左侧可切换 4 类业务，随便选一类填写测试数据点「生成合同 →」，10~60 秒后出现「核对通过」和下载按钮即部署成功。

---

## 七、数据备份（必做）

**需要备份的只有 `/opt/contract-agent/server/data/`**（SQLite 历史 + 已生成合同 docx，含客户隐私），
代码和模板可随时从仓库恢复。

```bash
mkdir -p /backup
cat > /etc/cron.daily/contract-backup <<'EOF'
#!/bin/sh
# 每天打包 data 目录，保留最近 30 天。
# SQLite 热拷贝可能得到损坏副本：先秒级停服再打包，打包完立即恢复。
systemctl stop contract-agent
tar -czf /backup/contract-data-$(date +%F).tar.gz -C /opt/contract-agent/server data
systemctl start contract-agent
find /backup -name 'contract-data-*.tar.gz' -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/contract-backup

# 手动验证一次：
/etc/cron.daily/contract-backup && ls -lh /backup/
# 建议另行把 /backup 同步到异机/对象存储（rsync/OSS 均可，按贵司现有备份体系接）
```

**恢复步骤**（备份包在停服状态下打包，一致性无忧；恢复前同样先停服务）：

```bash
systemctl stop contract-agent
rm -rf /opt/contract-agent/server/data
tar -xzf /backup/contract-data-<日期>.tar.gz -C /opt/contract-agent/server
chown -R contract:contract /opt/contract-agent/server/data
systemctl start contract-agent
```

---

## 八、日常运维

### 更新代码（发新版）

```bash
sudo -u contract git -C /opt/contract-agent pull          # 或按贵司方式上传覆盖
/opt/contract-agent/venv/bin/pip install -r /opt/contract-agent/requirements.txt   # 依赖有变时
systemctl restart contract-agent
```

### 回滚

```bash
sudo -u contract git -C /opt/contract-agent checkout <上一个版本号/commit>
systemctl restart contract-agent
```

### 换 LLM 模型 / 换 API Key

只改 `/opt/contract-agent/.env` 中的 `LLM_MODEL` 或 `SILICONFLOW_API_KEY`，然后 `systemctl restart contract-agent`，无需动代码。改完用 `curl -s https://contract.eazycar.top/api/health` 确认 `model` 字段已变化。

---

## 九、常见问题（FAQ）

| 现象 | 原因与处理 |
|---|---|
| 页面点「生成」约 60 秒后报 **504 Gateway Timeout** | Nginx 超时没调大或被改掉了。确认第六章配置中 `proxy_read_timeout 300s;` 存在后 `nginx -t && systemctl reload nginx` |
| 生成等 1~2 分钟 | **正常**。AI 复核依赖大模型，界面上有「已等待 N 秒」提示；`journalctl -u contract-agent -f` 可看到 `[LLM] 调用开始/成功` 实时日志 |
| 点「AI 提取」报 **502 LLM 抽取失败** | ① `.env` 的 API Key 无效或账户欠费（health 里 `key_set` 只能证明填了，不能证明有效）；② 服务器出站访问 `api.siliconflow.cn` 被防火墙拦了：`curl -s https://api.siliconflow.cn` 测试连通性 |
| 服务起不来，日志报 `ModuleNotFoundError: No module named 'api'` | systemd 的 `WorkingDirectory` 不是 `/opt/contract-agent/server`，对照第五章修正 |
| 日志报 Permission denied，涉及 `server/data` | 目录属主不对：`chown -R contract:contract /opt/contract-agent` |
| 下载的合同文件名乱码 | 系统缺 UTF-8 locale（Ubuntu 默认有）。`locale` 检查，异常时 `apt install locales && dpkg-reconfigure locales` 选 `C.UTF-8` |
| 凌晨生成的合同编号日期是「昨天」 | 时区被改回了 UTC：重新执行 `timedatectl set-timezone Asia/Shanghai` |
| 想限制只有公司网络能访问 | 见第十章「访问控制」 |

---

## 十、访问控制（必做）

系统当前**没有登录鉴权**——任何拿到网址的人都能生成合同、查看历史、下载合同（历史记录含客户姓名证件等隐私）。已上公网域名，以下两案**必选其一**：

**方案 A：Nginx Basic Auth（最简单，全员共用一个账号或一人一个）**

```bash
apt install -y apache2-utils
htpasswd -c /etc/nginx/.htpasswd huaxing        # 输入两遍密码，即全员共用账号
# 一人一个账号就重复执行（去掉 -c）：htpasswd /etc/nginx/.htpasswd zhangsan
```

然后在 `/etc/nginx/sites-available/contract-agent` 的 `location / { }` 内加两行：

```nginx
        auth_basic "Huaxing Contract System";
        auth_basic_user_file /etc/nginx/.htpasswd;
```

`nginx -t && systemctl reload nginx` 生效。此后访问网页会先弹账号密码框。

**方案 B：IP 白名单（适合固定办公网络出口）**

`location / { }` 内加：

```nginx
        allow 203.0.113.0/24;   # 换成公司出口 IP 段
        deny all;
```

> 另：`.env`（API Key）务必保持 `chmod 600` 且属主为 contract 用户，备份包同样含隐私，存放位置按敏感数据管理。

---

## 附：验收清单（部署完成逐项打勾）

- [ ] `timedatectl` 显示 Asia/Shanghai
- [ ] `systemctl status contract-agent` 为 active (running)，且服务器重启后能自动拉起（`systemctl is-enabled contract-agent` → enabled）
- [ ] `curl -s https://contract.eazycar.top/api/health` 返回 `"status":"ok"` 且 `key_set:true`
- [ ] 浏览器打开 `https://contract.eazycar.top` 正常显示，证书有效（地址栏无警告）
- [ ] 完整走一单：选类型 → 填表单（或 AI 提取）→ 生成 → 核对通过 → 下载 docx 能用 Word 打开
- [ ] 生成历史抽屉里能看到刚才那单，可重新下载
- [ ] `ls /backup/` 有当日备份包，cron 已生效
- [ ] Basic Auth 或 IP 白名单已配置（第十章，必做）
