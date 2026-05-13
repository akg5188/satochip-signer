#!/bin/sh

export LANGUAGE=zh_Hans_CN
export LANG=C.UTF-8
export OFFLINE_SIGNER_MODE=1
export TP_ONLY_MODE=1
export TMPDIR=/run/seedsigner

cd /opt/src/

mkdir -p "$TMPDIR"

# Keep logs in RAM so failures can be inspected without persisting data to the SD card.
/usr/bin/python3 main.py >> "$TMPDIR/seedsigner.log" 2>&1 &

# Set the date to release so that GPG can work
TIME_DEFAULT_FILE="/opt/src/.build_commit_time"
TIME_FALLBACK="2025-02-28 12:00"
TIME_FILE="/mnt/microsd/time.txt"
TIME_VALUE="$TIME_FALLBACK"

if [ -f "$TIME_DEFAULT_FILE" ]; then
    TIME_FROM_DEFAULT=$(tr -d '\r\n' < "$TIME_DEFAULT_FILE")
    if [ -n "$TIME_FROM_DEFAULT" ]; then
        TIME_VALUE="$TIME_FROM_DEFAULT"
    fi
fi

if [ -f "$TIME_FILE" ]; then
    TIME_FROM_FILE=$(tr -d '\r\n' < "$TIME_FILE")
    if [ -n "$TIME_FROM_FILE" ]; then
        TIME_VALUE="$TIME_FROM_FILE"
    fi
fi

/bin/date -s "$TIME_VALUE" || /bin/date -s "$TIME_FALLBACK"
