# 服务器状态大屏（Sea Glass Dashboard）

一块「开机就能看」的服务器状态页：黑底、海底气泡、一只看板娘，卡片里是容器、看门狗、磁盘内存、备份、可选服务、最近事件。
外面套一层自己的登录网关（账号 + 口令 + 算术验证码），Caddy 只放行带正确 Cookie 的请求。

整套东西**不含任何一台机器的具体值**：IP、域名、QQ 号、令牌、路径、容器名全是占位符或环境变量，改配置就能用在你自己的机器上。

> 想给 AI 助手看的那份说明在 **[AGENTS.md](AGENTS.md)** —— 它写的是「什么能动、什么不能动、怎么验证」。
> 这份 README 是给人看的。

---

## 目录

1. [长成什么样](#1-长成什么样)
2. [两种用法，先选一种](#2-两种用法先选一种)
3. [目录结构](#3-目录结构)
4. [快速开始 A：宿主直装（推荐）](#4-快速开始-a宿主直装推荐)
5. [快速开始 B：Docker 只跑大屏](#5-快速开始-bdocker-只跑大屏)
6. [配置参考](#6-配置参考)
7. [health.json 数据结构](#7-healthjson-数据结构)
8. [那只鲸鱼（立绘/头像/favicon）](#8-那只鲸鱼立绘头像favicon)
9. [登录、Cookie 与安全边界](#9-登录cookie-与安全边界)
10. [运维手册](#10-运维手册)
11. [排错速查](#11-排错速查)
12. [接入你自己的业务系统（MaiBot / SnowLuma 实操）](#12-接入你自己的业务系统)
13. [已知限制](#13-已知限制)
14. [许可与第三方](#14-许可与第三方)

另有三份独立文档，每份都写了「给人看」和「给 AI 执行」两个版本：

| 主题 | 给人看 | 给 AI 助手执行 |
|---|---|---|
| 运行环境（要什么机器、实测过什么） | [部署环境.md](docs/部署环境.md) | ——（内容已压缩进 [AGENTS.md](AGENTS.md) §5） |
| HTTPS 与证书（自签 / Let's Encrypt / 已有证书） | [HTTPS与证书.md](docs/HTTPS与证书.md) | [HTTPS与证书-给AI.md](docs/HTTPS与证书-给AI.md) |
| **接入 MaiBot / SnowLuma**（怎么把业务数据接进来） | [接入-MaiBot与SnowLuma.md](docs/接入-MaiBot与SnowLuma.md) | [接入-MaiBot与SnowLuma-给AI.md](docs/接入-MaiBot与SnowLuma-给AI.md) |

---

## 1. 长成什么样

- 顶部：标题 + 采集时间 + 一个气泡（看板娘会根据数据好坏换表情——正常是扑腾、小情况是蔫、出事是宕机脸）
- 横幅：`正常` / `正常（数据偏旧）` / `有点小情况` / `出事了` 四态，颜色跟着变
- 卡片：容器状态、看门狗、主机（负载/内存/Swap/磁盘/运行时长/主机名）、自动备份、联网服务（可选）、数据目录、最近事件
- 页脚：数据来源说明 + 三个短链（立即刷新 / 管理后台 / 退出登录）
- 手机宽度下自动单列；开了「减弱动态效果」只停动画，不把画面整个藏掉

数据全部来自同目录下的 `health.json`，由宿主机上的采集器每 2 分钟写一次。**页面本身没有任何后端**，纯静态文件。

### 1.1 先在本机看一眼（30 秒，不用服务器）

不想先折腾证书和 Docker，只想看它长什么样：

```bash
python3 tools/demo.py            # 也可以用 py tools/demo.py（Windows）
# 打开 http://127.0.0.1:8080/dash.html
```

它把 `site/` 和一份**示意数据**（`examples/health.json`，全是 `example-*` 这种假值）摆进临时目录，
起一个本地静态服务器；改那份 JSON、刷新页面就能看到变化，Ctrl-C 结束，临时目录自动删掉。

| 参数 | 作用 |
|---|---|
| `--data 文件.json` | 换一份示意数据（比如你自己造的极端情况） |
| `--port 9000` | 换端口（默认 8080，被占用会自动往后找） |
| `--open` | 起完自动打开浏览器 |
| `--keep-times` | 原样使用数据里的时间（默认会把所有时间戳挪到「现在」，否则一开就是「数据陈旧」） |
| `--mood ok\|warn\|bad\|offline` | 直接看某个状态：正常 / 数据偏旧 / 出事 / 读不到数据（掉线），配合下面 §8 的状态图 |

> 为什么不用 `python -m http.server`：Windows 版 Python 把 `.svg` 认成 `image/svg`（少了 `+xml`），
> 浏览器直接拒渲染，你会看到「立绘全是破图」——那不是模板的问题。`demo.py` 把 MIME 钉死了。

这也就是「数据区预留」的意思：**卡片的槽位和字段都在代码里写好了，只是没有你的数据**。
真部署时，采集器没启用的那一块（比如没配 MCP、没有备份脚本）整张卡片不渲染，不会显示空表格；
想让它出现，就在 `collector/health.config.json` 里把对应块打开（见 §6.2）。

---

## 2. 两种用法，先选一种

| 场景 | 用哪套 | 需要什么 |
|---|---|---|
| 就想在自己服务器上看状态，后台已有别的东西 | **A. 宿主直装**（`deploy/install.sh`） | Ubuntu/Debian + systemd + 已装好的 Caddy |
| 不想碰宿主，全靠容器 | **B. Docker 只跑大屏**（`deploy/docker-compose.yml`） | Docker + docker compose v2 |

两套用的是同一份前端、同一个采集器、同一份 Caddy 站点配置，只是启动方式不同。

### 2.1 跑在什么环境上

一句话：**任意现代 Linux + Docker + Python 3.8+**，没有数据库、没有 Node、没有 `pip install`、不需要外网。
实测过两种环境——Ubuntu 22.04 / 2 核 2 G / 40 G 盘（Caddy 2.4.6 与 2-alpine 都验过），以及 Windows 10/11 + Python 3.14 的开发机（`tools/demo.py` 就在这上面调出来的）。

最低要求、端口目录清单、资源占用、浏览器基线、已知不支持的情况，全在 **[docs/部署环境.md](docs/部署环境.md)** 里。

---

## 3. 目录结构

```
.
├─ site/                        # 纯静态前端，直接丢给 Caddy 的 file_server
│  ├─ dash.html                 #   主页面：样式 + 渲染逻辑都在这一个文件里
│  ├─ config.js                 #   唯一的「改这里」的地方：标题/链接/文案/署名
│  └─ assets/
│     ├─ mascot.webp            #   看板娘整身（默认：鲸鱼娘同人图，CC BY-NC-SA 4.0）
│     ├─ mascot-head.webp       #   小头像（页头/横幅/卡片标题共用）
│     ├─ mascot.svg             #   占位形象（自绘，无版权问题，可当回退/替身）
│     ├─ mascot-head.svg        #   占位小头像
│     ├─ favicon.svg            #   标签页图标
│     └─ LICENSE-art.md         #   两套图的来源与协议（换图前先看这个）
├─ collector/
│  ├─ health.py                 # 采集器：docker/磁盘/内存/备份/MCP → health.json（纯标准库）
│  └─ health.config.example.json# 采集器配置模板（容器名、路径、开关）
├─ auth/
│  ├─ auth_gate.py              # 登录网关：账号口令 + 算术验证码 + Cookie 会话（纯标准库）
│  ├─ make_auth_conf.py         # 生成 auth.json（口令哈希、salt、会话令牌、验证码密钥）
│  ├─ auth.json.example         # auth.json 结构示例（全是占位符）
│  └─ assets/                   # 可选：登录页要用的立绘（没有就用 site/assets 里的）
├─ deploy/
│  ├─ Caddyfile                 # 主配置：全局设置 + import sites/*.caddy
│  ├─ sites/dash.caddy          # 站点：登录 → 证书 → 大屏 → 短链 → 业务后台 → 兜底
│  ├─ sites-examples/alt-site.caddy  # 可选第二个站点（示例，不启用）
│  ├─ dashboard.env.example     # 全部环境变量（含怎么生成令牌）
│  ├─ gen_certs.sh              # 自签 CA + 服务端证书（含 SAN）
│  ├─ install.sh                # 宿主直装脚本（幂等）
│  ├─ docker-compose.yml        # 只用 Docker 跑大屏 + 网关
│  ├─ systemd/                  # dash-auth.service / dash-health.service + .timer
│  └─ fail2ban/                 # filter.d / action.d / jail.d 三件套
├─ tools/
│  ├─ demo.py                   # 本机演示：摆好示意数据起静态服务，不用服务器（纯标准库）
│  └─ verify_deploy.py          # 端到端自检：该拦的拦住、该放的放行（纯标准库）
├─ examples/                    # health.json / state.json / backup.json 的示意数据（全是 example-*）
├─ docs/                        # 教程与说明（不想读整个 README 就看这几份）
│  ├─ 部署环境.md                     #   要什么机器、实测过什么、端口目录清单
│  ├─ 接入-MaiBot与SnowLuma.md        #   人看的：改哪几个文件、每个字段什么意思
│  ├─ 接入-MaiBot与SnowLuma-给AI.md   #   AI 看的：字段契约、验证顺序、失败对照表
│  ├─ HTTPS与证书.md                  #   自签 / Let's Encrypt / 已有证书，手机怎么装根证书
│  └─ HTTPS与证书-给AI.md             #   AI 看的：四类判定、精确改法、验证顺序、禁区
├─ status/                      # 运行期目录：health.json、二维码、事件（不进仓库）
└─ AGENTS.md                    # 给 AI 助手看的操作说明
```

设计上只有一条硬规矩：**站点配置拆成文件**，`deploy/sites/*.caddy` 每个文件一个站点，`Caddyfile` 只负责 `import`。想加站点就往目录里丢文件，不用在两处同步一百多行。

---

## 4. 快速开始 A：宿主直装（推荐）

前提：Ubuntu/Debian、有 systemd、已经装好 Caddy（`apt install caddy` 或官方源）。

```bash
git clone <这个仓库> ~/dashboard-src
cd ~/dashboard-src
sudo ./deploy/install.sh
```

脚本会（幂等，重复跑不会覆盖已存在的东西）：

1. 建系统用户 `dash` 和目录 `/opt/dashboard`
2. 把 `site/ collector/ tools/ auth/ deploy/` 拷进去
3. 生成自签证书到 `/opt/dashboard/certs/`（跑之前会问你要给哪个域名/IP 签）
4. 交互式问账号口令 → 写 `/opt/dashboard/auth/auth.json`
5. 写 `/opt/dashboard/dashboard.env`（令牌、短链 key、路径，权限 600）
6. 装 systemd：`dash-auth.service`（常驻）+ `dash-health.timer`（每 2 分钟跑采集器）
7. 打印剩下要手动做的事

装完还差三步（脚本会再念一遍）：

```bash
# 1) 告诉 Caddy 用这份配置
sudo cp -r /opt/dashboard/deploy/Caddyfile.template /opt/dashboard/deploy/sites /etc/caddy/  # Caddyfile.template 改名成 Caddyfile
#    站点文件在这：/opt/dashboard/deploy/sites/*.caddy
#    环境变量：让 caddy.service 读 /opt/dashboard/dashboard.env
#      sudo systemctl edit caddy
#      [Service]
#      EnvironmentFile=/opt/dashboard/dashboard.env
#    注意：模板里的 {$DASH_STATUS_DIR} 默认是 /srv/dashboard/status，
#    dashboard.env 里会写成 /opt/dashboard/status，别把两处搞混。
sudo systemctl restart caddy

# 2) 放行端口（默认 8443）
sudo ufw allow 8443/tcp        # 云主机还要在安全组里放行

# 3) 自检（最值得跑的一步）
cd /opt/dashboard
sudo -u dash DASH_BASE=https://127.0.0.1:8443 DASH_USER=admin DASH_PW='你的口令' \
  DASH_CA=/opt/dashboard/certs/ca.crt python3 tools/verify_deploy.py
```

看到 `全部通过` 就可以用了：`https://<你的地址>:8443/status/dash.html`。

**第一次打开会证书告警**（自签的，正常）。手机要装一次 `ca.crt`：

```
https://<你的地址>:8443/ca.crt      ← 浏览器里直接下载
```

装证书的完整步骤（Windows / macOS / Android / iOS / Firefox）、SAN 怎么核对、以及为什么 http 下登录会死循环，单开了一页：**[HTTPS 与证书](docs/HTTPS与证书.md)**。有域名的话那条路更省事 —— Caddy 自己申请 Let's Encrypt，用户端不用装任何东西。

---

## 5. 快速开始 B：Docker 只跑大屏

```bash
cd deploy
cp dashboard.env.example dashboard.env
$EDITOR dashboard.env            # 至少要改 DASH_TOKEN
# DASH_TOKEN 从哪来：先跑一次 auth 配置生成
python3 ../auth/make_auth_conf.py ../auth/auth.json   # 交互问口令，输出 session_token
docker compose up -d
```

这套编排里只有两个服务：`auth`（不发布端口，只在内部给 Caddy 用）和 `caddy`。
状态目录 `../status` 用 rw 挂进去（宿主的采集器写、Caddy 读），日志目录 `./logs` 单独挂出来给宿主的 fail2ban 读。

`status/dash.html` 需要你自己放进去 —— 仓库里的 `site/` 是「资源目录」，`status/` 是「Caddy 的站点根」。不想手动拷：

```bash
mkdir -p ../status && cp ../site/*.html ../site/*.js ../status/ && cp -r ../site/assets ../status/
```

（宿主直装时 `install.sh` 就是这么摆的，Docker 这条路要自己来一次。）

---

## 6. 配置参考

### 6.1 `site/config.js`（前端唯一要改的文件）

| 字段 | 作用 | 备注 |
|---|---|---|
| `title` | 页面标题（`<title>` 和 h1） | |
| `refreshMs` | 自动刷新间隔（毫秒），默认 30000 | 小于 5000 会被按 5000 处理 |
| `footer` | 页脚第一行（支持 HTML，如 `<code>`） | |
| `links` | 页脚右侧链接数组 `{text, href}` | `http(s)://` 自动 `target=_blank` |
| `credit` | 底部署名/素材授权说明 | **留空则整块隐藏**；用别人的立绘必须在这里写作者与协议 |
| `labels` | 卡片标题文案（`containers/watchdog/host/backup/mcp/data/events`） | 每个卡片标题右上角的小标签（`tags`）也能改 |
| `mood` | 看板娘三句话 `{ok, warn, bad}` | 只影响气泡文字，不影响判定 |

改完刷新页面即可，**不需要重建任何东西**（`config.js` 是静态文件）。

### 6.2 `collector/health.config.json`

```jsonc
{
  "status_dir": "/opt/dashboard/status",      // health.json 写这里（必须和 Caddy 的站点根一致）
  "data_dir":   "/opt/dashboard/data",        // 算目录体积用
  "timezone_offset_hours": 8,
  "stale_after_sec": 420,                     // 超过这么久没更新，页面判「数据偏旧」
  "containers": [                             // 想看几个就写几个，label 显示在卡片里
    {"name": "app", "label": "业务容器", "required": true},
    {"name": "dash-caddy",  "label": "网关容器", "required": true}
  ],
  "mcp":      {"enabled": true, "probe_url": "http://127.0.0.1:8765/healthz", "timeout": 3},
  "probes": [                                 // 想盯几个 HTTP 端口就写几条（401/403/404 也算「通」）
    {"name": "webui", "label": "业务 WebUI", "url": "http://127.0.0.1:5099/", "required": false, "timeout": 4}
  ],
  "watchdog": {"enabled": true, "state_file": "state.json", "events_file": "events.log", "qr_file": "qr.png"},
  "backup":   {"enabled": true, "report_file": "backup.json", "schedule": "每日 04:00"},
  "databases":{"enabled": true, "suffixes": ["message.db", "emoji.db"], "limit": 6},
  "scan_file_cap": 20000                       // 统计目录体积时最多走多少个文件（防卡死）
}
```

所有键都可缺省；缺了就用内置默认值，文件不存在也不报错。**相对路径按配置文件所在目录解析。**

`required: true` 的容器没在运行 → 页面进「出事」态。不写就是「只显示，不判死」。

`probes` 是「探几个 HTTP 端口通不通」：`200/204/301/302/401/403/404` 都算通（`401` 是「要登录」，不是挂了），只有连不上/超时才判死。`required: true` 的探活失败会把横幅判红，**先手工 `curl` 确认再升 required**。
容器内端口（比如 OneBot 的 `3001`）宿主探不到，别写进这里 —— 交给看门狗用 `docker exec` 探。

### 6.3 `deploy/dashboard.env`

| 变量 | 默认 | 说明 |
|---|---|---|
| `DASH_HTTPS_PORT` | `8443` | Caddy **容器内**监听端口（Caddyfile 站点地址用它） |
| `DASH_PUBLISH_PORT` | `8443` | 宿主发布端口（Docker 那套用） |
| `DASH_CERT_FILE` / `DASH_KEY_FILE` | `/etc/caddy/certs/...` | 证书 |
| `DASH_CERTS_DIR` | `/etc/caddy/certs` | `/ca.crt` 从这取 |
| `DASH_STATUS_DIR` | `/srv/dashboard/status` | 站点根（`/status/*` strip_prefix 之后） |
| `DASH_ACCESS_LOG` | `/var/log/caddy/access.log` | 给 fail2ban 读 |
| `DASH_AUTH_UPSTREAM` | `127.0.0.1:8766` | 登录网关（Docker 里写 `auth:8766`） |
| `DASH_COOKIE` | `DashSession` | Cookie 名，要和网关一致 |
| `DASH_TOKEN` | `__SET_ME__` | **必须等于 auth.json 的 `session_token`** |
| `DASH_SHORT_KEY` | `disabled` | 短链钥匙；`disabled` = 路径不存在 |
| `DASH_APP_UPSTREAM` | `127.0.0.1:8001` | 登录后的「业务后台」（你的 WebUI，随便哪个都行） |
| `DASH_ALT_PORT` / `DASH_ALT_UPSTREAM` | `8445` / `127.0.0.1:5099` | 第二个站点（示例配置用） |
| `DASH_SITES_GLOB` | `/etc/caddy/sites/*.caddy` | 站点文件目录 |

两个「故意的坑人默认值」：`DASH_TOKEN=__SET_ME__`、`DASH_SHORT_KEY=disabled`。
它们是**进不去**而不是**全放行** —— 忘了配的时候宁可打不开，也不要任何人拿着任意 Cookie 就能进。

### 6.4 `auth/auth.json`

```json
{
  "username": "admin",
  "password_hash": "…",     // scrypt(n=2^14, r=8, p=1, dklen=32)
  "salt": "…",
  "session_token": "…",     // 同步进 Caddy 的 DASH_TOKEN
  "captcha_key": "…",       // 验证码 HMAC 签名密钥
  "title": "服务器状态大屏",  // 可选
  "landing": "/status/dash.html"  // 可选
}
```

只由 `make_auth_conf.py` 生成，`chmod 600`。口令只存哈希，**丢了只能重新生成**（会连带换 `session_token`，记得同步 Caddy）。

---

## 7. `health.json` 数据结构

`schema: 2`。缺字段一律按「没这项」处理，前端不会崩。

完整可跑的样例在 [`examples/health.json`](examples/health.json)，下面这份是同一份结构带注释的版本：

```jsonc
{
  "schema": 2,                          // 固定 2
  "generated_at": "2026-01-01 12:00:00",
  "generated_ts": 1767240000,           // 秒级时间戳，页面用它算「多久前」
  "stale_after_sec": 420,               // 超过就提示「数据偏旧」
  "overall": "ok",                      // 只有 ok / bad 两种：problems 非空即 bad
  "problems": [],                       // 横幅文案，一条一个字符串
  "host": {"hostname": "example-host", "cpu_count": 2, "uptime_sec": 1123200,
           "load1": 0.14, "load5": 0.21, "load15": 0.19},
  "disk": {"total": 107374182400, "used": 64424509440, "free": 42949672960, "percent": 60.0},
  "mem":  {"total": 8589934592, "available": 5368709120, "used": 3221225472,
           "percent": 37.5, "swap_total": 0, "swap_used": 0},
  "containers": [{"name": "example-app", "label": "业务容器", "required": true,
                  "state": "running", "running": true, "restart_count": 0, "health": null,
                  "image": "example/app:latest", "started_at": "…", "uptime_sec": 14400}],
  "watchdog": {"state": "online", "since": "2026-01-01 11:12:31", "since_epoch": 1767237151,
               "duration_sec": 2849, "down_today": 1, "container_running": true,
               "last_check": "2026-01-01 11:59:45", "qr": false},
  "backup": {"last_backup": "2026-01-01 04:00:12", "file": "backup-20260101-0400.tar.gz",
             "size_bytes": 536870912, "files": 128, "oss": "已上传", "ok": true,
             "schedule": "每日 04:00"},
  "mcp": {"ok": true, "status": 200, "latency_ms": 7, "body": "{\"ok\": true}"},
  "probes": [{"name": "gateway", "label": "网关 WebUI", "required": false,
              "ok": true, "status": 200, "latency_ms": 11},
             {"name": "worker", "label": "另一个后台", "required": false,
              "ok": false, "error": "connection refused"}],
  "events": ["2026-01-01 11:59:45  online  容器在跑，WebSocket 在听"],   // 原样字符串，最多取 events_tail 行
  "databases": [{"path": "data/app/message.db", "size": 73400320}],
  "data_dir_bytes": 2147483648,
  "qr": {"exists": true, "mtime": "2026-01-01 11:58:02", "age_sec": 118, "size": 8192}
}
```

想加自己的卡片：在 `health.py` 里加一个 `collect_xxx()` 返回 dict，塞进 payload，然后在 `dash.html` 的 `render()` 里加 `card("标题", …)`。**注意卡片里不要渲染出主机名、IP、路径这类东西**（这块屏可能被截图发出去）。

---

## 8. 那只鲸鱼（立绘/头像/favicon）

默认形象是社区那只**鲸鱼娘**（chibi 女仆版），页头小头像、状态横幅、卡片标题、右下角背景那只，
全是从同一套图里取的。来源与协议写在 [`site/assets/LICENSE-art.md`](site/assets/LICENSE-art.md)：

- 文件：`site/assets/mascot.webp`（整身）、`site/assets/mascot-head.webp`（头像）
- 协议：**CC BY-NC-SA 4.0** —— 署名要留、不能商用、再分发沿用同协议
- 署名已经写进 `config.js` 的 `credit`（页面底部那一行），**别删**

### 想换成自己的图

三件套由 `config.js` 的 `assets` 决定，改配置就行，不用动 `dash.html`：

```js
assets: {
  mascot: "assets/mascot.webp",      // 看板娘整身（也用在两只游动的小鲸上）
  head:   "assets/mascot-head.webp", // 小头像：页头 logo、横幅角标、卡片标题
  deep:   "assets/mascot.webp"       // 背景那只大的（压到 7% 透明度 + 模糊）
}
```

| 位置 | 尺寸建议 | 取哪个字段 |
|---|---|---|
| 顶部整身立绘 | 高约 480px，透明底 | `mascot` |
| 小头像 | 正方形，≥96px | `head` |
| 页面背景那只 | 同 `mascot` 即可，也可单独给一张大图 | `deep` |
| 标签页图标 | `site/assets/favicon.svg` | 直接换文件 |
| 登录页立绘 | `auth/assets/` 或 `site/assets/` | 网关按扩展名自动找 |

**回退链**：`assets` 指向的图加载失败 → 自动换成 `mascot.svg` / `mascot-head.svg` 占位图 →
两张都失败才把那只藏起来（不留破图）。所以只想用自绘占位形象的人，把 `assets` 三个值都写成
`.svg`、把两个 `.webp` 删掉就行。

**用了别人的图，必须在 `config.js` 的 `credit` 里写作者和协议** —— 留空会整块隐藏，等于没署名。

### 状态怎么表达（正常 / 偏旧 / 出事 / 掉线）

看板娘**只有一张图，不会换人**：状态靠「右上角贴纸 + 滤镜 + 横幅配色」表达，鲸鱼娘始终在那。

| 状态 | 什么时候出现 | 贴纸 | 看板娘 | 横幅 |
|---|---|---|---|---|
| `ok` | `overall=ok` 且数据新鲜 | 无 | 原色，轻轻浮动 | 绿「一切正常」 |
| `warn` | 数据偏旧 / 等扫码 / MCP 离线 / 探活失败 / 磁盘 80%+ | 黄色 **！** | 轻微降饱和，浮动变慢 | 黄「正常（数据偏旧）」或列出问题 |
| `bad` | `overall=bad`：容器没跑、看门狗判非在线、备份失败、磁盘 90%+ | 红色 **✕** | 灰度 + 垂下、地上一圈红光 | 红，列出全部问题 |
| `offline` | **压根读不到 `health.json`**（采集器没跑、路径不对、HTTP 404） | 灰色 **Zzz** | 变暗、慢呼吸 | 灰蓝「连不上采集器：HTTP xxx」+ 三步排查卡 |

想在自己的机器上挨个看一遍：

```bash
python3 tools/demo.py --mood ok
python3 tools/demo.py --mood warn
python3 tools/demo.py --mood bad
python3 tools/demo.py --mood offline     # 故意不写 health.json，页面就走掉线状态
```

**要真给每个状态换不同的图**，`config.js` 里还有个可选项 `assets.moods`（留空=不换）：

```js
assets: {
  mascot: "assets/mascot.webp",
  moods: {
    ok: "",                            // 空 = 用 mascot（就是鲸鱼娘）
    warn: "assets/mascot-warn.webp",   // 填了就换成这张
    bad: "assets/mascot-bad.webp",
    offline: "assets/mascot-offline.webp"
  }
}
```

填了以后 `data-mood="1"` 会挂在 `<img>` 上，CSS 不再叠灰度（免得换上去的图被染脏）。
这几张图要你自己准备；没有就全留空，贴纸+滤镜照样能看出状态。

---

## 9. 登录、Cookie 与安全边界

```
浏览器 ──TLS──> Caddy ──┬─ /login /logout         → auth（登录网关）
                        ├─ /ca.crt                → 证书文件（公开）
                        ├─ Cookie 命中 /status/*  → 大屏静态文件
                        ├─ Cookie 命中 其它路径   → 业务后台（反代）
                        └─ 其余（没 Cookie）      → auth（登录页）
```

- **Caddy 只做字面匹配**：`header Cookie *DashSession=<TOKEN>*`。它不认识账号密码，只认这一个字符串。所以 `DASH_TOKEN` 必须等于 `auth.json` 的 `session_token`，否则「登录成功但还在登录页」。
- **会话**：登录成功 → `302` + `Set-Cookie: DashSession=…; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000`。
- **验证码**：算术题，答案用 HMAC 签进 token，`TTL=600` 秒。题面和 token 都藏在页面里，不存服务端状态。
- **限速**：同一来源 600 秒内错 10 次 → 冷却 300 秒。**只数 401**，`health.json` 的轮询不计入。
- **fail2ban**（可选）：读 Caddy 的 JSON 访问日志，401 连击就封 IP。**必须封在 `DOCKER-USER` 链**——docker publish 的流量走 FORWARD 不走 INPUT，封 INPUT 的表现是「日志说 banned，人照样能连」。宿主直装 Caddy 时改用 `iptables-multiport` action。
- **短链** `/s/<key>/dash.html` 只是「隐藏门」，**不是免口令通道**：照样要 Cookie。含二维码的 `/qr.png`、`/index.html` 在这条路径下永远 404。
- **网关别 publish 端口**。它只该被 Caddy 在内网访问；publish 出去等于绕过反代。
- **日志别放站点根**。放进 `status/` 就等于「访问日志可以被直接下载」。

### 上线前自查

> 证书这条单独一页：[HTTPS 与证书](docs/HTTPS与证书.md)（含 `ca.key` 别外传、SAN 必须含你访问用的地址）。

```bash
# 1) 配置语法
docker run --rm -v "$PWD/deploy:/c" -e DASH_TOKEN=x caddy:2-alpine \
  caddy validate --config /c/Caddyfile --adapter caddyfile
# 2) 端到端
python3 tools/verify_deploy.py
# 3) 令牌是否一致（两处都打出来对一眼）
grep session_token auth/auth.json; grep DASH_TOKEN deploy/dashboard.env
```

---

## 10. 运维手册

| 想做什么 | 怎么做 |
|---|---|
| 手动刷一次数据 | `sudo systemctl start dash-health.service`（或 `python3 collector/health.py`） |
| 看采集器日志 | `journalctl -u dash-health.service -n 50` |
| 看网关日志 | `journalctl -u dash-auth.service -f` |
| 网关挂了 | `systemctl status dash-auth`；它是常驻服务，`Restart=always` |
| 改了口令 | 重新跑 `make_auth_conf.py` → 同步 `DASH_TOKEN` → `systemctl restart dash-auth` + 重启 Caddy |
| 改了站点文件 | **必须重建** Caddy 容器：`docker compose up -d --force-recreate caddy`（`admin off` ⇒ reload 必失败；单文件 bind-mount 换 inode） |
| 备份 | 至少要备份 `auth/auth.json`、`certs/ca.key`、`dashboard.env`、`data/` |
| 换机器 | 拷 `auth/` + `certs/` + `data/` + `dashboard.env`，重装一遍，Cookie 还在（同一张 session_token） |

采集器用 systemd timer（`OnUnitActiveSec=2min`），不用 cron —— 因为 `/etc/cron.d/` 里的条目 `crontab -l` 看不见，以后排错会怀疑人生。

---

## 11. 排错速查

| 症状 | 大概原因 | 查什么 |
|---|---|---|
| 登录成功但还在登录页 | `DASH_TOKEN` ≠ `auth.json.session_token` | 两处都打出来比 |
| 页面一直「数据偏旧」 | 采集器没跑 / 写到了别的目录 | `ls -l status/health.json` 的时间戳；`DASH_STATUS_DIR` |
| 卡片空白但页面在 | `health.json` 里对应对象是 `null`/缺键 | 前端对空对象整块不渲染，属预期 |
| 大屏打开是一片 JSON | Caddy 没命中 `@statusok`，落到了兜底反代 | 看 Cookie 名是否和 `DASH_COOKIE` 一致 |
| `/login-mascot.svg` 404 | 网关找不到立绘 | 网关会依次找 `auth/assets`、`../site/assets`、`../assets`；也可用 `DASH_AUTH_MASCOT` 指定 |
| 改了 Caddyfile 没生效 | 没重建容器 | `--force-recreate`；`caddy reload` 在 `admin off` 下必失败 |
| fail2ban `total failed` 恒 0 | `logpath` 写成了容器内路径 / 时间格式不匹配 | 宿主上 `ls` 一下那个文件；`datepattern = "ts":{EPOCH}` |
| 封了 IP 但人还能连 | action 封了 INPUT | 改封 `DOCKER-USER`（FORWARD） |
| 手机上看不到气泡/立绘 | 系统开了「减弱动态效果」 | 设计如此：只停动画，静物保留 |
| 本地 `python3` 跑不起来、没输出 | Windows 上是应用商店的占位 stub | 用 `py`，或装真正的 Python |
| 配置读进来报 `Unexpected UTF-8 BOM` | 记事本存成了带 BOM | 代码已按 `utf-8-sig` 读，仍报就重存为无 BOM |

---

## 12. 接入你自己的业务系统

大屏不认识你的业务系统。它只吃三样东西：**docker 的容器状态**、**`status/` 下几个约定格式的文件**、**HTTP 探活**。
把这三样产出来，再写对 `health.config.json`，屏幕就有数了 —— 不用改一行 Python。

以 **MaiBot + SnowLuma** 为例的完整过程（容器名怎么查、`state.json` / `events.log` / `backup.json` 每个字段、
探活怎么配、六个必踩的坑）：

- 人看的：[`docs/接入-MaiBot与SnowLuma.md`](docs/接入-MaiBot与SnowLuma.md)
- 给 AI 助手执行用的：[`docs/接入-MaiBot与SnowLuma-给AI.md`](docs/接入-MaiBot与SnowLuma-给AI.md)

换成别的系统（AnythingLLM、青龙、自己写的服务）也是同一套：容器名 + 三个状态文件 + 探活。
两张对照表都在文档第一段，替换名字就行。

---

## 13. 已知限制

- **单机版**：只采本机，没有多机汇总/历史曲线。想要趋势图得自己接 Prometheus。
- **判定很朴素**：容器是否在跑、端口是否在听、磁盘内存过没过线。没有智能基线。
- **前端零依赖**：所以也没有框架的组件化，改结构就是改 `dash.html` 的 `render()`。
- **`health.json` 是明文**：里面有主机名、目录体积这些。**它在大屏的登录后面**，别把 `status/` 直接挂到公网静态站。
- **没有用户体系**：一个账号、一个口令、一张 Cookie。多人用就一张令牌。
- **看门狗只判一件事**：你配的那个端口在不在听。业务进程自己卡死但端口还开着，它抓不到。

---

## 14. 许可与第三方

本仓库代码：MIT（见 [LICENSE](LICENSE)）。

第三方组件各自遵守自己的许可，本仓库**不包含**它们的代码或镜像：

| 组件 | 说明 |
|---|---|
| Caddy | Apache-2.0，镜像 `caddy:2-alpine` |
| 鲸鱼娘立绘 `mascot.webp` / `mascot-head.webp` | 第三方同人图，**CC BY-NC-SA 4.0**（角色原案 上善无形，二创 ZipZipPipe，修复 QYQCAMIAO，素材仓库 `fornarwhal/deepseek-whale-girl-icon`）。只覆盖这两张图，不影响本仓库其它部分的 MIT |
| 占位形象 `mascot.svg` / `mascot-head.svg` / `favicon.svg` | 本仓库自带，纯 SVG 手绘，可自由替换 |

原版背景里那张「成熟比例版」大立绘（作者 JerryZRic）**没有**放进仓库：它的原文只写了
「未标注授权协议、仅个人非商用」，不适合随仓库分发。你自己要用，见 `site/assets/LICENSE-art.md`。

**这个仓库里没有任何真实的 IP、域名、令牌或 API Key。**
它也不含任何业务系统的代码或配置 —— 大屏只负责「看」，你的后台仍然是你自己的东西，
通过 `DASH_APP_UPSTREAM` 反代进来而已。

如果你从别处拿到了带真实值的版本，先按 `AGENTS.md` 的「敏感信息清单」清一遍再考虑公开。

---

## 附：最短路径

```bash
git clone <repo> && cd <repo>
sudo ./deploy/install.sh                       # 交互问口令、生成证书、装 systemd
sudo cp -r /opt/dashboard/deploy/Caddyfile.template /opt/dashboard/deploy/sites /etc/caddy/  # Caddyfile.template 改名成 Caddyfile
sudo systemctl restart caddy
python3 tools/verify_deploy.py                  # 全绿就完事
```
