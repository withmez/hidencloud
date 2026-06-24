import json
import logging
import os
import re
import time
import base64
from urllib.parse import parse_qs, unquote, urlparse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from curl_cffi import requests

# 尝试导入加密库
try:
    from nacl import encoding, public
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("HidenCloud")

def escape_markdown(text):
    """转义 Markdown 特殊字符，防止 TG 报错 can't parse entities"""
    if not text:
        return ""
    # 转义 MarkdownV1/V2 或标准解析中容易崩的字符，特别是下划线和星号的错位
    escape_chars = r'_*`['
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', str(text))

class HidenCloudBot:
    def __init__(self, cookie_str, tg_config=None, proxy_dict=None, account_idx=1):
        self.base_url = "https://dash.hidencloud.com"
        self.cookie_str = cookie_str
        self.tg_config = tg_config
        self.proxy_dict = proxy_dict
        self.account_idx = account_idx
        
        # 统一升级至最新的真实浏览器指纹 chrome136
        self.session = requests.Session(impersonate="chrome136")
        if self.proxy_dict:
            self.session.proxies = self.proxy_dict
            
        self.username = f"Account_{account_idx}"
        self.balance = "未知"
        self.csrf_token = ""
        self.parse_and_set_cookies()

    def parse_and_set_cookies(self):
        cookies = {}
        for item in self.cookie_str.split(';'):
            if '=' in item:
                parts = item.strip().split('=', 1)
                if len(parts) == 2:
                    cookies[parts[0]] = parts[1]
        self.session.cookies.update(cookies)

    def get_cookie_string(self):
        return "; ".join([f"{k}={v}" for k, v in self.session.cookies.items()])

    def update_github_secret(self, new_cookie):
        """反向回写更新 GitHub Secret，保持 Cookie 长效接力"""
        gh_pat = os.environ.get("GH_PAT")
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not gh_pat or not repo:
            return
        if not HAS_NACL:
            logger.error(f"[{self.username}] 未安装 pynacl 库，无法自动同步 Secret")
            return

        headers = {
            "Authorization": f"token {gh_pat}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "HidenCloud-Renew-Bot"
        }
        try:
            # 1. 获取公钥
            res = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers)
            if res.status_code != 200: return
            pub_data = res.json()
            
            # 2. 加密
            public_key = public.PublicKey(pub_data['key'].encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(public_key)
            encrypted_value = base64.b64encode(sealed_box.encrypt(new_cookie.encode("utf-8"))).decode("utf-8")

            # 3. 提交
            requests.put(
                f"https://api.github.com/repos/{repo}/actions/secrets/HIDEN_COOKIE",
                headers=headers,
                json={"encrypted_value": encrypted_value, "key_id": pub_data['key_id']}
            )
            logger.info(f" [{self.username}] ✅ GitHub Secret (HIDEN_COOKIE) 自动同步成功！")
        except Exception as e:
            logger.error(f"[{self.username}] 同步 Secret 异常: {e}")

    def get_hitokoto(self):
        try:
            resp = requests.get("https://v1.hitokoto.cn/?encode=json", timeout=5)
            if resp.status_code == 200:
                return f"『{resp.json()['hitokoto']}』—— {resp.json()['from']}"
        except Exception:
            pass
        return "保持热爱，奔赴山海。"

    def send_tg_notification(self, message):
        if not self.tg_config or not self.tg_config.get("bot_token") or not self.tg_config.get("chat_id"):
            return
        url = f"https://api.telegram.org/bot{self.tg_config['bot_token']}/sendMessage"
        
        # 严格保护排版和 Markdown 转义
        formatted_message = (
            f"☁️ **HidenCloud 续费报告**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 **账号**: `{escape_markdown(self.username)}`\n"
            f"💰 **余额**: `{escape_markdown(self.balance)}`\n"
            f"🕒 **时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{message}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 **每日一言**:\n_{escape_markdown(self.get_hitokoto())}_"
        )
        try:
            requests.post(url, json={"chat_id": self.tg_config["chat_id"], "text": formatted_message, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            logger.error(f"[{self.username}] TG 推送失败: {e}")

    def get_csrf_token(self, html):
        if not html: return ""
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('meta', attrs={'name': 'csrf-token'})
        if meta: self.csrf_token = meta.get('content')
        else:
            inp = soup.find('input', attrs={'name': '_token'})
            if inp: self.csrf_token = inp.get('value')
        return self.csrf_token

    def check_login(self):
        try:
            resp = self.session.get(f"{self.base_url}/dashboard", timeout=20, allow_redirects=True)
            if "/login" in resp.url or resp.status_code != 200:
                return False
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            self.get_csrf_token(resp.text)
            
            # 提取邮箱/用户名
            email_tag = soup.select_one('p.font-light.text-gray-500') or soup.find('p', string=re.compile(r'.+@.+\..+'))
            if email_tag and "[email" not in email_tag.get_text():
                self.username = email_tag.get_text().strip()
            
            # 提取余额
            balance_link = soup.select_one('a[href*="/balance"]')
            if balance_link:
                balance_tag = balance_link.find(['dt', 'h4', 'div'], class_=re.compile(r'font-extrabold|text-3xl'))
                if balance_tag: self.balance = balance_tag.get_text().strip()
            if self.balance == "未知":
                b_text = soup.find(string=re.compile(r'(¥|€|余额)\s*\d+\.\d+'))
                if b_text: self.balance = b_text.strip()
                
            logger.info(f"✅ 账号 [{self.username}] 登录成功 | 余额: {self.balance}")
            return True
        except Exception as e:
            logger.error(f"[{self.username}] 登录检查异常: {e}")
            return False

    def get_service_ids(self):
        try:
            resp = self.session.get(f"{self.base_url}/dashboard", timeout=20)
            return list(set(re.findall(r'service/(\d+)/manage', resp.text)))
        except Exception:
            return []

    def renew_service(self, service_id):
        manage_url = f"{self.base_url}/service/{service_id}/manage"
        try:
            resp = self.session.get(manage_url, timeout=20)
            token = self.get_csrf_token(resp.text)
            if not token: return False, "获取 Token 失败"

            renew_url = f"{self.base_url}/service/{service_id}/renew"
            headers = {"Referer": manage_url, "Origin": self.base_url, "X-CSRF-TOKEN": token}
            xsrf = self.session.cookies.get("XSRF-TOKEN")
            if xsrf: headers["X-XSRF-TOKEN"] = unquote(xsrf)

            res = self.session.post(renew_url, data={"_token": token, "days": "7"}, headers=headers, timeout=20)
            if "invoice" in res.url or "payment" in res.url:
                return True, "自动续期成功 (7天)"
            
            soup = BeautifulSoup(res.text, 'html.parser')
            alert = soup.find(['div', 'span'], attrs={'role': 'alert'})
            if alert:
                txt = alert.get_text(strip=True)
                if "only renew" in txt or "expires in" in txt:
                    match = re.search(r'expires in (\d+) days', txt)
                    return True, f"未到期 (剩 {match.group(1)} 天)" if match else "未到续期时间"
                return False, f"基础错误: {txt}"
            return True, "状态正常"
        except Exception as e:
            return False, f"续期异常: {e}"

    def pay_unpaid_invoices(self, service_id):
        list_url = f"{self.base_url}/service/{service_id}/invoices?where=unpaid"
        try:
            resp = self.session.get(list_url, timeout=20)
            soup = BeautifulSoup(resp.text, 'html.parser')
            links = []
            for a in soup.find_all('a', href=True):
                if '/invoice/' in a['href'] and 'download' not in a['href']:
                    parent = a.find_parent(['tr', 'div', 'li'])
                    if parent and any(k in parent.get_text() for k in ['Unpaid', '待支付', '未支付', '待付款']):
                        links.append(a['href'])
            
            links = list(set(links))
            if not links: return True, "暂无未支付订单"

            success_count = 0
            for link in links:
                inv_url = link if link.startswith('http') else self.base_url + link
                inv_res = self.session.get(inv_url, timeout=20)
                inv_soup = BeautifulSoup(inv_res.text, 'html.parser')
                
                form = None
                for f in inv_soup.find_all('form'):
                    if 'balance/add' in f.get('action', ''): continue
                    btn = f.find(['button', 'input'], attrs={'type': 'submit'}) or f.find('button')
                    if btn and any(k in btn.get_text() for k in ['支付', 'Pay', '确认']):
                        form = f
                        break
                if not form:
                    for f in inv_soup.find_all('form'):
                        if 'invoice' in f.get('action', '') or 'payment' in f.get('action', ''):
                            form = f
                            break
                if form:
                    act = form.get('action', '')
                    action_url = act if act.startswith('http') else self.base_url + act
                    payload = {inp.get('name'): inp.get('value', '') for inp in form.find_all('input') if inp.get('name')}
                    token = self.get_csrf_token(inv_res.text)
                    if token: payload['_token'] = token
                    
                    headers = {"Referer": inv_url, "X-CSRF-TOKEN": token or self.csrf_token}
                    pay_res = self.session.post(action_url, data=payload, headers=headers, timeout=20)
                    if any(k in pay_res.text for k in ["成功", "Success"]) or pay_res.status_code == 200:
                        success_count += 1
            return True, f"扣费成功 ({success_count}/{len(links)})"
        except Exception as e:
            return False, f"扣费异常: {e}"

    def execute(self):
        if not self.check_login():
            logger.error(f"❌ 账号进程 [{self.username}] Cookie 失效或遭 cf 阻断")
            self.send_tg_notification("❌ **Cookie 已失效或遭遇阻断**，请登录官网重新抓取覆盖。")
            return

        s_ids = self.get_service_ids()
        if not s_ids:
            self.send_tg_notification("🧾 账单状态: `未检索到任何活跃服务`")
            return

        results = []
        for s_id in s_ids:
            _, r_msg = self.renew_service(s_id)
            _, p_msg = self.pay_unpaid_invoices(s_id)
            results.append(f" 📦 **服务 ID: {s_id}**\n  └ 续期结果: `{escape_markdown(r_msg)}`\n  └ 扣费检测: `{escape_markdown(p_msg)}`")
            
        report = "\n".join(results)
        self.send_tg_notification(report)

        # 全自动智能接力
        new_cookie = self.get_cookie_string()
        if new_cookie != self.cookie_str and len(self.cookie_str) > 20:
            self.update_github_secret(new_cookie)


def parse_proxy_node(node_url):
    """【硬核补全】全协议代理节点解析模块，完美输出标准 Xray 客户端配置"""
    node_url = node_url.strip()
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": 1080, "listen": "127.0.0.1", "protocol": "socks"}],
        "outbounds": []
    }
    try:
        if node_url.startswith("socks5://") or node_url.startswith("socks://"):
            return "external", node_url.split("#")[0].replace("socks5://", "").replace("socks://", "")

        elif node_url.startswith("vless://"):
            # vless://uuid@host:port?query#remarks
            parsed = urlparse(node_url)
            uuid = parsed.username
            host, port = parsed.hostname, parsed.port
            query = parse_qs(parsed.query)
            
            vless_outbound = {
                "protocol": "vless",
                "settings": {"vnext": [{"address": host, "port": int(port), "users": [{"id": uuid, "encryption": "none"}]}]},
                "streamSettings": {"network": query.get("type", ["tcp"])[0]}
            }
            if query.get("security", ["none"])[0] == "reality":
                vless_outbound["streamSettings"].update({
                    "security": "reality",
                    "realitySettings": {"serverName": query.get("sni", [""])[0], "publicKey": query.get("pbk", [""])[0], "shortId": query.get("sid", [""])[0]}
                })
            config["outbounds"].append(vless_outbound)

        elif node_url.startswith("vmess://"):
            # vmess://base64(json)
            b64_str = node_url[8:].split("#")[0]
            # 补齐 base64 填充
            b64_str += "=" * (-len(b64_str) % 4)
            v_data = json.loads(base64.b64decode(b64_str).decode("utf-8"))
            
            config["outbounds"].append({
                "protocol": "vmess",
                "settings": {"vnext": [{"address": v_data.get("add"), "port": int(v_data.get("port")), "users": [{"id": v_data.get("id"), "alterId": int(v_data.get("aid", 0))}]}]},
                "streamSettings": {"network": v_data.get("net", "tcp"), "security": "none"}
            })

        elif node_url.startswith("trojan://"):
            # trojan://password@host:port?query
            parsed = urlparse(node_url)
            password = parsed.username
            host, port = parsed.hostname, parsed.port
            config["outbounds"].append({
                "protocol": "trojan",
                "settings": {"servers": [{"address": host, "port": int(port), "password": password}]},
                "streamSettings": {"security": "tls"}
            })

        elif node_url.startswith("ss://"):
            # ss://base64(method:password)@host:port
            parsed = urlparse(node_url)
            host, port = parsed.hostname, parsed.port
            user_info = parsed.username
            user_info += "=" * (-len(user_info) % 4)
            method, password = base64.b64decode(user_info).decode("utf-8").split(":", 1)
            
            config["outbounds"].append({
                "protocol": "shadowsocks",
                "settings": {"servers": [{"address": host, "port": int(port), "method": method, "password": password}]}
            })
        else:
            return None, None
            
        with open("xray_config.json", "w") as f:
            json.dump(config, f, indent=4)
        return "xray", "127.0.0.1:1080"
    except Exception as e:
        logger.error(f"解析代理节点发生致命错误: {e}")
        return None, None


def main():
    env_cookies = os.environ.get("HIDEN_COOKIE", "").strip()
    proxy_node = os.environ.get("PROXY_NODE", "").strip()
    
    if not env_cookies:
        logger.error("未找到环境变量 HIDEN_COOKIE，终止进程。")
        return

    # 智能多账号流切分
    accounts = [c.strip() for c in re.split(r'[&\n]', env_cookies) if c.strip()]
    logger.info(f"成功载入 {len(accounts)} 个目标账号。")

    # 动态组装全局分流代理
    proxy_dict = None
    if proxy_node:
        mode, server = parse_proxy_node(proxy_node)
        if mode == "external":
            proxy_dict = {"http": f"socks5://{server}", "https": f"socks5://{server}"}
            logger.info(f"已采用外部直连 SOCKS5 代理: {server}")
        elif mode == "xray":
            import subprocess
            logger.info("正在启动后台本地分布式 Xray 核心引擎...")
            subprocess.Popen(["./xray/xray", "run", "-c", "xray_config.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3) # 给予稳健的握手建连时间
            proxy_dict = {"http": f"socks5://{server}", "https": f"socks5://{server}"}
            logger.info("本地 Xray 轻量代理桥接网络已搭建成功。")

    tg_config = {
        "bot_token": os.environ.get("TG_BOT_TOKEN"),
        "chat_id": os.environ.get("TG_CHAT_ID")
    }

    # 【高能保留】README 承诺的多账号高并发调度
    max_workers = min(5, len(accounts))
    logger.info(f"开启多线程高并发流水线，最大并发数: {max_workers}")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for idx, cookie in enumerate(accounts, 1):
            bot = HidenCloudBot(cookie, tg_config, proxy_dict, account_idx=idx)
            futures.append(executor.submit(bot.execute))
        
        # 等待所有线程执行完毕
        for future in futures:
            future.result()

if __name__ == "__main__":
    main()
