# AI Observability — Executive View (DAB)

A portable Databricks Asset Bundle that deploys the AI Observability dashboard to any workspace.

## Prerequisites

1. **Databricks CLI >= 0.281.0** (required for `dataset_catalog`/`dataset_schema`)
2. **SQL Warehouse** accessible to the deploying user
3. **Source tables** in the target catalog/schema:
   - `ai_cost_fact` — billing line items (cost_usd, dbu_quantity, user_identity, endpoint_name, surface, billing_origin_product)
   - `ai_interaction_fact` — per-request telemetry (latency_ms, status_code, tokens, model_canonical, requester)
   - `ai_daily_rollup` — pre-aggregated daily endpoint x model metrics (cost_allocation_method = 'matched')
   - `genie_daily_metrics` — Genie orchestration usage (sql_executions, successful_queries, distinct_users, avg_query_duration_ms)

## Quick Start

```bash
# 1. Clone this repo
git clone <repo-url> && cd ai-observability-dashboard

# 2. Update targets in databricks.yml for your workspace + catalog/schema

# 3. Validate
databricks bundle validate

# 4. Deploy
databricks bundle deploy -t dev

# 5. Open
databricks bundle open ai_observability -t dev
```

## Customer Deployment

Add a new target block per customer:

```yaml
targets:
  acme_corp:
    mode: production
    workspace:
      host: https://<workspace>.azuredatabricks.net
    variables:
      catalog: "acme_catalog"
      schema: "ai_observability"
      warehouse_id: "<their-warehouse-id>"
```

Then: `databricks bundle deploy -t acme_corp`

## How Portability Works

All dataset queries use **unqualified** table names (e.g. `FROM ai_cost_fact`).
The bundle resource injects the correct catalog/schema at deploy time via:

```yaml
dataset_catalog: ${var.catalog}
dataset_schema: ${var.schema}
```

## Regenerating the Dashboard JSON

```bash
# Export from live dashboard
databricks bundle generate dashboard \
  --existing-id 01f189e0ca2a1ac4b761386a5f92098f \
  --key ai_observability

# Strip catalog.schema prefixes for portability
python scripts/strip_catalog_prefix.py src/ai_observability.lvdash.json
```

## Project Structure

```
├── databricks.yml              # Bundle config + variables + targets
├── resources/
│   └── dashboard.yml           # Dashboard resource definition
├── src/
│   └── ai_observability.lvdash.json  # Generated dashboard JSON (portable)
│       └── ai_observability.lvdash.json   # Serialized dashboard (portable)
├── scripts/
│   └── strip_catalog_prefix.py # Makes SQL queries env-agnostic
└── README.md
```

## Dashboard Pages

| Page | Content |
| --- | --- |
| AI Cost and Operations | KPIs (cost, DBU, endpoints, users), weekly spend trend, top endpoints, WoW movers, user distribution |
| AI Operations and Adoption | Request volume, latency, error rates, model leaderboard, traffic by surface |
| Genie | Genie-specific cost/adoption, success rate, per-surface breakdown |
| Unit Economics | Cost-per-request, cost-per-1M-tokens, endpoint economics table |
| Global Filters | Date range, user, workspace, surface (cross-page) |

## Changelog

### v1.1.0 — Data Integrity Fixes (2026-08-03)

Critical corrections identified during front-to-back audit:

| Dataset | Fix |
| --- | --- |
| AI Cost (SQL) | Added `billing_origin_product != 'GENIE'` to match stated scope; removed `COALESCE(user_identity, 'unknown')` phantom user |
| AI Operations (SQL) | Added `surface != 'platform_internal'` — excluded 12.5M internal orchestration calls (99.3% of rows) |
| Error Rate by Model | Added `surface != 'platform_internal'` |
| Daily Volume (Top 5 Models) | Added `surface != 'platform_internal'` in both CTE and main query |
| Unit Economics (Matched) | Replaced naive `AVG(latency_p95_ms)` with request-weighted `SUM(p95 * requests) / SUM(requests)` |
| Genie Daily Metrics | Renamed `distinct_users` → `user_sessions` to reflect pre-aggregation overcounting |
| Genie KPI (Accurate) [NEW] | True `COUNT(DISTINCT user_identity)` from `ai_cost_fact` — fixes 2-4× overcount |

**Impact:** KPI "Active Users" dropped from 809 → ~517 (removed Genie bleed + phantom 'unknown'). Genie "Users" dropped from 1,164 → 384 (true distinct vs summed pre-agg). Operations "Total Requests" dropped from 12.6M → ~92K (user-facing only).

### v1.2.0 — Genie/Genie Code Split + Global Filter Consistency (2026-08-03)

**Page restructure:**
- Renamed "Genie" → **"Genie Spaces"** (scoped to `genie_spaces`, `genie_one`, `genie_other`)
- Created **"Genie Code"** page (scoped to `surface = 'genie_code'`) — AI coding assistant cost, users, DBU, top users, daily active users

**Global date filter now controls ALL widgets:**

| Dataset | Before | Now |
| --- | --- | --- |
| Genie Code KPI / Daily | Hardcoded 90d | Global filter (`:date_range` param) |
| Genie Spaces KPI (Accurate) | Hardcoded 90d | Global filter |
| Cost User Distribution | Hardcoded 30d | Global filter |
| Genie User Distribution | Hardcoded 30d | Global filter |
| Error Rate by Model | Hardcoded 90d | Global filter |
| Cost per 1M Tokens | No date filter | Global filter |

**Intentionally exempt (labeled in UI):**
- WoW Cost Movers — fixed rolling 14d window (last 7d vs prior 7d), clearly labeled in widget description

**New datasets:** `genie_code_kpi`, `genie_code_daily`
**Updated datasets:** `genie_kpi_accurate`, `genie_metrics`, `genie_success_rate`, `cost_user_dist`, `genie_user_dist`, `error_by_model`, `cost_per_token`
