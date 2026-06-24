import os
import sys
import re
import time
import pickle
import datetime
import requests
from seleniumbase import Driver

def mask_email(email):
    if "-----" in email:
        email = email.split("-----")[0]
    if "@" in email:
        name, domain = email.split("@", 1)
        return f"{name[:2]}***@{domain}"
    return "***"

def send_telegram_notification(token, chat_id, message, screenshot_path=None):
    if not token or not chat_id:
        print("[INFO] 未配置 Telegram Token 或 Chat ID，放弃推送。")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        if screenshot_path and os.path.exists(screenshot_path):
            photo_url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(screenshot_path, 'rb') as f:
                requests.post(photo_url, data={"chat_id": chat_id}, files={"photo": f}, timeout=15)
        print("[INFO] Telegram 结果状态推送完成。")
    except Exception as e:
        print(f"[WARN] Telegram 推送失败: {e}")

def update_github_cron(days_remaining):
    """
    智能分析计算剩余到期天数，提早 20 小时修改工作流 yml
    """
    if days_remaining <= 0:
        print("[WARN] 无法计算非法剩余天数，放弃时间重写。")
        return
        
    now = datetime.datetime.utcnow()
    # 提前 20 小时运行
    target_time = now + datetime.timedelta(days=days_remaining) - datetime.timedelta(hours=20)
    
    # 转换为标准的 Cron 表达式（分钟 小时 日 月 *）
    new_cron = f"{target_time.minute} {target_time.hour} {target_time.day} {target_time.month} *"
    print(f"[INFO] 智能计算下次执行 UTC 时间为: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 生成的目标 Cron 表达式: '{new_cron}'")
    
    yml_path = ".github/workflows/HidenCloud_Renew.yml"
    if os.path.exists(yml_path):
        with open(yml_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 匹配替换最顶部的 schedule cron 规则
        updated_content = re.sub(r"- cron:\s*'[^']+'", f"- cron: '{new_cron}'", content, count=1)
        
        with open(yml_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print("[INFO] 成功在本地修改工作流 Cron 表达式")
    else:
        print("[WARN] 未找到工作流文件，本地跳过修改")

def main():
    account_info = os.environ.get("HIDENCLOUD", "").strip()
    tg_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    proxy_server = os.environ.get("PROXY_SERVER", "").strip()
    proxy_port = os.environ.get("PROXY_SOCKS5_PORT", "").strip()

    if "-----" not in account_info:
        print("[ERROR] 账号凭证格式有误，请使用 '邮箱-----密码' 格式配置")
        sys.exit(1)

    email, password = account_info.split("-----", 1)
    masked = mask_email(email)
    print(f"[INFO] 🚀 启动 HidenCloud 服务器自动化续期。账号: {masked}")

    # 初始化配置高级防检测指纹浏览器环境
    driver_kwargs = {
        "browser": "chrome",
        "headless": True,
        "uc": True, # 启用高级 UC 模式过人机校验验证
        "incognito": False
    }

    if proxy_server:
        print(f"[INFO] 正在为本地安全浏览器挂载内部代理环境: socks5://{proxy_server}")
        driver_kwargs["proxy"] = f"127.0.0.1:{proxy_port}"

    driver = Driver(**driver_kwargs)
    driver.set_window_size(1366, 768)

    cookie_file = "saved_cookies.pkl"
    login_success = False

    try:
        # 1. 尝试导入持久化缓存会话加速
        driver.get("https://dash.hidencloud.com/login")
        time.sleep(3)

        if os.path.exists(cookie_file):
            print("[INFO] 检测到本地持久化缓存会话记录，正在注入...")
            with open(cookie_file, "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    try:
                        driver.add_cookie(cookie)
                    except Exception:
                        pass
            driver.refresh()
            time.sleep(4)

        # 判断是否跳过登录直接成功进入主页
        if "login" not in driver.current_url.lower():
            print("[INFO] 🎉 会话有效，已自动登录到控制台主页")
            login_success = True
        else:
            print("[INFO] 缓存已失效或首次登录，正在输入凭证账密...")
            driver.type('input[type="email"]', email)
            driver.type('input[type="password"]', password)
            
            # 点击登录，并给 Cloudflare Turnstile 预留充裕的安全滑动解析时间
            driver.click('button[type="submit"]')
            print("[INFO] 等待人机接口验证处理响应...")
            time.sleep(12)
            
            if "login" not in driver.current_url.lower():
                print("[INFO] 🎉 账密硬登录鉴权成功。")
                login_success = True
                # 导出保存状态供下次复用
                with open(cookie_file, "wb") as f:
                    pickle.dump(driver.get_cookies(), f)
            else:
                print("[ERROR] 登录遭遇 Cloudflare 阻断或凭证失效。")
                driver.save_screenshot("login_failed.png")
                send_telegram_notification(tg_token, tg_chat_id, f"❌ 账号 `{masked}` 登录失败，被人机验证拦截。", "login_failed.png")
                sys.exit(1)

        # 2. 前往服务器管理模块并进行续期检测
        if login_success:
            driver.get("https://dash.hidencloud.com/vps")
            time.sleep(6)
            
            # 使用 BeautifulSoup 解析抓取具体的到期指标
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(driver.page_source, "html.parser")
            
            # 兼容寻找页面上指示天数的关键标识文本 (示例: "6 days remaining" 或 "Expires in 5 days")
            days_text = soup.find(text=re.compile(r"(\d+)\s*days?\s*(remaining|expires)", re.I))
            
            days_remaining = 7 # 默认安全轮询天数
            if days_text:
                match = re.search(r"(\d+)", days_text)
                if match:
                    days_remaining = int(match.group(1))
                    print(f"[INFO] 智能识别当前的服务器剩余健康天数: {days_remaining} 天")

            # 3. 寻找并执行续期按钮点击
            renew_buttons = [btn for btn in driver.find_elements("button") if "renew" in btn.text.lower() or "续期" in btn.text]
            
            if renew_buttons:
                renew_buttons[0].click()
                print("[INFO] 发送续期指令...")
                time.sleep(5)
                
                driver.save_screenshot("renew_result.png")
                success_msg = f"✅ 账号 `{masked}` 续期任务触发成功！\n📊 运行前识别剩余: `{days_remaining}` 天。"
                print(f"[INFO] {success_msg}")
                
                send_telegram_notification(tg_token, tg_chat_id, success_msg, "renew_result.png")
                
                # 4. 精准计算出下次最优运行时间，动态控制重写 yml 表达式
                update_github_cron(days_remaining)
            else:
                print("[WARN] 页面未检索到续期触发按钮，可能还未到可以续期的指定时限。")
                driver.save_screenshot("no_button.png")
                send_telegram_notification(tg_token, tg_chat_id, f"⚠️ 账号 `{masked}` 暂无可操作的续期按钮（未到期）。", "no_button.png")
                update_github_cron(days_remaining)

    except Exception as e:
        print(f"[ERROR] 自动化引擎崩溃: {e}")
        try:
            driver.save_screenshot("exception.png")
            send_telegram_notification(tg_token, tg_chat_id, f"💥 账号 `{masked}` 运行时发生致命异常: {str(e)[:100]}", "exception.png")
        except:
            pass
        sys.exit(1)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
