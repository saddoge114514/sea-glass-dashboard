# AGENTS.md — 给 AI 助手的操作说明

这份文件是给**要动这个仓库的 AI 助手**看的。人看 [README.md](README.md)。
目标只有一个：让你在不理解全部背景的情况下，也**不把已经跑通的链路改坏**，尤其是别把真实主机信息带进仓库。

---

## 0. 三十秒了解这套东西

一套「服务器状态大屏」：静态前端 + 一个纯标准库采集器 + 一个纯标准库登录网关 + Caddy 站点配置。
三个部分之间只通过**文件和 HTTP 的 Cookie** 耦合：

```
health.py ──写──> status/health.json ──Caddy file_server──> dash.html（浏览器）
                                                     ↑
auth_gate.py ──写 Cookie──> 浏览器 ──Cookie──> Caddy 的 header 字面匹配
```

没有数据库、没有框架、没有 npm 依赖。所有代码都是「改一个文件就能跑」的规模。

---

## 1. 不许动的六条线（动了就是 bug）

1. **`DASH_TOKEN` 必须等于 `auth/auth.json` 的 `session_token`。**
   Caddy 只做 `header Cookie *<cookie名>=<token>*` 的字面匹配。不一致的唯一表现是
   「登录返回 302 成功，但页面还在登录页」—— 这种 bug 极难从日志看出来。
2. **`deploy/sites/dash.caddy` 里 `@shortdeep` 必须写在 `@shortok` 前面。**
   Caddy 的 handle 是「首个匹配者胜出」，顺序写反 → 短链下的陌生路径全部 404、页面白屏。
3. **改任何 `*.caddy` / `Caddyfile` 之后必须重建容器**：
   `docker compose up -d --force-recreate caddy`。
   `admin off` ⇒ `caddy reload` 一定失败；单文件 bind-mount 换 inode ⇒ 只改文件不重建还是旧配置。
4. **登录网关不要 publish 端口。** 它只能被 Caddy 在内网访问。
5. **fail2ban 必须封 `DOCKER-USER` 链**（docker publish 走 FORWARD，不走 INPUT）。
   封 INPUT 的表现是「`fail2ban-client status` 显示 banned，但对方照样连得上」。
6. **不要把日志目录指到站点根**（`status/`）。那是 `file_server` 的根，日志会被直接下载。

---

## 2. 敏感信息清单：这些**永远**不能出现在仓库里

提交前跑一遍自查（见 §5.1）。任何一条命中就停下来清掉：

- 公网 IP、域名、ECS 实例 ID、内网主机名（形如 `iZxxxxZ`）
- QQ 号、群号、OpenID、`nt_qq_*` 这类账号目录名
- 任何 `sk-` 开头的模型 Key、`session_token`、`accessToken`、`SendKey`、OSS AccessKey
- 真实绝对路径（`/root/<项目名>`、`/home/<用户名>`）→ 换成 `/opt/dashboard` 或占位符
- 真实容器名/镜像 tag（如某个具体业务镜像）→ 换成 `example/app:latest`、`app`、`gateway`
- `auth/auth.json`（真文件，不是 `.example`）、`dashboard.env`、`.env`
- 运行期产物：`status/health.json`、`status/qr.png`、`status/events.log`、`certs/*.key`
- 证书私钥、`.bak` 备份文件
- **未标注授权协议的第三方素材**（例如 `site/assets/mascot-deep.webp`）：只能本机用，`.gitignore` 已排掉，别为了「好看」硬提交

`status/health.json` 尤其容易漏：它是**真数据**，里面有主机名和目录体积。

---

## 3. 文件地图（改之前先定位）

