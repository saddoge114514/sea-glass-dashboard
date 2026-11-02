#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大屏登录网关 —— 只用 Python 标准库的极小 HTTP 服务。

【为什么不用 basicauth】
Caddy 的 basicauth 依赖浏览器弹「原生 HTTP Basic 登录框」。Electron（以及很多内嵌
WebView）默认不处理 HTTP 认证，请求会被静默取消 —— 页面只剩一片白，用户根本没地方
输入口令。所以改成「真正的 HTML 登录页 + Cookie 会话」：
  · 登录页是本服务吐出来的 HTML，任何浏览器都能渲染；
  · 登录成功下发 Cookie: <cookie_name>=<token>；
  · Caddy 侧只做这一个 Cookie 的字面匹配，不依赖任何插件。

【本服务只做四件事】
  GET  /login?next=...   渲染登录页（带算术验证码）
  POST /login            校验口令 + 验证码，成功则下发 Cookie 并 302 回原地址
  GET  /logout           清掉 Cookie
  GET  /login-mascot.svg 登录页上那张占位图（文件不存在就 404，页面自己兜底）

【安全设计】
  · 口令不落明文：auth.json 里存 scrypt 哈希（n=2^14, r=8, p=1）+ 随机盐。
  · 验证码：服务端出题，把「答案+时间戳」用 HMAC 签成一个 token 随页面下发，
    不占服务端状态；10 分钟过期。
  · 同一 IP 在窗口内连续失败 N 次 → 429 冷却（与 Caddy 日志上的 fail2ban 双保险）。
  · Cookie 带 HttpOnly + Secure + SameSite=Lax，只在 HTTPS 上生效。
  · 默认只监听 127.0.0.1，由 Caddy 反代，不直接暴露到公网。

【环境变量】
  DASH_AUTH_CONF     配置文件路径，默认 ./auth.json
  DASH_AUTH_BIND     监听地址，默认 127.0.0.1
  DASH_AUTH_PORT     监听端口，默认 8766
  DASH_AUTH_LANDING  登录成功后默认落点，默认 /status/dash.html
  DASH_AUTH_COOKIE   Cookie 名，默认 DashSession（必须和 Caddyfile 里的 $DASH_COOKIE 一致）
  DASH_AUTH_TITLE    页面标题，默认「服务器状态大屏」
  DASH_AUTH_MASCOT   登录页那张图的路径，默认自动找 site/assets/mascot.webp（没有就退回 mascot.svg）
  DASH_AUTH_INSECURE_COOKIE=1  本地 http 调试用：去掉 Cookie 的 Secure 标记（仅测试）
