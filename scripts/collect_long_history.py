"""V15 public-domain FRED collection; independent of public Dashboard."""
import csv, datetime as dt, hashlib, io, json, pathlib, sys, urllib.request, urllib.error
from decimal import Decimal, InvalidOperation

SERIES = ("DGS10",)
ROOT = pathlib.Path("research-data/fred")
def parse(raw, series, today):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames not in (["observation_date", series], ["DATE", series]):
        raise ValueError("unexpected CSV columns")
    rows = {}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("malformed row")
        day, val = row[reader.fieldnames[0]], row[series].strip()
        date = dt.date.fromisoformat(day)
        if date > today or day in rows:
            raise ValueError("future or duplicate date")
        if val in ("", "."):
            rows[day] = ""
        else:
            n = Decimal(val)
            if not n.is_finite():
                raise ValueError("non-finite observation")
            rows[day] = str(n)
    if not rows or not any(rows.values()):
        raise ValueError("empty series")
    return rows

def merge_rows(old, incoming):
    conflicts = [d for d,v in incoming.items()
                 if d in old and old[d] and (not v or Decimal(v)!=Decimal(old[d]))]
    if conflicts:
        raise ValueError("source revision requires review: " + ",".join(conflicts[:10]))
    merged = dict(old)
    for d,v in incoming.items():
        if d not in merged or not merged[d]:
            merged[d] = v
    return merged

def annual_slots(today, completed, latest=None):
    # First refresh recent observations; then backfill at most two older years.
    # DGS10 starts 1962-01-02.
    start = dt.date(today.year,1,1)
    if latest:
        start = min(start, dt.date.fromisoformat(latest)-dt.timedelta(days=35)) if latest >= start.isoformat() else start
    start = max(start,dt.date(1962,1,2))
    slots = [(start,today,None)]
    for year in range(today.year-1,1961,-1):
        if year not in completed:
            slots.append((max(dt.date(year,1,1),dt.date(1962,1,2)),dt.date(year,12,31),year))
            if len(slots)==3:
                break
    return slots

def fetch_window(series, start, end, today):
    import time
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv?id="+series
           +"&cosd="+start.isoformat()+"&coed="+end.isoformat())
    req = urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 Jenbao public economic data research/1.1"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                raw=response.read(8_000_001)
            if len(raw)>8_000_000:
                raise ValueError("response size limit")
            rows=parse(raw,series,today)
            if any(not start.isoformat()<=d<=end.isoformat() for d in rows):
                raise ValueError("source ignored requested date range")
            return rows
        except (OSError, urllib.error.URLError) as err:
            print(json.dumps({"window":[str(start),str(end)],"attempt":attempt+1,"error":type(err).__name__}),flush=True)
            if attempt==1:
                raise
            time.sleep(2)

def collect(series, today):
    dest = ROOT / (series + ".csv")
    mp = dest.with_suffix(".json")
    old = parse(dest.read_bytes(), series, today) if dest.exists() else {}
    prior = json.loads(mp.read_text()) if mp.exists() else {}
    if prior and (not dest.exists() or prior.get("sha256")!=hashlib.sha256(dest.read_bytes()).hexdigest()):
        raise ValueError("existing checkpoint SHA mismatch")
    completed = set(prior.get("completed_annual_requests",[]))
    merged = dict(old)
    errors=[]
    succeeded=0
    for start,end,year in annual_slots(today,completed,max(old) if old else None):
        try:
            incoming=fetch_window(series,start,end,today)
            dates=[dt.date.fromisoformat(d) for d,v in incoming.items() if v]
            if year is not None and ((min(dates)-start).days>7 or (end-max(dates)).days>7 or len(dates)<220):
                raise ValueError("annual coverage boundary/count check failed")
            merged=merge_rows(merged,incoming)
            succeeded+=1
            if year is not None:
                completed.add(year)
        except (OSError,ValueError,InvalidOperation) as err:
            errors.append({"from":str(start),"to":str(end),"error":type(err).__name__})
            print(json.dumps({"status":"WARN_WINDOW","from":str(start),"to":str(end),"detail":str(err)[:200]}),flush=True)
    if not succeeded:
        raise RuntimeError("all requested windows failed; preserving prior files")
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["observation_date",series])
    writer.writerows(sorted(merged.items()))
    data = out.getvalue().encode()
    valid = [d for d,v in merged.items() if v]
    if not valid:
        raise ValueError("no valid observations")
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {"series":series,"source":"https://fred.stlouisfed.org/series/"+series,
        "source_provider":"Board of Governors of the Federal Reserve System via FRED",
        "rights":"Public Domain: Citation Requested","frequency":"daily","units":"percent",
        "first_observation":min(valid),"last_observation":max(valid),
        "valid_rows":len(valid),"source_nulls":len(merged)-len(valid),
        "sha256":hashlib.sha256(data).hexdigest(),"quality":"source_csv_candidate",
        "completed_annual_requests":sorted(completed),"annual_requests_remaining":[y for y in range(1962,today.year) if y not in completed],
        "last_window_errors":errors,"successful_windows":succeeded,
        "scope":"public economic series; not portfolio data; calendar coverage not certified"}
    meta = (json.dumps(manifest,sort_keys=True,indent=2)+"\n").encode()
    for p, content in ((dest,data),(ROOT/(series+".json"),meta)):
        if not p.exists() or p.read_bytes()!=content:
            tmp=p.with_suffix(p.suffix+".tmp")
            tmp.write_bytes(content)
            tmp.replace(p)
    print(json.dumps({"series":series,"new_dates":len(set(merged)-set(old)),
        "valid_rows":len(valid),"last_observation":max(valid),"sha256":manifest["sha256"]}))

def self_test():
    today=dt.date(2026,11,24)
    assert parse(b"observation_date,DGS10\n2026-11-20,4.92\n2026-11-21,.\n","DGS10",today)=={"2026-11-20":"4.92","2026-11-21":""}
    for raw in (b"<html>",b"DATE,DGS10\n2026-11-20,NaN\n",b"DATE,DGS10\n2026-11-20,1\n2026-11-20,2\n",b"DATE,DGS10\n2027-01-01,1\n"):
        try: parse(raw,"DGS10",today)
        except (ValueError,InvalidOperation): pass
        else: raise AssertionError("invalid data accepted")
    assert [x[2] for x in annual_slots(today,{2025})]==[None,2024,2023]
    assert merge_rows({"2026-11-20":"4.90"},{"2026-11-20":"4.9","2026-11-21":""})=={"2026-11-20":"4.90","2026-11-21":""}
    try: merge_rows({"2026-11-20":"4.90"},{"2026-11-20":""})
    except ValueError: pass
    else: raise AssertionError("valid observation erased")
    print("PASS parser, annual checkpoint and merge fixtures")

if __name__ == "__main__":
    self_test()
    if "--self-test" not in sys.argv:
        for series in SERIES:
            collect(series,dt.date.today())
