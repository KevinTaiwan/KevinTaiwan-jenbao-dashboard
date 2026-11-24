#!/usr/bin/env python3
"""Market-only intraday 5-minute OHLC and verified monetary turnover.

Taiwan: Yahoo ^TWII five-minute *price* candles (may be delayed); optional
An optional verified TWD-turnover provider with explicit currency and monetary bars;\nwithout it turnover and projection remain null.
US: Yahoo ^GSPC five-minute price candles; index volume is NEVER labeled
market turnover value. No fabricated monetary turnover or projections.

The file is a PROVISIONAL intraday layer, not the daily official archive.
"""
import datetime as dt
import json
import math
import os
import pathlib
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

PATH=pathlib.Path("public/intraday-market.json")
TPE=ZoneInfo("Asia/Taipei")
NY=ZoneInfo("America/New_York")
UTC=dt.timezone.utc
UA={"User-Agent":"Mozilla/5.0 (compatible; JenbaoMarket/1.0)","Accept":"application/json"}
MARKETS={
 "taiex":{"tz":TPE,"open":dt.time(9,0),"close":dt.time(13,30),"symbol":"^TWII"},
 "sp500":{"tz":NY,"open":dt.time(9,30),"close":dt.time(16,0),"symbol":"^GSPC"},
}

def read_json(url,headers=None):
    req=urllib.request.Request(url,headers={**UA,**(headers or {})})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode("utf-8-sig"))

def number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):
        return None

def session(m,now):
    local=now.astimezone(m["tz"])
    return (local.weekday()<5 and
            m["open"] <= local.time().replace(tzinfo=None) <=
            (dt.datetime.combine(local.date(),m["close"])+dt.timedelta(minutes=12)).time()),local


def completed_bar_boundary(raw):
    """Allow only source timestamps on explicit five-minute OHLC boundaries."""
    try:
        when=dt.datetime.fromisoformat(str(raw))
        return (when.utcoffset() is not None and when.minute%5==0
                and when.second==0 and when.microsecond==0)
    except (TypeError,ValueError,OverflowError):
        return False

def normalize(raw,day,tz,opens,closes):
    bytime={}
    for b in raw:
        try:
            when=dt.datetime.fromisoformat(str(b["time"]))
            if not completed_bar_boundary(b["time"]):continue
            when=when.astimezone(tz)
            if when.date().isoformat()!=day:continue
            clock=when.time().replace(tzinfo=None)
            if not (opens<=clock<=closes):continue
            op,hi,lo,cl=(number(b.get(x)) for x in ("open","high","low","close"))
            if None in (op,hi,lo,cl) or min(op,hi,lo,cl)<=0 or hi<max(op,cl,lo) or lo>min(op,cl,hi):continue
            item={"time":when.isoformat(timespec="seconds"),"open":round(op,4),
                  "high":round(hi,4),"low":round(lo,4),"close":round(cl,4)}
            vol=number(b.get("turnoverTwd"))
            if vol is not None and vol>=0:item["turnoverYiTwd"]=round(vol/1e8,6)
            bytime[item["time"]]=item
        except (KeyError,ValueError,OverflowError):
            continue
    return [bytime[k] for k in sorted(bytime)]

