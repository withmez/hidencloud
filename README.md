# HidenCloud 自动续费

<p align="left">
  <img src="https://img.shields.io/github/stars/SunshineList/hidencloud_renew?style=flat-square&logo=github" alt="GitHub stars">
  <img src="https://img.shields.io/github/forks/SunshineList/hidencloud_renew?style=flat-square&logo=github" alt="GitHub forks">
  <img src="https://img.shields.io/github/actions/workflow/status/SunshineList/hidencloud_renew/hidencloud_renew.yml?style=flat-square&logo=github-actions" alt="GitHub workflow status">
  <img src="https://img.shields.io/github/license/SunshineList/hidencloud_renew?style=flat-square" alt="GitHub license">
</p>

HidenCloud 自动续费脚本，支持多账号并发、Telegram 通知及 Cookie 自动更新持久化。

针对部分网络环境受限、无法正常访问目标网站的问题，本项目**内置了全协议代理分流网络功能**。脚本在运行时会自动下载 Xray 核心并搭建本地轻量代理，无需额外安装任何 Actions 插件。

## 💡 核心功能

- **自动续期**：默认自动续期 7 天。
- **自动扣费**：智能检测账户下未支付的订单，并自动使用账户余额完成支付。
- **TG 推送**：集成 Telegram Bot 消息推送，通知内容包含：账号信息、账户余额、执行结果及每日一言。
- **自动持久化**：配合 GitHub PAT（个人访问令牌），脚本可自动回写更新后的 Cookie 到 Repository Secrets 中，免去频繁手动更新的烦恼。
- **内置原生代理**：集成 Xray 核心，完美支持 `Vless` / `Vmess` / `Trojan` / `Shadowsocks` / `Socks5` 等主流节点链接的自动解析与本地分流环境搭建。

---

## 🛠️ 快速配置 (GitHub Actions)

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
| **`GH_PAT`** | ❌ 选填 | 个人访问令牌，[在此生成](https://github.com/settings/tokens)（须勾选 `repo` 权限）。用于实现 Cookie 自动回写更新。 |
| **`PROXY_NODE`** | ❌ 选填 | 网络代理节点链接，用于在受限网络环境下提供网络代理分流。 |

#### 🔗 支持的代理节点格式
> 💡 *提示：建议优先使用注册该 HidenCloud 账号时所用的代理节点，并在配置前先在本地客户端测试是否可以正常登录官网。*

- **VLESS**：`vless://...` (支持 Reality、TLS、WS、gRPC 等主流格式)
- **VMess**：`vmess://...` (标准的 Base64 编码格式链接)
- **Trojan**：`trojan://...`
- **Shadowsocks**：`ss://...`
- **SOCKS5 / SOCKS**：`socks5://...` 或 `socks://...`

> ⚠️ **注意**：若未配置 `PROXY_NODE` 变量，脚本在运行时将默认采用**直连模式**，不会下载和启动后台 Xray 核心。

---

## 💻 本地运行

如果你希望先在本地环境中进行测试，请按照以下步骤操作：

1. **安装依赖库**：
   ```bash
   pip install curl_cffi beautifulsoup4 pynacl

   ```

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

- **Cookie 自动更新不生效？**

  检查 `GH_PAT` 是否配置正确且具备 `repo` 权限。
  
- **配置了 PROXY_NODE 节点却连不上？**
  
  工作流在启动 Xray 后会自动对 https://api.ipify.org 发起 5 次连接测试，若提示连接失败，请检查你的节点链接是否能够正常握手，或更换其他节点尝试。
  

