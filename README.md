# 🔭 Unified AI Observability Dashboard

A portable [Databricks Asset Bundle](https://docs.databricks.com/dev-tools/bundles/index.html) that drops an executive-ready AI observability dashboard into any workspace. One `bundle deploy` and you've got full visibility into AI/ML spend, model operations, Genie adoption, and Genie Code usage — no manual setup required.

**Repo:** https://github.com/kevin-ippen/unified-observability-dash

---

## What You Get

Five dashboard pages covering everything an AI platform team needs:

| Page | What's on it |
| --- | --- |
| **AI Cost & Operations** | Total spend, DBU, active users/endpoints, weekly trends, top endpoints, WoW movers, user cost distribution |
| **AI Operations & Adoption** | Request volume, P95 latency, error rates, model leaderboard, traffic by surface |
| **Genie** | Genie Agents (NL→SQL for business users), Genie One, and other Genie surfaces — success rates, SQL executions, query duration, user spend |
| **Genie Code** | AI coding assistant — cost, distinct users, DBU, top users by spend, daily active users |
| **Unit Economics** | Cost-per-request, cost-per-1M-tokens, endpoint economics (matched cost allocation only) |

A cross-page **global date filter** controls all widgets (default: last 90 days). WoW Cost Movers is the one exception — intentionally fixed at a rolling 14-day window, clearly labeled.

---

## Source Tables

You need these four tables in your target catalog/schema. The dashboard uses unqualified names — the bundle injects the right catalog/schema at deploy time.

| Table | What it holds |
| --- | --- |
| `ai_cost_fact` | Billing line items — cost, DBU, user, endpoint, surface, billing product |
| `ai_interaction_fact` | Per-request telemetry — latency, tokens, status codes, model, surface |
| `ai_daily_rollup` | Pre-aggregated daily metrics at endpoint × model grain (includes cost allocation method) |
| `genie_daily_metrics` | Genie usage at date × surface × channel × agent grain — SQL executions, success, duration |

---

## How Portability Works

All dataset SQL uses **unqualified table names** (just `FROM ai_cost_fact`, not `FROM main.ai_observability.ai_cost_fact`). At deploy time, the bundle injects the correct catalog and schema:

```yaml
# resources/dashboard.yml
dashboards:
  ai_observability:
    display_name: "AI Observability — Executive View"
    dataset_catalog: ${var.catalog}
    dataset_schema: ${var.schema}
    file_path: ../src/ai_observability.lvdash.json
```

Same JSON works for `main.ai_observability`, `prod.analytics`, `acme_corp.ai_metrics` — whatever. Just change the variables.

---

## Quick Start

```bash
git clone https://github.com/kevin-ippen/unified-observability-dash.git
cd unified-observability-dash

# Edit databricks.yml — set your workspace host + catalog/schema/warehouse
databricks bundle validate
databricks bundle deploy -t dev
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

Then `databricks bundle deploy -t acme_corp` — done. Same dashboard, their data.

---

## Re-exporting from the Live Dashboard

If you make changes in the UI and want to sync back:

```bash
databricks bundle generate dashboard \
  --existing-id 01f189e0ca2a1ac4b761386a5f92098f \
  --key ai_observability

python scripts/strip_catalog_prefix.py src/ai_observability.lvdash.json
```

The strip script validates that critical fixes are intact (Genie exclusion, platform_internal filter, date_range params, page structure). Exits non-zero if something's missing.

---

## Project Structure

```
├── databricks.yml                  # Bundle config, variables, targets
├── resources/
│   └── dashboard.yml               # Dashboard resource definition
├── scripts/
│   └── strip_catalog_prefix.py     # Portability + validation
├── src/
│   └── ai_observability.lvdash.json  # The dashboard (generated)
├── .gitignore
└── README.md
```

---

## Prerequisites

- **Databricks CLI ≥ 0.281.0** — needed for `dataset_catalog`/`dataset_schema`
- **SQL Warehouse** — serverless or pro, accessible to deploying user
- **Source tables** populated in target catalog/schema

---

## Good to Know

- Genie is split into two tabs: **Genie** (Agents, One, and other NL→SQL surfaces for business users) and **Genie Code** (AI coding assistant for developers). Different products, different personas, different metrics.
- AI Cost excludes Genie billing (`billing_origin_product != 'GENIE'`) — Genie has its own page.
- Operations excludes `platform_internal` (millions of internal orchestration calls that would drown out user-facing metrics).
- Unit Economics only covers `cost_allocation_method = 'matched'` (~22% of spend where cost ties to telemetry). Disclosed in the page header.
- WoW Cost Movers ignores the global date filter — always last 7d vs prior 7d. Labeled.
- "Genie Spaces" has been rebranded to "Genie Agents" in the product — the dashboard page is just called **Genie** to stay future-proof.
