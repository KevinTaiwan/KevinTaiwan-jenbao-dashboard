"""V15 public-domain FRED collection; independent of public Dashboard."""
import csv, datetime as dt, hashlib, io, json, math, pathlib, sys, urllib.request
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

def collect(series, today):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series
    dest = ROOT / (series + ".csv")
    old = parse(dest.read_bytes(), series, today) if dest.exists() else {}
    # Incremental refresh with overlap for source revisions; first acquisition is full.
    if old:
        start = dt.date.fromisoformat(max(old)) - dt.timedelta(days=35)
        url += "&cosd=" + start.isoformat()
    req = urllib.request.Request(url, headers={"User-Agent":"Jenbao public economic data research/1.0"})
    with urllib.request.urlopen(req, timeout=40) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("response size limit")
    incoming = parse(raw, series, today)
    # Do not erase existing valid values or silently replace conflicting observations.
    conflicts = [d for d,v in incoming.items() if d in old and old[d] and v != old[d]]
    if conflicts:
        raise ValueError("source revision requires review: " + ",".join(conflicts[:10]))
    merged = dict(old)
    merged.update(incoming)
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
    print("PASS parser fixtures")

if __name__ == "__main__":
    self_test()
    if "--self-test" not in sys.argv:
        for series in SERIES:
            collect(series,dt.date.today())
