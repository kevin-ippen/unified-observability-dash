# 🔭 Unified AI Observability Dashboard

A portable [Databricks Asset Bundle](https://docs.databricks.com/dev-tools/bundles/index.html) that drops an executive-ready AI observability dashboard into any workspace. One `bundle deploy` and you've got full visibility into AI/ML spend, model operations, Genie Spaces adoption, and Genie Code usage — no manual setup required.

**Repo:** https://github.com/kevin-ippen/unified-observability-dash

---

## What You Get

Six dashboard pages covering everything an AI platform team needs:

| Page | What's on it |
| --- | --- |
| **AI Cost & Operations** | Total spend, DBU, active users/endpoints, weekly trends, top endpoints, WoW movers, user cost distribution |
| **AI Operations & Adoption** | Request volume, P95 latency, error rates, model leaderboard, traffic by surface |
| **Genie Spaces** | NL→SQL adoption — success rates, SQL executions, query duration, per-user spend (excludes Genie Code) |
| **Genie Code** | AI coding assistant — cost, distinct users, DBU, top users, daily active users |
| **Unit Economics** | Cost-per-request, cost-per-1M-tokens, endpoint economics (matched cost allocation only) |
| **Global Filters** | Date range picker that controls all widgets across all pages |

Every widget respects the global date filter (default: last 90 days). The one exception is WoW Cost Movers, which is intentionally a fixed rolling 14-day window — and it's clearly labeled.

---

## Source Tables

You need these four tables in your target catalog/schema. The dashboard doesn't care what they're called catalog-wise — it uses unqualified names and the bundle injects the right prefix at deploy time.

| Table | What it holds |
| --- | --- |
| `ai_cost_fact` | Billing line items — cost, DBU, user, endpoint, surface, billing product |
| `ai_interaction_fact` | Per-request telemetry — latency, tokens, status codes, model, surface |
| `ai_daily_rollup` | Pre-aggregated daily metrics at endpoint × model grain (includes cost allocation method) |
| `genie_daily_metrics` | Genie usage at date × surface × channel × agent grain — SQL executions, success, duration |

---

## How Portability Works

All dataset SQL in the `.lvdash.json` uses **unqualified table names** (just `FROM ai_cost_fact`, not `FROM main.ai_observability.ai_cost_fact`). At deploy time, the bundle resource config injects the correct catalog and schema:

```yaml
# resources/dashboard.yml
dashboards:
  ai_observability:
    display_name: "AI Observability — Executive View"
    dataset_catalog: ${var.catalog}
    dataset_schema: ${var.schema}
    file_path: ../src/ai_observability.lvdash.json
```

So the same JSON works for `main.ai_observability`, `prod.analytics`, `acme_corp.ai_metrics` — whatever. Just change the variables.

---

## Quick Start

```bash
# Clone it
git clone https://github.com/kevin-ippen/unified-observability-dash.git
cd unified-observability-dash

# Edit databricks.yml — set your workspace host + catalog/schema/warehouse
# (see the variables section and targets block)

# Validate everything looks good
databricks bundle validate

# Deploy
databricks bundle deploy -t dev

# Open in browser
databricks bundle open ai_observability -t dev
```

---

## Adding a New Workspace / Customer

Just add a target block in `databricks.yml`:

```yaml
targets:
  acme_corp:
    mode: production
    workspace:
      host: https://<their-workspace>.azuredatabricks.net
    variables:
      catalog: "acme_catalog"
      schema: "ai_observability"
      warehouse_id: "<their-warehouse-id>"
```

Then: `databricks bundle deploy -t acme_corp` — done. Same dashboard, their data.

---

## Re-exporting from the Live Dashboard

If you make changes in the UI and want to sync back to the bundle:

```bash
# Pull the latest dashboard JSON
databricks bundle generate dashboard \
  --existing-id 01f189e0ca2a1ac4b761386a5f92098f \
  --key ai_observability

# Strip catalog.schema prefixes to keep it portable
python scripts/strip_catalog_prefix.py src/ai_observability.lvdash.json
```

The strip script also validates that critical fixes are intact (Genie exclusion filters, platform_internal exclusion, date_range parameters, correct page structure). If something's missing, it'll warn you and exit non-zero.

---

## Project Structure

```
├── databricks.yml                  # Bundle config, variables, targets
├── resources/
│   └── dashboard.yml               # Dashboard resource definition
├── scripts/
│   └── strip_catalog_prefix.py     # Makes exported JSON portable + validates fixes
├── src/
│   └── ai_observability.lvdash.json  # The actual dashboard (generated)
├── .gitignore
└── README.md
```

---

## Prerequisites

- **Databricks CLI ≥ 0.281.0** — needed for `dataset_catalog`/`dataset_schema` support
- **SQL Warehouse** accessible to the deploying user (serverless or pro)
- **Source tables** populated in the target catalog/schema (see above)

---

## Good to Know

- The dashboard splits Genie into two tabs: **Genie Spaces** (NL→SQL for business users) and **Genie Code** (AI coding assistant for developers). Different products, different personas, different metrics.
- AI Cost page excludes Genie billing (`billing_origin_product != 'GENIE'`) to avoid double-counting. Genie has its own pages.
- Operations page excludes `platform_internal` surface (millions of internal orchestration calls that would drown out user-facing metrics).
- Unit Economics only covers `cost_allocation_method = 'matched'` (~22% of total spend where we can tie cost to telemetry). This is disclosed in the page header.
- WoW Cost Movers is the only widget that ignores the global date filter — it always shows last 7d vs prior 7d. Clearly labeled.
