"""Increment public-only macro and intraday archives; preserve verified observations."""
import csv
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "data" / "history-1000"
FRED = {
    "singleBOas":"BAMLH0A2HYB", "t10yie":"T10YIE", "t5yie":"T5YIE",
    "us1y":"DGS1", "us2y":"DGS2", "us3y":"DGS3", "us5y":"DGS5", "us30y":"DGS30",
    "tgcr":"TGCRRATE", "inflation5y5y":"T5YIFR", "sofr":"SOFR", "iorb":"IORB",
}
YAHOO = {"move":"^MOVE", "wtiFuturesUsd":"CL=F", "goldFuturesUsd":"GC=F"}
BUND = "https://api.statistiken.bundesbank.de/rest/download/BBSSY/D.REN.EUR.A630.000000WT1010.A?format=csv&lang=en&startPeriod="
TODAY = dt.datetime.now(dt.timezone.utc).date()
START = (TODAY - dt.timedelta(days=1850)).isoformat()

def download(url):
    request = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8-sig")

def yahoo(symbol, interval):
    period = "5y" if interval == "1d" else "1mo"
    url = "https://query2.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="")
    result = json.loads(download(url + "?range=" + period + "&interval=" + interval))["chart"]["result"][0]
    meta = result["meta"]
    if meta["symbol"] != symbol or meta["dataGranularity"] != interval:
        raise ValueError("Unexpected source series")
    zone = ZoneInfo(meta["exchangeTimezoneName"])
    quotes = result["indicators"]["quote"][0]
    for i,stamp in enumerate(result["timestamp"]):
        t = dt.datetime.fromtimestamp(stamp,zone)
        if t.date() >= dt.datetime.now(zone).date() or t.weekday() >= 5:
            continue
        yield t, {k:quotes[k][i] for k in ("open","high","low","close")}

def merge(path, key, updates):
    rows = {}
    if path.exists():
        with path.open() as f:
            rows = {r[key]:r for r in csv.DictReader(f)}
    changed = False
    for day,values in updates:
        row = rows.setdefault(day,{key:day})
        for col,val in values.items():
            if not row.get(col) and val is not None and math.isfinite(val):
                row[col] = val
                changed = True
    if changed:
        cols = [key] + sorted(set().union(*(r.keys() for r in rows.values())) - {key})
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            w = csv.DictWriter(f,cols,lineterminator="\n")
            w.writeheader()
            w.writerows(rows[d] for d in sorted(rows))
        os.replace(tmp,path)

def fred(code):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + code + "&cosd=" + START
    return {r["observation_date"]:float(r[code]) for r in csv.DictReader(io.StringIO(download(url)))
            if r[code] not in ("",".") and dt.date.fromisoformat(r["observation_date"]) < TODAY}

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    daily = ROOT/"daily.csv"
    errors = []
    rates = {}
    def collect(label,fn):
        try:
            fn()
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            errors.append(label + ": " + str(exc))
    def rate(field,code):
        rates[field] = fred(code)
        merge(daily,"date",((d,{field:v}) for d,v in rates[field].items()))
    for field,code in FRED.items():
        collect(code,lambda:rate(field,code))
    if "sofr" in rates and "iorb" in rates:
        merge(daily,"date",((d,{"sofrMinusIorbBp":round(100*(v-rates["iorb"][d]),5)})
              for d,v in rates["sofr"].items() if d in rates["iorb"]))
    for field,symbol in YAHOO.items():
        collect(symbol,lambda:merge(daily,"date",((t.date().isoformat(),{field:r["close"]}) for t,r in yahoo(symbol,"1d"))))
    for code in ("DRBLACBS","DRTSCILM","PCEC96","RSAFS","PAYEMS","UMCSENT"):
        collect(code,lambda:merge(ROOT/"macro-releases.csv","observation_period",
            ((d,{code:v}) for d,v in fred(code).items())))
    def bund():
        data = list(csv.reader(io.StringIO(download(BUND+START))))
        if "BBSSY.D.REN.EUR.A630.000000WT1010.A" not in data[0]:
            raise ValueError("Unexpected Bundesbank series")
        merge(daily,"date",((r[0],{"de10y":float(r[1])}) for r in data if len(r)>1 and
              len(r[0])==10 and r[0][4]=="-" and r[1] not in (".","") and dt.date.fromisoformat(r[0])<TODAY))
    collect("Bund",bund)
    for name,symbol in [("taiex","^TWII"),("sp500","^GSPC")]:
        collect(symbol,lambda:merge(ROOT/(name+"-5m.csv"),"time",((t.isoformat(),r)
            for t,r in yahoo(symbol,"5m") if t.minute%5==0 and t.second==0 and
            all(v is not None and math.isfinite(v) and v>0 for v in r.values())
            and r["high"]==max(r.values()) and r["low"]==min(r.values()))))
    if errors:
        print("Source gaps:",*errors,sep="\n")

if __name__=="__main__":
    main()
