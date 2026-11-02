# HTTPS 怎么来 —— 证书、信任、以及「为什么不能用 http」

> 这页只解决一件事：**让你能用 `https://…` 打开这块大屏，且地址栏不吓人**。
> 要把这事交给 AI 助手做，让它读 [HTTPS与证书-给AI.md](HTTPS与证书-给AI.md)（判定 → 改法 → 验证 → 禁区）。
> 装完的入口长得像：`https://<你的地址>:8443/status/dash.html`

---

## 0. 三句话版本

1. **必须是 https**。登录成功后网关发的 Cookie 带 `Secure` 标记，浏览器在 http 下**根本不会把它发回来** —— 结果是「登录成功，但页面又跳回登录页」，一直循环。这条不是风格选择，是硬约束。
2. 默认走**自签证书**（`deploy/gen_certs.sh` 一条命令，10 年有效期，SAN 里带你的 IP/域名）。代价：每台设备第一次要装一次 `ca.crt`，或者手动点「继续前往」。
3. 有域名就换成 **Let's Encrypt 自动签发**（Caddy 自带），或者把你现有的证书指过去 —— 见 §3、§4。

---

## 1. 为什么不能用 http 凑合

| 会坏在哪 | 具体表现 |
|---|---|
| Cookie 的 `Secure` | `Set-Cookie: DashSession=…; Secure` 在 http 页面下被浏览器丢弃 → 登录 302 回大屏，但没 Cookie → Caddy 又把人送回登录页，**死循环** |
| Caddy 站点本身 | `deploy/sites/dash.caddy` 的站点地址就是 `:{$DASH_HTTPS_PORT:8443}`（https 站），`tls` 行是必填的；没有证书 Caddy 起不来 |
| 自检脚本 | `tools/verify_deploy.py` 默认就是 `DASH_BASE=https://127.0.0.1:8443`，校验的还是同一份证书 |

> 只想在**本机**快速看效果，不要折腾证书：`python3 tools/demo.py`（http，但它是纯静态演示，没有登录那一层）。真实部署必须 https。

---

## 2. 路线 A：自签（默认，不需要域名）

### 2.1 生成

```bash
cd /opt/dashboard            # 或者你 clone 下来的仓库根目录
./deploy/gen_certs.sh ./certs 203.0.113.10 dash.example.com
```

- 第一个参数是**证书目录**（会被 `mkdir -p`）
- 后面的参数是**你要用来访问的地址**，可以是 IP、域名，混着写都行；脚本按 `a.b.c.d` 的样子自动分到 `IP.n` / `DNS.n`
- 不传地址时，只签 `127.0.0.1` 和 `localhost`（本机测 `verify_deploy.py` 用这个就够）
- **想给手机用，就必须把手机访问时敲的那个地址写进去**（用公网 IP 访问就写公网 IP；用域名就写域名）

产出（都在 `./certs/`）：

| 文件 | 是什么 | 权限 | 要不要给别人 |
|---|---|---|---|
| `ca.crt` | 根证书，**要装进设备信任库** | 644 | 可以，页面 `/ca.crt` 就把它发出去 |
| `ca.key` | 根私钥 | 600 | **绝对不给**，泄露等于谁都能伪造你的证书 |
| `server.key` | 服务器私钥 | 600 | 不给 |
| `server.crt` | 服务器证书（含 SAN） | 644 | 一般不用单独给 |
| `server-fullchain.crt` | 服务端证书 + CA，**Caddy 用的就是这个** | 644 | 不给 |

有效期都是 **3650 天**。`ca.key`/`ca.crt` 已存在时脚本**复用**，只重签服务器证书 —— 因为换 CA 会让所有已经装过 `ca.crt` 的设备全部失效，得重新装一遍。

### 2.2 核对（30 秒，别跳过）

```bash
# 1) 有效期与签发者
openssl x509 -in certs/server.crt -noout -subject -issuer -dates

# 2) SAN 里必须包含你实际访问用的那个地址
openssl x509 -in certs/server.crt -noout -ext subjectAltName
```

SAN 里没有你敲的地址 → 浏览器报 `ERR_CERT_COMMON_NAME_INVALID`（和「不受信任」是两回事，别搞混）。**改 IP / 加域名后必须重签**。

### 2.3 让设备信任这张 CA

装的是 **`ca.crt`**（根证书），不是 `server.crt`。

**Windows 10/11（Chrome、Edge、IE 都用系统库）**

1. 双击 `ca.crt` → 「安装证书」
2. 存储位置选 **本地计算机**（要管理员）→ 下一步
3. 选「将所有的证书都放入下列存储」→ **受信任的根证书颁发机构** → 确定
4. 关掉所有 Chrome 窗口再开（证书库有缓存）
5. 命令行核对：`certutil -store Root | findstr /i "Self-Signed"`

**macOS**

