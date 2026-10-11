"""Portable Windows setup window and Linux command-line setup."""
from __future__ import annotations

import argparse
import contextlib
import copy
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import webbrowser

import rock_merchant_bot as bot

APP_DIR = bot.PROJECT_DIR
CONFIG_PATH = APP_DIR / "config.json"
NAPCAT_GUIDE = "https://napneko.github.io/guide/boot/Shell"
VERSION = "1.0.1"


def read_settings(config_path: Path = CONFIG_PATH) -> dict:
    template = APP_DIR / "config.example.json"
    return bot.load_config(config_path if config_path.exists() else template)


def make_settings(base: dict, url: str, token: str, recipients: str,
                  target_type: str, low_power: bool, subscribe: bool,
                  require_targets: bool = True) -> dict:
    from urllib.parse import urlparse
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("接口地址应填写完整的 http:// 或 https:// 地址。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请填写接口地址，并把访问令牌填入独立的 Token 栏。")
    targets = list(dict.fromkeys(x for x in re.split(r"[,，;；\s]+", recipients.strip()) if x))
    if any(not re.fullmatch(r"[1-9]\d{4,11}", x) for x in targets):
        raise ValueError("QQ 号或群号应为 5 至 12 位数字，多个号码用逗号分隔。")
    if require_targets and not targets:
        raise ValueError("请先填写接收消息的 QQ 号或群号。")
    if target_type not in ("private", "group"):
        raise ValueError("接收类型只能是 private 或 group。")
    if subscribe and target_type == "group":
        raise ValueError("好友订阅适用于 QQ 私聊推送；群推送时请取消订阅选项。")
    config = copy.deepcopy(base)
    config["qq"].update(enabled=True, base_url=url, access_token=token.strip(),
                        target_type=target_type, target_id="", target_ids=targets)
    config["monitor"]["low_power_mode"] = low_power
    config["subscription_commands"]["enabled"] = subscribe
    return config


def write_settings(config: dict, destination: Path = CONFIG_PATH) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    bot.save_config(destination, config)
    if os.name != "nt":
        destination.chmod(0o600)


def check_login(config: dict) -> str:
    result = bot.qq_request(config["qq"], "get_login_info")
    data = result.get("data") or {}
    if result.get("retcode") not in (None, 0, "0") or not data.get("user_id"):
        raise bot.BotError("未确认 QQ 登录，请检查 NapCat 在线状态、HTTP 地址和 Token。")
    return f"已连接 QQ：{data.get('nickname', '')}（{data['user_id']}）"


def task_name(app_dir: Path = APP_DIR) -> str:
    digest = hashlib.sha256(str(app_dir.resolve()).casefold().encode("utf-8")).hexdigest()[:12]
    return "RockMerchantQQ-" + digest


def systemd_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("运行路径不能包含换行。")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def linux_units(app_dir: Path, config_path: Path, executable: Path,
                script_path: Path | None = None) -> tuple[str, str]:
    working_directory = str(app_dir)
    if "\n" in working_directory or "\r" in working_directory:
        raise ValueError("运行路径不能包含换行。")
    command = [str(executable)]
    if script_path is not None:
        command.append(str(script_path))
    command.extend(["--config", str(config_path), "--once"])
    service = ("[Unit]\nDescription=Rock Kingdom merchant QQ reminder\n\n[Service]\n"
               "Type=oneshot\nWorkingDirectory=" + working_directory.replace("%", "%%") +
               "\nExecStart=" + " ".join(systemd_quote(x) for x in command) +
               "\nNice=10\nTimeoutStartSec=120\n")
    timer = ("[Unit]\nDescription=Check merchant every five minutes\n\n[Timer]\n"
             "OnStartupSec=1min\nOnUnitInactiveSec=5min\nAccuracySec=15s\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return service, timer


def manage_schedule(action: str, config_path: Path = CONFIG_PATH) -> str:
    if action not in ("Install", "Remove", "Status"):
        raise ValueError("Unknown schedule action")
    frozen = bool(getattr(sys, "frozen", False))
    script = None if frozen else Path(__file__).resolve()
    if os.name == "nt":
        args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(APP_DIR / "tasks.ps1"), "-Action", action,
                "-AppDir", str(APP_DIR), "-ConfigPath", str(config_path),
                "-Executable", sys.executable]
        if script:
            args.extend(["-ScriptPath", str(script)])
        result = subprocess.run(args, capture_output=True, encoding="utf-8",
                                errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=45)
    else:
        name = task_name()
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        if action == "Install":
            service, timer = linux_units(APP_DIR, config_path.resolve(), Path(sys.executable), script)
            unit_dir.mkdir(parents=True, exist_ok=True)
            (unit_dir / (name + ".service")).write_text(service, encoding="utf-8")
            (unit_dir / (name + ".timer")).write_text(timer, encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True,
                           capture_output=True, text=True, timeout=30)
            args = ["systemctl", "--user", "enable", "--now", name + ".timer"]
        elif action == "Remove":
            subprocess.run(["systemctl", "--user", "disable", "--now", name + ".timer"],
                           check=True, capture_output=True, text=True, timeout=30)
            subprocess.run(["systemctl", "--user", "stop", name + ".service"],
                           capture_output=True, text=True, timeout=30)
            for suffix in (".service", ".timer"):
                (unit_dir / (name + suffix)).unlink(missing_ok=True)
            args = ["systemctl", "--user", "daemon-reload"]
        else:
            args = ["systemctl", "--user", "list-timers", "--all", name + ".timer", "--no-pager"]
        result = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "定时任务操作失败。")
    return result.stdout.strip() or "操作完成。"


