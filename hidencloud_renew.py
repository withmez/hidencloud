import json
import logging
import os
import re
import time
import base64
import subprocess
from urllib.parse import parse_qs, unquote, urlparse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from curl_cffi import requests

# 尝试导入加密库（用于反向同步 GitHub Secret）
try:
    from nacl import encoding, public
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

# 配置全局日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("HidenCloud")

def escape_markdown(text):
    """转义 Markdown 特殊字符，防止 TG 报错 can't parse entities"""
    if not text:
        return ""
    escape_chars = r'_*`['
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', str(text))

class HidenCloudBot:
    def __init__(self, cookie_str, tg_config=None, proxy_dict=None, account_idx=1):
        self.base_url = "https://dash.hidencloud.com"
        self.cookie_str = cookie_str
        self.tg_config = tg_config
        self.proxy_dict = proxy_dict
        self.account_idx = account_idx
        
        # 统一注入最新的真实浏览器指纹 chrome136
        self.session = requests.Session(impersonate="chrome136")
        if self.proxy_dict:
            self.session.proxies = self.proxy_dict
            
        self.username = f"Account_{account_idx}"
        self.balance = "未知"
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
        """长效自动化接力：安全同步回写最新的 Cookie 至 GitHub Secrets"""
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

            # 3. 提交回写
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
        
        formatted_message = (
            f"☁️ **HidenCloud 续费报告 (API版)**\n"
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

    def check_login_api(self):
        """混合嗅探：优先走快捷 API，若拿不到邮箱则动态回退至控制台 HTML 正则提取"""
        try:
            resp = self.session.get(f"{self.base_url}/api/user", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success" or "email" in data:
                    self.username = data.get("email") or data.get("name") or self.username
                    self.balance = str(data.get("balance", "未知"))
                    
                    # 联动优化：如果接口只给了默认代号，通过控制台 HTML 解析出真实邮箱
                    if "Account_" in str(self.username) or not self.username:
                        logger.info(f"[{self.username}] API未返回真实邮箱，正在尝试从控制台 HTML 提取...")
                        dash_resp = self.session.get(f"{self.base_url}/dashboard", timeout=20)
                        if dash_resp.status_code == 200:
                            soup = BeautifulSoup(dash_resp.text, 'html.parser')
                            email_tag = soup.select_one('p.font-light.text-gray-500') or soup.find('p', string=re.compile(r'.+@.+\..+'))
                            if email_tag and "[email" not in email_tag.get_text():
                                self.username = email_tag.get_text().strip()

                    logger.info(f"✅ 账号 [{self.username}] 登录成功 | 余额: {self.balance}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[{self.username}] API 登录检查异常: {e}")
            return False

    def get_services_api(self):
        """采用高效 API 获取服务列表"""
        try:
            resp = self.session.get(f"{self.base_url}/api/vps", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                services = data if isinstance(data, list) else data.get("data", [])
                return services
        except Exception as e:
            logger.error(f"[{self.username}] API 获取服务列表失败: {e}")
        return []

    def renew_service_api(self, service_id):
        """基于重构后的 API 提交执行服务续期"""
        try:
            renew_url = f"{self.base_url}/api/vps/renew"
            payload = {"id": service_id, "days": 7}
            res = self.session.post(renew_url, json=payload, timeout=20)
            
            if res.status_code == 200:
                data = res.json()
                msg = data.get("message", "请求完成")
                if "success" in data.get("status", "").lower() or data.get("code") == 200:
                    return True, "自动续期成功 (7天)"
                return True, f"完成: {msg}"
            elif res.status_code == 400:
                try:
                    msg = res.json().get("message", "未到续期时间")
                except:
                    msg = "未到续期时间"
                return True, f"状态正常 ({msg})"
            return False, f"HTTP错误: {res.status_code}"
        except Exception as e:
            return False, f"API续期异常: {e}"

    def pay_unpaid_invoices_api(self):
        """API 一键完成未支付账单的自动化余额扣除闭环"""
        try:
            resp = self.session.get(f"{self.base_url}/api/invoices", timeout=20)
            if resp.status_code != 200:
                return True, "暂无账单"
                
            data = resp.json()
            invoices = data if isinstance(data, list) else data.get("data", [])
            unpaid_count = 0
            success_count = 0
            
            for inv in invoices:
                if str(inv.get("status")).lower() in ["unpaid", "pending", "0", "未支付", "待支付"]:
                    unpaid_count += 1
                    inv_id = inv.get("id")
                    pay_res = self.session.post(f"{self.base_url}/api/invoice/pay", json={"id": inv_id}, timeout=20)
                    if pay_res.status_code == 200 and "success" in pay_res.text.lower():
                        success_count += 1
            
            if unpaid_count == 0:
                return True, "暂无待支付订单"
            return True, f"自动扣费完成 ({success_count}/{unpaid_count} 成功)"
        except Exception as e:
            return False, f"API 扣费异常: {e}"

    def execute(self):
        """多线程并发执行核心流"""
        if not self.check_login_api():
            logger.error(f"❌ 账号进程 [{self.username}] Cookie 失效或遭 cf 阻断")
            self.send_tg_notification("❌ **Cookie 已失效或遭遇阻断**，请登录官网重新抓取覆盖。")
            return

        services = self.get_services_api()
        if not services:
            _, p_msg = self.pay_unpaid_invoices_api()
            self.send_tg_notification(f"🧾 账单状态: `未检索到活跃VPS服务`\n└ 扣费检测: `{escape_markdown(p_msg)}`")
            return

        results = []
        for s in services:
            s_id = s.get("id")
            if not s_id: continue
            _, r_msg = self.renew_service_api(s_id)
            _, p_msg = self.pay_unpaid_invoices_api()
            results.append(f" 📦 **服务 ID: {s_id}**\n  └ 续期结果: `{escape_markdown(r_msg)}`\n  └ 扣费检测: `{escape_markdown(p_msg)}`")
            
        report = "\n".join(results)
        self.send_tg_notification(report)

        # 智能动态 Cookie 续航接力
        new_cookie = self.get_cookie_string()
        if new_cookie != self.cookie_str and len(self.cookie_str) > 20:
            self.update_github_secret(new_cookie)


def parse_proxy_node(node_url):
    """【高级组件级移植】全功能多协议代理节点智能解包模块"""
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
            b64_str = node_url[8:].split("#")[0]
            b64_str += "=" * (-len(b64_str) % 4)
            v_data = json.loads(base64.b64decode(b64_str).decode("utf-8"))
            config["outbounds"].append({
                "protocol": "vmess",
                "settings": {"vnext": [{"address": v_data.get("add"), "port": int(v_data.get("port")), "users": [{"id": v_data.get("id"), "alterId": int(v_data.get("aid", 0))}]}]},
                "streamSettings": {"network": v_data.get("net", "tcp"), "security": "none"}
            })

        elif node_url.startswith("trojan://"):
            parsed = urlparse(node_url)
            password = parsed.username
            host, port = parsed.hostname, parsed.port
            config["outbounds"].append({
                "protocol": "trojan",
                "settings": {"servers": [{"address": host, "port": int(port), "password": password}]},
                "streamSettings": {"security": "tls"}
            })

        elif node_url.startswith("ss://"):
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
        logger.error(f"解析代理节点发生错误: {e}")
        return None, None


def main():
    env_cookies = os.environ.get("HIDEN_COOKIE", "").strip()
    proxy_node = os.environ.get("PROXY_NODE", "").strip()
    
    if not env_cookies:
        logger.error("未找到环境变量 HIDEN_COOKIE，终止进程。")
        return

    # 兼容换行符以及 & 符号切分的多账号架构
    accounts = [c.strip() for c in re.split(r'[&\n]', env_cookies) if c.strip()]
    logger.info(f"成功载入 {len(accounts)} 个目标账号。")

    proxy_dict = None
    if proxy_node:
        mode, server = parse_proxy_node(proxy_node)
        if mode == "external":
            proxy_dict = {"http": f"socks5://{server}", "https": f"socks5://{server}"}
            logger.info(f"采用外部直连 SOCKS5 代理: {server}")
        elif mode == "xray":
            logger.info("启动分布式后台本地 Xray 核心传输链路...")
            subprocess.Popen(["./xray/xray", "run", "-c", "xray_config.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            proxy_dict = {"http": f"socks5://{server}", "https": f"socks5://{server}"}
            logger.info("本地代理网络桥接完成。")

    tg_config = {
        "bot_token": os.environ.get("TG_BOT_TOKEN"),
        "chat_id": os.environ.get("TG_CHAT_ID")
    }

    # 多账号并行高并发调度
    max_workers = min(5, len(accounts))
    logger.info(f"开启多线程并行调度流，最大并发数: {max_workers}")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for idx, cookie in enumerate(accounts, 1):
            bot = HidenCloudBot(cookie, tg_config, proxy_dict, account_idx=idx)
            futures.append(executor.submit(bot.execute))
        
        for future in futures:
            future.result()

if __name__ == "__main__":
    main()
