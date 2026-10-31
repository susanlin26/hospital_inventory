"""Shared alert classification, with no changes to financial formulas."""
from decimal import Decimal as D
from .analytics import rule_for
def flags(x,rules):
 r=rule_for(rules,x['category']);q=x.get('qty');valid=x['used']>=0 and x.get('opening',D(0))>=0 and x['ending']>=0 and (q is None or q>=0 and ((x['used']==0)==(q==0)))
 high=valid and x.get('days') is not None and x['days']>D(r['high_days']);low=valid and x.get('low_stock_days') is not None and x['low_stock_days']<D(r['low_days']);idle=valid and x['used']==0 and (q is None or q==0) and x['ending']>0
 return dict(valid=valid,high=bool(high),low=bool(low),idle=bool(idle),persistent=bool(idle and x.get('idle_persistent')),long_term=bool(idle and x.get('idle_confirmed')),severity='週轉嚴重偏慢' if high and x['days']>D(r['severe_days']) else '週轉偏慢' if high else '',high_days=r['high_days'],severe_days=r['severe_days'],low_days=r['low_days'],idle_warn_days=r['idle_warn_days'],idle_days=r['idle_days'])
