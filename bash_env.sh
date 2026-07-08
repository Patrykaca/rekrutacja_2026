#!/usr/bin/env bash
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:-YOUR_PROJECT_ID}"
export REGION="${REGION:-us-east1}"
export DATASET="${DATASET:-product_ds}"
export TABLE="${TABLE:-products_raw}"
export TOPIC="${TOPIC:-synthetic-data-generator}"
export SERVICE="${SERVICE:-pubsub-to-bq-products}"

export SUBSCRIPTION="${SUBSCRIPTION:-${TOPIC}-push-sub}"
export DLQ_TOPIC="${DLQ_TOPIC:-${TOPIC}-dlq}"
export DLQ_SUBSCRIPTION="${DLQ_SUBSCRIPTION:-${DLQ_TOPIC}-pull-sub}"

export RUN_SA_NAME="${RUN_SA_NAME:-pubsub-bq-run}"
export PUSH_SA_NAME="${PUSH_SA_NAME:-pubsub-push}"
export RUN_SA="${RUN_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export PUSH_SA="${PUSH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export BQ_TABLE="${PROJECT_ID}.${DATASET}.${TABLE}"
export EXTERNAL_PUBLISHER_SA="${EXTERNAL_PUBLISHER_SA:-data-office-assignment@kramp-data-office-sandbox.iam.gserviceaccount.com}"
export GRANT_EXTERNAL_PUBLISHER="${GRANT_EXTERNAL_PUBLISHER:-true}"
export REQUIRE_EXTERNAL_PUBLISHER_BINDING="${REQUIRE_EXTERNAL_PUBLISHER_BINDING:-true}"
export PYTHON_BIN="${PYTHON_BIN:-python3}"
export RESET_RESOURCES="${RESET_RESOURCES:-true}"
export RESET_BIGQUERY_DATASET="${RESET_BIGQUERY_DATASET:-true}"
export CLEAN_ARTIFACT_IMAGES="${CLEAN_ARTIFACT_IMAGES:-true}"
export ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-cloud-run-source-deploy}"

if [[ "${PROJECT_ID}" == "YOUR_PROJECT_ID" ]]; then
  echo "Set PROJECT_ID before running, for example: PROJECT_ID=my-gcp-project bash bash_env.sh" >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  pubsub.googleapis.com \
  run.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com

delete_subscription_if_exists() {
  local subscription="$1"
  if gcloud pubsub subscriptions describe "${subscription}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud pubsub subscriptions delete "${subscription}" --project="${PROJECT_ID}" --quiet
  fi
}

delete_topic_if_exists() {
  local topic="$1"
  if gcloud pubsub topics describe "${topic}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud pubsub topics delete "${topic}" --project="${PROJECT_ID}" --quiet
  fi
}

delete_cloud_run_service_if_exists() {
  if gcloud run services describe "${SERVICE}" --region="${REGION}" >/dev/null 2>&1; then
    gcloud run services delete "${SERVICE}" --region="${REGION}" --quiet
  fi
}

delete_bigquery_dataset_if_exists() {
  if bq show --project_id="${PROJECT_ID}" "${DATASET}" >/dev/null 2>&1; then
    bq rm -r -f "${PROJECT_ID}:${DATASET}"
  fi
}

delete_artifact_package_if_exists() {
  if ! gcloud artifacts repositories describe "${ARTIFACT_REPOSITORY}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" >/dev/null 2>&1; then
    return
  fi

  if gcloud artifacts packages describe "${SERVICE}" \
    --project="${PROJECT_ID}" \
    --repository="${ARTIFACT_REPOSITORY}" \
    --location="${REGION}" >/dev/null 2>&1; then
    gcloud artifacts packages delete "${SERVICE}" \
      --project="${PROJECT_ID}" \
      --repository="${ARTIFACT_REPOSITORY}" \
      --location="${REGION}" \
      --quiet
  fi
}

