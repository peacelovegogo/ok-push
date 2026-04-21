#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = PROJECT_DIR / ".env"

MIGRATED_API_URLS = [
    (
        "https://web3.binance.com/bapi/defi/v1/public/"
        "wallet-direct/buw/wallet/market/token/pulse/rank/list/ai"
    ),
    (
        "https://web3.binance.com/bapi/defi/v1/public/"
        "wallet-direct/buw/wallet/market/token/pulse/rank/list"
    ),
]
MIGRATED_PAGE_URL = "https://web3.binance.com/zh-CN/trenches?chain={chain_slug}"

DEFAULT_LIMIT = 100
DEFAULT_INTERVAL_SECONDS = 10
DEFAULT_NOTIFY_MAX_AGE_SECONDS = 60 * 60
STATE_FILE_PATH = PROJECT_DIR / ".state" / "binance-migrated-bsc.json"
EMPTY_RESULT_WARNING_INTERVAL_SECONDS = 10 * 60
LAST_EMPTY_RESULT_WARNING_AT = 0.0
PROTOCOL_LABELS = {
    1001: "Pump.fun",
    1002: "Moonit",
    1003: "Pump AMM",
    1004: "Launch Lab",
    1005: "Raydium V4",
    1006: "Raydium CPMM",
    1007: "Raydium CLMM",
    1008: "BONK",
    1009: "Dynamic BC",
    1010: "Moonshot",
    1011: "Jup Studio",
    1012: "Bags",
    1013: "Believer",
    1014: "Meteora DAMM V2",
    1015: "Meteora Pools",
    1016: "Orca",
    2001: "Four.meme",
    2002: "Flap",
}
CHAIN_ALIASES = {"bsc": "56", "56": "56"}
CHAIN_SLUGS = {"56": "bsc"}


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def apply_local_environment() -> None:
    os.environ.update(load_env_file(ENV_FILE_PATH))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Binance Web3 migrated meme tokens.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Check once and print the current snapshot.",
    )
    parser.add_argument(
        "--chain",
        default="bsc",
        help="Chain alias or chainId. Default: bsc",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="How many tokens to request. Binance currently caps at 100.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Polling interval in seconds. Default: 10",
    )
    parser.add_argument(
        "--state",
        default=str(STATE_FILE_PATH),
        help="Path to the state file.",
    )
    parser.add_argument(
        "--webhook",
        default="",
        help="Optional webhook URL for new items.",
    )
    parser.add_argument(
        "--telegram-bot-token",
        default="",
        help="Telegram bot token. Falls back to TELEGRAM_BOT_TOKEN or TG_BOT_TOKEN.",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default="",
        help="Telegram chat id. Falls back to TELEGRAM_CHAT_ID or TG_CHAT_ID.",
    )
    parser.add_argument(
        "--telegram-test-message",
        default="",
        help="Send a Telegram test message and exit.",
    )
    parser.add_argument(
        "--telegram-enable-preview",
        action="store_true",
        help="Enable link preview in Telegram messages.",
    )
    return parser.parse_args()


def normalize_chain_id(value: str) -> str:
    chain_id = CHAIN_ALIASES.get(str(value).strip().lower())
    if not chain_id:
        raise ValueError(f"Unsupported chain: {value}")
    return chain_id


def clamp_limit(value: int) -> int:
    if value <= 0:
        raise ValueError("limit must be a positive integer")
    return min(value, DEFAULT_LIMIT)


def empty_state(chain_id: str) -> dict:
    return {
        "version": 1,
        "chainId": chain_id,
        "initializedAt": None,
        "lastCheckAt": None,
        "seen": {},
    }