def terminal_setup(destination: Path) -> None:
    config = read_settings(destination)
    print("远行商人 QQ 提醒 v" + VERSION)
    print("先按 NapCat 官方说明登录自己的 QQ：" + NAPCAT_GUIDE)
    url = input("OneBot HTTP 地址 [http://127.0.0.1:3000]: ").strip() or "http://127.0.0.1:3000"
    token = getpass.getpass("OneBot HTTP Token（输入不回显）: ")
    kind = input("接收类型 private/group [private]: ").strip() or "private"
    recipients = input("接收 QQ 号/群号（多个用逗号分隔）: ")
    config = make_settings(config, url, token, recipients, kind, True, False)
    write_settings(config, destination)
    print("已保存：" + str(destination))
    print("下一步运行 --check-login，确认后运行 --test-message 和 --enable-auto。")


def desktop_window() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("远行商人 QQ 提醒 v" + VERSION)
    root.geometry("780x650")
    root.minsize(720, 600)
    try:
        base = read_settings()
    except Exception as exc:
        messagebox.showerror("无法读取配置", str(exc))
        root.destroy()
        return
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    ttk.Label(panel, text="远行商人 · 用自己的 QQ 接收提醒", font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    ttk.Label(panel, text="1. 在 NapCat 中登录 QQ   2. 填写接口和接收账号   3. 测试后开启自动提醒").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))
    ttk.Button(panel, text="NapCat 安装与登录说明", command=lambda: webbrowser.open(NAPCAT_GUIDE)).grid(row=2, column=0, sticky="w", pady=(0, 12))

    def open_napcat():
        selected = filedialog.askopenfilename(title="选择 NapCat 启动文件", filetypes=[("启动文件", "*.exe *.bat"), ("所有文件", "*.*")])
        if selected:
            try:
                os.startfile(selected)
            except OSError as exc:
                messagebox.showerror("启动失败", str(exc))

    ttk.Button(panel, text="打开 NapCat 登录自己的 QQ", command=open_napcat).grid(row=2, column=1, sticky="w", padx=8, pady=(0, 12))
    url = tk.StringVar(value=base["qq"]["base_url"])
    token = tk.StringVar(value=base["qq"].get("access_token", ""))
    recipients = tk.StringVar(value=", ".join(bot.qq_target_ids(base["qq"])))
    kind = tk.StringVar(value="QQ群" if base["qq"].get("target_type") == "group" else "QQ私聊")
    low_power = tk.BooleanVar(value=base["monitor"].get("low_power_mode", True))
    subscribe = tk.BooleanVar(value=base["subscription_commands"].get("enabled", False))
    for row, label, value, hidden in [(3, "HTTP 接口地址", url, False), (4, "HTTP Token", token, True), (6, "接收 QQ / 群号", recipients, False)]:
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=7)
        ttk.Entry(panel, textvariable=value, show="*" if hidden else "").grid(row=row, column=1, columnspan=2, sticky="ew", pady=7)
    ttk.Label(panel, text="接收方式").grid(row=5, column=0, sticky="w", pady=7)
    ttk.Combobox(panel, textvariable=kind, values=["QQ私聊", "QQ群"], state="readonly", width=16).grid(row=5, column=1, sticky="w")
    ttk.Label(panel, text="多个号码用逗号分隔。Token 填 NapCat 的 HTTP Token。", foreground="#666666").grid(row=7, column=1, columnspan=2, sticky="w")
    ttk.Checkbutton(panel, text="低负载：同轮成功推送后跳过抓取", variable=low_power).grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 2))
    ttk.Checkbutton(panel, text="允许好友私聊发送“开启推送”订阅（仅私聊推送）", variable=subscribe).grid(row=9, column=0, columnspan=3, sticky="w")
    controls = ttk.Frame(panel)
    controls.grid(row=10, column=0, columnspan=3, sticky="ew", pady=14)
    output = scrolledtext.ScrolledText(panel, height=12, wrap="word", font=("Microsoft YaHei UI", 10))
    output.grid(row=11, column=0, columnspan=3, sticky="nsew")
    panel.rowconfigure(11, weight=1)
    events: queue.Queue = queue.Queue()
    buttons = []
    busy = False

    def say(text):
        output.insert("end", str(text) + "\n")
        output.see("end")

    def operation(action):
        nonlocal base, busy
        if busy:
            return
        try:
            config = base
            if action != "remove":
                config = make_settings(base, url.get(), token.get(), recipients.get(),
                                       "group" if kind.get() == "QQ群" else "private",
                                       low_power.get(), subscribe.get(),
                                       require_targets=action in ("save", "test", "install"))
                write_settings(config)
                base = config
        except Exception as exc:
            messagebox.showerror("请检查配置", str(exc))
            return
        busy = True
        for button in buttons:
            button.configure(state="disabled")
        say("正在处理…")

        def worker():
            try:
                if action == "save":
                    result = "配置已保存在程序文件夹。"
                elif action == "login":
                    result = check_login(config)
                elif action == "test":
                    check_login(config)
                    bot.send_qq_message(config["qq"], "【远行商人助手】\nQQ 推送连接正常，这是你手动发送的测试消息。")
                    result = "测试消息已发送，请查看接收 QQ 或群。"
                elif action == "preview":
                    logger = bot.setup_logging(config)
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        ok = bot.run_once(config, logger, preview=True)
                    result = buffer.getvalue().strip() if ok else "当前没有可预览的商品，请检查营业时段或稍后重试。"
                elif action == "install":
                    check_login(config)
                    manage_schedule("Install")
                    result = "自动提醒已开启，约一分钟后首次检查，之后每五分钟检查。\n可以关闭本窗口；NapCat 需要保持在线。"
                else:
                    manage_schedule("Remove")
                    result = "自动提醒已关闭，配置和历史记录保留。"
                events.put((True, result))
            except Exception as exc:
                events.put((False, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    for label, action in [("保存配置", "save"), ("检查 QQ 登录", "login"), ("发送测试", "test"), ("预览商品", "preview"), ("开启自动提醒", "install"), ("关闭自动提醒", "remove")]:
        button = ttk.Button(controls, text=label, command=lambda a=action: operation(a))
        button.pack(side="left", padx=(0, 5))
        buttons.append(button)

    def poll():
        nonlocal busy
        try:
            while True:
                ok, text = events.get_nowait()
                say(text if ok else "操作失败：" + text)
                busy = False
                for button in buttons:
                    button.configure(state="normal")
        except queue.Empty:
            pass
        root.after(100, poll)
    say("首次使用请先登录 NapCat QQ，并在其 WebUI 启用 HTTP 服务。\nQQ 密码和扫码登录均在 NapCat 中完成，本工具只连接消息接口。")
    root.after(100, poll)
    root.mainloop()


def main() -> int:
    custom = ("--setup", "--check-login", "--enable-auto", "--disable-auto", "--status", "--self-test")
    if any(flag in sys.argv for flag in custom):
        parser = argparse.ArgumentParser(description="远行商人 QQ 提醒配置")
        mode = parser.add_mutually_exclusive_group(required=True)
        for flag in custom:
            mode.add_argument(flag, action="store_true")
        parser.add_argument("--config", type=Path, default=CONFIG_PATH)
        parser.add_argument("--self-test-output", type=Path)
        args = parser.parse_args()
        try:
            if args.self_test:
                config = read_settings(args.config)
                report = {"version": VERSION, "config_readable": True, "platform": sys.platform}
                if os.name == "nt":
                    import tkinter
                    root = tkinter.Tk()
                    root.withdraw()
                    root.update()
                    root.destroy()
                    report["gui_available"] = True
                if args.self_test_output:
                    args.self_test_output.write_text(json.dumps(report), encoding="utf-8")
                if sys.stdout:
                    print(json.dumps(report))
            elif args.setup:
                terminal_setup(args.config.resolve())
            elif args.disable_auto or args.status:
                print(manage_schedule("Remove" if args.disable_auto else "Status", args.config.resolve()))
            else:
                config = read_settings(args.config)
                if args.check_login:
                    print(check_login(config))
                else:
                    bot.validate_qq_config(config["qq"])
                    check_login(config)
                    print(manage_schedule("Install", args.config.resolve()))
            return 0
        except Exception as exc:
            if sys.stderr:
                print(str(exc), file=sys.stderr)
            return 1
    if len(sys.argv) > 1:
        return bot.main()
    if os.name == "nt":
        desktop_window()
    else:
        print("远行商人 QQ 提醒 v" + VERSION + "\n首次配置：./RockMerchantQQ --setup\n其他参数：--check-login / --test-message / --preview / --enable-auto / --disable-auto / --status / --once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