| 想改 | 改这个 | 别碰 |
|---|---|---|
| 文案、标题、页脚、链接、署名 | `site/config.js` | `dash.html` 里的默认值只在配置缺失时才对 |
| 页面结构、卡片、样式、情绪判定 | `site/dash.html`（`render()` / `moodOf()` / CSS） | 别删 `stale_after_sec` 的读法 |
| 采什么数据 | `collector/health.py`（加 `collect_*()` → 塞进 payload） | 保持「单函数 try/except，失败降级不抛」 |
| 采集器指向哪、看哪些容器 | `collector/health.config.example.json` → 部署时复制成 `health.config.json` | 别在 `health.py` 里写死路径 |
| 登录流程、Cookie、验证码、限速 | `auth/auth_gate.py` | 别动 `safe_next()`（它挡开放重定向） |
| 口令/令牌怎么生成 | `auth/make_auth_conf.py` | 输出必须是 0600 |
| 哪些路径放行/拦截 | `deploy/sites/*.caddy` | 别改 handle 顺序（见 §1.2） |
| 端口、证书路径、上游地址 | `deploy/dashboard.env.example`（+ 各 compose 的 `env_file`） | 别把真实值写进 example |
| 部署 | `deploy/install.sh`（宿主直装）、`deploy/docker-compose.yml`（Docker） | 两个入口共用同一份 `site/`、`collector/`、`auth/`、`deploy/sites/` |
| 端到端验收 | `tools/verify_deploy.py` | 加断言时保持「每条独立判定 + 失败 exit 1」 |
| 本机看效果 / 改示意数据 | `tools/demo.py` + `examples/health.json` | 示意数据必须是 `example-*` 假值；别把 `status/` 里的真数据拷进 `examples/` |
| 立绘 / 头像 / 背景那只 | `site/config.js` 的 `assets`，图放 `site/assets/` | 别在 `dash.html` 写死图片路径；第三方图必须带 `credit` 署名 |
| 接入业务系统（看哪些容器、探哪些端口） | `collector/health.config.example.json` 的 `containers` / `probes` / `watchdog` / `backup` | 别改 `health.py` 里字段名；契约见 `docs/接入-MaiBot与SnowLuma-给AI.md` §2 |
| 运行环境/兼容性（能不能装在这台机上） | `docs/部署环境.md` | 那份文档写的是实测值，别把没验过的版本写成「支持」 |

---

## 4. 常见任务的标准做法

### 4.1 加一个数据卡片

1. `collector/health.py`：写 `def collect_foo(cfg) -> dict`，内部 `try/except` 返回 `{"error": …}`；然后在 `main()` 组装 payload 的地方加一行 `payload["foo"] = collect_foo(cfg)`（现有函数名：`collect_containers` / `collect_disk` / `collect_mem` / `collect_host` / `collect_dir_size` / `collect_databases` / `collect_qr` / `collect_probe`(MCP) / `collect_probes`）。
2. `examples/health.json`：加一份假数据（必须是 `example-*` 这种明显假的值）。
3. `site/dash.html` 的 `render(d)`：`if (d.foo) card("标题", rows…)`。**空对象整块不渲染**是刻意设计，别改成显示空表格。
4. `site/config.js`：在 `labels` 里加标题文案；需要右上角小标签就加 `tags`。
5. 验证：`python3 collector/health.py --out /tmp/h.json` 后 `python3 -c "import json;print(json.load(open('/tmp/h.json'))['foo'])"`，再本机起静态服务器看页面。

### 4.2 加一个站点（第二个面板）

```bash
cp deploy/sites-examples/alt-site.caddy deploy/sites/alt-site.caddy
# 改里面的 DASH_ALT_UPSTREAM（或直接在 env 里给值）
docker compose up -d --force-recreate caddy
```

`deploy/Caddyfile` 是 `import {$DASH_SITES_GLOB:/etc/caddy/sites/*.caddy}`，
**glob 一条都没匹配到时 Caddy 会拒绝启动** —— `sites/` 里至少留一个 `.caddy`。

### 4.3 换立绘 / 改状态表现

