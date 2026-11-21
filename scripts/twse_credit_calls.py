"""Append published TWSE whole-market credit calls and next-session disposals."""
import datetime as dt
import json
import urllib.request

URL = "https://www.twse.com.tw/rwd/zh/marginTrading/BFIJ3U_TREND"
FIRST = "2026-08-03"
# The TWSE dashboard labels belowAccNum as 追繳戶數.
FIELDS = {
    "creditBelow130Accounts": ("belowAccNum", "戶：全市場整戶維持率低於130%"),
    "creditCallAmountTwd": ("callAmt", "新台幣元：當日通知應補繳金額"),
    "creditDisposalAccounts": ("exeAccNum", "戶：次一營業日應處分"),
    "creditDisposalAmountTwd": ("exeAmt", "新台幣元：次一營業日應處分部位"),
}


def merge_credit(doc):
    window = [r for r in doc["rows"] if "taiex" in r][-1000:]
    gaps = {r["date"] for r in window if r["date"] >= FIRST and not FIELDS.keys() <= r.keys()}
    rows = {r["date"]: r for r in window}
    pending = {}
    while gaps:
        end = max(gaps)
        url = URL + "?response=json&days=60&date=" + end.replace("-", "")
        with urllib.request.urlopen(url, timeout=25) as response:
            batch = json.load(response)
        records = batch.get("data") or []
        if batch.get("stat") != "OK" or not records:
            break
        dates = []
        for record in records:
            day = dt.datetime.strptime(record["date"], "%Y%m%d").date().isoformat()
            dates.append(day)
            if day not in gaps or day > end:
                continue
            values = {key: record.get(field) for key, (field, _) in FIELDS.items()}
            if any(type(v) != int or v < 0 for v in values.values()):
                continue
            if any(k in rows[day] and rows[day][k] != v for k, v in values.items()):
                raise ValueError("Conflicting credit observation on " + day)
            pending[day] = values
        gaps = {d for d in gaps if d < min(dates) and d < end}
    if not pending:
        return 0
    for day, values in pending.items():
        rows[day].update(values)
    for key, (_, unit) in FIELDS.items():
        series = [r for r in doc["rows"] if key in r]
        doc["units"][key] = unit
        doc["stats"][key] = dict(count=len(series), first=series[0]["date"],
            last=series[-1]["date"], lastValue=series[-1][key],
            status="ready" if len(series) >= 1000 else "partial",
            source={"name": "TWSE BFIJ3U_TREND " + FIELDS[key][0], "url": URL})
    return len(pending)
