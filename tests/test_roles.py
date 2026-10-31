from app import monthly_workflow as wf,monthly_cases as mc
from test_workflow import client,sign,act,item,PLAN


def test_next_owner_is_always_business_role():
 for state,want in [('待填原因','前線人員'),('改善中','前線人員'),('待審核','會計／覆核主管'),('待確認結案','會計／覆核主管'),('已完成','—')]:
  assert wf.next_owner(dict(workflow_status=state,owner='系統管理員'))==want


def test_role_todos_ignore_old_named_owner():
 x=dict(workflow_status='改善中',owner='系統管理員',follow_up=True,cause_approved=True)
 assert mc.own_todo(x,dict(role='frontline',name='前線甲'))
 assert mc.own_todo(x,dict(role='admin',name='管理員'))
 assert not mc.own_todo(x,dict(role='accountant',name='系統管理員'))
 assert not mc.own_todo(x,dict(role='viewer',name='系統管理員'))
 x['workflow_status']='待確認結案';assert mc.own_todo(x,dict(role='accountant',name='會計甲'))


def test_admin_can_act_but_next_owner_is_frontline(client):
 sign(client,'admin099');act(client,'reason',**PLAN);act(client,'approve_follow')
 t,k,x=item(client);assert x['next_owner']=='前線人員'
 sign(client,'front099');act(client,'progress',evidence='由前線更新');act(client,'submit',result_period='2026-09',evidence='前線成果')
 assert item(client)[2]['next_owner']=='會計／覆核主管'
 sign(client,'acct099');act(client,'progress',expected=403);act(client,'finish')
 assert item(client)[2]['next_owner']=='—'
