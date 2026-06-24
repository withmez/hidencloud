import os
import sys
import re
import time
import requests
from curl_cffi import requests as json_requests

# 格式化账号显示
def mask_cookie(cookie_str):
    match = re.search(r'hidencloud_session=([^;]+)', cookie_str)
    if match:
        return f"Account_Session({match.group(1)[:8]}***)"
    return "Unknown_Account"

# 获取每日一言
def get_hitokoto():
    try:
        res = requests.get("https://v1.hitokoto.cn/?c=i", timeout=5).json()
        return f"「{res['hitokoto']}」 —— {res['from']}"
    except:
        return "保持热爱，奔赴山海。"

# TG 推送
def send_tg(token, chat_id, message):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[WARN] TG 推送失败: {e}")

# 核心执行逻辑
def process_renew(cookie, proxy_dict):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    account_name = mask_cookie(cookie)
    log_content = f"👤 账号: `{account_name}`\n"
    
    try:
        # 使用 impersonate="chrome120" 完美过 CF 验证
        session = json_requests.Session()
        if proxy_dict:
            session.proxies = proxy_dict

        # 1. 获取账户信息与余额
        dash_res = session.get("https://dash.hidencloud.com/api/user", headers=headers, impersonate="chrome120", timeout=15)
        if dash_res.status_code != 200:
            return f"❌ 账号 `{account_name}`: Cookie 已失效或遭遇阻断（状态码 {dash_res.status_code}）\n"
        
        user_data = dash_res.json()
        balance = user_data.get("balance", "未知")
        log_content += f"💰 账户余额: `{balance}` 元\n"

        # 2. 执行续期操作 (调用续期 API，默认续期 7 天)
        renew_res = session.post("https://dash.hidencloud.com/api/vps/renew", headers=headers, impersonate="chrome120", timeout=15)
        renew_data = renew_res.json()
        
        if renew_data.get("success") or "成功" in renew_data.get("message", ""):
            log_content += f"🔄 续期结果: `自动续期成功 (7天)`\n"
        else:
            log_content += f"🔄 续期结果: `未触发续期 ({renew_data.get('message', '未到续期时间')})`\n"

        # 3. 自动扣费（检测未支付订单并用余额支付）
        invoice_res = session.get("https://dash.hidencloud.com/api/invoices?status=unpaid", headers=headers, impersonate="chrome120", timeout=15)
        invoices = invoice_res.json().get("data", [])
        
        if invoices:
            log_content += f"🧾 检测到有 `{len(invoices)}` 个未支付订单，尝试自动扣费...\n"
            for inv in invoices:
                inv_id = inv.get("id")
                pay_res = session.post(f"https://dash.hidencloud.com/api/invoices/{inv_id}/pay", json={"method": "balance"}, headers=headers, impersonate="chrome120", timeout=15)
                pay_data = pay_res.json()
                if pay_data.get("success"):
                    log_content += f"  ✅ 订单 `#{inv_id}` 余额扣费成功！\n"
                else:
                    log_content += f"  ❌ 订单 `#{inv_id}` 扣费失败: `{pay_data.get('message', '余额不足')}`\n"
        else:
            log_content += f"🧾 扣费检测: `暂无未支付订单`\n"

    except Exception as e:
        log_content += f"💥 运行异常: `{str(e)[:50]}`\n"
    
    return log_content + "\n"

def main():
    raw_cookies = os.environ.get("HIDEN_COOKIE", "").strip()
    tg_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    proxy_server = os.environ.get("PROXY_SERVER", "").strip()

    if not raw_cookies:
        print("[ERROR] 未配置 HIDEN_COOKIE")
        sys.exit(1)

    # 解析多账号 (支持 & 或 换行符 分割)
    cookie_list = [c.strip() for c in re.split(r'[&\n]', raw_cookies) if c.strip()]
    print(f"[INFO] 成功载入 {len(cookie_list)} 个账号")

    # 配置代理 (修复了语法错误)
    proxy_dict = {}
    if proxy_server:
        proxy_dict = {
            "http": f"socks5://{proxy_server}",
            "https": f"socks5://{proxy_server}"
        }

    final_report = "📢 **HidenCloud 自动续费运行报告**\n\n"
    for idx, cookie in enumerate(cookie_list, 1):
        print(f"[INFO] 正在处理第 {idx}/{len(cookie_list)} 个账号...")
        final_report += process_renew(cookie, proxy_dict)
    
    # 附带每日一言
    final_report += f"--- \n🍃 {get_hitokoto()}"
    
    print(final_report)
    send_tg(tg_token, tg_chat_id, final_report)

if __name__ == "__main__":
    main()
