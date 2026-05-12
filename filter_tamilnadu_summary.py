#!/usr/bin/env python3
"""Keep only Tamil Nadu shops from tasmac_tn_summary.csv."""

import argparse
import csv
import re
from pathlib import Path

TN_BBOX = {"lat_min": 8.07, "lat_max": 13.57, "lng_min": 76.23, "lng_max": 80.33}
TN_POLYGON = [
    (13.57, 79.90), (13.35, 80.30), (12.90, 80.20), (12.60, 80.25), (12.00, 79.85),
    (11.60, 79.85), (11.40, 79.70), (10.80, 79.85), (10.35, 79.85), (9.85, 79.35),
    (9.25, 79.20), (8.90, 78.15), (8.60, 77.50), (8.25, 77.20), (8.07, 77.52),
    (8.10, 76.90), (8.30, 76.80), (8.50, 76.90), (9.00, 76.70), (9.50, 76.75),
    (10.00, 76.95), (10.30, 76.60), (10.80, 76.50), (11.20, 76.65), (11.60, 76.85),
    (12.00, 77.40), (12.40, 77.65), (12.80, 77.60), (13.00, 77.85), (13.20, 78.20),
    (13.50, 78.65), (13.57, 79.20), (13.57, 79.90),
]
OTHER_STATE_RE = re.compile(
    r"\b(kerala|karnataka|andhra(?:\s+pradesh)?|telangana|puducherry|pondicherry|"
    r"goa|bengaluru|bangalore|hyderabad|kochi|kozhikode|thiruvananthapuram|"
    r"ernakulam|thrissur|kollam|kasaragod|mangalore|mysore|mysuru|vijayawada|"
    r"visakhapatnam|guntur|nellore|anantapur|chittoor|kadapa|kurnool)\b",
    re.IGNORECASE,
)
TAMIL_NADU_TEXT_RE = re.compile(r"tamil\s*nadu|tamilnadu", re.IGNORECASE)


def point_in_polygon(lat, lng, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i][1], poly[i][0]
        xj, yj = poly[j][1], poly[j][0]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def in_tamil_nadu(lat, lng):
    if not (TN_BBOX["lat_min"] <= lat <= TN_BBOX["lat_max"] and TN_BBOX["lng_min"] <= lng <= TN_BBOX["lng_max"]):
        return False
    return point_in_polygon(lat, lng, TN_POLYGON)


def is_tamil_nadu_shop(row):
    text = f"{row.get('Shop Name', '')} {row.get('Shop Address', '')}"
    if OTHER_STATE_RE.search(text):
        return False
    if TAMIL_NADU_TEXT_RE.search(text):
        return True

    try:
        lat = float(row["Lat"])
        lng = float(row["Lng"])
    except (KeyError, TypeError, ValueError):
        return False

    return in_tamil_nadu(lat, lng)


def filter_summary(input_path, output_path):
    with input_path.open(newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {input_path}")

        rows = []
        skipped = 0
        for row in reader:
            if is_tamil_nadu_shop(row):
                rows.append(row)
            else:
                skipped += 1

    with output_path.open("w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="tasmac_tn_summary.csv",
        type=Path,
        help="Source summary CSV",
    )
    parser.add_argument(
        "--output",
        default="tasmac_tn_summary_tamilnadu_only.csv",
        type=Path,
        help="Filtered output CSV",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    kept, skipped = filter_summary(args.input, args.output)
    print(f"Wrote {kept} Tamil Nadu rows to {args.output}")
    print(f"Skipped {skipped} rows outside Tamil Nadu or with invalid coordinates")


if __name__ == "__main__":
    main()