def yahoo(m,local):
    symbol=urllib.parse.quote(m["symbol"],safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=2d&includePrePost=false"
    root=read_json(url)["chart"]
    if root.get("error"):raise ValueError("Yahoo chart error "+str(root["error"]))
    result=root["result"][0]
    stamps=result.get("timestamp") or []
    q=(result.get("indicators",{}).get("quote") or [{}])[0]
    raw=[]
    for i,t in enumerate(stamps):
        candle={}
        for key in ("open","high","low","close"):
            arr=q.get(key) or []
            candle[key]=arr[i] if i<len(arr) else None
        candle["time"]=dt.datetime.fromtimestamp(t,UTC).isoformat()
        raw.append(candle)
    # Index 'volume' has no trustworthy TWD turnover monetary unit: exclude.
    return normalize(raw,local.date().isoformat(),m["tz"],m["open"],m["close"]),int(result.get("meta",{}).get("exchangeDataDelayedBy") or 0)

def verified_turnover(local,m):
    """Optional authenticated provider or trusted adapter, requiring explicit TWD currency.

    Expected JSON: {date:'YYYY-MM-DD',currency:'TWD',bars:[{time,open,high,low,close,turnoverTwd}]}.
    No provider configured means monetary turnover remains null.
    """
    url=os.environ.get("JENBAO_VERIFIED_TWD_TURNOVER_URL","").strip()
    if not url or not url.startswith("https://"):
        return [],"no_verified_intraday_TWD_turnover_source"
    headers={}
    if os.environ.get("JENBAO_TURNOVER_API_KEY"):
        headers["Authorization"]="Bearer "+os.environ["JENBAO_TURNOVER_API_KEY"]
    payload=read_json(url,headers)
    if payload.get("currency")!="TWD" or payload.get("date")!=local.date().isoformat():
        raise ValueError("turnover source missing explicit same-day TWD currency")
    raw=payload.get("bars") or []
    if not isinstance(raw,list) or not raw:
        return [],"no_verified_bars"
    if any(number(b.get("turnoverTwd")) is None for b in raw):
        raise ValueError("turnover value not explicitly provided by provider")
    return normalize(raw,local.date().isoformat(),m["tz"],m["open"],m["close"]),"verified_TWD_turnover_provider"

def summarise(rows,now,market,mode,delayed):
    first,last=rows[0],rows[-1]
    day=last["time"][:10]
    price={"open":first["open"],"high":max(r["high"] for r in rows),
           "low":min(r["low"] for r in rows),"close":last["close"],
           "lastCandleTime":last["time"]}
    values=[r.get("turnoverYiTwd") for r in rows]
    monetary=(market=="taiex" and len(values)==len(rows) and all(v is not None for v in values))
    cum=round(sum(values),3) if monetary else None
    estimate=None
    elapsed=None
    if monetary:
        start=dt.datetime.combine(dt.date.fromisoformat(day),MARKETS[market]["open"],tzinfo=MARKETS[market]["tz"])
        nowlocal=now.astimezone(MARKETS[market]["tz"])
        elapsed=max(0,min(270,(nowlocal-start).total_seconds()/60))
        # At least 15min coverage; naive linear volume curve estimate.
        if 15<=elapsed<270:
            estimate=round(cum*270/elapsed,3)
        elif elapsed>=270:estimate=cum
    return {"market":market,"date":day,"status":"provisional",
            "source":mode,"sourceDelayMinutes":delayed,
            "latest":price,"candles":rows,
            "turnoverYiTwd":cum,"projectedTurnoverYiTwd":estimate,
            "projectionMethod":"elapsed_session_linear_extrapolation_v1" if estimate is not None else None,
            "projectionIsEstimate":estimate is not None,
            "turnoverStatus":"verified_index_turnover_TWD" if monetary else "unavailable_not_inferred_from_shares",
            "note":"OHLC are 5-minute provisional candles, not official closing values. Volume is monetary turnover (億元), never index share count."}


def sanitize_saved_candles(markets,now):
    """Remove legacy in-progress off-grid bars while retaining completed bars.

    Do not round a partial quote timestamp into a supposedly verified candle.
    """
    fresh=dict(markets)
    fixed=[]
    for name,old in markets.items():
        if name not in MARKETS or not isinstance(old,dict):
            continue
        bars=old.get("candles")
        if not isinstance(bars,list) or not bars:
            continue
        verified=[b for b in bars if completed_bar_boundary(b.get("time"))]
        if len(verified)==len(bars):
            continue
        if verified:
            fixed_market=summarise(verified,now,name,old.get("source","previous verified source"),old.get("sourceDelayMinutes"))
            last=dt.datetime.fromisoformat(verified[-1]["time"]).astimezone(UTC)
            fixed_market["quoteAgeMinutes"]=round((now-last).total_seconds()/60,1)
            fresh[name]=fixed_market
        else:
            # With no completed bars, don't republish a misleading candle.
            del fresh[name]
        fixed.append(name)
        print("REMOVED INCOMPLETE FIVE-MINUTE CANDLE",name,
              "removed",len(bars)-len(verified),"retained",len(verified),flush=True)
    return fresh,fixed

def main():
    now=dt.datetime.now(UTC)
    existing={}
    if PATH.is_file():
        try:existing=json.loads(PATH.read_text(encoding="utf-8"))
        except ValueError:pass
    latest=existing.get("markets",{}) if isinstance(existing.get("markets"),dict) else {}
    fresh,updated=sanitize_saved_candles(latest,now)
    for name,m in MARKETS.items():
        active,local=session(m,now)
        if not active:continue
        try:
            rows,delay=yahoo(m,local)
            mode="Yahoo Finance 5m index quote (delayed/indicative)"
        except Exception as ex:
            rows=[];delay=None
            print(name+" Yahoo unavailable:",str(ex)[:180])
        if name=="taiex":
            try:
                fr,fmode=verified_turnover(local,m)
                if fr:
                    rows=fr
                    mode="Verified index 5m OHLC / TWD monetary turnover"
                    delay=0
            except Exception as e:
                print("Verified TWD turnover provider unavailable; shares never used as money:",str(e)[:180])
        if rows:
            # Source timestamps are bar START times; do not publish a still-forming
            # candle even when its timestamp falls precisely on a 5-minute grid.
            rows=[bar for bar in rows
                  if dt.datetime.fromisoformat(bar["time"]).astimezone(UTC)
                     +dt.timedelta(minutes=5)<=now]
        if not rows:
            print(name,"no completed same-session bars; preserved previous valid data")
            continue
        # If provider is delayed or a holiday, never treat stale rows as "live".
        last=dt.datetime.fromisoformat(rows[-1]["time"]).astimezone(UTC)
        age=(now-last).total_seconds()/60
        if age>55 or age<-10:
            print(name,"stale last bar age(minutes):",round(age,1))
            continue
        fresh[name]=summarise(rows,now,name,mode,delay)
        fresh[name]["quoteAgeMinutes"]=round(age,1)
        if name not in updated:updated.append(name)
    if not updated:
        print("No verified active market updates; no file change")
        return
    payload={"schemaVersion":1,"audience":"public-market-intraday",
        "generatedAt":now.isoformat(timespec="seconds"),"asOfTaipei":now.astimezone(TPE).isoformat(timespec="seconds"),
        "refreshIntentMinutes":5,"actualQuoteDelayVaries":True,
        "tradingSessions":"TAIEX 09:00-13:30 Asia/Taipei; SP500 09:30-16:00 America/New_York",
        "markets":fresh,"updatedMarkets":updated,
        "safetyNotes":["Quote prices can be delayed; GitHub schedule and GitHub Pages deployment have additional latency.",
                       "Market turnover is 成交金額 (億元), never shares. Missing verified source => null.",
                       "Estimated full-day turnover is a naive linear extrapolation, not a closing forecast.",
                       "Intraday candles are not appended to official closing daily master."]}
    # Ignore acquisition timestamps in equality check: no repeated commits when quotes unchanged.
    def fingerprint(d):
        return {k:{"date":v.get("date"),"candles":v.get("candles"),"turnover":v.get("turnoverYiTwd"),
                   "estimate":v.get("projectedTurnoverYiTwd")}
                for k,v in d.get("markets",{}).items()}
    if fingerprint(existing)==fingerprint(payload):
        print("Market values unchanged, no commit")
        return
    PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Intraday updated",updated,{k:len(fresh[k]["candles"]) for k in updated})

if __name__=="__main__":
    main()
