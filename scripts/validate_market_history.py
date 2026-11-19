#!/usr/bin/env python3
"""Strict validator: this published JSON is PUBLIC market data only."""
import json, datetime as dt, pathlib, math, sys
path=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "public/market-history.json")
d=json.loads(path.read_text(encoding="utf-8"))
if set(d)!={"schemaVersion","audience","generatedAt","cutoff","calendar","units","stats","rows"} or d["schemaVersion"]!=1 or d["audience"]!="public-market-history":
    raise SystemExit("FAIL: unexpected public market-history structure")
keys={"taiex","dxy","usdtwd","vix","hyOas","marginDailyYi","foreignNetYi","marginMaintenanceExEtf","us10yYield","us10y2ySpread","voo","qqq","fedFundsEffective"}
if set(d["units"])!=keys or set(d["stats"])!=keys:raise SystemExit("FAIL: unexpected market series")
if not isinstance(d["rows"],list):raise SystemExit("FAIL: malformed rows")
# Permanent data archive: never reject due to reaching 20/60/120/240/260 days or any count limit.
prev=None
bounds={"taiex":(1000,100000),"dxy":(50,200),"usdtwd":(15,60),"vix":(5,100),"hyOas":(0.1,40),"marginDailyYi":(-2000,2000),"foreignNetYi":(-2500,2500),"marginMaintenanceExEtf":(80,500),"us10yYield":(0,25),"us10y2ySpread":(-6,7),"voo":(20,2000),"qqq":(20,2000),"fedFundsEffective":(0,25)}
counts={k:0 for k in keys}
for r in d["rows"]:
    if set(r)-({"date"}|keys):raise SystemExit("FAIL: private or unexpected history key")
    day=dt.date.fromisoformat(r["date"])
    if prev is not None and day<=prev:raise SystemExit("FAIL: dates unordered or repeated")
    if day>dt.date.fromisoformat(d["cutoff"]):raise SystemExit("FAIL: intraday/future observation")
    prev=day
    for k in keys.intersection(r):
        v=r[k];a,b=bounds[k]
        if type(v) not in (int,float) or not math.isfinite(v) or not a<=v<=b:
            raise SystemExit(f"FAIL: invalid {k} observation")
        counts[k]+=1
for k,st in d["stats"].items():
    if set(st)!={"count","first","last","lastValue","status","source"}:raise SystemExit("FAIL: unexpected series metadata")
    if st["count"]!=counts[k]:raise SystemExit("FAIL: inconsistent count")
    if st["status"] not in ("ready","partial"):raise SystemExit("FAIL: invalid series status")
    src=st["source"]
    if set(src)!={"name","url"}:raise SystemExit("FAIL: bad source")
    if src["url"] is not None and (not isinstance(src["url"],str) or not src["url"].startswith("https://")):raise SystemExit("FAIL: untrusted source")
if counts["taiex"]<20:raise SystemExit("FAIL: insufficient market series")
print("PASS: market-only history, chronological observations, no personal data",counts)
