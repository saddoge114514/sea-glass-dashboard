#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务器状态大屏的采集器 —— 只用 Python 标准库。

跑一次就写一份 JSON（默认 status/health.json），交给同目录的 dash.html 读。
推荐用 cron 每 2 分钟跑一次，见 README「部署」一节。

设计原则（都是踩坑换来的）：
  * 任何一个采集块失败都不能拖垮整份 JSON —— 每块独立 try/except
  * 不装 pip 包、不依赖 docker SDK，全部走 CLI + /proc
  * 原子写：先写 .tmp 再 os.replace，避免页面读到半个文件
  * 所有机器相关的值都在 health.config.json 里，脚本本身不含任何主机信息

用法：
    python3 health.py [--config /path/health.config.json] [--out /path/health.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "health.config.json")

CONFIG = {
    # 采集结果写哪里。dash.html 必须能读到同一个 health.json。
    "status_dir": os.path.join(HERE, "..", "status"),
    # 大屏「数据」卡片统计的目录（数据库、二维码之类都在它下面）
    "data_dir": os.path.join(HERE, "..", "data"),
    # 显示用时间偏移（小时）。中国 +8
    "timezone_offset_hours": 8,
    # 超过这个秒数没更新，页面就提示「数据偏旧」
    "stale_after_sec": 420,

    # 要监控的容器。label 是给人看的名字；required=false 的容器挂了不算故障。
    "containers": [
        {"name": "app", "label": "应用", "required": True},
        {"name": "gateway", "label": "网关", "required": True},
        {"name": "proxy", "label": "反向代理", "required": False},
    ],

    # 可选的 HTTP 探活（比如自己写的 /healthz）。enabled=false 时整块不显示。
    "mcp": {"enabled": False, "probe_url": "", "timeout": 4},

    # 其它探活，可以写多条：网关的 WebUI、SnowLuma 的 /、你自己的 /healthz……
    # required=true 的那条挂了会把 overall 判成有故障，false 的只提示。
    "probes": [],

    # 可选的看门狗产物：state.json 决定「在线/离线」，events.log 供页面展示
    "watchdog": {
        "enabled": True,
        "state_file": "state.json",
        "events_file": "events.log",
        "events_tail": 8,
        "qr_file": "qr.png",
    },

    # 可选的备份报告：backup.json，字段见 README
    "backup": {"enabled": True, "report_file": "backup.json", "schedule": "每日"},

    # data/ 下扫哪些文件当数据库展示
    "databases": {"enabled": True, "suffixes": [".db", ".sqlite", ".sqlite3"], "limit": 8},

    # 统计 data/ 大小时最多数多少个文件（防止几百万小文件把采集拖住）
    "scan_file_cap": 400000,
}


def load_config(path: str) -> dict:
    """配置文件覆盖默认值；文件不存在就用默认值继续跑（不报错）。"""
    cfg = json.loads(json.dumps(CONFIG))  # deep copy
    try:
        # utf-8-sig：Windows 记事本存出来的 JSON 带 BOM，用 utf-8 读会直接报
        # "Unexpected UTF-8 BOM"。这个坑很常见，所以这里主动吃掉 BOM。
        with open(path, "r", encoding="utf-8-sig") as fh:
            user = json.load(fh)
    except FileNotFoundError:
        return cfg
    except Exception as exc:  # noqa: BLE001
        raise SystemExit("配置文件读不了：%s（%s）" % (path, exc))
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


def make_now(cfg):
    offset = timedelta(hours=float(cfg.get("timezone_offset_hours", 8)))
    tz = timezone(offset)
    return lambda: datetime.now(tz)


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return default


def tail_lines(path: str, n: int = 8):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read().splitlines()[-n:]
    except Exception:
        return []


def run(cmd, timeout: int = 20):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:  # noqa: BLE001 - 采集器不能因为子进程炸掉而整体失败
        return -1, "", str(exc)