"""

import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CONF_PATH = os.environ.get("DASH_AUTH_CONF", os.path.join(HERE, "auth.json"))
BIND_HOST = os.environ.get("DASH_AUTH_BIND", "127.0.0.1")
BIND_PORT = int(os.environ.get("DASH_AUTH_PORT", "8766"))
DEFAULT_LANDING = os.environ.get("DASH_AUTH_LANDING", "/status/dash.html")
COOKIE_NAME = os.environ.get("DASH_AUTH_COOKIE", "DashSession")
TITLE = os.environ.get("DASH_AUTH_TITLE", "服务器状态大屏")
def _find_mascot():
    """登录页那张图在哪。给了环境变量就用它，否则按常见布局找一遍。

    仓库里立绘放在 site/assets/，装到 /opt/dashboard 之后是 ../site/assets/ ——
    两种布局都要能用，所以这里不写死一个路径。
    顺序是「先真图、后占位」：mascot.webp > mascot.png > mascot.svg，
    这样把 webp 删掉也不会 404（自动退回自绘的 svg）。
    （都找不到也不影响登录，页面上 <img onerror> 会自己藏起来，只是少了那张图。）
    """
    env = os.environ.get("DASH_AUTH_MASCOT", "").strip()
    if env:
        return env
    dirs = [
        os.path.join(HERE, "assets"),
        os.path.join(HERE, "..", "site", "assets"),
        os.path.join(HERE, "..", "assets"),
    ]
    for name in ("mascot.webp", "mascot.png", "mascot.svg"):
        for d in dirs:
            cand = os.path.join(d, name)
            if os.path.exists(cand):
                return os.path.abspath(cand)
    return os.path.join(dirs[0], "mascot.svg")


MASCOT_PATH = _find_mascot()
MASCOT_ROUTE = "/login-mascot." + (os.path.splitext(MASCOT_PATH)[1].lstrip(".") or "svg")
INSECURE_COOKIE = os.environ.get("DASH_AUTH_INSECURE_COOKIE", "") not in ("", "0", "false")

CAPTCHA_TTL = 600          # 验证码有效期 10 分钟
FAIL_WINDOW = 600          # 失败计数窗口 10 分钟
FAIL_LIMIT = 10            # 窗口内失败次数上限（建议与 fail2ban 的 maxretry 对齐）
COOL_DOWN = 300            # 超限后的冷却时间 5 分钟（建议与 fail2ban 首次封禁时长一致）

_conf = {}
_fails = {}                # ip -> [次数, 窗口起点, 冷却截止]


# --------------------------------------------------------------------------- 配置
def load_conf():
    global _conf, DEFAULT_LANDING, TITLE
    # utf-8-sig：手改过的 auth.json 可能带 BOM（Windows 记事本习惯），吃掉它
    with open(CONF_PATH, "r", encoding="utf-8-sig") as f:
        _conf = json.load(f)
    for key in ("username", "password_hash", "salt", "session_token", "captcha_key"):
        if key not in _conf:
            raise SystemExit("auth.json 缺少字段: %s" % key)
    # 配置文件里也能写落点和标题，命令行环境变量优先
    if not os.environ.get("DASH_AUTH_LANDING") and _conf.get("landing"):
        DEFAULT_LANDING = _conf["landing"]
    if not os.environ.get("DASH_AUTH_TITLE") and _conf.get("title"):
        TITLE = _conf["title"]
    return _conf


def check_username(user):
    return hmac.compare_digest(_conf["username"], user.strip())


def scrypt_hash(password, salt_hex):
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=2 ** 14, r=8, p=1, dklen=32,
    ).hex()


def check_password(password):
    expect = _conf["password_hash"]
    got = scrypt_hash(password, _conf["salt"])
    return hmac.compare_digest(expect, got)


# --------------------------------------------------------------------------- 验证码
def make_captcha():
    a = secrets.randbelow(9) + 2      # 2..10
    b = secrets.randbelow(9) + 2
    ans = "%d" % (a + b)
    ts = "%d" % int(time.time())
    banner = "%d+%d" % (a, b)
    sig = hmac.new(_conf["captcha_key"].encode(),
                   ("%s|%s|%s" % (ts, banner, ans)).encode(),
                   hashlib.sha256).hexdigest()[:32]
    # 令牌里只有三段：时间戳 | 题面 | 签名。题面是 "7+5" 这种，本身不含竖线，
    # 所以 split("|") 一定正好拿到三段。（早先版本把答案也塞进来，变成四段，
    # 校验端按三段解析 → 永远校验失败。）
    token = base64.urlsafe_b64encode(("%s|%s|%s" % (ts, banner, sig)).encode()).decode()
    return banner, token


def verify_captcha(token, answer):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split("|")
        if len(parts) != 3:
            return False
        ts, banner, sig = parts
    except Exception:
        return False
    try:
        if time.time() - int(ts) > CAPTCHA_TTL:
            return False
    except ValueError:
        return False
    want = hmac.new(_conf["captcha_key"].encode(),
                    ("%s|%s|%s" % (ts, banner, answer.strip())).encode(),
                    hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(want, sig)


# --------------------------------------------------------------------------- 失败限速
def is_cooling(ip):
    rec = _fails.get(ip)
    if not rec:
        return 0
    if rec[2] > time.time():
        return int(rec[2] - time.time())
    return 0


def note_fail(ip):
    now = time.time()
    rec = _fails.get(ip)
    if not rec or now - rec[1] > FAIL_WINDOW:
        rec = [0, now, 0.0]
    rec[0] += 1
    if rec[0] >= FAIL_LIMIT:
        rec[2] = now + COOL_DOWN
        rec[0] = 0
        rec[1] = now
    _fails[ip] = rec


def clear_fail(ip):
    _fails.pop(ip, None)


# --------------------------------------------------------------------------- 页面
PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 登录</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128011;</text></svg>">
<style>
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;display:flex;align-items:center;justify-content:center;padding:28px 16px;
       font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#e8eef7;
       background:#0a0f16 radial-gradient(120% 90% at 50% -10%,#16324f 0%,#0a0f16 60%) no-repeat;
       background-attachment:fixed;overflow-x:hidden}
  /* 背景里往上冒的气泡，跟大屏一个调子 */
  .sea{position:fixed;inset:0;overflow:hidden;pointer-events:none;z-index:0}
  .sea i{position:absolute;bottom:-60px;width:var(--s);height:var(--s);border-radius:50%;
         background:radial-gradient(circle at 32% 30%,#8fd0ff66,#3f86c41f 60%,transparent 72%);
         border:1px solid #8fd0ff1f;animation:rise var(--d) linear infinite;animation-delay:var(--dl)}
  @keyframes rise{0%{transform:translateX(0) translateY(0);opacity:0}
                  12%{opacity:.9}
                  100%{transform:translateX(var(--dx)) translateY(-108vh);opacity:0}}
  .card{position:relative;z-index:1;width:min(392px,92vw);padding:26px 30px 24px;border-radius:20px;
        background:linear-gradient(180deg,#111c2b,#0d1622);
        border:1px solid #1e3348;box-shadow:0 24px 60px -20px #000,0 0 0 1px #ffffff08 inset}
  /* 看板娘占位图 */
  .mascot{position:relative;display:flex;flex-direction:column;align-items:center;margin:-6px 0 10px}
  .mascot img{width:124px;height:auto;display:block;
              filter:drop-shadow(0 10px 22px #2f8fd055) drop-shadow(0 0 18px #4aa8ff33);
              animation:bob 4.6s ease-in-out infinite}
  @keyframes bob{0%,100%{transform:translateY(0) rotate(-1.4deg)}
                 50%{transform:translateY(-7px) rotate(1.4deg)}}
  .hi{position:relative;margin-bottom:6px;padding:7px 13px;border-radius:12px;font-size:12.5px;
      background:#132539;border:1px solid #27506f;color:#a9cdeb;white-space:nowrap}
  .hi:after{content:"";position:absolute;left:50%;bottom:-6px;margin-left:-5px;
            width:10px;height:10px;background:#132539;border-right:1px solid #27506f;
            border-bottom:1px solid #27506f;transform:rotate(45deg)}
  h1{margin:0 0 4px;font-size:19px;text-align:center;letter-spacing:.5px}
  .sub{margin:0 0 20px;text-align:center;font-size:12.5px;color:#7d93ab}
  label{display:block;font-size:12.5px;color:#9db2c7;margin:0 0 6px}
  input{width:100%;padding:11px 13px;border-radius:10px;border:1px solid #24405a;
        background:#0a121c;color:#e8eef7;font-size:15px;outline:none}
  input:focus{border-color:#3d7ebd;box-shadow:0 0 0 3px #3d7ebd26}
  .row{margin-bottom:15px}
  .cap{display:flex;gap:10px;align-items:center}
  .q{flex:0 0 auto;padding:11px 14px;border-radius:10px;background:#0a121c;
     border:1px solid #24405a;font:600 15px/1 ui-monospace,Consolas,monospace;color:#7cc4ff;
     letter-spacing:1px;white-space:nowrap}
  button{width:100%;margin-top:4px;padding:12px;border:0;border-radius:10px;cursor:pointer;
         font-size:15px;font-weight:600;color:#04121f;
         background:linear-gradient(180deg,#7cc4ff,#4a9fe0)}
  button:hover{filter:brightness(1.08)}
  .err{margin:0 0 16px;padding:10px 13px;border-radius:10px;font-size:13px;
       background:#3a1114;border:1px solid #7d2a30;color:#ffb4b8}
  .foot{margin:18px 0 0;text-align:center;font-size:11.5px;color:#5d7387;line-height:1.7}
  .foot a{color:#6f93b3}
  @media (prefers-reduced-motion:reduce){.mascot img,.sea i{animation:none}}
</style>
</head>
<body>
<div class="sea">
  <i style="--s:9px;--l:8%;--d:19s;--dl:0s;--dx:22px"></i>
  <i style="--s:5px;--l:19%;--d:25s;--dl:3s;--dx:-16px"></i>
  <i style="--s:13px;--l:31%;--d:22s;--dl:7s;--dx:14px"></i>
  <i style="--s:6px;--l:44%;--d:28s;--dl:1.5s;--dx:-20px"></i>
  <i style="--s:11px;--l:57%;--d:20s;--dl:9s;--dx:18px"></i>
  <i style="--s:5px;--l:68%;--d:26s;--dl:5s;--dx:-12px"></i>
  <i style="--s:15px;--l:79%;--d:24s;--dl:2s;--dx:16px"></i>
  <i style="--s:7px;--l:90%;--d:21s;--dl:11s;--dx:-24px"></i>
</div>
<form class="card" method="post" action="/login">
  <div class="mascot">
    <span class="hi">看一眼机器还好吗</span>
    <img src="__MASCOT__" alt="" onerror="this.style.display='none'">
  </div>
  <h1>__TITLE__</h1>
  <p class="sub">进门要口令</p>
  __ERROR__
  <div class="row">
    <label for="user">账号</label>
    <input id="user" name="user" type="text" required autofocus
           placeholder="请输入账号" autocomplete="username" spellcheck="false">
  </div>
  <div class="row">
    <label for="pw">口令</label>
    <input id="pw" name="pw" type="password" required
           placeholder="请输入访问口令" autocomplete="current-password">
  </div>
  <div class="row">
    <label for="cap">验证码 · 请算出结果</label>
    <div class="cap">
      <span class="q">__QUESTION__ = ?</span>
      <input id="cap" name="cap" type="text" inputmode="numeric" required
             placeholder="答案" autocomplete="off">
    </div>
  </div>
  <input type="hidden" name="cap_token" value="__TOKEN__">
  <input type="hidden" name="next" value="__NEXT__">
  <button type="submit">进入大屏</button>
  <p class="foot">连续答错会被暂时挡住</p>
</form>
</body>
</html>
"""

