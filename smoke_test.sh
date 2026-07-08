#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PROJECT_ID="${PROJECT_ID:-YOUR_PROJECT_ID}"
export REGION="${REGION:-us-east1}"
export DATASET="${DATASET:-product_ds}"
export TABLE="${TABLE:-products_raw}"
export TOPIC="${TOPIC:-synthetic-data-generator}"
export DLQ_SUBSCRIPTION="${DLQ_SUBSCRIPTION:-${TOPIC}-dlq-pull-sub}"
export BQ_TABLE="${BQ_TABLE:-${PROJECT_ID}.${DATASET}.${TABLE}}"
export VALID_TIMEOUT_SECONDS="${VALID_TIMEOUT_SECONDS:-120}"
export DLQ_TIMEOUT_SECONDS="${DLQ_TIMEOUT_SECONDS:-240}"
export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
export CHECK_DLQ="${CHECK_DLQ:-true}"
export PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ "${PROJECT_ID}" == "YOUR_PROJECT_ID" ]]; then
  echo "Set PROJECT_ID before running, for example: PROJECT_ID=my-gcp-project bash smoke_test.sh" >&2
  exit 1
fi

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
}

sql_escape() {
  local value="$1"
  printf "%s" "${value//\'/\'\'}"
}

query_inserted_row_count() {
  local message_id="$1"
  local escaped_message_id
  escaped_message_id="$(sql_escape "${message_id}")"

  bq query \
    --project_id="${PROJECT_ID}" \
    --location="${REGION}" \
    --quiet \
    --format=csv \
    --use_legacy_sql=false \
    "SELECT COUNT(1) AS row_count FROM \`${BQ_TABLE}\` WHERE _source_message_id = '${escaped_message_id}'" |
    tail -n 1 |
    tr -d '\r'
}

wait_for_bigquery_row() {
  local message_id="$1"
  local deadline=$((SECONDS + VALID_TIMEOUT_SECONDS))

  while ((SECONDS < deadline)); do
    local row_count
    row_count="$(query_inserted_row_count "${message_id}")"
    if [[ "${row_count}" =~ ^[0-9]+$ ]] && ((row_count >= 1)); then
      echo "BigQuery row found for Pub/Sub message_id=${message_id}"
      return 0
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for BigQuery row for Pub/Sub message_id=${message_id}" >&2
  return 1
}

dlq_pull_contains_marker() {
  local marker="$1"

  "${PYTHON_BIN}" -c '
import base64
import json
import sys

marker = sys.argv[1]
raw = sys.stdin.read()

try:
    received_messages = json.loads(raw or "[]")
except json.JSONDecodeError:
    sys.exit(1)

for received_message in received_messages:
    encoded_data = received_message.get("message", {}).get("data", "")
    try:
        decoded_data = base64.b64decode(encoded_data).decode("utf-8", errors="replace")
    except Exception:
        decoded_data = encoded_data

    if marker in decoded_data:
        print(decoded_data)
        sys.exit(0)

sys.exit(1)
' "${marker}"
}

wait_for_dlq_message() {
  local marker="$1"
  local deadline=$((SECONDS + DLQ_TIMEOUT_SECONDS))

  while ((SECONDS < deadline)); do
    local pulled_messages
    pulled_messages="$(
      gcloud pubsub subscriptions pull "${DLQ_SUBSCRIPTION}" \
        --project="${PROJECT_ID}" \
        --limit=20 \
        --format=json
    )"

    if dlq_pull_contains_marker "${marker}" <<<"${pulled_messages}" >/dev/null; then
      echo "DLQ message found for marker=${marker}"
      return 0
    fi

    sleep "${POLL_INTERVAL_SECONDS}"
  done

  echo "Timed out waiting for DLQ message marker=${marker}" >&2
  return 1
}

require_command gcloud
require_command bq
require_command "${PYTHON_BIN}"

echo "Publishing valid sample message..."
VALID_MESSAGE_ID="$(
  gcloud pubsub topics publish "${TOPIC}" \
    --project="${PROJECT_ID}" \
    --message="$(cat "${SCRIPT_DIR}/sample/sample.json")" \
    --format="value(messageIds[0])"
)"

if [[ -z "${VALID_MESSAGE_ID}" ]]; then
  echo "Could not read message id from valid Pub/Sub publish response." >&2
  exit 1
fi

wait_for_bigquery_row "${VALID_MESSAGE_ID}"

if [[ "${CHECK_DLQ}" != "true" ]]; then
  echo "Skipping DLQ check because CHECK_DLQ=${CHECK_DLQ}."
  exit 0
fi

INVALID_MARKER="invalid-smoke-$(date +%s)"
INVALID_PAYLOAD="{\"id\":\"not-a-uuid\",\"name\":\"${INVALID_MARKER}\",\"is_in_stock\":\"true\",\"price\":\"10.50\",\"last_update\":\"Mon, 17 Jun 2024 13:47:16 UTC\",\"attributes\":[]}"

echo "Publishing invalid sample message marker=${INVALID_MARKER}..."
gcloud pubsub topics publish "${TOPIC}" \
  --project="${PROJECT_ID}" \
  --message="${INVALID_PAYLOAD}" \
  --format="value(messageIds[0])" >/dev/null

wait_for_dlq_message "${INVALID_MARKER}"

echo "Smoke test passed."
