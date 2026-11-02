# 把 MaiBot + SnowLuma 接上这块大屏

这份文档解决一件事：**让大屏上那些格子显示你家麦麦（MaiBot）和 SnowLuma 的真实状态**。

大屏本身不认识麦麦，也不调它的 API。它只吃三样东西：

1. `docker inspect` 出来的**容器状态**
2. 几个**约定格式的 JSON / 日志文件**（你自己写出来）
3. **HTTP 探活**（端口通不通）

所以「接入」= 把这三样产出来 + 写对 `health.config.json`。全套只动两个地方：
`/opt/dashboard/collector/health.config.json`，以及麦麦那侧的 `watchdog.sh` / `backup.sh`（如果你还没有）。

> 本文里的容器名、路径、端口都是**示例**。以你自己的 `docker ps` 和 `docker-compose.yml` 为准。

---

## 0. 先确认你的容器叫什么

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
docker inspect -f '{{.Name}}  {{.State.Status}}  {{.RestartCount}}' $(docker ps -aq) | sed 's|^/||'
```

一套典型的三容器长这样：

> 下表的容器名与端口都是**示例**（MaiBot 社区部署里常见的命名）。
> 照抄前先 `docker ps --format '{{.Names}}\t{{.Ports}}'` 看一眼你自己的实际值，再改配置。

| 用途 | 典型容器名 | 端口 | 要不要盯 |
|---|---|---|---|
| 麦麦本体 + WebUI | `maibot-core` | `18001:8001` | ✅ `required: true` |
| QQ 网关 | `maibot-snowluma` | `127.0.0.1:5099`（WebUI）、`127.0.0.1:6081`（noVNC）、容器内 `3001`（OneBot WS） | ✅ `required: true` |
| 反向代理 | `maibot-proxy` | `18443:443` | ⭕ `required: false` |
| NapCat（旧方案） | `maibot-napcat` | `16099:6099` | ❌ **别盯** |

> **坑 1：容器名不是服务名。**
> compose 默认把它拼成 `<项目目录名>-<服务名>-<序号>`，你写了 `container_name` 才是自己起的名。
> 名字写错的唯一表现是卡片上显示 `missing`，不报错、不退出。
>
> **坑 2：别盯已经停用的容器。**
> 像 `profiles: ["legacy"]` 里的 NapCat 常年 `Exited`，把它写进 `containers` 且 `required: true`，
> 大屏会一直红着。要么别写，要么 `required: false`。

---

## 1. 每一格数据是从哪来的

| 大屏上的卡片 | `health.json` 字段 | 谁产出 | 你要做什么 |
|---|---|---|---|
| 容器 | `containers[]` | `health.py` 自己 `docker inspect` | 配容器名 |
| 看门狗（在线/掉线次数/等扫码） | `watchdog{}` | 你的 `watchdog.sh` 写 `status/state.json` | 配文件名，或照 §3.1 实现 |
| 最近事件 | `events[]` | `watchdog.sh` 追加 `status/events.log` | 同上 |
| 数据 · 二维码 | `qr{}` | 网关把 `qr.png` 落到 `status/` | 配文件名 |
| 自动备份 | `backup{}` | `backup.sh` 写 `status/backup.json` | 照 §3.3 实现 |
| 联网服务（MCP） | `mcp{}` | `health.py` 探一个 URL | 配 `probe_url` |
| 探活（可多条） | `probes[]` | `health.py` 探任意 URL | 配 `probes`，SnowLuma 就在这里 |
| 数据 · 占用/数据库 | `data_dir_bytes` / `databases[]` | `health.py` 扫 `data_dir` | 配路径 |
| 主机 | `host{}` / `disk{}` / `mem{}` | `health.py` 读 `/proc` | 不用管 |

**关键认知**：除了容器和主机，其它格子都是「**你写出文件，大屏去读**」。
文件不存在不是错误 —— 那个格子会整块不显示。所以可以一步步来：先接容器，再接看门狗，再接备份。

---

## 2. 写配置

`/opt/dashboard/collector/health.config.json`（从 `health.config.example.json` 复制过来改）：

```json
{
  "status_dir": "/opt/dashboard/status",
  "data_dir": "/opt/dashboard/data",
  "timezone_offset_hours": 8,
  "stale_after_sec": 300,

  "containers": [
    { "name": "maibot-core",     "label": "麦麦本体",   "required": true },
    { "name": "maibot-snowluma", "label": "SnowLuma",  "required": true },
    { "name": "maibot-proxy",      "label": "反向代理",   "required": false }
  ],

  "watchdog": {
    "enabled": true,
    "state_file": "state.json",
    "events_file": "events.log",
    "events_tail": 8,
    "qr_file": "qr.png"
  },

  "backup": {
    "enabled": true,
    "report_file": "backup.json",
    "schedule": "每日 04:00"
  },

  "mcp": {
    "enabled": true,
    "probe_url": "http://172.18.0.1:8765/healthz",
    "timeout": 4
  },

  "probes": [
    { "name": "snowluma-webui", "label": "SnowLuma WebUI", "url": "http://127.0.0.1:5099/", "required": true,  "timeout": 4 },
    { "name": "bot-webui",      "label": "麦麦 WebUI",     "url": "http://127.0.0.1:18001/", "required": false, "timeout": 4 }
  ],

  "databases": {
    "enabled": true,
    "suffixes": [".db", ".sqlite", ".sqlite3"],
    "limit": 8
  },

  "scan_file_cap": 400000
}
```

逐键含义：

| 键 | 说明 |
|---|---|
| `status_dir` | 大屏读状态文件、写 `health.json` 的目录。**必须和 Caddy 的 `DASH_STATUS_DIR` 是同一个** |
| `data_dir` | 统计占用、扫数据库的目录（麦麦数据一般在这下面） |
| `timezone_offset_hours` | 显示用时间偏移，中国 `8`；容器里跑也都是按这个算，不依赖 TZ 环境变量 |
| `stale_after_sec` | 采集器多久没更新就提示「数据偏旧」。`300` 配 2 分钟一采，容错一次 |
| `containers[].required` | `false` 的容器挂了只显示红点，不算故障（不会把横幅变红） |
| `mcp.probe_url` | MCP 服务地址。**在容器/宿主里探宿主上的服务，用 `172.18.0.1` 不是 `127.0.0.1`**（见坑 4） |
| `probes[]` | 想盯几条写几条，`required: true` 的挂了会让横幅变红 |
| `watchdog.*_file` | 都是**相对 `status_dir`** 的文件名，别写绝对路径 |
| `scan_file_cap` | 扫 `data_dir` 时最多数多少个文件。几千个文件无所谓，几十万小文件要限流 |

改完先手动跑一次（§6），别急着挂定时任务。

---

## 3. 麦麦侧要产出的三份文件

### 3.1 `status/state.json` —— 决定「在线/离线」和看板娘的表情

大屏把它当成「看门狗的心跳」，字段就这么几个：

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | string | **必须是 `online` / `ok` / `up` 之一**，其它值一律判为异常 |
| `since` | string | 当前状态开始时间 `YYYY-MM-DD HH:MM:SS` |
| `since_epoch` | int | 同上，秒级时间戳（页面算时长用） |
| `duration_sec` | int | 已持续秒数（可选，页面不强制用） |
| `down_today` | int | 今天掉线次数 |
| `container_running` | bool | 容器在不在跑 |
| `last_check` | string | 最后一次检查时间 |
| `qr` | bool | 是否在等扫码（`true` 时氛围变黄，提示「等待扫码」） |

**判定口径建议**：别只看 `docker ps` 显示 `Up`，要看**容器内的 OneBot 端口在不在听**——
容器活着但 WebSocket 断了，麦麦就是不回消息，`Up` 会骗你。

一个够用的 `watchdog.sh`（每 15 秒跑一次，由 systemd timer 或 `while` 循环驱动）：

```bash
#!/usr/bin/env bash
# 判活：容器内 3001（OneBot WS）在不在听。容器活着但端口没人听 = 半死。
set -uo pipefail

