# 接入 MaiBot + SnowLuma —— 给 AI 的操作手册

> 相关契约：证书 / https 判定与改法见 [HTTPS与证书-给AI.md](HTTPS与证书-给AI.md)；人看的版本见 [接入-MaiBot与SnowLuma.md](接入-MaiBot与SnowLuma.md)。
> 这份文档写给**执行任务的 AI 助手**（Claude / GPT / 任何 agent），不是给人读的散文。
> 人版在 [`接入-MaiBot与SnowLuma.md`](接入-MaiBot与SnowLuma.md)，内容等价、表述不同。
> 仓库自身的规矩在根目录 [`AGENTS.md`](../AGENTS.md)，与本文件冲突时**以 AGENTS.md 为准**。

## §0 任务定义

**输入**：一台已经用 docker compose 跑着 MaiBot（`core`）+ SnowLuma + Caddy 的机器；本仓库的大屏已经按 README 部署在 `/opt/dashboard`（或你指定 `DASH_ROOT`）。
**产出**：

1. `/opt/dashboard/collector/health.config.json` —— 采集器配置（容器名、状态文件、探活）
2. `status/state.json` + `status/events.log` —— 由 watchdog 周期产出
3. `status/backup.json` —— 由 backup 脚本周期产出
4. 一个定时任务（cron 或 systemd timer），2 分钟跑一次采集器

**禁止**：改 `collector/health.py` 里已有字段的**名字与语义**；把真实 IP / QQ 号 / 内网主机名 / 绝对路径 / 密钥写进仓库纳管的文件。

**动手前先确认环境**：[`部署环境.md`](部署环境.md) 里有最低要求（Linux + Python 3.8+ + docker CLI）与实测过的版本。
在那台机器上先把 `python3 -V`、`docker --version`、`ss -lntp | grep -E '8443|8766'` 三条跑一遍，不满足就别往下改配置。

---

## §1 三条数据链（先记住这个，别的都是细节）

```
链 A（拉）：health.py --docker inspect--> containers[] 的 state/running/restart_count/image/uptime_sec
链 B（读）：health.py --read--> status_dir/{state.json, events.log, backup.json, qr.png}
链 C（探）：health.py --urlopen--> mcp{} 与 probes[] 的 ok/status/latency_ms
```

- 链 A **不需要业务侧配合**，配好容器名就有了。
- 链 B **必须由业务侧写出文件**。文件不存在不是错误：对应卡整块不渲染。
- 链 C 只用 HTTP，连不上就是 `ok:false`。

---

## §2 硬契约（改了页面就坏）

| 契约 | 说明 | 违反的后果 |
|---|---|---|
| `schema` 必须为 `2` | 页面按 2 解析 | 页面所有字段都取不到 |
| `watchdog.state ∈ {online, ok, up}` | 只认这三个值 | 大屏永久判红，且 `problems` 出现看门狗异常 |
| `backup.oss == "已上传"` | 字符串精确匹配才显示绿点 | 备份永远 "未上传" |
| `probes[].required === true && ok === false` | 进 `problems`，`overall` 变 `bad` | 横幅红、看板娘 droop |
| `status_file` 类键是**文件名**不是路径 | 相对 `status_dir` 解析 | 写成绝对路径 → 读不到 → 卡消失 |
| 采集器输出目录 === Caddy 的 `DASH_STATUS_DIR` | Caddy `root * {$DASH_STATUS_DIR}` | 页面 404 或读到旧文件 |
| `health.json` 留在登录之后 | `/status/*` 走 Cookie | 主机名/路径泄漏到公网 |

`overall` 的计算规则（采集器内部，**不要在前端重算**）：
`problems` 为空 → `"ok"`；否则 `"bad"`。`problems` 只来自三处：required 容器非 running、watchdog.state 不合法、required 探活失败。

---

## §3 `health.config.json` 全键表

> 容器名同样是**示例**（`maibot-core` / `maibot-snowluma` …）。生成或修改配置前先用
> `docker ps --format '{{.Names}}'` 取真实名字；名字写错只会得到 `missing`，不会报错，也不会进 `problems` 之外的任何提示。

