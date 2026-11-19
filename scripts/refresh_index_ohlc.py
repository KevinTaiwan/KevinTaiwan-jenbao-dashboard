#!/usr/bin/env python3
"""Maintain a permanent PUBLIC TAIEX and S&P 500 true-index daily OHLC archive.

TAIEX primary: official TWSE MI_5MINS_HIST (monthly, market index OHLC).
TAIEX optional backup: Yahoo Finance ^TWII (explicitly identified per row).
S&P 500: Yahoo Finance ^GSPC INDEX, not SPY or VOO ETF.
Initial backfill verifies >=240 complete trading sessions per index; incremental
updates merge by date and NEVER truncate or discard valid historical records.
"""
import csv
import datetime as dt
import io
import json
import math
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / "public" / "index-ohlc-history.json"
TODAY = dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
# Run at 06:00 Taipei, after US close and before TWSE opens.
CUTOFF = TODAY - dt.timedelta(days=1)
MIN_DAYS = 240
TWSE_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TWSE_URL_LEGACY = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
SERIES = {
    "taiex": {"label": "Taiwan Stock Exchange Capitalization Weighted Stock Index", "symbol": "TAIEX", "unit": "index points"},
    "sp500": {"label": "S&P 500 Index", "symbol": "^GSPC", "unit": "index points"}
}
SOURCE_REGISTRY = {
    "TWSE": {"name": "Taiwan Stock Exchange MI_5MINS_HIST official TAIEX OHLC", "url": TWSE_URL},
    "YAHOO_TWII": {"name": "Yahoo Finance ^TWII TAIEX index OHLC fallback", "url": "https://finance.yahoo.com/quote/%5ETWII/history/"},
    "YAHOO_GSPC": {"name": "Yahoo Finance ^GSPC S&P 500 index OHLC", "url": "https://finance.yahoo.com/quote/%5EGSPC/history/"},
    "STOOQ_SPX": {"name": "Stooq ^SPX S&P 500 cash index OHLC fallback (not SPY)", "url": "https://stooq.com/q/d/?s=%5Espx&i=d"},
    "GITHUB_SPX_DATASET": {"name": "Public S&P 500 index OHLC historical dataset by jingerzz, based on Stooq ^SPX and Yahoo ^SPX (baseline only)", "url": "https://github.com/jingerzz/historical-index-api/tree/main/data/sp500"}
}
ARCHIVE = {k: {} for k in SERIES}
ERRORS = []
FETCHED = {}
def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "identity"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body=r.read(10_000_000)
    return json.loads(body.decode("utf-8-sig"))

def date_of(v):
    if not isinstance(v, str):
        return None
    v=v.strip()
    try:
        if re.fullmatch(r"\d{2,3}/\d{1,2}/\d{1,2}",v):
            y,m,d=map(int,v.split("/"))
            result=dt.date(y+1911,m,d)
        elif re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}",v):
            y,m,d=map(int,v.split("/"))
            result=dt.date(y,m,d)
        else:
            result=dt.date.fromisoformat(v[:10])
        return result if result<=CUTOFF else None
    except (ValueError,TypeError):
        return None

def parsed_float(v):
    return float(str(v).replace(",","").strip())

def save_record(key,date,op,hi,lo,cl,source):
    d=date if isinstance(date,dt.date) else date_of(date)
    if d is None or d>CUTOFF:
        return False
    try:
        op,hi,lo,cl=(parsed_float(v) for v in (op,hi,lo,cl))
    except (ValueError,TypeError,OverflowError):
        return False
    vals=(op,hi,lo,cl)
    if not all(math.isfinite(v) and 100<=v<=200000 for v in vals):
        return False
    # reject corrupt candles; small floating-point tolerance for quote feeds
    if hi+0.00001<max(op,cl,lo) or lo-0.00001>min(op,cl,hi):
        return False
    date_key=d.isoformat()
    row={"date":date_key, "open":round(op,4),"high":round(hi,4),"low":round(lo,4),"close":round(cl,4),"source":source}
    old=ARCHIVE[key].get(date_key)
    # Prefer the official TWSE value, then the existing verified row.
    if old and old["source"]=="TWSE" and source!="TWSE":
        return False
    if old and old["source"]!=source and source not in ("TWSE","YAHOO_GSPC"):
        return False
    ARCHIVE[key][date_key]=row
    return True

