#!/bin/bash
# 把大屏装进一个干净的 Ubuntu/Debian 机器（宿主直跑，不用 Docker）。
# 在仓库根目录执行：sudo ./deploy/install.sh
#
# 它做这些事：
#   1. 建系统用户 dash 和目录 /opt/dashboard
#   2. 拷 site/ collector/ auth/ tools/ 进去
#   3. 生成自签证书（如果 deploy/certs 里还没有）
#   4. 交互式问口令 → 生成 /opt/dashboard/auth/auth.json
#   5. 写 /opt/dashboard/dashboard.env（令牌、短链 key、路径）
#   6. 装 systemd 单元：dash-auth（常驻）+ dash-health.timer（每 2 分钟）
#   7. 打印剩下要手动做的事
#
# 幂等：重复跑不会覆盖已有的 auth.json / 证书 / dashboard.env。

set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/dashboard
USER_NAME=dash

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

[ "$(id -u)" = "0" ] || { echo "请用 root 跑（sudo $0）"; exit 1; }

say "1/7 用户与目录"
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$USER_NAME"
  echo "已创建用户 $USER_NAME"
fi
install -d -m 0755 "$DEST"
install -d -m 0755 "$DEST/site" "$DEST/collector" "$DEST/tools" "$DEST/deploy"
install -d -m 0750 -o root -g "$USER_NAME" "$DEST/status"
install -d -m 0700 "$DEST/auth"

say "2/7 拷文件"
cp -f "$REPO/site/dash.html" "$REPO/site/config.js" "$DEST/site/"
mkdir -p "$DEST/site/assets"
cp -f "$REPO/site/assets/"* "$DEST/site/assets/"
cp -f "$REPO/collector/health.py" "$DEST/collector/"
cp -f "$REPO/tools/verify_deploy.py" "$DEST/tools/"
cp -f "$REPO/auth/auth_gate.py" "$REPO/auth/make_auth_conf.py" "$DEST/auth/"
cp -f "$REPO/deploy/Caddyfile" "$DEST/deploy/Caddyfile.template"
install -d -m 0755 "$DEST/deploy/sites" "$DEST/deploy/sites-examples"
cp -f "$REPO/deploy/sites/"*.caddy "$DEST/deploy/sites/"
cp -f "$REPO/deploy/sites-examples/"*.caddy "$DEST/deploy/sites-examples/"
# 示例数据：只在 status 目录还空的时候放，免得盖掉真实的 health.json
[ -f "$DEST/status/health.json" ] || cp -f "$REPO/examples/health.json" "$DEST/status/health.json"
chown -R root:"$USER_NAME" "$DEST"
chmod -R g+rX "$DEST"
chmod 0600 "$DEST/status/health.json" 2>/dev/null || true
echo "已拷入 $DEST"

say "3/7 自签证书"
CERT_DIR="$DEST/certs"
install -d -m 0700 "$CERT_DIR"
if [ ! -f "$CERT_DIR/server-fullchain.crt" ]; then
  HOSTS=("127.0.0.1" "localhost")
  read -r -p "访问这块屏用的域名或公网 IP（留空=只本机）: " EXTRA
  [ -n "$EXTRA" ] && HOSTS+=($EXTRA)
  ( cd "$CERT_DIR" && bash "$REPO/deploy/gen_certs.sh" . "${HOSTS[@]}" >/dev/null )
  echo "证书已生成：$CERT_DIR"
else
  echo "证书已存在，跳过"
fi

say "4/7 口令与 auth.json"
if [ -f "$DEST/auth/auth.json" ]; then
  echo "auth.json 已存在，保留不动"
else
  read -r -p "登录账号 [admin]: " U
  U=${U:-admin}
  read -r -s -p "登录口令（输入时不显示）: " P; echo
  [ -n "$P" ] || { echo "口令不能为空"; exit 1; }
  read -r -p "大屏标题 [服务器状态大屏]: " T
  T=${T:-服务器状态大屏}
  DASH_AUTH_PW="$P" DASH_AUTH_USER="$U" DASH_AUTH_TITLE="$T" \
    python3 "$DEST/auth/make_auth_conf.py" "$DEST/auth/auth.json"
  unset P
