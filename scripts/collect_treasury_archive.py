"""Collect the official US Treasury par-yield archive without splicing FRED."""
import csv, datetime as dt, hashlib, io, json, pathlib, sys, urllib.request
from decimal import Decimal

URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rate-archives/par-yield-curve-rates-1990-2023.csv"
ROOT = pathlib.Path("research-data/treasury")
NAME = "par-yield-curve-rates-1990-2023"
MATURITIES = ("1 Yr","2 Yr","3 Yr","5 Yr","10 Yr","30 Yr")

def validate(raw):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = reader.fieldnames or []
    if len(fields)!=len(set(fields)) or not {"Date", *MATURITIES}.issubset(fields):
        raise ValueError("unexpected Treasury CSV columns")
    dates=set()
    counts={m:0 for m in MATURITIES}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("malformed Treasury row")
        stamp=row["Date"].strip()
        try:
            day=dt.datetime.strptime(stamp,"%m/%d/%Y").date()
        except ValueError:
            day=dt.date.fromisoformat(stamp)
        if day in dates or not 1990<=day.year<=2023:
            raise ValueError("duplicate or out-of-range date")
        dates.add(day)
        for key in MATURITIES:
            val=row[key].strip()
            if val.upper() in ("","N/A","NA",".","NULL"):
                continue
            n=Decimal(val)
            if not n.is_finite() or not Decimal("-5")<=n<=Decimal("30"):
                raise ValueError("invalid yield")
            counts[key]+=1
    if not dates:
        raise ValueError("empty archive")
    return {"first":str(min(dates)),"last":str(max(dates)),"dates":len(dates),
            "valid_by_maturity":counts}

def self_test():
    raw=b"Date,1 Yr,2 Yr,3 Yr,5 Yr,10 Yr,30 Yr\n01/02/1990,7.81,7.87,7.90,7.87,7.94,8.00\n"
    assert validate(raw)["valid_by_maturity"]["10 Yr"]==1
    try: validate(raw+raw.splitlines(keepends=True)[1])
    except ValueError: pass
    else: raise AssertionError("duplicate accepted")
    print("PASS Treasury parser fixtures")

def collect():
    dest=ROOT/(NAME+".csv")
    meta=dest.with_suffix(".json")
    if dest.exists() or meta.exists():
        if not(dest.exists() and meta.exists()):
            raise ValueError("incomplete prior archive")
        raw=dest.read_bytes()
        m=json.loads(meta.read_text())
        if hashlib.sha256(raw).hexdigest()!=m["sha256"] or m["source"]!=URL:
            raise ValueError("prior archive SHA/source mismatch")
        validate(raw)
        print("SKIP_EXISTING_VERIFIED_TREASURY_ARCHIVE")
        return
    req=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0 (Jenbao public economic research)","Accept":"text/csv,*/*","Accept-Encoding":"identity"})
    with urllib.request.urlopen(req,timeout=40) as res:
        raw=res.read(8_000_001)
    if len(raw)>8_000_000:
        raise ValueError("archive size limit")
    coverage=validate(raw)
    if coverage["dates"]<8000 or coverage["first"]>"1990-01-10" or coverage["last"]<"2023-12-20":
        raise ValueError("incomplete archive date coverage")
    manifest={"source":URL,"provider":"US Department of the Treasury",
        "definition":"Daily Treasury Par Yield Curve Rates; percent",
        "series_id":"UST_PAR_CURVE_1990_2023","coverage":coverage,
        "sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
        "quality":"official_source_candidate","not_fred_dgs10":True,
        "limitations":"Source nulls retained; no calendar completeness certification or FRED splicing."}
    ROOT.mkdir(parents=True,exist_ok=True)
    for p,content in ((dest,raw),(meta,(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode())):
        tmp=p.with_suffix(p.suffix+".tmp")
        tmp.write_bytes(content)
        tmp.replace(p)
    print(json.dumps(manifest))

if __name__=="__main__":
    self_test()
    if "--self-test" not in sys.argv:
        collect()