| 键 | 类型 | 默认 | 语义 / 陷阱 |
|---|---|---|---|
| `status_dir` | str | `/opt/dashboard/status` | 读状态文件 + 写 `health.json`。必须与 Caddy 的 `DASH_STATUS_DIR` 一致 |
| `data_dir` | str | `/opt/dashboard/data` | 统计占用、扫数据库的根。**注意容器视角 `/MaiMBot/data` ↔ 宿主 `.../data/MaiMBot`，差一层** |
| `timezone_offset_hours` | num | `8` | 显示用；不读 TZ 环境变量 |
| `stale_after_sec` | num | `420` | 超过这么久没更新 → 前端显示「数据偏旧」，`mood` 降级 |
| `containers` | list | `[]` | `{name, label, required}`；`name` 是**容器名**（`docker ps` 的 NAMES），不是 compose 服务名 |
| `containers[].required` | bool | `true` | `false` 时容器挂了只红点、不进 `problems` |
| `mcp` | obj | `{enabled:false}` | `{enabled, probe_url, timeout}`；`enabled:false` → 输出 `{"ok":null,"disabled":true}`，卡整块不渲染 |
| `probes` | list | `[]` | `{name, label, url, required, timeout}`；任意条数，顺序即显示顺序 |
| `watchdog` | obj | `{enabled:true,...}` | `{enabled, state_file, events_file, events_tail, qr_file}`；`events_tail` 默认 8 |
| `backup` | obj | `{enabled:true,...}` | `{enabled, report_file, schedule}`；`schedule` 只用于右上角显示 |
| `databases` | obj | `{enabled:true,...}` | `{enabled, suffixes, limit}`；按后缀在 `data_dir` 下找，`limit` 是**展示条数上限** |
| `scan_file_cap` | int | `400000` | 扫 `data_dir` 的文件数上限；命中上限时体积统计会偏小（这是设计，不是 bug） |

**深合并**：只写在配置里的键会覆盖默认值，没写的用默认。读文件用 `utf-8-sig`（用户会用记事本存 BOM）。

---

## §4 三个状态产物的字段契约

### §4.1 `status/state.json`（watchdog 写）

| 字段 | 类型 | 必填 | 取值 | 缺省时的页面表现 |
|---|---|---|---|---|
| `state` | str | ✅ | `online`/`ok`/`up` | 卡显示但判红（`problems` 有看门狗条目） |
| `since` | str | ✅ | `YYYY-MM-DD HH:MM:SS` | 「状态开始」空白 |
| `since_epoch` | int | ⭕ | 秒级时间戳 | 时长算成 0 |
| `duration_sec` | int | ⭕ | 秒 | 页面自行用 `since_epoch` 兜底 |
| `down_today` | int | ⭕ | 今日掉线次数 | 显示 0 |
| `container_running` | bool | ⭕ | — | 显示「否」 |
| `last_check` | str | ⭕ | 时间串 | 空白 |
| `qr` | bool | ⭕ | `true` = 等扫码 | 不提示扫码 |

### §4.2 `status/events.log`（watchdog 追加）

一行一条，**按时间正序**（新的在末尾）。格式固定三段、双空格分隔：

```
YYYY-MM-DD HH:MM:SS  <online|offline>  <一句话说明>
```

页面读**最后 `events_tail` 行原样显示**，不做解析。要求：单行别超过约 40 个汉字（手机端会折行）；文件末尾留换行；条数自己截断（建议 200 行）。

### §4.3 `status/backup.json`（backup 脚本写）

| 字段 | 类型 | 说明 |
|---|---|---|
| `last_backup` | str | `YYYY-MM-DD HH:MM:SS` |
| `file` | str | 文件名（不含路径） |
| `size_bytes` | int | 大屏格式化成 GB/MB |
| `files` | int | 打包文件数 |
| `oss` | str | **`已上传` 才是绿**；其它值 = 黄 |
| `ok` | bool | `false` → `problems` 里出现「备份失败」→ 横幅红 |
| `schedule` | str | 右上角显示，如 `每日 04:00` |