1. 双击 `ca.crt` → 加入「系统」钥匙串
2. 钥匙串访问里找到 `Self-Signed Root CA` → 双击 → 展开「信任」→ 「使用此证书时」选 **始终信任**
3. `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain certs/ca.crt` 也能一条命令搞定

**Android**

1. 浏览器打开 `https://<你的地址>:8443/ca.crt` 下载（或数据线拷过去）
2. 设置 → 安全 → 加密与凭据 → 安装证书 → **CA 证书** → 选择刚下载的文件
3. 不同厂商菜单名不一样，搜「安装证书」最快
4. 注意：Android 7+ 里**用户装的 CA 只对浏览器生效**，App 默认不信任（这是系统策略，不影响你看大屏）

**iOS / iPadOS**

1. Safari 打开 `https://<你的地址>:8443/ca.crt` → 允许下载描述文件
2. 设置 → 通用 → VPN 与设备管理 → 已下载的描述文件 → 安装
3. **关键一步**：设置 → 通用 → 关于本机 → **证书信任设置** → 打开 `Self-Signed Root CA` 的开关
4. 少第 3 步 = 装了也没用，照样红警告

**Firefox**

Firefox 有自己的证书库，不读系统库：设置 → 隐私与安全 → 证书 → 查看证书 → 证书颁发机构 → 导入 → 勾「信任由此 CA 标识的网站」。

**懒得装？** 也行：点「高级」→「继续前往（不安全）」。功能完全正常，只是每次（或每次清缓存后）都要点一次，且地址栏会有红色警告 —— 自己用没问题，**别把这种地址发给别人**。

### 2.4 接到部署里

**宿主直装**：`install.sh` 已经生成到 `/opt/dashboard/certs/`，`dashboard.env` 里对应三行：

```bash
DASH_CERT_FILE=/opt/dashboard/certs/server-fullchain.crt
DASH_KEY_FILE=/opt/dashboard/certs/server.key
DASH_CERTS_DIR=/opt/dashboard/certs     # /ca.crt 就是从这里取的
```

**Docker**：`deploy/docker-compose.yml` 把宿主 `./certs` 挂到 `/etc/caddy/certs`，直接用默认值即可：

```bash
./deploy/gen_certs.sh ./certs 203.0.113.10
docker compose up -d
```

**Caddy 在容器里跑时**：`DASH_CERT_FILE` / `DASH_KEY_FILE` 写的是**容器内路径**（`/etc/caddy/certs/...`），不是宿主路径。写错的表现是启动即报 `open ...: no such file`。

---

## 3. 路线 B：有域名 → Let's Encrypt 自动签

前提：域名 A/AAAA 记录指向这台机，**80 端口对外可达**（HTTP-01 验证要用），云安全组也放行。

改两个地方（`deploy/Caddyfile` 的全局块在第 26 行 `auto_https off`，站点在 `deploy/sites/dash.caddy`）：

```caddyfile
# deploy/Caddyfile：把全局的 auto_https off 去掉（或改成 auto_https on）
{
    admin off
    # 想收证书到期提醒就填邮箱
    email you@example.com
}

# deploy/sites/dash.caddy：
# 站点地址从 :{$DASH_HTTPS_PORT:8443} 改成你的域名
dash.example.com {
    # 删掉 tls 那一行，让 Caddy 自己申请
    encode zstd gzip
    ...
}
```

然后：

```bash
docker compose up -d --force-recreate caddy     # 单文件挂载换 inode，必须重建
docker logs -f maibot-caddy 2>&1 | grep -i certificate    # 看签发过程
```

- 想继续用 8443 端口：站点地址写 `dash.example.com:8443`，但 **ACME 的 HTTP-01 仍然要 80 端口**
- 80 被墙/被占用：用 DNS-01（Caddy 需要带 DNS 插件的镜像，`caddy:2-alpine` 不含）
- 这条路线下 `/ca.crt` 就没意义了（公开 CA 不需要装根证书），留着不影响
- 自检时默认不再校验证书（`DASH_CA` 不填 = 不校验）；想真校验就走系统根证书：`DASH_BASE=https://dash.example.com DASH_CA=/etc/ssl/certs/ca-certificates.crt python3 tools/verify_deploy.py`

---

## 4. 路线 C：已有证书，或前面还有一层反代

### 4.1 手里有 fullchain + key（云厂商签的、公司 CA 签的）

```bash
DASH_CERT_FILE=/etc/caddy/certs/fullchain.pem     # 必须是 fullchain：叶子 + 中间证书
DASH_KEY_FILE=/etc/caddy/certs/privkey.pem
DASH_CERTS_DIR=/etc/caddy/certs
```

常见坑：只放了叶子证书（leaf only）→ 桌面 Chrome 可能能开（它自己补中间证书），手机/curl 直接 `unable to get local issuer certificate`。**用 fullchain 就没事**。

### 4.2 前面已经有 TLS（Cloudflare Tunnel / Nginx / frp / 负载均衡）