CORE="${CORE:-maibot-core}"
STATUS_DIR="${STATUS_DIR:-/opt/dashboard/status}"
STATE="$STATUS_DIR/state.json"
EVENTS="$STATUS_DIR/events.log"
PROBE_PORT="${PROBE_PORT:-3001}"
TZ_OFFSET=8   # 只影响日志里写的时间

mkdir -p "$STATUS_DIR"
now() { TZ="UTC-${TZ_OFFSET}" date '+%Y-%m-%d %H:%M:%S'; }

# docker exec 里没有 nc 也能测：python3 是镜像自带的
if docker exec "$CORE" python3 -c \
     "import socket,sys; socket.create_connection(('127.0.0.1',$PROBE_PORT),2); sys.exit(0)" \
     >/dev/null 2>&1; then
  STATE_NOW=online
  QR=false
else
  STATE_NOW=offline
  QR=false
fi

# 读上一次的状态，判断「变了没有」
prev_state=""; prev_since=""; down_today=0
[ -f "$STATE" ] && eval "$(python3 - "$STATE" <<'PY'
import json,sys,shlex
d=json.load(open(sys.argv[1],encoding="utf-8-sig"))
print("prev_state=%s" % shlex.quote(str(d.get("state",""))))
print("prev_since=%s" % shlex.quote(str(d.get("since",""))))
print("down_today=%d"   % int(d.get("down_today",0) or 0))
PY
)"