def load_previous():
    if not DEST.exists():
        return
    obj=json.loads(DEST.read_text(encoding="utf-8"))
    if obj.get("audience")!="public-index-ohlc" or obj.get("schemaVersion")!=1:
        raise ValueError("Existing OHLC archive schema mismatch: abort without overwriting!")
    for key in SERIES:
        for row in obj.get("series",{}).get(key,{}).get("rows",[]):
            if row.get("source") not in SOURCE_REGISTRY:
                raise ValueError("Unknown source in previously verified OHLC archive")
            if not save_record(key,row.get("date"),row.get("open"),row.get("high"),row.get("low"),row.get("close"),row["source"]):
                if date_of(row.get("date")) is None:
                    raise ValueError("Existing archive has a future/invalid date")
    print("PREVIOUS", {k:len(v) for k,v in ARCHIVE.items()},flush=True)

def month_start(year,month):
    return dt.date(year+(month-1)//12,(month-1)%12+1,1)

def field_index(fields,term):
    norm=lambda v: re.sub(r"[\s　()（）]", "",str(v))
    target=norm(term)
    return next((i for i,x in enumerate(fields) if target in norm(x)),None)

def fetch_twse_month(year,month):
    date=f"{year}{month:02d}01"
    failures=[]
    for base in (TWSE_URL,TWSE_URL_LEGACY):
        url=f"{base}?date={date}&response=json"
        try:
            doc=get_json(url,timeout=19)
            fields=doc.get("fields") or []
            data=doc.get("data") or []
            if not fields or not isinstance(data,list):
                raise ValueError("No indexed TWSE monthly data")
            indices=[field_index(fields,x) for x in ("日期","開盤指數","最高指數","最低指數","收盤指數")]
            if any(i is None for i in indices):
                raise ValueError(f"TWSE OHLC headers not found: {fields}")
            count=0
            for line in data:
                if not isinstance(line,list) or len(line)<=max(indices):
                    continue
                day=date_of(line[indices[0]])
                if day and save_record("taiex",day,*[line[i] for i in indices[1:]],"TWSE"):
                    count+=1
            if count:
                return count
            raise ValueError("No valid complete official TAIEX OHLC rows")
        except Exception as exc:
            failures.append(str(exc)[:115])
    raise ValueError(f"TWSE {date}: "+"; ".join(failures))

def fetch_twse():
    # The initial fetch reaches significantly beyond the 240-session goal;
    # subsequent runs request the most recent 2 months, not all history again.
    backfill=(not DEST.exists()) or len(ARCHIVE["taiex"])<MIN_DAYS
    months=20 if backfill else 2
    total=0
    for i in range(months):
        target=month_start(TODAY.year,TODAY.month-i)
        try:
            total+=fetch_twse_month(target.year,target.month)
        except Exception as exc:
            ERRORS.append(str(exc)[:200])
            if i<2 or backfill: print("WARN",str(exc)[:200],flush=True)
        time.sleep(.16)
    print("TWSE",total,"valid rows across",months,"months",flush=True)
    FETCHED["TWSE"]=total
    return total

def fetch_yahoo(symbol,key,source):
    # Two years at bootstrap ensures at least 240 S&P/TW sessions.
    # Every future refresh merges new and revised rows without trimming old dates.
    backfill=(not DEST.exists()) or len(ARCHIVE[key])<MIN_DAYS
    query="range=2y" if backfill else "range=3mo"
    last_error=None
    for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
        url=f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol,safe='')}?interval=1d&{query}"
        try:
            root=get_json(url)
            chart=root["chart"]
            if chart.get("error"):
                raise ValueError(str(chart["error"]))
            item=chart["result"][0]
            times=item.get("timestamp") or []
            quote=item["indicators"]["quote"][0]
            tz=ZoneInfo("Asia/Taipei" if key=="taiex" else "America/New_York")
            count=0
            for i,ts in enumerate(times):
                try:
                    date=dt.datetime.fromtimestamp(int(ts),tz=tz).date()
                    if save_record(key,date,quote["open"][i],quote["high"][i],quote["low"][i],quote["close"][i],source):
                        count+=1
                except (ValueError,IndexError,TypeError,KeyError):
                    continue
            if count>=2:
                FETCHED[source]=count
                print("YAHOO",symbol,count,"valid",flush=True)
                return count
            last_error=ValueError(f"Yahoo {symbol} only {count} valid OHLC")
        except Exception as exc:
            last_error=exc
    ERRORS.append(f"{symbol}: "+str(last_error)[:220])
    print("WARN",symbol,str(last_error)[:220],flush=True)
    FETCHED[source]=0
    return 0

