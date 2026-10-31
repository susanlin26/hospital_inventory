"""Per-problem outcomes live in existing case JSON and immutable tracking events."""
import hashlib,json
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from . import auth,db,tracking
DONE={'已驗證改善','已確認合理原因'}
STATES={'改善中','待驗證',*DONE}
def key(o):
 s=o['snapshot'];ident=json.loads(o['identity']) if isinstance(o['identity'],str) and o['identity'].startswith('[') else o['identity']
 if not isinstance(ident,list):ident=[]
 return hashlib.sha256(json.dumps([o['hospital'],s.get('code'),s.get('unit'),ident[3] if len(ident)>3 else '',o['scope'],'idle' if o['rule']=='長期未耗用' else o['rule'],o['basis']],ensure_ascii=False).encode()).hexdigest()
def number(t):return t['created_at'].astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y%m')+'-'+str(t['id']).zfill(6)
def groups(c,t):
 result={}
 for o in c.execute('SELECT * FROM tracking_observations WHERE case_id=%s ORDER BY period,id',(t['id'],)):
  k=key(o);p=result.setdefault(k,dict(key=k,hospital=o['hospital'],code=o['snapshot'].get('code'),name=o['snapshot'].get('name'),unit=o['snapshot'].get('unit'),rule='idle' if o['rule']=='長期未耗用' else o['rule'],label='無耗用仍有庫存' if o['rule']=='長期未耗用' else o['snapshot']['label'],scope=o['scope'],basis=o['basis'],periods=[],ids=[],latest=o,joined_period=o['period']))
  p['periods']=sorted(set([*p['periods'],o['period']]));p['ids'].append(o['id']);p['latest']=o
 for k,p in result.items():
  saved=(t['body'].get('problem_results') or {}).get(k,{})
  legacy='已驗證改善' if t['status']=='改善完成' and t['body'].get('approved_by') else '已確認合理原因' if t['status']=='合理原因結案' else '改善中'
  p.update(status=saved.get('status',legacy),result=saved.get('result',''),updated_at=saved.get('at',''),confirmed_periods=saved.get('confirmed_periods',[]),history=saved.get('history',[]))
 return result

def summary(c,t):
 ps=groups(c,t);products={};global_count=0
 for p in ps.values():
  if p['code']=='ALL':global_count+=1;continue
  products.setdefault((p['hospital'],p['code']),[]).append(p['status'])
 counts={s:0 for s in STATES}
 for states in products.values():
  s='改善中' if '改善中' in states else '待驗證' if '待驗證' in states else '已驗證改善' if '已驗證改善' in states else '已確認合理原因'
  counts[s]+=1
 text='共'+str(len(products))+'項｜'+'｜'.join(s+str(counts[s])+'項' for s in ['改善中','待驗證','已驗證改善','已確認合理原因'] if counts[s])
 partial=counts['已驗證改善']>0 and counts['改善中']+counts['待驗證']>0
 return dict(case_number=number(t),problem_summary=text,problem_counts=counts,partial_improvement=partial,global_problems=global_count,all_handled=bool(ps) and all(p['status'] in DONE for p in ps.values()))

def candidate_map(c,h):
 result={}
 for t in c.execute("SELECT * FROM tracking_cases WHERE hospital=%s AND status IN ('改善中','待驗證')",(h,)):
  for k,p in groups(c,t).items():
   if p['status'] not in DONE:result.setdefault(k,[]).append((t['id'],p['joined_period']))
 return result

def auto(c,h,scope):
 candidates=candidate_map(c,h)
 for o in c.execute("SELECT * FROM tracking_observations WHERE hospital=%s AND scope=%s AND case_id IS NULL AND NOT link_suppressed AND rule<>'data' AND level<>'資料問題' ORDER BY period,id FOR UPDATE",(h,scope)):
  matches=list({cid for cid,p in candidates.get(key(o),[]) if p<o['period']})
  if len(matches)==1:
   cid=matches[0];c.execute("UPDATE tracking_observations SET case_id=%s,link_origin='auto',revision=revision+1 WHERE id=%s",(cid,o['id']));tracking.event(c,h,'跨月自動接續',dict(case_id=cid,notice='本期異常已接續原案，本期原因待確認',period=o['period']),oid=o['id'],cid=cid)