grant_external_publisher_access() {
  local grant_output

  if [[ "${GRANT_EXTERNAL_PUBLISHER}" != "true" ]]; then
    echo "Skipping external publisher IAM grant because GRANT_EXTERNAL_PUBLISHER=${GRANT_EXTERNAL_PUBLISHER}."
    return
  fi

  echo "Granting roles/pubsub.publisher on ${TOPIC} to ${EXTERNAL_PUBLISHER_SA}..."
  if grant_output="$(gcloud pubsub topics add-iam-policy-binding "${TOPIC}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${EXTERNAL_PUBLISHER_SA}" \
    --role="roles/pubsub.publisher" \
    --quiet 2>&1)"; then
    echo "${grant_output}"
    return
  fi

  echo "WARNING: Could not grant roles/pubsub.publisher to ${EXTERNAL_PUBLISHER_SA}." >&2
  echo "Verify the external publisher service account from the assignment and rerun with EXTERNAL_PUBLISHER_SA=correct-sa@project.iam.gserviceaccount.com." >&2

  if [[ "${REQUIRE_EXTERNAL_PUBLISHER_BINDING}" == "true" ]]; then
    echo "${grant_output}" >&2
    exit 1
  fi
}

grant_bigquery_dataset_writer_access() {
  local dataset_ref="${PROJECT_ID}:${DATASET}"
  local current_metadata
  local updated_metadata

  current_metadata="$(mktemp)"
  updated_metadata="$(mktemp)"

  bq show --project_id="${PROJECT_ID}" --format=prettyjson "${dataset_ref}" >"${current_metadata}"

  "${PYTHON_BIN}" - "${current_metadata}" "${updated_metadata}" "${RUN_SA}" <<'PY'
import json
import sys

source_path, target_path, service_account = sys.argv[1:]

with open(source_path, encoding="utf-8") as source_file:
    dataset = json.load(source_file)

access_entries = dataset.setdefault("access", [])
writer_entry = {
    "role": "WRITER",
    "userByEmail": service_account,
}

if writer_entry not in access_entries:
    access_entries.append(writer_entry)

with open(target_path, "w", encoding="utf-8") as target_file:
    json.dump(dataset, target_file)
PY

  bq update --project_id="${PROJECT_ID}" --source="${updated_metadata}" "${dataset_ref}"

  rm -f "${current_metadata}" "${updated_metadata}"
}

if [[ "${RESET_RESOURCES}" == "true" ]]; then
  echo "Resetting existing GCP resources for ${SERVICE}..."
  delete_subscription_if_exists "${SUBSCRIPTION}"
  delete_subscription_if_exists "${DLQ_SUBSCRIPTION}"
  delete_topic_if_exists "${TOPIC}"
  delete_topic_if_exists "${DLQ_TOPIC}"
  delete_cloud_run_service_if_exists

  if [[ "${RESET_BIGQUERY_DATASET}" == "true" ]]; then
    delete_bigquery_dataset_if_exists
  fi

  if [[ "${CLEAN_ARTIFACT_IMAGES}" == "true" ]]; then
    delete_artifact_package_if_exists
  fi
fi

if ! gcloud iam service-accounts describe "${RUN_SA}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${RUN_SA_NAME}" \
    --display-name="Cloud Run Pub/Sub to BigQuery runtime"
fi

if ! gcloud iam service-accounts describe "${PUSH_SA}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${PUSH_SA_NAME}" \
    --display-name="Pub/Sub push OIDC invoker"
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
PUBSUB_SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding "${PUSH_SA}" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --quiet

if ! gcloud pubsub topics describe "${TOPIC}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud pubsub topics create "${TOPIC}" --project="${PROJECT_ID}"
fi

grant_external_publisher_access

if ! gcloud pubsub topics describe "${DLQ_TOPIC}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud pubsub topics create "${DLQ_TOPIC}" --project="${PROJECT_ID}"
fi

gcloud pubsub topics add-iam-policy-binding "${DLQ_TOPIC}" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role="roles/pubsub.publisher" \
  --quiet

if ! gcloud pubsub subscriptions describe "${DLQ_SUBSCRIPTION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud pubsub subscriptions create "${DLQ_SUBSCRIPTION}" \
    --topic="${DLQ_TOPIC}" \
    --project="${PROJECT_ID}"
fi