LOGOUT_PAGE = """<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>已退出 · __TITLE__</title>
<link rel='icon' href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128011;</text></svg>">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;
justify-content:center;font:15px/1.7 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
color:#e8eef7;background:#0a0f16 radial-gradient(120% 90% at 50% -10%,#16324f,#0a0f16 60%) no-repeat}
p{text-align:center}a{display:inline-block;margin-top:10px;padding:9px 20px;border-radius:9px;
color:#04121f;background:linear-gradient(180deg,#7cc4ff,#4a9fe0);text-decoration:none;font-weight:600}
</style></head><body><div><p>已经退出了，Cookie 也清掉了。</p>
<p><a href='/login'>重新登录</a></p></div></body></html>"""


def render_page(next_url, error=None, question=None, token=None):
    if error:
        err = '<p class="err">%s</p>' % html.escape(error)
    else:
        err = ""
    if question is None or token is None:
        question, token = make_captcha()
    page = PAGE
    page = page.replace("__TITLE__", html.escape(TITLE))
    page = page.replace("__MASCOT__", html.escape(MASCOT_ROUTE, quote=True))
    page = page.replace("__ERROR__", err)
    page = page.replace("__QUESTION__", html.escape(question))
    page = page.replace("__TOKEN__", html.escape(token, quote=True))
    page = page.replace("__NEXT__", html.escape(next_url, quote=True))
    return page.encode("utf-8")


