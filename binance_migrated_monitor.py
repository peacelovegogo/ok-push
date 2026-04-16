#!/usr/bin/env python3

import argparse
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

MIGRATED_API_URL = (
    "https://web3.binance.com/bapi/defi/v1/public/"
    "wallet-direct/buw/wallet/market/token/pulse/rank/list"
)
TOPIC_RUSH_API_URL = (
    "https://web3.binance.com/bapi/defi/v1/public/"
    "wallet-direct/buw/wallet/market/token/social-rush/rank/list"
)
MIGRATED_PAGE_URL = "https://web3.binance.com/zh-CN/trenches?chain={chain_slug}"
TOPIC_RUSH_PAGE_URL = "https://web3.binance.com/zh-CN/trenches/topic-rush?chain={chain_slug}"

DEFAULT_CHAIN_ID = "56"
DEFAULT_LIMIT = 100
DEFAULT_INTERVAL_SECONDS = 10
DEFAULT_STATE_FILE = Path(".state/binance-web3-monitor-bsc.json")
LEGACY_STATE_FILE = Path(".state/binance-migrated-bsc.json")
DEFAULT_TELEGRAM_PREVIEW = False
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

FEED_ALIASES = {
    "all": ["migrated", "topic-latest", "topic-rising", "topic-viral"],
    "topic": ["topic-latest", "topic-rising", "topic-viral"],
    "topic-all": ["topic-latest", "topic-rising", "topic-viral"],
}