def assessment(p,generated,period):
 found=next((o for o in generated if key(o)==p['key']),None)
 if not found:return dict(period=period,state='資料不足，無法判定')
 if found['rule']=='high_coverage':return dict(period=period,state='舊版覆蓋提醒，僅保留明細',snapshot=found['snapshot'])
 f=found['snapshot'].get('facts',{});r=found['rule']
 valid=f.get('valid',True) and f.get('zero_consistent',True)
 if r.startswith('standard30'):valid=f.get('eligible',False)
 if r in ('high_turnover','low_stock'):valid=valid and f.get('value') is not None
 if not valid:return dict(period=period,state='資料不足，無法判定',snapshot=found['snapshot'])
 return dict(period=period,state='本期仍達門檻' if found['active'] else '本期未達門檻',snapshot=found['snapshot'])

def view(c,t,generated=None,period=''):
 ps=list(groups(c,t).values())
 for p in ps:
  o=p.pop('latest');p['assessment']=assessment(p,generated if generated is not None else [o],period or o['period']);p['source_basis']=o['snapshot'];p['confirmation_pending']=o['link_origin']=='auto' and not o['confirmation']
 return dict(**summary(c,t),problems=tracking.plain(ps),period=period)

def act(c,t,body,u,generated,period):
 auth.authorize(u,t['hospital'],write=True)
 if body.get('revision')!=t['revision']:raise HTTPException(409,'案件已更新，請重新開啟')
 action=body.get('action');selected=list(dict.fromkeys(body.get('keys',[])));ps=groups(c,t)
 if not selected or any(k not in ps for k in selected):raise HTTPException(422,'請勾選原案內的問題')
 if t['status'] in tracking.CLOSED and action!='reopen':raise HTTPException(409,'整案已結案，請先由主管重啟')
 note=str(body.get('note','')).strip()
 if not note:raise HTTPException(422,'請填本次共同說明')
 if action in ('verify','reopen','return','close'):auth.authorize(u,t['hospital'],manager=True)
 if action not in ('submit','verify','reasonable','reopen','return','carry','progress','close'):raise HTTPException(422,'操作不正確')
 details=dict(t['body']);results={k:{'status':p['status'],**(details.get('problem_results',{}).get(k,{}))} for k,p in ps.items()};now=datetime.now(ZoneInfo('Asia/Taipei')).isoformat();after=[]
 for k in selected:
  p=ps[k];old=dict(results.get(k,{}));state=p['status'];a=assessment(p,generated,period);a['observation_id']=p['ids'][-1]
  if action in ('submit','verify','reasonable') and a['state']=='資料不足，無法判定':raise HTTPException(422,'資料不足，無法送驗或認定改善')
  if action=='submit' and state!='改善中':raise HTTPException(422,'僅勾選改善中的問題送驗')
  if action=='submit' and (not body.get('verification') or not body.get('observation_period')):raise HTTPException(422,'請一次填共同驗證方式與觀察期間')
  if action=='verify' and state!='待驗證':raise HTTPException(422,'僅待驗證問題可確認改善')
  if action in ('carry','progress','reasonable') and state in DONE:raise HTTPException(422,'已處理問題不需重填進度，若再次發生請重啟')
  if action=='carry' and (not details.get('cause') or not details.get('measure')):raise HTTPException(422,'原案未填原因與措施，請先補齊原案')
  if action=='reasonable' and p['rule'].startswith('standard30') and body.get('cause_category')=='住院人日變化':raise HTTPException(422,'人日變化不能單獨解釋標準化每床耗用異常')
  if action=='reasonable':
   for original in c.execute('SELECT hospital,period FROM tracking_observations WHERE id=ANY(%s)',(p['ids'],)):db.check_open(c,original['hospital'],original['period'])
  if action=='close':continue
  if action=='reopen' and state not in DONE:raise HTTPException(422,'只有已處理問題可重啟')
  newstate={'submit':'待驗證','verify':'已驗證改善','reasonable':'已確認合理原因','reopen':'改善中','return':'改善中'}.get(action,state)
  if action=='return' and state!='待驗證':raise HTTPException(422,'只有待驗證問題可退回')
  history=[*old.get('history',[]),dict(status=state,result=old.get('result',''),at=now,previous_at=old.get('at'),action=action,note=note,operator=u['id'],assessment=a)]
  results[k]={**old,'status':newstate,'result':note,'at':now,'operator':u['id'],'history':history,'verification':body.get('verification',old.get('verification','')),'observation_period':body.get('observation_period',old.get('observation_period','')),'cause_category':body.get('cause_category',old.get('cause_category','其他')),'confirmed_periods':sorted(set([*old.get('confirmed_periods',[]),*([period] if action=='carry' else [])]))}
  after.append(dict(key=k,before=state,after=newstate))
 if action=='carry':
  if not details.get('cause') or not details.get('measure'):raise HTTPException(422,'原案未填原因與措施，請先補齊原案')
  ids=[i for k in selected for i in ps[k]['ids']]
  rows=c.execute('SELECT * FROM tracking_observations WHERE id=ANY(%s) AND period=%s',(ids,period)).fetchall()
  if not rows:raise HTTPException(422,'本期無可沿用原因的有效觀察紀錄')
  tracking.batch_confirm(c,dict(ids=[o['id'] for o in rows],fingerprints={str(o['id']):o['fingerprint'] for o in rows},revisions={str(o['id']):o['revision'] for o in rows},cause_category='其他',cause=details['cause']+'；沿用原案措施：'+details['measure']+'；'+note),u)
 details['problem_results']=results
 current=[results.get(k,{}).get('status',p['status']) for k,p in ps.items()]
 status='待驗證' if current and all(s in DONE or s=='待驗證' for s in current) and any(s=='待驗證' for s in current) else '改善中'
 if action=='close':
  if not current or any(s not in DONE for s in current):raise HTTPException(422,'尚有問題未處理完成，不能結案')
  status='改善完成' if any(s=='已驗證改善' for s in current) else '合理原因結案';details.update(approved_by=u['id'],approved_at=now,completed_date=now[:10],result=note)
 details['progress']=note
 tracking.event(c,t['hospital'],'案件問題整批處理',dict(action=action,note=note,changes=after,after=dict(status=status,body=details)),u['id'],cid=t['id'])
 c.execute('UPDATE tracking_cases SET status=%s,body=%s,revision=revision+1,updated_by=%s,updated_at=now() WHERE id=%s',(status,Jsonb(tracking.plain(details)),u['id'],t['id']));db.audit(c,u['id'],'case_problem_'+action,t['hospital'],t['id'],dict(keys=selected));return dict(id=t['id'])


