"""Collect the official US Treasury par-yield archive without splicing FRED."""
import csv, datetime as dt, hashlib, io, json, pathlib, sys, urllib.request
from decimal import Decimal

URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rate-archives/par-yield-curve-rates-1990-2023.csv"
ROOT = pathlib.Path("research-data/treasury")
NAME = "par-yield-curve-rates-1990-2023"
MATURITIES = ("1 yr","2 yr","3 yr","5 yr","10 yr","30 yr")
REAL_MATURITIES = ("5 yr","7 yr","10 yr","20 yr","30 yr")
REAL_NAME = "par-real-yield-curve-rates-2003-2023"
REAL_URL = URL.rsplit("/",1)[0]+"/"+REAL_NAME+".csv"

def validate(raw, maturities=MATURITIES, start_year=1990, end_year=2023):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = [x.strip().lower() for x in (reader.fieldnames or [])]
    reader.fieldnames = fields
    if len(fields)!=len(set(fields)) or not {"date", *maturities}.issubset(fields):
        raise ValueError("unexpected Treasury CSV columns")
    dates=set()
    counts={m:0 for m in maturities}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("malformed Treasury row")
        stamp=row["date"].strip()
        try:
            day=dt.datetime.strptime(stamp,"%m/%d/%Y").date()
        except ValueError:
            day=dt.date.fromisoformat(stamp)
        if day in dates or not start_year<=day.year<=end_year:
            raise ValueError("duplicate or out-of-range date")
        dates.add(day)
        for key in maturities:
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
    assert validate(raw)["valid_by_maturity"]["10 yr"]==1
    try: validate(raw+raw.splitlines(keepends=True)[1])
    except ValueError: pass
    else: raise AssertionError("duplicate accepted")
    real=b"date,5 yr,7 yr,10 yr,20 yr,30 yr\n01/02/2003,1.75,2.24,2.43,,\n"
    assert validate(real,REAL_MATURITIES,2003)["valid_by_maturity"]["20 yr"]==0
    assert validate(real,REAL_MATURITIES,2003)["valid_by_maturity"]["10 yr"]==1
    print("PASS Treasury nominal and real parser fixtures")

def collect(real=False):
    name,url,maturities,start_year,min_rows = (REAL_NAME,REAL_URL,REAL_MATURITIES,2003,5000) if real else (NAME,URL,MATURITIES,1990,8000)
    dest=ROOT/(name+".csv")
    meta=dest.with_suffix(".json")
    if dest.exists() or meta.exists():
        if not(dest.exists() and meta.exists()):
            raise ValueError("incomplete prior archive")
        raw=dest.read_bytes()
        m=json.loads(meta.read_text())
        if hashlib.sha256(raw).hexdigest()!=m["sha256"] or m["source"]!=url:
            raise ValueError("prior archive SHA/source mismatch")
        validate(raw,maturities,start_year)
        print("SKIP_EXISTING_VERIFIED_TREASURY_ARCHIVE")
        return
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (Jenbao public economic research)","Accept":"text/csv,*/*","Accept-Encoding":"identity"})
    with urllib.request.urlopen(req,timeout=40) as res:
        raw=res.read(8_000_001)
    if len(raw)>8_000_000:
        raise ValueError("archive size limit")
    coverage=validate(raw,maturities,start_year)
    if coverage["dates"]<min_rows or coverage["first"]>f"{start_year}-01-10" or coverage["last"]<"2023-12-20":
        raise ValueError("incomplete archive date coverage")
    manifest={"source":url,"provider":"US Department of the Treasury",
        "definition":"Daily Treasury Par Real Yield Curve Rates; percent" if real else "Daily Treasury Par Yield Curve Rates; percent",
        "series_id":"UST_PAR_REAL_CURVE_2003_2023" if real else "UST_PAR_CURVE_1990_2023",
        "fred_reference_series":["DFII5","DFII7","DFII10","DFII20","DFII30"] if real else ["DGS1","DGS2","DGS3","DGS5","DGS10","DGS30"],"coverage":coverage,
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
        collect(real="--real" in sys.argv)
