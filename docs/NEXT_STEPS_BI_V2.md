# Next Steps — BI Platform V2

## Goal

Evolve the working BI V2 foundation into a full self-service BI platform capable of creating user-defined analytical models, similar in spirit to Power BI or Excel, while preserving:

- RBAC;
- performance;
- auditability;
- data correctness;
- semantic consistency;
- query safety.

---

## Immediate Priority: Semantic Layer + Query Builder

### 1. Semantic Layer SQL

Create enriched semantic views:

- `mart.v_positions_current_enriched`
- `mart.v_positions_daily_enriched`
- `mart.v_positions_history_enriched`
- `mart.v_profitability_enriched`
- `mart.v_accounts_enriched`
- `mart.v_advisors_enriched`

These views should join facts and dimensions so the frontend can analyze by:

- account;
- client;
- advisor;
- product;
- asset/ticker;
- business date;
- market;
- submarket;
- values;
- performance indicators.

---

### 2. Dataset Catalog Expansion

Add datasets:

- `positions_current`
- `positions_daily`
- `positions_history`
- `profitability_history`
- `accounts`
- `advisors`

Keep the existing `positions` dataset as a backward-compatible alias to current positions or deprecate it gradually.

---

### 3. Field Catalog Expansion

For each dataset, register fields with:

- `field_key`;
- `source_column`;
- `display_name`;
- `data_type`;
- `semantic_type`;
- default aggregation;
- filter flag;
- group flag;
- sort flag;
- format mask;
- ordinal.

---

### 4. API Query Engine

Expand `/datasets/query` to support:

- multiple dimensions;
- multiple measures;
- advanced filters;
- sorting;
- pagination;
- row limits;
- safe calculated fields;
- query logging;
- RBAC filtering.

Important rule:

```text
Never allow raw SQL from the frontend.
```

---

### 5. Formula Builder

Implement a safe expression layer with whitelist functions:

- `sum`
- `avg`
- `min`
- `max`
- `count`
- `count_distinct`
- `safe_divide`
- `coalesce`
- `abs`
- `round`

Example formulas:

```text
Result / Net Value
Revenue / AUM
Average Result %
```

---

### 6. Frontend Self-Service Builder

Add:

- dataset selector;
- fields panel;
- drag/drop dimensions;
- drag/drop measures;
- widget creation modal;
- widget edit modal;
- delete widget;
- delete dashboard/model;
- edit dashboard/model;
- filter panel;
- formula editor;
- pivot/table visual;
- chart visual selector;
- current vs. daily vs. history toggle;
- resize/reposition widgets.

---

### 7. Governance and Safety

Implement:

- query limits;
- timeout protection;
- audit logs;
- RBAC enforcement in every endpoint;
- no unrestricted SQL;
- data freshness indicators;
- scheduler status panel;
- worker status panel;
- last successful refresh display;
- query execution history.

---

## Important Architectural Rules

1. Keep the legacy portal running until V2 is fully validated.
2. Do not mix current positions with historical positions in the same default dataset.
3. Store raw data as received.
4. Normalize numbers into canonical database numeric format.
5. Apply Brazilian or local display formatting only at frontend/export level.
6. Keep one active mart snapshot per report per business day.
7. Do not commit secrets, tokens, passwords, worker keys or scheduler headers.
8. Keep semantic views stable for BI consumers.
9. Log all user-generated query executions.
10. Make delete operations auditable and reversible where possible.

---

## Suggested Development Order

### Step 1 — Backend Semantic Query Engine

- Add enriched views.
- Expand dataset catalog.
- Expand field catalog.
- Implement safe query builder.
- Add filters, grouping and measures.

### Step 2 — Frontend Builder

- Build dataset selector.
- Build field selector.
- Build widget editor.
- Add delete actions.
- Add filter panel.
- Add chart/table selector.

### Step 3 — Governance

- Query audit logs.
- RBAC scoping.
- Timeout/limit handling.
- Data freshness panel.
- Worker history screen.

### Step 4 — UX Refinement

- Save multiple models.
- Add Excel-like tabs.
- Add model duplication.
- Add widget resize/reposition.
- Add export options.
