#!/bin/sh

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
LOG_DIR="$ROOT_DIR/.logs"

stop_service() {
  name="$1"
  pid_file="$LOG_DIR/$name.pid"

  if [ ! -f "$pid_file" ]; then
    echo "$name is not running"
    return 0
  fi

  pid=$(cat "$pid_file" 2>/dev/null || true)
  rm -f "$pid_file"

  if [ -z "${pid:-}" ]; then
    echo "$name pid file was empty"
    return 0
  fi

  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "$name stopped (pid=$pid)"
  else
    echo "$name was not running (stale pid=$pid)"
  fi
}

stop_service migrated-monitor
stop_service topic-rush-monitor
