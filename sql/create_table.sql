CREATE TABLE IF NOT EXISTS `YOUR_PROJECT_ID.product_ds.products_raw` (
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
