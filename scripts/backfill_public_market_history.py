#!/usr/bin/env python3
"""Backfill verifiable public daily market history. Never invent/fill observations."""
import csv
import datetime as dt
import io
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

PATH = pathlib.Path("public/market-history.json")
TODAY = dt.datetime.now(dt.timezone.utc).date()
# Do not insert today's intraday FX or index quote into the verified daily archive.
# Refresh workflow advances the official cutoff once dates are properly validated.
ARCHIVE_CUTOFF = dt.date.fromisoformat(json.loads(PATH.read_text(encoding="utf-8"))["cutoff"])
START = TODAY - dt.timedelta(days=620)
UA = {"User-Agent": "Mozilla/5.0 JenbaoMarketHistory/1.0", "Accept": "application/json,text/csv,*/*"}
FRED = {"hyOas": "BAMLH0A0HYM2", "us10yYield": "DGS10",
        "us10y2ySpread": "T10Y2Y", "fedFundsEffective": "DFF"}

def download(url):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=24) as response:
                return response.read().decode("utf-8-sig")
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(str(last))

def number(value):
    try:
        if value is None or str(value).strip() in ("", ".", "-", "null"):
            return None
        n = float(str(value).replace(",", "").replace("+", "").strip())
        return round(n, 7) if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def insert(rows, key, date, value):
    if not isinstance(date, str) or len(date) != 10 or value is None:
        return
    try:
        d = dt.date.fromisoformat(date)
    except ValueError:
        return
    if d > TODAY or d > ARCHIVE_CUTOFF:
        return
    # Existing verified data wins on overlapping dates.
    rows.setdefault(date, {}).setdefault(key, value)

def fred(rows, key, ticker):
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id="
           + urllib.parse.quote(ticker) + "&cosd=" + START.isoformat())
    data = list(csv.DictReader(io.StringIO(download(url))))
    total = 0
    for row in data:
        d = row.get("DATE") or row.get("observation_date")
        val = number(row.get(ticker))
        if val is not None:
            insert(rows, key, d, val)
            total += 1
    print("FRED", ticker, "downloaded", total)

def yahoo_fx(rows):
    start = int(dt.datetime.combine(START, dt.time.min, dt.timezone.utc).timestamp())
    end = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).timestamp())
    query = urllib.parse.urlencode({"period1": start, "period2": end, "interval": "1d"})
    u = "https://query1.finance.yahoo.com/v8/finance/chart/TWD=X?" + query
    result = json.loads(download(u))["chart"]["result"][0]
    stamps = result.get("timestamp", [])
    close = result["indicators"]["quote"][0]["close"]
    for t, v in zip(stamps, close):
        insert(rows, "usdtwd", dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), number(v))
    print("Yahoo TWD=X downloaded", len(stamps))

def twse_month(rows, month):
    # Taiwan index daily closing level, with explicit official date conversion.
    u = "https://www.twse.com.tw/exchangeReport/FMTQIK?" + urllib.parse.urlencode(
        {"response": "json", "date": month.strftime("%Y%m%d")})
    obj = json.loads(download(u))
    fields = obj.get("fields") or []
    idx = next((i for i, f in enumerate(fields) if "發行量加權股價指數" in str(f)), None)
    if idx is None:
        raise ValueError("FMTQIK index field missing; won't guess column")
    count = 0
    for record in obj.get("data", []):
        try:
            a, b, c = [int(x) for x in str(record[0]).split("/")]
            d = dt.date(a + 1911, b, c).isoformat()
            val = number(record[idx])
            insert(rows, "taiex", d, val)
            count += val is not None
        except Exception:
            continue
    print("TWSE", month.strftime("%Y-%m"), count)

def main():
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    rows = {}
    for r in payload.get("rows", []):
        date = r.get("date")
        if date:
            rows[date] = {k: v for k, v in r.items() if k != "date" and v is not None}
    original = {k: sum(k in r for r in rows.values()) for k in payload["units"]}
    errors = []
    for key, series in FRED.items():
        try:
            fred(rows, key, series)
        except Exception as exc:
            errors.append(f"{key}: {exc}")
    try:
        yahoo_fx(rows)
    except Exception as exc:
        errors.append(f"usdtwd: {exc}")
    month = START.replace(day=1)
    while month <= TODAY:
        try:
            twse_month(rows, month)
        except Exception as exc:
            errors.append(f"taiex {month}: {exc}")
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    # Preserve all historical points (no 20/60/120/240-day retention cutoff).
    payload["rows"] = [{"date": day, **rows[day]} for day in sorted(rows)]
    for key in payload["units"]:
        series = [(day, r[key]) for day, r in sorted(rows.items()) if key in r and number(r[key]) is not None]
        stat = payload.setdefault("stats", {}).setdefault(key, {})
        if series:
            stat.update(count=len(series), first=series[0][0], last=series[-1][0],
                        lastValue=series[-1][1])
            stat["status"] = "ready" if len(series) >= 240 else "partial"
        else:
            stat.update(count=0, status="partial")
    payload["generatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    payload["backfillAudit"] = {
        "targetObservations": 240, "collectedAt": payload["generatedAt"],
        "before": original, "after": {k: payload["stats"][k]["count"] for k in payload["units"]},
        "unverifiedOrUnavailable": errors,
        "notes": ["Existing data retained on overlapping dates", "No forward filling or interpolating",
                  "TWSE market margin and foreign flows require independently validated column mappings",
                  "Exclude-ETF margin maintenance must only be filled from verified same-definition sources"]
    }
    # Atomic replace only after valid JSON assembled, retaining the original if no gains.
    gains = sum(max(0, payload["stats"][k]["count"] - original[k]) for k in original)
    print(json.dumps(payload["backfillAudit"], ensure_ascii=False))
    if gains:
        temp = PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(PATH)
        print("Saved additional confirmed points:", gains)
    else:
        print("No new verified observations; original untouched")

if __name__ == "__main__":
    main()
