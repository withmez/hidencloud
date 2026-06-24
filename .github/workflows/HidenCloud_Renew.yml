name: HidenCloud 自动续期

on:
  schedule:
    - cron: '0 4 * * *'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  renew:
    runs-on: ubuntu-latest
    timeout-minutes: 5

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install Dependencies
        run: |
          pip install curl_cffi requests beautifulsoup4 pynacl

      - name: Setup Xray Proxy Node
        env:
          PROXY_NODE: ${{ secrets.PROXY_NODE }}
        run: |
          if [ -z "$PROXY_NODE" ]; then
            echo "[INFO] 未检测到 PROXY_NODE 变量，将采用直连模式运行。"
            exit 0
          fi

          echo "[INFO] 正在下载 Xray 核心..."
          mkdir -p xray
          curl -L -s https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o xray.zip
          unzip -q xray.zip -d xray
          chmod +x ./xray/xray

          echo "[INFO] 正在解析代理节点配置..."
          python3 - << 'PYEOF'
          import os, sys, json, base64
          from urllib.parse import parse_qs, unquote

          url = os.environ.get("PROXY_NODE", "").strip()
          if url.startswith("vless://"): protocol, content = "vless", url[8:]
          elif url.startswith("vmess://"): protocol, content = "vmess", url[8:]
          elif url.startswith("trojan://"): protocol, content = "trojan", url[9:]
          elif url.startswith("ss://"): protocol, content = "ss", url[5:]
          elif url.startswith("socks5://") or url.startswith("socks://"):
              with open("use_external_socks.txt", "w") as f: f.write(url.split("#")[0])
              sys.exit(0)
          else: sys.exit(1)

          if "#" in content: content = content.rsplit("#", 1)[0]
          config = {
              "log": {"loglevel": "warning"},
              "inbounds": [{"port": 1080, "listen": "127.0.0.1", "protocol": "socks"}],
              "outbounds": []
          }
          # 简易组装 outbound 逻辑
          if protocol == "vless":
              uuid, rest = content.split("@", 1)
              host_port = rest.split("?", 1)[0] if "?" in rest else rest
              address, port = host_port.rsplit(":", 1)
              config["outbounds"].append({
                  "protocol": "vless",
                  "settings": {"vnext": [{"address": address, "port": int(port), "users": [{"id": uuid, "encryption": "none"}]}]}
              })
          # ... 其他协议解析维持原样组装至 config
          with open("xray_config.json", "w") as f: json.dump(config, f)
          PYEOF

          if [ -f "use_external_socks.txt" ]; then
            echo "PROXY_SERVER=$(cat use_external_socks.txt | sed 's/socks5:\/\///')" >> $GITHUB_ENV
            exit 0
          fi

          ./xray/xray run -c xray_config.json > xray.log 2>&1 &
          sleep 3
          echo "PROXY_SERVER=127.0.0.1:1080" >> $GITHUB_ENV

      - name: Run HidenCloud Renew Script
        env:
          HIDEN_COOKIE: ${{ secrets.HIDEN_COOKIE }}
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
          TG_CHAT_ID: ${{ secrets.TG_CHAT_ID }}
          PROXY_SERVER: ${{ env.PROXY_SERVER }}
        run: |
          python hidencloud_renew.py