def load_state(path: Path, chain_id: str) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_state(chain_id)

    try:
        data = json.loads(content)
    except Exception as error:
        print(
            f"[{format_now()}] State file is invalid, rebuilding baseline: {error}",
            file=sys.stderr,
        )
        return empty_state(chain_id)

    if not isinstance(data, dict):
        print(
            f"[{format_now()}] State file is invalid, rebuilding baseline: not a JSON object",
            file=sys.stderr,
        )
        return empty_state(chain_id)

    if isinstance(data.get("seen"), dict):
        state = empty_state(chain_id)
        state["initializedAt"] = data.get("initializedAt")
        state["lastCheckAt"] = data.get("lastCheckAt")
        state["seen"] = data.get("seen", {})
        return state

    print(
        f"[{format_now()}] State file is invalid, rebuilding baseline: unsupported structure",
        file=sys.stderr,
    )
    return empty_state(chain_id)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_telegram_config(args: argparse.Namespace) -> Optional[dict]:
    bot_token = (
        args.telegram_bot_token
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TG_BOT_TOKEN")
        or ""
    ).strip()
    chat_id = (
        args.telegram_chat_id
        or os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("TG_CHAT_ID")
        or ""
    ).strip()

    if not bot_token and not chat_id:
        return None
    if not bot_token or not chat_id:
        raise ValueError("Telegram bot token and chat id must be provided together")

    return {
        "botToken": bot_token,
        "chatId": chat_id,
        "disablePreview": not args.telegram_enable_preview,
    }


def http_post_json(url: str, payload: dict, headers: Optional[dict[str, str]] = None) -> dict:
    request_headers = {
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "Mozilla/5.0 (compatible; MigratedMonitor/1.0)",
    }
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=request_headers,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API request failed with HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"API request failed: {error.reason}") from error


def fetch_tokens(chain_id: str, limit: int) -> list[dict]:
    request_payload = {
        "chainId": chain_id,
        "rankType": 30,
        "limit": limit,
    }
    headers = build_request_headers(chain_id)
    last_payload: Optional[dict] = None

    for api_url in MIGRATED_API_URLS:
        payload = http_post_json(api_url, request_payload, headers=headers)
        last_payload = payload

        if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
            continue

        if payload["data"]:
            return [normalize_token(item, chain_id) for item in payload["data"]]

    if last_payload and last_payload.get("code") == "000000" and isinstance(last_payload.get("data"), list):
        maybe_warn_on_empty_result()
        return []

    if last_payload is None:
        raise RuntimeError("Unexpected API response: empty response")

    raise RuntimeError(
        f"Unexpected API response: {last_payload.get('code')} {last_payload.get('message') or ''}".strip()
    )


def build_request_headers(chain_id: str) -> dict[str, str]:
    chain_slug = CHAIN_SLUGS.get(chain_id, "bsc")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://web3.binance.com",
        "Referer": MIGRATED_PAGE_URL.format(chain_slug=chain_slug),
    }
    user_agent = str(os.getenv("MIGRATED_API_USER_AGENT") or "").strip()
    if user_agent:
        headers["User-Agent"] = user_agent

    cookie_header = str(os.getenv("MIGRATED_COOKIE_HEADER") or "").strip()
    if cookie_header:
        headers["Cookie"] = cookie_header

    return headers


def maybe_warn_on_empty_result() -> None:
    global LAST_EMPTY_RESULT_WARNING_AT

    now = time.time()
    if now - LAST_EMPTY_RESULT_WARNING_AT < EMPTY_RESULT_WARNING_INTERVAL_SECONDS:
        return

    LAST_EMPTY_RESULT_WARNING_AT = now
    cookie_header = str(os.getenv("MIGRATED_COOKIE_HEADER") or "").strip()
    if cookie_header:
        print(f"[{format_now()}] 接口返回空列表 | 已尝试官方 API 与 Cookie 兜底")
        return

    print(
        f"[{format_now()}] 接口返回空列表 | "
        "如浏览器网页可见，请在当前项目的 .env 中配置 MIGRATED_COOKIE_HEADER 复用浏览器会话"
    )


