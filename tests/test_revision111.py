"""Dual purchase thresholds, optional evidence and atomic hospital rule updates."""
from decimal import Decimal as D
import pytest
from app import engine
from helpers import line
from test_workflow import client,sign

@pytest.mark.parametrize('rate,quantity,alert', [('9.99',1000,False),('10',285,False),('10',286,True),('-10',286,True),('20',100,False),('20',200,True)])
def test_purchase_requires_both_thresholds(rate,quantity,alert):
 old=line(period='2026-08',in_a='1000',in_q='10',sale_a='100',sale_q='1',end_a='100')
 current=line(period='2026-09',in_a=str(D(100)*(1+D(rate)/100)*quantity),in_q=str(quantity),sale_a='100',sale_q='1',end_a='100')
 x=engine.analyze([current],[old],'2026-09')['items'][0]
 assert x['purchase_alert'] is alert
 assert x['purchase_delta']['pct']==D(rate)
 assert x['purchase_impact']==D('105')*D(rate)/100*quantity

def test_bulk_rules_atomic_and_authorized(client):
 sign(client,'admin099')
 def put(h,**rules):return client.put('/api/rules/'+h,json=dict(effective_from='2027-01',**rules))
 assert put('SM',change_pct='15').status_code==200
 assert put('DE',change_pct='18',change_amount='6000').status_code==200
 payload=dict(hospitals=['SM','DE'],rules=dict(effective_from='2027-02',change_amount='5000'))
 assert client.put('/api/rules-batch',json=payload).status_code==409
 # The earlier hospital must also roll back on any conflict.
 assert len(client.get('/api/rules/DE/history').json())==1
 payload['rules']['overwrite']=True
 r=client.put('/api/rules-batch',json=payload);assert r.status_code==200,r.text
 for h,pct in [('SM','15'),('DE','18')]:
  rules=client.get('/api/settings/context',params=dict(hospital=h,month='2027-02')).json()['rules']
  assert D(rules['change_amount'])==5000 and D(rules['change_pct'])==D(pct)
 sign(client,'front099');assert client.put('/api/rules-batch',json=payload).status_code==403

def test_purchase_pending_alert_recalculates_when_threshold_changes(client):
 from test_workflow import item
 sign(client,'admin099')
 assert item(client,kind='purchase')[2]['comparison_active']
 rule=dict(effective_from='2026-09',effective_until='2026-12',purchase_pct='10',purchase_amount='5000')
 r=client.put('/api/rules/SM',json=rule);assert r.status_code==200,r.text
 assert not item(client,kind='purchase')[2]['comparison_active']
 r=client.put('/api/rules/SM',json={**rule,'purchase_amount':'3000','overwrite':True});assert r.status_code==200,r.text
 assert item(client,kind='purchase')[2]['comparison_active']

@pytest.mark.parametrize('metric',['used','standard30','ending','days'])
def test_category_excel_totals_match_only_additive_metrics(client,metric):
 from io import BytesIO
 from openpyxl import load_workbook
 sign(client,'admin099')
 tab='inventory' if metric in ('ending','days') else 'consumption'
 r=client.get('/api/export/cross-comparison',params=dict(hospitals='SM,DE',month='2026-09',category_metric=metric,tab=tab,export_section='categories'))
 assert r.status_code==200,r.text[:200]
 rows=list(load_workbook(BytesIO(r.content))['分類比較'].values)
 if metric=='days':assert rows[-1][0]!='合計'
 else:
  assert rows[-1][0]=='合計'
  for col in range(1,len(rows[0])):
   values=[r[col] for r in rows[1:-1] if isinstance(r[col],(int,float))]
   assert rows[-1][col]==(sum(values) if values else '—')