FEED_CONFIGS = {
    "migrated": {
        "label": "已迁移代币",
        "kind": "token",
        "event": "new_migrated_tokens",
        "idField": "address",
        "timeField": "migrateTimeMs",
    },
    "topic-latest": {
        "label": "热点雷达 Latest",
        "kind": "topic",
        "event": "new_topic_rush_latest",
        "rankType": "10",
        "sort": "10",
        "idField": "topicId",
        "timeField": "createTimeMs",
    },
    "topic-rising": {
        "label": "热点雷达 Rising",
        "kind": "topic",
        "event": "new_topic_rush_rising",
        "rankType": "20",
        "sort": "10",
        "idField": "topicId",
        "timeField": "createTimeMs",
    },
    "topic-viral": {
        "label": "热点雷达 Viral",
        "kind": "topic",
        "event": "new_topic_rush_viral",
        "rankType": "30",
        "sort": "30",
        "idField": "topicId",
        "timeField": "createTimeMs",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor Binance Web3 migrated meme tokens and Topic Rush feeds."
    )
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
        help="How many migrated tokens to request. Binance currently caps at 100.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Polling interval in seconds. Default: 10",
    )
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_FILE),
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
        default="migrated",
        help=(
            "Comma-separated feeds: migrated, topic-latest, topic-rising, "
            "topic-viral, topic, all. Default: migrated"
        ),
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
        "version": 2,
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
    candidate_paths = [path]
    if path == DEFAULT_STATE_FILE.resolve() and LEGACY_STATE_FILE.exists():
        candidate_paths.append(LEGACY_STATE_FILE.resolve())

    loaded_path = None
    content = None

    for candidate in candidate_paths:
        try:
            content = candidate.read_text(encoding="utf-8")
            loaded_path = candidate
            break
        except FileNotFoundError:
            continue

    if content is None:
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

    # Backward compatibility with the first version that only stored migrated tokens.
    if isinstance(data.get("seen"), dict) and "feeds" not in data:
        state = empty_state(chain_id)
        state["lastCheckAt"] = data.get("lastCheckAt")
        state["feeds"]["migrated"] = {
            "initializedAt": data.get("initializedAt"),
            "lastCheckAt": data.get("lastCheckAt"),
            "seen": data.get("seen", {}),
        }
        if loaded_path == LEGACY_STATE_FILE.resolve() and path != loaded_path:
            print(
                f"[{format_now()}] 已兼容旧状态文件 {loaded_path}，后续会写入 {path}",
                file=sys.stderr,
            )
        return state

    feeds = data.get("feeds")
    if not isinstance(feeds, dict):
        print(
            f"[{format_now()}] State file is invalid, rebuilding baseline: missing feeds",
            file=sys.stderr,
        )
        return empty_state(chain_id)

    state = empty_state(chain_id)
    state["lastCheckAt"] = data.get("lastCheckAt")

    for feed_name, feed_state in feeds.items():
        if not isinstance(feed_state, dict):
            continue
        state["feeds"][feed_name] = {
            "initializedAt": feed_state.get("initializedAt"),
            "lastCheckAt": feed_state.get("lastCheckAt"),
            "seen": feed_state.get("seen", {})
            if isinstance(feed_state.get("seen"), dict)
            else {},
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


def http_post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (compatible; BinanceWeb3Monitor/2.0)",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API request failed with HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"API request failed: {error.reason}") from error


def http_get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "identity",
            "User-Agent": "Mozilla/5.0 (compatible; BinanceWeb3Monitor/2.0)",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"API request failed with HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"API request failed: {error.reason}") from error


def fetch_feed_items(feed_name: str, chain_id: str, limit: int) -> list[dict]:
    if feed_name == "migrated":
        return fetch_migrated_tokens(chain_id, limit)
    return fetch_topic_rush_topics(feed_name, chain_id)


def fetch_migrated_tokens(chain_id: str, limit: int) -> list[dict]:
    payload = http_post_json(
        MIGRATED_API_URL,
        {
            "chainId": chain_id,
            # rankType=30 is the "已迁移" list used by Binance Web3 Meme Rush.
            "rankType": 30,
            "limit": limit,
        },
    )

    if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
        raise RuntimeError(
            f"Unexpected API response: {payload.get('code')} {payload.get('message') or ''}".strip()
        )

    return [normalize_migrated_token(item, chain_id) for item in payload["data"]]


def fetch_topic_rush_topics(feed_name: str, chain_id: str) -> list[dict]:
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

    return [normalize_topic_rush_topic(item, chain_id) for item in payload["data"]]


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


def protocol_label(protocol: Optional[int]) -> str:
    if protocol is None:
        return "-"
    return PROTOCOL_LABELS.get(protocol, f"Protocol {protocol}")


def normalize_migrated_token(raw_token: dict, chain_id: str) -> dict:
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
        "migrateStatus": int(raw_token.get("migrateStatus") or 0),
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
        "price": parse_decimal(raw_token.get("price")),
        "priceChangePercent": parse_decimal(raw_token.get("priceChange")),
        "top10HoldingPercent": parse_decimal(raw_token.get("holdersTop10Percent")),
        "devHoldingPercent": parse_decimal(raw_token.get("holdersDevPercent")),
        "sniperHoldingPercent": parse_decimal(raw_token.get("holdersSniperPercent")),
        "insiderHoldingPercent": parse_decimal(raw_token.get("holdersInsiderPercent")),
        "bnHolders": int(raw_token.get("bnHolders") or 0),
        "bnHoldingPercent": parse_decimal(raw_token.get("bnHoldingPercent")),
        "kolHolders": int(raw_token.get("kolHolders") or 0),
        "kolHoldingPercent": parse_decimal(raw_token.get("kolHoldingPercent")),
        "proHolders": int(raw_token.get("proHolders") or 0),
        "proHoldingPercent": parse_decimal(raw_token.get("proHoldingPercent")),
        "newWalletHoldingPercent": parse_decimal(raw_token.get("newWalletHoldingPercent")),
        "bundlerHolders": int(raw_token.get("bundlerHolders") or 0),
        "bundlerHoldingPercent": parse_decimal(raw_token.get("bundlerHoldingPercent")),
        "devSellPercent": parse_decimal(raw_token.get("devSellPercent")),
        "devAddress": str(raw_token.get("devAddress") or ""),
        "narrativeCn": str((raw_token.get("narrativeText") or {}).get("cn") or ""),
        "narrativeEn": str((raw_token.get("narrativeText") or {}).get("en") or ""),
        "websiteUrl": normalize_url(socials.get("website")),
        "twitterUrl": normalize_url(socials.get("twitter")),
        "telegramUrl": normalize_url(socials.get("telegram")),
        "twitterHandle": raw_token.get("twitterHandle"),
        "twitterFollowers": int(twitter_info.get("followersCnt") or 0),
        "twitterFollowing": int(twitter_info.get("followingCnt") or 0),
        "twitterType": str(twitter_info.get("type") or ""),
        "tokenUrl": f"https://web3.binance.com/zh-CN/token/{chain_slug}/{address}",
    }


