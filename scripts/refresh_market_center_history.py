#!/usr/bin/env python3
"""Append independently dated, public market observations to center archive.
Old values are immutable; missing feeds never become synthetic points.
"""
import csv
import datetime as dt
import io
import json
import math
import pathlib
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

PATH=pathlib.Path(__file__).resolve().parents[1]/"public"/"market-center-history.json"
TODAY=dt.datetime.now(ZoneInfo("Asia/Taipei")).date()
CUTOFF=TODAY-dt.timedelta(days=1)
START=(CUTOFF-dt.timedelta(days=48)).isoformat()
FRED={
 "singleBOas":"BAMLH0A2HYB",
 "cccOas":"BAMLH0A3HYC",
 "cccYield":"BAMLH0A3HYCEY",
 "tgcr":"TGCRRATE",
 "us1y":"DGS1","us2y":"DGS2","us3y":"DGS3",
 "us5y":"DGS5","us30y":"DGS30",
 "sofr":"SOFR","iorb":"IORB",
 "t5yie":"T5YIE","t10yie":"T10YIE",
 "inflation5y5y":"T5YIFR",
 "nfci":"NFCI",
 "mortgage":"MORTGAGE30US",
}
YAHOO={
 "2330TW":"2330.TW","006208TW":"006208.TW",
 "IXIC":"^IXIC","SOX":"^SOX","move":"^MOVE",
 "goldFuturesUsd":"GC=F","wtiFuturesUsd":"CL=F",
}
def download(url,timeout=12):
 req=urllib.request.Request(url,headers={
    "User-Agent":"Mozilla/5.0 (JenbaoPublicCenter/1.0)",
    "Accept":"application/json,text/csv,*/*","Accept-Encoding":"identity"})
 with urllib.request.urlopen(req,timeout=timeout) as response:
    return response.read(7000000).decode("utf-8-sig")

def valid_date(s):
 try:
    value=dt.date.fromisoformat(str(s))
    return value.isoformat() if value<=CUTOFF and value>=CUTOFF-dt.timedelta(days=365) else None
 except (ValueError,TypeError):
    return None

def valid_number(x):
 try:
    v=float(str(x).replace(",",""))
    return v if math.isfinite(v) else None
 except (ValueError,TypeError):
    return None

def fetch_fred(code):
 params=urllib.parse.urlencode({"id":code,"cosd":START,"coed":CUTOFF.isoformat()})
 url="https://fred.stlouisfed.org/graph/fredgraph.csv?"+params
 found={}
 for row in csv.DictReader(io.StringIO(download(url))):
    day=valid_date(row.get("observation_date") or row.get("DATE") or row.get("date"))
    value=valid_number(row.get(code))
    if day and value is not None:found[day]=round(value,7)
 if not found:raise ValueError("No dated observed values for "+code)
 return found

def fetch_yahoo(symbol):
 url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol,safe="")
 url+="?interval=1d&range=1mo"
 doc=json.loads(download(url))
 j=doc["chart"]["result"][0]
 if j["meta"]["symbol"]!=symbol:raise ValueError("Unexpected Yahoo symbol")
 tz=ZoneInfo(j["meta"]["exchangeTimezoneName"])
 dates=j.get("timestamp") or []
 closes=j["indicators"]["quote"][0]["close"]
 found={}
 for stamp,value in zip(dates,closes):
    day=valid_date(dt.datetime.fromtimestamp(int(stamp),tz).date().isoformat())
    v=valid_number(value)
    if day and v is not None and v>0:found[day]=round(v,7)
 if not found:raise ValueError("No completed daily quotes for "+symbol)
 return found

def fetch_twse_stock(stock):
 """Fallback: official TWSE STOCK_DAY actual close for a named listed security.
 Only append independently dated completed sessions. Never estimate missing days.
 """
 month=CUTOFF.replace(day=1)
 stamp=month.strftime("%Y%m%d")
 args=urllib.parse.urlencode({"response":"json","date":stamp,"stockNo":stock})
 url="https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"+args
 doc=json.loads(download(url,timeout=18))
 if doc.get("stat")!="OK" or not isinstance(doc.get("data"),list):
    raise ValueError("Official TWSE STOCK_DAY incomplete for "+stock)
 fields=doc.get("fields") or []
 col=next((i for i,n in enumerate(fields) if "收盤價" in str(n)),None)
 if col is None:raise ValueError("STOCK_DAY no validated closing-price column")
 vals={}
 for row in doc["data"]:
    if not isinstance(row,list) or len(row)<=col:continue
    try:
        year,month,day=(int(x) for x in str(row[0]).split("/"))
        observed=valid_date(dt.date(year+1911,month,day).isoformat())
    except (TypeError,ValueError):continue
    price=valid_number(row[col])
    if observed and price is not None and 1<=price<=5000:
        vals[observed]=round(price,5)
 if not vals:raise ValueError("STOCK_DAY no dated prices for "+stock)
 return vals

def fetch_margin():
 # TWSE MI_MARGN: quoted balances are in TWD thousand; /100000 => TWD 100m.
 # Reject mismatched dates, unlabelled rows or implausible balances.
 for offset in range(7):
    day=CUTOFF-dt.timedelta(days=offset)
    if day.weekday()>=5:continue
    stamp=day.strftime("%Y%m%d")
    url="https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?"+urllib.parse.urlencode({
        "response":"json","date":stamp,"selectType":"MS"})
    try:
        obj=json.loads(download(url,timeout=10))
        if str(obj.get("date"))!=stamp:continue
        tables=[obj]+[x for x in obj.get("tables",[]) if isinstance(x,dict)]
        for table in tables:
            columns=table.get("fields") or []
            # Official TWSE summary is: item, buy, sell, repayment, previous, today.
            if len(columns)<6 or "前日餘額" not in str(columns[4]) or "今日餘額" not in str(columns[5]):continue
            for row in table.get("data",[]):
                if not isinstance(row,list) or len(row)<6 or "融資金額" not in str(row[0]):continue
                balance=valid_number(row[5])
                if balance is None:continue
                yi=round(balance/100000,7)
                if 1000<=yi<=20000:return {day.isoformat():yi}
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        continue
 raise ValueError("TWSE MI_MARGN dated summary unavailable; previous retained")

