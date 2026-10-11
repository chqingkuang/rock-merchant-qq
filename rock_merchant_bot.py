#!/usr/bin/env python3
"""洛克王国：世界远行商人监控与 QQ 推送。"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import logging.handlers
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PROJECT_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_API_URL = (
    "https://huodong2.4399.com/n/comm/tool/api.php"
    "?path=lkyxGood/index&tool_id=11"
)
SOURCE_PAGE = "https://huodong2.4399.com/yxhtools/game-store"
FULL_SOURCE_PAGE = (
    "https://www.onebiji.com/hykb_tools/comm/lkwgmerchant/"
    "preview.php?id=1&immgj=0"
)
BATCH_LABELS = {
    1: "08:00-12:00",
    2: "12:00-16:00",
    3: "16:00-20:00",
    4: "20:00-24:00",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "source": {
        "full_page_url": FULL_SOURCE_PAGE,
        "api_url": DEFAULT_API_URL,
        "timeout_seconds": 15,
        "retries": 3,
    },
    "qq": {
        "enabled": True,
        "base_url": "http://127.0.0.1:3000",
        "access_token": "",
        "target_type": "private",
        "target_id": "",
        "target_ids": [],
        "timeout_seconds": 10,
    },
    "subscription_commands": {
        "enabled": True,
        "add_keywords": ["开启推送"],
        "recent_count": 20,
        "confirm_message": "【远行商人】\n已开启推送",
        "already_enabled_message": "【远行商人】\n你已经在推送名单内",
    },
    "monitor": {
        "poll_seconds": 300,
        "low_power_mode": True,
        "min_batch_age_minutes": 3,
        "state_file": "data/state.json",
        "log_file": "logs/merchant_bot.log",
    },
    "rare": {
        "names": [
            "棱镜球",
            "炫彩蛋",
            "炫彩精灵蛋",
            "赛季炫彩精灵蛋",
            "国王球",
            "首领血脉秘药",
            "祝福项坠",
        ],
        "name_keywords": ["炫彩", "棱镜", "首领血脉"],
        "tag_keywords": ["超级稀有", "较为罕见", "露头就秒"],
        "trust_source_worth_flag": True,
    },
    "weekend_sale": {
        "ball_keywords": [
            "球"
        ],
        "item_names": [
            "残缺魔镜",
            "适格钥匙",
            "能力钥匙"
        ],
        "event_limit_names": [
            "残缺魔镜",
            "适格钥匙",
            "能力钥匙"
        ],
        "exclude_names": [
            "国王球",
            "棱镜球",
            "炫彩球"
        ]
    },
}


class BotError(RuntimeError):
    pass


@dataclass(frozen=True)
class MerchantBatch:
    batch: int
    items: list[dict[str, Any]]


class FullMerchantPageParser(HTMLParser):
    """Parse the public full-product merchant page without external packages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._capture: str | None = None
        self._capture_parts: list[str] = []
        self._stack: list[tuple[str, set[str]]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attrs}

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr_map = self._attrs(attrs)
        classes = set(attr_map.get("class", "").split())
        if tag == "li" and "li_show" in classes:
            batches = sorted(
                {
                    int(match.group(1))
                    for value in classes
                    if (match := re.fullmatch(r"show_([1-4])", value))
                }
            )
            self._current = {
                "batches": batches,
                "end_timestamp": attr_map.get("data-time", ""),
            }
        elif self._current is not None and tag == "em":
            if "shop_name" in classes:
                self._capture = "name"
            elif "shop_price" in classes:
                self._capture = "price_text"
            elif any("gitem" in parent_classes for _, parent_classes in self._stack):
                self._capture = "buy_limit_text"
            if self._capture:
                self._capture_parts = []
        if tag not in {"img", "br", "hr", "input", "meta", "link"}:
            self._stack.append((tag, classes))

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._capture:
            self._capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "em" and self._current is not None and self._capture:
            text = "".join(self._capture_parts).strip()
            self._current[self._capture] = text
            self._capture = None
            self._capture_parts = []
        if tag == "li" and self._current is not None:
            if self._current.get("name") and self._current.get("batches"):
                self.items.append(self._current)
            self._current = None
            self._capture = None
            self._capture_parts = []
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise BotError(f"配置文件不存在：{path}")
    try:
        user_config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BotError(f"无法读取配置文件 {path}：{exc}") from exc
    if not isinstance(user_config, dict):
        raise BotError("配置文件顶层必须是 JSON 对象")
    return deep_merge(DEFAULT_CONFIG, user_config)


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_DIR / path


