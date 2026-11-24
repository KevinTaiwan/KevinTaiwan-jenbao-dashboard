#!/usr/bin/env python3
"""Protect public market JSON bytes from metadata-only rechecks.

Callers must validate market data before calling this write gate.
Observation values/dates, provenance, quality and error fields stay material.
"""
import copy
import datetime as dt
import json
from pathlib import Path

VOLATILE={
 "market-history":[("generatedAt",),("cutoff",),("twseTurnoverAudit","generatedAt"),("backfillAudit","collectedAt")],
 "market-data":[("updatedAt",)],
}

def material_view(value,kind):
    if kind not in VOLATILE: raise ValueError("unexpected public market schema")
    if not isinstance(value,dict): raise TypeError("expected a JSON object")
    result=copy.deepcopy(value)
    for path in VOLATILE[kind]:
        node=result
        for key in path[:-1]: node=node.get(key) if isinstance(node,dict) else None
        if isinstance(node,dict): node.pop(path[-1],None)
    return result

def write_public_if_materially_changed(path,value,kind):
    path=Path(path)
    if path.is_file():
        original=json.loads(path.read_text(encoding="utf-8"))
        if material_view(original,kind)==material_view(value,kind):
            check_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            print(f"SKIP_NO_MATERIAL_CHANGE {path.name}; verified_at={check_at}",flush=True)
            return False
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)
    print(f"WRITE_MATERIAL_CHANGE {path.name}",flush=True)
    return True
