#!/usr/bin/env python3
"""Explicit market-only projection from the old mixed daily-data.json format.
The export intentionally discards every freeform field, portfolio/holdings/risk/defense,
user-specific statistics, sources and notes. No source file is modified.
"""
import json, pathlib, sys, datetime as dt
from validate_public import ALLOWED_MARKET, validate

def export(src):
    market=src.get('market') or {}
    public={
        'schemaVersion':2,'audience':'public-market',
        'asOf':src.get('asOf') or '2026-11-13',
        'dataStatus':'partial',
        'updatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
        'headline':'市場日報已同步（僅公開指標）',
        'summary':'本版僅包含公開市場監測資料；缺值不代表零。請參照各指標來源與公布日期。',
        'market':{key:market.get(key) if type(market.get(key)) in (int,float) else None for key in sorted(ALLOWED_MARKET)},
        'ai':[], 'alerts':[], 'sources':[], 'marketHistory':[],
        'notes':['公開市場監測資料為主；缺值請以最新核實來源為準。']
    }
    # Do NOT copy free-form AI text from a mixed private report; even this field
    # might contain personal holdings, notes or position sizes. Publishing AI
    # requires a purpose-built, separately reviewed public payload.
    validate(public)
    return public

if __name__=='__main__':
    if len(sys.argv)!=3:sys.exit('Usage: python scripts/export_public.py <mixed-daily-data.json> <public/market-data.json>')
    src=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
    dst=pathlib.Path(sys.argv[2]);dst.parent.mkdir(exist_ok=True,parents=True)
    result=export(src)
    if dst.exists():
        existing=json.loads(dst.read_text(encoding='utf-8'))
        validate(existing)
        if result['asOf'] < existing['asOf']:
            sys.exit('Refusing to replace a newer snapshot')
        incoming={k:v for k,v in result['market'].items() if v is not None}
        if 'marginMaintenanceAsOf' in existing['market']:
            incoming.pop('marginMaintenance', None)  # mixed input has no verified observation date
        result={**existing, 'market':{**existing['market'], **incoming},
                'asOf':result['asOf'], 'dataStatus':result['dataStatus'], 'updatedAt':result['updatedAt']}
        validate(result)
    temp=dst.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(dst)
    print('Market-only payload written:',dst)