def decorate(c,rows):
 cases=c.execute("SELECT * FROM tracking_cases WHERE hospital=ANY(%s) AND id IN (SELECT case_id FROM tracking_observations WHERE hospital=ANY(%s) AND snapshot->>'code'=ANY(%s))",(list({o['hospital'] for o in rows}),list({o['hospital'] for o in rows}),list({o['snapshot'].get('code') for o in rows}))).fetchall() if rows else []
 matches={};by={}
 for t in cases:
  by[t['id']]=t
  for k,p in groups(c,t).items():matches.setdefault(k,[]).append((t,p['status']))
 from .engine import previous
 active_batches={r['id'] for r in c.execute('SELECT id FROM batches WHERE hospital=ANY(%s) AND active AND deleted_at IS NULL',(list({o['hospital'] for o in rows}),))} if rows else set()
 history=list(c.execute("SELECT * FROM tracking_observations WHERE hospital=ANY(%s) AND period=ANY(%s) AND snapshot->>'code'=ANY(%s) AND active",(list({o['hospital'] for o in rows}),list({previous(o['period']) for o in rows}),list({o['snapshot'].get('code') for o in rows})))) if rows else []
 for o in rows:
  o['continuous']=bool(o['active'] and any(a['period']==previous(o['period']) and key(a)==key(o) and a['snapshot'].get('source') and all(src.get('batch_id') in active_batches for src in a['snapshot']['source'] if src.get('period')==a['period']) for a in history))
  related=matches.get(key(o),[]);o['case_number']=number(by[o['case_id']]) if o.get('case_id') in by else ''
  o['recurrence']=bool(o['active'] and not o.get('case_id') and any(s in DONE or t['status'] in tracking.CLOSED for t,s in related))
  o['candidate_cases']=[dict(id=t['id'],number=number(t),title=t['title'],status=s,closed=t['status'] in tracking.CLOSED) for t,s in related]
 return rows