def setup_logging(config: dict[str, Any], verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("rock_merchant_bot")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    log_path = resolve_project_path(config["monitor"]["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    retries: int = 1,
) -> dict[str, Any]:
    body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/136 Safari/537.36"
        ),
    }
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"

    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            request = urllib.request.Request(
                url, data=body, headers=request_headers, method=method
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                result = json.loads(response.read().decode(charset))
                if not isinstance(result, dict):
                    raise BotError("接口返回内容不是 JSON 对象")
                return result
        except (
            OSError,
            urllib.error.URLError,
            urllib.error.HTTPError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(min(2**attempt, 4))
    raise BotError(f"请求失败：{url}；{last_error}")


def request_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
    retries: int = 1,
) -> str:
    request_headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/136 Safari/537.36"
        ),
    }
    if headers:
        request_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(min(2**attempt, 4))
    raise BotError(f"请求失败：{url}；{last_error}")


def fetch_rare_name_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = config["source"]
    result = request_json(
        source["api_url"],
        headers={"Referer": SOURCE_PAGE},
        timeout=int(source["timeout_seconds"]),
        retries=int(source["retries"]),
    )
    if result.get("error_code") not in (0, "0", None) or result.get("success") is False:
        raise BotError(f"数据源返回错误：{result.get('msg', '未知错误')}")

    raw_batches = result.get("list")
    if not isinstance(raw_batches, list):
        raise BotError("数据源缺少商品列表")

    rare_map: dict[str, dict[str, Any]] = {}
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, dict):
            continue
        raw_items = raw_batch.get("items", [])
        for item in raw_items:
            if isinstance(item, dict) and str(item.get("name", "")).strip():
                rare_map[str(item["name"]).strip()] = item
    return rare_map


def parse_full_batches(
    html: str, rare_map: dict[str, dict[str, Any]] | None = None
) -> list[MerchantBatch]:
    parser = FullMerchantPageParser()
    parser.feed(html)
    grouped: dict[int, list[dict[str, Any]]] = {
        batch: [] for batch in BATCH_LABELS
    }
    rare_map = rare_map or {}
    for parsed_item in parser.items:
        name = str(parsed_item.get("name", "")).strip()
        price_text = (
            str(parsed_item.get("price_text", ""))
            .replace("价格：", "")
            .strip()
        )
        buy_limit_text = (
            str(parsed_item.get("buy_limit_text", ""))
            .replace("限购", "")
            .strip()
        )
        rare_item = rare_map.get(name, {})
        is_special_all_day = str(rare_item.get("day_batch", "")) == "0"
        covers_all_rounds = parsed_item["batches"] == [1, 2, 3, 4]
        item = {
            "id": str(rare_item.get("id", "")),
            "name": name,
            "price_text": price_text,
            "buy_limit": buy_limit_text,
            "is_worth": rare_item.get("is_worth", "0"),
            "tags": rare_item.get("tags", ""),
            "stime": "",
            "etime": "",
            "special_all_day": is_special_all_day,
            "covers_all_rounds": covers_all_rounds,
        }
        target_batches = (
            list(BATCH_LABELS)
            if is_special_all_day or covers_all_rounds
            else parsed_item["batches"]
        )
        for batch in target_batches:
            grouped[batch].append(dict(item))
    return [
        MerchantBatch(batch=batch, items=items)
        for batch, items in grouped.items()
    ]