def fetch_cnn_mirror():
    # Same CNN-specific mirror used by the existing extended-history collector.
    url="https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/datasets/cnn_fear_greed.csv"
    grouped={}
    for row in csv.DictReader(io.StringIO(download(url))):
        day=valid_date(row.get("Date"))
        val=valid_number(row.get("Fear Greed"))
        if day and val is not None and 0<=val<=100:
            grouped.setdefault(day,set()).add(val)
    found={d:next(iter(v)) for d,v in grouped.items() if len(v)==1}
    if not found:raise ValueError("No unambiguous dated CNN mirror values")
    return found

def fetch_taifex_positions():
    # Official contract-specific CSV, POST; no mini/micro or all-contract aggregate.
    params=urllib.parse.urlencode({"queryStartDate":(CUTOFF-dt.timedelta(days=14)).strftime("%Y/%m/%d"),
        "queryEndDate":CUTOFF.strftime("%Y/%m/%d"),"commodityId":"TXF"})
    url="https://www.taifex.com.tw/cht/3/futContractsDateDown"
    req=urllib.request.Request(url,data=params.encode(),headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv,*/*",
         "Content-Type":"application/x-www-form-urlencoded","Referer":"https://www.taifex.com.tw/cht/3/futContractsDateView"})
    with urllib.request.urlopen(req,timeout=20) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError("TAIFEX response limit")
    try: body=raw.decode("utf-8-sig")
    except UnicodeDecodeError:body=raw.decode("cp950")
    reader=csv.DictReader(io.StringIO(body))
    reader.fieldnames=[x.strip() for x in (reader.fieldnames or [])]
    required={"日期","商品名稱","身份別","多方未平倉口數","空方未平倉口數","多空未平倉口數淨額"}
    if not required.issubset(reader.fieldnames):raise ValueError("Unexpected TAIFEX CSV schema")
    found={}
    for row in reader:
        if row["商品名稱"].strip() not in ("臺股期貨","台股期貨") or row["身份別"].strip()!="外資及陸資":continue
        stamp=dt.datetime.strptime(row["日期"].strip(),"%Y/%m/%d").date().isoformat()
        day=valid_date(stamp)
        if not day:continue
        long,short,net=(int(row[k].replace(",","").strip()) for k in ("多方未平倉口數","空方未平倉口數","多空未平倉口數淨額"))
        if long<0 or short<0 or long-short!=net:raise ValueError("TAIFEX net-position arithmetic mismatch")
        if day in found and found[day]!=net:raise ValueError("TAIFEX conflicting duplicate")
        found[day]=net
    if not found:raise ValueError("No official foreign TXF observations")
    return found

def main():
 center=json.loads(PATH.read_text(encoding="utf-8"))
 if not isinstance(center,dict):raise RuntimeError("Invalid center archive")
 pending={}
 problems=[]
 for key,code in FRED.items():
    if key not in center:raise RuntimeError("Unknown center field: "+key)
    try:pending[key]=fetch_fred(code)
    except Exception as error:problems.append(key+": "+str(error)[:100])
 for key,code in YAHOO.items():
    if key not in center:raise RuntimeError("Unknown center field: "+key)
    try:pending[key]=fetch_yahoo(code)
    except Exception as error:problems.append(key+": "+str(error)[:100])
 # Official listed-security closes fill dates that Yahoo currently omits.
 # The preexisting center archive always wins on overlapping observations.
 for stock,key in (("006208","006208TW"),("2330","2330TW")):
    try:
        verified=fetch_twse_stock(stock)
        pending.setdefault(key,{}).update(verified)
    except Exception as error:problems.append("TWSE "+stock+": "+str(error)[:100])
 try:pending["marginBalanceYi"]=fetch_margin()
 except Exception as error:problems.append("marginBalanceYi: "+str(error)[:120])
 for key,fn in (("cnnFearGreed",fetch_cnn_mirror),("foreignTxOpenInterestNetContracts",fetch_taifex_positions)):
    try:pending[key]=fn()
    except Exception as error:problems.append(key+": "+str(error)[:150])
 if "sofr" in pending and "iorb" in pending:
    common=pending["sofr"].keys() & pending["iorb"].keys()
    pending["sofrMinusIorbBp"]={day:round((pending["sofr"][day]-pending["iorb"][day])*100,5)
        for day in common}
 totals={}
 for key,updates in pending.items():
    original=center.get(key)
    if not isinstance(original,list) or any(not isinstance(row,list) or len(row)!=2 for row in original):
        raise RuntimeError("Unexpected historical row structure for "+key)
    rows={day:value for day,value in original}
    old=len(rows)
    for day,value in updates.items():
        if day not in rows:rows[day]=value
    center[key]=[[d,rows[d]] for d in sorted(rows)]
    totals[key]={"added":len(rows)-old,"last":center[key][-1][0]}
 if not any(v["added"] for v in totals.values()):
    print("CENTER NO NEW OBSERVATIONS",json.dumps(totals,ensure_ascii=False),flush=True)
 else:
    temp=PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(center,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(PATH)
    print("CENTER UPDATE",json.dumps(totals,ensure_ascii=False),flush=True)
 if problems:print("CENTER SOURCE WARN",json.dumps(problems,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
