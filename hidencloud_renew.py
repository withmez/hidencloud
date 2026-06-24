def main():
    config = {}
    env_cookies = os.environ.get("HIDEN_COOKIE")
    proxy_url = os.environ.get("PROXY_URL") # 👈 新增：自动捕获来自上方 Xray 写入的环境变量
    
    config_cookies = []
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "config.json")
    
    if env_cookies:
        logger.info("从环境变量 HIDEN_COOKIE 加载账号信息")
        account_cookies = re.split(r'[&\n]', env_cookies)
    elif os.path.exists(config_path):
        logger.info("从本地 config.json 加载账号信息")
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                accounts = config.get("accounts", [])
                account_cookies = []
                for acc in accounts:
                    if acc.get("cookie_str"):
                        account_cookies.append(acc.get("cookie_str"))
                    elif acc.get("cookies"):
                        if isinstance(acc["cookies"], dict):
                            c_str = "; ".join([f"{k}={v}" for k, v in acc["cookies"].items()])
                        else:
                            c_str = str(acc["cookies"])
                        account_cookies.append(c_str)
                # 兼容本地 config.json 的代理
                if not proxy_url:
                    proxy_url = config.get("proxy_url")
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

    # 循环运行账号任务
    for cookie_str in account_cookies:
        if not cookie_str.strip(): continue
        try:
            # 👈 这里把刚才解析出的 proxy_url 传入 HidenCloud 类中
            bot = HidenCloud(cookie_str, tg_config, proxy_url=proxy_url)
            bot.run_task()
        except Exception as e:
            logger.error(f"处理账号时发生异常: {e}")
