# HTTPS 与证书 —— 给 AI 助手看的执行版

> 配套文档：人看的在 [HTTPS与证书.md](HTTPS与证书.md)，决策树与背景知识在那边；**这页只写"要你动手时怎么做、怎么验、不许做什么"**。
> 目标：拿到任何一台机器，能在不查资料的情况下把 `https://…:8443` 弄通，并且不把私钥带进仓库。

---

## 0. 任务定义

用户说的通常是这一句：**「打不开 / 提示不安全 / 登录后还在登录页 / 手机上看不了」**。

你的工作是判断它落在下面四类中的哪一类，然后只做那一类的动作：

| 类型 | 判据 | 你的动作 |
|---|---|---|
| A 没证书 | Caddy 起不来、日志 `no such file ... server.key` | 生成证书（§2.1） |
| B 有证书但不被信任 | 浏览器 `ERR_CERT_AUTHORITY_INVALID`、`curl` 报 `self signed certificate` | 让设备信任 CA（§2.2），**不重签** |
| C 地址不在 SAN | `ERR_CERT_COMMON_NAME_INVALID`、`openssl s_client` 的 SAN 与访问地址不一致 | 带正确地址重签（§2.3），**复用 CA** |
| D 登录死循环 | 302 到 `/status/dash.html` 又被踢回 `/login` | 先确认访问的是不是 https（§1.1），再查 `DASH_TOKEN`≠`session_token` |

**推论**：看到「证书有问题」不要一律重生成 —— 重生成 CA 会让所有已装 `ca.crt` 的设备失效，属于破坏性操作。

---

## 1. 硬契约（违背任意一条，页面就打不开或登不进）

### 1.1 必须 https

`auth/auth_gate.py` 下发的 Cookie 带 `Secure`。http 页面下浏览器**不会把它发回来**，现象是"登录成功但还在登录页"。所以：

- 不允许把站点改成 `http://`
- 不允许为了"本机调试"把 `Secure` 去掉后拿去部署（`DASH_AUTH_INSECURE_COOKIE=1` **只用于本机**）
- 需要 http 的话只有一个合法理由：**TLS 在前置反代终止**，Caddy 只在内网收 http（§2.4），此时浏览器看到的仍是 https

### 1.2 SAN 里必须有实际访问用的那个地址

证书校验比的是 **SAN**，不是 CN。用公网 IP 访问就必须把该 IP 签进去；用域名就把域名签进去；两个都用就都写上。

### 1.3 三处证书路径必须指向同一套文件

| 变量 | 默认值 | 谁在用 | 注意 |
|---|---|---|---|
| `DASH_CERT_FILE` | `/etc/caddy/certs/server-fullchain.crt` | `deploy/sites/dash.caddy` 的 `tls` 行 | **必须是 fullchain**（叶子 + 中间证书） |
| `DASH_KEY_FILE` | `/etc/caddy/certs/server.key` | 同上 | 权限 600 |
| `DASH_CERTS_DIR` | `/etc/caddy/certs` | `@ca` 那段 `file_server` | `/ca.crt` 从这里取 |

**Docker 部署下这三个值是容器内路径**（`/etc/caddy/certs/...`），宿主路径只出现在 compose 的 `volumes` 里。

### 1.4 `gen_certs.sh` 的产物契约（别自己手搓 openssl）

```bash
./deploy/gen_certs.sh <证书目录> [主机名或IP ...]
# 不传地址 → 只签 127.0.0.1 与 localhost（本机自测足够）
```

| 文件 | 内容 | 权限 | 进仓库 |
|---|---|---|---|
| `ca.crt` | 根证书 | 644 | 可选（是公开信息，但默认也不提交） |
| `ca.key` | 根私钥 | 600 | **永不** |
| `server.key` | 服务器私钥 | 600 | **永不** |
| `server.crt` | 服务器证书（含 SAN） | 644 | 不要 |
| `server-fullchain.crt` | `server.crt` + `ca.crt` | 644 | 不要 |

`ca.key` 已存在时脚本**复用**（不重签 CA），只重签服务器证书 —— 这是刻意设计，见 §0 推论。

---

## 2. 四类动作的精确改法

### 2.1 生成（类型 A）

```bash
cd /opt/dashboard                      # 或仓库根
sudo -u dash ./deploy/gen_certs.sh ./certs 203.0.113.10 dash.example.com
```

然后在 `dashboard.env`（或 compose 的 `environment`）确认三行指向它，重启 Caddy：

