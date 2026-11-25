"""Build public-only Treasury real yields and deterministic summary from verified archives."""
import csv, datetime as dt, hashlib, io, json, math, pathlib, statistics, sys
from decimal import Decimal

ROOT=pathlib.Path("research-data")
KEYS={f"usReal{n}y":f"{n} yr" for n in (5,7,10,20,30)}
PUBLIC=pathlib.Path("public/real-yield-history.json")
CACHE=pathlib.Path(".sync/real-yield-calculations.json")
MA=(5,10,20,60,120,240)

def load_one(p,first,last):
    raw=p.read_bytes()
    m=json.loads(p.with_suffix(".json").read_text())
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=m["sha256"] or len(raw)!=m["bytes"] or m.get("provider")!="US Department of the Treasury":
        raise ValueError("source integrity mismatch: "+str(p))
    if not m["source"].startswith("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"):
        raise ValueError("source not allowlisted")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    cols=[x.strip().lower() for x in reader.fieldnames]
    if len(cols)!=len(set(cols)) or not {"date",*KEYS.values()}.issubset(cols):
        raise ValueError("invalid source schema")
    reader.fieldnames=cols
    seen=set(); out={k:[] for k in KEYS}
    for row in reader:
        if None in row or any(v is None for v in row.values()): raise ValueError("malformed row")
        s=row["date"].strip()
        try: day=dt.date.fromisoformat(s)
        except ValueError: day=dt.datetime.strptime(s,"%m/%d/%Y").date()
        if not first<=day<=last or day in seen: raise ValueError("wrong or duplicate date")
        seen.add(day)
        for k,col in KEYS.items():
            val=row[col].strip()
            if val.upper() in ("","N/A","NA","NULL","."): continue
            n=Decimal(val)
            if not n.is_finite() or not Decimal("-5")<=n<=Decimal("30"): raise ValueError("invalid yield")
            out[k].append([day.isoformat(),float(n)])
    if not seen: raise ValueError("empty source")
    counts=m.get("coverage",m)
    if len(seen)!=counts["dates"] or any(len(out[k])!=counts["valid_by_maturity"][col] for k,col in KEYS.items()):
        raise ValueError("manifest counts mismatch")
    return out,sha

def stats(rows):
    a=[r[1] for r in rows]; n=len(a); v=a[-1]
    def pct(w): return round(100*sum(x<=v for x in w)/len(w),6)
    s=statistics.stdev(a[-252:]) if n>=252 else 0
    return {"as_of":rows[-1][0],"count":n,"value":v,"previous":a[-2] if n>1 else None,
            "ma":{str(w):round(statistics.fmean(a[-w:]),6) if n>=w else None for w in MA},
            "change_bps":{str(w):round(100*(v-a[-w-1]),6) if n>w else None for w in (1,5,20)},
            "percentile":{**{str(w):pct(a[-w:]) if n>=w else None for w in (252,1000)},"expanding":pct(a)},
            "z252":round((v-statistics.fmean(a[-252:]))/s,6) if s else None}

def build(today):
    archive=ROOT/"treasury/par-real-yield-curve-rates-2003-2023.csv"
    inputs=[(archive,dt.date(2003,1,1),dt.date(2023,12,31))]
    for year in range(2024,today.year+1):
        inputs.append((ROOT/f"treasury-recent/ust-real-{year}.csv",dt.date(year,1,1),min(today,dt.date(year,12,31))))
    series={k:[] for k in KEYS}; hashes={}
    for p,first,last in inputs:
        part,sha=load_one(p,first,last)
        hashes[str(p)]=sha
        for k,rows in part.items(): series[k].extend(rows)
    for k,rows in series.items():
        rows.sort()
        if len(rows)<240 or len({d for d,v in rows})!=len(rows): raise ValueError("insufficient or duplicate "+k)
    doc={"schemaVersion":1,"audience":"public-market","provider":"US Department of the Treasury",
         "definition":"Daily Treasury par real yield curve, percent; not FRED DFII",
         "sourceSha256":hashes,"series":series}
    raw=(json.dumps(doc,ensure_ascii=False,separators=(",",":"),sort_keys=True)+"\n").encode()
    summary={"schemaVersion":1,"method":"valid observations only; percentile <= current; sample z252; no fill",
             "sourceSha256":hashes,"publicSha256":hashlib.sha256(raw).hexdigest(),"series":{k:stats(v) for k,v in series.items()},
             "quality":"official_source_candidate; release-time and calendar audit pending"}
    return raw,(json.dumps(summary,indent=2,sort_keys=True)+"\n").encode()

def self_test():
    rows=[[(dt.date(2020,1,1)+dt.timedelta(days=i)).isoformat(),float(i)] for i in range(300)]
    s=stats(rows)
    assert s["ma"]["5"]==297 and s["change_bps"]["5"]==500 and s["percentile"]["252"]==100
    assert s["ma"]["240"]==179.5
    print("PASS real yield calculation fixtures")

if __name__=="__main__":
    self_test()
    if "--self-test" not in sys.argv:
        raw,cache=build(dt.datetime.now(dt.timezone.utc).date())
        for p,content in ((PUBLIC,raw),(CACHE,cache)):
            if "--check" in sys.argv:
                if p.read_bytes()!=content: raise ValueError("derived output mismatch: "+str(p))
            elif not p.exists() or p.read_bytes()!=content:
                p.parent.mkdir(parents=True,exist_ok=True)
                tmp=p.with_suffix(p.suffix+".tmp");tmp.write_bytes(content);tmp.replace(p)
        print(cache.decode())
