#!/usr/bin/env python3
"""Reject leaked private data and incorrect/unsafe provisional index OHLC."""
import datetime as dt
import json
import math
import pathlib
import re
import sys

p=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "public/intraday-market.json")
d=json.loads(p.read_text(encoding="utf-8"))
assert d["audience"]=="public-market-intraday" and d["schemaVersion"]==1
assert set(d)<= {"schemaVersion","audience","generatedAt","asOfTaipei","refreshIntentMinutes","actualQuoteDelayVaries","tradingSessions","markets","updatedMarkets","safetyNotes"}
assert set(d["markets"]) <= {"taiex","sp500"}
for key,m in d["markets"].items():
    assert m["market"]==key
    assert m["status"]=="provisional"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}",m["date"])
    candles=m["candles"]
    assert 1<=len(candles)<=140
    assert all(b.get("time","").startswith(m["date"]) for b in candles)
    assert [b["time"] for b in candles]==sorted(set(b["time"] for b in candles))
    for b in candles:
        assert set(b) <= {"time","open","high","low","close","turnoverYiTwd"}
        vals=[b[k] for k in ("open","high","low","close")]
        assert all(type(x) in (float,int) and math.isfinite(x) and 100<=x<=200000 for x in vals)
        assert b["high"]>=max(b["open"],b["close"],b["low"])
        assert b["low"]<=min(b["open"],b["close"],b["high"])
    for k in ("turnoverYiTwd","projectedTurnoverYiTwd"):
        value=m.get(k)
        assert value is None or (key=="taiex" and type(value) in (float,int) and 0<=value<=200000)
    if m.get("turnoverYiTwd") is not None:
        assert m["turnoverStatus"]=="verified_index_turnover_TWD"
        assert all("turnoverYiTwd" in x for x in candles)
    else:
        assert m.get("projectedTurnoverYiTwd") is None
    assert m["latest"]["close"]==candles[-1]["close"]
print("PASS: intraday market-only five-minute provisional OHLC", {k:len(v["candles"]) for k,v in d["markets"].items()})
