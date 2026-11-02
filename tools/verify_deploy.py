#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署自检 —— 一条命令把整条链子跑一遍，只用标准库。

它验的不是「进程活着」，而是「该拦的拦住了、该放行的放行了」。
真正想确认的三件事：
  1. 没登录时，大屏和后台都进不去（被换成登录页）
  2. 登录（含算术验证码）之后，Cookie 能进、能读健康数据
  3. 短网址入口不是免口令通道，且那个含二维码的文件在短链下依然是 404

用法（在服务器本机跑，直连 Caddy 的 HTTPS 口）：
    DASH_PW='你的口令' python3 verify_deploy.py
    DASH_PW='…' DASH_BASE=https://203.0.113.10:8443 DASH_CA=./tls/ca.crt \
        DASH_SHORT_KEY=abcdef123456 python3 verify_deploy.py

可用环境变量：
    DASH_BASE        默认 https://127.0.0.1:8443      （自签 → 默认不校验证书）
    DASH_CA          给了就用它当 CA 校验（推荐：能同时验证 SAN 对不对）
    DASH_USER        默认 admin
    DASH_PW          必填
    DASH_COOKIE      默认 DashSession
    DASH_LANDING     默认 /status/dash.html
    DASH_SHORT_KEY   给了就顺带验短链
    DASH_ALLOW_FAIL  设为 1 时，全部跑完但恒以 0 退出（用于只想看报告）

退出码：全过 0，否则 1。
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("DASH_BASE", "https://127.0.0.1:8443").rstrip("/")
CA = os.environ.get("DASH_CA", "").strip()
USER = os.environ.get("DASH_USER", "admin")
PW = os.environ.get("DASH_PW", "")
COOKIE = os.environ.get("DASH_COOKIE", "DashSession")
LANDING = os.environ.get("DASH_LANDING", "/status/dash.html")
SHORT_KEY = os.environ.get("DASH_SHORT_KEY", "").strip()
ALLOW_FAIL = os.environ.get("DASH_ALLOW_FAIL", "") == "1"

LOGIN_MARK = 'name="cap_token"'   # 判定「这是登录页」的唯一可靠特征。
# 别用标题判定：登录页的 h1 和大屏标题是同一个字符串，两个页面都能匹配上。

CTX = ssl.create_default_context(cafile=CA) if CA else ssl._create_unverified_context()

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  · " + detail) if detail else ""))
    return ok


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CTX), NoRedirect())


def req(path, data=None, cookie=None, method=None, next_url=None):
    url = BASE + path
    body = None
    headers = {"User-Agent": "dash-verify/1"}
    if cookie:
        headers["Cookie"] = "%s=%s" % (COOKIE, cookie)
    if next_url:
        headers["X-Original-URI"] = next_url
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    r = urllib.request.Request(url, data=body, headers=headers,
                               method=method or ("POST" if body else "GET"))
    try:
        with OPENER.open(r, timeout=15) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def parse_login(html):
    """从登录页里取题面和令牌，自己算答案（不靠自己记住题目）。"""
    text = html.decode("utf-8", "replace")
    q = re.search(r'class="q">(\d+)\s*\+\s*(\d+)', text)
    t = re.search(r'name="cap_token"\s+value="([^"]*)"', text)
    if not q or not t:
        return None, None
    return int(q.group(1)) + int(q.group(2)), t.group(1)


