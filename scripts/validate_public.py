#!/usr/bin/env python3
"""Fail closed: only approved market data types may be publicly deployed."""
import datetime as dt
import json
import pathlib
import re
import sys
from urllib.parse import urlsplit

ALLOWED_TOP={'schemaVersion','audience','asOf','dataStatus','updatedAt','headline','summary','market','ai','alerts','sources','marketHistory','notes'}
ALLOWED_MARKET={'taiex','taiexChange','ma5','ma10','ma20','ma60','ma120','ma240','vix','move','usdtwd','dxy','us10y','de10y','cnn','marginBalanceYi','marginDailyYi','marginMaintenance','foreignNetYi','futuresNetContracts','hyOas','singleBOas','sofrMinusIorb','t10yie','t5yie','oil','goldPrice'}
# Defensively catch private-field leaks even if a future editor accidentally expands the schema.
BANNED_KEY_FRAGMENTS=('portfolio','holding','position','allocation','account','secret','token','password','private','networth','costbasis','assetweight','personaldrawdown','personalreturn','defense','beta','volatility','correlation','cash','bondweight','user','owner','statement','ledger')
BANNED_TEXT_FRAGMENTS=('我的投資組合','我的持股','你的持股','總資產','個人資產','買入成本','券商帳戶','原始部位','個人回撤','現金占比','現金佔比','d1 防守','股債配置','個人報酬','私有資料')
DATE=re.compile(r'^\d{4}-\d{2}-\d{2}$')

def fail(s): raise ValueError(s)
def valid_date(s):
    if not isinstance(s,str) or not DATE.fullmatch(s): fail('invalid ISO date')
    try: dt.date.fromisoformat(s)
    except ValueError: fail('nonexistent date')
def check_text(s, maxlen=500):
    if not isinstance(s,str) or len(s)>maxlen: fail('bad public text')
    if any(w in s.lower() for w in BANNED_TEXT_FRAGMENTS): fail('possible personal phrase in public text')
    if '\x00' in s: fail('NUL text')
def check_keys(obj, allowed):
    if not isinstance(obj,dict): fail('expected object')
    extra=set(obj)-allowed
    if extra: fail('unsafe/unknown fields: '+repr(sorted(extra)))
    for k in obj:
        if any(w in k.lower() for w in BANNED_KEY_FRAGMENTS): fail('possible private key: '+k)
def check_num(v,name):
    if v is not None and (type(v) not in (int,float) or not (-1e15<v<1e15)):
        fail('invalid numeric market value: '+name)
def validate(d):
    coverage = d.get('marginMaintenanceCoverage')
    if coverage is not None:
        fields = {'targetTradingDays', 'observedTradingDays', 'missingTradingDays',
                  'targetFirst', 'targetLast', 'status', 'sourceUrl'}
        if set(coverage) != fields: fail('invalid maintenance coverage schema')
        for key in ('targetTradingDays', 'observedTradingDays', 'missingTradingDays'):
            if type(coverage[key]) != int or coverage[key] < 0: fail('invalid coverage count')
        if coverage['observedTradingDays'] + coverage['missingTradingDays'] != coverage['targetTradingDays']:
            fail('inconsistent coverage counts')
        valid_date(coverage['targetFirst'])
        valid_date(coverage['targetLast'])
        if coverage['status'] not in ('partial', 'complete'): fail('invalid coverage status')
        if coverage['sourceUrl'] != 'https://www.wantgoo.com/stock/margin-trading/exclude-etf/taiex':
            fail('invalid maintenance source')
    check_keys(d,ALLOWED_TOP | {'marginMaintenanceCoverage'})
    if d.get('schemaVersion')!=2 or d.get('audience')!='public-market': fail('wrong schema/audience')
    valid_date(d.get('asOf'))
    if d.get('dataStatus') not in {'verified','partial','intraday','awaiting-verification'}: fail('bad status')
    if d.get('updatedAt') is not None: check_text(d['updatedAt'],64)
    for key in ('headline','summary'): check_text(d.get(key,''),650)
    m=d.get('market');check_keys(m,ALLOWED_MARKET | {'marginMaintenanceScope', 'marginMaintenanceAsOf'})
    for k,v in m.items():
        if k == 'marginMaintenanceAsOf': valid_date(v)
        elif k == 'marginMaintenanceScope': check_text(v, 200)
        else: check_num(v,k)
    for a in d.get('ai',[]):
        check_keys(a,{'name','value','trend','status'})
        check_text(a.get('name',''),100);check_text(a.get('trend',''),300)
        if a.get('status') not in ('ok','alert','unknown'):fail('bad AI status')
        if a.get('value') is not None:
            if type(a['value']) in (float,int): check_num(a['value'],'ai')
            else: check_text(a['value'],120)
    for item in d.get('alerts',[]):
        check_keys(item,{'label','status','detail'})
        for k in ('label','status','detail'): check_text(item.get(k,''),240)
    for item in d.get('sources',[]):
        check_keys(item,{'label','url','date'})
        check_text(item.get('label',''),160);check_text(item.get('url',''),1000)
        u=urlsplit(item['url'])
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:fail('unsafe source url')
        if item.get('date') is not None:valid_date(item['date'])
    for h in d.get('marketHistory',[]):
        check_keys(h,{'date','taiex'});valid_date(h.get('date'));check_num(h.get('taiex'),'history')
    for note in d.get('notes',[]):check_text(note,300)
    if len(json.dumps(d,ensure_ascii=False))>200_000:fail('oversized data')
    return True

if __name__=='__main__':
    path=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'public/market-data.json')
    try:
        d=json.loads(path.read_text(encoding='utf-8'))
        validate(d)
    except Exception as e:
        print('REJECTED:',e,file=sys.stderr);sys.exit(1)
    print('PASS: public market JSON has no private schema fields')