```bash
# 宿主直装
sudo systemctl restart caddy
# Docker（改过 env / compose / Caddyfile 都要重建）
docker compose up -d --force-recreate caddy
```

**不要**用 `systemctl reload caddy`：模板里 `admin off`，reload 一定失败。

### 2.2 让设备信任（类型 B）

分发 `/ca.crt` 的现成渠道已经存在：站点的 `@ca` 段把 `DASH_CERTS_DIR/ca.crt` 公开发出，路径 `/ca.crt`。所以正确的话术是"打开 `https://<地址>:8443/ca.crt` 下载，然后按系统装"。

装的位置必须是**根证书信任库**，不是"服务器证书"或"个人"证书库：

- Windows：`certutil -addstore -f Root ca.crt`（管理员），或图形界面「本地计算机 → 受信任的根证书颁发机构」
- macOS：`sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ca.crt`
- Android：设置 → 安全 → 加密与凭据 → 安装证书 → **CA 证书**
- iOS：装描述文件 **后**还要去「设置 → 通用 → 关于本机 → 证书信任设置」打开开关（漏这步等于没装）
- Firefox 独立证书库：`certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n selfca -i ca.crt` 或界面导入
- curl/脚本：`--cacert ca.crt`，不要退化成 `-k`（`-k` 会连 SAN 错配都放过）

### 2.3 重签（类型 C）

```bash
# 带上「所有」会用到的地址，一次签全，避免反复
sudo -u dash ./deploy/gen_certs.sh ./certs 203.0.113.10 dash.example.com 10.0.0.5
```

- 会覆盖 `server.crt/server.key/server-fullchain.crt`，**保留** `ca.crt`/`ca.key` → 已装 CA 的设备不用重装
- 重签后必须重启/重建 Caddy（证书是启动时读的）
- 自检脚本里带 `DASH_CA` 的那条断言会顺带验证 SAN，改完就跑一遍（§3.4）

### 2.4 已有证书 / 前面还有一层 TLS（类型 D 的合法变体）

**手里有 fullchain + key**：只改变量，不动 Caddyfile。

```bash
DASH_CERT_FILE=/etc/caddy/certs/fullchain.pem
DASH_KEY_FILE=/etc/caddy/certs/privkey.pem
DASH_CERTS_DIR=/etc/caddy/certs
```

只给叶子证书的典型症状：桌面 Chrome 正常（自己补中间证书），手机/curl 报 `unable to get local issuer certificate`。

**TLS 在前置反代终止**（Cloudflare Tunnel / Nginx / frp / SLB）：把站点地址改成 `http://127.0.0.1:8443 { … }`，删掉 `tls` 行；前层必须转发 `Host`、`X-Forwarded-Proto: https`。同时把 8443 收回内网（`127.0.0.1:8443:8443` 或只监听回环），别让裸端口暴露。

**有域名想省事**：让 Caddy 走 ACME —— `deploy/Caddyfile` 全局块删 `auto_https off`（第 26 行）、加 `email`；`deploy/sites/dash.caddy` 站点地址改成域名并删 `tls` 行。前提：80 端口可达（HTTP-01）。此路线下 `/ca.crt` 无意义但无害。

---

## 3. 验证顺序（照这个顺序，别跳）

### 3.1 证书本身

```bash
openssl x509 -in certs/server.crt -noout -subject -issuer -dates
openssl x509 -in certs/server.crt -noout -ext subjectAltName
# 链完整（fullchain 应能自证到根）
openssl verify -CAfile certs/ca.crt certs/server.crt
```

判据：`notAfter` 未过期；SAN 含访问地址；`verify` 输出 `OK`。

### 3.2 端口与进程

```bash
sudo ss -lntp | grep -E '8443|:443'
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -i caddy
docker logs --tail 30 <caddy容器名> 2>&1 | grep -iE 'certificate|tls|error'
```

### 3.3 TLS 握手（三种严格度，依次试）

```bash
curl -vk https://127.0.0.1:8443/login -o /dev/null          # 只看链路通不通
curl -v --cacert certs/ca.crt https://203.0.113.10:8443/login -o /dev/null   # 证书真没问题（关键）
echo | openssl s_client -connect 203.0.113.10:8443 -servername dash.example.com 2>/dev/null \
  | openssl x509 -noout -text | grep -A1 'Subject Alternative Name'
```

**第二条不报错才算证书 OK**；第一条过了第二条没过 = 信任或 SAN 的问题（回到 §0 判 B / C）。

### 3.4 端到端

