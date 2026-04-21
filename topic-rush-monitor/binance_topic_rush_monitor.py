#!/usr/bin/env python3

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = PROJECT_DIR / ".env"
TOPIC_TELEGRAM_ENV_MAP = {
    "TOPIC_TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
    "TOPIC_TG_BOT_TOKEN": "TG_BOT_TOKEN",
    "TOPIC_TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
    "TOPIC_TG_CHAT_ID": "TG_CHAT_ID",
}

TOPIC_RUSH_API_URL = (
    "https://web3.binance.com/bapi/defi/v1/public/"
    "wallet-direct/buw/wallet/market/token/social-rush/rank/list"
)
TOPIC_RUSH_PAGE_URL = "https://web3.binance.com/zh-CN/trenches/topic-rush?chain={chain_slug}"

DEFAULT_INTERVAL_SECONDS = 10
STATE_FILE_PATH = PROJECT_DIR / ".state" / "binance-topic-rush-bsc.json"
CHAIN_ALIASES = {"bsc": "56", "56": "56"}
CHAIN_SLUGS = {"56": "bsc"}

FEED_ALIASES = {
    "all": ["topic-latest", "topic-rising", "topic-viral"],
    "topic": ["topic-latest", "topic-rising", "topic-viral"],
    "topic-all": ["topic-latest", "topic-rising", "topic-viral"],
}
FEED_CONFIGS = {
    "topic-latest": {
        "label": "热点雷达 Latest",
        "event": "new_topic_rush_latest",
        "rankType": "10",
        "sort": "10",
    },
    "topic-rising": {
        "label": "热点雷达 Rising",
        "event": "new_topic_rush_rising",
        "rankType": "20",
        "sort": "10",
    },
    "topic-viral": {
        "label": "热点雷达 Viral",
        "event": "new_topic_rush_viral",
        "rankType": "30",
        "sort": "30",
    },
}


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

    for source_key, target_key in TOPIC_TELEGRAM_ENV_MAP.items():
        value = os.getenv(source_key, "").strip()
        if value:
            os.environ[target_key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Binance Web3 Topic Rush feeds.")
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
    parser.add_argument(
        "--feeds",
        default="topic",
        help="Comma-separated feeds: topic-latest, topic-rising, topic-viral, topic, all. Default: topic",
    )
    return parser.parse_args()


def normalize_chain_id(value: str) -> str:
    chain_id = CHAIN_ALIASES.get(str(value).strip().lower())
    if not chain_id:
        raise ValueError(f"Unsupported chain: {value}")
    return chain_id


def resolve_feeds(value: str) -> list[str]:
    requested = [item.strip().lower() for item in str(value).split(",") if item.strip()]
    if not requested:
        raise ValueError("feeds must not be empty")

    expanded: list[str] = []
    for item in requested:
        expanded.extend(FEED_ALIASES.get(item, [item]))

    feeds: list[str] = []
    for feed_name in expanded:
        if feed_name not in FEED_CONFIGS:
            raise ValueError(f"Unsupported feed: {feed_name}")
        if feed_name not in feeds:
            feeds.append(feed_name)
    return feeds


def empty_state(chain_id: str) -> dict:
    return {
        "version": 1,
        "chainId": chain_id,
        "lastCheckAt": None,
        "feeds": {},
    }


def empty_feed_state() -> dict:
    return {
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

    feeds = data.get("feeds")
    if not isinstance(feeds, dict):
        print(
            f"[{format_now()}] State file is invalid, rebuilding baseline: missing feeds",
            file=sys.stderr,
        )
        return empty_state(chain_id)

    state = empty_state(chain_id)
    state["lastCheckAt"] = data.get("lastCheckAt")

    for feed_name in FEED_CONFIGS:
        feed_state = feeds.get(feed_name)
        if not isinstance(feed_state, dict):
            continue
        state["feeds"][feed_name] = {
            "initializedAt": feed_state.get("initializedAt"),
            "lastCheckAt": feed_state.get("lastCheckAt"),
            "seen": feed_state.get("seen", {}) if isinstance(feed_state.get("seen"), dict) else {},
        }

    return state


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


def http_get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (compatible; TopicRushMonitor/1.0)",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API request failed with HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"API request failed: {error.reason}") from error


def fetch_topics(feed_name: str, chain_id: str) -> list[dict]:
    config = FEED_CONFIGS[feed_name]
    query = urllib.parse.urlencode(
        {
            "chainId": chain_id,
            "rankType": config["rankType"],
            "sort": config["sort"],
            "asc": "false",
        }
    )
    payload = http_get_json(f"{TOPIC_RUSH_API_URL}?{query}")

    if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
        raise RuntimeError(
            f"Unexpected API response: {payload.get('code')} {payload.get('message') or ''}".strip()
        )

    return [normalize_topic(item, chain_id) for item in payload["data"]]


def normalize_url(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"https://bin.bnbstatic.com{text}"
    return text


def is_x_url(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        host = urllib.parse.urlparse(value).netloc.lower()
    except Exception:
        return False
    host = host.split(":", 1)[0]
    return host == "x.com" or host.endswith(".x.com") or host == "twitter.com" or host.endswith(".twitter.com")


def collect_topic_x_urls(raw_topic: dict) -> list[str]:
    candidates: list[str] = []

    topic_link = normalize_url(raw_topic.get("topicLink"))
    if is_x_url(topic_link):
        candidates.append(topic_link)

    for raw_token in raw_topic.get("tokenList") or []:
        preview_link = raw_token.get("previewLink") or {}
        raw_x_links = preview_link.get("x")
        if isinstance(raw_x_links, str):
            raw_x_links = [raw_x_links]
        if not isinstance(raw_x_links, list):
            continue

        for raw_link in raw_x_links:
            link = normalize_url(raw_link)
            if is_x_url(link):
                candidates.append(link)

    return unique_non_empty(candidates)


def normalize_topic(raw_topic: dict, chain_id: str) -> dict:
    chain_slug = CHAIN_SLUGS.get(chain_id, "bsc")
    name = raw_topic.get("name") or {}
    topic_name_cn = str(name.get("topicNameCn") or "")
    topic_name_en = str(name.get("topicNameEn") or "")
    tokens = [normalize_topic_token(token, chain_id) for token in raw_topic.get("tokenList") or []]
    token_symbols = unique_non_empty([token["symbol"] for token in tokens])
    topic_x_urls = collect_topic_x_urls(raw_topic)

    return {
        "topicId": str(raw_topic.get("topicId") or ""),
        "topicNameCn": topic_name_cn,
        "topicNameEn": topic_name_en,
        "displayName": topic_name_cn or topic_name_en or str(raw_topic.get("topicId") or ""),
        "type": str(raw_topic.get("type") or ""),
        "tokenSize": int(raw_topic.get("tokenSize") or len(tokens)),
        "createTimeMs": int(raw_topic.get("createTime") or 0),
        "createTimeText": format_timestamp(raw_topic.get("createTime") or 0),
        "topicNetInflow": parse_decimal(raw_topic.get("topicNetInflow")),
        "topicNetInflow1h": parse_decimal(raw_topic.get("topicNetInflow1h")),
        "topicNetInflowAth": parse_decimal(raw_topic.get("topicNetInflowAth")),
        "tokenSymbols": token_symbols,
        "topicXUrl": topic_x_urls[0] if topic_x_urls else None,
        "pageUrl": TOPIC_RUSH_PAGE_URL.format(chain_slug=chain_slug),
    }


def normalize_topic_token(raw_token: dict, chain_id: str) -> dict:
    address = str(raw_token.get("contractAddress") or "").lower()
    chain_slug = CHAIN_SLUGS.get(chain_id, "bsc")

    return {
        "address": address,
        "symbol": str(raw_token.get("symbol") or ""),
        "netInflow": parse_decimal(raw_token.get("netInflow")),
        "netInflow1h": parse_decimal(raw_token.get("netInflow1h")),
        "marketCap": parse_decimal(raw_token.get("marketCap")),
        "liquidity": parse_decimal(raw_token.get("liquidity")),
        "holders": int(raw_token.get("holders") or 0),
        "uniqueTrader1h": int(raw_token.get("uniqueTrader1h") or 0),
        "count1h": int(raw_token.get("count1h") or 0),
        "tokenUrl": f"https://web3.binance.com/zh-CN/token/{chain_slug}/{address}",
    }


def parse_decimal(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unique_non_empty(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def get_feed_state(state: dict, feed_name: str) -> dict:
    if feed_name not in state["feeds"]:
        state["feeds"][feed_name] = empty_feed_state()
    return state["feeds"][feed_name]


def find_new_items(items: list[dict], feed_state: dict) -> list[dict]:
    new_items: list[dict] = []

    for item in items:
        previous = feed_state["seen"].get(item["topicId"])
        if previous is None or item["createTimeMs"] > int(previous.get("createTimeMs") or 0):
            new_items.append(item)

    new_items.sort(key=lambda entry: entry["createTimeMs"], reverse=True)
    return new_items


def update_seen_state(feed_state: dict, items: list[dict], now_iso: str) -> None:
    for item in items:
        previous = feed_state["seen"].get(item["topicId"], {})
        feed_state["seen"][item["topicId"]] = {
            "topicId": item["topicId"],
            "displayName": item["displayName"],
            "topicNameCn": item["topicNameCn"],
            "topicNameEn": item["topicNameEn"],
            "createTimeMs": item["createTimeMs"],
            "pageUrl": item["pageUrl"],
            "tokenSymbols": item["tokenSymbols"],
            "firstSeenAt": previous.get("firstSeenAt") or now_iso,
            "lastSeenAt": now_iso,
        }


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
    parse_mode: Optional[str] = None,
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
    if parse_mode:
        payload["parse_mode"] = parse_mode

    send_telegram_api(telegram_config, "sendMessage", payload)
    print(f"[{format_now()}] Telegram delivered")


def maybe_notify_telegram(telegram_config: Optional[dict], feed_name: str, items: list[dict]) -> None:
    if telegram_config is None:
        return

    for index, item in enumerate(items, start=1):
        send_telegram_topic_card(telegram_config, feed_name, index, item)


def send_telegram_topic_card(
    telegram_config: Optional[dict],
    feed_name: str,
    index: int,
    item: dict,
) -> None:
    message = build_telegram_topic_message(feed_name, index, item)
    keyboard = build_telegram_topic_keyboard(item)
    send_telegram_message(telegram_config, message, keyboard, parse_mode="HTML")


def process_feed(
    args: argparse.Namespace,
    state: dict,
    feed_name: str,
    chain_id: str,
    now_iso: str,
    telegram_config: Optional[dict],
) -> None:
    config = FEED_CONFIGS[feed_name]
    feed_state = get_feed_state(state, feed_name)
    items = fetch_topics(feed_name, chain_id)

    if not feed_state["initializedAt"]:
        update_seen_state(feed_state, items, now_iso)
        feed_state["initializedAt"] = now_iso
        feed_state["lastCheckAt"] = now_iso
        print(f"[{format_now()}] {config['label']} 已建立基线 | 当前 {len(items)} 条 | 后续仅提示新增")
        if args.once:
            print_snapshot(feed_name, items)
        return

    new_items = find_new_items(items, feed_state)
    update_seen_state(feed_state, items, now_iso)
    feed_state["lastCheckAt"] = now_iso

    print(
        f"[{format_now()}] {config['label']} 检查完成 | "
        f"当前 {len(items)} 条 | 新发现 {len(new_items)} 条 | 推送 {len(new_items)} 条"
    )

    if new_items:
        print_new_items(feed_name, new_items)
        maybe_notify_webhook(
            args.webhook,
            {
                "event": config["event"],
                "source": "topic-rush-monitor",
                "feed": feed_name,
                "label": config["label"],
                "detectedAt": now_iso,
                "chainId": chain_id,
                "items": new_items,
            },
        )
        maybe_notify_telegram(telegram_config, feed_name, new_items)
    elif args.once:
        print_snapshot(feed_name, items)


def print_snapshot(feed_name: str, items: list[dict]) -> None:
    print("")
    print(f"=== 当前快照 | {FEED_CONFIGS[feed_name]['label']} ===")
    for index, item in enumerate(items, start=1):
        print(item_snapshot_line(index, item))
    print("")


def print_new_items(feed_name: str, items: list[dict]) -> None:
    print("")
    print(f"=== 新增条目 | {FEED_CONFIGS[feed_name]['label']} ===")
    for index, item in enumerate(items, start=1):
        print(item_new_line(index, item))
    print("")


def item_snapshot_line(index: int, item: dict) -> str:
    lines = [
        f"{index}. {item['displayName']}".strip(),
        (
            "   创建时间: "
            f"{item['createTimeText']} | 类型: {item['type'] or '-'} "
            f"| 主题净流入: {format_compact(item['topicNetInflow'])}"
        ),
        (
            "   1h净流入: "
            f"{format_compact(item['topicNetInflow1h'])} | ATH净流入: "
            f"{format_compact(item['topicNetInflowAth'])} | 代币数: {format_integer(item['tokenSize'])}"
        ),
        f"   代币: {', '.join(item['tokenSymbols'][:6]) or '-'}",
    ]
    if item.get("topicXUrl"):
        lines.append(f"   X: {item['topicXUrl']}")
    return "\n".join(lines)


def item_new_line(index: int, item: dict) -> str:
    lines = [
        f"{index}. {item['displayName']}".strip(),
        (
            "   创建时间: "
            f"{item['createTimeText']} | 类型: {item['type'] or '-'} "
            f"| 主题净流入: {format_compact(item['topicNetInflow'])}"
        ),
        (
            "   1h净流入: "
            f"{format_compact(item['topicNetInflow1h'])} | ATH净流入: "
            f"{format_compact(item['topicNetInflowAth'])} | 代币数: {format_integer(item['tokenSize'])}"
        ),
        f"   代币: {', '.join(item['tokenSymbols'][:6]) or '-'}",
    ]
    if item.get("topicXUrl"):
        lines.append(f"   X: {item['topicXUrl']}")
    lines.append(f"   页面: {item['pageUrl']}")
    return "\n".join(lines)


def build_telegram_topic_message(feed_name: str, index: int, item: dict) -> str:
    config = FEED_CONFIGS[feed_name]
    token_count = format_integer(item["tokenSize"])
    net_inflow = escape_html(format_compact(item["topicNetInflow"]))
    net_inflow_1h = escape_html(format_compact(item["topicNetInflow1h"]))

    lines = [
        f"<b>{escape_html(config['label'])} 新增</b>",
        f"<code>{escape_html(format_now())}</code>",
        "",
        f"<b>{index}. {escape_html(item['displayName'])}</b>",
        "",
        f"<b>相关代币</b> {token_count} 个",
        format_topic_symbols_html(item["tokenSymbols"]),
        "",
        f"<b>创建</b> {escape_html(item['createTimeText'])}",
        f"<b>净流入</b> {net_inflow}  |  <b>1h净流入</b> {net_inflow_1h}",
    ]
    return "\n".join(lines)


def build_telegram_topic_keyboard(item: dict) -> Optional[dict]:
    return build_telegram_inline_keyboard(
        [
            ("Binance", item["pageUrl"]),
            ("X", item.get("topicXUrl")),
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


def escape_html(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


def format_topic_symbols_html(symbols: list[str], limit: int = 4) -> str:
    cleaned = unique_non_empty(symbols)
    if not cleaned:
        return "-"

    visible = [f"<code>{escape_html(symbol)}</code>" for symbol in cleaned[:limit]]
    if len(cleaned) > limit:
        visible.append("...")
    return " ".join(visible)


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


def format_integer(value: int) -> str:
    return f"{value:,}"


def format_timestamp(timestamp_ms: int) -> str:
    if not timestamp_ms:
        return "-"
    return datetime.fromtimestamp(timestamp_ms / 1000).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def format_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def run_check(
    args: argparse.Namespace,
    state_file: Path,
    chain_id: str,
    feeds: list[str],
    telegram_config: Optional[dict],
) -> None:
    now_iso = datetime.now().astimezone().isoformat()
    state = load_state(state_file, chain_id)
    state["chainId"] = chain_id

    processed = 0
    errors: list[str] = []
    for feed_name in feeds:
        try:
            process_feed(args, state, feed_name, chain_id, now_iso, telegram_config)
            processed += 1
        except Exception as error:
            message = f"{FEED_CONFIGS[feed_name]['label']}: {error}"
            errors.append(message)
            print(f"[{format_now()}] {message}", file=sys.stderr)

    if processed == 0 and errors:
        raise RuntimeError(" | ".join(errors))

    state["lastCheckAt"] = now_iso
    save_state(state_file, state)


def main() -> None:
    apply_local_environment()
    args = parse_args()
    chain_id = normalize_chain_id(args.chain)
    feeds = resolve_feeds(args.feeds)
    state_file = Path(args.state).expanduser().resolve()
    interval = args.interval
    telegram_config = load_telegram_config(args)

    if interval <= 0:
        raise ValueError("interval must be a positive integer")

    if args.telegram_test_message:
        send_telegram_message(telegram_config, args.telegram_test_message)
        return

    if args.once:
        run_check(args, state_file, chain_id, feeds, telegram_config)
        return

    print(
        f"[{format_now()}] 开始监控 Binance Web3 热点雷达 | "
        f"chain={chain_id} | feeds={','.join(feeds)} | interval={interval}s | state={state_file}"
    )

    while True:
        try:
            run_check(args, state_file, chain_id, feeds, telegram_config)
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