TLS 在前层终止，Caddy 只在内网收 http：

```caddyfile
http://127.0.0.1:8443 {
    # 不要 tls 行
}
```

- 只绑 `127.0.0.1` 更安全，别让 8443 直接暴露在公网
- 前层要转发 `Host`、`X-Forwarded-For`、`X-Forwarded-Proto: https`
- **Cookie 的 `Secure` 仍然成立**，因为浏览器看到的是 https；但前层如果是 http 对外，登录立刻死循环（回到 §1）
- 反代要带上 `Upgrade`/`Connection` 头？这块大屏没有 WebSocket，不需要

### 4.3 只想内网/本机自签，不想装 CA

Caddy 自带内部 CA：

```caddyfile
dash.example.com {
    tls internal          # 用 Caddy 自己的 CA 签，root 在容器 /data/caddy/pki/authorities/local/root.crt
}
```

和 `gen_certs.sh` 的自签是同一类方案，区别只是谁来管私钥。装信任时要把 Caddy 的那个 `root.crt` 装进去。

---

## 5. 通了没有：按顺序敲这几条

```bash
# 1) 端口在听吗（容器/进程侧）
sudo ss -lntp | grep -E '8443|443'

# 2) 本机走 TLS 能拿到证书吗（-k 跳过校验，先确认链路通）
curl -vk https://127.0.0.1:8443/login 2>&1 | grep -E 'subject|issuer|SSL certificate|HTTP/'

# 3) 用你签出来的 CA 严格校验（不带 -k，能过才算证书没问题）
curl -v --cacert certs/ca.crt https://<你的地址>:8443/login -o /dev/null

# 4) 证书里的 SAN 对不对
echo | openssl s_client -connect <你的地址>:8443 -servername <你的域名或IP> 2>/dev/null \
  | openssl x509 -noout -text | grep -A1 'Subject Alternative Name'

# 5) 外围放行
sudo ufw status | grep 8443          # 宿主防火墙
#    云主机的安全组还要单独放行（控制台里加，`ufw allow` 管不到它）

# 6) 端到端（32 项断言里包含证书这条）
DASH_BASE=https://<你的地址>:8443 DASH_CA=certs/ca.crt \
DASH_USER=admin DASH_PW='你的口令' python3 tools/verify_deploy.py
```

---

## 6. 症状 → 原因对照

| 浏览器/curl 说什么 | 真正的原因 | 怎么办 |
|---|---|---|
| `ERR_CERT_AUTHORITY_INVALID` / 「不是私密连接」 | CA 没装进这台设备（或装了没重启浏览器） | §2.3。Firefox 单独再装一遍 |
| `ERR_CERT_COMMON_NAME_INVALID` | SAN 里没有你敲的这个地址 | 带正确地址重跑 `gen_certs.sh`（会自动复用 CA，不用重新装） |
| `ERR_CERT_DATE_INVALID` | 系统时间不对，或证书过期 | 先对时；过期就重签 |
| 手机：描述文件装了还是红字 | iOS 少开了「证书信任设置」那一步 | §2.3 iOS 第 3 步 |
| `curl: (60) SSL certificate problem` | 没带 `--cacert` | `curl --cacert certs/ca.crt …` |
| `curl: (60) unable to get local issuer certificate` | 只给了叶子证书，缺中间证书 | 用 fullchain（§4.1） |
| 容器起不来，日志 `no such file ... /etc/caddy/certs/...` | 证书路径写成了宿主路径 | 容器里认的是容器内路径 |
| 登录成功却又回到登录页 | 用 http 访问（Cookie `Secure` 被丢） | 换 https（§1） |
| 地址栏正常但 `/ca.crt` 404 | `DASH_CERTS_DIR` 指错，或文件不叫 `ca.crt` | 对一下 `dashboard.env` 和实际文件名 |
| 换了个 IP 访问就报错 | SAN 里只有旧 IP | 重签，新 IP 加进参数 |
| `docker compose` 改了 Caddyfile 没生效 | 单文件 bind-mount 换了 inode，`admin off` 又不能 reload | `docker compose up -d --force-recreate caddy` |

---

## 7. 一页清单（贴墙上）

```
[ ] gen_certs.sh ./certs <公网IP或域名>        # 地址要在 SAN 里
[ ] openssl x509 -ext subjectAltName 核对
[ ] DASH_CERT_FILE / DASH_KEY_FILE / DASH_CERTS_DIR 指对（容器内路径）
[ ] 安全组 + ufw 放行 8443（走 Let's Encrypt 还要 80）
[ ] 桌面装 ca.crt 到「受信任的根证书颁发机构」
[ ] 手机 Safari/浏览器打开 /ca.crt，装描述文件 + 开「证书信任设置」
[ ] curl --cacert certs/ca.crt https://…/login 不报错
[ ] verify_deploy.py 全绿
[ ] 顺带：ca.key 不进仓库、不进任何同步盘
```