```bash
DASH_BASE=https://203.0.113.10:8443 DASH_CA=./certs/ca.crt \
DASH_USER=admin DASH_PW='口令' python3 tools/verify_deploy.py
```

- 给 `DASH_CA` → 校验证书（推荐，能同时抓 SAN 错配）
- 不给 → `ssl._create_unverified_context()`，只验业务链路
- 走公开 CA（ACME）时给系统根：`DASH_CA=/etc/ssl/certs/ca-certificates.crt`

### 3.5 浏览器侧

无头环境用 `curl` 代替即可；有图形界面才谈「地址栏小锁」。**不要**把"用户点了继续前往"当成通过验收 —— 那只是绕过了校验。

---

## 4. 失败对照（按症状查，别猜）

| 现象 | 根因 | 改法 |
|---|---|---|
| Caddy 起不来，`open …server.key: no such file` | 路径写的是宿主路径 / 文件没生成 | §1.3，Docker 用容器内路径 |
| `ERR_CERT_AUTHORITY_INVALID` | CA 未装进该设备 | §2.2 |
| `ERR_CERT_COMMON_NAME_INVALID` | SAN 缺访问地址 | §2.3 |
| `ERR_CERT_DATE_INVALID` | 系统时间错 / 证书过期 | 先对时，再重签 |
| `curl: (60) unable to get local issuer certificate` | 只有叶子证书 | 用 fullchain |
| `curl: (60) self signed certificate in certificate chain` | 没给 `--cacert` | §3.3 第二条 |
| 登录 302 后又回登录页 | 走了 http；或 `DASH_TOKEN` 与 `session_token` 不一致 | §1.1；不一致是另一份契约（AGENTS §1.1） |
| `/ca.crt` 404 | `DASH_CERTS_DIR` 指错或文件名不是 `ca.crt` | §1.3 |
| 改了 Caddyfile 不生效 | 单文件 bind-mount 换 inode，且 `admin off` 不能 reload | `up -d --force-recreate caddy` |
| 手机 iOS 装了描述文件仍红 | 缺「证书信任设置」开关 | §2.2 iOS |
| 换 IP 后突然不行 | SAN 是旧的 | §2.3 |

---

## 5. 不许做的事

1. **不许**把 `ca.key` / `server.key` / `*.pem` / `certs/` 提交到仓库（`.gitignore` 已排 `certs`，别强行 `-f`）。
2. **不许**为了让告警消失而"顺手重生成 CA" —— 换 CA = 所有设备重装。
3. **不许**把 `DASH_AUTH_INSECURE_COOKIE=1` 写进部署环境的 env 文件。
4. **不许**用 `-k` / `--insecure` / `verify=False` 作为"验收通过"的依据。
5. **不许**把证书私钥贴进 issue、文档、聊天记录。
6. **不许**在仓库里留真实 IP / 域名 / 主机名 —— 文档示例一律用 `203.0.113.10`（RFC 5737）、`dash.example.com`、`you@example.com`。
7. **不许**把 `insecure` / `skip-verify` 之类的开关加进 `verify_deploy.py` 当默认值。

---

## 6. 提交前自查

```bash
# 1) 私钥/证书有没有混进来（有输出就是必须清掉）
git ls-files | grep -Ei '\.(key|pem|crt|p12|pfx)$|(^|/)certs/'

# 2) 真实地址/域名（示例 IP 与 example.com 应被放过）
git ls-files | xargs grep -nIE '([0-9]{1,3}\.){3}[0-9]{1,3}' | grep -vE '127\.0\.0\.1|0\.0\.0\.0|203\.0\.113\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.'

# 3) 语法与链接
python3 -m py_compile auth/*.py collector/health.py tools/*.py
bash -n deploy/gen_certs.sh deploy/install.sh
```

---

## 7. 一页速查（贴在你自己的执行日志里）

```
判定：起不来→A生成 / 不受信任→B装CA / 名字不对→C重签 / 登不进→先看是不是https
生成：./deploy/gen_certs.sh ./certs <IP或域名...>   （CA 复用，别删 ca.key）
路径：DASH_CERT_FILE=fullchain  DASH_KEY_FILE=key  DASH_CERTS_DIR=目录（容器内路径）
生效：systemctl restart caddy | docker compose up -d --force-recreate caddy
验证：openssl verify → ss -lntp → curl --cacert（不带 -k）→ verify_deploy.py
禁区：私钥进仓库 / 重生成 CA / -k 当验收 / 真实 IP 进文档
```
