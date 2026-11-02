#!/bin/bash
# 自签 CA + 服务器证书（SAN 里带公网 IP / 域名），给 Caddy 用。
#
# 为什么自签：只是自己看的一块屏，不想为它买域名、也不想把 80/443 暴露给 ACME。
# 代价：手机/电脑第一次访问会报「不安全」，要把 ca.crt 装进设备的信任库，
#       装完之后地址栏就是正常的小锁（详见 README「证书」一节）。
#
# 用法：
#   ./gen_certs.sh [证书目录] [主机名或IP...]
#   ./gen_certs.sh ./tls 203.0.113.10 example.com
#
# 不传参数时默认写到 ./tls，SAN 只有 127.0.0.1 和 localhost（本机测试用）。

set -e

TLS="${1:-./tls}"
shift || true
HOSTS=("$@")
if [ ${#HOSTS[@]} -eq 0 ]; then
  HOSTS=(127.0.0.1 localhost)
fi

mkdir -p "$TLS"
cd "$TLS"

echo "=== 1. 根 CA（10 年）==="
if [ ! -f ca.key ]; then
  openssl genrsa -out ca.key 4096
  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
    -subj "/C=CN/O=Self-Signed/CN=Self-Signed Root CA" \
    -out ca.crt
  echo "CA 已创建"
else
  echo "CA 已存在，复用（换新 CA 会让已装证书的设备全部失效）"
fi

echo
echo "=== 2. 服务器证书 ==="
{
  echo "[req]"
  echo "distinguished_name = dn"
  echo "req_extensions = v3_req"
  echo "prompt = no"
  echo
  echo "[dn]"
  echo "C  = CN"
  echo "O  = Self-Signed"
  echo "CN = ${HOSTS[0]}"
  echo
  echo "[v3_req]"
  echo "keyUsage = keyEncipherment, dataEncipherment, digitalSignature"
  echo "extendedKeyUsage = serverAuth"
  echo "subjectAltName = @alt"
  echo
  echo "[alt]"
  ip_i=1
  dns_i=1
  for h in "${HOSTS[@]}"; do
    if [[ "$h" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "IP.$ip_i = $h"
      ip_i=$((ip_i+1))
    else
      echo "DNS.$dns_i = $h"
      dns_i=$((dns_i+1))
    fi
  done
} > san.cnf

openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -config san.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 3650 -sha256 -extfile san.cnf -extensions v3_req

cat server.crt ca.crt > server-fullchain.crt
rm -f server.csr

chmod 644 ca.crt server.crt server-fullchain.crt
chmod 600 ca.key server.key

echo
echo "=== 3. 核对 ==="
openssl x509 -in server.crt -noout -subject -issuer -dates
echo "--- SAN（必须包含你实际访问用的地址）---"
openssl x509 -in server.crt -noout -ext subjectAltName

echo
echo "=== 4. 文件清单 ==="
ls -l
echo
echo "把 ca.crt 装进手机/电脑的信任库，浏览器才不会报错。"