if ! bq show --project_id="${PROJECT_ID}" "${DATASET}" >/dev/null 2>&1; then
  bq --location="${REGION}" mk --dataset "${PROJECT_ID}:${DATASET}"
fi

bq query --project_id="${PROJECT_ID}" --location="${REGION}" --use_legacy_sql=false <<SQL
CREATE TABLE IF NOT EXISTS \`${BQ_TABLE}\` (
  id STRING,
  name STRING,
  description STRING,
  is_in_stock BOOL,
  price NUMERIC,
  last_update TIMESTAMP,
  attributes ARRAY<STRUCT<key STRING, value STRING>>,
  _insert_timestamp TIMESTAMP,
  _source_message_id STRING,
  _raw_payload STRING
);
SQL

grant_bigquery_dataset_writer_access

gcloud run deploy "${SERVICE}" \
  --source . \
  --region="${REGION}" \
  --service-account="${RUN_SA}" \
  --no-allow-unauthenticated \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},PUBSUB_TOPIC=${TOPIC},BQ_DATASET=${DATASET},BQ_TABLE=${BQ_TABLE},REQUIRE_PUBSUB_OIDC=false,LOG_LEVEL=INFO,BQ_TIMEOUT=30,MAX_REQUEST_BYTES=9437184,MAX_RAW_PAYLOAD_BYTES=8388608,MAX_ROWS_PER_BATCH=250" \
  --quiet

SERVICE_URL="$(gcloud run services describe "${SERVICE}" \
  --region="${REGION}" \
  --format="value(status.url)")"

gcloud run services update "${SERVICE}" \
  --region="${REGION}" \
  --update-env-vars="REQUIRE_PUBSUB_OIDC=true,PUBSUB_OIDC_AUDIENCE=${SERVICE_URL},PUBSUB_OIDC_SERVICE_ACCOUNT=${PUSH_SA}" \
  --quiet

gcloud run services add-iam-policy-binding "${SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${PUSH_SA}" \
  --role="roles/run.invoker" \
  --quiet

if gcloud pubsub subscriptions describe "${SUBSCRIPTION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud pubsub subscriptions delete "${SUBSCRIPTION}" --project="${PROJECT_ID}" --quiet
fi

gcloud pubsub subscriptions create "${SUBSCRIPTION}" \
  --topic="${TOPIC}" \
  --project="${PROJECT_ID}" \
  --push-endpoint="${SERVICE_URL}/pubsub/push" \
  --push-auth-service-account="${PUSH_SA}" \
  --push-auth-token-audience="${SERVICE_URL}" \
  --dead-letter-topic="${DLQ_TOPIC}" \
  --max-delivery-attempts=5

gcloud pubsub subscriptions add-iam-policy-binding "${SUBSCRIPTION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${PUBSUB_SERVICE_AGENT}" \
  --role="roles/pubsub.subscriber" \
  --quiet

echo "Cloud Run URL: ${SERVICE_URL}"
echo "Healthcheck requires an authenticated Cloud Run request."

echo "Publishing valid sample message..."
gcloud pubsub topics publish "${TOPIC}" \
  --project="${PROJECT_ID}" \
  --message="$(cat sample/sample.json)"

echo "Recent Cloud Run logs:"
gcloud run services logs read "${SERVICE}" --region="${REGION}" --limit=20

echo "Recent BigQuery rows:"
bq query --project_id="${PROJECT_ID}" --location="${REGION}" --use_legacy_sql=false <<SQL
SELECT id, name, price, _source_message_id
FROM \`${BQ_TABLE}\`
ORDER BY _insert_timestamp DESC
LIMIT 10;
SQL

cat <<EOF

To test DLQ manually, publish an invalid message:

gcloud pubsub topics publish "${TOPIC}" \\
  --project="${PROJECT_ID}" \\
  --message='{"id":"not-a-uuid","name":"Bad product","is_in_stock":"true","price":"10.50","last_update":"Mon, 17 Jun 2024 13:47:16 UTC","attributes":[]}'

Then wait for retries and pull from DLQ:

gcloud pubsub subscriptions pull "${DLQ_SUBSCRIPTION}" \\
  --project="${PROJECT_ID}" \\
  --auto-ack \\
  --limit=10
EOF