def main():
    if not PW:
        raise SystemExit("没有 DASH_PW，没法验登录。")
    print("目标 %s   用户 %s" % (BASE, USER))
    print("-" * 62)

    # 1. 登录页本身
    st, hd, body = req("/login")
    check("登录页可访问 (200)", st == 200, "HTTP %s" % st)
    check("登录页是网关渲染的（有 cap_token 字段）", LOGIN_MARK.encode() in body)

    # 2. 免登录素材：证书与登录页立绘
    st, hd, body = req("/ca.crt")
    check("/ca.crt 可下载（手机装证书用）", st == 200 and b"BEGIN CERTIFICATE" in body,
          "HTTP %s, %d B" % (st, len(body)))
    st, hd, body = req("/login-mascot.svg")
    ok = st == 200 and len(body) > 200
    if not ok:  # 有人换成 png/webp，按实际文件名再试一次
        for ext in ("png", "webp"):
            st2, _, body2 = req("/login-mascot." + ext)
            if st2 == 200 and len(body2) > 200:
                st, body, ok = st2, body2, True
                break
    check("登录页立绘可访问", ok, "HTTP %s, %d B" % (st, len(body)))

    # 3. 没 Cookie：大屏必须被换成登录页（而不是真给文件）
    st, hd, body = req("/status/dash.html")
    intercepted = LOGIN_MARK.encode() in body or st in (401, 403)
    check("未登录访问大屏被拦下", intercepted,
          "HTTP %s, %d B%s" % (st, len(body), "" if intercepted else " ← 裸奔了"))

    # 4. 验证码错 → 401
    ans, tok = parse_login(req("/login")[2])
    st, hd, body = req("/login", data={"user": USER, "pw": PW, "cap": "9999",
                                       "cap_token": tok or "", "next": LANDING})
    check("验证码答错被拒 (401)", st == 401, "HTTP %s" % st)

    # 5. 口令错 → 401（换一个新题，避免被上面那条的限速连坐得太难看）
    ans, tok = parse_login(req("/login")[2])
    st, hd, body = req("/login", data={"user": USER, "pw": PW + "x",
                                       "cap": str(ans or 0), "cap_token": tok or "",
                                       "next": LANDING})
    check("口令错被拒 (401)", st == 401, "HTTP %s" % st)

    # 6. 全对 → 302 + Set-Cookie
    ans, tok = parse_login(req("/login")[2])
    if ans is None:
        check("能从登录页解析出验证码", False, "页面结构变了？")
        return report()
    st, hd, body = req("/login", data={"user": USER, "pw": PW, "cap": str(ans),
                                       "cap_token": tok, "next": LANDING})
    raw_cookie = hd.get("Set-Cookie", "")
    session = ""
    m = re.search(r"%s=([^;]+)" % re.escape(COOKIE), raw_cookie)
    if m:
        session = m.group(1)
    check("登录成功返回 302", st == 302, "HTTP %s" % st)
    check("响应里带 %s Cookie" % COOKIE, bool(session),
          "长度 %d" % len(session) if session else "没拿到")
    check("Cookie 带 HttpOnly", "HttpOnly" in raw_cookie)
    check("Cookie 带 SameSite=Lax", "SameSite=Lax" in raw_cookie.replace(" ", ""))
    check("Cookie 有效期 30 天", "Max-Age=2592000" in raw_cookie)
    check("302 落到落点页面", LANDING in hd.get("Location", ""),
          hd.get("Location", ""))

    # 7. 带 Cookie：大屏真身 + 健康数据
    st, hd, body = req("/status/dash.html", cookie=session)
    real = st == 200 and LOGIN_MARK.encode() not in body and len(body) > 3000
    check("带 Cookie 拿到真大屏", real, "HTTP %s, %d B" % (st, len(body)))
    st, hd, body = req("/status/health.json", cookie=session)
    data = None
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        pass
    check("带 Cookie 读到 health.json", st == 200 and isinstance(data, dict),
          "HTTP %s, %d B" % (st, len(body)))
    if isinstance(data, dict):
        check("health.json 有 schema 字段（采集器版本对得上）",
              "schema" in data, "schema=%r" % data.get("schema"))
        check("health.json 有容器列表", isinstance(data.get("containers"), list),
              "%d 个" % len(data.get("containers") or []))
    st, hd, body = req("/status/config.js", cookie=session)
    check("带 Cookie 读到 config.js", st == 200 and b"DASH_CONFIG" in body)

    # 8. 短链（可选）
    if SHORT_KEY:
        pre = "/s/%s" % SHORT_KEY
        st, hd, body = req(pre + "/dash.html", cookie=session)
        check("短链下能打开大屏", st == 200 and LOGIN_MARK.encode() not in body,
              "HTTP %s" % st)
        st, hd, body = req(pre + "/dash.html")
        check("短链不是免口令通道", LOGIN_MARK.encode() in body or st in (401, 403),
              "HTTP %s" % st)
        st, hd, body = req(pre + "/index.html", cookie=session)
        check("短链下 index.html 仍是 404", st == 404, "HTTP %s" % st)
        st, hd, body = req(pre + "/qr.png", cookie=session)
        check("短链下 qr.png 仍是 404", st == 404, "HTTP %s" % st)
        st, hd, body = req(pre + "/some-deep-link", cookie=session)
        check("短链下的陌生路径 302 回首页（不是 404 白屏）", st == 302,
              "HTTP %s → %s" % (st, hd.get("Location", "")))

    # 9. 退出
    st, hd, body = req("/logout", cookie=session)
    check("退出页可访问", st == 200, "HTTP %s" % st)
    check("退出时清掉 Cookie", "Max-Age=0" in hd.get("Set-Cookie", ""))

    return report()


def report():
    print("-" * 62)
    bad = [r for r in results if not r[1]]
    print("共 %d 项，通过 %d，失败 %d" % (len(results), len(results) - len(bad), len(bad)))
    if bad:
        print()
        for name, _, detail in bad:
            print("  ✗ %s  %s" % (name, detail))
    return 0 if (not bad or ALLOW_FAIL) else 1


if __name__ == "__main__":
    sys.exit(main())
