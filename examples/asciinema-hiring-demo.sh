#!/usr/bin/env bash
set -euo pipefail

export MORTICIAN_INCIDENTS_DIR="${MORTICIAN_INCIDENTS_DIR:-/mnt/c/Users/andih/repo/mortician/incidents}"
cd /mnt/c/Users/andih/repo/mortician

pause() { sleep "${1:-0.9}"; }

run() {
  echo
  printf '$ %s\n' "$*"
  pause 0.6
  eval "$@"
  pause 1.0
}

title="Run$(date +%H%M%S) Id$(date +%M%S) Demo$(date +%S) checkout queue latency spike from retry storm"

run "python3 -m mortician.main create \"$title\""
run "python3 -m mortician.main select"
issue_id="$(python3 -m mortician.main select | awk '{print $3}')"

run "python3 -m mortician.main timeline add \"$issue_id\" --action \"Declared incident and opened response bridge with Support + SRE.\""
run "python3 -m mortician.main timeline add \"$issue_id\" --action \"Rolled back retry policy and restored exponential backoff with jitter.\""
run "python3 -m mortician.main action add --task \"Add retry-policy canary tests\" --owner \"SRE\" --due \"2026-04-05\""
run "python3 -m mortician.main action add --task \"Publish support comms template for payment degradation\" --owner \"Support\" --due \"2026-04-01\""
run "python3 -m mortician.main action list"
run "python3 -m mortician.main action done 1"

run "python3 -m mortician.main edit --severity P1 --status \"Temporary Resolution\" --summary \"Retry storm exhausted DB pools; mitigation stabilized checkout latency.\" --root-cause \"Retry jitter removed in a hot path, causing synchronized reconnect storms.\" --temp-fix \"Rollback policy + cap worker concurrency + circuit breaker\""
run "python3 -m mortician.main show \"$issue_id\" --render rich"
run "python3 -m mortician.main list --status \"Temporary Resolution\""