def normalize_url(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"https://bin.bnbstatic.com{text}"
    return text


def protocol_label(protocol: Optional[int]) -> str:
    if protocol is None:
        return "-"
    return PROTOCOL_LABELS.get(protocol, f"Protocol {protocol}")


def normalize_token(raw_token: dict, chain_id: str) -> dict:
    address = str(raw_token.get("contractAddress") or "").lower()
    chain_slug = CHAIN_SLUGS.get(chain_id, "bsc")
    protocol = int(raw_token.get("protocol") or 0) or None
    socials = raw_token.get("socials") or {}
    twitter_info = raw_token.get("twitterInfo") or {}

    return {
        "address": address,
        "symbol": str(raw_token.get("symbol") or ""),
        "name": str(raw_token.get("name") or ""),
        "displayName": " ".join(
            item for item in [str(raw_token.get("symbol") or ""), str(raw_token.get("name") or "")] if item
        ).strip(),
        "iconUrl": normalize_url(raw_token.get("icon")),
        "protocol": protocol,
        "platformLabel": protocol_label(protocol),
        "migrateTimeMs": int(raw_token.get("migrateTime") or 0),
        "migrateTimeText": format_timestamp(raw_token.get("migrateTime") or 0),
        "createTimeMs": int(raw_token.get("createTime") or 0),
        "createTimeText": format_timestamp(raw_token.get("createTime") or 0),
        "marketCap": parse_decimal(raw_token.get("marketCap")),
        "liquidity": parse_decimal(raw_token.get("liquidity")),
        "volume": parse_decimal(raw_token.get("volume")),
        "holders": int(raw_token.get("holders") or 0),
        "txCount": int(raw_token.get("count") or 0),
        "buyCount": int(raw_token.get("countBuy") or 0),
        "sellCount": int(raw_token.get("countSell") or 0),
        "priceChangePercent": parse_decimal(raw_token.get("priceChange")),
        "top10HoldingPercent": parse_decimal(raw_token.get("holdersTop10Percent")),
        "insiderHoldingPercent": parse_decimal(raw_token.get("holdersInsiderPercent")),
        "sniperHoldingPercent": parse_decimal(raw_token.get("holdersSniperPercent")),
        "newWalletHoldingPercent": parse_decimal(raw_token.get("newWalletHoldingPercent")),
        "bnHolders": int(raw_token.get("bnHolders") or 0),
        "kolHolders": int(raw_token.get("kolHolders") or 0),
        "proHolders": int(raw_token.get("proHolders") or 0),
        "devSellPercent": parse_decimal(raw_token.get("devSellPercent")),
        "narrativeCn": str((raw_token.get("narrativeText") or {}).get("cn") or ""),
        "narrativeEn": str((raw_token.get("narrativeText") or {}).get("en") or ""),
        "websiteUrl": normalize_url(socials.get("website")),
        "twitterUrl": normalize_url(socials.get("twitter")),
        "telegramUrl": normalize_url(socials.get("telegram")),
        "twitterHandle": raw_token.get("twitterHandle"),
        "twitterFollowers": int(twitter_info.get("followersCnt") or 0),
        "tokenUrl": f"https://web3.binance.com/zh-CN/token/{chain_slug}/{address}",
    }


def parse_decimal(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def find_new_items(items: list[dict], state: dict) -> list[dict]:
    new_items: list[dict] = []

    for item in items:
        previous = state["seen"].get(item["address"])
        if previous is None or item["migrateTimeMs"] > int(previous.get("migrateTimeMs") or 0):
            new_items.append(item)

    new_items.sort(key=lambda entry: entry["migrateTimeMs"], reverse=True)
    return new_items


def update_seen_state(state: dict, items: list[dict], now_iso: str) -> None:
    for item in items:
        previous = state["seen"].get(item["address"], {})
        state["seen"][item["address"]] = {
            "address": item["address"],
            "displayName": item["displayName"],
            "symbol": item["symbol"],
            "name": item["name"],
            "migrateTimeMs": item["migrateTimeMs"],
            "tokenUrl": item["tokenUrl"],
            "firstSeenAt": previous.get("firstSeenAt") or now_iso,
            "lastSeenAt": now_iso,
        }


def split_notification_items(items: list[dict], now_epoch_ms: int) -> tuple[list[dict], list[dict]]:
    cutoff_ms = now_epoch_ms - DEFAULT_NOTIFY_MAX_AGE_SECONDS * 1000
    notify_items: list[dict] = []
    skipped_items: list[dict] = []

    for item in items:
        migrate_time_ms = int(item.get("migrateTimeMs") or 0)
        if migrate_time_ms and migrate_time_ms >= cutoff_ms:
            notify_items.append(item)
            continue
        skipped_items.append(item)

    return notify_items, skipped_items


def maybe_notify_webhook(webhook_url: str, payload: dict) -> None:
    if not webhook_url:
        return

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 400:
                raise RuntimeError(f"Webhook failed with HTTP {response.status}")
    except Exception as error:
        raise RuntimeError(f"Webhook failed: {error}") from error

    print(f"[{format_now()}] Webhook delivered")


def send_telegram_api(telegram_config: Optional[dict], method: str, payload: dict) -> dict:
    if telegram_config is None:
        return {}

    url = f"https://api.telegram.org/bot{telegram_config['botToken']}/{method}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Telegram request failed with HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Telegram request failed: {error.reason}") from error

    if not response_payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {response_payload.get('description') or 'unknown error'}")

    return response_payload


def send_telegram_message(
    telegram_config: Optional[dict],
    text: str,
    reply_markup: Optional[dict] = None,
) -> None:
    if telegram_config is None:
        return

    payload = {
        "chat_id": telegram_config["chatId"],
        "text": text,
        "disable_web_page_preview": telegram_config["disablePreview"],
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    send_telegram_api(telegram_config, "sendMessage", payload)
    print(f"[{format_now()}] Telegram delivered")


def send_telegram_photo(
    telegram_config: Optional[dict],
    photo_url: str,
    caption: str,
    reply_markup: Optional[dict] = None,
) -> None:
    if telegram_config is None:
        return

    payload = {
        "chat_id": telegram_config["chatId"],
        "photo": photo_url,
        "caption": caption,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    send_telegram_api(telegram_config, "sendPhoto", payload)
    print(f"[{format_now()}] Telegram delivered")


def maybe_notify_telegram(telegram_config: Optional[dict], items: list[dict]) -> None:
    if telegram_config is None:
        return

    for item in items:
        send_telegram_token_card(telegram_config, item)


def send_telegram_token_card(telegram_config: Optional[dict], item: dict) -> None:
    caption = build_telegram_token_caption(item)
    keyboard = build_telegram_token_keyboard(item)
    if item.get("iconUrl"):
        try:
            send_telegram_photo(telegram_config, item["iconUrl"], caption, keyboard)
            return
        except Exception as error:
            print(f"[{format_now()}] Telegram photo fallback to text: {error}", file=sys.stderr)

    send_telegram_message(telegram_config, caption, keyboard)


def process_tokens(
    args: argparse.Namespace,
    state: dict,
    chain_id: str,
    now_iso: str,
    telegram_config: Optional[dict],
) -> None:
    items = fetch_tokens(chain_id, clamp_limit(args.limit))
    now_epoch_ms = int(time.time() * 1000)

    if not state["initializedAt"]:
        update_seen_state(state, items, now_iso)
        state["initializedAt"] = now_iso
        state["lastCheckAt"] = now_iso
        print(f"[{format_now()}] 已建立基线 | 当前 {len(items)} 条 | 后续仅提示新增")
        if args.once:
            print_snapshot(items)
        return

    new_items = find_new_items(items, state)
    notify_items, skipped_items = split_notification_items(new_items, now_epoch_ms)
    update_seen_state(state, items, now_iso)
    state["lastCheckAt"] = now_iso

    print(
        f"[{format_now()}] 检查完成 | 当前 {len(items)} 条 | "
        f"新发现 {len(new_items)} 条 | 推送 {len(notify_items)} 条"
    )

    if skipped_items:
        print(
            f"[{format_now()}] 已跳过 {len(skipped_items)} 条超出通知时间窗口的旧条目 | "
            f"时间窗口 {DEFAULT_NOTIFY_MAX_AGE_SECONDS // 60} 分钟"
        )

    if notify_items:
        print_new_items(notify_items)
        maybe_notify_webhook(
            args.webhook,
            {
                "event": "new_migrated_tokens",
                "source": "migrated-monitor",
                "detectedAt": now_iso,
                "chainId": chain_id,
                "items": notify_items,
            },
        )
        maybe_notify_telegram(telegram_config, notify_items)
    elif args.once:
        print_snapshot(items)


def print_snapshot(items: list[dict]) -> None:
    print("")
    print("=== 当前快照 | 已迁移代币 ===")
    for index, item in enumerate(items, start=1):
        print(item_snapshot_line(index, item))
    print("")


def print_new_items(items: list[dict]) -> None:
    print("")
    print("=== 新增条目 | 已迁移代币 ===")
    for index, item in enumerate(items, start=1):
        print(item_new_line(index, item))
    print("")


def item_snapshot_line(index: int, item: dict) -> str:
    return "\n".join(
        [
            f"{index}. {item['displayName']}".strip(),
            (
                "   迁移时间: "
                f"{item['migrateTimeText']} | 市值: {format_compact(item['marketCap'])} "
                f"| 流动性: {format_compact(item['liquidity'])}"
            ),
            (
                "   地址: "
                f"{item['address']} | 持有人: {format_integer(item['holders'])} "
                f"| TX: {format_integer(item['txCount'])}"
            ),
        ]
    )


def item_new_line(index: int, item: dict) -> str:
    return "\n".join(
        [
            f"{index}. {item['displayName']}".strip(),
            (
                "   迁移时间: "
                f"{item['migrateTimeText']} | 市值: {format_compact(item['marketCap'])} "
                f"| 成交额: {format_compact(item['volume'])}"
            ),
            (
                "   地址: "
                f"{item['address']} | 持有人: {format_integer(item['holders'])} "
                f"| TX: {format_integer(item['txCount'])}"
            ),
            f"   链接: {item['tokenUrl']}",
        ]
    )


def build_telegram_token_caption(item: dict) -> str:
    symbol = str(item.get("symbol") or "").strip()
    name = str(item.get("name") or "").strip()
    if symbol and name and symbol != name:
        title = f"{symbol} {name}"
    else:
        title = symbol or name or item["displayName"] or "Unknown"

    lines = [f"{title} [{format_platform_display(item['platformLabel'], item['protocol'])}]"]
    lines.append("🧬 CA:")
    lines.append(item["address"])

    narrative = pick_token_narrative(item)
    if narrative:
        lines.append(f"📝 叙事: {narrative}")

    lines.extend(
        [
            "",
            (
                "📈 年龄: "
                f"{format_age_from_ms(item['migrateTimeMs'])} | 涨跌: {format_signed_percent(item['priceChangePercent'])}"
            ),
            (
                "💰 市值: "
                f"{format_compact(item['marketCap'])} | 💧 流动性: {format_compact(item['liquidity'])}"
            ),
            (
                "📊 成交量: "
                f"{format_compact(item['volume'])} | 🔁 TX: {format_integer(item['txCount'])}"
            ),
            (
                "🛒 买/卖: "
                f"{format_integer(item['buyCount'])}/{format_integer(item['sellCount'])} | 👛 持有: {format_integer(item['holders'])}"
            ),
            (
                "🧠 Pro/KOL/BN: "
                f"{format_integer(item['proHolders'])}/{format_integer(item['kolHolders'])}/{format_integer(item['bnHolders'])}"
            ),
            (
                "🧱 Top10: "
                f"{format_percent_value(item['top10HoldingPercent'])} | 🕵 Insider: {format_percent_value(item['insiderHoldingPercent'])}"
            ),
            (
                "🎯 Sniper: "
                f"{format_percent_value(item['sniperHoldingPercent'])} | 🆕 New: {format_percent_value(item['newWalletHoldingPercent'])}"
            ),
        ]
    )

    if item["twitterHandle"] or item["twitterFollowers"]:
        twitter_bits = ["🐦"]
        if item["twitterHandle"]:
            twitter_bits.append(f"@{item['twitterHandle']}")
        if item["twitterFollowers"]:
            twitter_bits.append(f"粉丝: {format_compact(float(item['twitterFollowers']))}")
        lines.append(" ".join(twitter_bits))

    if item["devSellPercent"] is not None:
        lines.append(f"🧯 Dev Sell: {format_percent_value(item['devSellPercent'])}")

    return "\n".join(lines)


def build_telegram_token_keyboard(item: dict) -> Optional[dict]:
    return build_telegram_inline_keyboard(
        [
            ("Binance", item["tokenUrl"]),
            ("X", item.get("twitterUrl")),
            ("TG", item.get("telegramUrl")),
            ("Web", item.get("websiteUrl")),
        ]
    )


def build_telegram_inline_keyboard(candidates: list[tuple[str, Optional[str]]]) -> Optional[dict]:
    row = []
    seen_urls = set()

    for text, url in candidates:
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        row.append({"text": text, "url": url})

    return {"inline_keyboard": [row[:4]]} if row else None


def format_compact(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value) < 1e-12:
        return "0"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return compact_unit(value / 1_000_000_000, "B")
    if absolute >= 1_000_000:
        return compact_unit(value / 1_000_000, "M")
    if absolute >= 1_000:
        return compact_unit(value / 1_000, "K")
    if absolute >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def compact_unit(value: float, suffix: str) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") + suffix


def format_percent_value(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if abs(value) < 1e-12:
        return "0%"
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"


def format_signed_percent(value: Optional[float]) -> str:
    if value is None:
        return "-"
    prefix = "+" if value > 0 else ""
    return prefix + format_percent_value(value)


def format_integer(value: int) -> str:
    return f"{value:,}"


def format_timestamp(timestamp_ms: int) -> str:
    if not timestamp_ms:
        return "-"
    return datetime.fromtimestamp(timestamp_ms / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_age_from_ms(timestamp_ms: int) -> str:
    if not timestamp_ms:
        return "-"

    diff_seconds = max(0, int(time.time() - timestamp_ms / 1000))
    if diff_seconds < 60:
        return f"{diff_seconds}s"

    diff_minutes = diff_seconds // 60
    if diff_minutes < 60:
        return f"{diff_minutes}m"

    diff_hours = diff_minutes // 60
    if diff_hours < 24:
        return f"{diff_hours}h"

    diff_days = diff_hours // 24
    return f"{diff_days}d"


def format_platform_display(label: str, protocol: Optional[int]) -> str:
    if protocol is None:
        return label or "-"
    if label and not label.startswith("Protocol "):
        return f"{label} ({protocol})"
    return f"Protocol {protocol}"


def pick_token_narrative(item: dict) -> str:
    for candidate in [item.get("narrativeCn"), item.get("narrativeEn")]:
        text = str(candidate or "").strip()
        if text:
            return truncate_text(text, 96)
    return ""


def truncate_text(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "..."


def run_check(
    args: argparse.Namespace,
    state_file: Path,
    chain_id: str,
    telegram_config: Optional[dict],
) -> None:
    now_iso = datetime.now().astimezone().isoformat()
    state = load_state(state_file, chain_id)
    state["chainId"] = chain_id
    process_tokens(args, state, chain_id, now_iso, telegram_config)
    state["lastCheckAt"] = now_iso
    save_state(state_file, state)


def main() -> None:
    apply_local_environment()
    args = parse_args()
    chain_id = normalize_chain_id(args.chain)
    state_file = Path(args.state).expanduser().resolve()
    interval = args.interval
    telegram_config = load_telegram_config(args)

    if interval <= 0:
        raise ValueError("interval must be a positive integer")

    if args.telegram_test_message:
        send_telegram_message(telegram_config, args.telegram_test_message)
        return

    if args.once:
        run_check(args, state_file, chain_id, telegram_config)
        return

    print(
        f"[{format_now()}] 开始监控 Binance Web3 已迁移代币 | "
        f"chain={chain_id} | limit={clamp_limit(args.limit)} | "
        f"interval={interval}s | state={state_file}"
    )

    while True:
        try:
            run_check(args, state_file, chain_id, telegram_config)
        except Exception as error:
            print(f"[{format_now()}] 检查失败: {error}", file=sys.stderr)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{format_now()}] 已停止监控")
    except Exception as error:
        print(f"[{format_now()}] 运行失败: {error}", file=sys.stderr)
        sys.exit(1)
