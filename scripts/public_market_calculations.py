#!/usr/bin/env python3
"""Offline deterministic statistics of public market archives only."""
import datetime as dt
import hashlib
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = (20, 60, 252)
MA = (5, 10, 20, 60, 120, 240)
METHOD = "V13.2"

def pairs_checked(rows, positive=False):
    result = []
    prev = ""
    for day, value in rows:
        if dt.date.fromisoformat(day).isoformat() != day or day <= prev:
            raise ValueError("invalid or duplicate date")
        if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
            raise ValueError("invalid value")
        result.append((day,value))
        prev = day
    return result

def index_metrics(rows):
    pairs = pairs_checked(((r["date"],r["close"]) for r in rows), True)
    if not pairs:
        raise ValueError("empty index")
    prices = [v for _,v in pairs]
    result = {"asOf":pairs[-1][0],"close":prices[-1],
              "previousDate":pairs[-2][0] if len(pairs)>1 else None,
              "previousClose":prices[-2] if len(pairs)>1 else None,
              "movingAverages":{str(n):round(st.fmean(prices[-n:]),4) if len(prices)>=n else None for n in MA},
              "windows":{}}
    for n in WINDOWS:
        count = min(n,len(prices)-1)
        entry = {"requiredReturns":n,"availableReturns":count,"startDate":None,
                 "endDate":pairs[-1][0],"annualizedVolatilityPct":None,"maxDrawdownPct":None,
                 "status":"insufficient_samples"}
        if count == n:
            p = prices[-(n+1):]
            returns = [b/a-1 for a,b in zip(p,p[1:])]
            peak = p[0]
            dd = 0
            for v in p:
                peak = max(peak,v)
                dd = min(dd,v/peak-1)
            entry.update(startDate=pairs[-(n+1)][0],
                         annualizedVolatilityPct=round(st.stdev(returns)*math.sqrt(252)*100,6),
                         maxDrawdownPct=round(dd*100,6),status="computed_from_archive")
        result["windows"][str(n)] = entry
    return result

def ratio20(rows,unit):
    p = pairs_checked(rows)
    r = {"unit":unit,"asOf":None,"latest":None,"previousDate":None,"previousValue":None,
         "baselineCount":min(20,max(0,len(p)-1)),"baselineStart":None,"baselineEnd":None,
         "baselineMean":None,"latestMinusPrior20Mean":None,"latestOverPrior20Mean":None,
         "status":"insufficient_samples"}
    if p:
        r.update(asOf=p[-1][0],latest=p[-1][1])
    if len(p)>1:
        r.update(previousDate=p[-2][0],previousValue=p[-2][1])
    if len(p)>=21:
        prior=p[-21:-1]
        mean=st.fmean(v for _,v in prior)
        r.update(baselineStart=prior[0][0],baselineEnd=prior[-1][0],
                 baselineMean=round(mean,8),latestMinusPrior20Mean=round(p[-1][1]-mean,8))
        if mean>0 and p[-1][1]>=0:
            r.update(latestOverPrior20Mean=round(p[-1][1]/mean,8),status="computed_from_archive")
        else:
            r["status"]="ratio_not_meaningful"
    return r

def load_public(name):
    raw=(ROOT/"public"/name).read_bytes()
    return json.loads(raw),{"gitBlobSha":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest(),
                            "sha256":hashlib.sha256(raw).hexdigest()}

def calculate():
    o,os=load_public("index-ohlc-history.json")
    h,hs=load_public("market-history.json")
    c,cs=load_public("market-center-history.json")
    if o.get("audience")!="public-index-ohlc" or h.get("audience")!="public-market-history" or set(o["series"])!={"taiex","sp500"}:
        raise ValueError("unexpected input identity")
    ratios={}
    for k,unit in (("hyOas","percentage_points"),("vix","index_points")):
        ratios[k]=ratio20(((r["date"],r[k]) for r in h["rows"] if r.get(k) is not None),unit)
    for k,unit in (("singleBOas","percentage_points"),("sofrMinusIorbBp","basis_points"),("move","index_points")):
        ratios[k]=ratio20(c[k],unit)
    return {"schemaVersion":1,"audience":"public-market-calculations","methodVersion":METHOD,
            "method":{"returns":"local currency close-to-close simple price returns, not total returns",
                      "volatility":"sample standard deviation times sqrt(252), percent",
                      "drawdown":"minimum close/running peak minus one within n+1 closes, percent",
                      "ratio20":"latest divided by mean of preceding 20 available observations, excluding latest; null if mean nonpositive or latest negative",
                      "coverage":"available archive observations only; does not certify complete exchange sessions or fresh original source checks"},
            "inputs":{"index-ohlc-history.json":os,"market-history.json":hs,"market-center-history.json":cs},
            "indices":{k:index_metrics(o["series"][k]["rows"]) for k in ("taiex","sp500")},
            "ratios":ratios}

def main():
    result=calculate()
    dest=ROOT/".sync"/"public-market-calculations.json"
    raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
    if dest.exists() and dest.read_bytes()==raw:
        print("SKIP_NO_CHANGE public-market-calculations")
        return
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix(".json.tmp")
    temp.write_bytes(raw)
    temp.replace(dest)
    print("PASS public market calculations", {k:v["asOf"] for k,v in result["indices"].items()})

if __name__=="__main__":
    main()
