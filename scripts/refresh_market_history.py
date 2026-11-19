#!/usr/bin/env python3
"""Backfill and refresh PUBLIC TAIEX/DXY/USD-TWD/VIX/HY-OAS history.

No personal positions, allocations, account details, or raw Library files.
Source dates are preserved. Failed fetches never become fabricated zeros.
"""
import csv
import io
import json
import math
import os
import pathlib
import time
import datetime as dt
import urllib.parse
import urllib.request
import zipfile
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / "public" / "market-history.json"
SEED = ROOT / "scripts" / "market_seed.json"
TODAY = dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
CUTOFF = TODAY - dt.timedelta(days=1)  # no intraday price in daily-close chart
EARLIEST = TODAY - dt.timedelta(days=300)
FIELDS = ("taiex", "dxy", "usdtwd", "vix", "hyOas")
SOURCE = {}
OBS = {key: {} for key in FIELDS}
SUCCESS = {}
URLS = {
    "taiex": "https://www.twse.com.tw/exchangeReport/FMTQIK",
    "dxy": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
    "dxy_fallback": "https://raw.githubusercontent.com/Wangxian111/xaudaily-data/main/data/daily/all.csv",
    "usdtwd": "https://query1.finance.yahoo.com/v8/finance/chart/TWD=X",
    "vix": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    "vix_fred": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
    "hyOas": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2",
}

def get(url, timeout=22):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; JenbaoPublicMarketHistory/1.0; +https://github.com/KevinTaiwan/KevinTaiwan-jenbao-dashboard)",
        "Accept":"application/json,text/csv,text/plain,*/*",
        "Accept-Encoding":"identity"
    })
    with urllib.request.urlopen(req,timeout=timeout) as res:
        raw=res.read(9_000_000)
    if raw[:2]==b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name=next((n for n in z.namelist() if n.endswith(".csv")),None)
            if not name:raise ValueError("Missing CSV in zip")
            raw=z.read(name)
    return raw.decode("utf-8-sig")

def valid_day(value):
    try:
        date=dt.date.fromisoformat(str(value))
        return date if EARLIEST<=date<=CUTOFF else None
    except (TypeError,ValueError):
        return None

def add(key, day, value):
    day=valid_day(day)
    if day is None or value in (None,"",".","NA","N/A"):return
    try:
        v=float(str(value).replace(",","").replace("%","").strip())
    except (ValueError,TypeError):return
    bounds={"taiex":(1000,100000),"dxy":(50,200),"usdtwd":(15,60),"vix":(5,100),"hyOas":(0.1,40)}
    a,b=bounds[key]
    if math.isfinite(v) and a<=v<=b:
        OBS[key][day.isoformat()]=round(v,4)

def csvrows(raw):
    return list(csv.DictReader(io.StringIO(raw)))

def parse_date(value):
    value=str(value or "").strip()
    for fmt in ("%Y-%m-%d","%m/%d/%Y","%Y/%m/%d","%m/%d/%y","%d/%m/%Y"):
        try:return dt.datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    return value[:10]

def attempt(label, fn):
    try:
        count=fn()
        SUCCESS[label]=count
        print("OK",label,"observations",count,flush=True)
        return count
    except Exception as exc:
        SUCCESS[label]=0
        print("WARN",label,"not available:",str(exc)[:180],flush=True)
        return 0

def load_seed():
    seed=json.loads(SEED.read_text(encoding="utf-8"))
    for row in seed["rows"]:
        for key in ("taiex","usdtwd"):
            add(key,row.get("date"),row.get(key))
    SOURCE["taiex"]={"name":"TAIEX official TWSE; Library closing prices as fallback","url":URLS["taiex"]}
    SOURCE["usdtwd"]={"name":"USD/TWD indicative market close; Library historical price input","url":URLS["usdtwd"]}
    if DEST.exists():
        old=json.loads(DEST.read_text(encoding="utf-8"))
        for row in old.get("rows",[]):
            for key in FIELDS:add(key,row.get("date"),row.get(key))

def fetch_twse():
    found=0
    for offset in range(8):
        y,m=TODAY.year,TODAY.month-offset
        while m<=0:y-=1;m+=12
        date=f"{y}{m:02d}01"
        url=f"https://www.twse.com.tw/exchangeReport/FMTQIK?response=json&date={date}"
        try:
            d=json.loads(get(url,timeout=16))
            fields=d.get("fields") or []
            p=next((i for i,k in enumerate(fields) if "發行量加權股價指數" in k),4)
            for row in d.get("data",[]):
                year,mon,day=map(int,row[0].split("/"))
                add("taiex",f"{year+1911:04d}-{mon:02d}-{day:02d}",row[p])
                found+=1
        except Exception as exc:print("WARN TWSE month",date,str(exc)[:75],flush=True)
        time.sleep(0.35)
    if found<20:raise ValueError("TWSE not enough rows")
    SOURCE["taiex"]={"name":"TWSE FMTQIK daily index level; Library market-only seed","url":URLS["taiex"]}
    return found