### §4.4 `status/qr.png`（网关写）

只要文件存在就会显示「二维码 · 时间（N 秒前）」。`qr.exists=false` 时显示「无」。**不要**把它暴露在无需登录的路径（见 Caddy 里 `@private` 的 404 规则）。

---

## §5 探活规则（`probes` / `mcp` 共用）

判「通」的白名单：HTTP 状态码 `200/204/301/302/401/403/404`。
理由：401/403 说明端口在、服务在应答（只是要登录）；404 说明服务在、路径不对；这些都不是「服务死了」。

判「死」：连接被拒、DNS 失败、超时、5xx。

字段：`{name, label, required, ok, status?, latency_ms?, error?}`；`ok:false` 时带 `error` 文案，直接显示在卡片上。

**容器内端口不能写进 `probes`**：SnowLuma 的 OneBot WS 在容器内 `3001`，宿主 `127.0.0.1:3001` 必然失败。
判这个端口要在容器里探（`docker exec <容器> python3 -c "import socket;socket.create_connection(('127.0.0.1',3001),2)"`），
结果写进 `state.json` 的 `state`，走链 B。

**宿主 vs 容器**：采集器跑在宿主 → `127.0.0.1` 是宿主；采集器跑在容器 → 探宿主写 `172.18.0.1`（bridge 网关）。

---

## §6 常见改造的精确改法

| 需求 | 改哪里 | 具体 |
|---|---|---|
| 多盯一个容器 | `containers` 追加 | `{"name":"<docker ps 的 NAMES>","label":"<中文名>","required":true}` |
| 多一条探活 | `probes` 追加 | `{"name":"<机器名>","label":"<中文名>","url":"http://127.0.0.1:<port>/","required":false,"timeout":4}` |
| 只想盯端口不想报警 | 同上 | `required:false`；失败只显示灰点 |
| 嫌「数据偏旧」来得太快 | `stale_after_sec` | 设为采集周期的 2~3 倍（2 分钟一采 → 300~420） |
| 不要「自动备份」卡 | `backup.enabled=false` | 卡整块消失；不会报错 |
| 不要「联网服务(MCP)」卡 | `mcp.enabled=false` | 输出 `disabled:true`，卡消失 |
| 数据卡数字不对 | `data_dir` | 指向容器 `/MaiMBot/data` 对应的宿主路径（注意差一层） |
| 换采集频率 | cron / timer | `*/2` → `*/5`；同时调 `stale_after_sec` |

---

## §7 验证顺序（严格按序，任一步失败就停，不要跳步）

**1. 语法与格式**

```bash
python3 -m py_compile /opt/dashboard/collector/health.py
python3 -c "import json;json.load(open('/opt/dashboard/collector/health.config.json',encoding='utf-8-sig'));print('config ok')"
```

**2. 手动采一次**

```bash
sudo -u dash python3 /opt/dashboard/collector/health.py \
  --config /opt/dashboard/collector/health.config.json --out /tmp/h.json
```

**3. 断言（这段直接跑，全 True 才算通）**

```bash
python3 - <<'PY'
import json
d = json.load(open('/tmp/h.json', encoding='utf-8'))
assert d['schema'] == 2, d['schema']
assert d['overall'] in ('ok', 'bad')
assert isinstance(d['problems'], list)
names = {c['name'] for c in d['containers']}
assert names, 'containers 为空：配置里没写容器？'
assert all(c['state'] != 'missing' for c in d['containers']), \
       '有容器名写错：' + str([c['name'] for c in d['containers'] if c['state'] == 'missing'])
wd = d.get('watchdog') or {}
if wd and wd.get('state') not in ('online', 'ok', 'up'):
    print('!! 看门狗 state 不合法：', wd.get('state'))
for p in d.get('probes', []):
    print('探活', p['label'], p['ok'], p.get('status'), p.get('error'))
print('数据目录', d.get('data_dir_bytes'), '数据库', len(d.get('databases', [])))
print('OK  schema=%s overall=%s containers=%d probes=%d' %
      (d['schema'], d['overall'], len(d['containers']), len(d.get('probes', []))))
PY
```

