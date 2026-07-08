#!/usr/bin/env bash
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:-YOUR_PROJECT_ID}"
export REGION="${REGION:-us-east1}"
export DATASET="${DATASET:-product_ds}"
export TOPIC="${TOPIC:-synthetic-data-generator}"
export SERVICE="${SERVICE:-pubsub-to-bq-products}"
export SUBSCRIPTION="${SUBSCRIPTION:-${TOPIC}-push-sub}"
export DLQ_TOPIC="${DLQ_TOPIC:-${TOPIC}-dlq}"
export DLQ_SUBSCRIPTION="${DLQ_SUBSCRIPTION:-${DLQ_TOPIC}-pull-sub}"
export ARTIFACT_REPOSITORY="${ARTIFACT_REPOSITORY:-cloud-run-source-deploy}"
export CLEAN_ARTIFACT_IMAGES="${CLEAN_ARTIFACT_IMAGES:-true}"
export DELETE_SERVICE_ACCOUNTS="${DELETE_SERVICE_ACCOUNTS:-false}"
export RUN_SA_NAME="${RUN_SA_NAME:-pubsub-bq-run}"
export PUSH_SA_NAME="${PUSH_SA_NAME:-pubsub-push}"
export RUN_SA="${RUN_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export PUSH_SA="${PUSH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ "${PROJECT_ID}" == "YOUR_PROJECT_ID" ]]; then
  echo "Set PROJECT_ID before running, for example: PROJECT_ID=my-gcp-project bash cleanup.sh" >&2
  exit 1
fi

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
  if gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud run services delete "${SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --quiet
  fi
}

delete_bigquery_dataset_if_exists() {
  if bq show --project_id="${PROJECT_ID}" "${DATASET}" >/dev/null 2>&1; then
    bq rm -r -f "${PROJECT_ID}:${DATASET}"
  fi
}

delete_artifact_package_if_exists() {
  if [[ "${CLEAN_ARTIFACT_IMAGES}" != "true" ]]; then
    echo "Skipping Artifact Registry cleanup because CLEAN_ARTIFACT_IMAGES=${CLEAN_ARTIFACT_IMAGES}."
    return
  fi

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

delete_service_account_if_exists() {
  local service_account="$1"
  if gcloud iam service-accounts describe "${service_account}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts delete "${service_account}" --project="${PROJECT_ID}" --quiet
  fi
}

echo "Cleaning resources for project=${PROJECT_ID}, region=${REGION}..."

delete_subscription_if_exists "${SUBSCRIPTION}"
delete_subscription_if_exists "${DLQ_SUBSCRIPTION}"
delete_topic_if_exists "${TOPIC}"
delete_topic_if_exists "${DLQ_TOPIC}"
delete_cloud_run_service_if_exists
delete_bigquery_dataset_if_exists
delete_artifact_package_if_exists

if [[ "${DELETE_SERVICE_ACCOUNTS}" == "true" ]]; then
  delete_service_account_if_exists "${RUN_SA}"
  delete_service_account_if_exists "${PUSH_SA}"
else
  echo "Keeping service accounts. Set DELETE_SERVICE_ACCOUNTS=true to remove ${RUN_SA} and ${PUSH_SA}."
fi

echo "Cleanup complete."
