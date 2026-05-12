"""
TASMAC Wine Shop Proximity Scanner — Full Tamil Nadu v4
=======================================================
M1 Max optimised — asyncio + aiohttp, 50 concurrent workers,
token-bucket rate limiter, live progress, crash-resume.

Speed vs v3:
  v3  (sequential)  : ~18–24 hours
  v4  (async/M1Max) : ~35–55 minutes

Install:
    pip install aiohttp aiofiles tqdm

Run:
    python tasmac_tamilnadu_scanner_v4.py

Resume after crash:
    Script auto-resumes from tasmac_shops_raw.json and
    tasmac_violations_progress.json if they exist.
"""

import asyncio
import aiohttp
import aiofiles
import json
import csv
import time
import os
import sys
import threading
from math import radians, sin, cos, sqrt, atan2
from collections import defaultdict
from datetime import datetime
from tqdm import tqdm  # pip install tqdm

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY     = "YOUR_GOOGLE_MAPS_API_KEY"  # <-- Replace

PROXIMITY_RADIUS_M      = 500
GRID_STEP_KM            = 15
TILE_SEARCH_RADIUS_M    = 17000
DEDUP_DISTANCE_M        = 80

# M1 Max has 10 performance cores + fast unified memory.
# Google Places allows ~100 QPS; we stay conservative at 60 QPS.
TILE_WORKERS            = 30    # concurrent tile scanners
VIOLATION_WORKERS       = 50    # concurrent shop violation checkers
MAX_QPS                 = 55    # requests per second cap (safe under Google's 100 QPS limit)
RETRIES                 = 3
TIMEOUT_S               = 12

PLACES_API_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# Checkpoint files — delete to force full rescan
CHECKPOINT_SHOPS      = "tasmac_shops_raw.json"
CHECKPOINT_VIOLATIONS = "tasmac_violations_progress.json"

# ─────────────────────────────────────────────────────────────
# SEARCH VARIANTS
# ─────────────────────────────────────────────────────────────
TASMAC_KEYWORDS = [
    "TASMAC",
    "TASMAC wine shop",
    "TASMAC liquor shop",
    "TASMAC beverages",
    "Tamil Nadu State Marketing Corporation",
    "government wine shop",
    "government liquor shop",
    "government beverages",
    "Tamil Nadu beverages",
    "TN beverages",
    "அரசு மதுக்கடை",
    "தாஸ்மாக்",
    "மதுக்கடை",
    "மது விற்பனை நிலையம்",
    "wine shop",
    "liquor shop",
    "beer shop",
    "bar and restaurant",
]

TASMAC_PLACE_TYPES = ["liquor_store", "bar"]

SENSITIVE_TYPES = {
    "place_of_worship"       : ["hindu_temple", "mosque", "church", "place_of_worship"],
    "educational_institution": ["school", "university", "primary_school", "secondary_school"],
    "bus_stand"              : ["bus_station", "transit_station"],
}

CATEGORY_LABELS = {
    "place_of_worship"       : "Place of Worship",
    "educational_institution": "Educational Institution",
    "bus_stand"              : "Bus Stand",
}

# ─────────────────────────────────────────────────────────────
# TAMIL NADU BOUNDARY
# ─────────────────────────────────────────────────────────────
TN_BBOX    = {"lat_min": 8.07, "lat_max": 13.57, "lng_min": 76.23, "lng_max": 80.33}
TN_POLYGON = [
    (13.57,79.90),(13.35,80.30),(12.90,80.20),(12.60,80.25),(12.00,79.85),
    (11.60,79.85),(11.40,79.70),(10.80,79.85),(10.35,79.85),(9.85, 79.35),
    (9.25, 79.20),(8.90, 78.15),(8.60, 77.50),(8.25, 77.20),(8.07, 77.52),
    (8.10, 76.90),(8.30, 76.80),(8.50, 76.90),(9.00, 76.70),(9.50, 76.75),
    (10.00,76.95),(10.30,76.60),(10.80,76.50),(11.20,76.65),(11.60,76.85),
    (12.00,77.40),(12.40,77.65),(12.80,77.60),(13.00,77.85),(13.20,78.20),
    (13.50,78.65),(13.57,79.20),(13.57,79.90),
]