**4. 页面真能读到**（必须带 Cookie；不带会拿到登录页 HTML）

```bash
TOK=$(sudo python3 -c "import json;print(json.load(open('/opt/dashboard/auth/auth.json'))['session_token'])")
curl -sk -b "DashSession=$TOK" "https://127.0.0.1:8443/status/health.json" | head -c 200
```

**5. 定时器真的在跑**（等两个周期后 `generated_ts` 必须变化）

```bash
systemctl list-timers dash-health.timer    # 或 crontab -l
stat -c '%y' /opt/dashboard/status/health.json
```

---

## §8 失败对照表

| 症状 | 先看哪个字段 | 根因 | 修 |
|---|---|---|---|
| 容器卡全是 `missing` | `containers[].state` | 容器名错 / `docker` 不在 PATH | `docker ps` 抄名字；用绝对路径 `/usr/bin/docker` |
| 横幅红但容器都好 | `problems[]` | 看门狗 state 非法 / required 探活失败 | 按 `problems` 文案改对应项 |
| 看门狗卡不出现 | `watchdog` 是否 `{}` | `state_file` 写成绝对路径 / 权限 | 改成文件名；`chmod 644` |
| 看门狗有数但判红 | `watchdog.state` | 写了 `running`/`1`/`true` | 只写 `online` |
| 二维码一直「无」 | `qr.exists` | 网关没把 `qr.png` 落到 `status_dir` | 对齐 `qr_file`；扫码后文件消失属正常 |
| 备份永远黄 | `backup.oss` | 不是精确字符串 `已上传` | 改成 `已上传` |
| MCP 离线 | `mcp.ok` | 用了 `127.0.0.1:8765` | 采集器在容器里要写 `172.18.0.1` |
| 探活红但网页能开 | `probes[].status` | url 写错/协议错 | `curl -sS -o /dev/null -w '%{http_code}'` 先确认 |
| 数据体积 0 或 None | `data_dir_bytes` | `data_dir` 指错层 | 容器 `/MaiMBot/data` ↔ 宿主 `.../data/MaiMBot` |
| 采集一次十几秒 | 耗时 | 几十万小文件 | 调小 `scan_file_cap` 或收窄 `data_dir` |
| 页面「数据偏旧」 | `generated_ts` | 采集器没跑 / 阈值太小 | 查 timer 与 `stale_after_sec` |
| `json.load` 报 BOM | — | 记事本存了 BOM | 采集器已用 `utf-8-sig`；仍报就重存无 BOM |

---

## §9 提交前必查（敏感信息）

提交/上传前在仓库根跑：

```bash
grep -rInE '([0-9]{1,3}\.){3}[0-9]{1,3}|sk-[A-Za-z0-9]{10,}|[1-9][0-9]{5,11}|nt_qq_|iZ[0-9a-z]+Z|/root/|/opt/maibot' \
  --exclude-dir=.git . | grep -v '127\.0\.0\.1' | grep -vE '203\.0\.113|198\.51\.100|192\.0\.2'
```

允许出现的：`127.0.0.1`、`0.0.0.0`、RFC5737 示例地址、文档里作为「禁写项」举的例子。
不允许：真实公网 IP、内网主机名、QQ 号、`sk-` 开头的 Key、真实数据目录。

---

## §10 不要做的事

1. **不要**改 `health.py` 里已有的键名（`schema`/`overall`/`probes`/`watchdog`…）——前端与验证脚本都按它写死。
2. **不要**把 `status/` 加进 Caddy 的免登录白名单；`health.json` 里有主机名和路径。
3. **不要**把 `status/` 目录挂成可写 web 根（会变成上传口）；采集器写文件走宿主，不经过 Caddy。
4. **不要**把容器内端口（`3001`）写进 `probes`——宿主探不到，会永久红。
5. **不要**让 cron 与 systemd timer 同时跑同一份采集器。
6. **不要**在配置里留 `required: true` 的探活却没手工验证过（`required: false` 起步，通了再升）。
7. **不要** commit / push，除非用户明确要求。
