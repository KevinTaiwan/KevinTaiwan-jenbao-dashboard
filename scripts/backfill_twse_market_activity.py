#!/usr/bin/env python3
"""Backfill >=240 official TWSE *turnover value* (成交金額), NOT 成交股數.

FMTQIK month: market traded TWD value per trading date.
TWTB4U2 month: day-trading buy and sell traded TWD values and official
buy/sell value market-share percentages.
The day-trading numerator is (buy TWD + sell TWD) / 2 to avoid
counting a matched round-trip twice. This is the traded-value metric.
Never substitute '當沖成交股數占比' for this value ratio.
"""
import datetime as dt
import os
import json
import math
import pathlib
import re
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

FILE=pathlib.Path("public/market-history.json")
TODAY=dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
TARGET=1000
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; JenbaoPublicMarketData/1.0)",
         "Accept":"application/json"}
KEYS={
  "marketTurnoverYiTwd":{
    "name":"TWSE whole-market成交金額 (億元)",
    "url":"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"},
  "dayTradeTurnoverYiTwd":{
    "name":"TWSE day-trading traded value, (buy+sell)/2, 億元",
    "url":"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U2"},
  "dayTradeTurnoverSharePct":{
    "name":"TWSE day-trading成交金額占大盤成交金額, %",
    "url":"https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U2"}}

def n(x):
    try:
        z=float(str(x).replace(",","").replace("%","").strip())
        return z if math.isfinite(z) else None
    except (ValueError,TypeError):
        return None

def compact(x):
    return re.sub(r"\s+","",str(x)).replace("（","(").replace("）",")")

def rocdate(raw):
    try:
        y,m,d=[int(v) for v in str(raw).strip().split("/")]
        value=dt.date(y+1911,m,d)
        return value.isoformat() if value<=TODAY else None
    except Exception:
        return None

def fetch(url):
    error=None
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers=HEADERS)
            with urllib.request.urlopen(request,timeout=25) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except Exception as exc:
            error=exc
            time.sleep((attempt+1)*1.1)
    print("TWSE FETCH ERROR",url.split("?")[0],str(error)[:140])
    return None

def get_report(path,month):
    params=urllib.parse.urlencode({"response":"json","date":month.strftime("%Y%m%d")})
    section = "dayTrading" if path == "TWTB4U2" else "afterTrading"
    for hostpath in (f"https://www.twse.com.tw/rwd/zh/{section}/{path}",
                     f"https://www.twse.com.tw/exchangeReport/{path}"):
        doc=fetch(hostpath+"?"+params)
        if isinstance(doc,dict) and (doc.get("data") or doc.get("tables")):
            return doc
    return None

def tables(obj):
    if not isinstance(obj,dict):
        return
    if isinstance(obj.get("data"),list) and isinstance(obj.get("fields"),list):
        yield obj
    for value in obj.get("tables",[]) or []:
        if isinstance(value,dict):
            yield from tables(value)

def extract_market(obj):
    result={}
    for table in tables(obj):
        fields=[compact(x) for x in table["fields"]]
        moneyindex=next((i for i,field in enumerate(fields) if field=="成交金額"),None)
        if moneyindex is None:
            continue
        for row in table["data"]:
            if not isinstance(row,list) or len(row)<=moneyindex:continue
            day=rocdate(row[0])
            amount=n(row[moneyindex])
            if day and amount is not None and amount>0:
                result[day]=round(amount/1e8,6)
        if result:
            return result
    return result

def extract_daytrade(obj):
    result={}
    for table in tables(obj):
        fields=[compact(x) for x in table["fields"]]
        def idx(text,ratio):
            return next((i for i,f in enumerate(fields)
                         if text in f and (("占市場比重" in f)==ratio)),None)
        bi=idx("當日沖銷交易總買進成交金額",False)
        si=idx("當日沖銷交易總賣出成交金額",False)
        bri=idx("當日沖銷交易總買進成交金額",True)
        sri=idx("當日沖銷交易總賣出成交金額",True)
        if None in (bi,si,bri,sri):
            continue
        for row in table["data"]:
            if not isinstance(row,list) or len(row)<=max(bi,si,bri,sri):
                continue
            day=rocdate(row[0])
            buy,sell,buyratio,sellratio=(n(row[i]) for i in (bi,si,bri,sri))
            if (day and buy is not None and sell is not None and
                buyratio is not None and sellratio is not None
                and buy>0 and sell>0 and 0<=buyratio<=100 and 0<=sellratio<=100):
                result[day]=(buy,sell,buyratio,sellratio)
        if result:
            return result
    return result