if [ "$STATE_NOW" != "$prev_state" ]; then
  since="$(now)"
  [ "$STATE_NOW" = offline ] && down_today=$((down_today+1))
  printf '%s  %-7s %s\n' "$(now)" "$STATE_NOW" \
    "$([ "$STATE_NOW" = online ] && echo '容器在跑，WebSocket 在听' || echo '容器内端口无人监听')" >> "$EVENTS"
  tail -n 200 "$EVENTS" > "$EVENTS.tmp" && mv "$EVENTS.tmp" "$EVENTS"
else
  since="${prev_since:-$(now)}"
fi

since_epoch=$(date -d "$since" +%s 2>/dev/null || date +%s)
printf '{"state":"%s","since":"%s","since_epoch":%s,"duration_sec":%s,"down_today":%s,"container_running":%s,"last_check":"%s","qr":%s}\n' \
  "$STATE_NOW" "$since" "$since_epoch" "$(( $(date +%s) - since_epoch ))" "$down_today" \
  "$(docker inspect -f '{{.State.Running}}' "$CORE" 2>/dev/null || echo False)" \
  "$(now)" "$QR" > "$STATE.tmp"
mv "$STATE.tmp" "$STATE"
```

要点：
- **原子写**：先写 `.tmp` 再 `mv`。直接覆盖时采集器可能正好读到半个文件 → `json.load` 失败 → 那一次采集就没有看门狗数据。
- **只有状态变化才追加日志**，否则 `events.log` 每 15 秒长一行，一年就是 200 万行。
- 日志留最近 200 行就够（大屏只显示最后 8 行）。

### 3.2 `status/events.log`

一行一条，大屏原样贴最后 8 行：

```
2026-01-01 11:59:45  online   容器在跑，WebSocket 在听
2026-01-01 10:41:07  offline  容器内端口无人监听，已重启容器
```

时间 + 两个空格 + 状态 + 两个空格 + 一句话。**别写太长**，手机上会折成三行。

### 3.3 `status/backup.json` —— 「自动备份」卡片

```json
{
  "last_backup": "2026-01-01 04:00:12",
  "file": "backup-20260101-0400.tar.gz",
  "size_bytes": 536870912,
  "files": 128,
  "oss": "已上传",
  "ok": true,
  "schedule": "每日 04:00"
}
```

| 字段 | 说明 |
|---|---|
| `oss` | **字符串 `已上传` 才算绿**；其它值（`未上传`、`失败`、空）都是黄点 |
| `ok` | 本次备份是否成功；`false` 会让横幅变红 |
| `schedule` | 显示在卡片右上角，随便写，别写太长 |

`backup.sh` 收尾时这么写就行：

```bash
cat > "$STATUS_DIR/backup.json.tmp" <<EOF
{"last_backup":"$(date '+%Y-%m-%d %H:%M:%S')","file":"$(basename "$TARBALL")",
 "size_bytes":$(stat -c%s "$TARBALL" 2>/dev/null || echo 0),"files":$FILE_COUNT,
 "oss":"$OSS_RESULT","ok":$([ "$RC" -eq 0 ] && echo true || echo false),"schedule":"每日 04:00"}
EOF
mv "$STATUS_DIR/backup.json.tmp" "$STATUS_DIR/backup.json"
```

---

## 4. SnowLuma 的两条探活

SnowLuma 提供两样东西可看，**性质不同**：

**① WebUI（`127.0.0.1:5099`）—— 用 `probes` 探。**
它是宿主上能直接访问的 HTTP 端口，最适合 `probes`：

```json
{ "name": "snowluma-webui", "label": "SnowLuma WebUI", "url": "http://127.0.0.1:5099/", "required": true }
```

- 只绑 `127.0.0.1` 是**故意的**，别改成 `0.0.0.0` 或往 Caddy 上加公网入口。要看就 SSH 隧道：
  `ssh -L 5099:127.0.0.1:5099 root@<你的服务器>`，然后本地开 `http://127.0.0.1:5099/`。
