#!/usr/bin/env python3
"""Safely backfill TWSE daily cash flow & margin; reject unvalidated definitions."""
import datetime as dt
import json
import math
import pathlib
import time
import urllib.parse
import urllib.request

FILE = pathlib.Path("public/market-history.json")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TODAY = dt.datetime.now(dt.timezone.utc).date()
START = TODAY - dt.timedelta(days=560)
LIMIT = 500

def fetch(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=18) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1.2 * (attempt + 1))

def num(value):
    try:
        val = float(str(value).strip().replace(",", "").replace("+", ""))
        return val if math.isfinite(val) else None
    except (ValueError, TypeError):
        return None

def fetch_day(date, category):
    fmt = date.strftime("%Y%m%d")
    if category == "foreign":
        params = urllib.parse.urlencode({"dayDate":fmt, "type":"day", "response":"json"})
        return fetch("https://www.twse.com.tw/rwd/zh/fund/BFI82U?" + params)
    params = urllib.parse.urlencode({"date":fmt, "selectType":"ALL", "response":"json"})
    return fetch("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?" + params)

def foreign_net(obj):
    if not obj or not obj.get("data"):
        return None
    # Only match exact named investor class. A total of three institutional
    # investors or proprietary foreign traders is NOT the same series.
    for row in obj["data"]:
        if not isinstance(row,list) or len(row)<4:
            continue
        label = str(row[0]).strip().replace(" ", "").replace("　", "")
        if label in ("外資及陸資(不含外資自營商)", "外資及陸資（不含外資自營商）"):
            value=num(row[3])
            if value is not None:
                return round(value/1e8, 6)
    return None

def margin_daily(obj):
    if not obj:
        return None
    # MI_MARGN reports money in thousands of TWD; use the outstanding
    # previous-day and current-day columns, not purchases or share volume.
    fields=obj.get("fields") or []
    if not obj.get("data") or not fields:
        return None
    prev_index = next((i for i,v in enumerate(fields) if str(v).strip()=="前日餘額"), None)
    current_index = next((i for i,v in enumerate(fields) if str(v).strip()=="今日餘額"), None)
    if prev_index is None or current_index is None:
        return None
    for row in obj["data"]:
        if not isinstance(row,list) or len(row)<=max(prev_index,current_index):
            continue
        if str(row[0]).replace(" ","").startswith("融資金額(仟元)"):
            prev=num(row[prev_index]);current=num(row[current_index])
            if prev is not None and current is not None:
                return round((current-prev)/100000,6)
    return None

def run():
    doc=json.loads(FILE.read_text(encoding="utf-8"))
    bydate={r["date"]:r for r in doc.get("rows",[]) if "date" in r}
    config=[("foreignNetYi","foreign",foreign_net),("marginDailyYi","margin",margin_daily)]
    audit={}
    changed=False
    dates=[TODAY-dt.timedelta(days=i) for i in range((TODAY-START).days+1)]
    for key,cat,parse in config:
        previous={d: num(r[key]) for d,r in bydate.items() if key in r and num(r[key]) is not None}
        observed={}
        fetched=0
        for date in dates:
            if date.weekday()>4:
                continue
            d=date.isoformat()
            if d in previous:
                continue
            obj=fetch_day(date,cat)
            fetched+=1
            val=parse(obj)
            if val is not None:
                observed[d]=val
            if fetched>=LIMIT:
                break
        # No substitution, only actual official dates. Verify overlapping
        # observations separately, and keep original entries as authority.
        for d,val in observed.items():
            if d not in bydate:
                bydate[d]={"date":d}
            bydate[d][key]=val
        changed=changed or bool(observed)
        audit[key]={"before":len(previous),"new":len(observed),
                    "after":len(previous)+len(observed),
                    "requests":fetched,"verifiedProvider":"TWSE",
                    "sampleNew":dict(list(sorted(observed.items()))[:3])}
        if observed:
            combined={**previous, **observed}
            series=sorted(combined.items())
            doc["stats"][key].update({"count":len(series),"first":series[0][0],
                "last":series[-1][0],"lastValue":series[-1][1],
                "status":"ready" if len(series)>=240 else "partial"})
    print(json.dumps(audit,ensure_ascii=False))
    if changed:
        doc["rows"]=[bydate[k] for k in sorted(bydate)]
        doc["twseFlowBackfillAudit"]={"collectedAt":dt.datetime.now(dt.timezone.utc).isoformat(),"results":audit,
           "note":"No estimated or carried-forward values; only official TWSE reports"}
        tmp=FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        tmp.replace(FILE)
if __name__=="__main__":
    run()
