#!/usr/bin/env python3
"""Strict validator: this published JSON is PUBLIC market data only."""
import json, datetime as dt, pathlib, math, sys
path=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "public/market-history.json")
d=json.loads(path.read_text(encoding="utf-8"))
expected={"schemaVersion","audience","generatedAt","cutoff","calendar","units","stats","rows"}
if not expected.issubset(d) or set(d)-expected-{"backfillAudit","twseTurnoverAudit","marginMaintenance240dAudit"} or d["schemaVersion"]!=1 or d["audience"]!="public-market-history":
    raise SystemExit("FAIL: unexpected public market-history structure")
keys={"taiex","dxy","usdtwd","vix","hyOas","marginDailyYi","foreignNetYi","marginMaintenanceExEtf","us10yYield","us10y2ySpread","voo","qqq","fedFundsEffective","marketTurnoverYiTwd","dayTradeTurnoverYiTwd","dayTradeTurnoverSharePct"}
if "foreignCumulativeYi" in d["units"]:
    keys.add("foreignCumulativeYi")
# History backfill attaches only public aggregation metadata, never private fields.
if "backfillAudit" in d:
    audit=d["backfillAudit"]
    allowed={"targetObservations","collectedAt","before","after","unverifiedOrUnavailable","notes"}
    if not isinstance(audit,dict) or set(audit)!=allowed:
        raise SystemExit("FAIL: malformed public backfill audit")
    if not isinstance(audit["targetObservations"],int) or audit["targetObservations"]<1:
        raise SystemExit("FAIL: invalid backfill target")
    if not isinstance(audit["collectedAt"],str):
        raise SystemExit("FAIL: invalid backfill timestamp")
    for field in ("before","after"):
        data=audit[field]
        if not isinstance(data,dict) or not set(data).issubset(keys) or any(type(n)!=int or n<0 for n in data.values()):
            raise SystemExit("FAIL: invalid backfill series counts")
    for field in ("unverifiedOrUnavailable","notes"):
        if not isinstance(audit[field],list) or any(not isinstance(item,str) or len(item)>500 for item in audit[field]):
            raise SystemExit("FAIL: invalid public backfill notes")

# Official TWSE turnover is monetary成交金額(億元), not traded shares.
turnover_keys={"marketTurnoverYiTwd","dayTradeTurnoverYiTwd","dayTradeTurnoverSharePct"}
if "twseTurnoverAudit" in d:
    audit=d["twseTurnoverAudit"]
    required={"generatedAt","target","counts","marketDatesDownloaded","dayTradeDatesDownloaded",
              "dayTradeDatesReconciled","sourceIssues","mismatchExamples","mismatchCount","notes"}
    if not isinstance(audit,dict) or set(audit)!=required:
        raise SystemExit("FAIL: malformed TWSE market turnover audit")
    if not isinstance(audit["generatedAt"],str) or type(audit["target"])!=int or audit["target"]<1:
        raise SystemExit("FAIL: bad TWSE turnover audit metadata")
    if set(audit["counts"])!=turnover_keys or any(type(n)!=int or n<0 for n in audit["counts"].values()):
        raise SystemExit("FAIL: bad TWSE turnover audit counts")
    for field in ("marketDatesDownloaded","dayTradeDatesDownloaded","dayTradeDatesReconciled","mismatchCount"):
        if type(audit[field])!=int or audit[field]<0:
            raise SystemExit("FAIL: bad TWSE audit count")
    for field in ("sourceIssues","notes"):
        if not isinstance(audit[field],list) or any(type(v)!=str or len(v)>500 for v in audit[field]):
            raise SystemExit("FAIL: bad TWSE audit notes")
    if not isinstance(audit["mismatchExamples"],list):
        raise SystemExit("FAIL: bad TWSE audit mismatch list")
