# HidenCloud 自动续费

HidenCloud 自动续费脚本，基于 `curl_cffi` 完美绕过 Cloudflare 安全防护。支持多账号并发执行、未支付账单自动扣费、Telegram 综合报告推送以及自动清理历史运行记录。

针对部分网络环境受限、无法正常访问目标网站的问题，本项目**内置了全协议代理分流与清洗功能**。脚本在运行时会根据配置自动下载现代化 `sing-box` 通用核心并搭建本地轻量代理，无需额外安装任何 Actions 插件。

## 🎯 核心功能

- **多账号并发**：支持在配置中同时注入多个账号的 Cookie，流水线式依序触发，高效稳定。
- **免疫托盘（过 CF 盾）**：采用轻量级 `curl_cffi` 模拟真实浏览器指纹，免去粗糙的无头浏览器，完美绕过人机验证。
- **API 优先 + HTML 兜底**：所有操作（登录、获取服务、续期、扣费）均先走 API 通道，API 失败或返回不完整时自动回退 HTML 解析，双层保障。
- **自动续期**：自动请求官网续期接口（默认续期 7 天）。
- **智能自动扣费**：智能检测账户与所有处于 `unpaid`（未支付）状态的订单，并自动使用用户可用余额完成支付。
- **TG 推送 + 每日一言**：集成 Telegram Bot 消息推送，通知内容包含：账号脱敏标识、账户余额、续期结果、账单扣费状态及动态注入的每日一言。
- **历史记录自动清理**：工作流每次运行完毕后，会自动触发清理机制，**严格只保留最近 5 次的运行历史记录**，防止产生海量日志。
- **Cookie 自动刷新**：运行完毕后自动检测 Cookie 是否变化，如有变化自动同步更新 GitHub Secret 和本地 config.json。
- **通用原生代理清洗**：集成单一现代化 `sing-box` 核心，完美支持 `Vless` / `Vmess` / `Trojan` / `Shadowsocks` / `Hysteria2` (及简写 `hy2`) 等主流协议节点的自动参数清洗与本地高兼容分流环境。

---

## 🛠️ 快速配置（GitHub Actions）

### 1. 获取账号 Cookie

1. 使用浏览器登录 [HidenCloud 官网](https://hidencloud.com)。
2. 按 `F12` 打开开发者工具，并切换到 `Network` (网络) 标签页。
3. 刷新当前页面，在请求列表中点击任意一个请求，在右侧的 `Request Headers` (请求头) 中找到 `cookie` 字段。
4. 复制该字段对应的完整字符串（须包含 `hidencloud_session` 等关键信息）。

### 2. 配置仓库 Secrets

前往你的 GitHub 仓库，依次点击 `Settings` -> `Secrets and variables` -> `Actions`，点击 `New repository secret` 添加以下变量：

| Secret 名称 | 是否必填 | 说明 |
| :--- | :---: | :--- |
| **`HIDEN_COOKIE`** | ✅ 必填 | 步骤 1 中复制的 Cookie。如需运行多账号，账号之间使用 `&` 或 **换行符** 隔开。 |
| **`TG_BOT_TOKEN`** | ❌ 选填 | 联系 [@BotFather](https://t.me/BotFather) 创建机器人获取的 Token。 |
| **`TG_CHAT_ID`** | ❌ 选填 | 给 [@userinfobot](https://t.me/userinfobot) 发送消息获取的个人或频道 ID。 |
| **`GH_PAT`** | ❌ 选填 | 个人访问令牌，[在此生成](https://github.com/settings/tokens)。**必须勾选 `repo` 和 `workflow` 权限**。用于 Cookie 自动回写更新 Secret。 |
| **`PROXY_NODE`** | ❌ 选填 | 网络代理节点链接，用于在受限网络环境下提供网络代理分流。 |

#### 🔗 支持的代理节点格式

> 💡 *提示：建议优先使用注册该 HidenCloud 账号时所用的代理节点，并在配置前先在本地客户端测试是否可以正常登录官网。本项目已内置杂质参数剥离清洗，复制的节点含有额外扩展属性（如 `?ed=2560` 等）会自动切除以确保核心稳定运行。*

| 协议 | 链接格式 | 核心来源 |
| :--- | :--- | :--- |
| **VLESS** | `vless://...`（支持 Reality、TLS、WS 等主流格式） | [SagerNet/sing-box](https://github.com/SagerNet/sing-box) |
| **VMess** | `vmess://...`（标准的 Base64 编码格式链接） | [SagerNet/sing-box](https://github.com/SagerNet/sing-box) |
| **Trojan** | `trojan://...` | [SagerNet/sing-box](https://github.com/SagerNet/sing-box) |
| **Shadowsocks** | `ss://...` | [SagerNet/sing-box](https://github.com/SagerNet/sing-box) |
| **Hysteria 2** | `hy2://...` 或 `hysteria2://...` | [SagerNet/sing-box](https://github.com/SagerNet/sing-box) |
| **SOCKS5** | `socks5://...` 或 `socks://...` | 直连透传，无需核心 |

> ⚠️ **注意**：若未配置 `PROXY_NODE` 变量，脚本在运行时将默认采用**直连模式**，不会下载和启动后台代理核心。

### 3. 启用工作流

1. 确保仓库根目录下存在 `.github/workflows/hidencloud_renew.yml` 文件。
2. 工作流默认每天 UTC 04:00（北京时间 12:00）自动运行，也可在 Actions 页面手动触发。

---


## 💻 本地运行

如果你希望先在本地环境中进行测试，请按照以下步骤操作：

1. **安装依赖库**：
   ```bash
   pip install curl_cffi requests beautifulsoup4 pynacl

2. **配置信息：**
   ```bash
   修改项目目录下的 config.json 文件，填入你的账号 Cookie 及其他配置信息。

   ```

3. **执行脚本：**
   ```bash

   python hidencloud_renew.py

   ```

---



## 常见问题

- **为什么登录失败？**

  脚本目前不走账号密码登录（为了绕过 Cloudflare 验证码），只认 Cookie。如果提示失效，请按照上面的步骤重新抓取。

- **GitHub Actions 没跑？**

  确认 `.github/workflows` 文件夹在项目最根部，不要塞进子文件夹里。
  
- **配置了 PROXY_NODE 节点却连不上？**
  
  工作流在启动 sing-box 后会自动对 https://api.ipify.org 发起 5 次连接测试，若提示连接失败，请检查你的节点链接是否能够正常握手，或更换其他节点尝试。
  
- **API 请求返回默认账号名（Account_1）？**
  
  这是 HidenCloud 官方 API 的已知行为，脚本会自动检测并回退到 HTML 页面提取真实邮箱，无需手动干预。
  
- **支持 Hysteria2 协议吗？**
  
 支持。脚本统一支持 hy2:// 或 hysteria2:// 开头的节点链接。运行时会自动下载官方最新稳定版内核，并在本地开辟 1080 (SOCKS) 与 1081 (HTTP) 双重混合入站环境
  
