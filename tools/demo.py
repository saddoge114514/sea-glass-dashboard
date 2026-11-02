#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先看效果 —— 不用服务器、不用 Docker、不装任何东西，一条命令把大屏跑起来。

它干的事：把 site/ 和一份「示意数据」摆进临时目录，起一个本地静态服务器，
然后你就可以在浏览器里看到填满数据的样子。

    python3 tools/demo.py                # 用 examples/health.json（全部卡片都有数据）
    python3 tools/demo.py --open         # 顺手打开浏览器
    python3 tools/demo.py --port 9000
    python3 tools/demo.py --data 我的假数据.json
    python3 tools/demo.py --mood bad     # 看「出事」长什么样（ok / warn / bad / offline 四选一）

为什么不用 `python -m http.server` 了事：Windows 版 Python 把 .svg 映射成
`image/svg`（少了 +xml），Chromium 直接拒渲染，你会看到「立绘全是破图」——
那不是模板的问题。这里把 MIME 钉死，谁在哪台机器上跑都一样。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import shutil
import socketserver
import sys
import tempfile
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SITE = os.path.join(ROOT, "site")
DEFAULT_DATA = os.path.join(ROOT, "examples", "health.json")


class Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件 + 钉死的 MIME + 不缓存。"""

    # 少了这个，Windows 上 .svg 会被当成 image/svg，浏览器不认
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update({
        ".svg": "image/svg+xml",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
    })

    def end_headers(self):
        # 改数据后刷新就能看到，不用清缓存
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # 只在出错时说话，别刷屏
        if args and str(args[0]).startswith(("4", "5")):
            sys.stderr.write("  %s\n" % (fmt % args))


def freshen(payload: dict) -> dict:
    """把示意数据里的时间整体挪到「现在」，否则页面一开就是「数据陈旧」。

    只动时间字段，数值、容器名、事件内容一概不碰 —— 那些本就是假数据。
    """
    import datetime as _dt
    import re
    import time

    now = _dt.datetime.now()
    old_ts = payload.get("generated_ts")
    delta = 0
    if isinstance(old_ts, (int, float)):
        delta = int(time.time() - old_ts)
    payload["generated_ts"] = int(now.timestamp())
    payload["generated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    def shift(value):
        if not isinstance(value, str):
            return value
        try:
            t = _dt.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value
        return (t + _dt.timedelta(seconds=delta)).strftime("%Y-%m-%d %H:%M:%S")

    for key in ("last_backup",):
        if isinstance(payload.get("backup"), dict) and key in payload["backup"]:
            payload["backup"][key] = shift(payload["backup"][key])
    backup = payload.get("backup")
    if isinstance(backup, dict) and isinstance(backup.get("file"), str):
        # 文件名里的时间戳也要跟着挪，否则「上次备份」和文件名对不上，看着像假的
        m = re.match(r"^(backup-)(\d{8})-(\d{4})(.*)$", backup["file"])
        if m:
            try:
                t = _dt.datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M")
                t += _dt.timedelta(seconds=delta)
                backup["file"] = m.group(1) + t.strftime("%Y%m%d-%H%M") + m.group(4)
            except ValueError:
                pass
    wd = payload.get("watchdog")
    if isinstance(wd, dict):
        for key in ("since", "last_check"):
            if key in wd:
                wd[key] = shift(wd[key])
        if isinstance(wd.get("since_epoch"), (int, float)):
            wd["since_epoch"] = int(wd["since_epoch"] + delta)
    qr = payload.get("qr")
    if isinstance(qr, dict) and "mtime" in qr:
        qr["mtime"] = shift(qr["mtime"])
    events = payload.get("events")
    if isinstance(events, list):
        payload["events"] = [re.sub(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", lambda m: shift(m.group(0)), line)
                             if isinstance(line, str) else line
                             for line in events]
    return payload


def apply_mood(payload: dict, mood: str) -> dict:
    """把示意数据改成指定的状态，用来看四张状态立绘。

    ok      原样
    warn    把时间往回拨，触发「数据偏旧」
    bad     overall=bad + 一条问题 + 一个容器 exited + 备份失败
    offline 不写 health.json（页面取不到数据就是掉线状态）
    """
    import datetime as _dt
    import time

    if mood == "warn":
        stale_after = payload.get("stale_after_sec") or 420
        back = int(stale_after) + 300
        ts = int(time.time()) - back
        payload["generated_ts"] = ts
        payload["generated_at"] = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    elif mood == "bad":
        payload["overall"] = "bad"
        payload["problems"] = ["业务容器 没在跑", "备份失败"]
        cs = payload.get("containers") or []
        if cs:
            cs[0]["state"] = "exited"
            cs[0]["uptime_sec"] = 0
        if isinstance(payload.get("backup"), dict):
            payload["backup"]["ok"] = False
            payload["backup"]["oss"] = "没上传"
        dsk = payload.get("disk")
        if isinstance(dsk, dict):
            dsk["percent"] = 94.2
    return payload


def stage(data_path: str, keep_times: bool, mood: str = "ok") -> str:
    """把 site/ + 示意数据摆进临时目录，返回目录路径。"""
    if not os.path.isfile(data_path):
        raise SystemExit("找不到示意数据：%s" % data_path)
    with open(data_path, "r", encoding="utf-8-sig") as f:
        try:
            payload = json.load(f)
        except ValueError as e:
            raise SystemExit("示意数据不是合法 JSON：%s" % e)
    if not keep_times:
        payload = freshen(payload)
    payload = apply_mood(payload, mood)

    tmp = tempfile.mkdtemp(prefix="dash-demo-")
    src = os.path.join(tmp, "status")
    os.makedirs(src, exist_ok=True)
    for name in ("dash.html", "config.js"):
        shutil.copy(os.path.join(SITE, name), os.path.join(src, name))
    shutil.copytree(os.path.join(SITE, "assets"), os.path.join(src, "assets"))
    if mood != "offline":        # 掉线状态就别放数据了，页面取不到才是真掉线
        with open(os.path.join(src, "health.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    return src


def main() -> int:
    ap = argparse.ArgumentParser(description="本地起一个大屏演示（纯标准库）")
    ap.add_argument("--data", default=DEFAULT_DATA, help="示意数据 JSON，默认 examples/health.json")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--open", action="store_true", help="起完自动打开浏览器")
    ap.add_argument("--keep-times", action="store_true",
                    help="原样使用数据里的时间（默认会把时间挪到现在，免得一开就显示“数据陈旧”）")
    ap.add_argument("--mood", default="ok", choices=["ok", "warn", "bad", "offline"],
                    help="看哪一状态：ok 正常 / warn 偏旧 / bad 出事 / offline 读不到数据")
    args = ap.parse_args()

    root = stage(args.data, args.keep_times, args.mood)
    handler = functools.partial(Handler, directory=root)

    port = args.port
    for _ in range(20):                      # 端口被占就顺延，别让人手动改
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            port += 1
    else:
        raise SystemExit("127.0.0.1:%d 前后 20 个端口都被占了" % args.port)

    url = "http://127.0.0.1:%d/dash.html" % port
    print("演示数据 %s（状态：%s）" % (os.path.relpath(args.data, ROOT), args.mood))
    print("目录     %s" % root)
    print("地址     %s" % url)
    print("改数据    直接改上面的 JSON，刷新页面即可；Ctrl-C 结束。")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
