def check_login_api(self):
        """优化版：API 结合 HTML 混合嗅探，确保完美提取真实邮箱账号"""
        try:
            resp = self.session.get(f"{self.base_url}/api/user", timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success" or "email" in data:
                    self.username = data.get("email") or data.get("name") or self.username
                    self.balance = str(data.get("balance", "未知"))
                    
                    # 如果 API 返回的是默认的 Account_1 或空值，自动回退到 HTML 嗅探真实邮箱
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
        """采用 API 获取用户持有的 VPS 服务列表"""
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
        """采用高效的 API 进行续费提交通道"""
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
        """采用 API 完成一键自动对未付账单进行扣款扣费"""
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