fi
chown root:"$USER_NAME" "$DEST/auth"/* 2>/dev/null || true
chmod 0600 "$DEST/auth/auth.json"
chmod 0640 "$DEST/auth/auth_gate.py" "$DEST/auth/make_auth_conf.py"

say "5/7 采集器配置 + 环境文件"
if [ ! -f "$DEST/collector/health.config.json" ]; then
  cp -f "$REPO/collector/health.config.example.json" "$DEST/collector/health.config.json"
  echo "已放置采集器示例配置：$DEST/collector/health.config.json（里面的容器名要改成你自己的）"
else
  echo "采集器配置已存在，跳过"
fi
if [ ! -f "$DEST/dashboard.env" ]; then
  TOKEN=$(python3 -c "import json;print(json.load(open('$DEST/auth/auth.json'))['session_token'])")
  SHORT=$(openssl rand -hex 12)
  cat > "$DEST/dashboard.env" <<EOF
DASH_HTTPS_PORT=8443
DASH_CERT_FILE=$CERT_DIR/server-fullchain.crt
DASH_KEY_FILE=$CERT_DIR/server.key
DASH_CERTS_DIR=$CERT_DIR
DASH_AUTH_UPSTREAM=127.0.0.1:8766
DASH_COOKIE=DashSession
DASH_TOKEN=$TOKEN
DASH_STATUS_DIR=$DEST/status
DASH_ACCESS_LOG=/var/log/caddy/access.log
DASH_SHORT_KEY=$SHORT
DASH_APP_UPSTREAM=127.0.0.1:8001
DASH_SITES_GLOB=$DEST/deploy/sites/*.caddy
EOF
  chmod 0600 "$DEST/dashboard.env"
  echo "已写 $DEST/dashboard.env（含令牌，权限 600）"
  echo "  短网址入口：/s/$SHORT/dash.html"
else
  echo "dashboard.env 已存在，跳过"
fi
install -d -m 0750 /var/log/caddy

say "6/7 systemd"
install -m 0644 "$REPO/deploy/systemd/dash-auth.service" /etc/systemd/system/
install -m 0644 "$REPO/deploy/systemd/dash-health.service" /etc/systemd/system/
install -m 0644 "$REPO/deploy/systemd/dash-health.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dash-auth.service
systemctl enable --now dash-health.timer
systemctl start dash-health.service || true
echo "dash-auth 与 dash-health.timer 已启用"

say "7/7 还差什么（要你手动决定的部分）"
cat <<EOF
  1) Caddy 自己怎么装、配置文件放哪，各家不同，这里不给硬塞。
     模板在：$DEST/deploy/Caddyfile.template
     把里面的 {\$DASH_*:默认值} 换成 $DEST/dashboard.env 里的值，
     或者直接用 caddy 的 env 支持（systemd 的 EnvironmentFile=）。
     改完必须重启 Caddy（admin off 时 reload 会失败）。
     宿主的 Caddy 不在容器里时，日志路径要和 fail2ban 的 logpath 对齐。

  2) 防火墙/安全组放行 8443（或你改的端口）。

  3) 手机/电脑装一次 $CERT_DIR/ca.crt 进信任库，浏览器才不报错。
     也可以在浏览器里下载：https://<地址>:8443/ca.crt

  4) 把 ca.crt 与 server.key 留好：换 CA 会让所有已装证书的设备失效。

  5) 自检（最值得跑的一步）：
     cd $DEST && sudo -u $USER_NAME DASH_PW='你的口令' \\
       python3 tools/verify_deploy.py
     它会把「该拦的拦住、该放行的放行」整条链子验一遍。

  6) fail2ban 三件套在 $REPO/deploy/fail2ban/，拷到 /etc/fail2ban 对应目录，
     把 jail 里的 logpath 改成 Caddy 实际写的文件，然后
     fail2ban-client reload && fail2ban-client status dash-auth
EOF
