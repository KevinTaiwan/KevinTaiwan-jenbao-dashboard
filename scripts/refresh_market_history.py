#!/usr/bin/env python3
"""Backfill and refresh PUBLIC TAIEX/DXY/USD-TWD/VIX/HY-OAS plus UST 10Y / 10Y-2Y history.

No personal positions, allocations, account details, or raw Library files.
Source dates are preserved. Failed fetches never become fabricated zeros.
VOO and QQQ use publicly accessible USD share prices; not user-specific positions.
DFF observations are the effective overnight rate, distinct from the FOMC target range.
"""
from decimal import Decimal
from twse_credit_calls import merge_credit
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
import re
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / "public" / "market-history.json"
SEED = ROOT / "scripts" / "market_seed.json"
TODAY = dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
CUTOFF = TODAY - dt.timedelta(days=1)  # no intraday price in daily-close chart
EARLIEST = dt.date(1900,1,1)  # archive floor: retained historical observations do not expire
FETCH_START = TODAY - dt.timedelta(days=300)  # incremental source fetch horizon only
FIELDS = ("taiex", "dxy", "usdtwd", "vix", "hyOas", "marginDailyYi", "foreignNetYi", "marginMaintenanceExEtf", "us10yYield", "us10y2ySpread", "voo", "qqq", "fedFundsEffective")
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
    "foreignNetYi":"https://www.twse.com.tw/rwd/zh/fund/BFI82U",
    "marginDailyYi":"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
    "marginMaintenanceExEtf":"https://www.wantgoo.com/stock/margin-trading/exclude-etf/taiex",
    "us10yYield":"https://fred.stlouisfed.org/series/DGS10",
    "us10y2ySpread":"https://fred.stlouisfed.org/series/T10Y2Y",
    "voo":"https://finance.yahoo.com/quote/VOO/history/",
    "qqq":"https://finance.yahoo.com/quote/QQQ/history/",
    "fedFundsEffective":"https://fred.stlouisfed.org/series/DFF",
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
    if day is None or (day.weekday()>=5 and key!="fedFundsEffective") or value in (None,"",".","NA","N/A"):return
    try:
        v=float(str(value).replace(",","").replace("%","").strip())
    except (ValueError,TypeError):return
    bounds={"taiex":(1000,100000),"dxy":(50,200),"usdtwd":(15,60),"vix":(5,100),"hyOas":(0.1,40),"marginDailyYi":(-2000,2000),"foreignNetYi":(-100000,100000),"marginMaintenanceExEtf":(80,500),"us10yYield":(0,25),"us10y2ySpread":(-6,7),"voo":(20,2000),"qqq":(20,2000),"fedFundsEffective":(0,25)}
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
    exetf=ROOT / "scripts" / "ex_etf_maintenance_seed.json"
    if exetf.exists():
        trusted=json.loads(exetf.read_text(encoding="utf-8"))
        if trusted.get("audience")!="public-market-seed" or trusted.get("series")!="marginMaintenanceExEtf":
            raise ValueError("Invalid source-labeled ETF-excluded financing maintenance seed")
        for row in trusted["rows"]:
            add("marginMaintenanceExEtf",row.get("date"),row.get("value"))
        SOURCE["marginMaintenanceExEtf"]={"name":"Wantgoo: TAIEX financing maintenance EXCLUDING ETF, dated historical seed","url":URLS["marginMaintenanceExEtf"]}
    if DEST.exists():
        old=json.loads(DEST.read_text(encoding="utf-8"))
        for row in old.get("rows",[]):
            for key in FIELDS:add(key,row.get("date"),row.get(key))
        for key in FIELDS:
            if key not in SOURCE and isinstance(old.get("stats",{}).get(key,{}).get("source"),dict):
                SOURCE[key]=old["stats"][key]["source"]

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
    name=(f"Yahoo Finance {symbol} daily ETF Close, USD, unadjusted; excludes distributions" if key in ("voo","qqq")
          else f"Yahoo Finance {symbol} daily market close (not ICE licensed feed)" if key=="dxy"
          else "Yahoo Finance TWD=X daily indicative FX quote; Library values override on overlapping dates")
    SOURCE[key]={"name":name,"url":URLS[key]}
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
    raw=get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={FETCH_START.isoformat()}&coed={CUTOFF.isoformat()}")
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


def _twse_tables(payload):
    tables = payload.get("tables") or payload.get("stat") or []
    if isinstance(tables,list):
        for table in tables:
            if isinstance(table,dict) and isinstance(table.get("data"),list):
                yield table.get("fields") or [],table["data"]
    if isinstance(payload.get("data"),list):
        yield payload.get("fields") or [], payload["data"]

def _number(v):
    return float(str(v).replace(",","").replace(" ","").replace("+","").strip())