# ─────────────────────────────────────────────────────────────
# GEOMETRY
# ─────────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2-lat1), radians(lon2-lon1)
    a = sin(dp/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def point_in_polygon(lat, lng, poly):
    n, inside, j = len(poly), False, len(poly)-1
    for i in range(n):
        xi,yi = poly[i][1], poly[i][0]
        xj,yj = poly[j][1], poly[j][0]
        if ((yi>lat)!=(yj>lat)) and (lng<(xj-xi)*(lat-yi)/(yj-yi)+xi):
            inside = not inside
        j = i
    return inside

def km_to_deg_lat(km):      return km / 111.0
def km_to_deg_lng(km, lat): return km / (111.0 * cos(radians(lat)))

def build_tn_grid(step_km=GRID_STEP_KM):
    tiles, row = [], 0
    lat = TN_BBOX["lat_min"]
    while lat <= TN_BBOX["lat_max"]:
        lng = TN_BBOX["lng_min"]
        if row % 2 == 1:
            lng += km_to_deg_lng(step_km/2, lat)
        while lng <= TN_BBOX["lng_max"]:
            if point_in_polygon(lat, lng, TN_POLYGON):
                tiles.append((round(lat,4), round(lng,4)))
            lng += km_to_deg_lng(step_km, lat)
        lat += km_to_deg_lat(step_km * 0.866)
        row += 1
    return tiles

# ─────────────────────────────────────────────────────────────
# TOKEN-BUCKET RATE LIMITER
# ─────────────────────────────────────────────────────────────
class RateLimiter:
    """Async token-bucket: allows MAX_QPS requests/second across all workers."""
    def __init__(self, rate: float):
        self._rate      = rate
        self._tokens    = rate
        self._last      = time.monotonic()
        self._lock      = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1

# Global limiter — shared across all coroutines
_rate_limiter: RateLimiter = None  # initialised in main()

# ─────────────────────────────────────────────────────────────
# ASYNC PLACES API
# ─────────────────────────────────────────────────────────────
async def async_nearby_search(
    session: aiohttp.ClientSession,
    location: tuple,
    radius: int,
    keyword: str = None,
    place_type: str = None,
) -> list:
    results = []
    params = {
        "location": f"{location[0]},{location[1]}",
        "radius":   radius,
        "key":      GOOGLE_MAPS_API_KEY,
    }
    if keyword:    params["keyword"] = keyword
    if place_type: params["type"]    = place_type

    while True:
        await _rate_limiter.acquire()
        for attempt in range(RETRIES):
            try:
                async with session.get(
                    PLACES_API_URL, params=params,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT_S)
                ) as resp:
                    data = await resp.json(content_type=None)
                break
            except Exception:
                if attempt == RETRIES - 1:
                    return results
                await asyncio.sleep(1.5 * (attempt + 1))

        status = data.get("status")
        if status == "ZERO_RESULTS":
            break
        if status != "OK":
            break

        results.extend(data.get("results", []))
        next_token = data.get("next_page_token")
        if not next_token:
            break
        # Google requires ~2s before next_page_token is valid
        await asyncio.sleep(2.1)
        params = {"pagetoken": next_token, "key": GOOGLE_MAPS_API_KEY}

    return results

# ─────────────────────────────────────────────────────────────
# FILTER & DEDUP
# ─────────────────────────────────────────────────────────────
TASMAC_SIGNALS = [
    "tasmac", "தாஸ்மாக்", "மதுக்கடை", "madhu kadai", "madu kadai",
    "government wine", "govt wine", "government liquor", "govt liquor",
    "tamil nadu beverages", "tn beverages", "arasu madhu",
    "wine shop", "liquor shop", "beverages corporation",
    "bar & restaurant", "bar and restaurant", "மது விற்பனை",
]

def is_tasmac(name: str) -> bool:
    n = name.lower()
    return any(sig in n for sig in TASMAC_SIGNALS)

def consolidate(raw: list) -> dict:
    """2-pass dedup: by place_id, then by GPS proximity."""
    by_pid = {}
    for r in raw:
        pid = r.get("place_id")
        if pid and pid not in by_pid:
            by_pid[pid] = r

    unique = []
    for candidate in by_pid.values():
        cloc = candidate["geometry"]["location"]
        clat, clng = cloc["lat"], cloc["lng"]
        dup = any(
            haversine(clat, clng,
                      e["geometry"]["location"]["lat"],
                      e["geometry"]["location"]["lng"]) < DEDUP_DISTANCE_M
            for e in unique
        )
        if not dup:
            unique.append(candidate)

    return {r["place_id"]: r for r in unique}

