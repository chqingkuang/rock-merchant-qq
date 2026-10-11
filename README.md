# 洛克王国：世界远行商人 QQ 提醒

自动查询远行商人当前轮次商品、价格和限购数量，用 `★` 标出稀有或高价值商品，通过使用者自己的 QQ 发送提醒。

作者：十七。版本：1.0.1。MIT 许可。

[独立源码仓库](https://github.com/chqingkuang/rock-merchant-qq) · [博客图文教程](https://chqingkuang.github.io/2026/10/11/远行商人QQ提醒工具：Windows和Linux使用说明/)

## 下载

[GitHub 下载页](https://github.com/chqingkuang/rock-merchant-qq/releases/tag/rock-merchant-qq-v1.0.1)

| 文件 | 用途 |
| --- | --- |
| `RockMerchantQQ-v1.0.1-windows-x64.zip` | Windows 10/11 64位，图形界面，无需 Python |
| `RockMerchantQQ-v1.0.1-linux-x86_64.zip` | Linux x86_64，命令行，无需 Python；在 Ubuntu 22.04 构建，要求 glibc 2.35 或以上 |
| `RockMerchantQQ-v1.0.1-source.zip` | 完整源码，运行要求 Python 3.10 或以上 |
| `SHA256SUMS.txt` | 下载文件的 SHA256 校验值 |

Linux 包不适用于 ARM、Alpine/musl 或较老的 glibc。其他架构可以使用源码；源码自身不依赖第三方 Python 包。

## 先登录自己的 QQ

QQ 登录由 NapCat 完成。本工具不收集 QQ 密码，不代替扫码验证，也不包含作者的登录状态、Token 或接收名单。

1. 按 [NapCat 官方安装说明](https://napneko.github.io/guide/boot/Shell) 在电脑上安装并启动 NapCat，用手机 QQ 扫 NapCat 显示的二维码登录。接收账号可以是主 QQ；群推送要求机器人已加入目标群。
2. **扫码只完成 QQ 登录，还需要配置下面的 HTTP 服务。** 回到电脑的 NapCat 启动窗口，找到 `WebUI` / `WebUi User Panel Url` / `WebUI Local Panel Url` 那一行，复制完整网址到电脑浏览器。管理页面通常是 `http://127.0.0.1:6099/webui/`，实际地址、端口和管理密码以启动窗口为准；不要关闭 NapCat。
3. 登录管理页面。如果要求管理密码，使用启动窗口显示的 **WebUI Token**；按页面要求修改管理密码后进入面板。
4. 点击左侧 **网络配置 → 新建 → HTTP 服务端（HTTP 服务器）**。不要选择 HTTP 客户端或 WebSocket。填入：

   | NapCat 设置 | 填什么 |
   | --- | --- |
   | 名称（若需要） | `merchant-http`，只是便于识别 |
   | Host / 主机 | `127.0.0.1` |
   | Port / 端口 | `3000` |
   | Token / 访问令牌 | **自己设置一段随机字符**，并记下来 |
   | 启用 / 保存时启用 | 打开，保存 |

5. 回到远行商人提醒工具：**HTTP 接口地址填 `http://127.0.0.1:3000`；HTTP Token 填刚才第 4 步自己设置的那一段。** 不要填管理页面的 6099 地址，也不要复制 WebUI 的登录密码。
6. 填接收 QQ / 群号，点击“检查 QQ 登录”，再点击“发送测试”。正常后再开启自动提醒。

**为什么扫码后找不到 Token？** 提醒工具要用的 HTTP Token 由自己在“HTTP 服务端”里设置，不是扫码后手机给的一串号码。手机 QQ 里没有这个配置入口；如果只登录了普通 QQ，需要先在电脑上运行 NapCat，再打开它的管理页面。

以上地址适用于 NapCat 和提醒工具在同一台电脑运行、非 Docker 的情况。3000 被占用时换一个空闲端口，并同步修改工具的地址。跨电脑或 Docker 部署需要使用实际可访问的地址和映射端口，不能照抄 `127.0.0.1`。

两个 Token 用途不同：**WebUI Token 用来进入管理页面；HTTP Token 用来让提醒工具连接 QQ 接口。** 找不到管理入口或 WebUI Token 时，参照 [NapCat 官方 WebUI 配置指南](https://napneko.github.io/config/starter.shell)。

## Windows

1. 完整解压 Windows 包到固定的、有写入权限的文件夹。不要在压缩包内运行。
2. 双击 `RockMerchantQQ.exe`。
3. 若尚未登录 QQ，点击“NapCat 安装与登录说明”，或点击“打开 NapCat 登录自己的 QQ”选择安装目录里的启动文件。也可以直接使用 NapCat 自己的启动入口。
4. 填 HTTP 地址、HTTP Token，选择 QQ 私聊或 QQ 群，填写接收 QQ/群号。多个号码用逗号分隔。
5. 点击“检查 QQ 登录”，确认显示的是自己的机器人账号。
6. 点击“发送测试”，检查接收端是否收到中文消息。
7. 点击“开启自动提醒”。约一分钟后首次检查，以后每五分钟检查一次。

完成后可关闭本工具窗口。NapCat 仍需在线，Windows 用户需保持登录；电脑关机或休眠时不会检查。

关闭提醒：重新打开程序，点击“关闭自动提醒”。这只移除当前安装目录对应的任务，不删除配置或历史数据。

本工具不自动配置 NapCat 的开机登录。重启后需按 NapCat 的安装方式启动并确认 QQ 在线。移动整个程序目录前先关闭提醒，移动后重新开启。

## Linux

适用于安装了 systemd 的 Ubuntu 22.04/24.04 等 x86_64 系统。先完成上面的 NapCat 登录和 HTTP 服务配置。

解压后进入程序目录：

```sh
unzip RockMerchantQQ-v1.0.1-linux-x86_64.zip
cd RockMerchantQQ-v1.0.1
chmod +x RockMerchantQQ
./RockMerchantQQ --setup
```

按提示填写 HTTP 地址、Token、接收类型 `private` 或 `group`、接收号码。Token 输入时不会回显。

```sh
./RockMerchantQQ --check-login
./RockMerchantQQ --test-message
./RockMerchantQQ --preview
./RockMerchantQQ --enable-auto
./RockMerchantQQ --status
```

其中 `--test-message` 会向你配置的接收端发送一条测试消息；`--preview` 只显示商品，不发送。

自动提醒使用当前用户的 systemd timer，不需要用 root 运行。服务和计时器保存到 `~/.config/systemd/user/`，每次检查结束即退出。

需要退出终端或注销后继续运行时，可由系统管理员为该用户启用 lingering，例如 `loginctl enable-linger "$USER"`。NapCat 也要独立配置为持续运行。若 `systemctl --user` 提示无法连接总线，请先在正常的用户登录会话中操作。

关闭提醒：

```sh
./RockMerchantQQ --disable-auto
```

无 systemd 的环境也可以用自己已有的调度器每五分钟运行一次：

```sh
/完整路径/RockMerchantQQ --config /完整路径/config.json --once
```

程序不是常驻服务；不要同时启用多个调度器。迁移目录后应重新安装定时任务。

## 配置、日志和运行规则

- 首次保存后生成 `config.json`，位于程序旁；Linux 下该文件设置为仅当前用户读写。
- 运行日志：`logs/merchant_bot.log`；推送记录：`data/state.json`。
- 营业时段按北京时间：08:00、12:00、16:00、20:00 四轮；00:00-08:00 不发商品提醒。
- `★` 是数据源和本地规则判定的稀有/高价值商品，不是游戏官方稀有度评级。
- 默认低负载模式：同一天同一轮成功推送后，不再重复抓商品。这样不会自动发现该轮后续修正；取消低负载选项或把 `monitor.low_power_mode` 改为 `false` 可继续检查，重复内容仍会去重。
- 默认关闭好友自助订阅。该功能只适用于私聊推送；开启后，好友私聊发送“开启推送”，会在下一次检查时加入接收名单。
- 改接收名单不会清空本轮推送记录；用“发送测试”检查新号码，正式商品通常从下一轮开始接收。
- 分享给别人时使用原始下载包，不要把自己生成的 `config.json`、`data/`、`logs/` 或 NapCat 登录目录一起打包。

## 常见问题

**接口无法连接 / 401：** 检查 NapCat 是否在线，启用的是否为 HTTP 服务，地址、端口和 HTTP Token 是否一致。

**能检查登录，但收不到消息：** 检查接收 QQ/群号、机器人是否能向它发消息；先用测试消息确认通道。商品源尚未更新或处于非营业时段时，不会强行发空消息。

**Linux 提示 GLIBC 版本不足或不能执行：** 使用满足条件的 x86_64 系统，或者使用源码在本机运行/构建。先确认已经 `chmod +x`。

**Windows 无法创建任务：** 把程序放在自己有权限的目录，并在当前登录用户下运行；错误详情会显示在窗口中。

## 源码运行和构建

解压源码包，在源码目录执行：

```sh
python desktop_app.py
python -m unittest discover -s tests -v
```

Windows 默认打开窗口；Linux 默认显示命令帮助，可用 `python desktop_app.py --setup` 配置。

自行打包：

```sh
python -m pip install -r requirements-build.txt
python build_release.py
```

需在目标系统上构建，不能在 Windows 上直接生成 Linux 可执行文件。构建产物位于 `dist/`。GitHub Actions 同时构建 Windows 和 Linux 版本，并完成测试和打包后的自检。

## 来源

- [好游快爆每日远行商人查询页](https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/preview.php?id=1&immgj=0)
- [4399 远行商人查询工具](https://huodong2.4399.com/yxhtools/game-store)
- [NapCat 文档](https://napneko.github.io/)

第三方源站的数据和接口可能变化。本工具不会登录游戏账号，也不会修改游戏数据。
