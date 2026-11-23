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
 try:pending["marginBalanceYi"]=fetch_margin()
 except Exception as error:problems.append("marginBalanceYi: "+str(error)[:120])
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
