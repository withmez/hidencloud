import json
import logging
import os
import re
import time
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from curl_cffi import requests

try:
    from nacl import encoding, public
    HAS_NACL = True
except ImportError:
    HAS_NACL = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class HidenCloud:
    BASE_URL = "https://dash.hidencloud.com"

    def __init__(self, cookie_str, tg_config=None, proxies=None):
        self.cookie_str = cookie_str
        self.tg_config = tg_config
        self.session = requests.Session(impersonate="chrome110")
        if proxies:
            self.session.proxies = proxies
        self.username = "Unknown"
        self.balance = "未知"
        self.csrf_token = ""
        self._parse_cookies()

    # -- Cookie -------------------------------------------------------------

    def _parse_cookies(self):
        if not self.cookie_str:
            return
        cookies = {}
        for item in self.cookie_str.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v
        self.session.cookies.update(cookies)

    def _cookie_string(self):
        return "; ".join(f"{n}={v}" for n, v in self.session.cookies.items())

    # -- CSRF ---------------------------------------------------------------

    def _csrf(self, html=None, url=None):
        try:
            if html is None and url:
                html = self.session.get(url, timeout=20).text
            if not html:
                return self.csrf_token
            soup = BeautifulSoup(html, "html.parser")
            m = soup.find("meta", attrs={"name": "csrf-token"})
            if m:
                self.csrf_token = m.get("content")
                return self.csrf_token
            i = soup.find("input", attrs={"name": "_token"})
            if i:
                self.csrf_token = i.get("value")
        except Exception as e:
            logger.error(f"CSRF 获取失败: {e}")
        return self.csrf_token

    # -- Login (API → HTML) ------------------------------------------------

    def check_login(self):
        try:
            resp = self.session.get(f"{self.BASE_URL}/api/user", timeout=20)
            if resp.status_code == 200:
                d = resp.json()
                if d.get("status") == "success" or "email" in d:
                    self.username = d.get("email") or d.get("name") or self.username
                    self.balance = str(d.get("balance", "未知"))
                    if "Account_" in str(self.username) or not self.username:
                        logger.info("[API] 未返回真实邮箱，回退 HTML...")
                        return self._login_html()
                    logger.info(f"✅ [{self.username}] 登录成功 | 余额: {self.balance}")
                    return True
        except Exception as e:
            logger.warning(f"API 登录异常: {e}，回退 HTML...")
        return self._login_html()

    def _login_html(self):
        try:
            resp = self.session.get(f"{self.BASE_URL}/dashboard",
                                    timeout=20, allow_redirects=True)
            if "/login" in resp.url:
                return False
            if resp.status_code != 200:
                return False
            self._csrf(html=resp.text)
            soup = BeautifulSoup(resp.text, "html.parser")
            tag = soup.select_one("p.font-light.text-gray-500")
            if not tag:
                tag = soup.find("p", string=re.compile(r".+@.+\..+"))
            if tag and "[email" not in tag.get_text():
                self.username = tag.get_text().strip()
            else:
                n = soup.select_one("h3 > a[href='#']")
                if n:
                    self.username = n.get_text().strip()
            bl = soup.select_one("a[href*='/balance']")
            if bl:
                bt = bl.find(["dt", "h4", "div"],
                             class_=re.compile(r"font-extrabold|text-3xl"))
                if bt:
                    self.balance = bt.get_text().strip()
            if self.balance == "未知":
                m = soup.find(string=re.compile(r"(￥|¥|余额)\s*\d+"))
                if m:
                    self.balance = m.strip()
            logger.info(f"✅ {self.username} 登录成功 (余额: {self.balance})")
            return True
        except Exception as e:
            logger.error(f"HTML 登录异常: {e}")
        return False

    # -- Service IDs (API → HTML) ------------------------------------------

    def get_service_ids(self):
        try:
            resp = self.session.get(f"{self.BASE_URL}/api/vps", timeout=20)
            if resp.status_code == 200:
                d = resp.json()
                svcs = d if isinstance(d, list) else d.get("data", [])
                ids = [str(s["id"]) for s in svcs if s.get("id")]
                if ids:
                    logger.info(f"API 获取到 {len(ids)} 个服务")
                    return ids
        except Exception as e:
            logger.warning(f"API 服务列表失败: {e}，回退 HTML...")
        try:
            resp = self.session.get(f"{self.BASE_URL}/dashboard", timeout=20)
            ids = list(set(re.findall(r"service/(\d+)/manage", resp.text)))
            if ids:
                logger.info(f"HTML 获取到 {len(ids)} 个服务")
            return ids
        except Exception as e:
            logger.error(f"HTML 服务列表失败: {e}")
            return []

    # -- Renew (API → HTML) ------------------------------------------------

    def renew_service(self, sid):
        try:
            res = self.session.post(f"{self.BASE_URL}/api/vps/renew",
                                    json={"id": int(sid), "days": 7}, timeout=20)
            if res.status_code == 200:
                d = res.json()
                msg = d.get("message", "请求完成")
                if "success" in d.get("status", "").lower() or d.get("code") == 200:
                    return True, "自动续期成功 (7天)"
                return True, f"完成: {msg}"
            if res.status_code == 400:
                try:
                    msg = res.json().get("message", "未到续期时间")
                except Exception:
                    msg = "未到续期时间"
                return True, f"状态正常 ({msg})"
        except Exception as e:
            logger.warning(f"API 续期异常: {e}，回退 HTML...")
        return self._renew_html(sid)

    def _renew_html(self, sid):
        url = f"{self.BASE_URL}/service/{sid}/manage"
        try:
            resp = self.session.get(url, timeout=20)
            token = self._csrf(html=resp.text)
            if not token:
                return False, "获取 Token 失败"
            headers = {"Referer": url, "Origin": self.BASE_URL, "X-CSRF-TOKEN": token}
            xsrf = self.session.cookies.get("XSRF-TOKEN")
            if xsrf:
                from urllib.parse import unquote
                headers["X-XSRF-TOKEN"] = unquote(xsrf)
            resp = self.session.post(
                f"{self.BASE_URL}/service/{sid}/renew",
                data={"_token": token, "days": "7"}, headers=headers, timeout=20
            )
            if "invoice" in resp.url or "payment" in resp.url:
                return True, "申请成功"
            soup = BeautifulSoup(resp.text, "html.parser")
            alert = soup.find(["div", "span"], attrs={"role": "alert"})
            if alert:
                t = alert.get_text(strip=True)
                if "only renew" in t or "expires in" in t:
                    m = re.search(r"expires in (\d+) days", t)
                    extra = f" (剩余 {m.group(1)} 天)" if m else ""
                    return True, f"未到期{extra}"
                return False, f"申请失败: {t}"
            if resp.status_code == 200 and "/service" in resp.url:
                return True, "状态正常"
            return False, f"续期失败: {resp.status_code}"
        except Exception as e:
            return False, f"续期异常: {e}"

    # -- Pay invoices (API → HTML) -----------------------------------------

    def pay_unpaid_invoices(self, sid=None):
        try:
            resp = self.session.get(f"{self.BASE_URL}/api/invoices", timeout=20)
            if resp.status_code == 200:
                d = resp.json()
                invs = d if isinstance(d, list) else d.get("data", [])
                unpaid = [i for i in invs
                          if str(i.get("status")).lower()
                          in ("unpaid", "pending", "0", "未支付", "待支付")]
                if not unpaid:
                    return True, "暂无待支付订单"
                ok = 0
                for inv in unpaid:
                    r = self.session.post(f"{self.BASE_URL}/api/invoice/pay",
                                          json={"id": inv.get("id")}, timeout=20)
                    if r.status_code == 200 and "success" in r.text.lower():
                        ok += 1
                return True, f"自动扣费完成 ({ok}/{len(unpaid)} 成功)"
        except Exception as e:
            logger.warning(f"API 扣费异常: {e}，回退 HTML...")
        if sid:
            return self._pay_html(sid)
        return True, "暂无账单"

    def _pay_html(self, sid):
        url = f"{self.BASE_URL}/service/{sid}/invoices?where=unpaid"
        try:
            resp = self.session.get(url, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/invoice/" in href and "download" not in href:
                    p = a.find_parent(["tr", "div", "li"])
                    if p and any(kw in p.get_text()
                                 for kw in ["Unpaid", "待支付", "未支付", "Invoice"]):
                        links.append(href)
            if not links:
                return True, "无待支付订单"
            links = list(set(links))
            ok = 0
            for lk in links:
                full = lk if lk.startswith("http") else self.BASE_URL + lk
                ir = self.session.get(full, timeout=20)
                isoup = BeautifulSoup(ir.text, "html.parser")
                form = None
                for f in isoup.find_all("form"):
                    act = f.get("action", "")
                    if "balance/add" in act:
                        continue
                    btn = (f.find(["button", "input"], attrs={"type": "submit"})
                           or f.find("button"))
                    if btn and any(kw in btn.get_text()
                                   for kw in ["支付", "Pay", "确认"]):
                        form = f
                        break
                if not form:
                    for f in isoup.find_all("form"):
                        act = f.get("action", "")
                        if "invoice" in act or "payment" in act:
                            form = f
                            break
                if form:
                    action = form.get("action", "")
                    if not action.startswith("http"):
                        action = self.BASE_URL + action
                    payload = {inp.get("name"): inp.get("value", "")
                               for inp in form.find_all("input") if inp.get("name")}
                    token = self._csrf(html=ir.text)
                    if token:
                        payload["_token"] = token
                    pr = self.session.post(action, data=payload,
                                           headers={"Referer": full,
                                                    "X-CSRF-TOKEN": token or self.csrf_token},
                                           timeout=20)
                    if any(kw in pr.text for kw in ["成功", "Success"]) or pr.status_code == 200:
                        ok += 1
            return True, f"支付完成 ({ok}/{len(links)} 成功)"
        except Exception as e:
            return False, f"支付异常: {e}"

    # -- TG notification ----------------------------------------------------

    @staticmethod
    def _hitokoto():
        try:
            r = requests.get("https://v1.hitokoto.cn/?encode=json", timeout=10)
            if r.status_code == 200:
                d = r.json()
                return f"「{d['hitokoto']}」—— {d['from']}"
        except Exception:
            pass
        return "保持热爱，奔赴山海。"

    def send_tg(self, message):
        if not self.tg_config or not self.tg_config.get("bot_token"):
            return
        h = self._hitokoto()
        text = (
            f"☁️ **HidenCloud 自动续费任务**\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 **账号**: `{self.username}`\n"
            f"💰 **余额**: `{self.balance}`\n"
            f"🕐 **时间**: `{time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{message}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💕 **每日一言**:\n_{h}_"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.tg_config['bot_token']}/sendMessage",
                json={"chat_id": self.tg_config["chat_id"],
                      "text": text, "parse_mode": "Markdown"},
                timeout=10
            )
        except Exception as e:
            logger.error(f"TG 通知异常: {e}")

    # -- GitHub Secret update -----------------------------------------------

    def update_github_secret(self, new_cookie):
        gh_pat = os.environ.get("GH_PAT")
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not gh_pat or not repo or not HAS_NACL:
            return
        logger.info("正在更新 GitHub Secret: HIDEN_COOKIE")
        hdr = {"Authorization": f"token {gh_pat}",
               "Accept": "application/vnd.github.v3+json",
               "User-Agent": "HidenCloud-Bot"}
        try:
            pk = requests.get(
                f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
                headers=hdr, timeout=15
            )
            if pk.status_code != 200:
                logger.error(f"获取公钥失败: {pk.text}")
                return
            pkd = pk.json()

            def encrypt(pub_key_str, val):
                p = public.PublicKey(pub_key_str.encode(), encoding.Base64Encoder())
                return base64.b64encode(public.SealedBox(p).encrypt(val.encode())).decode()

            ev = encrypt(pkd["key"], new_cookie)
            r = requests.put(
                f"https://api.github.com/repos/{repo}/actions/secrets/HIDEN_COOKIE",
                headers=hdr,
                json={"encrypted_value": ev, "key_id": pkd["key_id"]},
                timeout=15
            )
            if r.status_code in (201, 204):
                logger.info("✅ GitHub Secret 更新成功")
            else:
                logger.error(f"❌ Secret 更新失败: {r.text}")
        except Exception as e:
            logger.error(f"Secret 更新出错: {e}")

    def _update_local_config(self, new_cookie):
        cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        if not os.path.exists(cp):
            return
        try:
            with open(cp, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for acc in cfg.get("accounts", []):
                if acc.get("cookie_str") == self.cookie_str or len(cfg.get("accounts", [])) == 1:
                    acc["cookie_str"] = new_cookie
                    break
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            logger.info("✅ 本地 config.json 已同步")
        except Exception as e:
            logger.error(f"本地配置更新失败: {e}")

    # -- Main task ----------------------------------------------------------

    def run_task(self):
        if not self.check_login():
            logger.error("❌ Cookie 已失效")
            self.send_tg("❌ Cookie 已失效，请重新提取并更新 Secrets")
            return

        logger.info(f"账号 {self.username} 验证通过，开始任务...")
        ids = self.get_service_ids()
        if not ids:
            logger.warning("未找到活跃服务")
            return

        results, ok_n, fail_n = [], 0, 0
        for sid in ids:
            r_ok, r_msg = self.renew_service(sid)
            p_ok, p_msg = self.pay_unpaid_invoices(sid)
            icon = "✅" if r_ok and p_ok else "❌"
            results.append(f"{icon} **服务 {sid}**\n   ┣ 续期: `{r_msg}`\n   ┗ 支付: `{p_msg}`")
            ok_n += 1 if r_ok and p_ok else 0
            fail_n += 0 if r_ok and p_ok else 1

        report = f"📊 **统计**: 成功 `{ok_n}` | 失败 `{fail_n}`\n\n" + "\n".join(results)
        logger.info(f"任务完成:\n{report}")
        self.send_tg(report)

        new_cookie = self._cookie_string()
        if new_cookie != self.cookie_str:
            logger.info("Cookie 已刷新，同步更新...")
            self.update_github_secret(new_cookie)
            self._update_local_config(new_cookie)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    env_cookies = os.environ.get("HIDEN_COOKIE")
    config_cookies = []
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    config = {}

    if env_cookies:
        logger.info("从环境变量 HIDEN_COOKIE 加载账号")
        config_cookies = re.split(r"[&\n]", env_cookies)
    elif os.path.exists(config_path):
        logger.info("从本地 config.json 加载账号")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            for acc in config.get("accounts", []):
                cs = acc.get("cookie_str")
                if not cs and acc.get("cookies"):
                    cs = ("; ".join(f"{k}={v}" for k, v in acc["cookies"].items())
                          if isinstance(acc["cookies"], dict) else str(acc["cookies"]))
                if cs:
                    config_cookies.append(cs)
        except Exception as e:
            logger.error(f"读取 config.json 失败: {e}")
            return
    else:
        logger.error("未找到 HIDEN_COOKIE 环境变量或 config.json")
        return

    tg_config = {
        "bot_token": os.environ.get("TG_BOT_TOKEN") or config.get("telegram", {}).get("bot_token"),
        "chat_id": os.environ.get("TG_CHAT_ID") or config.get("telegram", {}).get("chat_id")
    }

    # 代理：由 YML 中的 "安装并启动代理" step 写入 PROXY_SERVER 环境变量
    proxy_server = os.environ.get("PROXY_SERVER", "")
    proxies = None
    if proxy_server:
        logger.info(f"检测到代理: {proxy_server}")
        proxies = {"http": proxy_server, "https": proxy_server}

    # ======== 🕵️ 代理质量与脚本隔离测试 ========
        logger.info("====== 🕵️ 开始执行代理质量排查 ======")
        try:
            # 1. 测试常规国际公网是否畅通
            test_pub = requests.get("https://cp.cloudflare.com/generate_204", proxies=proxies, timeout=10)
            logger.info(f"🟢 [基础网络] 节点本身正常，可连接外网 (状态码: {test_pub.status_code})")
            
            # 2. 测试目标网站 HidenCloud 是否对该节点阻断
            test_target = requests.get("https://dash.hidencloud.com/dashboard", proxies=proxies, timeout=15, impersonate="chrome110")
            logger.info(f"🟢 [目标面板] 节点成功握手 HidenCloud 官网 (状态码: {test_target.status_code})")
            logger.info("👉 结论：节点完美通行！若后续报错，则是 Cookie、解析或业务逻辑问题。")
        except Exception as e:
            logger.error(f"🔴 [测试失败] 代理请求出现异常。详细错误: {e}")
            if "timeout" in str(e).lower() or "28" in str(e):
                logger.info("👉 结论：节点 IP 极大概率已被 HidenCloud 防御系统/Cloudflare 彻底拉黑（流量被丢弃）。请更换 PROXY_NODE！")
            else:
                logger.info("👉 结论：Xray 代理隧道可能未成功建立，请检查 YML 中的节点参数（Path/UUID/TLS）是否正确。")
        logger.info("====================================")
        # ==========================================

    # 并发执行
    with ThreadPoolExecutor(max_workers=min(len(config_cookies), 5)) as pool:
        futs = {}
        for cs in config_cookies:
            cs = cs.strip()
            if not cs:
                continue
            bot = HidenCloud(cs, tg_config, proxies)
            futs[pool.submit(bot.run_task)] = bot.username
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:
                logger.error(f"账号 {futs[f]} 异常: {e}")


if __name__ == "__main__":
    main()
