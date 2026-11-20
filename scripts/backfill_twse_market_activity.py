#!/usr/bin/env python3
"""Add TWSE market share turnover and official day-trade share ratio to 240-day history.

Sources:
- /rwd/zh/afterTrading/FMTQIK (market volume in shares, by month)
- /rwd/zh/afterTrading/TWTB4U (official daily day-trading market statistics)
No imputation. No mixing share-volume ratio with turnover-value ratio.
"""
import datetime as dt
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

PATH = pathlib.Path("public/market-history.json")
TODAY = dt.datetime.now(dt.timezone.utc).date()
TARGET = 240
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; market-research/1.0)",
           "Accept": "application/json"}
SOURCES = {
    "marketVolumeYiShares": {"name":"TWSE FMTQIK daily market成交股數, 億股",
        "url":"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"},
    "dayTradeVolumeSharePct": {"name":"TWSE TWTB4U official day-traded shares / all market shares, %",
        "url":"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U"},
    "dayTradeVolumeYiShares": {"name":"TWSE TWTB4U total day-traded shares, 億股",
        "url":"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U"}
}

def number(x):
    try:
        v = float(str(x).replace(",", "").replace("%", "").strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def get(url):
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(req,timeout=18) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except Exception as e:
            if attempt == 2:
                print("FETCH FAILED",url.split("?")[0],str(e)[:120])
                return None
            time.sleep(attempt+1)

def report(url, params):
    return get(url+"?"+urllib.parse.urlencode(params))

def roc_date(s):
    try:
        y,m,d=(int(x) for x in str(s).split("/"))
        date=dt.date(y+1911,m,d)
        return date.isoformat() if date<=TODAY else None
    except Exception:
        return None

def traverse_tables(document):
    if not isinstance(document,dict): return
    if "fields" in document and "data" in document:
        yield document
    for item in document.get("tables",[]):
        if isinstance(item,dict):
            yield from traverse_tables(item)

def compact(s):
    return str(s).replace(" ","").replace("　","").replace("\n","").strip()

def fmtqik(rows, months):
    count=0
    for first in months:
        obj=report("https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK",
                   {"response":"json","date":first.strftime("%Y%m%d")})
        for tab in traverse_tables(obj):
            fields=[compact(x) for x in tab["fields"]]
            try: idx=fields.index("成交股數")
            except ValueError: continue
            for r in tab["data"]:
                if not isinstance(r,list) or len(r)<=idx: continue
                day=roc_date(r[0])
                v=number(r[idx])
                if day and v is not None and v>=0:
                    rows.setdefault(day,{"date":day}).setdefault("marketVolumeYiShares",round(v/1e8,6))
                    count+=1
            break
        time.sleep(0.12)
    return count

def daytrade_report(date):
    params={"response":"json","date":date.replace("-",""),"selectType":"All"}
    for endpoint in ("https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U",
                     "https://www.twse.com.tw/exchangeReport/TWTB4U"):
        obj=report(endpoint,params)
        for table in traverse_tables(obj):
            fields=[compact(f) for f in table["fields"]]
            volume_col=next((i for i,f in enumerate(fields) if "當日沖銷交易總成交股數" in f and "占" not in f),None)
            ratio_col=next((i for i,f in enumerate(fields) if "當日沖銷交易總成交股數占市場比重" in f),None)
            if volume_col is None or ratio_col is None: continue
            for row in table["data"]:
                if not isinstance(row,list) or len(row)<=max(volume_col,ratio_col):continue
                v=number(row[volume_col]);ratio=number(row[ratio_col])
                if v is not None and v>=0 and ratio is not None and 0<=ratio<=100:
                    return round(v/1e8,6),round(ratio,4)
        # Do not derive an unofficial ratio from market value or incomplete records.
    return None

def update_stats(doc, rows, key):
    records=sorted((day, r[key]) for day,r in rows.items()
                   if isinstance(r.get(key),(int,float)) and math.isfinite(r[key]))
    entry=doc.setdefault("stats",{}).setdefault(key,{})
    if records:
        entry.update(count=len(records),first=records[0][0],
                     last=records[-1][0],lastValue=records[-1][1],
                     status="ready" if len(records)>=TARGET else "partial",
                     source=SOURCES[key])
    else:
        entry.update(count=0,status="partial",source=SOURCES[key])
    return len(records)

def main():
    doc=json.loads(PATH.read_text(encoding="utf-8"))
    rows={r["date"]:r for r in doc["rows"] if "date" in r}
    doc.setdefault("units",{}).update({
        "marketVolumeYiShares":"100 million shares, TWSE FMTQIK daily market trading volume",
        "dayTradeVolumeSharePct":"percent, TWSE official TWTB4U day-traded share volume / market share volume",
        "dayTradeVolumeYiShares":"100 million shares, TWSE TWTB4U day-trading matched share volume"})
    month=(TODAY-dt.timedelta(days=560)).replace(day=1)
    months=[]
    while month<=TODAY:
        months.append(month)
        month=(month.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    print("TWSE monthly market share volume observations:",fmtqik(rows,months))
    # Restrict day-trade requests to official index trading dates; 260 to allow
    # sporadic unavailable records. Re-check T, T+1, T+2 observations every run.
    sessions=sorted((day for day,r in rows.items() if isinstance(r.get("taiex"),(float,int))
                     and day <= TODAY.isoformat()),reverse=True)
    selected=sessions[:300]
    attempts=0;filled=0
    for day in selected:
        r=rows[day]
        days_ago=(TODAY-dt.date.fromisoformat(day)).days
        if days_ago>8 and "dayTradeVolumeSharePct" in r and "dayTradeVolumeYiShares" in r:
            continue
        pair=daytrade_report(day)
        attempts+=1
        if pair is not None:
            volume, ratio=pair
            r["dayTradeVolumeYiShares"]=volume
            r["dayTradeVolumeSharePct"]=ratio
            filled+=1
        time.sleep(0.10)
    doc["rows"]=[rows[d] for d in sorted(rows)]
    counts={k:update_stats(doc,rows,k) for k in SOURCES}
    doc["twseActivityAudit"]={
        "checkedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
        "target":TARGET,"counts":counts,
        "dayTradeDatesRequested":attempts,"dayTradeReportsParsed":filled,
        "notes":["Market volume counts shares, not value in TWD.",
                 "Day-trade ratio is TWSE published share-volume ratio, not turnover-value ratio.",
                 "T to T+2 figures are subject to official revision.",
                 "Missing data are left missing, never filled with zero or interpolation."]
    }
    payload=json.dumps(doc,ensure_ascii=False,indent=2)+"\n"
    before=PATH.read_text(encoding="utf-8")
    if payload!=before:
        tmp=PATH.with_suffix(".tmp")
        tmp.write_text(payload,encoding="utf-8")
        tmp.replace(PATH)
    print(json.dumps(doc["twseActivityAudit"],ensure_ascii=False))

if __name__=="__main__":
    main()
