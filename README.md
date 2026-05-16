# Cloud Report Ingestion API

Public-safe version of a financial report ingestion platform built to automate the collection, storage, normalization and distribution of operational reports for business intelligence workflows.

The project demonstrates how a cloud-based ingestion layer can receive reports through APIs and webhooks, store raw files, keep a latest-report reference, normalize data structures and prepare outputs for SQL databases, dashboards and BI tools.

> This repository is a sanitized public version. It does not contain real credentials, private endpoints, client data, production buckets, internal project IDs or confidential business information.

---

## Overview

Financial and operational teams often depend on recurring reports coming from different APIs, files and systems. When this process is handled manually, it becomes slow, fragile and difficult to audit.

This project was designed as an ingestion layer to centralize those reports and make them available for downstream analysis.

The core idea is simple:

```text
External Report Source
        ↓
API / Webhook Receiver
        ↓
Cloud Run Application
        ↓
Raw File Storage
        ↓
Latest Report Pointer
        ↓
Data Normalization
        ↓
SQL / BI / Dashboard Layer