- 返回 **401 / 403 / 404 都算「通」**（端口开着、服务在回答，只是要登录或路径不对）。
  采集器已经按这个口径判了：只有连不上/超时才判死。别把「要登录」当故障。

**② OneBot WebSocket（容器内 `3001`）—— 宿主探不到，别写进 `probes`。**

`3001` 在容器网络里，宿主 `curl 127.0.0.1:3001` 必然失败。两条路：

- **推荐**：交给 `watchdog.sh` 用 `docker exec` 去探（§3.1 那段就是干的这事），
  结果体现在「看门狗 · 在线/离线」和「最近事件」上。
- 想多看一眼容器端口映射：`docker port maibot-snowluma`（只会列出发布出来的 5099/6081）。

> **坑 3：`required: true` 的探活写错端口 = 大屏永久红。**
> 先 `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5099/` 手动确认通了，再写进配置。
> 不确定要不要报警的探活，一律 `required: false`。

---

## 5. 让采集器定时跑

**cron（最简单）**：

```cron
*/2 * * * * /usr/bin/python3 /opt/dashboard/collector/health.py --config /opt/dashboard/collector/health.config.json >> /var/log/dash-health.log 2>&1
```

**systemd timer（repo 自带，更好排错）**：

```bash
sudo cp /opt/dashboard/deploy/systemd/dash-health.service /opt/dashboard/deploy/systemd/dash-health.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dash-health.timer
systemctl list-timers dash-health.timer
```

两种都行，**别同时开**（会写同一份 `health.json`，虽然原子写不会坏，但没意义）。

> **坑 5：cron 的 PATH 很短。** `docker` 不在 `PATH` 里时，容器卡片会全是 `missing`。
> 用绝对路径 `/usr/bin/docker`，或者在 crontab 顶上写 `PATH=/usr/local/bin:/usr/bin:/bin`。
>
> **坑 6：`/etc/cron.d/` 里的文件不显示在 `crontab -l` 里。** 排查「到底有没有在跑」时两处都要看。

---

## 6. 先手动跑一次，看输出

```bash
sudo -u dash python3 /opt/dashboard/collector/health.py \
  --config /opt/dashboard/collector/health.config.json \
  --out /tmp/h.json
```

拿关键字段自查：

```bash
python3 - <<'PY'
import json
d = json.load(open('/tmp/h.json', encoding='utf-8'))
print('overall     :', d['overall'], d['problems'])
print('容器        :', [(c['name'], c['state'], c['required']) for c in d['containers']])
print('看门狗      :', d.get('watchdog', {}).get('state'))
print('探活        :', [(p['label'], p['ok']) for p in d.get('probes', [])])
print('MCP         :', d.get('mcp', {}).get('ok'))
print('数据目录    :', d.get('data_dir_bytes'))
print('数据库      :', [x['path'] for x in d.get('databases', [])])
PY
```

期望：
- `容器` 里三个都是你自己的容器名，`state` 为 `running`；`missing` = 名字写错（坑 1）
- `看门狗` 是 `online`；空字典 = `state.json` 没读到（路径/权限，坑 7）
- `探活` 里 SnowLuma 是 `True`
- `数据目录` 有数值；`None` = `data_dir` 不存在

再看页面（记得带 Cookie，否则会被换成登录页）：

```bash
TOK=$(sudo python3 -c "import json;print(json.load(open('/opt/dashboard/auth/auth.json'))['session_token'])")
curl -sk -b "DashSession=$TOK" https://127.0.0.1:8443/status/health.json | head -c 300
```

页面本身：浏览器打开 `https://<你的域名或IP>:8443/`，登录后看那几格是不是都有数。

---

## 7. 坑表

