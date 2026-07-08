FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Required at runtime:
#   PROJECT_ID=YOUR_PROJECT_ID
#   PUBSUB_TOPIC=synthetic-data-generator
#   BQ_DATASET=product_ds
#   BQ_TABLE=YOUR_PROJECT_ID.product_ds.products_raw
#   PUBSUB_OIDC_AUDIENCE=https://SERVICE_URL
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
