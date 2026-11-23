#!/usr/bin/env python3
"""Public market snapshot from dated verified sources; no forward fill."""
from pathlib import Path
from datetime import datetime, timezone
import json
from validate_public import validate

PUBLIC=Path(__file__).resolve().parents[1]/"public"
read=lambda name:json.loads((PUBLIC/name).read_text(encoding="utf-8"))

def last(rows,key):
    for row in reversed(rows):
        v=row.get(key)
        if type(v) in (float,int):return row["date"],v
    return None

def center_latest(center,key):
    rows=center.get(key)
    if isinstance(rows,list) and rows and len(rows[-1])==2 and type(rows[-1][1]) in (int,float):
        return rows[-1][0],rows[-1][1]
    return None

def main():
    snapshot=read("market-data.json")
    history=read("market-history.json")
    ohlc=read("index-ohlc-history.json")
    center=read("market-center-history.json")
    records=ohlc["series"]["taiex"]["rows"]
    if len(records)<240:raise SystemExit("No verified TAIEX OHLC history")
    day=records[-1]["date"]
    if day<snapshot["asOf"]:raise SystemExit("Refuse older archive as daily summary")
    m=snapshot["market"];used={}
    def write(key,value):
        if value is None:return
        observed,val=value
        if type(val) not in (int,float):return
        m[key]=val
        used[key]=(observed,val)
    write("taiex",(day,records[-1]["close"]))
    m["taiexChange"]=round((records[-1]["close"]/records[-2]["close"]-1)*100,4)
    for n in (5,10,20,60,120,240):
        m["ma"+str(n)]=round(sum(r["close"] for r in records[-n:])/n,4)
    history_keys={"dxy":"dxy","usdtwd":"usdtwd","vix":"vix",
                  "hyOas":"hyOas","us10y":"us10yYield",
                  "marginDailyYi":"marginDailyYi",
                  "foreignNetYi":"foreignNetYi",
                  "marginMaintenance":"marginMaintenanceExEtf"}
    center_keys={"singleBOas":"singleBOas",
                 "sofrMinusIorb":"sofrMinusIorbBp",
                 "t10yie":"t10yie","t5yie":"t5yie",
                 "marginBalanceYi":"marginBalanceYi",
                 "cnn":"cnnFearGreed","move":"move",
                 "futuresNetContracts":"foreignTxOpenInterestNetContracts",
                 "oil":"wtiFuturesUsd","goldPrice":"goldSpot"}
    for key,field in history_keys.items():write(key,last(history["rows"],field))
    for key,field in center_keys.items():write(key,center_latest(center,field))
    if "marginMaintenance" in used:m["marginMaintenanceAsOf"]=used["marginMaintenance"][0]
    snapshot["asOf"]=day
    snapshot["updatedAt"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot["dataStatus"]="partial"
    snapshot["headline"]=f"台股最新正式收盤 {day}：{records[-1]['close']:,.2f} 點；其他市場指標各按自身觀測日"
    summary=[]
    for key in ("taiex","vix","usdtwd","hyOas","foreignNetYi"):
        if key in used:
            d,v=used[key]
            summary.append(f"{key} {v:,.3f}（觀測日 {d}）")
    snapshot["summary"]="｜".join(summary)
    snapshot["marketHistory"]=[{"date":r["date"],"taiex":r["close"]} for r in records[-30:]]
    source_links={
      "taiex":"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST",
      "vix":"https://fred.stlouisfed.org/series/VIXCLS",
      "hyOas":"https://fred.stlouisfed.org/series/BAMLH0A0HYM2",
      "us10y":"https://fred.stlouisfed.org/series/DGS10",
      "singleBOas":"https://fred.stlouisfed.org/series/BAMLH0A2HYB",
      "marginDailyYi":"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
      "marginMaintenance":"https://www.wantgoo.com/stock/margin-trading/exclude-etf/taiex",
      "foreignNetYi":"https://www.twse.com.tw/rwd/zh/fund/BFI82U",
      "usdtwd":"https://finance.yahoo.com/quote/TWD=X/history/",
      "dxy":"https://finance.yahoo.com/quote/DX-Y.NYB/history/",
      "t10yie":"https://fred.stlouisfed.org/series/T10YIE",
      "t5yie":"https://fred.stlouisfed.org/series/T5YIE",
      "sofrMinusIorb":"https://fred.stlouisfed.org/series/SOFR"}
    snapshot["sources"]=[{"label":k+" 觀測日 "+d,"date":d,"url":source_links[k]}
        for k,(d,_) in used.items() if k in source_links]
    note="各指標保留自身原始觀測日，來源延遲不以最新交易日補值；市場敘事僅引用已核對資料。"
    previous=list(snapshot.get("notes",[]))
    if note not in previous:previous.append(note)
    snapshot["notes"]=previous[-20:]
    validate(snapshot)
    dest=PUBLIC/"market-data.json"
    tmp=PUBLIC/"market-data.json.tmp"
    tmp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(dest)
    print("SUMMARY REBUILT",day,{k:d for k,(d,_) in used.items()})
if __name__=="__main__":main()
