"""Backfill the complete verifiable history of daily TAIEX market valuations.

Market-cap-weighted P/E among profitable TWSE-listed ordinary shares as
published in ToAlpha's public market history, derived from TWSE daily
per-stock P/E data. Distinct from official TWSE C04001 MONTHLY market P/E.

No interpolation, extrapolation, price-based approximation or zero filling.
"""
import datetime as dt
import json
import math
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CENTER = ROOT / "public" / "market-center-history.json"
OHLC = ROOT / "public" / "index-ohlc-history.json"
SOURCE = "https://toalpha.tw/market"
PATTERN = re.compile(r'\{\\"time\\":\\"(\d{4}-\d{2}-\d{2})\\"[^{}]{0,550}?\\"pe\\":(-?\d+(?:\.\d+)?)')

def main():
    request = urllib.request.Request(
        SOURCE, headers={"User-Agent": "Mozilla/5.0 (Jenbao-Public-Market-Data-Verification/1.0)"}
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise RuntimeError(f"P/E source HTTP {response.status}")
        html = response.read(5_000_000).decode("utf-8", "replace")
    matches = PATTERN.findall(html)
    if len(matches) < 240:
        raise RuntimeError(f"Source contained only {len(matches)} dated P/E readings")
    actual = {}
    for day, raw in matches:
        value = float(raw)
        if not math.isfinite(value) or not (0 < value < 150):
            raise RuntimeError(f"Out-of-bounds market P/E: {day}={raw}")
        if day in actual and not math.isclose(actual[day], value, rel_tol=1e-12):
            raise RuntimeError(f"Conflicting market P/E records for {day}")
        actual[day] = value

    with OHLC.open(encoding="utf-8") as handle:
        official_sessions = json.load(handle)["series"]["taiex"]["rows"]
    target_dates = [row["date"] for row in official_sessions[-240:]]
    if len(target_dates) != 240 or len(set(target_dates)) != 240:
        raise RuntimeError("Incomplete/duplicated 240-session index date key")
    missing = [day for day in target_dates if day not in actual]
    if missing:
        raise RuntimeError(f"P/E source missing {len(missing)} actual recent sessions: {missing[:15]}")
    # Store ALL independently observed daily dates, not just the last 240.
    # Never synthesize records for holidays or dates absent from the source.
    dated = sorted((day, value) for day, value in actual.items()
                   if day <= target_dates[-1])
    if len(dated) < 900:
        raise RuntimeError(f"Historical source shrank unexpectedly: {len(dated)} dated records")
    if any(dated[i][0] >= dated[i+1][0] for i in range(len(dated)-1)):
        raise RuntimeError("Duplicate or unordered P/E dates")
    values = [[day, round(value, 4)] for day, value in dated]
    if values[-1][0] != target_dates[-1]:
        raise RuntimeError("Latest historical P/E observation must match latest confirmed TAIEX date")
    if target_dates[-1] == "2026-11-20" and not math.isclose(values[-1][1],17.1,abs_tol=0.15):
        raise RuntimeError("2026-11-20 P/E is inconsistent with published latest 17.1x")
    last240 = {day: value for day, value in values if day in target_dates}
    if len(last240) != 240:
        raise RuntimeError(f"Only {len(last240)}/240 recent trading days after processing")


    with CENTER.open(encoding="utf-8") as handle:
        market = json.load(handle)
    if "twPeMonthly" not in market:
        old = market.get("twPe")
        if not isinstance(old, list) or not old or len(old) > 24 or any(
            not isinstance(row, list) or len(row) != 2 or not str(row[0]).endswith("-01")
            for row in old
        ):
            raise RuntimeError("Cannot safely archive the existing monthly twPe observations")
        market["twPeMonthly"] = old
    # Refuse silent changes to previously verified daily history.
    prior_daily = market.get("twPe", [])
    if len(prior_daily) >= 240:
        changed = [(d, v, dict(values).get(d)) for d, v in prior_daily
                   if d in dict(values) and not math.isclose(v,dict(values)[d],abs_tol=0.00011)]
        if changed:
            raise RuntimeError(f"Previously verified P/E readings changed; review revisions first: {changed[:8]}")
    # Do not mix the official monthly/old MacroMicro series with daily derived P/E.
    market["twPe"] = values
    market["twPeSource"] = {
        "source": "ToAlpha publicly reported daily market P/E, computed from TWSE daily individual stock P/E",
        "url": SOURCE,
        "frequency": "daily_trading_sessions",
        "methodology": "Profitable TWSE-listed ordinary shares, market-cap-weighted; excludes loss-making companies",
        "official_twse_monthly": False,
        "archived_monthly_series": "twPeMonthly",
        "last_observed_date": target_dates[-1],
        "first_observed_date": target_dates[0],
        "observations": len(values),
        "last_240_sessions_verified": 240,
        "missing_sessions": 0
    }
    rendered = json.dumps(market, ensure_ascii=False, separators=(",", ":")) + "\n"
    before = CENTER.read_text(encoding="utf-8")
    if before != rendered:
        CENTER.write_text(rendered, encoding="utf-8")
    with CENTER.open(encoding="utf-8") as handle:
        verified = json.load(handle)
    assert verified["twPe"] == values
    assert len(verified["twPe"]) >= 900
    assert len({d for d, _ in verified["twPe"]}) == len(verified["twPe"])
    assert all(d in dict(verified["twPe"]) for d in target_dates)
    assert len(verified["twPeMonthly"]) >= 2
    assert verified["twPeSource"]["missing_sessions"] == 0
    print(f"PASS: {len(values)} historical daily P/E readings; 240/240 latest TAIEX sessions")
    print(f"DATE_RANGE: {values[0][0]} to {values[-1][0]}")
    print(f"RECENT_240: {target_dates[0]} to {target_dates[-1]}")
    print(f"LATEST_PE: {values[-1][1]}x; previous: {values[-2][1]}x")
    print(f"ORIGINAL_MONTHLY_ARCHIVED: {len(verified['twPeMonthly'])}")
    print(f"SOURCE_MATCHES: {len(matches)}, UNIQUE: {len(actual)}")
    print(f"FILE_READ_BACK_VERIFIED: true")
    print("METHOD: third-party published TWSE-per-stock-derived daily P/E, not monthly TWSE market P/E")

if __name__ == "__main__":
    main()