def fetch_foreign_daily():
    found=0
    # Backfill only within current 120 calendar days, then daily incremental maintenance.
    for delta in range(121):
        date=CUTOFF-dt.timedelta(days=delta)
        if date.weekday()>=5:continue
        stamp=date.strftime("%Y%m%d")
        try:
            u=URLS["foreignNetYi"]+"?type=day&dayDate="+stamp+"&response=json"
            payload=json.loads(get(u,timeout=12))
            if payload.get("date") != stamp: continue
            for fields,rows in _twse_tables(payload):
                for row in rows:
                    if not row or "外資及陸資" not in str(row[0]) or "自營商" not in str(row[0]):continue
                    # BFI82U units are TWD, with net in 4th column.
                    if len(row)<4:continue
                    raw=str(row[3])
                    val=_number(raw)/1e8
                    if abs(val)>100000:continue
                    add("foreignNetYi",date.isoformat(),val)
                    found+=1
                    break
            if found>=70:break
        except Exception as e:
            if delta<4:print("WARN foreign",stamp,str(e)[:80])
        time.sleep(0.22)
    SOURCE["foreignNetYi"]={"name":"TWSE BFI82U foreign cash investment net amount, TWD 100m","url":URLS["foreignNetYi"]}
    if found<1:raise ValueError("No verified BFI82U daily foreign observations")
    return found

def fetch_margin_daily():
    found=0
    for delta in range(121):
        date=CUTOFF-dt.timedelta(days=delta)
        if date.weekday()>=5:continue
        stamp=date.strftime("%Y%m%d")
        try:
            u=URLS["marginDailyYi"]+"?date="+stamp+"&selectType=MS&response=json"
            d=json.loads(get(u,timeout=12))
            if d.get("date") != stamp: continue
            for fields,rows in _twse_tables(d):
                for row in rows:
                    if len(row)<6 or "融資金額" not in str(row[0]):continue
                    # TWSE MI_MARGN row[4] is preceding balance, row[5] is current outstanding (TWD 1000).
                    # Keep only when descriptions and both positive balances are available.
                    cur,prev=_number(row[4]),_number(row[5])
                    if cur<1e6 or prev<1e6:continue
                    val=(prev-cur)/1e5
                    if abs(val)>2000:continue
                    add("marginDailyYi",date.isoformat(),val)
                    found+=1
                    break
            if found>=70:break
        except Exception as e:
            if delta<4:print("WARN margin",stamp,str(e)[:80])
        time.sleep(0.22)
    SOURCE["marginDailyYi"]={"name":"TWSE MI_MARGN finance outstanding daily change, includes ETFs, TWD 100m","url":URLS["marginDailyYi"]}
    if found<1:raise ValueError("No verified MI_MARGN daily financing observations")
    return found

class _WantgooRows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.inside_tr=False;self.inside_cell=False;self.cell=[];self.cells=[]
    def handle_starttag(self,tag,attrs):
        if tag=="tr":self.inside_tr=True;self.cells=[]
        if tag in ("td","th") and self.inside_tr:self.inside_cell=True;self.cell=[]
    def handle_data(self,data):
        if self.inside_cell:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.inside_cell:
            self.cells.append("".join(self.cell).strip());self.inside_cell=False
        if tag=="tr" and self.inside_tr:
            if self.cells:self.rows.append(self.cells)
            self.inside_tr=False

def fetch_wantgoo_ex_etf():
    html=get(URLS["marginMaintenanceExEtf"],timeout=25)
    parser=_WantgooRows();parser.feed(html)
    found=0
    for row in parser.rows:
        if len(row)<4:continue
        mmdd=re.fullmatch(r"(\d{1,2})/(\d{1,2})",row[0].strip())
        if not mmdd:continue
        # The row columns explicitly describe financing balance, change, maintenance rate.
        try:
            month,day=map(int,mmdd.groups())
            year=CUTOFF.year-(1 if month>CUTOFF.month+2 else 0)
            date=dt.date(year,month,day).isoformat()
            maint=row[3].replace("%","").strip()
            value=_number(maint)
            if not 80<=value<=500:continue
            add("marginMaintenanceExEtf",date,value)
            found+=1
        except (ValueError,TypeError):continue
    SOURCE["marginMaintenanceExEtf"]={"name":"Wantgoo TAIEX margin trading excludes ETFs, financing maintenance (%)","url":URLS["marginMaintenanceExEtf"]}
    if found<1:raise ValueError("Wantgoo HTML has no verifiable dated ETF-excluded maintenance rows")
    return found

def main():
    load_seed()
    if os.environ.get("JENBAO_ETF_ONLY")=="1":
        attempt("VOO_Yahoo",lambda:fetch_yahoo("VOO","voo"))
        attempt("QQQ_Yahoo",lambda:fetch_yahoo("QQQ","qqq"))
    elif os.environ.get("JENBAO_YIELD_ONLY")=="1":
        attempt("US10Y_FRED",lambda:fetch_fred("us10yYield","DGS10"))
        attempt("US10Y_MINUS_US2Y_FRED",lambda:fetch_fred("us10y2ySpread","T10Y2Y"))
        attempt("FED_FUNDS_EFFECTIVE_DFF_FRED",lambda:fetch_fred("fedFundsEffective","DFF"))
    else:
        full_refresh()
    finalize_history(include_credit=not (os.environ.get("JENBAO_ETF_ONLY")=="1" or os.environ.get("JENBAO_YIELD_ONLY")=="1"))

