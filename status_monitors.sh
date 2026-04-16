#!/bin/sh

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
LOG_DIR="$ROOT_DIR/.logs"

show_service() {
  name="$1"
  pid_file="$LOG_DIR/$name.pid"
  log_file="$LOG_DIR/$name.log"

  if [ ! -f "$pid_file" ]; then
    echo "$name: stopped"
    return 0
  fi

  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
    echo "$name: running (pid=$pid)"
  else
    echo "$name: stale pid (${pid:-none})"
  fi

  if [ -f "$log_file" ]; then
    tail -n 5 "$log_file"
  fi
}

show_service migrated-monitor
echo ""
show_service topic-rush-monitor
