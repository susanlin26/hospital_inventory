"""Effective rule intervals, hospital creation, dynamic imports and multi-hospital authorization."""
from decimal import Decimal as D
from test_workflow import client,sign,PW
from helpers import make_excel,line
from app import db
import pytest


def test_rule_overwrite_keeps_old_nonoverlapping_period(client):
 sign(client,'admin099')
 a=client.put('/api/rules/DE',json=dict(effective_from='2025-01',change_amount='7500'));assert a.status_code==200,a.text
 b=client.put('/api/rules/DE',json=dict(effective_from='2026-01',change_amount='5000'));assert b.status_code==409
 b=client.put('/api/rules/DE',json=dict(effective_from='2026-01',change_amount='5000',overwrite=True));assert b.status_code==200,b.text
 versions=client.get('/api/rules/DE/history').json();old=next(v for v in versions if v['id']==a.json()['version'])
 assert not old['disabled_at'] and old['body']['effective_until']=='2025-12'
 assert D(client.get('/api/settings/context?hospital=DE&month=2025-12').json()['rules']['change_amount'])==7500
 assert D(client.get('/api/settings/context?hospital=DE&month=2026-01').json()['rules']['change_amount'])==5000


def test_hospital_creation_import_mapping_and_access(client):
 sign(client,'front099');assert client.post('/api/hospitals',json=dict(code='AB1',name='新增測試院')).status_code==403
 sign(client,'admin099')
 for code in ['ALL','X','A-B','A_B','1AB','中文','ABCDEFGHIJKLM',None,123]:
  assert client.post('/api/hospitals',json=dict(code=code,name='測試院')).status_code==422
 r=client.post('/api/hospitals',json=dict(code=' ab1 ',name='新增測試院'));assert r.status_code==200,r.text
 assert r.json()==dict(code='AB1',name='新增測試院')
 assert client.post('/api/hospitals',json=dict(code='ab1',name='重複院')).status_code==409
 assert any(h['code']=='AB1' for h in client.get('/api/hospitals').json())
 filename='11509_AB1進銷存表_耗材.xlsx'
 check=client.post('/api/import/inspect',json=dict(filenames=[filename])).json()[0];assert check['can_import'] and check['hospital']=='AB1'
 body=make_excel([line(sale_q='1',sale_a='100')])
 r=client.post('/api/import',data=dict(hospital='AB1',month='2026-09'),files=dict(file=(filename,body)));assert r.status_code==200,r.text
 with db.connect() as c:
  assert c.execute('SELECT hospital FROM import_jobs WHERE id=%s',(r.json()['job_id'],)).fetchone()['hospital']=='AB1'
  assert c.execute("SELECT count(*) n FROM audit WHERE action='hospital_created' AND hospital='AB1'").fetchone()['n']==1
 sign(client,'front099');assert not any(h['code']=='AB1' for h in client.get('/api/hospitals').json())
 assert client.post('/api/import/inspect',json=dict(filenames=[filename])).status_code==403
 assert client.get('/api/monthly-cases?hospitals=AB1&month=2026-09').status_code==403

@pytest.mark.parametrize('role',['frontline','accountant','manager','viewer'])
def test_multi_hospital_accounts_keep_scope_permissions(client,role):
 sign(client,'admin099');name='multi112_'+role
 r=client.post('/api/users',json=dict(username=name,name=name,password=PW,role=role,hospitals=['SM','DE']));assert r.status_code==200,r.text
 sign(client,name);assert {h['code'] for h in client.get('/api/hospitals').json()}=={'SM','DE'}
 assert client.get('/api/monthly-cases?hospitals=SM,DE&month=2026-09').status_code==200
 assert client.get('/api/monthly-cases?hospitals=ZK&month=2026-09').status_code==403