def normalize_topic_rush_topic(raw_topic: dict, chain_id: str) -> dict:
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
        "deepAnalysisFlag": int(raw_topic.get("deepAnalysisFlag") or 0),
        "createTimeMs": int(raw_topic.get("createTime") or 0),
        "createTimeText": format_timestamp(raw_topic.get("createTime") or 0),
        "topicNetInflow": parse_decimal(raw_topic.get("topicNetInflow")),
        "topicNetInflow1h": parse_decimal(raw_topic.get("topicNetInflow1h")),
        "topicNetInflowAth": parse_decimal(raw_topic.get("topicNetInflowAth")),
        "tokenSymbols": token_symbols,
        "topicXUrl": topic_x_urls[0] if topic_x_urls else None,
        "tokens": tokens,
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
        "migrateStatus": int(raw_token.get("migrateStatus") or 0),
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


def find_new_items(feed_name: str, items: list[dict], feed_state: dict) -> list[dict]:
    config = FEED_CONFIGS[feed_name]
    id_field = config["idField"]
    time_field = config["timeField"]
    new_items: list[dict] = []

    for item in items:
        item_id = item[id_field]
        previous = feed_state["seen"].get(item_id)
        if previous is None or item[time_field] > int(previous.get(time_field) or 0):
            new_items.append(item)

    new_items.sort(key=lambda entry: entry[time_field], reverse=True)
    return new_items


def update_seen_state(feed_name: str, feed_state: dict, items: list[dict], now_iso: str) -> None:
    config = FEED_CONFIGS[feed_name]
    id_field = config["idField"]
    time_field = config["timeField"]

    for item in items:
        item_id = item[id_field]
        previous = feed_state["seen"].get(item_id, {})
        entry = {
            id_field: item_id,
            "displayName": item["displayName"],
            time_field: item[time_field],
            "firstSeenAt": previous.get("firstSeenAt") or now_iso,
            "lastSeenAt": now_iso,
        }
        if config["kind"] == "token":
            entry["tokenUrl"] = item["tokenUrl"]
            entry["symbol"] = item["symbol"]
            entry["name"] = item["name"]
        else:
            entry["pageUrl"] = item["pageUrl"]
            entry["topicNameCn"] = item["topicNameCn"]
            entry["topicNameEn"] = item["topicNameEn"]
            entry["tokenSymbols"] = item["tokenSymbols"]
        feed_state["seen"][item_id] = entry


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


def send_telegram_api(
    telegram_config: Optional[dict],
    method: str,
    payload: dict,
) -> dict:
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
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Telegram request failed with HTTP {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Telegram request failed: {error.reason}") from error

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload.get('description') or 'unknown error'}")

    return payload


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


def maybe_notify_telegram(telegram_config: Optional[dict], feed_name: str, items: list[dict]) -> None:
    if telegram_config is None or not items:
        return

    if FEED_CONFIGS[feed_name]["kind"] == "token":
        for item in items:
            send_telegram_token_card(telegram_config, item)
        return

    for index, item in enumerate(items, start=1):
        send_telegram_topic_card(telegram_config, feed_name, index, item)


def send_telegram_token_card(telegram_config: Optional[dict], item: dict) -> None:
    caption = build_telegram_token_caption(item)
    keyboard = build_telegram_token_keyboard(item)
    if item.get("iconUrl"):
        try:
            send_telegram_photo(telegram_config, item["iconUrl"], caption, keyboard)
            return
        except Exception as error:
            print(
                f"[{format_now()}] Telegram photo fallback to text: {error}",
                file=sys.stderr,
            )
    send_telegram_message(telegram_config, caption, keyboard)