立绘路径全在 `site/config.js` 的 `assets`（`mascot` / `head` / `deep`）里，
`dash.html` 通过 `applyArt()` 把它们套到 4 处 `<img>` 和 2 处 CSS 背景上，
**不要再往 `dash.html` 里写死图片路径**。

- 默认 `mascot.webp` / `mascot-head.webp` 是第三方同人图（CC BY-NC-SA 4.0，见 `site/assets/LICENSE-art.md`），
  底部 `credit` 的署名是协议要求的，别删；`deep` 默认复用 `mascot.webp`。
- 回退链：`assets` 里的图 404 → 换成 `mascot.svg` / `mascot-head.svg` → 都失败才隐藏（`applyArt()` 里 `FB`）。
- **状态表达：任何状态都不许把鲸鱼娘换掉**。状态 = `#sticker` 贴纸（warn `！` / bad `✕` / offline `Zzz`，内联 SVG 写在 `dash.html` 的 `STICKER` 表）+ `body.mood-*` 的滤镜/动画 + 横幅配色。`config.js` 的 `assets.moods` 是可选开关，留空就用 `mascot`；填了以后 `img[data-mood="1"]` 不再叠灰度。
- `site/assets/mascot-deep.webp`（JerryZRic 的成熟比例版背景）**未标注授权协议，已在 `.gitignore` 里排掉**，
  不要提交，也不要把 `credit` 里的 CC BY-NC-SA 说成覆盖它。
- `auth_gate.py` 的 `/login-mascot.*` 路由按扩展名探测 MIME，`.svg` / `.png` / `.webp` 都认。

### 4.4 加一条自检断言

`tools/verify_deploy.py` 的结构是「一个函数一个断言，返回 `(ok, 说明)`」。
新增时：不要依赖页面标题（登录页 h1 和大屏 h1 同名，这是踩过的坑），
要依赖结构特征（`name="cap_token"`、`schema` 字段、字节数）。

---

### 4.5 接一个新业务系统（MaiBot / SnowLuma / 别的）

三件事，别多做：

1. **容器**：`docker ps --format '{{.Names}}'` 抄名字，写进配置的 `containers`；已停用的 profile 容器别写（会永久红）。
2. **状态文件**：`status/state.json`（`state` 只认 `online/ok/up`）、`events.log`（一行一条、双空格分隔、末尾换行）、`backup.json`（`oss` 必须精确等于 `已上传`）。三个文件都由**业务侧脚本**写，采集器只读。
3. **探活**：能 HTTP 访问到的端口写 `probes`（`401/403/404` 也算通）；容器内端口（如 OneBot `3001`）宿主探不到，交给 `docker exec` 写进 `state.json`。

细节与坑表在 [`docs/接入-MaiBot与SnowLuma.md`](docs/接入-MaiBot与SnowLuma.md)（人看）
与 [`docs/接入-MaiBot与SnowLuma-给AI.md`](docs/接入-MaiBot与SnowLuma-给AI.md)（字段契约 + 验证顺序 + 失败对照）。

---

## 5. 验证：改完必须跑

### 5.1 仓库自查（不需要服务器）

```bash
# 语法
python3 -m py_compile auth/auth_gate.py auth/make_auth_conf.py collector/health.py tools/verify_deploy.py tools/demo.py
bash -n deploy/*.sh

# JSON / YAML 结构
python3 -c "import json;json.load(open('examples/health.json'));json.load(open('collector/health.config.example.json'))"

# 敏感信息扫描（命中即停）
grep -rniE '([0-9]{1,3}\.){3}[0-9]{1,3}|\bsk-[A-Za-z0-9]{16,}|[0-9]{9,11}|iZ[A-Za-z0-9]{12,}|/root/|nt_qq_' \
  --include='*' --exclude-dir=.git . | grep -v '127.0.0.1\|0.0.0.0\|172\.\|192\.168\|10\.\|example'
```

> 上面那条扫描会把 `127.0.0.1`、示例路径放过去，其余 IP 段一律当泄漏处理。

### 5.2 Caddy 配置语法

