#!/bin/sh

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
LOG_DIR="$ROOT_DIR/.logs"

mkdir -p "$LOG_DIR"

start_service() {
  name="$1"
  shift

  pid_file="$LOG_DIR/$name.pid"
  log_file="$LOG_DIR/$name.log"

  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file" 2>/dev/null || true)
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      echo "$name is already running (pid=$pid)"
      return 0
    fi
    rm -f "$pid_file"
  fi

  (
    cd "$ROOT_DIR"
    nohup "$@" >> "$log_file" 2>&1 &
    echo $! > "$pid_file"
  )

  echo "$name started (pid=$(cat "$pid_file"))"
}

start_service migrated-monitor python3 -u migrated-monitor/binance_migrated_monitor.py
start_service topic-rush-monitor python3 -u topic-rush-monitor/binance_topic_rush_monitor.py
