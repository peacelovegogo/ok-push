#!/usr/bin/env python3

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECT_DIR.parent
ENGINE_PATH = ROOT_DIR / "binance_migrated_monitor.py"
DEFAULT_STATE_PATH = PROJECT_DIR / ".state" / "binance-topic-rush-bsc.json"
ENV_FILE_PATH = PROJECT_DIR / ".env"
TOPIC_TELEGRAM_ENV_MAP = {
    "TOPIC_TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
    "TOPIC_TG_BOT_TOKEN": "TG_BOT_TOKEN",
    "TOPIC_TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
    "TOPIC_TG_CHAT_ID": "TG_CHAT_ID",
}
GENERIC_TELEGRAM_ENV_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TG_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TG_CHAT_ID",
]


def has_option(arguments: list[str], option: str) -> bool:
    return any(argument == option or argument.startswith(f"{option}=") for argument in arguments)


def with_default_option(arguments: list[str], option: str, value: str) -> list[str]:
    if has_option(arguments, option):
        return arguments
    return [option, value, *arguments]


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


def build_command(arguments: list[str]) -> list[str]:
    resolved = with_default_option(arguments, "--state", str(DEFAULT_STATE_PATH))
    resolved = with_default_option(resolved, "--feeds", "topic")
    return [sys.executable, str(ENGINE_PATH), *resolved]


def build_environment() -> dict[str, str]:
    environment = dict(os.environ)

    # Topic Rush does not inherit the migrated-token Telegram bot by default.
    for key in GENERIC_TELEGRAM_ENV_KEYS:
        environment.pop(key, None)

    environment.update(load_env_file(ENV_FILE_PATH))

    for source_key, target_key in TOPIC_TELEGRAM_ENV_MAP.items():
        value = environment.get(source_key, "").strip()
        if value:
            environment[target_key] = value

    return environment


def main() -> None:
    os.execve(sys.executable, build_command(sys.argv[1:]), build_environment())


if __name__ == "__main__":
    main()