def send_telegram_topic_card(
    telegram_config: Optional[dict],
    feed_name: str,
    index: int,
    item: dict,
) -> None:
    message = build_telegram_topic_message(feed_name, index, item)
    keyboard = build_telegram_topic_keyboard(item)
    send_telegram_message(telegram_config, message, keyboard)


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
    items = fetch_feed_items(feed_name, chain_id, clamp_limit(args.limit))

    if not feed_state["initializedAt"]:
        update_seen_state(feed_name, feed_state, items, now_iso)
        feed_state["initializedAt"] = now_iso
        feed_state["lastCheckAt"] = now_iso
        print(
            f"[{format_now()}] {config['label']} 已建立基线 | "
            f"当前 {len(items)} 条 | 后续仅提示新增"
        )
        if args.once:
            print_snapshot(feed_name, items)
        return

    new_items = find_new_items(feed_name, items, feed_state)
    update_seen_state(feed_name, feed_state, items, now_iso)
    feed_state["lastCheckAt"] = now_iso

    print(
        f"[{format_now()}] {config['label']} 检查完成 | "
        f"当前 {len(items)} 条 | 新增 {len(new_items)} 条"
    )

    if new_items:
        print_new_items(feed_name, new_items)
        maybe_notify_webhook(
            args.webhook,
            {
                "event": config["event"],
                "source": "binance-web3-monitor",
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
    config = FEED_CONFIGS[feed_name]
    print("")
    print(f"=== 当前快照 | {config['label']} ===")
    if config["kind"] == "token":
        for index, item in enumerate(items, start=1):
            print(item_snapshot_line_token(index, item))
    else:
        for index, item in enumerate(items, start=1):
            print(item_snapshot_line_topic(index, item))
    print("")


def print_new_items(feed_name: str, items: list[dict]) -> None:
    config = FEED_CONFIGS[feed_name]
    print("")
    print(f"=== 新增条目 | {config['label']} ===")
    if config["kind"] == "token":
        for index, item in enumerate(items, start=1):
            print(item_new_line_token(index, item))
    else:
        for index, item in enumerate(items, start=1):
            print(item_new_line_topic(index, item))
    print("")


def item_snapshot_line_token(index: int, item: dict) -> str:
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


def item_new_line_token(index: int, item: dict) -> str:
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


def item_snapshot_line_topic(index: int, item: dict) -> str:
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


def item_new_line_topic(index: int, item: dict) -> str:
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


def build_telegram_message(feed_name: str, items: list[dict]) -> str:
    config = FEED_CONFIGS[feed_name]
    lines = [
        f"[Binance Web3] {config['label']} 新增 {len(items)} 条",
        f"时间: {format_now()}",
        "",
    ]

    max_items = min(len(items), 3)
    for index, item in enumerate(items[:max_items], start=1):
        if config["kind"] == "token":
            lines.extend(build_telegram_lines_token(index, item))
        else:
            lines.extend(build_telegram_lines_topic(index, item))
        if index != max_items:
            lines.append("")

    if len(items) > max_items:
        lines.extend(
            [
                "",
                f"其余 {len(items) - max_items} 条请查看本地终端输出或状态文件。",
            ]
        )

    return "\n".join(lines)


def build_telegram_lines_token(index: int, item: dict) -> list[str]:
    return [
        f"{index}. {item['displayName']}".strip(),
        (
            "迁移: "
            f"{item['migrateTimeText']} | 市值: {format_compact(item['marketCap'])} "
            f"| 成交额: {format_compact(item['volume'])}"
        ),
        (
            "地址: "
            f"{item['address']} | 持有人: {format_integer(item['holders'])} "
            f"| TX: {format_integer(item['txCount'])}"
        ),
        item["tokenUrl"],
    ]


def build_telegram_lines_topic(index: int, item: dict) -> list[str]:
    lines = [
        f"{index}. {item['displayName']}".strip(),
        (
            "创建: "
            f"{item['createTimeText']} | 类型: {item['type'] or '-'} "
            f"| 净流入: {format_compact(item['topicNetInflow'])}"
        ),
        (
            "1h净流入: "
            f"{format_compact(item['topicNetInflow1h'])} | 代币数: {format_integer(item['tokenSize'])}"
        ),
        f"代币: {', '.join(item['tokenSymbols'][:6]) or '-'}",
    ]
    if item.get("topicXUrl"):
        lines.append(f"X: {item['topicXUrl']}")
    lines.append(item["pageUrl"])
    return lines


def build_telegram_topic_message(feed_name: str, index: int, item: dict) -> str:
    config = FEED_CONFIGS[feed_name]
    lines = [
        f"[Binance Web3] {config['label']} 新增",
        f"时间: {format_now()}",
        "",
    ]
    lines.extend(build_telegram_lines_topic(index, item))
    return "\n".join(lines)


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


def build_telegram_topic_keyboard(item: dict) -> Optional[dict]:
    return build_telegram_inline_keyboard(
        [
            ("Binance", item["pageUrl"]),
            ("X", item.get("topicXUrl")),
        ]
    )


def build_telegram_inline_keyboard(candidates: list[tuple[str, Optional[str]]]) -> Optional[dict]:
    candidates = [
        (text, url)
        for text, url in candidates
    ]
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
    candidates = [
        item.get("narrativeCn"),
        item.get("narrativeEn"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return truncate_text(text, 96)
    return ""


def truncate_text(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


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
        f"[{format_now()}] 开始监控 Binance Web3 榜单 | "
        f"chain={chain_id} | feeds={','.join(feeds)} | "
        f"migrated-limit={clamp_limit(args.limit)} | interval={interval}s | state={state_file}"
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