def months():
    if os.environ.get("JENBAO_TWSE_INCREMENTAL")=="1":
        recent=(TODAY-dt.timedelta(days=40)).replace(day=1)
        latest=TODAY.replace(day=1)
        return sorted(set((recent,latest)))
    start=(TODAY-dt.timedelta(days=1570)).replace(day=1)
    out=[]
    while start<=TODAY:
        out.append(start)
        start=(start.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    return out

def stats(doc,rows,key):
    seq=sorted((day,row[key]) for day,row in rows.items()
               if isinstance(row.get(key),(float,int)) and math.isfinite(row[key]))
    entry=doc.setdefault("stats",{}).setdefault(key,{})
    entry.update({"count":len(seq),"status":"ready" if len(seq)>=TARGET else "partial",
                  "source":KEYS[key]})
    if seq:entry.update({"first":seq[0][0],"last":seq[-1][0],"lastValue":seq[-1][1]})
    return len(seq)

def main():
    doc=json.loads(FILE.read_text(encoding="utf-8"))
    rows={r["date"]:r for r in doc["rows"] if isinstance(r,dict) and "date" in r}
    market={}
    daytrade={}
    errors=[]
    for month in months():
        base=get_report("FMTQIK",month)
        trades=get_report("TWTB4U2",month)
        m=extract_market(base)
        t=extract_daytrade(trades)
        if not m:errors.append("FMTQIK "+month.isoformat())
        if not t:errors.append("TWTB4U2 "+month.isoformat())
        market.update(m)
        daytrade.update(t)
        print(month.strftime("%Y-%m"),"market",len(m),"daytrade",len(t),flush=True)
        time.sleep(0.12)

    mismatch=[]
    paired=0
    for day,value in sorted(market.items()):
        if day <= doc["cutoff"]:
            rows.setdefault(day,{"date":day}).setdefault("marketTurnoverYiTwd",value)
    for day,(buy,sell,buyratio,sellratio) in sorted(daytrade.items()):
        if day not in market or day > doc["cutoff"]:continue
        total_yi=market[day]
        if total_yi<=0:continue
        mean_yi=(buy+sell)/2/1e8
        ratio=100*mean_yi/total_yi
        official=(buyratio+sellratio)/2
        # Reject material denominator discrepancies rather than silently mix
        # different market universes or share-vs-value measures.
        if not(0<=ratio<=100) or abs(ratio-official)>0.75:
            mismatch.append({"date":day,"computed":round(ratio,3),
                             "twseOfficial":round(official,3)})
            continue
        entry=rows.setdefault(day,{"date":day})
        entry.setdefault("dayTradeTurnoverYiTwd",round(mean_yi,6))
        entry.setdefault("dayTradeTurnoverSharePct",round(ratio,4))
        paired+=1

    doc["units"]={
        **doc.get("units",{}),
        "marketTurnoverYiTwd":"TWD 100 million market trading value, TWSE FMTQIK 成交金額",
        "dayTradeTurnoverYiTwd":"TWD 100 million, (TWSE day-trade buy TWD + sell TWD)/2",
        "dayTradeTurnoverSharePct":"percent, TWSE day-trade avg buy/sell TWD value divided by FMTQIK market trading TWD value"}
    doc["rows"]=[rows[day] for day in sorted(rows)]
    counts={k:stats(doc,rows,k) for k in KEYS}
    doc["twseTurnoverAudit"]={
        "generatedAt":dt.datetime.now(dt.timezone.utc).isoformat(),
        "target":TARGET,"counts":counts,
        "marketDatesDownloaded":len(market),"dayTradeDatesDownloaded":len(daytrade),
        "dayTradeDatesReconciled":paired,
        "sourceIssues":errors[:30],"mismatchExamples":mismatch[:20],
        "mismatchCount":len(mismatch),
        "notes":["成交量依使用者指定採成交金額(億元)，不採成交股數",
                 "當沖成交金額=(買進成交金額+賣出成交金額)/2",
                 "股數當沖比重不得取代成交金額當沖比重",
                 "僅記錄證交所官方同日交易日資料，無插補、無補零"]}
    text=json.dumps(doc,ensure_ascii=False,indent=2)+"\n"
    tmp=FILE.with_suffix(".json.tmp")
    tmp.write_text(text,encoding="utf-8")
    tmp.replace(FILE)
    print(json.dumps(doc["twseTurnoverAudit"],ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
