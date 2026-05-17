## BI Platform V2

This repository now documents the foundation for a parallel self-service BI platform built on top of the financial report ingestion architecture.

The V2 architecture keeps the legacy portal running while introducing:

- API backend for authentication, datasets, dashboards, tabs, widgets and query execution;
- worker service for mart refresh and daily snapshot management;
- frontend dashboard builder;
- SQL semantic mart;
- RBAC and audit schemas;
- daily snapshot policy for report history;
- smart numeric normalization for financial datasets;
- public-safe documentation for troubleshooting and next steps.

### Current validated capabilities

- login and token-based authentication;
- master-user permission flow;
- dashboard creation;
- tab and widget persistence;
- current-position KPI validation;
- chart rendering from semantic data;
- hourly worker refresh schedule;
- initial dashboard builder interface.

### Next stage

The next development stage is:

```text
Semantic Layer + Self-Service Query Builder
```

Main objectives:

- expand semantic views;
- expand dataset and field catalogs;
- support multiple dimensions and measures;
- support filters, sorting and pagination;
- implement safe calculated fields;
- add widget editing and deletion;
- add dashboard/model deletion;
- implement data freshness and worker status panels.