def safe_next(raw):
    """只允许站内相对路径，防止开放重定向；并决定"没指定去哪"时落到哪。

    两个讲究：
    1. 挡住网关自己的入口。登录页的 X-Original-URI 就是 /login，
       照着它跳会被送回登录页 —— 看起来就像口令错了。
    2. "/" 通常是反代后面的业务后台，不是大屏。想登录完看大屏的人
       会被扔进后台，一脸懵。所以没指定目标时统一落到 DEFAULT_LANDING。
    """
    if not raw:
        return DEFAULT_LANDING
    p = urlparse(raw)
    if p.scheme or p.netloc or not raw.startswith("/"):
        return DEFAULT_LANDING
    if p.path in ("/", "/login", "/logout", MASCOT_ROUTE):
        return DEFAULT_LANDING
    return raw


# --------------------------------------------------------------------------- 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "DashAuth/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), self.client_address[0], fmt % args))

    # ---- 工具
    def client_ip(self):
        # Caddy 会把真实客户端地址放进 X-Forwarded-For
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def cookie_flags(self):
        return "" if INSECURE_COOKIE else "; Secure"

    def send_html(self, body, code=200, extra=None):
        # 允许传 str（容易写错成 str，写出去会 TypeError、页面全白），统一转成 bytes
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def original_uri(self):
        return safe_next(self.headers.get("X-Original-URI", "/"))

    def send_file(self, path, ctype, max_age=604800):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=%d" % max_age)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ---- GET
    def do_GET(self):
        path = urlparse(self.path).path
        if path == MASCOT_ROUTE:
            ctype = mimetypes.guess_type(MASCOT_PATH)[0] or "application/octet-stream"
            self.send_file(MASCOT_PATH, ctype)
            return
        if path == "/logout":
            self.send_html(
                LOGOUT_PAGE.replace("__TITLE__", html.escape(TITLE)),
                extra=[("Set-Cookie",
                        "%s=; Path=/; HttpOnly%s; SameSite=Lax; Max-Age=0"
                        % (COOKIE_NAME, self.cookie_flags()))],
            )
            return
        if path == "/health":
            # 给 systemd / 探活用，不含任何敏感信息
            self.send_html(b"ok")
            return
        qs = parse_qs(urlparse(self.path).query)
        nxt = safe_next((qs.get("next") or [self.original_uri()])[0])
        self.send_html(render_page(nxt))

    # ---- POST
    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/login":
            self.send_html(b"not found", code=404)
            return
        ip = self.client_ip()
        left = is_cooling(ip)
        if left:
            self.send_html(
                render_page("/", "尝试次数太多，请 %d 分钟后再来。" % max(1, left // 60)),
                code=429)
            return

        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(n).decode("utf-8", "replace")
        except Exception:
            body = ""
        form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
        nxt = safe_next(form.get("next", "/"))
        user = form.get("user", "")
        pw = form.get("pw", "")
        cap = form.get("cap", "")
        tok = form.get("cap_token", "")

        if not verify_captcha(tok, cap):
            note_fail(ip)
            self.send_html(render_page(nxt, "验证码不对，再算一次。"), code=401)
            return
        # 账号和口令都错时给同一句话，不告诉对方"账号是对的、口令错了"
        if not (check_username(user) and check_password(pw)):
            note_fail(ip)
            self.log_message("登录失败 ip=%s user=%r", ip, user)
            self.send_html(render_page(nxt, "账号或口令不对。"), code=401)
            return

        clear_fail(ip)
        self.log_message("登录成功 ip=%s", ip)
        self.send_response(302)
        self.send_header("Location", nxt)
        self.send_header("Set-Cookie",
                         "%s=%s; Path=/; HttpOnly%s; SameSite=Lax; Max-Age=2592000"
                         % (COOKIE_NAME, _conf["session_token"], self.cookie_flags()))
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    do_HEAD = do_GET


def main():
    load_conf()
    srv = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    srv.daemon_threads = True
    sys.stderr.write("登录网关已启动：http://%s:%d  (cookie=%s, landing=%s)\n"
                     % (BIND_HOST, BIND_PORT, COOKIE_NAME, DEFAULT_LANDING))
    if INSECURE_COOKIE:
        sys.stderr.write("警告：DASH_AUTH_INSECURE_COOKIE=1，Cookie 没有 Secure 标记，只用于本地调试\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
