#!/usr/bin/env python3
"""
Strip fully-qualified catalog.schema prefixes from dashboard SQL queries
to make the .lvdash.json portable across environments.

Usage:
    python strip_catalog_prefix.py src/dashboards/ai_observability.lvdash.json

The bundle's dataset_catalog / dataset_schema resource settings will inject
the correct catalog.schema at deploy time.
"""
import json
import re
import sys
from pathlib import Path

# Tables to un-qualify (add more if the dashboard evolves)
TABLES = [
    "ai_cost_fact",
    "ai_interaction_fact",
    "ai_daily_rollup",
    "genie_daily_metrics",
]

# Expected pages in the exported dashboard
EXPECTED_PAGES = [
    "AI Cost",
    "AI Operations",
    "Genie",
    "Genie Code",
    "Unit Economics",
]

# Pattern: main.ai_observability.table_name -> table_name
PATTERN = re.compile(
    r"\b\w+\.\w+\.(" + "|".join(TABLES) + r")\b",
    re.IGNORECASE,
)


def strip_prefixes(text: str) -> str:
    return PATTERN.sub(r"\1", text)


def validate_fixes(content: str) -> list:
    """Verify that critical v1.1.0+ audit fixes are present."""
    warnings = []
    if "billing_origin_product" not in content:
        warnings.append("GENIE exclusion filter not found in AI Cost dataset")
    if "platform_internal" not in content:
        warnings.append("platform_internal exclusion not found in AI Operations dataset")
    if "genie_kpi_accurate" not in content.lower() and "Genie KPI" not in content:
        warnings.append("Genie KPI (Accurate) dataset not found — user counts may overcount")
    # v1.2.0 checks
    if "genie_code" not in content.lower():
        warnings.append("Genie Code page/dataset not found — Genie/Genie Code split missing")
    if "date_range" not in content:
        warnings.append(":date_range parameter not found — global filter bindings may be missing")
    # Check page structure
    for page in EXPECTED_PAGES:
        if page not in content:
            warnings.append(f"Expected page '{page}' not found in export")
    return warnings


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-lvdash.json>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    content = path.read_text(encoding="utf-8")
    updated = strip_prefixes(content)

    # Verify still valid JSON
    json.loads(updated)

    # Validate v1.1.0 audit fixes are present
    warnings = validate_fixes(updated)
    for w in warnings:
        print(f"  WARNING: {w}", file=sys.stderr)

    path.write_text(updated, encoding="utf-8")
    print(f"Done. Stripped catalog.schema prefixes from {path}")
    print(f"  Tables made portable: {', '.join(TABLES)}")

    if warnings:
        print(f"\n  {len(warnings)} warning(s) - ensure v1.1.0 fixes were applied before export.")
        sys.exit(1)


if __name__ == "__main__":
    main()
