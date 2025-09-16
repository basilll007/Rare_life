# Rare_life
PubMed → OpenAlex/iCite analytics with Streamlit


**PubMed → OpenAlex/iCite analytics with Streamlit**

Live app: **[https://rarelife-rpqshyrsa42gmgr6t7gcjf.streamlit.app/](https://rarelife-rpqshyrsa42gmgr6t7gcjf.streamlit.app/)**

---

## 🚀 What is this?

* Search PubMed with advanced queries and year filters
* Enrich works with **OpenAlex** + **NIH iCite** citation data
* Analyze trends, authors, institutions, discrepancies
* Explore co-author collaboration networks
* Export cleaned datasets

Built for researchers who prefer results over excuses.

---

## ✨ Features

### Search & Ingest

* **PubMed integration** (ESearch/ESummary/EFetch with polite rate limiting)
* **Bulk processing** up to \~10k articles per run (paged via `WebEnv/QueryKey`)
* **Year-range filtering** and per-year hit counts
* **Robust retries/backoff** and graceful skips

### Citations (Dual Source)

* **OpenAlex `cited_by_count`**
* **iCite `cited_by`**
* Configurable policy: `prefer_openalex | prefer_icite | max | min | reconcile`
* Per-item provenance & discrepancy reporting

### Visual Analytics

* KPIs (total, fetched, coverage %, dual-source %, discrepancy %)
* **Publication trends** by year (interactive)
* **OpenAlex vs iCite** scatter with y=x guide
* **Discrepancy histogram**
* **Top authors / institutions** (bar charts)
* **Co-author network** (PyVis): zoomable, clickable

### Exports

* Download filtered tables as CSV
* JSON output preserved for reproducibility

---

## 🧱 Architecture (high level)

```
PubMed → (PMIDs) → ESummary (+EFetch for missing DOI)
           ↘ year counts
OpenAlex ← pmid:bulk lookup (works) ─→ concepts, authorships, citations
iCite   ← pmids:bulk → cited_by
                 ↓
           Unified citations (policy) + merge
                 ↓
            results.json  →  Streamlit app (visuals + exports)
```

---

## 📦 Repo Layout

```
.
├─ literature_harvester.py   # CLI harvester (backend)
├─ app.py                    # Streamlit dashboard (frontend)
├─ results.json              # Example output (input to app)
├─ requirements.txt          # Minimal deps
└─ README.md                 # You are here
```

**requirements.txt**

```
requests
pandas
plotly
streamlit
networkx
pyvis
```

---

## 🔧 Setup & Run

1. **Create env**

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. **Harvest (optional here if you already have results.json)**

```bash
python literature_harvester.py \
  --query "corona" \
  --start-year 2020 --end-year 2022 \
  --email you@example.com \
  --citations-source both \
  --citations-policy reconcile \
  --outfile results.json
```

3. **Launch dashboard**

```bash
streamlit run app.py
```


## 🧭 Using the App

* **Sidebar**: load `results.json`, filter by year range, pick citation source, search titles/journals.
* **KPIs**: quick sanity check (coverage, discrepancies).
* **Charts**: hover, zoom, and select ranges; all update with filters.
* **Table**: sort columns; expand rows to view authors/affiliations; click DOI links.
* **Network**: inspect clusters; nodes = authors, edge weight = coauthorship count.

---

## 📝 License

MIT