```bash
# 必须挂到 /etc/caddy：官方镜像的 ENTRYPOINT 默认读 /etc/caddy/Caddyfile。
# 挂到别的目录（比如 /c）容器会静默用镜像内置的默认配置起在 :80 —— 看着在跑，其实不是你的配置。
docker run --rm -v "$PWD/deploy:/etc/caddy:ro" -e DASH_TOKEN=probe caddy:2-alpine \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

`Valid configuration` 算过；`stapling OCSP ... no OCSP server specified` 是无害警告。

### 5.3 端到端（在有证书、网关已起的环境里）

```bash
DASH_BASE=https://127.0.0.1:8443 \
DASH_CA=/opt/dashboard/certs/ca.crt \
DASH_USER=admin DASH_PW='口令' DASH_SHORT_KEY='短链key' \
python3 tools/verify_deploy.py
```

它会验：登录页特征 → `ca.crt` 可下 → 立绘可访 → 未登录访问大屏被换成登录页 →
验证码错 401 → 口令错 401 → 全对 302 + `Set-Cookie` 属性 → 带 Cookie 拿到真大屏 +
`health.json`(schema/containers) + `config.js` → 短链下 `index.html`/`qr.png` 仍 404、
陌生路径 302 → `/logout` 清 Cookie。全绿才算过。

### 5.4 前端视觉

本机起静态服务器时必须**显式把 `.svg` 的 MIME 设成 `image/svg+xml`**：
Windows 版 Python 的 `mimetypes` 会给成 `image/svg`，Chromium 直接拒渲染，
你会看到「SVG 全是 0×0」——那不是模板的 bug，是临时服务器的锅。Caddy 给的是对的值。

最快的看法：`python3 tools/demo.py`（它自带正确 MIME，不用起临时服务器）；看某一状态用 `--mood ok|warn|bad|offline`。

另外：很多环境下 `prefers-reduced-motion: reduce` 恒为 true，`.sea`/`.swimmer` 会被媒体查询隐藏（设计如此，只停动画）。别误判成「气泡丢了」。

---

## 6. 失败信号对照表

| 现象 | 先怀疑 |
|---|---|
| 登录后还在登录页 | `DASH_TOKEN` ≠ `session_token`；或 Cookie 名不一致 |
| 大屏显示成一坨 JSON | 请求没命中 `@statusok`（Cookie 名错/没带 Cookie） |
| 短链 404 或白屏 | `@shortdeep` / `@shortok` 顺序反了；或 `DASH_SHORT_KEY` 与 URL 不一致 |
| 改了配置没生效 | 没 `--force-recreate`；或 env 没进容器（`env_file` 路径） |
| fail2ban `total failed` 恒 0 | `logpath` 指到容器内路径；或 `datepattern` 与日志对不上 |
| `banned` 但对方能连 | action 封错了链（要 `DOCKER-USER`） |
| 采集器写出空/畸形 JSON | 配置里相对路径按「配置文件所在目录」解析，别当成 CWD |
| `json.load` 报 `Unexpected UTF-8 BOM` | 记事本存了 BOM；代码已按 `utf-8-sig` 读，仍报就重存 |
| `py`/`python3` 无输出直接退出 | Windows 上是应用商店占位 stub，用 `py` 或装真 Python |
| 手机上看不到气泡 | 系统开了省电/减弱动效，属预期 |

---

## 7. 风格约束

- 代码注释用中文，讲**为什么**，不复述代码在做什么。
- 保持零第三方依赖（标准库 + 浏览器原生气 API）。引入依赖前先想清楚能不能不加。
- `health.py` 的每个采集块都必须能单独失败：外部命令挂了、文件不存在，都要降级成 `{"error": …}` 而不是抛异常。
- 前端不渲染主机名/IP/绝对路径这类「截图发出去会出事」的信息；需要展示就展示标签。
- 不改动与本任务无关的文件；不 `git commit`、不 `push`，除非用户明确要求。
