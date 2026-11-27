#!/usr/bin/env python3
"""Public market snapshot from dated verified sources; no forward fill."""
from pathlib import Path
from datetime import datetime, timezone
import json
from validate_public import validate
from market_material_write import write_public_if_materially_changed

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
    # Derive coverage and freshness from the exact history revision consumed.
    audit=history.get("marginMaintenance240dAudit")
    label="扣 ETF 融資維持率時效"
    snapshot["alerts"]=[x for x in snapshot.get("alerts",[]) if x.get("label")!=label]
    if audit:
        snapshot["marginMaintenanceCoverage"]={
            "targetTradingDays":audit["target"], "observedTradingDays":audit["observed"],
            "missingTradingDays":audit["missing"], "targetFirst":audit["targetFirst"],
            "targetLast":audit["targetLast"], "status":audit["status"], "sourceUrl":audit["source"]}
        latest=m.get("marginMaintenanceAsOf","")
        lag=sum(d>latest for d in audit["missingDates"])
        if lag:
            status="FAIL" if lag>=2 else "WARN"
            detail=f"{status}：觀測日 {latest}，落後已歸檔台股交易日 {lag} 日；不得視為最新值"
            snapshot["alerts"].append({"label":label,"status":status,"detail":detail})
            print("::warning::"+detail,flush=True)
        m["marginMaintenanceScope"]="TWSE financing maintenance excluding ETF (Wantgoo; observed date, no forward-fill)"
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
      "sofrMinusIorb":"https://fred.stlouisfed.org/series/SOFR",
      "marginBalanceYi":"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
      "move":"https://finance.yahoo.com/quote/%5EMOVE/",
      "cnn":"https://edition.cnn.com/markets/fear-and-greed",
      "futuresNetContracts":"https://www.taifex.com.tw/cht/3/futContractsDate",
      "oil":"https://finance.yahoo.com/quote/CL%3DF/",
      "goldPrice":"https://metalcharts.org/xauusd-historical-data"}
    snapshot["sources"]=[{"label":k+" 觀測日 "+d,"date":d,"url":source_links[k]}
        for k,(d,_) in used.items() if k in source_links]
    note="各指標保留自身原始觀測日，來源延遲不以最新交易日補值；市場敘事僅引用已核對資料。"
    snapshot["notes"]=[note]+[
        f"{key} 實際觀測日 {value[0]}；不保證等於首頁加權指數收盤日"
        for key,value in used.items()
    ][:19]
    validate(snapshot)
    dest=PUBLIC/"market-data.json"
    changed=write_public_if_materially_changed(dest,snapshot,kind="market-data")
    print("SUMMARY UPDATED" if changed else "SUMMARY UNCHANGED",day,{k:d for k,(d,_) in used.items()})
if __name__=="__main__":main()