def fetch_api_batches(config: dict[str, Any]) -> list[MerchantBatch]:
    source = config["source"]
    result = request_json(
        source["api_url"],
        headers={"Referer": SOURCE_PAGE},
        timeout=int(source["timeout_seconds"]),
        retries=int(source["retries"]),
    )
    if result.get("error_code") not in (0, "0", None) or result.get("success") is False:
        raise BotError(f"数据源返回错误：{result.get('msg', '未知错误')}")
    raw_batches = result.get("list")
    if not isinstance(raw_batches, list):
        raise BotError("数据源缺少商品列表")
    grouped: dict[int, list[dict[str, Any]]] = {
        batch: [] for batch in BATCH_LABELS
    }
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, dict):
            continue
        try:
            batch_number = int(raw_batch.get("batch", 0))
        except (TypeError, ValueError):
            continue
        raw_items = raw_batch.get("items", [])
        items = [item for item in raw_items if isinstance(item, dict)]
        if batch_number in BATCH_LABELS:
            for raw_item in items:
                item = dict(raw_item)
                is_special_all_day = str(item.get("day_batch", "")) == "0"
                item["special_all_day"] = is_special_all_day
                item["covers_all_rounds"] = is_special_all_day
                target_batches = (
                    list(BATCH_LABELS) if is_special_all_day else [batch_number]
                )
                for batch in target_batches:
                    grouped[batch].append(dict(item))
    return [
        MerchantBatch(batch=batch, items=items)
        for batch, items in grouped.items()
    ]


def merge_batch_sources(
    primary: list[MerchantBatch], secondary: list[MerchantBatch]
) -> list[MerchantBatch]:
    secondary_by_batch = {batch.batch: batch for batch in secondary}
    merged: list[MerchantBatch] = []
    for primary_batch in primary:
        items = [dict(item) for item in primary_batch.items]
        seen_names = {str(item.get("name", "")) for item in items}
        secondary_batch = secondary_by_batch.get(primary_batch.batch)
        if secondary_batch:
            for item in secondary_batch.items:
                name = str(item.get("name", ""))
                if name and name not in seen_names:
                    items.append(dict(item))
                    seen_names.add(name)
        merged.append(MerchantBatch(batch=primary_batch.batch, items=items))
    return merged


def fetch_batches(config: dict[str, Any]) -> list[MerchantBatch]:
    source = config["source"]
    try:
        rare_map = fetch_rare_name_map(config)
    except BotError:
        rare_map = {}
    try:
        html = request_text(
            source["full_page_url"],
            headers={"Referer": source["full_page_url"]},
            timeout=int(source["timeout_seconds"]),
            retries=int(source["retries"]),
        )
        batches = parse_full_batches(html, rare_map)
        if any(batch.items for batch in batches):
            try:
                api_batches = fetch_api_batches(config)
            except BotError:
                return batches
            return merge_batch_sources(batches, api_batches)
    except BotError:
        pass
    return fetch_api_batches(config)


def active_batch_number(now: datetime) -> int | None:
    local = now.astimezone(CHINA_TZ)
    if 8 <= local.hour < 12:
        return 1
    if 12 <= local.hour < 16:
        return 2
    if 16 <= local.hour < 20:
        return 3
    if 20 <= local.hour < 24:
        return 4
    return None


def item_is_rare(item: dict[str, Any], rare_config: dict[str, Any]) -> bool:
    name = str(item.get("name", "")).strip()
    tags = str(item.get("tags", ""))
    if rare_config.get("trust_source_worth_flag", True):
        try:
            if int(item.get("is_worth", 0)) == 1:
                return True
        except (TypeError, ValueError):
            pass
    if name in {str(value) for value in rare_config.get("names", [])}:
        return True
    if any(str(keyword) in name for keyword in rare_config.get("name_keywords", [])):
        return True
    return any(
        str(keyword) in tags for keyword in rare_config.get("tag_keywords", [])
    )


