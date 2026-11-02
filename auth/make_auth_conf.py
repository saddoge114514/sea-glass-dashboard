#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 auth.json —— 口令只以 scrypt 哈希形式落盘。

用法（口令从环境变量读，不进聊天记录、不进命令行历史）：
    DASH_AUTH_PW='你的口令' python3 make_auth_conf.py ./auth.json
    DASH_AUTH_PW='你的口令' DASH_AUTH_USER=admin DASH_AUTH_TITLE='我的大屏' python3 make_auth_conf.py ./auth.json

生成内容：
    username       登录账号（默认 admin）
    password_hash  scrypt(口令, salt, n=2^14, r=8, p=1) 的 hex
    salt           32 字节随机盐
    session_token  会话 Cookie 的值（32 字节随机 hex），Caddy 侧字面匹配它
    captcha_key    验证码 HMAC 签名密钥
    title          可选，登录页与大屏标题
文件权限 0600，目录 0700。
"""
import hashlib
import json
import os
import secrets
import sys


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: make_auth_conf.py <输出路径>")
    pw = os.environ.get("DASH_AUTH_PW")
    if not pw:
        raise SystemExit("环境变量 DASH_AUTH_PW 为空")
    user = os.environ.get("DASH_AUTH_USER", "admin").strip()
    if not user:
        raise SystemExit("账号不能为空")

    out = sys.argv[1]
    salt = secrets.token_hex(32)
    conf = {
        "username": user,
        "password_hash": hashlib.scrypt(
            pw.encode("utf-8"), salt=bytes.fromhex(salt),
            n=2 ** 14, r=8, p=1, dklen=32).hex(),
        "salt": salt,
        "session_token": secrets.token_hex(32),
        "captcha_key": secrets.token_hex(32),
    }
    title = os.environ.get("DASH_AUTH_TITLE", "").strip()
    if title:
        conf["title"] = title
    landing = os.environ.get("DASH_AUTH_LANDING", "").strip()
    if landing:
        conf["landing"] = landing

    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    try:
        os.chmod(parent, 0o700)
    except Exception:
        pass
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    # 只回显不含口令的信息
    print("auth.json 已写入 %s" % out)
    print("  账号 %r" % user)
    print("  口令长度 %d，scrypt(n=2^14,r=8,p=1) 哈希前 12 位 %s…"
          % (len(pw), conf["password_hash"][:12]))
    print("  session_token 长度 %d" % len(conf["session_token"]))
    print()
    print("下一步：把同一个 session_token 填进 Caddy 的环境变量 DASH_TOKEN，")
    print("       否则登录成功也进不去大屏（Cookie 值对不上）。")


if __name__ == "__main__":
    main()
