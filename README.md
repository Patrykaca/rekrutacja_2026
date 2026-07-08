# Product Data Ingestion Pipeline

![CI](https://github.com/Patrykaca/rekrutacja_2026/actions/workflows/ci.yml/badge.svg)

Small GCP ingestion service for Pub/Sub product events.

## Architecture

```text
External publisher
  -> Pub/Sub topic: synthetic-data-generator
  -> Pub/Sub push subscription: synthetic-data-generator-push-sub
  -> authenticated Cloud Run service: pubsub-to-bq-products
  -> FastAPI endpoint: POST /pubsub/push
  -> BigQuery table: product_ds.products_raw

Invalid messages
  -> non-2xx response from Cloud Run
  -> Pub/Sub retry
  -> Pub/Sub dead-letter topic after maxDeliveryAttempts
```

The service validates and normalizes incoming product payloads before inserting them into BigQuery. Valid messages are acknowledged only after the BigQuery insert succeeds.

## Assumptions

- The source system publishes messages to the `synthetic-data-generator` Pub/Sub topic using the product JSON structure from the assignment.
- Product events are stored append-only. The pipeline does not update or delete previous product rows.
- `description` can be null in BigQuery, although the assignment generator normally sends it as a string.
- Pub/Sub redelivery is possible, so the Pub/Sub message id is used as BigQuery `insertId` for best-effort deduplication.
- The external assignment publisher service account is `data-office-assignment@kramp-data-office-sandbox.iam.gserviceaccount.com`.

## Main Decisions

- One BigQuery table stores valid product events: `product_ds.products_raw`.
- Invalid business payloads are not inserted into BigQuery. They return a non-2xx response and are handled by Pub/Sub dead-letter policy.
- Pub/Sub message id is passed to BigQuery as `insertId` for best-effort deduplication.
- Cloud Run is deployed without unauthenticated access.
- Pub/Sub push service account is granted `roles/run.invoker`.
- Pub/Sub push requests are verified with OIDC.
- BigQuery inserts are split into batches to stay below request size and row count limits.

## Why These GCP Services

Cloud Run keeps the application small, inexpensive and suitable for the free-tier constraints while still supporting authenticated HTTPS push from Pub/Sub. Pub/Sub is the required ingestion boundary from the assignment. BigQuery is the warehouse target and stores the product events in an append-only raw table. A Pub/Sub dead-letter topic keeps invalid messages inspectable without inserting bad rows into BigQuery. Dataflow is intentionally not used because the assignment excludes it from the free-tier solution.

## Project Layout

```text
.github/workflows/
  ci.yml                   # unit tests and bash syntax checks

app/
  auth.py                  # Pub/Sub OIDC verification
  bigquery_operator.py     # BigQuery insert + batching + insertId support
  config/settings.py       # environment configuration
  main.py                  # FastAPI app and Pub/Sub endpoint
  parser.py                # Pydantic payload parser

sql/
  create_table.sql

tests/
  test_auth.py
  test_bigquery_operator.py
  test_main.py
  test_parser.py

bash_env.sh                # GCP setup/deploy/test helper
smoke_test.sh              # GCP end-to-end smoke test helper
```

## Local Development

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run tests:

```bash
python -m unittest discover -s tests
```

CI:

```text
.github/workflows/ci.yml runs Ruff, unit tests, bash syntax checks and ShellCheck on push and pull request.
```

Run locally:

```bash
export PROJECT_ID="your-project-id"
export PUBSUB_TOPIC="synthetic-data-generator"
export BQ_DATASET="product_ds"
export BQ_TABLE="your-project-id.product_ds.products_raw"
export PUBSUB_OIDC_AUDIENCE="http://localhost:8080"
export REQUIRE_PUBSUB_OIDC=false

uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Environment Variables

Required:

```text
PROJECT_ID
PUBSUB_TOPIC
BQ_DATASET
BQ_TABLE
PUBSUB_OIDC_AUDIENCE
```

Optional:

```text
BQ_TIMEOUT=30
MAX_REQUEST_BYTES=9437184
MAX_RAW_PAYLOAD_BYTES=8388608
MAX_ROWS_PER_BATCH=250
REQUIRE_PUBSUB_OIDC=true
PUBSUB_OIDC_SERVICE_ACCOUNT=
GRANT_EXTERNAL_PUBLISHER=true
REQUIRE_EXTERNAL_PUBLISHER_BINDING=true
PYTHON_BIN=python3
LOG_LEVEL=INFO
```

## GCP Deployment

The helper script creates or updates the required GCP resources:

- Pub/Sub topic
- Pub/Sub push subscription
- Pub/Sub dead-letter topic
- DLQ pull subscription for inspection
- BigQuery dataset/table
- authenticated Cloud Run service
- OIDC settings for Pub/Sub push
- dataset-level BigQuery `WRITER` access for the Cloud Run runtime service account
- IAM binding for the external assignment publisher service account

Run:

```bash
PROJECT_ID="your-project-id" bash bash_env.sh
```

By default the script resets resources owned by this project setup before redeploying:

- Cloud Run service
- Pub/Sub subscriptions and topics
- BigQuery dataset
- Artifact Registry package for the Cloud Run source image

Disable the full reset:

```bash
PROJECT_ID="your-project-id" RESET_RESOURCES=false bash bash_env.sh
```

Keep existing BigQuery data while still resetting the rest:

```bash
PROJECT_ID="your-project-id" RESET_BIGQUERY_DATASET=false bash bash_env.sh
```

Default values can be overridden:

```bash
PROJECT_ID="your-project-id" \
REGION="us-east1" \
TOPIC="synthetic-data-generator" \
SERVICE="pubsub-to-bq-products" \
bash bash_env.sh
```

Granting the external publisher account is handled by the script through:

```bash
EXTERNAL_PUBLISHER_SA="data-office-assignment@kramp-data-office-sandbox.iam.gserviceaccount.com"
```

It grants:

```text
roles/pubsub.publisher
```

on the main Pub/Sub topic.

The external publisher binding is required by default. For local-only smoke testing without the assignment publisher binding, override it explicitly:

```bash
PROJECT_ID="your-project-id" \
GRANT_EXTERNAL_PUBLISHER=false \
bash bash_env.sh
```

## Manual Testing

Run the end-to-end smoke test:

```bash
PROJECT_ID="your-project-id" bash smoke_test.sh
```

The smoke test publishes a valid message, waits until the Pub/Sub `messageId` appears in BigQuery, publishes an invalid message, and waits until that invalid payload reaches the DLQ.

Skip the DLQ check when only the happy path should be verified:

```bash
PROJECT_ID="your-project-id" CHECK_DLQ=false bash smoke_test.sh
```

## Verified E2E


Publish a valid sample message:

```bash
gcloud pubsub topics publish synthetic-data-generator \
  --project=**** \
  --message="$(cat sample/sample.json)"
messageIds:
- '20327292732787353'
```

Read Cloud Run logs:

```bash
gcloud run services logs read pubsub-to-bq-products \
  --region=us-east1 \
  --limit=50
(...)
2026-07-08 01:31:15 POST 204 https://pubsub-to-bq-products-***-ue.a.run.app/pubsub/push
2026-07-08 01:31:20 INFO:     Started server process [1]
2026-07-08 01:31:20 INFO:     Waiting for application startup.
2026-07-08 01:31:20 INFO:     Application startup complete.
2026-07-08 01:31:20 INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
2026-07-08 01:31:20 INFO:app.main:Product stored message_id=20327292732787353 invoker=pubsub-push@****.iam.gserviceaccount.com
2026-07-08 01:31:20 INFO:     169.254.169.126:2644 - "POST /pubsub/push HTTP/1.1" 204 No Content
```

Successful processing looks like:

```text
Product stored message_id=...
POST /pubsub/push HTTP/1.1" 204 No Content
```

Query BigQuery:

```bash
bq query --use_legacy_sql=false \
'SELECT id, name, price, _source_message_id, _insert_timestamp
 FROM `****.product_ds.products_raw`
 ORDER BY _insert_timestamp DESC
 LIMIT 10'
+--------------------------------------+---------------+--------+--------------------+---------------------+
|                  id                  |     name      | price  | _source_message_id |  _insert_timestamp  |
+--------------------------------------+---------------+--------+--------------------+---------------------+
| 57b2d226-4e29-4d00-a7cb-663a81d42229 | asWWKWUogiEJS | 873.06 | 20327292732787353  | 2026-07-08 01:31:20 |
| 57b2d226-4e29-4d00-a7cb-663a81d42229 | asWWKWUogiEJS | 873.06 | 19816095545837601  | 2026-07-08 00:52:00 |
+--------------------------------------+---------------+--------+--------------------+---------------------+
```

Test DLQ with an invalid message:

```bash
gcloud pubsub topics publish synthetic-data-generator \
  --project=**** \
  --message='{"id":"not-a-uuid","name":"Bad product","is_in_stock":"true","price":"10.50","last_update":"Mon, 17 Jun 2024 13:47:16 UTC","attributes":[]}'
messageIds:
- '19817156180660593'
```

Inspect DLQ:

```bash
gcloud pubsub subscriptions pull synthetic-data-generator-dlq-pull-sub \
  --project=**** \
  --limit=10
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬───────────────────┬──────────────┬───────────────────────────────────────────────────────────────────────────┬──────────────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                     DATA                                                                    │     MESSAGE_ID    │ ORDERING_KEY │                                 ATTRIBUTES                                │ DELIVERY_ATTEMPT │                                                                                              ACK_ID                                                                                              │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────────┼──────────────┼───────────────────────────────────────────────────────────────────────────┼──────────────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ {"id":"not-a-uuid","name":"Bad product","is_in_stock":"true","price":"10.50","last_update":"Mon, 17 Jun 2024 13:47:16 UTC","attributes":[]} │ 19816684617978589 │              │ CloudPubSubDeadLetterSourceDeliveryCount=5                                │                  │ ***-MD5F                                                                                                                                                                                         │
│                                                                                                                                             │                   │              │ CloudPubSubDeadLetterSourceSubscription=synthetic-data-generator-push-sub │                  │                                                                                                                                                                                                  │
│                                                                                                                                             │                   │              │ CloudPubSubDeadLetterSourceSubscriptionProject=rekrutacaj-2026            │                  │                                                                                                                                                                                                  │
│                                                                                                                                             │                   │              │ CloudPubSubDeadLetterSourceTopicPublishTime=2026-07-08T01:35:28.132+00:00 │                  │                                                                                                                                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────┴──────────────┴───────────────────────────────────────────────────────────────────────────┴──────────────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

```

Clean DLQ after inspection:

```bash
gcloud pubsub subscriptions pull synthetic-data-generator-dlq-pull-sub \
  --project=*** \
  --auto-ack \
  --limit=1000
```

## Troubleshooting

```text
401
```

OIDC token is missing or invalid. Check `PUBSUB_OIDC_AUDIENCE`, push subscription OIDC audience and service account.

```text
403
```

A Cloud Run IAM 403 before the application logs usually means the Pub/Sub push service account is missing `roles/run.invoker`. If the request reaches the application, the OIDC token is valid but the service account does not match `PUBSUB_OIDC_SERVICE_ACCOUNT`.

```text
400
```

The payload failed validation. The logs include the failing field and a short `raw_payload_preview`.

```text
413
```

The decoded payload exceeded `MAX_RAW_PAYLOAD_BYTES`.

```text
500
```

Usually BigQuery permission, schema mismatch, environment variable or transient Google API issue.

## Data Model

`products_raw` is append-only. The service stores every valid product event and does not update existing BigQuery rows.

## Challenges

The main challenge was getting familiar with the GCP services used in the pipeline and understanding how they fit together: Pub/Sub, Cloud Run, OIDC authentication, IAM and BigQuery.

Another challenge was deciding how to handle invalid messages. I chose not to insert invalid payloads into BigQuery. Instead, the service returns a non-2xx response so Pub/Sub retries the message and eventually moves it to the DLQ.

Cloud Run authentication also required care because there are two layers: Cloud Run IAM must allow the Pub/Sub push service account to invoke the service, and the application validates the OIDC token to make sure the request comes from the expected service account.

## Future Improvements

- Manage GCP resources with Terraform for clearer infrastructure diffs and safer updates.
- Add alerting for Cloud Run 5xx responses, Pub/Sub DLQ growth and BigQuery insert failures.
- Add an analytical current-state view that deduplicates by product id and latest `last_update`.
- Replace best-effort BigQuery `insertId` deduplication with an explicit idempotency table if exactly-once semantics become required.
- Add stronger duplicate handling, for example by storing processed message ids or creating a deduplicated downstream table.
- Add product change tracking, for example detecting price, stock or attribute changes between product events.
- Add more automated and manual test scenarios for malformed payloads, duplicate deliveries and larger messages.

## Known Limitations

- BigQuery `insertId` deduplication is best-effort, not a strict exactly-once guarantee.
- The table is append-only; consumers that need current product state should query through a deduplicating view.
- CI does not run the GCP smoke test because it requires project credentials and live cloud resources.
