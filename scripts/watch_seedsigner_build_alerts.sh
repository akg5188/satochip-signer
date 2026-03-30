#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/build-alert-watcher.pid"
WATCH_LOG="$LOG_DIR/build-alert-watcher.log"
EVENT_LOG="$LOG_DIR/build-alert-events.log"
STATE_FILE="$LOG_DIR/build-alert-state.env"

BUILD_LOG="${BUILD_LOG:-$LOG_DIR/seedsigner-build-live.log}"
ASCII_BASE="${TP_ASCII_BASE:-$HOME/satochip-signer-ascii}"
BUILD_TIME_LOG="${BUILD_TIME_LOG:-$ASCII_BASE/output/build/build-time.log}"
OUTPUT_IMAGE_DIR="${OUTPUT_IMAGE_DIR:-$ASCII_BASE/output/images}"
FINAL_IMAGE_DIR="${FINAL_IMAGE_DIR:-$ASCII_BASE/images}"
POLL_INTERVAL="${POLL_INTERVAL:-1}"
OFFICIAL_RUNTIME_DIR="${OFFICIAL_RUNTIME_DIR:-$ROOT_DIR/.br-smartcard-runtime}"
DIST_DIR="${DIST_DIR:-$ROOT_DIR/dist}"
DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

mkdir -p "$LOG_DIR"

build_running() {
  pgrep -af "build.sh --pi0 --smartcard --skip-repo --no-clean|O=$ASCII_BASE/output|$ASCII_BASE/output|O=$OFFICIAL_RUNTIME_DIR|$OFFICIAL_RUNTIME_DIR|build_official_pi0_base_image.sh" >/dev/null
}

latest_image() {
  find "$OUTPUT_IMAGE_DIR" "$FINAL_IMAGE_DIR" "$DIST_DIR" -maxdepth 2 -type f \( -name '*.img' -o -name '*.img.xz' \) -newermt "@$WATCH_START_EPOCH" 2>/dev/null | sort | tail -n 1
}

image_ready() {
  find "$OUTPUT_IMAGE_DIR" "$FINAL_IMAGE_DIR" "$DIST_DIR" -maxdepth 2 -type f \( -name '*.img' -o -name '*.img.xz' \) -newermt "@$WATCH_START_EPOCH" 2>/dev/null | grep -q .
}

latest_error() {
  if [[ ! -f "$BUILD_LOG" ]]; then
    return 0
  fi

  rg -n '(^make: \*\*\*|^make\[[0-9]+\]: \*\*\*|Error [0-9]+|No space left|UnicodeDecodeError|Traceback|FAILED|error:)' "$BUILD_LOG" | tail -n 1 || true
}

notify_user() {
  local urgency="$1"
  local title="$2"
  local body="$3"
  local ts
  ts="$(date '+%F %T')"

  printf '[%s] %s | %s\n' "$ts" "$title" "$body" | tee -a "$EVENT_LOG" >/dev/null

  if command -v notify-send >/dev/null 2>&1; then
    env \
      DBUS_SESSION_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS" \
      XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
      notify-send -u "$urgency" -a "satochip-signer" "$title" "$body" || true
  fi
}

write_state() {
  cat >"$STATE_FILE" <<EOF
SEEN_RUNNING=$SEEN_RUNNING
LAST_STATUS=$LAST_STATUS
LAST_ERROR_HASH=$LAST_ERROR_HASH
WATCH_START_EPOCH=$WATCH_START_EPOCH
EOF
}

load_state() {
  SEEN_RUNNING=0
  LAST_STATUS="init"
  LAST_ERROR_HASH=""
  WATCH_START_EPOCH="$(date +%s)"

  if [[ -f "$STATE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$STATE_FILE"
  fi
}

watch_loop() {
  load_state

  while true; do
    local current_error current_error_hash image_path

    if build_running; then
      SEEN_RUNNING=1
      LAST_STATUS="running"
      write_state
    fi

    if image_ready; then
      image_path="$(latest_image)"
      if [[ "$LAST_STATUS" != "done" ]]; then
        notify_user normal "SeedSigner build finished" "${image_path:-Image ready}"
        printf '%s\n' "${image_path:-image-ready}" >"$LOG_DIR/BUILD_DONE.alert"
        LAST_STATUS="done"
        write_state
      fi
      exit 0
    fi

    if ! build_running && [[ "$SEEN_RUNNING" == "1" ]]; then
      current_error="$(latest_error)"
      current_error_hash="$(printf '%s' "$current_error" | sha256sum | awk '{print $1}')"

      if [[ "$LAST_STATUS" != "failed" || "$current_error_hash" != "$LAST_ERROR_HASH" ]]; then
        if [[ -n "$current_error" ]]; then
          notify_user critical "SeedSigner build stopped" "$current_error"
          printf '%s\n' "$current_error" >"$LOG_DIR/BUILD_FAILED.alert"
        else
          notify_user critical "SeedSigner build stopped" "Build process exited and no image was generated."
          printf '%s\n' "Build process exited and no image was generated." >"$LOG_DIR/BUILD_FAILED.alert"
        fi
        LAST_ERROR_HASH="$current_error_hash"
        LAST_STATUS="failed"
        write_state
      fi
      exit 0
    fi

    sleep "$POLL_INTERVAL"
  done
}

start_daemon() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    sleep 1
  fi

  local start_epoch
  start_epoch="$(date +%s)"
  cat >"$STATE_FILE" <<EOF
SEEN_RUNNING=0
LAST_STATUS=init
LAST_ERROR_HASH=
WATCH_START_EPOCH=$start_epoch
EOF

  nohup "$0" --watch >>"$WATCH_LOG" 2>&1 &
  echo "$!" >"$PID_FILE"
  printf 'watcher_started pid=%s\n' "$!"
}

stop_daemon() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
    printf 'watcher_stopped\n'
  else
    rm -f "$PID_FILE"
    printf 'watcher_not_running\n'
  fi
}

status_daemon() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    printf 'watcher_running pid=%s\n' "$(cat "$PID_FILE")"
  else
    printf 'watcher_not_running\n'
  fi
}

case "${1:---watch}" in
  --watch)
    watch_loop
    ;;
  --daemonize)
    start_daemon
    ;;
  --stop)
    stop_daemon
    ;;
  --status)
    status_daemon
    ;;
  *)
    echo "Usage: $0 [--watch|--daemonize|--stop|--status]" >&2
    exit 1
    ;;
esac
