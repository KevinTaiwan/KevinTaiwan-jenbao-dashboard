"""V15 official Treasury recent-year par yield curves; distinct from FRED."""
import csv, datetime as dt, hashlib, io, json, pathlib, sys, urllib.parse, urllib.request
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ROOT=pathlib.Path("research-data/treasury-recent")
BASE="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
KINDS={"nominal":("daily_treasury_yield_curve",("1 yr","2 yr","3 yr","5 yr","7 yr","10 yr","20 yr","30 yr")),
       "real":("daily_treasury_real_yield_curve",("5 yr","7 yr","10 yr","20 yr","30 yr"))}
NULLS={"","N/A","NA","NULL","."}

def parse(raw,kind,year,today):
    mats=KINDS[kind][1]
    reader=csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    headers=[x.strip().lower() for x in next(reader)]
    if headers.count("date")!=1 or not set(mats).issubset(headers):
        raise ValueError("missing required Treasury columns")
    positions={m:[i for i,x in enumerate(headers) if x==m] for m in mats}
    rows={}
    for row in reader:
        if not row or not any(x.strip() for x in row): continue
        if len(row)!=len(headers): raise ValueError("malformed CSV row")
        s=row[headers.index("date")].strip()
        try: day=dt.datetime.strptime(s,"%m/%d/%Y").date()
        except ValueError: day=dt.date.fromisoformat(s)
        if day.year!=year or day>today or day.isoformat() in rows:
            raise ValueError("duplicate, future or wrong-year observation")
        vals=[]
        for m in mats:
            found=set()
            for i in positions[m]:
                s=row[i].strip()
                if s.upper() in NULLS: continue
                n=Decimal(s)
                if not n.is_finite() or not Decimal("-5")<=n<=Decimal("30"):
                    raise ValueError("invalid yield")
                found.add(n)
            if len(found)>1: raise ValueError("conflicting same-maturity columns")
            vals.append(format(next(iter(found)),"f") if found else "")
        rows[day.isoformat()]=vals
    if not rows or not any(v for vals in rows.values() for v in vals):
        raise ValueError("no valid data")
    return rows

def merge(old,new):
    out={k:list(v) for k,v in old.items()}
    for d,vals in new.items():
        if d not in out: out[d]=list(vals);continue
        for i,v in enumerate(vals):
            prior=out[d][i]
            if prior and (not v or Decimal(prior)!=Decimal(v)):
                raise ValueError("source revision: "+d)
            if not prior and v: out[d][i]=v
    return out

def collect(kind,year,today):
    typ,mats=KINDS[kind]
    url=BASE+str(year)+"/all?"+urllib.parse.urlencode({"_format":"csv","field_tdr_date_value":year,"page":"","type":typ})
    dest=ROOT/f"ust-{kind}-{year}.csv"
    meta=dest.with_suffix(".json")
    old={}
    if dest.exists() or meta.exists():
        if not(dest.exists() and meta.exists()): raise ValueError("incomplete checkpoint")
        previous=json.loads(meta.read_text())
        oldraw=dest.read_bytes()
        if previous.get("sha256")!=hashlib.sha256(oldraw).hexdigest() or previous.get("source")!=url:
            raise ValueError("checkpoint SHA/source mismatch")
        old=parse(oldraw,kind,year,today)
        if year<today.year and previous.get("full_year_boundary_check"):
            print("SKIP_VERIFIED_YEAR",kind,year);return
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (Jenbao public economic research)","Accept":"text/csv,*/*","Accept-Encoding":"identity"})
    with urllib.request.urlopen(req,timeout=25) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError("response limit")
    incoming=parse(raw,kind,year,today)
    full=year<today.year and len(incoming)>=220 and min(incoming)<=f"{year}-01-10" and max(incoming)>=f"{year}-12-20"
    if year<today.year and not full: raise ValueError("incomplete historical annual response")
    if old and set(old)-set(incoming): raise ValueError("source dropped existing dates")
    merged=merge(old,incoming)
    buf=io.StringIO(newline="")
    writer=csv.writer(buf,lineterminator="\n")
    writer.writerow(["date",*mats])
    writer.writerows((d,*v) for d,v in sorted(merged.items()))
    data=buf.getvalue().encode()
    counts={m:sum(bool(v[i]) for v in merged.values()) for i,m in enumerate(mats)}
    if any(n==0 for n in counts.values()): raise ValueError("empty required maturity")
    m={"series_id":f"UST_PAR_{kind.upper()}_{year}","source":url,"provider":"US Department of the Treasury",
       "definition":"Daily Treasury par "+("real " if kind=="real" else "")+"yield curve, percent",
       "source_raw_sha256":hashlib.sha256(raw).hexdigest(),"sha256":hashlib.sha256(data).hexdigest(),
       "bytes":len(data),"first":min(merged),"last":max(merged),"dates":len(merged),"valid_by_maturity":counts,
       "full_year_boundary_check":full,"quality":"official_source_candidate",
       "limitations":"No estimated fills, no FRED splice, no complete calendar or publication-time certification."}
    ROOT.mkdir(parents=True,exist_ok=True)
    for p,content in ((dest,data),(meta,(json.dumps(m,sort_keys=True,indent=2)+"\n").encode())):
        if not p.exists() or p.read_bytes()!=content:
            tmp=p.with_suffix(p.suffix+".tmp");tmp.write_bytes(content);tmp.replace(p)
    print(json.dumps(m),flush=True)

def self_test():
    today=dt.date(2026,11,24)
    raw=b"Date,5 YR,7 YR,10 YR,20 YR,30 YR,20 Yr,30 Yr\n01/02/2025,1.5,1.7,2,2.4,2.5,N/A,N/A\n"
    r=parse(raw,"real",2025,today)
    assert r["2025-01-02"]==["1.5","1.7","2","2.4","2.5"]
    assert merge(r,{"2025-01-02":["1.50","1.7","2","2.4","2.5"]})==r
    try: parse(raw.replace(b"N/A,N/A",b"2.9,N/A"),"real",2025,today)
    except ValueError: pass
    else: raise AssertionError("conflict accepted")
    try: merge(r,{"2025-01-02":["","1.7","2","2.4","2.5"]})
    except ValueError: pass
    else: raise AssertionError("valid value erased")
    print("PASS Treasury recent-year fixtures")

if __name__=="__main__":
    self_test()
    if "--self-test" not in sys.argv:
        today=dt.datetime.now(ZoneInfo("America/New_York")).date()
        failed=[]
        for year in range(2024,today.year+1):
            for kind in KINDS:
                try: collect(kind,year,today)
                except (OSError,ValueError,InvalidOperation) as exc:
                    failed.append([kind,year,str(exc)[:200]])
        print(json.dumps({"failed":failed}),flush=True)
        sys.exit(bool(failed))