if set(d["units"])!=keys or set(d["stats"])!=keys:raise SystemExit("FAIL: unexpected market series")
if not isinstance(d["rows"],list):raise SystemExit("FAIL: malformed rows")
# Permanent data archive: never reject due to reaching 20/60/120/240/260 days or any count limit.
prev=None
bounds={"taiex":(1000,100000),"dxy":(50,200),"usdtwd":(15,60),"vix":(5,100),"hyOas":(0.1,40),"marginDailyYi":(-2000,2000),"foreignNetYi":(-100000,100000),"marginMaintenanceExEtf":(80,500),"us10yYield":(0,25),"us10y2ySpread":(-6,7),"voo":(20,2000),"qqq":(20,2000),"fedFundsEffective":(0,25),"marketTurnoverYiTwd":(0,200000),"dayTradeTurnoverYiTwd":(0,200000),"dayTradeTurnoverSharePct":(0,100)}
bounds["foreignCumulativeYi"]=(-1e12,1e12)
counts={k:0 for k in keys}
for r in d["rows"]:
    if set(r)-({"date"}|keys):raise SystemExit("FAIL: private or unexpected history key")
    day=dt.date.fromisoformat(r["date"])
    if prev is not None and day<=prev:raise SystemExit("FAIL: dates unordered or repeated")
    if day>dt.date.fromisoformat(d["cutoff"]):raise SystemExit("FAIL: intraday/future observation")
    prev=day
    for k in keys.intersection(r):
        v=r[k];a,b=bounds[k]
        if type(v) not in (int,float) or not math.isfinite(v) or not a<=v<=b:
            raise SystemExit(f"FAIL: invalid {k} observation")
        counts[k]+=1
for k,st in d["stats"].items():
    required={"count","first","last","lastValue","status","source"}
    optional=set()
    if k in {"foreignNetYi", "marginDailyYi"} and "backfillSource" in st:
        optional.add("backfillSource")
        src=st["backfillSource"]
        if set(src)!={"name","url"} or not isinstance(src["name"],str) or not src["url"].startswith("https://"):
            raise SystemExit("FAIL: malformed backfill source")
    if k=="marginMaintenanceExEtf":
        optional.update({"targetTradingDays","observedInTarget","missingInTarget","coveragePct",
                         "targetFirst","targetLast","dataScope","note"})
        for name in optional.intersection(st):
            typ = str if name in {"targetFirst","targetLast","dataScope","note"} else (float,int)
            if not isinstance(st[name],typ): raise SystemExit("FAIL: malformed maintenance metadata")
    if not required <= set(st) <= required|optional: raise SystemExit("FAIL: unexpected series metadata")
    if st["count"]!=counts[k]:raise SystemExit("FAIL: inconsistent count")
    if st["status"] not in ("ready","partial"):raise SystemExit("FAIL: invalid series status")
    src=st["source"]
    if set(src) not in ([{"name"},{"name","url"}] if k=="foreignCumulativeYi" else [{"name","url"}]) or not isinstance(src["name"],str):raise SystemExit("FAIL: bad source")
    if src.get("url") is not None and (not isinstance(src["url"],str) or not src["url"].startswith("https://")):raise SystemExit("FAIL: untrusted source")
if "twseTurnoverAudit" in d:
    audit=d["twseTurnoverAudit"]
    if any(audit["counts"][key]!=counts[key] for key in turnover_keys):
        raise SystemExit("FAIL: TWSE turnover audit inconsistent with observations")
if counts["taiex"]<20:raise SystemExit("FAIL: insufficient market series")
print("PASS: market-only history, chronological observations, no personal data",counts)

if "marginMaintenance240dAudit" in d:
    audit=d["marginMaintenance240dAudit"]
    required={"target","targetFirst","targetLast","observed","missing","status","source",
              "missingDates","historyPreserved","caveat","sourceSnapshots"}
    if set(audit)!=required or audit["target"]!=240 or audit["historyPreserved"] is not True:
        raise SystemExit("FAIL: malformed maintenance audit")
    if not isinstance(audit["caveat"],str) or audit["source"]!="https://www.wantgoo.com/stock/margin-trading/exclude-etf/taiex":
        raise SystemExit("FAIL: invalid maintenance attribution")
    window=[r for r in d["rows"] if "taiex" in r and r["date"]<=audit["targetLast"]][-audit["target"]:]
    gaps=[r["date"] for r in window if "marginMaintenanceExEtf" not in r]
    if (audit["missingDates"]!=gaps or audit["missing"]!=len(gaps) or
        audit["observed"]!=len(window)-len(gaps) or audit["targetFirst"]!=window[0]["date"]
        or audit["targetLast"]!=window[-1]["date"] or audit["status"]!=("partial" if gaps else "complete")):
        raise SystemExit("FAIL: inconsistent maintenance coverage")
    for snapshot in audit["sourceSnapshots"]:
        if set(snapshot)!={"asOf","validObservations","observationFirst","observationLast","extraction","sourceUrl"}:
            raise SystemExit("FAIL: unexpected maintenance snapshot fields")
        for field in ("asOf","observationFirst","observationLast"):
            dt.date.fromisoformat(snapshot[field])
        if type(snapshot["validObservations"])!=int or not isinstance(snapshot["extraction"],str) or snapshot["sourceUrl"]!=audit["source"]:
            raise SystemExit("FAIL: invalid maintenance snapshot")
