"""Fail-closed approved public news schema and exchange-session validation."""
import argparse, hashlib, json, re
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
CATEGORIES=set("monetary_policy fiscal_policy inflation employment economic_growth trade_policy market_regulation semiconductor_earnings ai_infrastructure major_financial_event".split())
HOSTS={"Federal Reserve":{"www.federalreserve.gov","federalreserve.gov"},"US Treasury":{"home.treasury.gov","www.treasury.gov","treasury.gov"},"BLS":{"www.bls.gov","bls.gov"},"BEA":{"www.bea.gov","bea.gov"},"USTR":{"ustr.gov","www.ustr.gov"},"TWSE":{"www.twse.com.tw","twse.com.tw"},"FSC":{"www.fsc.gov.tw","fsc.gov.tw","law.fsc.gov.tw"},"TSMC":{"investor.tsmc.com","pr.tsmc.com"},"NVIDIA":{"nvidianews.nvidia.com","investor.nvidia.com"}}
FIELDS=set("eventId revision date kind title summary source url publishedAt eventAt effectiveAt reactionDates publicationAllowed quality".split())
def require(ok,msg):
    if not ok: raise ValueError(msg)
def day(s):
    require(isinstance(s,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",s),"date format")
    return date.fromisoformat(s)
def stamp(s):
    require(isinstance(s,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})",s),"timestamp must carry timezone")
    return datetime.fromisoformat(s)
def safe_url(s,source):
    if not isinstance(s,str) or len(s)>700 or not re.fullmatch(r"https://[a-z0-9.-]+/[A-Za-z0-9_./%~+-]+",s): return False
    return urlsplit(s).hostname in HOSTS.get(source,set()) and not re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f|5c|2f|3f|23)",s,re.I)
def sessions(root):
    o=json.loads((root/"index-ohlc-history.json").read_text())
    m=json.loads((root/"market-center-history.json").read_text())
    tw={day(r["date"]) for r in o["series"]["taiex"]["rows"] if r.get("source")=="TWSE" and isinstance(r.get("close"),(int,float))}
    us={day(r["date"]) for r in o["series"]["sp500"]["rows"] if isinstance(r.get("close"),(int,float))}
    us.update(day(r[0]) for r in m["IXIC"] if isinstance(r[1],(int,float)))
    return {"tw":tw,"us":us}
def reaction(ts,market,days):
    local=ts.astimezone(ZoneInfo("Asia/Taipei" if market=="tw" else "America/New_York"))
    require(local.year==2026,"calendar year not independently approved")
    close=time(13,30) if market=="tw" else (time(13) if local.date().isoformat() in {"2026-11-27","2026-12-24"} else time(16))
    candidates=sorted(d for d in days if d>local.date() or (d==local.date() and local.time()<close))
    require(bool(candidates) and (candidates[0]-local.date()).days<=7,"missing observed exchange session")
    return candidates[0].isoformat()
def validate(raw,approval,root):
    require(re.fullmatch(r"[0-9a-f]{64}",approval) is not None and hashlib.sha256(raw).hexdigest()==approval,"unapproved public news bytes")
    doc=json.loads(raw)
    require(set(doc)=={"schemaVersion","audience","status","records"} and doc["schemaVersion"]==2 and doc["audience"]=="public-market" and doc["status"]=="approved_public_release","invalid envelope")
    rows=doc["records"];require(isinstance(rows,list) and 0<len(rows)<=5000,"invalid record count")
    cal=sessions(root);ids=set();urls=set()
    for e in rows:
        require(isinstance(e,dict) and set(e)==FIELDS,"extra/missing display fields")
        require(e["publicationAllowed"] is True and e["quality"]=="verified_public","unapproved record")
        require(e["kind"] in CATEGORIES and type(e["revision"]) is int and e["revision"]>=1 and isinstance(e["eventId"],str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{5,150}",e["eventId"]),"event identity")
        require(safe_url(e["url"],e["source"]),"source host mismatch")
        require(e["eventId"] not in ids and e["url"].rstrip("/") not in urls,"duplicate event or source")
        ids.add(e["eventId"]);urls.add(e["url"].rstrip("/"))
        for k,n in (("title",120),("summary",350),("source",80)):
            require(isinstance(e[k],str) and 0<len(e[k].strip())<=n and len(e[k])<=n and not re.search(r"[\x00-\x1f\x7f]",e[k]),"invalid text")
        ts=stamp(e["publishedAt"]);require(day(e["date"]).isoformat()==e["publishedAt"][:10] and ts<=datetime.now(timezone.utc),"publication date")
        for k in ("eventAt","effectiveAt"):
            if e[k] is not None:stamp(e[k])
        require(isinstance(e["reactionDates"],dict) and set(e["reactionDates"])=={"tw","us"},"market keys")
        for market in ("tw","us"):require(e["reactionDates"][market]==reaction(ts,market,cal[market]),"market date mismatch")
    print("Public news approval, privacy schema, unique event IDs, source and calendar: PASS",len(rows),approval)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--approved-sha256",required=True);p.add_argument("--public-root",default="public");a=p.parse_args();root=Path(a.public_root);validate((root/"public-news-events.json").read_bytes(),a.approved_sha256,root)
