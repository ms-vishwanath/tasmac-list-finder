# TASMAC List Finder

**Last updated:** 12 May 2026, 12:51 IST

Async Python tooling to discover TASMAC and government liquor shops across Tamil Nadu with the Google Places API, then flag proximity violations near places of worship, schools, and bus stands.

The repository includes the scanner, a Tamil Nadu-only summary filter, and the generated datasets from a full-state run.

## What it does

`main.py` tiles Tamil Nadu, searches for liquor shops with multiple English and Tamil keywords, deduplicates nearby results, and checks each shop for sensitive places within 500 m. Progress is checkpointed so a long run can resume after interruption.

`filter_tamilnadu_summary.py` trims the shop summary to Tamil Nadu rows using the same boundary polygon as the scanner, plus address-based state checks to drop obvious out-of-state matches.

## Repository contents

| File | Description |
| --- | --- |
| `main.py` | Full-state async scanner |
| `filter_tamilnadu_summary.py` | Tamil Nadu-only summary filter |
| `requirements.txt` | Python dependencies |
| `tasmac_shops_raw.json` | Raw shop records from discovery |
| `tasmac_tn_report.json` | Full JSON report with per-shop violations |
| `tasmac_tn_summary.csv` | One row per scanned shop |
| `tasmac_tn_summary_tamilnadu_only.csv` | Tamil Nadu-only summary |
| `tasmac_tn_violations.csv` | One row per violation |

## Tamil Nadu snapshot

From `tasmac_tn_summary_tamilnadu_only.csv`:

**102,266** total violations across **1,940** Tamil Nadu shops.

Every shop in that file has at least one violation.

| Category | Count |
| --- | ---: |
| Near worship | 92,354 |
| Near schools | 7,347 |
| Near bus stands | 2,565 |

## Requirements

- Python 3.10+
- A Google Maps Platform API key with Places API access
- Billing enabled on the Google Cloud project used for the key

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set your API key in `main.py`:

```python
GOOGLE_MAPS_API_KEY = "YOUR_GOOGLE_MAPS_API_KEY"
```

## Run the scanner

```bash
python3 main.py
```

Outputs are written to the project root:

- `tasmac_shops_raw.json`
- `tasmac_tn_report.json`
- `tasmac_tn_summary.csv`
- `tasmac_tn_violations.csv`

Delete the checkpoint files listed in `main.py` if you want a full rescan instead of resuming from saved progress.

## Filter Tamil Nadu-only summary rows

```bash
python3 filter_tamilnadu_summary.py
```

Custom paths:

```bash
python3 filter_tamilnadu_summary.py \
  --input tasmac_tn_summary.csv \
  --output tasmac_tn_summary_tamilnadu_only.csv
```

## Notes

- Coordinates and place metadata come from Google Maps. Treat the outputs as research aids, not legal findings.
- The Tamil Nadu boundary is a simplified polygon for statewide scanning and filtering.
- Respect Google Maps Platform terms of use and rate limits when re-running the scanner.