def full_refresh():
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
    attempt("US10Y_FRED",lambda:fetch_fred("us10yYield","DGS10"))
    attempt("US10Y_MINUS_US2Y_FRED",lambda:fetch_fred("us10y2ySpread","T10Y2Y"))
    attempt("FED_FUNDS_EFFECTIVE_DFF_FRED",lambda:fetch_fred("fedFundsEffective","DFF"))
    attempt("VOO_Yahoo",lambda:fetch_yahoo("VOO","voo"))
    attempt("QQQ_Yahoo",lambda:fetch_yahoo("QQQ","qqq"))
    attempt("TWSE_FOREIGN",fetch_foreign_daily)
    attempt("TWSE_MARGIN",fetch_margin_daily)
    attempt("WANTGOO_EX_ETF",fetch_wantgoo_ex_etf)
def finalize_history(include_credit=False):
    archive = json.loads(DEST.read_text(encoding="utf-8")) if DEST.exists() else {}
    retained = {row["date"]: row for row in archive.get("rows", [])}
    dates = sorted(set(retained).union(day for ser in OBS.values() for day in ser))
    rows=[]
    for day in dates:
        item=retained.get(day, {"date":day})
        for key in FIELDS:
            if day in OBS[key]:item.setdefault(key, OBS[key][day])
        rows.append(item)
    # Permanent archive: NEVER truncate stored market history based on chart lookback windows.
    # Chart windows 20/60/120/240 days are presentation filters only.
    stats=archive.get("stats", {})
    for key in FIELDS:
        values=[(r["date"],r[key]) for r in rows if key in r]
        stats[key]={
          **stats.get(key, {}),
          "count":len(values),
          "first":values[0][0] if values else None,
          "last":values[-1][0] if values else None,
          "lastValue":values[-1][1] if values else None,
          "status":"ready" if len(values)>=55 else "partial",
          "source":stats.get(key, {}).get("source") or SOURCE.get(key,{"name":"Previously verified market observations","url":None})
        }
    out={
      "schemaVersion":1,
      "audience":"public-market-history",
      "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
      "cutoff":CUTOFF.isoformat(),
      "calendar":"source observation dates; never forward-fill; latest intraday excluded",
      "units":{"taiex":"index pts","dxy":"ICE US Dollar Index points","usdtwd":"TWD per USD","vix":"index pts","hyOas":"percent","marginDailyYi":"TWD 100 million daily finance balance change, including ETF","foreignNetYi":"TWD 100 million, TWSE foreign institution cash net","marginMaintenanceExEtf":"percent, Wantgoo margin maintenance excludes ETF","us10yYield":"percent, 10-year Treasury constant maturity yield (FRED DGS10)","us10y2ySpread":"percentage points, 10-year minus 2-year Treasury constant maturity spread (FRED T10Y2Y)","voo":"USD per VOO share, Yahoo Finance daily unadjusted Close; distributions excluded","qqq":"USD per QQQ share, Yahoo Finance daily unadjusted Close; distributions excluded","fedFundsEffective":"percent, effective federal funds overnight rate, FRED DFF (not FOMC target range)"},
      "stats":stats,
      "rows":rows
    }
    out = {**archive, **out, "units": {**out["units"], **archive.get("units", {})},
           "cutoff": max(out["cutoff"], archive.get("cutoff", ""))}
    if "foreignCumulativeYi" in stats:
        cumulative = stats["foreignCumulativeYi"]
        total = Decimal(str(cumulative["lastValue"]))
        for row in rows:
            if row["date"] <= cumulative["last"] or "taiex" not in row:
                continue
            if "foreignNetYi" not in row:
                break
            total += Decimal(str(row["foreignNetYi"]))
            row["foreignCumulativeYi"] = float(total)
            cumulative.update(last=row["date"], lastValue=float(total), count=cumulative["count"]+1)
    audit = out.get("marginMaintenance240dAudit")
    if audit:
        window = [r for r in rows if "taiex" in r][-audit["target"]:]
        missing = [r["date"] for r in window if "marginMaintenanceExEtf" not in r]
        observed = len(window) - len(missing)
        status = "partial" if missing else "complete"
        audit.update(targetFirst=window[0]["date"], targetLast=window[-1]["date"],
                     observed=observed, missing=len(missing), missingDates=missing, status=status)
        stats["marginMaintenanceExEtf"].update(targetFirst=audit["targetFirst"],
            targetLast=audit["targetLast"], observedInTarget=observed, missingInTarget=len(missing),
            coveragePct=round(100 * observed / len(window), 2), status="partial" if missing else "ready")
    if stats["taiex"]["count"]<20:raise SystemExit("FAIL: insufficient TAIEX source history")
    if include_credit:
        attempt("TWSE_CREDIT_CALLS", lambda: merge_credit(out))
    temp = DEST.with_suffix(".json.tmp")
    temp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(DEST)
    print("FINAL COUNTS",json.dumps({k:(v["count"],v["last"]) for k,v in stats.items()},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
