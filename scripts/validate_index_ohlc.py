#!/usr/bin/env python3
"""Validate permanently archived public-only TAIEX and S&P 500 index OHLC."""
import datetime as dt
import json
import math
import pathlib
import sys

path=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "public/index-ohlc-history.json")
d=json.loads(path.read_text(encoding="utf-8"))
if set(d)!={"schemaVersion","audience","generatedAt","cutoff","retention","minimumTradingSessions","sourceRegistry","series"}:
    raise SystemExit("FAIL: unexpected OHLC archive schema")
if d["schemaVersion"]!=1 or d["audience"]!="public-index-ohlc" or d["retention"]!="permanent-no-date-limit":
    raise SystemExit("FAIL: wrong OHLC identity/retention")
if d["minimumTradingSessions"]!=240:
    raise SystemExit("FAIL: minimum must be 240 real sessions")
if set(d["series"])!={"taiex","sp500"}:raise SystemExit("FAIL: index symbols incorrect")
sources={"TWSE","YAHOO_TWII","YAHOO_GSPC","STOOQ_SPX","GITHUB_SPX_DATASET","CBOE_SPX"}
if set(d["sourceRegistry"])!=sources:raise SystemExit("FAIL: source registry changed")
limit=dt.date.fromisoformat(d["cutoff"])
counts={}
for key,meta in d["series"].items():
    if set(meta)!={"label","symbol","unit","count","first","last","rows"}:
        raise SystemExit("FAIL: unexpected OHLC series metadata")
    if meta["symbol"]!=("TAIEX" if key=="taiex" else "^GSPC"):
        raise SystemExit("FAIL: wrong symbol - ensure real S&P 500 INDEX")
    rows=meta["rows"]
    if len(rows)<240 or len(rows)!=meta["count"]:
        raise SystemExit(f"FAIL: {key} OHLC history contains fewer than 240 real sessions")
    if meta["first"]!=rows[0]["date"] or meta["last"]!=rows[-1]["date"]:
        raise SystemExit("FAIL: OHLC first/last metadata mismatch")
    prev=None
    for row in rows:
        if set(row)!={"date","open","high","low","close","source"}:
            raise SystemExit("FAIL: forbidden/private OHLC field")
        day=dt.date.fromisoformat(row["date"])
        if day>limit or prev is not None and day<=prev:
            raise SystemExit("FAIL: OHLC dates not sorted or future")
        prev=day
        if row["source"] not in sources:
            raise SystemExit("FAIL: unknown OHLC provenance")
        if key=="sp500" and row["source"] not in {"YAHOO_GSPC","STOOQ_SPX","GITHUB_SPX_DATASET","CBOE_SPX"}:
            raise SystemExit("FAIL: S&P 500 index data are not ^GSPC")
        vals=[row[k] for k in ("open","high","low","close")]
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 100<=v<=200000 for v in vals):
            raise SystemExit("FAIL: invalid index OHLC number")
        op,hi,lo,cl=vals
        if hi+0.00001<max(op,cl,lo) or lo-0.00001>min(op,cl,hi):
            raise SystemExit(f"FAIL: invalid OHLC high/low {key} {day}")
    counts[key]=len(rows)
print("PASS index OHLC: real 240+ sessions, no truncation, verified symbols, chronological and public-only",counts)