def item_is_weekend_sale(
    item: dict[str, Any], weekend_config: dict[str, Any]
) -> bool:
    if not item.get("covers_all_rounds"):
        return False
    name = str(item.get("name", "")).strip()
    if name in {str(value) for value in weekend_config.get("exclude_names", [])}:
        return False
    if name in {str(value) for value in weekend_config.get("item_names", [])}:
        return True
    return any(
        str(keyword) in name
        for keyword in weekend_config.get("ball_keywords", ["球"])
    )


def item_has_event_limit(
    item: dict[str, Any], weekend_config: dict[str, Any]
) -> bool:
    name = str(item.get("name", "")).strip()
    return name in {
        str(value) for value in weekend_config.get("event_limit_names", [])
    }


def format_number(value: Any) -> str:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number:,}"


def format_message(
    merchant_batch: MerchantBatch,
    now: datetime,
    rare_config: dict[str, Any],
    weekend_config: dict[str, Any] | None = None,
) -> str:
    local = now.astimezone(CHINA_TZ)
    weekend_config = weekend_config or DEFAULT_CONFIG["weekend_sale"]
    rare_count = sum(
        item_is_rare(item, rare_config) for item in merchant_batch.items
    )
    lines = [
        "【远行商人】",
        f"{local:%m月%d日} 第{merchant_batch.batch}轮 "
        f"{BATCH_LABELS[merchant_batch.batch]}",
        "",
    ]
    weekend_items = [
        item
        for item in merchant_batch.items
        if local.weekday() in (4, 5, 6)
        and item_is_weekend_sale(item, weekend_config)
    ]
    special_all_day_items = [
        item
        for item in merchant_batch.items
        if item.get("special_all_day")
        and not item_is_weekend_sale(item, weekend_config)
    ]
    separated_ids = {id(item) for item in weekend_items + special_all_day_items}
    regular_items = [
        item for item in merchant_batch.items if id(item) not in separated_ids
    ]

    def append_item(
        item: dict[str, Any], *, event_limit: bool = False
    ) -> None:
        rare = item_is_rare(item, rare_config)
        marker = "★ " if rare else "· "
        detail: list[str] = []
        price_text = str(item.get("price_text", "")).strip()
        price = price_text or format_number(item.get("price"))
        buy_limit = format_number(item.get("buy_limit"))
        if price and price != "0":
            detail.append(f"{price}洛克贝")
        if buy_limit and buy_limit != "0":
            if event_limit:
                detail.append(f"活动限购{buy_limit}")
            else:
                detail.append(f"限购{buy_limit}")
        suffix = f"  {' / '.join(detail)}" if detail else ""
        lines.append(f"{marker}{item.get('name', '未知商品')}{suffix}")
 
    for item in regular_items:
        append_item(item)
    if weekend_items:
        if regular_items:
            lines.append("")
        lines.append("【周末特卖 08:00-24:00】")
        for item in weekend_items:
            append_item(
                item,
                event_limit=item_has_event_limit(item, weekend_config),
            )
    if special_all_day_items:
        if regular_items or weekend_items:
            lines.append("")
        lines.append("【全天商品 08:00-24:00】")
        for item in special_all_day_items:
            append_item(item)
    if rare_count:
        lines.extend(["", "★ 为稀有/高价值商品"])
    return "\n".join(lines)


