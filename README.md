# TASMAC List Finder

**Last updated:** 12 May 2026, 13:12 IST

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

## Estimated Google Maps cost

These figures are **rough, non-binding estimates** for a **full Tamil Nadu run** like the one in this repository. They are **not invoices**, **not guarantees**, and **not legal or financial advice**. Actual billing depends on your Google Cloud billing region, monthly free caps, pagination, retries, and how many places Google returns in each Nearby Search response.

The scanner uses the **legacy Places Nearby Search** API. Google bills **each HTTP request** (including pagination) and may also bill **Contact Data** and **Atmosphere Data** for places returned in those responses.

### What a full run typically does

| Input | Value in this repository |
| --- | ---: |
| Shops scanned | 2,220 |
| Minimum Nearby Search calls | 38,700 |
| Stored proximity hits | 126,335 |
| Tamil Nadu-only shops (filtered summary) | 1,940 |
| Tamil Nadu-only stored proximity hits | 102,266 |

### Estimated total cost per full run

| Billing region | Low | Mid | High |
| --- | ---: | ---: | ---: |
| India | ~$400 | ~$600 | ~$875 |
| Global (non-India) | ~$2,300 | ~$3,100 | ~$3,900 |

The **mid** row is a reasonable planning number for a first full-state run. A **Tamil Nadu-only filtered slice** of that work is only a subset of the billed scan; do not treat it as a separate invoice line.

Check **Google Cloud Console → Billing → Reports** for the amount you were actually charged.

## License

### Project code and documentation

The scanner scripts, filter script, and documentation in this repository are released under the [MIT License](LICENSE), unless a file states otherwise.

### Python dependencies

Third-party packages in `requirements.txt` are distributed under their own licenses. Review each package before redistribution or commercial use:

| Package | Typical license |
| --- | --- |
| `aiohttp` | Apache License 2.0 |
| `aiofiles` | Apache License 2.0 |
| `tqdm` | MIT / Mozilla Public License 2.0 (dual-licensed) |
| `uvloop` | MIT / Apache License 2.0 (dual-licensed) |

### Google Maps Platform data

Place names, coordinates, addresses, and Maps URLs in the generated datasets come from **Google Maps Platform**. They are **not** official records of the Government of Tamil Nadu, TASMAC, or any licensing authority.

Use of Google data is governed by the [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms) and the [Places API policies](https://developers.google.com/maps/documentation/places/web-service/policies). You are responsible for API keys, billing, quotas, attribution, caching rules, and any restrictions on storing or republishing Google content.

## Legal and compliance notice

Read this section carefully if you are a government body, researcher, journalist, advocate, business operator, or member of the public reviewing liquor-shop proximity in Tamil Nadu.

### No government affiliation

This repository is an **independent open-source research project**. It is **not** affiliated with, endorsed by, commissioned by, or operated on behalf of the **Government of Tamil Nadu**, **TASMAC**, the **Tamil Nadu State Marketing Corporation**, or any other public authority.

References to government wine shops, TASMAC, or Tamil Nadu in the code and datasets describe search targets and public map listings. They do **not** imply official status, authorization, or approval.

### Research output, not legal findings

The outputs are **automated proximity reports** based on third-party map data and a simplified Tamil Nadu boundary. They are **not** court findings, statutory notices, excise determinations, or proof that any shop violates any law, rule, government order, licence condition, or court order.

A flagged row means the script found a mapped place within the configured radius. It does **not** by itself establish illegality, licence breach, or the exact distance required by any statute, rule, notification, or court direction.

### Regulatory context in Tamil Nadu

Tamil Nadu liquor retail is a regulated subject. Rules, licence conditions, prohibited locations, enforcement practice, and court interpretations can change and may depend on facts this project does not collect.

Anyone using these files for policy, enforcement, litigation, licensing, journalism, or investment decisions should **verify locations, distances, licence status, and the applicable legal text with primary sources and qualified professionals** before acting.

### Data limitations

- Google listings can be incomplete, outdated, duplicated, mislabeled, or misplaced.
- Search keywords and place types can miss valid shops or include unrelated businesses.
- The 500 m check radius is a **project setting**, not a statement of the distance required by law.
- The Tamil Nadu boundary is a **simplified polygon** for statewide scanning and filtering.
- Border areas can include or exclude locations near Kerala, Karnataka, Andhra Pradesh, Telangana, and Puducherry.
- Dense cities can produce large duplicate or overlapping counts across categories.

### Personal and business information

Datasets can contain business names, addresses, coordinates, and links to public map pages. Handle them responsibly. Do not use them for harassment, doxxing, unauthorised surveillance, or targeted abuse of shop staff, worshippers, students, or residents.

### Excise, licensing, and publication

This project does **not** grant permission to sell, serve, advertise, or distribute liquor. It does **not** replace excise licences, local approvals, or compliance with applicable central and state laws, including excise, shop-and-establishment, municipal, educational-institution, and religious-institution related requirements.

If you republish the datasets or derived work, make clear that the material is **research output**, identify the Google Maps source where required, and comply with Google’s terms and any applicable Indian law on maps, data use, and publication.

### No warranty

THE SOFTWARE AND DATASETS ARE PROVIDED **"AS IS"**, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, OR NON-INFRINGEMENT.

To the fullest extent permitted by law, the authors and contributors are **not liable** for any direct, indirect, incidental, special, consequential, or punitive damages, or for any decisions made from the software or datasets, including regulatory, financial, reputational, or enforcement outcomes.

### Questions from public authorities

Government agencies reviewing this repository may contact the repository owner through GitHub. This project is offered in good faith for **transparency and public-interest research**. It should be read together with primary legal sources and verified field or official records, not treated as an official government dataset.

## Notes

- Coordinates and place metadata come from Google Maps. Treat the outputs as research aids, not legal findings.
- The Tamil Nadu boundary is a simplified polygon for statewide scanning and filtering.
- Respect Google Maps Platform terms of use and rate limits when re-running the scanner.
