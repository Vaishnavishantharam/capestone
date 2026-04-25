# Phase 1 — Knowledge Base Ingestion + Retrieval (M1)

This phase mirrors your M1 approach: **approved scheme URLs → ingest → `data/schemes.json` → retrieval**.

## Run

```bash
source .venv/bin/activate
python phase_1/run_ingest.py
python phase_1/run_query.py "exit load"
```

## Notes

- Configure URLs in `data/knowledge/source_urls.json`.
- INDMoney pages may block direct scraping; the ingestor includes a fallback fetch path for prototyping.