| 现象 | 原因 | 修法 |
|---|---|---|
| 容器卡片全是 `missing` | 容器名写错 / cron 里没有 `docker` | `docker ps` 抄名字；用绝对路径或设 `PATH` |
| 大屏一直红，`problems` 里有「容器未运行」 | 盯了已停用的容器（NapCat legacy） | 删掉这条，或 `required: false` |
| 看门狗卡片不显示 | `state.json` 没读到 | 确认 `watchdog.state_file` 是相对 `status_dir` 的文件名，且文件 0644 可读 |
| 看门狗有数但一直红 | `state` 写了 `running`、`1` 这类值 | 只认 `online` / `ok` / `up` |
| 二维码那格一直是「无」 | 网关没把 `qr.png` 落到 `status_dir` | 确认 `qr_file` 名字；登录时才有，扫完就删属正常 |
| MCP 一直离线 | 用了 `127.0.0.1:8765` | 探宿主服务要用 **`172.18.0.1`**（docker bridge 网关），见坑 4 |
| SnowLuma 探活离线但网页打得开 | 探活写的是容器内地址/端口 | 宿主视角写 `127.0.0.1:5099` |
| 数据目录体积是 0 | `data_dir` 指错层（`data/` vs `data/MaiMBot/`） | 麦麦的数据在**容器 `/MaiMBot/data`**，宿主对应 `.../data/MaiMBot`，差一层 |
| 采集一次要十几秒 | `data_dir` 下几十万小文件 | 调小 `scan_file_cap`，或把 `data_dir` 指到更内层 |
| `json.load` 报 `Unexpected UTF-8 BOM` | 用记事本存了 BOM | 采集器已按 `utf-8-sig` 读；还是报就重新存成无 BOM |
| `problems` 里有「探活失败」但服务正常 | 探活写成了 `https://` 或带了错路径，返回 5xx | 用 `curl -sS -o /dev/null -w '%{http_code}'` 确认；`required` 先设 `false` |
| 页面显示「数据偏旧」 | 采集器没在跑 / `stale_after_sec` 太小 | `systemctl list-timers` 和 `crontab -l` 两处都查 |

> **坑 4（最常踩）：`127.0.0.1` 在哪个命名空间。**
> 采集器在**宿主**上跑，`127.0.0.1` 就是宿主自己；要探宿主上监听 `127.0.0.1:8765` 的服务没问题。
> 但如果采集器在**容器里**跑，`127.0.0.1` 是容器自己，探宿主得写 `172.18.0.1`（docker bridge 的网关地址），
> 或者在 compose 里用 `host.docker.internal`（要 `extra_hosts`）。

---

## 8. 安全：`health.json` 里到底有什么

接完之后 `status/health.json` 里会出现：

- 主机名、CPU/内存/磁盘、负载
- **数据目录的绝对路径**，以及数据库文件名（可能带 QQ 号、群号这类目录名）
- 容器名、镜像 tag、重启次数
- 备份文件名（含日期时间）、备份里的文件数
- MCP 探活返回的 body 前 200 字节（工具名列表之类）

所以：

1. **它必须挂在登录后面**（本仓库的 Caddy 配置就是这样：`/status/*` 要 Cookie）。
2. **别把 `status/` 目录直接挂成公开静态站**，也别把访问日志放进 `status/`。
3. **截图发出去前打码**：主机名、路径、镜像名都算内部信息。
4. 想让某些值不出现：别把 `data_dir` 指到含敏感目录名的层；`mcp` 那条可以 `enabled: false`。

---

## 附：一份接好的 `health.json`（字段齐全的样子）

```json
{
 "schema": 2,
 "generated_at": "2026-01-01 12:00:00",
 "generated_ts": 1767240000,
 "stale_after_sec": 300,
 "overall": "ok",
 "problems": [],
 "containers": [
  {"name": "maibot-core", "label": "麦麦本体", "required": true, "state": "running",
   "running": true, "restart_count": 0, "image": "<镜像>", "uptime_sec": 14400},
  {"name": "maibot-snowluma", "label": "SnowLuma", "required": true, "state": "running",
   "running": true, "restart_count": 2, "image": "<镜像>", "uptime_sec": 9000}
 ],
 "watchdog": {"state": "online", "since": "2026-01-01 11:12:31", "down_today": 1,
              "container_running": true, "last_check": "2026-01-01 11:59:45", "qr": false},
 "backup": {"last_backup": "2026-01-01 04:00:12", "file": "backup-20260101-0400.tar.gz",
            "size_bytes": 536870912, "files": 128, "oss": "已上传", "ok": true,
            "schedule": "每日 04:00"},
 "mcp": {"ok": true, "status": 200, "latency_ms": 7, "body": "{\"ok\": true}"},
 "probes": [
  {"name": "snowluma-webui", "label": "SnowLuma WebUI", "required": true, "ok": true,
   "status": 200, "latency_ms": 11}
 ],
 "events": ["2026-01-01 11:59:45  online  容器在跑，WebSocket 在听"],
 "databases": [{"path": "data/MaiMBot/app/message.db", "size": 73400320}],
 "data_dir_bytes": 2147483648,
 "qr": {"exists": true, "mtime": "2026-01-01 11:58:02", "age_sec": 118, "size": 8192}
}
```

字段的机器可读定义见 [`AGENTS.md`](../AGENTS.md) 与 `examples/health.json`。