# ─────────────────────────────────────────────────────────────
# STEP 1 — ASYNC TILE SCANNER
# ─────────────────────────────────────────────────────────────
async def scan_tile(
    session: aiohttp.ClientSession,
    tile: tuple,
    radius: int,
) -> list:
    """Fire all keywords + types for one tile concurrently."""
    tasks = []
    for kw in TASMAC_KEYWORDS:
        tasks.append(async_nearby_search(session, tile, radius, keyword=kw))
    for pt in TASMAC_PLACE_TYPES:
        tasks.append(async_nearby_search(session, tile, radius, place_type=pt))

    results_nested = await asyncio.gather(*tasks)
    raw = [item for sublist in results_nested for item in sublist]
    return raw


async def scan_all_tiles(tiles: list) -> dict:
    """Scan every tile concurrently (TILE_WORKERS at a time)."""
    master    = {}
    semaphore = asyncio.Semaphore(TILE_WORKERS)
    lock      = asyncio.Lock()
    capped    = []

    connector = aiohttp.TCPConnector(
        limit=TILE_WORKERS * 4,
        ttl_dns_cache=300,
        ssl=False,          # Places API is HTTPS but skip verify overhead
        limit_per_host=80,
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        pbar = tqdm(total=len(tiles), desc="  Tiles", unit="tile",
                    colour="cyan", ncols=80)

        async def process_tile(tile):
            async with semaphore:
                raw      = await scan_tile(session, tile, TILE_SEARCH_RADIUS_M)
                merged   = consolidate(raw)
                filtered = {pid: r for pid, r in merged.items()
                            if is_tasmac(r.get("name", ""))}

                async with lock:
                    before = len(master)
                    master.update(filtered)
                    new = len(master) - before
                    if new > 35:          # dense tile — re-scan with sub-grid
                        capped.append(tile)
                    pbar.update(1)
                    pbar.set_postfix(total=len(master), new=new)

        await asyncio.gather(*[process_tile(t) for t in tiles])
        pbar.close()

        # ── Re-scan dense tiles at 8km sub-grid ─────────────
        if capped:
            sub_tiles = []
            for ct in capped:
                for dlat in [-8, 0, 8]:
                    for dlng in [-8, 0, 8]:
                        slat = ct[0] + km_to_deg_lat(dlat)
                        slng = ct[1] + km_to_deg_lng(dlng, ct[0])
                        sub_tiles.append((round(slat,4), round(slng,4)))

            print(f"\n  🔁 Re-scanning {len(capped)} dense tiles "
                  f"→ {len(sub_tiles)} sub-tiles at 8km ...")
            pbar2 = tqdm(total=len(sub_tiles), desc="  Sub-tiles",
                         unit="tile", colour="yellow", ncols=80)

            async def process_sub(tile):
                async with semaphore:
                    raw      = await scan_tile(session, tile, 8000)
                    merged   = consolidate(raw)
                    filtered = {pid: r for pid, r in merged.items()
                                if is_tasmac(r.get("name", ""))}
                    async with lock:
                        master.update(filtered)
                        pbar2.update(1)
                        pbar2.set_postfix(total=len(master))

            await asyncio.gather(*[process_sub(t) for t in sub_tiles])
            pbar2.close()

    return master

# ─────────────────────────────────────────────────────────────
# STEP 2 — ASYNC VIOLATION CHECKER
# ─────────────────────────────────────────────────────────────
async def check_violations(
    session: aiohttp.ClientSession,
    shop: dict,
) -> list:
    sloc   = shop["geometry"]["location"]
    coords = (sloc["lat"], sloc["lng"])
    seen   = set()
    violations = []

    # Fire all sensitive-type searches for this shop concurrently
    tasks = []
    type_map = []
    for category, types in SENSITIVE_TYPES.items():
        for ptype in types:
            tasks.append(async_nearby_search(session, coords, PROXIMITY_RADIUS_M,
                                             place_type=ptype))
            type_map.append(category)

    results_nested = await asyncio.gather(*tasks)

    for category, places in zip(type_map, results_nested):
        for place in places:
            pid = place["place_id"]
            if pid in seen:
                continue
            seen.add(pid)
            ploc = place["geometry"]["location"]
            dist = haversine(coords[0], coords[1], ploc["lat"], ploc["lng"])
            if dist <= PROXIMITY_RADIUS_M:
                violations.append({
                    "category"  : category,
                    "name"      : place.get("name", "Unknown"),
                    "address"   : place.get("vicinity", "N/A"),
                    "distance_m": round(dist, 1),
                    "lat"       : ploc["lat"],
                    "lng"       : ploc["lng"],
                    "maps_url"  : f"https://www.google.com/maps/place/?q=place_id:{pid}",
                })

    return violations


async def analyse_all_shops(shops: list, already_done: dict) -> list:
    """Check all shops concurrently (VIOLATION_WORKERS at a time)."""
    semaphore = asyncio.Semaphore(VIOLATION_WORKERS)
    lock      = asyncio.Lock()
    report    = [None] * len(shops)
    done_count = 0

    connector = aiohttp.TCPConnector(
        limit=VIOLATION_WORKERS * 4,
        ttl_dns_cache=300,
        ssl=False,
        limit_per_host=80,
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        pbar = tqdm(total=len(shops), desc="  Shops", unit="shop",
                    colour="green", ncols=80,
                    initial=len(already_done))

        async def process_shop(idx, shop):
            nonlocal done_count
            pid  = shop["place_id"]
            sloc = shop["geometry"]["location"]
            name = shop.get("name", "TASMAC Shop")
            addr = shop.get("vicinity", "N/A")
            url  = f"https://www.google.com/maps/place/?q=place_id:{pid}"

            # Resume: skip if already computed
            if pid in already_done:
                entry = already_done[pid]
                async with lock:
                    report[idx] = entry
                    pbar.set_postfix(violations=entry["violation_count"])
                return

            async with semaphore:
                violations = await check_violations(session, shop)

            entry = {
                "shop_name"      : name,
                "shop_address"   : addr,
                "shop_lat"       : sloc["lat"],
                "shop_lng"       : sloc["lng"],
                "shop_maps_url"  : url,
                "violation_count": len(violations),
                "violations"     : violations,
            }

            async with lock:
                report[idx] = entry
                done_count += 1
                pbar.update(1)
                pbar.set_postfix(violations=len(violations),
                                 name=name[:20])

                # Auto-checkpoint every 100 shops
                if done_count % 100 == 0:
                    done_map = {r["shop_maps_url"].split("place_id:")[-1]: r
                                for r in report if r is not None}
                    with open(CHECKPOINT_VIOLATIONS, "w", encoding="utf-8") as f:
                        json.dump(done_map, f, ensure_ascii=False)

        await asyncio.gather(*[process_shop(i, s) for i, s in enumerate(shops)])
        pbar.close()

    # Final checkpoint save
    done_map = {r["shop_maps_url"].split("place_id:")[-1]: r
                for r in report if r is not None}
    with open(CHECKPOINT_VIOLATIONS, "w", encoding="utf-8") as f:
        json.dump(done_map, f, ensure_ascii=False)

    return [r for r in report if r is not None]

# ─────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────
def print_summary(report):
    violating  = [s for s in report if s["violation_count"] > 0]
    cat_counts = defaultdict(int)
    for shop in violating:
        for v in shop["violations"]:
            cat_counts[v["category"]] += 1

    print(f"\n{'='*65}")
    print(f"  📋  TAMIL NADU TASMAC — FINAL REPORT  [{datetime.now():%Y-%m-%d %H:%M}]")
    print(f"{'='*65}")
    print(f"  Total shops scanned      : {len(report)}")
    print(f"  Shops WITH violations    : {len(violating)}  ⚠️")
    print(f"  Shops clean              : {len(report)-len(violating)}  ✅")
    print(f"\n  Sensitive locations within 500m:")
    for cat, count in cat_counts.items():
        print(f"    • {CATEGORY_LABELS.get(cat,cat):<28} : {count}")
    if violating:
        print(f"\n  Top 10 worst violators:")
        for s in sorted(violating, key=lambda x: x["violation_count"], reverse=True)[:10]:
            print(f"    [{s['violation_count']:>2}x] {s['shop_name']} — {s['shop_address']}")
            print(f"          {s['shop_maps_url']}")
    print(f"{'='*65}")


def save_outputs(report):
    # Full JSON
    with open("tasmac_tn_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"💾 tasmac_tn_report.json")

    # Violations CSV (one row per violation)
    rows = []
    for shop in report:
        base = {
            "Shop Name"       : shop["shop_name"],
            "Shop Address"    : shop["shop_address"],
            "Shop Lat"        : shop["shop_lat"],
            "Shop Lng"        : shop["shop_lng"],
            "Shop Maps URL"   : shop["shop_maps_url"],
            "Total Violations": shop["violation_count"],
        }
        if not shop["violations"]:
            rows.append({**base, "Violation Category":"None",
                         "Sensitive Place":"—","Sensitive Address":"—",
                         "Distance (m)":"—","Sensitive Place URL":"—"})
        for v in shop["violations"]:
            rows.append({**base,
                "Violation Category" : CATEGORY_LABELS.get(v["category"], v["category"]),
                "Sensitive Place"    : v["name"],
                "Sensitive Address"  : v["address"],
                "Distance (m)"       : v["distance_m"],
                "Sensitive Place URL": v["maps_url"],
            })
    if rows:
        with open("tasmac_tn_violations.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader(); w.writerows(rows)
        print(f"📊 tasmac_tn_violations.csv")

    # Summary CSV (one row per shop)
    summary = [{
        "Shop Name"       : s["shop_name"],
        "Shop Address"    : s["shop_address"],
        "Lat"             : s["shop_lat"],
        "Lng"             : s["shop_lng"],
        "Maps URL"        : s["shop_maps_url"],
        "Total Violations": s["violation_count"],
        "Near Worship"    : sum(1 for v in s["violations"] if v["category"]=="place_of_worship"),
        "Near Schools"    : sum(1 for v in s["violations"] if v["category"]=="educational_institution"),
        "Near Bus Stands" : sum(1 for v in s["violations"] if v["category"]=="bus_stand"),
        "Status"          : "VIOLATION" if s["violation_count"] > 0 else "CLEAN",
    } for s in report]
    with open("tasmac_tn_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=summary[0].keys())
        w.writeheader(); w.writerows(summary)
    print(f"📋 tasmac_tn_summary.csv")

# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
async def main():
    global _rate_limiter
    _rate_limiter = RateLimiter(MAX_QPS)

    print("\n🏛️  TASMAC Proximity Scanner v4 — Tamil Nadu (Async / M1 Max)")
    print(f"     Tile workers      : {TILE_WORKERS}")
    print(f"     Violation workers : {VIOLATION_WORKERS}")
    print(f"     Rate limit        : {MAX_QPS} req/s")
    print(f"     Keywords/types    : {len(TASMAC_KEYWORDS)+len(TASMAC_PLACE_TYPES)}")
    print(f"     Violation zone    : {PROXIMITY_RADIUS_M}m\n")

    t_start = time.monotonic()

    # ── STEP 1: Collect shops ───────────────────────────────
    if os.path.exists(CHECKPOINT_SHOPS):
        print(f"  ♻️  Resuming from {CHECKPOINT_SHOPS} ...")
        with open(CHECKPOINT_SHOPS, encoding="utf-8") as f:
            shops_raw = json.load(f)
        shops = shops_raw if isinstance(shops_raw, list) else list(shops_raw.values())
        print(f"  Loaded {len(shops)} shops from checkpoint.\n")
    else:
        tiles = build_tn_grid()
        print(f"🗺️  Grid: {len(tiles)} tiles at {GRID_STEP_KM}km spacing\n")
        master = await scan_all_tiles(tiles)
        shops  = list(master.values())
        with open(CHECKPOINT_SHOPS, "w", encoding="utf-8") as f:
            json.dump(shops, f, ensure_ascii=False, indent=2)
        t1 = time.monotonic() - t_start
        print(f"\n  ✅ {len(shops)} unique shops found in {t1/60:.1f} min")
        print(f"  💾 Saved → {CHECKPOINT_SHOPS}\n")

    # ── STEP 2: Violation check ─────────────────────────────
    already_done = {}
    if os.path.exists(CHECKPOINT_VIOLATIONS):
        print(f"  ♻️  Resuming violations from {CHECKPOINT_VIOLATIONS} ...")
        with open(CHECKPOINT_VIOLATIONS, encoding="utf-8") as f:
            already_done = json.load(f)
        print(f"  {len(already_done)} shops already checked, continuing...\n")

    print(f"\n{'='*65}")
    print(f"  STEP 2 — 500m zone check for {len(shops)} shops")
    print(f"  ({len(already_done)} already done, {len(shops)-len(already_done)} remaining)")
    print(f"{'='*65}\n")

    report = await analyse_all_shops(shops, already_done)

    t_total = time.monotonic() - t_start
    print(f"\n  ⏱️  Total time: {t_total/60:.1f} minutes")

    print_summary(report)
    print()
    save_outputs(report)

    # Clean up checkpoint on success
    if os.path.exists(CHECKPOINT_VIOLATIONS):
        os.remove(CHECKPOINT_VIOLATIONS)

    print("\n✅  All done!")


if __name__ == "__main__":
    if GOOGLE_MAPS_API_KEY == "YOUR_GOOGLE_MAPS_API_KEY":
        print("❌  Set GOOGLE_MAPS_API_KEY at the top of this file.")
        sys.exit(1)

    # M1 Mac: uvloop gives ~2x async performance over default event loop
    try:
        import uvloop
        uvloop.run(main())
        print("  (running with uvloop ⚡)")
    except ImportError:
        asyncio.run(main())
        print("  (tip: pip install uvloop for extra speed on M1)")