def fetch_yahoo(symbol, key):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol,safe='')}?interval=1d&range=1y"
    d=json.loads(get(url))
    item=d["chart"]["result"][0]
    timestamps=item.get("timestamp",[])
    quote=item["indicators"]["quote"][0]["close"]
    count=0
    for ts,close in zip(timestamps,quote):
        if close is None:continue
        day=dt.datetime.fromtimestamp(int(ts),tz=ZoneInfo("America/New_York")).date().isoformat()
        add(key,day,close)
        count+=1
    if count<50:raise ValueError(f"Yahoo {symbol} returned only {count} rows")
    SOURCE[key]={"name":f"Yahoo Finance {symbol} daily market close (not ICE licensed feed)" if key=="dxy" else "Yahoo Finance TWD=X daily indicative FX quote; Library values override on overlapping dates",
                  "url":URLS[key]}
    return count

def fetch_dxy_backup():
    raw=get(URLS["dxy_fallback"])
    count=0
    for row in csvrows(raw):
        day=row.get("dxy_asof","")
        if day!=row.get("date",""):continue  # no stale reuse in archive
        if not valid_day(day):continue
        add("dxy",day,row.get("dxy"))
        count+=1
    if count<15:raise ValueError("DXY backup too short")
    SOURCE["dxy"]={"name":"xaudaily.com daily DXY close/indicative snapshot, CC BY 4.0; Yahoo spot series unavailable","url":URLS["dxy_fallback"]}
    return count

def fetch_cboe():
    raw=get(URLS["vix"])
    rows=csvrows(raw);count=0
    for row in rows:
        day=parse_date(row.get("DATE") or row.get("Date") or row.get("date"))
        value=row.get("CLOSE") or row.get("Close") or row.get("close")
        if valid_day(day) and value not in (None,""):
            add("vix",day,value);count+=1
    if count<50:raise ValueError("Cboe CSV insufficient rows")
    SOURCE["vix"]={"name":"Cboe VIX Index official daily close","url":URLS["vix"]}
    return count

def fetch_fred(key,series):
    raw=get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={EARLIEST.isoformat()}&coed={CUTOFF.isoformat()}")
    rows=csvrows(raw)
    count=0
    for row in rows:
        day=row.get("observation_date") or row.get("DATE") or row.get("date")
        value=row.get(series)
        if valid_day(day) and value not in (None,"","."):
            add(key,day,value);count+=1
    if count<20:raise ValueError(f"FRED {series} only {count} rows")
    SOURCE[key]={"name":f"FRED {series} daily observations"+(" (ICE BofA HY OAS, percent)" if key=="hyOas" else ""),"url":f"https://fred.stlouisfed.org/series/{series}"}
    return count

def main():
    load_seed()
    attempt("TWSE_TAIEX",fetch_twse)
    # Yahoo US dollar index preferred, xaudaily only if Yahoo unavailable
    if not attempt("DXY_Yahoo",lambda:fetch_yahoo("DX-Y.NYB","dxy")):
        attempt("DXY_backup",fetch_dxy_backup)
    # Yahoo indicative fx; Library observations override it on overlapping dates
    if attempt("USD_TWD_Yahoo",lambda:fetch_yahoo("TWD=X","usdtwd")):
        seed=json.loads(SEED.read_text(encoding="utf-8"))
        for row in seed["rows"]:add("usdtwd",row.get("date"),row.get("usdtwd"))
    if not attempt("VIX_Cboe",fetch_cboe):
        attempt("VIX_FRED",lambda:fetch_fred("vix","VIXCLS"))
    attempt("HY_OAS_FRED",lambda:fetch_fred("hyOas","BAMLH0A0HYM2"))
    dates=sorted({day for ser in OBS.values() for day in ser})
    rows=[]
    for day in dates:
        item={"date":day}
        for key in FIELDS:
            if day in OBS[key]:item[key]=OBS[key][day]
        rows.append(item)
    rows=rows[-260:]  # ~120 trading days, preserve cross-market extra days
    stats={}
    for key in FIELDS:
        values=[(r["date"],r[key]) for r in rows if key in r]
        stats[key]={
          "count":len(values),
          "first":values[0][0] if values else None,
          "last":values[-1][0] if values else None,
          "lastValue":values[-1][1] if values else None,
          "status":"ready" if len(values)>=55 else "partial",
          "source":SOURCE.get(key,{"name":"Previously verified market observations","url":None})
        }
    out={
      "schemaVersion":1,
      "audience":"public-market-history",
      "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
      "cutoff":CUTOFF.isoformat(),
      "calendar":"source observation dates; never forward-fill; latest intraday excluded",
      "units":{"taiex":"index pts","dxy":"ICE US Dollar Index points","usdtwd":"TWD per USD","vix":"index pts","hyOas":"percent"},
      "stats":stats,
      "rows":rows
    }
    if stats["taiex"]["count"]<20:raise SystemExit("FAIL: insufficient TAIEX source history")
    DEST.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FINAL COUNTS",json.dumps({k:(v["count"],v["last"]) for k,v in stats.items()},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