def fetch_stooq_spx():
    """Best-effort backup for true cash S&P 500, never ETFs."""
    d1=(CUTOFF-dt.timedelta(days=900)).strftime("%Y%m%d")
    d2=CUTOFF.strftime("%Y%m%d")
    url="https://stooq.com/q/d/l/?s=%5Espx&i=d&d1="+d1+"&d2="+d2
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv,text/plain"})
    try:
        with urllib.request.urlopen(req,timeout=28) as response:
            txt=response.read(3_000_000).decode("utf-8-sig")
        count=0
        for row in csv.DictReader(io.StringIO(txt)):
            try:
                if save_record("sp500",row.get("Date"),row.get("Open"),row.get("High"),row.get("Low"),row.get("Close"),"STOOQ_SPX"):
                    count+=1
            except (ValueError,TypeError):
                continue
        FETCHED["STOOQ_SPX"]=count
        print("STOOQ_SPX",count,"valid cash S&P 500 sessions",flush=True)
        return count
    except Exception as exc:
        ERRORS.append("Stooq ^SPX: "+str(exc)[:190])
        print("WARN Stooq",str(exc)[:190],flush=True)
        return 0

def fetch_public_sp500_duckdb():
    """Transparent archival S&P 500 cash-index baseline, only if live daily sources fail.

    Dataset: https://github.com/jingerzz/historical-index-api
    This is a historical baseline, NOT falsely marketed as an up-to-date feed.
    Its newest date is checked and reported separately.
    """
    if len(ARCHIVE["sp500"])>=MIN_DAYS:
        return 0
    try:
        import duckdb
        url="https://raw.githubusercontent.com/jingerzz/historical-index-api/main/data/sp500/data.duckdb"
        req=urllib.request.Request(url,headers={"User-Agent":"JenbaoPublicMarketHistory/2.0"})
        with urllib.request.urlopen(req,timeout=35) as f:
            raw=f.read(8_000_000)
        if len(raw)<100_000:
            raise ValueError("Public S&P 500 index archive too small or missing")
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target=pathlib.Path(d)/"sp500.duckdb"
            target.write_bytes(raw)
            connection=duckdb.connect(str(target),read_only=True)
            try:
                rows=connection.execute(
                    "select date, open, high, low, close from indicators "
                    "where date >= DATE '2024-01-01' order by date"
                ).fetchall()
            finally:
                connection.close()
        count=0
        for date,op,hi,lo,cl in rows:
            if save_record("sp500",date,op,hi,lo,cl,"GITHUB_SPX_DATASET"):
                count+=1
        FETCHED["GITHUB_SPX_DATASET"]=count
        print("GITHUB_SPX_DATASET",count,"baseline sessions, last",
              max(ARCHIVE["sp500"]) if ARCHIVE["sp500"] else "none",flush=True)
        return count
    except Exception as exc:
        ERRORS.append("S&P 500 public archive: "+str(exc)[:220])
        print("WARN public S&P 500 archive",str(exc)[:220],flush=True)
        return 0

def finish():
    obj={"schemaVersion":1,"audience":"public-index-ohlc",
         "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
         "cutoff":CUTOFF.isoformat(),"retention":"permanent-no-date-limit",
         "minimumTradingSessions":MIN_DAYS,
         "sourceRegistry":SOURCE_REGISTRY,
         "series":{}}
    for key,meta in SERIES.items():
        rows=sorted(ARCHIVE[key].values(),key=lambda r:r["date"])
        if len(rows)<MIN_DAYS:
            raise ValueError(f"{key} only {len(rows)} verified complete OHLC trading days; need {MIN_DAYS}; archive NOT overwritten")
        obj["series"][key]={**meta,"count":len(rows),"first":rows[0]["date"],"last":rows[-1]["date"],"rows":rows}
    tmp=DEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,DEST)
    print("OHLC_RESULT",json.dumps({k:{"count":v["count"],"first":v["first"],"last":v["last"]} for k,v in obj["series"].items()},ensure_ascii=False),flush=True)
    if ERRORS: print("OHLC_PARTIAL_WARNINGS",json.dumps(ERRORS[:10],ensure_ascii=False),flush=True)

def main():
    load_previous()
    fetch_twse()
    # Official TWSE OHLC is preferred. Fill uncovered dates from ^TWII
    # without overwriting any official observation.
    if len(ARCHIVE["taiex"])<MIN_DAYS:
        fetch_yahoo("^TWII","taiex","YAHOO_TWII")
    fetch_yahoo("^GSPC","sp500","YAHOO_GSPC")
    if len(ARCHIVE["sp500"])<MIN_DAYS:
        fetch_stooq_spx()
    if len(ARCHIVE["sp500"])<MIN_DAYS:
        fetch_public_sp500_duckdb()
    finish()

if __name__=="__main__":
    main()
