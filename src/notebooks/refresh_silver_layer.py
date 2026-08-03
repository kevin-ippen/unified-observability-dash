# Databricks notebook source
# MAGIC %md
# MAGIC # AI Observability — Silver Layer Refresh
# MAGIC
# MAGIC Builds the 4 fact/rollup tables that feed the AI Observability dashboard.
# MAGIC
# MAGIC | Table | Sources | Grain |
# MAGIC |-------|---------|-------|
# MAGIC | `ai_cost_fact` | `system.billing.usage` × `system.billing.list_prices` | billing line item |
# MAGIC | `ai_interaction_fact` | `system.ai_gateway.usage` | per-request |
# MAGIC | `ai_daily_rollup` | cost × interaction (FULL OUTER on endpoint_name/date) | day × endpoint |
# MAGIC | `genie_daily_metrics` | cost + `system.query.history` | day × surface × agent |
# MAGIC
# MAGIC **Parameters:** `catalog` (default `main`), `schema` (default `ai_observability`)

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Target Catalog")
dbutils.widgets.text("schema", "ai_observability", "Target Schema")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")
print(f"✓ Target: {catalog}.{schema}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. ai_cost_fact
# MAGIC Billing line items for all AI products (Genie, AI Gateway, Model Serving, AI Functions).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.ai_cost_fact AS
WITH ai_billing AS (
  SELECT
    u.record_id,
    u.account_id,
    u.workspace_id,
    u.usage_date,
    u.usage_start_time,
    u.usage_end_time,
    u.billing_origin_product,
    u.sku_name,
    u.usage_quantity AS dbu_quantity,

    -- Normalized surface
    CASE u.billing_origin_product
      WHEN 'GENIE' THEN
        CASE u.usage_metadata.genie.surface
          WHEN 'GENIE_CODE' THEN 'genie_code'
          WHEN 'GENIE_AGENTS' THEN 'genie_spaces'
          WHEN 'GENIE_ONE' THEN 'genie_one'
          ELSE 'genie_other'
        END
      WHEN 'AI_GATEWAY' THEN 'ai_gateway'
      WHEN 'MODEL_SERVING' THEN
        CASE u.product_features.serving_type
          WHEN 'FOUNDATION_MODEL' THEN 'fmapi'
          WHEN 'MODEL' THEN 'custom_serving'
          WHEN 'GPU_MODEL' THEN 'gpu_serving'
          WHEN 'FEATURE' THEN 'feature_serving'
          ELSE 'serving_other'
        END
      WHEN 'AI_FUNCTIONS' THEN 'ai_functions'
      ELSE 'other'
    END AS surface,

    -- Normalized endpoint identity
    COALESCE(
      u.usage_metadata.ai_gateway.endpoint_name,
      u.usage_metadata.endpoint_name
    ) AS endpoint_name,
    COALESCE(
      u.usage_metadata.ai_gateway.endpoint_id,
      u.usage_metadata.endpoint_id
    ) AS endpoint_id,
    u.usage_metadata.ai_gateway.destination_model AS destination_model,

    -- Genie-specific
    u.usage_metadata.genie.surface AS genie_surface_raw,
    u.usage_metadata.genie.channel AS genie_channel,
    u.usage_metadata.genie.agent_id AS genie_agent_id,

    -- Serving-specific
    u.product_features.serving_type,
    u.product_features.model_serving.offering_type,
    u.product_features.ai_gateway.feature_type AS ai_gateway_feature,
    u.product_features.ai_functions.ai_function,

    -- Identity
    COALESCE(u.identity_metadata.run_as, u.identity_metadata.run_by) AS user_identity,

    -- Price lookup
    COALESCE(p.pricing.default, 0) AS price_per_dbu_usd

  FROM system.billing.usage u
  LEFT JOIN system.billing.list_prices p
    ON u.sku_name = p.sku_name
    AND u.usage_date >= DATE(p.price_start_time)
    AND (p.price_end_time IS NULL OR u.usage_date < DATE(p.price_end_time))
  WHERE u.billing_origin_product IN ('GENIE', 'AI_GATEWAY', 'MODEL_SERVING', 'AI_FUNCTIONS')
    AND u.usage_date >= current_date() - INTERVAL 90 DAYS
)
SELECT
  *,
  ROUND(dbu_quantity * price_per_dbu_usd, 6) AS cost_usd
FROM ai_billing
""")
print("✓ ai_cost_fact created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. ai_interaction_fact
# MAGIC Per-request telemetry from AI Gateway (tokens, latency, errors).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.ai_interaction_fact AS
SELECT
  request_id,
  account_id,
  workspace_id,
  event_time,
  DATE(event_time) AS event_date,

  -- Endpoint / routing
  endpoint_id,
  endpoint_name,
  destination_type,
  destination_name,
  destination_model,

  -- Normalized model name
  COALESCE(
    destination_model,
    REGEXP_REPLACE(endpoint_name, '^(system\\\\.ai\\\\.|databricks-)', '')
  ) AS model_canonical,

  -- Surface classification
  CASE
    WHEN invocation_metadata.source = 'AI_QUERY' THEN 'platform_internal'
    WHEN service_type = 'MCP_SERVICE' THEN 'mcp'
    WHEN service_type = 'MODEL_SERVICE' THEN 'model_service'
    WHEN endpoint_name LIKE 'system.ai.%' THEN 'fmapi_direct'
    ELSE 'ai_gateway'
  END AS surface,

  -- Invocation context
  invocation_metadata.source AS invocation_source,
  service_type,
  service_name,
  api_type,

  -- Requester
  requester,
  requester_type,

  -- Tokens
  input_tokens,
  output_tokens,
  total_tokens,
  token_details.cache_read_input_tokens AS cached_tokens,
  token_details.output_reasoning_tokens AS reasoning_tokens,

  -- Performance
  latency_ms,
  time_to_first_byte_ms,
  status_code,
  CASE WHEN status_code >= 400 THEN true ELSE false END AS is_error,
  CASE WHEN status_code >= 500 THEN true ELSE false END AS is_server_error,

  -- MCP metadata
  mcp_metadata.tool_name AS mcp_tool_name,
  mcp_metadata.server_type AS mcp_server_type,

  -- Quality stub
  CAST(NULL AS DOUBLE) AS quality_score,
  CAST(NULL AS STRING) AS quality_source,

  -- Tags
  request_tags,
  endpoint_tags

FROM system.ai_gateway.usage
WHERE event_time >= current_date() - INTERVAL 90 DAYS
""")
print("✓ ai_interaction_fact created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. ai_daily_rollup
# MAGIC Cost x telemetry joined on endpoint_name + date.
# MAGIC `cost_allocation_method` tracks join quality (matched / cost_only / telemetry_only).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.ai_daily_rollup AS
WITH interactions AS (
  SELECT
    event_date,
    endpoint_name,
    surface,
    model_canonical,
    invocation_source,
    COUNT(*) AS request_count,
    COUNT(DISTINCT requester) AS unique_users,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(total_tokens) AS total_tokens,
    SUM(CASE WHEN is_error THEN 1 ELSE 0 END) AS error_count,
    ROUND(SUM(CASE WHEN is_error THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 4) AS error_rate_pct,
    PERCENTILE(latency_ms, 0.5) AS latency_p50_ms,
    PERCENTILE(latency_ms, 0.95) AS latency_p95_ms,
    PERCENTILE(latency_ms, 0.99) AS latency_p99_ms,
    PERCENTILE(time_to_first_byte_ms, 0.95) AS ttfb_p95_ms
  FROM {catalog}.{schema}.ai_interaction_fact
  GROUP BY event_date, endpoint_name, surface, model_canonical, invocation_source
),
costs AS (
  SELECT
    usage_date AS event_date,
    endpoint_name,
    billing_origin_product,
    surface AS cost_surface,
    ROUND(SUM(cost_usd), 6) AS total_cost_usd,
    SUM(dbu_quantity) AS total_dbu
  FROM {catalog}.{schema}.ai_cost_fact
  GROUP BY usage_date, endpoint_name, billing_origin_product, surface
)
SELECT
  COALESCE(i.event_date, c.event_date) AS event_date,
  COALESCE(i.endpoint_name, c.endpoint_name) AS endpoint_name,
  i.surface AS interaction_surface,
  c.cost_surface,
  c.billing_origin_product,
  i.model_canonical,
  i.invocation_source,
  COALESCE(i.request_count, 0) AS request_count,
  COALESCE(i.unique_users, 0) AS unique_users,
  COALESCE(i.total_input_tokens, 0) AS total_input_tokens,
  COALESCE(i.total_output_tokens, 0) AS total_output_tokens,
  COALESCE(i.total_tokens, 0) AS total_tokens,
  COALESCE(i.error_count, 0) AS error_count,
  i.error_rate_pct,
  i.latency_p50_ms,
  i.latency_p95_ms,
  i.latency_p99_ms,
  i.ttfb_p95_ms,
  COALESCE(c.total_cost_usd, 0) AS total_cost_usd,
  COALESCE(c.total_dbu, 0) AS total_dbu,

  CASE
    WHEN i.request_count IS NOT NULL AND i.request_count > 0
         AND c.total_cost_usd IS NOT NULL AND c.total_cost_usd > 0
      THEN 'matched'
    WHEN i.request_count IS NOT NULL AND i.request_count > 0
      THEN 'telemetry_only'
    WHEN c.total_cost_usd IS NOT NULL AND c.total_cost_usd > 0
      THEN 'cost_only'
    ELSE 'unattributed'
  END AS cost_allocation_method,

  CASE WHEN COALESCE(i.request_count, 0) > 0 AND COALESCE(c.total_cost_usd, 0) > 0
    THEN ROUND(c.total_cost_usd / i.request_count, 6)
    ELSE NULL
  END AS cost_per_request_usd

FROM interactions i
FULL OUTER JOIN costs c
  ON i.event_date = c.event_date
  AND i.endpoint_name = c.endpoint_name
  AND i.endpoint_name IS NOT NULL
""")
print("✓ ai_daily_rollup created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. genie_daily_metrics
# MAGIC Genie cost + query execution stats from system.query.history.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {catalog}.{schema}.genie_daily_metrics AS
WITH genie_cost AS (
  SELECT
    usage_date,
    surface,
    genie_channel,
    genie_agent_id,
    user_identity,
    SUM(cost_usd) AS cost_usd,
    SUM(dbu_quantity) AS dbu_quantity
  FROM {catalog}.{schema}.ai_cost_fact
  WHERE billing_origin_product = 'GENIE'
  GROUP BY ALL
),
genie_queries AS (
  SELECT
    DATE(start_time) AS query_date,
    query_source.genie_space_id,
    COUNT(*) AS sql_executions,
    SUM(CASE WHEN execution_status = 'FINISHED' THEN 1 ELSE 0 END) AS successful_queries,
    COUNT(DISTINCT executed_by) AS querying_users,
    ROUND(AVG(total_duration_ms)) AS avg_query_ms,
    SUM(read_bytes) AS total_bytes_scanned
  FROM system.query.history
  WHERE query_source.genie_space_id IS NOT NULL
    AND start_time >= current_date() - INTERVAL 90 DAYS
  GROUP BY DATE(start_time), query_source.genie_space_id
)
SELECT
  c.usage_date,
  c.surface,
  c.genie_channel,
  c.genie_agent_id,
  COUNT(DISTINCT c.user_identity) AS distinct_users,
  ROUND(SUM(c.cost_usd), 4) AS total_cost_usd,
  SUM(c.dbu_quantity) AS total_dbu,
  MAX(q.sql_executions) AS sql_executions,
  MAX(q.successful_queries) AS successful_queries,
  MAX(q.querying_users) AS querying_users,
  MAX(q.avg_query_ms) AS avg_query_duration_ms,
  MAX(q.total_bytes_scanned) AS total_bytes_scanned
FROM genie_cost c
LEFT JOIN genie_queries q
  ON c.usage_date = q.query_date
  AND c.genie_agent_id = q.genie_space_id
GROUP BY c.usage_date, c.surface, c.genie_channel, c.genie_agent_id
""")
print("✓ genie_daily_metrics created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

for table in ["ai_cost_fact", "ai_interaction_fact", "ai_daily_rollup", "genie_daily_metrics"]:
    count = spark.sql(f"SELECT COUNT(*) FROM {catalog}.{schema}.{table}").collect()[0][0]
    print(f"  {table}: {count:,} rows")
print("\n✓ Silver layer refresh complete")