def parse_docker_time(raw: str):
    """把 docker 的 RFC3339 纳秒时间戳转成 datetime（3.10 的 fromisoformat 吃不下 9 位小数）。"""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("0001-01-01"):
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?", raw)
    if not match:
        return None
    base = match.group(1)
    frac = (match.group(2) or "")[:6]
    zone = match.group(3) or "+00:00"
    if zone == "Z":
        zone = "+00:00"
    text = base + ("." + frac if frac else "") + zone
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def collect_containers(cfg, now):
    result = []
    for spec in cfg.get("containers") or []:
        if isinstance(spec, str):
            spec = {"name": spec}
        name = spec.get("name")
        if not name:
            continue
        entry = {
            "name": name,
            "label": spec.get("label") or name,
            "required": bool(spec.get("required", True)),
            "state": "unknown",
            "running": False,
        }
        try:
            code, out, err = run(["docker", "inspect", name])
            if code != 0 or not out.strip():
                entry["state"] = "missing"
                entry["error"] = (err or "").strip()[:200]
                result.append(entry)
                continue
            data = json.loads(out)[0]
            state = data.get("State") or {}
            started = parse_docker_time(state.get("StartedAt"))
            entry.update(
                {
                    "state": state.get("Status") or "unknown",
                    "running": bool(state.get("Running")),
                    "restart_count": data.get("RestartCount"),
                    "health": (state.get("Health") or {}).get("Status"),
                    "image": (data.get("Config") or {}).get("Image"),
                    "started_at": state.get("StartedAt"),
                    "uptime_sec": int((now() - started).total_seconds()) if started else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            entry["state"] = "error"
            entry["error"] = str(exc)[:200]
        result.append(entry)
    return result


def collect_disk():
    try:
        usage = shutil.disk_usage("/")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def collect_mem():
    info = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key.strip()] = rest.strip()
        total = int(info.get("MemTotal", "0 kB").split()[0]) * 1024
        avail = int(info.get("MemAvailable", "0 kB").split()[0]) * 1024
        swap_total = int(info.get("SwapTotal", "0 kB").split()[0]) * 1024
        swap_free = int(info.get("SwapFree", "0 kB").split()[0]) * 1024
        return {
            "total": total,
            "available": avail,
            "used": total - avail,
            "percent": round((total - avail) / total * 100, 1) if total else None,
            "swap_total": swap_total,
            "swap_used": swap_total - swap_free,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def collect_host():
    host = {"cpu_count": os.cpu_count()}
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as fh:
            host["uptime_sec"] = int(float(fh.read().split()[0]))
    except Exception:
        pass
    try:
        load = os.getloadavg()
        host["load1"], host["load5"], host["load15"] = (
            round(load[0], 2),
            round(load[1], 2),
            round(load[2], 2),
        )
    except Exception:
        pass
    try:
        host["hostname"] = socket.gethostname()
    except Exception:
        pass
    return host


def collect_dir_size(path: str, cap: int = 400000) -> int:
    total = 0
    seen = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                seen += 1
                if seen > cap:
                    return total
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except Exception:
                    pass
    except Exception:
        pass
    return total


def collect_databases(cfg, data_dir: str):
    spec = cfg.get("databases") or {}
    if not spec.get("enabled", True) or not os.path.isdir(data_dir):
        return []
    suffixes = tuple(spec.get("suffixes") or (".db",))
    limit = int(spec.get("limit") or 8)
    found = []
    try:
        for root, dirs, files in os.walk(data_dir):
            dirs[:] = [d for d in dirs if d not in {"node_modules", ".git"}]
            for name in files:
                if name.endswith(suffixes):
                    path = os.path.join(root, name)
                    try:
                        rel = os.path.relpath(path, os.path.dirname(data_dir.rstrip("/")))
                        found.append({"path": rel.replace(os.sep, "/"), "size": os.path.getsize(path)})
                    except Exception:
                        pass
            if len(found) > 200:
                break
    except Exception:
        pass
    found.sort(key=lambda item: item["size"], reverse=True)
    return found[:limit]


def collect_qr(cfg, now):
    spec = cfg.get("watchdog") or {}
    name = spec.get("qr_file")
    if not spec.get("enabled", True) or not name:
        return {"exists": False}
    path = os.path.join(cfg["status_dir"], name)
    try:
        stat = os.stat(path)
        return {
            "exists": True,
            "mtime": datetime.fromtimestamp(stat.st_mtime, now().tzinfo).strftime("%Y-%m-%d %H:%M:%S"),
            "age_sec": int(time.time() - stat.st_mtime),
            "size": stat.st_size,
        }
    except Exception:
        return {"exists": False}


def collect_probe(cfg):
    spec = cfg.get("mcp") or {}
    if not spec.get("enabled"):
        return {"ok": None, "disabled": True}
    url = spec.get("probe_url") or ""
    if not url:
        return {"ok": None, "disabled": True, "error": "没配 probe_url"}
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=float(spec.get("timeout") or 4)) as resp:
            body = resp.read(400).decode("utf-8", "ignore")
        return {
            "ok": True,
            "status": resp.status,
            "latency_ms": int((time.time() - started) * 1000),
            "body": body.strip()[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def collect_probes(cfg):
    """按 probes 列表逐条探活。

    和 mcp 那条的区别：这里可以写多条，每条独立失败。
    「能返回 4xx」也算通——说明端口开着，只是没权限/路径不对，
    这种情况下判死会让「WebUI 要登录」被误报成离线。
    """
    out = []
    for spec in cfg.get("probes") or []:
        if isinstance(spec, str):
            spec = {"url": spec}
        url = (spec.get("url") or "").strip()
        if not url:
            continue
        name = spec.get("name") or url
        entry = {
            "name": name,
            "label": spec.get("label") or name,
            "required": bool(spec.get("required", False)),
            "ok": False,
        }
        started = time.time()
        try:
            with urllib.request.urlopen(url, timeout=float(spec.get("timeout") or 4)) as resp:
                resp.read(64)
            entry.update(
                {
                    "ok": True,
                    "status": resp.status,
                    "latency_ms": int((time.time() - started) * 1000),
                }
            )
        except urllib.error.HTTPError as exc:
            reachable = exc.code in (200, 204, 301, 302, 401, 403, 404)
            entry.update(
                {
                    "ok": reachable,
                    "status": exc.code,
                    "latency_ms": int((time.time() - started) * 1000),
                }
            )
            if not reachable:
                entry["error"] = "HTTP %s" % exc.code
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)[:160]
        out.append(entry)
    return out


def main():
    parser = argparse.ArgumentParser(description="服务器状态大屏采集器")
    parser.add_argument("--config", default=os.environ.get("DASH_HEALTH_CONFIG", DEFAULT_CONFIG))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    cfg = load_config(args.config)
    now = make_now(cfg)
    status_dir = os.path.abspath(cfg["status_dir"])
    data_dir = os.path.abspath(cfg["data_dir"])
    out_path = os.path.abspath(args.out) if args.out else os.path.join(status_dir, "health.json")
    stamp = now()

    containers = collect_containers(cfg, now)

    wd_spec = cfg.get("watchdog") or {}
    watchdog = {}
    if wd_spec.get("enabled", True) and wd_spec.get("state_file"):
        watchdog = read_json(os.path.join(status_dir, wd_spec["state_file"]), {}) or {}

    bk_spec = cfg.get("backup") or {}
    backup = {}
    if bk_spec.get("enabled", True) and bk_spec.get("report_file"):
        backup = read_json(os.path.join(status_dir, bk_spec["report_file"]), {}) or {}

    probes = collect_probes(cfg)

    problems = []
    for c in containers:
        if c.get("required", True) and not c.get("running"):
            problems.append("%s 容器未运行" % c.get("label"))
    if watchdog and str(watchdog.get("state", "")).lower() not in {"online", "ok", "up"}:
        problems.append("看门狗判定非在线：" + str(watchdog.get("state")))
    for probe in probes:
        if probe.get("required") and not probe.get("ok"):
            problems.append("探活失败：%s" % probe.get("label"))

    payload = {
        "schema": 2,
        "generated_at": stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_ts": int(stamp.timestamp()),
        "stale_after_sec": int(cfg.get("stale_after_sec") or 420),
        "overall": "ok" if not problems else "bad",
        "problems": problems,
        "host": collect_host(),
        "disk": collect_disk(),
        "mem": collect_mem(),
        "containers": containers,
        "watchdog": watchdog,
        "backup": backup,
        "mcp": collect_probe(cfg),
        "probes": probes,
        "events": tail_lines(os.path.join(status_dir, wd_spec["events_file"]),
                             int(wd_spec.get("events_tail") or 8))
        if wd_spec.get("enabled", True) and wd_spec.get("events_file") else [],
        "databases": collect_databases(cfg, data_dir),
        "data_dir_bytes": collect_dir_size(data_dir, int(cfg.get("scan_file_cap") or 400000))
        if os.path.isdir(data_dir) else None,
        "qr": collect_qr(cfg, now),
    }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)
    print("wrote %s (%d bytes)" % (out_path, os.path.getsize(out_path)))


if __name__ == "__main__":
    main()