def batch_fingerprint(
    merchant_batch: MerchantBatch, now: datetime
) -> str:
    local_date = now.astimezone(CHINA_TZ).date().isoformat()
    normalized_items = []
    for item in merchant_batch.items:
        normalized_items.append(
            {
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "price": str(item.get("price", "")),
                "price_text": str(item.get("price_text", "")),
                "buy_limit": str(item.get("buy_limit", "")),
                "is_worth": str(item.get("is_worth", "")),
                "tags": str(item.get("tags", "")),
                "stime": str(item.get("stime", "")),
                "etime": str(item.get("etime", "")),
                "special_all_day": bool(item.get("special_all_day")),
                "covers_all_rounds": bool(item.get("covers_all_rounds")),
            }
        )
    raw = json.dumps(
        {
            "date": local_date,
            "batch": merchant_batch.batch,
            "items": normalized_items,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sent": []}
    if not isinstance(state, dict) or not isinstance(state.get("sent"), list):
        return {"sent": []}
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp_path, path)


def save_config(path: Path, config: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp_path, path)


def qq_target_ids(qq_config: dict[str, Any]) -> list[str]:
    configured = qq_config.get("target_ids", [])
    if isinstance(configured, list):
        targets = [str(value).strip() for value in configured]
    else:
        targets = []
    legacy_target = str(qq_config.get("target_id", "")).strip()
    if legacy_target:
        targets.append(legacy_target)
    return list(dict.fromkeys(target for target in targets if target))


def set_qq_target_ids(qq_config: dict[str, Any], targets: list[str]) -> None:
    qq_config["target_id"] = ""
    qq_config["target_ids"] = list(dict.fromkeys(str(target) for target in targets))


def validate_qq_config(qq_config: dict[str, Any]) -> None:
    if not qq_config.get("enabled", True):
        return
    target_type = qq_config.get("target_type")
    if target_type not in ("private", "group"):
        raise BotError("qq.target_type 只能是 private 或 group")
    if not qq_target_ids(qq_config):
        raise BotError("尚未配置 qq.target_ids（接收消息的 QQ 号或群号）")
    if not str(qq_config.get("base_url", "")).strip():
        raise BotError("尚未配置 qq.base_url（OneBot HTTP 地址）")


def send_qq_message(qq_config: dict[str, Any], message: str) -> None:
    if not qq_config.get("enabled", True):
        return
    validate_qq_config(qq_config)

    target_type = qq_config["target_type"]
    endpoint = (
        "/send_private_msg" if target_type == "private" else "/send_group_msg"
    )
    target_key = "user_id" if target_type == "private" else "group_id"
    base_url = str(qq_config["base_url"]).rstrip("/")
    headers: dict[str, str] = {}
    token = str(qq_config.get("access_token", "")).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    failures: list[str] = []
    for target in qq_target_ids(qq_config):
        target_value: str | int = int(target) if target.isdigit() else target
        try:
            result = request_json(
                f"{base_url}{endpoint}",
                method="POST",
                payload={target_key: target_value, "message": message},
                headers=headers,
                timeout=int(qq_config.get("timeout_seconds", 10)),
                retries=1,
            )
            if result.get("status") not in (None, "ok") or result.get(
                "retcode"
            ) not in (None, 0, "0"):
                failures.append(f"{target}: {result}")
        except BotError as exc:
            failures.append(f"{target}: {exc}")
    if failures:
        raise BotError("QQ 推送失败：" + "；".join(failures))


def qq_request(
    qq_config: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int | None = None,
) -> dict[str, Any]:
    base_url = str(qq_config["base_url"]).rstrip("/")
    headers: dict[str, str] = {}
    token = str(qq_config.get("access_token", "")).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request_json(
        f"{base_url}/{endpoint.lstrip('/')}",
        method="POST",
        payload=payload or {},
        headers=headers,
        timeout=timeout or int(qq_config.get("timeout_seconds", 10)),
        retries=1,
    )


def normalize_command_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def command_key(contact: dict[str, Any], message: dict[str, Any]) -> str:
    return "|".join(
        [
            str(contact.get("peerUin", "")),
            str(contact.get("msgId", "")),
            str(contact.get("msgTime", "")),
            str(message.get("time", "")),
            normalize_command_text(message.get("raw_message", "")),
        ]
    )


def extract_subscription_request(
    contact: dict[str, Any],
    command_config: dict[str, Any],
) -> tuple[str, str] | None:
    if str(contact.get("chatType", "")) != "1":
        return None
    message = contact.get("lastestMsg")
    if not isinstance(message, dict):
        return None
    if message.get("post_type") != "message":
        return None
    if message.get("message_type") != "private":
        return None

    peer = str(contact.get("peerUin") or message.get("user_id") or "").strip()
    if not peer.isdigit():
        return None
    sender = str(message.get("user_id", "")).strip()
    self_id = str(message.get("self_id", "")).strip()
    if sender and self_id and sender == self_id:
        return None

    text = normalize_command_text(message.get("raw_message", ""))
    keywords = {
        normalize_command_text(keyword)
        for keyword in command_config.get("add_keywords", [])
    }
    if text not in keywords:
        return None
    return peer, command_key(contact, message)


def send_private_message_to_target(
    qq_config: dict[str, Any], target: str, message: str
) -> None:
    single_config = dict(qq_config)
    single_config["target_type"] = "private"
    set_qq_target_ids(single_config, [target])
    send_qq_message(single_config, message)


def process_subscription_commands(
    config: dict[str, Any],
    state: dict[str, Any],
    config_path: Path | None,
    logger: logging.Logger,
) -> list[str]:
    command_config = config.get("subscription_commands", {})
    if not command_config.get("enabled", True):
        return []
    qq_config = config["qq"]
    if not qq_config.get("enabled", True):
        return []
    if qq_config.get("target_type") != "private":
        return []

    try:
        result = qq_request(
            qq_config,
            "get_recent_contact",
            {"count": int(command_config.get("recent_count", 20))},
        )
    except BotError as exc:
        logger.warning("检查 QQ 指令失败：%s", exc)
        return []

    contacts = result.get("data", [])
    if not isinstance(contacts, list):
        return []

    processed = {
        str(value) for value in state.get("processed_subscription_commands", [])
    }
    targets = qq_target_ids(qq_config)
    added: list[str] = []

    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        request = extract_subscription_request(contact, command_config)
        if request is None:
            continue
        target, key = request
        if key in processed:
            continue
        processed.add(key)

        if target in targets:
            send_private_message_to_target(
                qq_config,
                target,
                str(command_config.get("already_enabled_message", "")).strip()
                or "【远行商人】\n你已经在推送名单内",
            )
            continue

        targets.append(target)
        added.append(target)
        send_private_message_to_target(
            qq_config,
            target,
            str(command_config.get("confirm_message", "")).strip()
            or "【远行商人】\n已开启推送",
        )
        logger.info("已将 QQ %s 加入推送名单", target)

    if added:
        set_qq_target_ids(qq_config, targets)
        if config_path is not None:
            save_config(config_path, config)

    if processed:
        state["processed_subscription_commands"] = list(processed)[-200:]
    return added


def select_active_batch(
    batches: list[MerchantBatch], now: datetime
) -> MerchantBatch | None:
    batch_number = active_batch_number(now)
    if batch_number is None:
        return None
    return next((batch for batch in batches if batch.batch == batch_number), None)


def batch_age_minutes(now: datetime, batch_number: int) -> int:
    local = now.astimezone(CHINA_TZ)
    start_hour = {1: 8, 2: 12, 3: 16, 4: 20}[batch_number]
    return local.hour * 60 + local.minute - start_hour * 60


def has_batch_specific_items(merchant_batch: MerchantBatch) -> bool:
    return any(
        not item.get("special_all_day") and not item.get("covers_all_rounds")
        for item in merchant_batch.items
    )


def run_once(
    config: dict[str, Any],
    logger: logging.Logger,
    *,
    force: bool = False,
    preview: bool = False,
    now: datetime | None = None,
    config_path: Path | None = None,
) -> bool:
    now = now or datetime.now(tz=CHINA_TZ)
    local = now.astimezone(CHINA_TZ)
    local_date = local.date().isoformat()
    state_path = resolve_project_path(config["monitor"]["state_file"])
    state = load_state(state_path)
    if not preview:
        process_subscription_commands(config, state, config_path, logger)
        save_state(state_path, state)

    batch_number = active_batch_number(now)
    if batch_number is None:
        logger.info("当前不在营业时段（北京时间 08:00-24:00），本次跳过")
        return False

    last_sent_date = str(
        state.get("last_sent_date")
        or str(state.get("last_sent_at", "")).split("T")[0]
    )
    if (
        config.get("monitor", {}).get("low_power_mode", True)
        and not force
        and not preview
        and state.get("last_batch") == batch_number
        and last_sent_date == local_date
    ):
        logger.info("第 %s 轮已推送，低负载模式跳过重复抓取", batch_number)
        return False

    batches = fetch_batches(config)
    merchant_batch = select_active_batch(batches, now)
    if merchant_batch is None:
        logger.info("当前不在营业时段（北京时间 08:00-24:00），本次跳过")
        return False
    if not merchant_batch.items:
        logger.info("第 %s 轮数据尚未更新，本次稍后再查", merchant_batch.batch)
        return False
    min_batch_age = int(config.get("monitor", {}).get("min_batch_age_minutes", 3))
    if (
        batch_age_minutes(now, merchant_batch.batch) < min_batch_age
        and not has_batch_specific_items(merchant_batch)
    ):
        logger.info(
            "第 %s 轮普通商品尚未出现，等待源站完成刷新",
            merchant_batch.batch,
        )
        return False

    message = format_message(
        merchant_batch,
        now,
        config["rare"],
        config.get("weekend_sale"),
    )
    if preview:
        print(message)
        return True

    fingerprint = batch_fingerprint(merchant_batch, now)
    if fingerprint in state["sent"] and not force:
        logger.info("第 %s 轮内容已推送，跳过重复消息", merchant_batch.batch)
        return False

    send_qq_message(config["qq"], message)
    state["sent"].append(fingerprint)
    state["sent"] = state["sent"][-200:]
    state["last_sent_at"] = now.astimezone(CHINA_TZ).isoformat()
    state["last_sent_date"] = local_date
    state["last_batch"] = merchant_batch.batch
    save_state(state_path, state)
    logger.info("第 %s 轮商品已推送到 QQ", merchant_batch.batch)
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="自动抓取洛克王国：世界远行商人并推送到 QQ"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_DIR / "config.json",
        help="配置文件路径",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="检查一次后退出")
    mode.add_argument("--watch", action="store_true", help="常驻并定时轮询")
    mode.add_argument("--preview", action="store_true", help="只在终端预览，不推送")
    mode.add_argument(
        "--test-message", action="store_true", help="向 QQ 发送一条连接测试消息"
    )
    parser.add_argument("--force", action="store_true", help="忽略去重，强制推送")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config.resolve())
        logger = setup_logging(config, args.verbose)
        if args.test_message:
            now = datetime.now(tz=CHINA_TZ)
            send_qq_message(
                config["qq"],
                f"【远行商人助手】QQ 推送连接正常\n测试时间：{now:%Y-%m-%d %H:%M:%S}（北京时间）",
            )
            logger.info("QQ 测试消息发送成功")
            return 0
        if args.preview:
            run_once(config, logger, preview=True)
            return 0
        if args.watch:
            validate_qq_config(config["qq"])
            interval = max(60, int(config["monitor"]["poll_seconds"]))
            logger.info("开始监控，轮询间隔 %s 秒", interval)
            while True:
                try:
                    run_once(
                        config,
                        logger,
                        force=args.force,
                        config_path=args.config.resolve(),
                    )
                except BotError as exc:
                    logger.error("%s", exc)
                time.sleep(interval)
        else:
            run_once(
                config,
                logger,
                force=args.force,
                config_path=args.config.resolve(),
            )
        return 0
    except BotError as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
        logging.getLogger("rock_merchant_bot").error("%s", exc)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
