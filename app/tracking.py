from .performance import timed
"""提醒觀察、整批原因與多品項案件。新增資料，保留舊案；判定依據與來源版本分開保存。"""
import calendar,hashlib,json
from datetime import date,datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from . import db,engine,auth
from .analytics import rule_for

CLOSED={'改善完成','合理原因結案','舊版結案待分類'}
CAUSES=['住院人日變化','照護需求改變','耗用單位成本變化','盤點或異動調整','備貨安排','其他']
LABELS={'usage_up':'耗用增加','usage_down':'耗用下降','standard30_up':'標準30日每床耗用增加','standard30_down':'標準30日每床耗用下降','high_turnover':'高庫存低耗用','high_coverage':'月底庫存覆蓋偏高','low_stock':'低庫存風險','idle':'無耗用仍有庫存','data':'資料問題'}

def plain(x):
 return json.loads(json.dumps(x,ensure_ascii=False,default=str))

def digest(x):
 def canonical(v):
  if isinstance(v,dict):return {k:canonical(a) for k,a in v.items()}
  if isinstance(v,list):return [canonical(a) for a in v]
  if isinstance(v,(D,str)) and __import__('re').fullmatch(r'[+-]?\d+(?:\.\d+)?',str(v)):
   n=D(v);return format(n.normalize(),'f') if n else '0'
  return v
 return hashlib.sha256(json.dumps(canonical(plain(x)),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def identity(x):return json.dumps([x.get('code'),x.get('name'),x.get('unit'),x.get('filename_department') or ''],ensure_ascii=False)

def observations(d,baseline):
 h,p=d['hospital'],d['period'];scope='__all__' if d.get('all_departments') else d.get('selected_department') or '';base=d['baseline'];out=[];source_index={}
 for raw in d['source_rows']:source_index.setdefault(identity(raw),[]).append(raw)
 def make(x,rule,active,facts,formula,current=None,reference=None,difference=None,unit='元',level='品項'):
  ident=identity(x) if level in ('品項','資料問題') else 'ALL';key_basis=baseline if rule.startswith(('usage_','standard30_')) or rule=='data' else 'fixed'
  source=[{k:r.get(k) for k in ('period','code','name','unit','batch_id','version','file_id','row','sheet','category_version','parser_version')} for r in (source_index.get(ident,[]) if level in ('品項','資料問題') else d['source_rows']) if r['period'] in set([p,*facts.get('periods',[])])]
  snapshot=plain(dict(tracking_policy='089',code=x.get('code','ALL'),name=x.get('name','全院'),unit=x.get('unit',''),category=x.get('category','整體指標'),rule=rule,label=LABELS.get(rule,rule),current=current,reference=reference,difference=difference,value_unit=unit,formula=formula,facts=facts,source=source,rule_version=d['rule_version'],baseline=key_basis,periods=facts.get('periods',[]),used=x.get('used'),ending=x.get('ending'),quantity=x.get('qty')))
  if rule in ('high_turnover','high_coverage') and facts.get('value') is not None:snapshot['severity']=('週轉嚴重偏慢' if D(str(facts['value']))>D(str(facts['severe'])) else '週轉偏慢') if rule=='high_turnover' else '舊版覆蓋提醒'
  out.append(dict(hospital=h,period=p,scope=scope,identity=ident,rule=rule,basis=key_basis,category=snapshot['category'],level=level,snapshot=snapshot,fingerprint=digest(dict(rule=rule,facts=facts)),active=bool(active)))
 for x in d['items']:
  from .inventory_rules import flags
  inventory=flags(x,d['rules'])
  rr=rule_for(d['rules'],x['category']);ch=x['change'];valid=x['used']>=0 and x['qty']>=0 and x['ending']>=0 and x['opening']>=0
  mismatch=(x['used']==0)!=(x['qty']==0);problems=[]
  if not valid:problems.append('淨耗用金額／數量或期初／期末庫存為負，請核對來源')
  if mismatch:problems.append('耗用金額與數量的零值不一致，不能認定完全無耗用')
  if x.get('baseline_used') is None:problems.append('缺少比較期同品項、規格或單位資料：'+','.join(base))
  elif x['baseline_used']<=0:problems.append('基準為零' if x['baseline_used']==0 else '基準為負值')
  base_qty=x.get('baseline_qty');base_used=x.get('baseline_used');base_valid=base_qty is not None and base_qty>=0 and base_used is not None and base_used>=0 and ((base_qty==0)==(base_used==0))
  if base_qty is not None and not base_valid:problems.append('基準耗用數量／金額為負或零值不一致')
  if x.get('low_stock_days') is None:problems.append(x.get('low_stock_reason','前三完整月歷史不足，無法判定低庫存'))
  make(x,'data',bool(problems),dict(reasons=problems,used=x['used'],qty=x['qty'],opening=x['opening'],ending=x['ending'],baseline=x.get('baseline_used'),periods=base),'；'.join(problems) or '資料有效',unit='說明')
  for direction in ('up','down'):
   sign=1 if direction=='up' else -1;hit=x['used']>=0 and x['qty']>=0 and x.get('baseline_used') is not None and x['baseline_used']>0 and ch['pct'] is not None and sign*ch['pct']>=D(rr['change_pct']) and sign*ch['amount']>=D(rr['change_amount'])
   facts=dict(used=x['used'],baseline=x.get('baseline_used'),pct=ch['pct'],difference=ch['amount'],change_pct=rr['change_pct'],change_amount=rr['change_amount'],valid=valid and base_valid,quantity_valid=x['qty']>=0,zero_consistent=not mismatch,periods=base)
   make(x,'usage_'+direction,hit,facts,'差異＝本期－基準；增減%＝差異÷正值基準×100%；百分比與金額均達門檻',x['used'],x.get('baseline_used'),ch['amount'])
  for rule,value,formula in [('high_turnover',x['days'],'存貨週轉天數＝當月天數×（期初庫存＋期末庫存）÷2÷本月耗用金額'),('high_coverage',x['coverage'],'月底庫存覆蓋天數＝期末庫存金額÷本月耗用金額×當月天數；不同於週轉天數及歷史數量推估可用天數')]:
   hit=rule=='high_turnover' and inventory['high']
   make(x,rule,hit,dict(value=value,threshold=rr['high_days'],severe=rr['severe_days'],valid=valid,quantity_valid=x['qty']>=0,zero_consistent=not mismatch,used=x['used'],ending=x['ending'],opening=x['opening'] if rule=='high_turnover' else None,periods=[p]),formula,value,D(rr['high_days']),value-D(rr['high_days']) if value is not None else None,'天')
  make(x,'idle',inventory['idle'],dict(used=x['used'],qty=x['qty'],ending=x['ending'],valid=valid,periods=[p]),'淨耗用金額＝0且淨耗用數量＝0，期末庫存金額>0',x['ending'],D(0),x['ending'])
  out[-1]['snapshot'].update(long_term=bool(x.get('idle_confirmed')),idle_observed_days=x.get('idle_observed_days',0),idle_days_threshold=rr['idle_days'],idle_warn_days_threshold=rr['idle_warn_days'],persistent=bool(x.get('idle_persistent')))
  value=x.get('low_stock_days');prior=[engine.previous(p)]
  for _ in range(2):prior.append(engine.previous(prior[-1]))
  make(x,'low_stock',inventory['low'],dict(value=value,threshold=rr['low_days'],valid=valid,quantity_valid=x['qty']>=0,zero_consistent=not mismatch,periods=prior),'推估庫存可用天數＝期末數量÷前三完整月平均每日耗用量；不得混加不同單位',value,D(rr['low_days']),value-D(rr['low_days']) if value is not None else None,'天')
 # 保留仍有管理用途的採購、長期未耗用、跨月銜接檢核。
 names={'採購單價上漲','採購單價下降'}
 for f in d['findings']:
  if f['level']!='品項' or not (f['rule'] in names or f['rule'].startswith('跨月')):continue
  x=next((x for x in d['items'] if x['code']==f['code']),None)
  if not x:continue
  if x['used']<0 or x['qty']<0 or x['ending']<0:continue
  data=f['rule'].startswith('跨月');unit='數量（'+x['unit']+'）' if '數量' in f['rule'] else '天' if f['rule']=='長期未耗用' else '元'
  make(x,f['rule'],True,dict(value=f['value'],basis=f['basis'],periods=x.get('purchase_periods',[]) if '採購' in f['rule'] else [p,engine.previous(p)],threshold=rule_for(d['rules'],x['category'])['idle_days'] if f['rule']=='長期未耗用' else {k:rule_for(d['rules'],x['category'])[k] for k in ('purchase_pct','purchase_amount')} if '採購' in f['rule'] else None),f['basis'],f['value'],None,None,unit,'資料問題' if data else '品項')
 for raw in d['source_rows']:
  if raw['period']==p and not raw.get('valid',True):
   issues=[i.get('reason','來源驗證未通過') for i in (d.get('validation') or {}).get('issues',[]) if i.get('row')==raw.get('row')]
   make(raw,'data',True,dict(reasons=issues or ['來源列未通過驗證，未納入分析'],periods=[p]),'；'.join(issues) or '來源列未通過驗證，未納入分析',unit='說明',level='資料問題')
 t=d['total'];b=d['daily_comparison']['baseline'];bc=b.get('per_patient_day');cur=t.get('standard30_per_bed');ref=bc*30 if bc is not None else None;pd=t.get('patient_days');eligible=t.get('comparison_eligible') and b.get('comparison_eligible',b.get('per_patient_day') is not None) and t.get('care_scope')==b.get('care_scope');used=t.get('used');eligible=eligible and all(x['used']>=0 and x['qty']>=0 and ((x['used']==0)==(x['qty']==0)) for x in d['items']);rr=rule_for(d['rules']);excess=used-bc*pd if eligible and used is not None and bc is not None and pd else None;pct=(cur-ref)/ref*100 if eligible and cur is not None and ref is not None and ref>0 else None
 for direction in ('up','down'):
  sign=1 if direction=='up' else -1
  make({},'standard30_'+direction,excess is not None and pct is not None and sign*excess>=D(rr['change_amount']) and sign*pct>=D(rr['change_pct']) and used>=0,dict(used=used,patient_days=pd,baseline_daily=bc,scope=t.get('care_scope'),base_scope=b.get('care_scope'),eligible=bool(eligible),pct=pct,excess=excess,change_pct=rr['change_pct'],change_amount=rr['change_amount'],periods=base),'標準30日＝適用耗用÷同範圍住院人日×30；超出基準金額＝本月適用耗用－基準每人日耗用×本月人日',cur,ref,cur-ref if cur is not None and ref is not None else None,'元／床／30日','整體')
 if not eligible or pct is None:
  why=t.get('daily_status','')+'；'+str(b.get('reason',''))+'；基準期須有正值及同範圍人日'
  make({},'data',True,dict(reason=why,used=used,patient_days=pd,baseline_daily=bc,scope=t.get('care_scope'),base_scope=b.get('care_scope'),periods=base),why,unit='說明',level='整體')
 return list({(o['identity'],o['rule'],o['basis']):o for o in out}.values())

def event(c,h,action,body,uid=None,oid=None,cid=None):
 c.execute('INSERT INTO tracking_events(hospital,observation_id,case_id,action,body,operator) VALUES(%s,%s,%s,%s,%s,%s)',(h,oid,cid,action,Jsonb(plain(body)),uid))

def migrate_legacy(c,h):
 # 舊編號原樣保留為 legacy_id；新案使用獨立連號，畫面明示舊案 #。
 for r in c.execute('SELECT * FROM reviews WHERE hospital=%s',(h,)).fetchall():
  status='舊版待確認' if r['status']=='待確認' else '改善中' if r['status'] in ('改善中','追蹤中') else '待驗證' if r['status']=='待驗證' else '改善完成' if r['details'].get('outcome')=='improved' and r['approved'] and r['confirmed'] and r['details'].get('result') and r['details'].get('completed_date') else '合理原因結案' if r['details'].get('outcome')=='reasonable' else '舊版結案待分類'
  body={**r['details'],**{k:plain(r[k]) for k in ('cause','measure','owner','due_date','note','confirmed','approved','code','rule','department')},'legacy_record':plain(r),'legacy_basis_notice':'舊版未完整保存判定來源；保留原記錄，不用現行數據補寫歷史'}
  c.execute('INSERT INTO tracking_cases(hospital,start_period,title,status,body,legacy_id,updated_by) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(legacy_id) DO NOTHING',(h,r['period'],'舊案 #'+str(r['id'])+' '+r['code']+' '+r['rule'],status,Jsonb(body),r['id'],r['updated_by']))

@timed('tracking')
def sync(c,reports,baseline):
 from .performance import source_revision,tracking_revision
 for h in sorted({d['hospital'] for d in reports}):c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(h+':tracking',))
 for d in reports:
  h,p=d['hospital'],d['period'];c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(h+':tracking',));scope='__all__' if d.get('all_departments') else d.get('selected_department') or ''
  source=d.get('_performance_source');track=tracking_revision(c,h)
  scan=c.execute('SELECT source_token,tracking_token,scan_state FROM tracking_work_state WHERE hospital=%s AND period=%s AND scope=%s AND basis=%s',(h,p,scope,baseline)).fetchone()
  policy_ok=c.execute("SELECT 1 FROM tracking_observations WHERE hospital=%s AND period=%s AND scope=%s AND snapshot->>'tracking_policy'='089' LIMIT 1",(h,p,scope)).fetchone()
  if policy_ok and source and source==source_revision(c) and scan and scan['scan_state']=='done' and scan['source_token']==source and scan['tracking_token']==track:continue
  migrate_legacy(c,h)
  oldrows=c.execute('SELECT * FROM tracking_observations WHERE hospital=%s AND period=%s AND scope=%s AND basis IN (%s,\'fixed\') FOR UPDATE',(h,p,scope,baseline)).fetchall();oldmap={(o['identity'],o['rule'],o['basis']):o for o in oldrows};seen=set()
  from . import case_problems
  continuing=case_problems.candidate_map(c,h)
  new_observations=[]
  for o in observations(d,baseline):
   key=(o['identity'],o['rule'],o['basis']);seen.add(key);old=oldmap.get(key)
   if not old and o['rule'] in ('high_coverage','長期未耗用'):continue
   if not old and not o['active'] and not any(start<o['period'] for _,start in continuing.get(case_problems.key(o),[])):continue
   if old:
    changed=old['fingerprint']!=o['fingerprint'] or old['active']!=o['active']
    if changed or old['snapshot']!=o['snapshot']:
     event(c,h,'判定資料更新' if changed else '來源版本更新（判定未變）',dict(before=old['snapshot'],after=o['snapshot'],before_active=old['active'],after_active=o['active']),oid=old['id'])
     c.execute('UPDATE tracking_observations SET snapshot=%s,fingerprint=%s,active=%s,category=%s,revision=revision+1,updated_at=now() WHERE id=%s',(Jsonb(o['snapshot']),o['fingerprint'],o['active'],o['category'],old['id']))
   else:
    new_observations.append(o)
  if new_observations:
   # One statement and one revision change, while preserving every reminder and its own event.
   inserted=c.execute('INSERT INTO tracking_observations(hospital,period,scope,identity,rule,basis,category,level,snapshot,fingerprint,active) SELECT hospital,period,scope,identity,rule,basis,category,level,snapshot,fingerprint,active FROM jsonb_to_recordset(%s) AS x(hospital text,period text,scope text,identity text,rule text,basis text,category text,level text,snapshot jsonb,fingerprint text,active boolean) RETURNING id,hospital,snapshot',(Jsonb(plain(new_observations)),)).fetchall()
   events=[dict(hospital=o['hospital'],observation_id=o['id'],body=o['snapshot']) for o in inserted]
   c.execute("INSERT INTO tracking_events(hospital,observation_id,action,body) SELECT hospital,observation_id,'自動產生提醒',body FROM jsonb_to_recordset(%s) AS x(hospital text,observation_id bigint,body jsonb)",(Jsonb(events),))
  for key,old in oldmap.items():
   if old['rule'] in ('high_coverage','長期未耗用'):
    if old['active']:c.execute('UPDATE tracking_observations SET active=false WHERE id=%s',(old['id'],))
    continue
   if key not in seen and old['active']:
    snap={**old['snapshot'],'unavailable_reason':'目前有效資料已無此品項／提醒；保留舊觀察，不視為改善完成'}
    c.execute('UPDATE tracking_observations SET active=false,snapshot=%s,fingerprint=%s,revision=revision+1 WHERE id=%s',(Jsonb(snap),digest(snap['unavailable_reason']),old['id']));event(c,h,'提醒來源已缺漏',dict(before=old['snapshot'],after=snap),oid=old['id'])
  autolink(c,h,scope)
  c.execute("INSERT INTO tracking_work_state(hospital,period,scope,basis,source_token,tracking_token) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(hospital,period,scope,basis) DO UPDATE SET source_token=excluded.source_token,tracking_token=excluded.tracking_token,scan_state='done',last_error=NULL",(h,p,scope,baseline,source,tracking_revision(c,h)))
  c.execute('INSERT INTO tracking_scans(hospital,period,scope,basis) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(h,p,scope,baseline))

def autolink(c,h,scope):
 from .case_problems import auto
 auto(c,h,scope)

def status(o):
 if o['confirmation'] and o['confirmed_fingerprint']==o['fingerprint']:return '合理原因已結案'
 if o['case_id']:return '已納入改善案'
 return '待確認'

def view(c,hs,p,scope,baseline):
 obs=c.execute('SELECT * FROM tracking_observations WHERE hospital=ANY(%s) AND period=%s AND scope=%s AND basis IN (%s,\'fixed\') AND (active OR confirmation IS NOT NULL OR case_id IS NOT NULL) ORDER BY hospital,category,id',(hs,p,scope,baseline)).fetchall()
 history=c.execute('SELECT hospital,scope,identity,rule,basis,period FROM tracking_observations WHERE hospital=ANY(%s) AND scope=%s AND period<=%s AND active',(hs,scope,p)).fetchall();keys={(r['hospital'],r['scope'],r['identity'],r['rule'],r['basis'],r['period']) for r in history}
 cases=c.execute('SELECT * FROM tracking_cases WHERE hospital=ANY(%s) ORDER BY id DESC',(hs,)).fetchall();links=c.execute('SELECT * FROM tracking_observations WHERE hospital=ANY(%s) AND case_id IS NOT NULL ORDER BY period,id',(hs,)).fetchall();today=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat();case_map={r['id']:r for r in cases}
 for o in obs:
  o['processing']=status(o);o['needs_reconfirm']=bool(o['confirmation'] and o['confirmed_fingerprint']!=o['fingerprint']);n=0;month=p
  while (*[o[k] for k in ('hospital','scope','identity','rule','basis')],month) in keys:n+=1;month=engine.previous(month)
  o['continuous_months']=n;o['data_issue']=o['rule']=='data' or o['level']=='資料問題'
  candidate_ids={a['case_id'] for a in links if a['hospital']==o['hospital'] and a['identity']==o['identity'] and a['rule']==o['rule'] and a['scope']==o['scope'] and a['basis']==o['basis'] and a['period']<p};o['candidate_cases']=[{k:case_map[cid][k] for k in ('id','title','status')} for cid in sorted(candidate_ids) if cid in case_map]
  o['case_title']=case_map.get(o['case_id'],{}).get('title');o['notice']='已接續原案，本月原因待確認' if o['link_origin']=='auto' and not o['confirmation'] else '需重新確認' if o['needs_reconfirm'] else ''
 for t in cases:
  t['overdue']=t['status'] not in CLOSED and bool(t['body'].get('due_date')) and t['body']['due_date']<today
  t['observations']=[o for o in links if o['case_id']==t['id']]
 normal=[o for o in obs if o['active'] and not o['data_issue'] and o['level']=='品項'];pending={ (o['hospital'],o['identity']) for o in normal if status(o)=='待確認' or o['needs_reconfirm'] or (o['link_origin']=='auto' and not o['confirmation'])};continuous={(o['hospital'],o['identity']) for o in normal if o['continuous_months']>=2}
 closures=c.execute("SELECT * FROM tracking_batches WHERE hospital=ANY(%s) ORDER BY id DESC",(hs,)).fetchall()
 return plain(dict(observations=obs,cases=cases,closures=closures,stats=dict(pending=len(pending),continuous=len(continuous),working=sum(t['status']=='改善中' for t in cases),overdue=sum(t['overdue'] for t in cases),completed=sum(t['status']=='改善完成' for t in cases)),as_of=today,scope=scope,period=p,baseline=baseline,note='提醒依所選月份；案件為目前狀態，非歷史月底狀態。逾期＝未完成且期限早於今日；資料問題及全院提醒不計入異常品項數。'))

def selected(c,body,u,check_closed=True):
 ids=body.get('ids',[])
 if not isinstance(ids,list) or not ids or len(ids)>10000:raise HTTPException(422,'請選取提醒（單次最多10000筆）')
 hospitals=c.execute('SELECT DISTINCT hospital FROM tracking_observations WHERE id=ANY(%s)',(list(set(ids)),)).fetchall()
 for h in sorted(x['hospital'] for x in hospitals):c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(h+':tracking',))
 rows=c.execute('SELECT * FROM tracking_observations WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(list(set(ids)),)).fetchall()
 if len(rows)!=len(set(ids)):raise HTTPException(409,'提醒已變更，請重新載入')
 hs={r['hospital'] for r in rows}
 if len(hs)!=1:raise HTTPException(422,'一次只能處理同院提醒')
 for o in rows:
  auth.authorize(u,o['hospital'],write=True)
  if check_closed:db.check_open(c,o['hospital'],o['period'])
  if str(body.get('fingerprints',{}).get(str(o['id']),''))!=o['fingerprint']:raise HTTPException(409,'判定資料已變更，請重新載入確認')
  if body.get('revisions',{}).get(str(o['id']))!=o['revision']:raise HTTPException(409,'其他人已修改此提醒，請重新載入')
 return rows

def batch_confirm(c,body,u):
 rows=selected(c,body,u);cause=str(body.get('cause','')).strip();category=body.get('cause_category','其他')
 if not cause or category not in CAUSES:raise HTTPException(422,'原因類別與原因說明必填')
 if category=='住院人日變化' and any(o['rule'].startswith('standard30_') for o in rows):raise HTTPException(422,'住院人日變化不能單獨解釋標準30日每床耗用異常，請選擇適用原因並說明')
 if any(o['rule']=='data' or o['level']=='資料問題' for o in rows):raise HTTPException(422,'資料問題請先修正來源，不能確認為一般合理耗用原因')
 batch=c.execute('INSERT INTO tracking_batches(hospital,body,operator) VALUES(%s,%s,%s) RETURNING id',(rows[0]['hospital'],Jsonb(plain(dict(cause=cause,cause_category=category,ids=[o['id'] for o in rows],snapshots={str(o['id']):o['snapshot'] for o in rows}))),u['id'])).fetchone()['id']
 for o in rows:
  confirm=plain(dict(batch_id=batch,cause=cause,cause_category=category,operator=u['id'],name=u['name'],at=datetime.now(ZoneInfo('Asia/Taipei')),snapshot=o['snapshot']))
  event(c,o['hospital'],'合理原因確認',dict(before=o['confirmation'],after=confirm),u['id'],o['id'],o['case_id']);c.execute('UPDATE tracking_observations SET confirmation=%s,confirmed_fingerprint=fingerprint,revision=revision+1 WHERE id=%s',(Jsonb(confirm),o['id']))
 db.audit(c,u['id'],'tracking_batch_confirm',rows[0]['hospital'],batch,dict(ids=[o['id'] for o in rows]));return dict(id=batch,count=len(rows))

def withdraw(c,body,u):
 if not str(body.get('reason','')).strip():raise HTTPException(422,'請填撤回原因')
 rows=selected(c,body,u)
 for o in rows:
  if not o['confirmation']:continue
  if o['confirmation']['operator']!=u['id']:auth.authorize(u,o['hospital'],manager=True)
  event(c,o['hospital'],'撤回原因確認',dict(before=o['confirmation'],reason=str(body.get('reason','')).strip()),u['id'],o['id'],o['case_id']);c.execute('UPDATE tracking_observations SET confirmation=NULL,confirmed_fingerprint=NULL,revision=revision+1 WHERE id=%s',(o['id'],))
 return dict(count=len(rows))

def get_case(c,cid,u):
 t=c.execute('SELECT * FROM tracking_cases WHERE id=%s FOR UPDATE',(cid,)).fetchone()
 if not t:raise HTTPException(404,'案件不存在')
 auth.authorize(u,t['hospital'],write=True);return t

def link(c,body,u):
 rows=selected(c,body,u);cid=body.get('case_id');t=get_case(c,int(cid),u) if cid else None
 if t and (t['hospital']!=rows[0]['hospital'] or t['status'] in CLOSED):raise HTTPException(422,'只能加入同院未完成案件')
 if any(o['rule']=='data' or o['level']=='資料問題' for o in rows):raise HTTPException(422,'請先處理資料問題，再建立改善案')
 if t:
  from .case_problems import groups,key,DONE
  existing=groups(c,t)
  if any(key(o) in existing and existing[key(o)]['status'] in DONE and o['period'] not in existing[key(o)]['periods'] for o in rows):raise HTTPException(409,'原案該問題已處理完成；再次異常請先重啟該問題或另立案件')
 if not t:
  title=str(body.get('title','')).strip()
  if not title:raise HTTPException(422,'請填案件名稱')
  from .case_problems import candidate_map,key
  candidates=candidate_map(c,rows[0]['hospital'])
  if any(any(start<=o['period'] for _,start in candidates.get(key(o),[])) for o in rows):raise HTTPException(409,'同一問題已有未結案件，請查看或加入原案；多案時請選擇')
  if any(o['case_id'] for o in rows):raise HTTPException(409,'選取提醒已有案件，請加入原案或明確改掛')
  t=c.execute("INSERT INTO tracking_cases(hospital,start_period,title,status,body,updated_by) VALUES(%s,%s,%s,'改善中',%s,%s) RETURNING *",(rows[0]['hospital'],min(o['period'] for o in rows),title,Jsonb({k:str(body[k]).strip()[:5000] for k in ('cause','responsible_unit','measure','due_date') if k in body}),u['id'])).fetchone()
 for o in rows:
  if o['case_id'] and o['case_id']!=t['id'] and not body.get('replace'):raise HTTPException(409,'已有其他案件，請明確選擇改掛')
  if o['case_id']==t['id']:continue
  event(c,o['hospital'],'納入改善案',dict(before=o['case_id'],after=t['id'],snapshot=o['snapshot']),u['id'],o['id'],t['id']);c.execute("UPDATE tracking_observations SET case_id=%s,link_origin='manual',link_suppressed=false,revision=revision+1 WHERE id=%s",(t['id'],o['id']))
 autolink(c,t['hospital'],rows[0]['scope']);db.audit(c,u['id'],'tracking_case_link',t['hospital'],t['id'],dict(ids=[o['id'] for o in rows]));return dict(id=t['id'])

def unlink(c,body,u):
 if not str(body.get('reason','')).strip():raise HTTPException(422,'請填取消關聯原因')
 rows=selected(c,body,u)
 for o in rows:
  event(c,o['hospital'],'取消案件關聯',dict(case_id=o['case_id'],reason=body.get('reason','')),u['id'],o['id'],o['case_id']);c.execute('UPDATE tracking_observations SET case_id=NULL,link_origin=NULL,link_suppressed=true,revision=revision+1 WHERE id=%s',(o['id'],))
 return dict(count=len(rows))

def update_case(c,cid,body,u):
 t=get_case(c,cid,u)
 if body.get('revision')!=t['revision']:raise HTTPException(409,'案件已被修改，請重新載入')
 action=body.get('action','update');status=body.get('status',t['status']);details={**t['body'],**{k:str(body.get(k,t['body'].get(k,''))).strip()[:5000] for k in ('cause','responsible_unit','measure','due_date','progress','verification','observation_period','result','completed_date')}}
 if details.get('due_date'):date.fromisoformat(details['due_date'])
 if details.get('completed_date'):date.fromisoformat(details['completed_date'])
 if action=='reopen':
  if t['status'] not in CLOSED:raise HTTPException(422,'只有結案案件可重啟')
  auth.authorize(u,t['hospital'],manager=True);status='改善中'
 elif t['status'] in CLOSED:raise HTTPException(409,'已結案紀錄不可覆寫，請先重啟並留下原因')
 operation=body.get('operation','')
 if operation in ('progress','edit') and status!=t['status']:raise HTTPException(422,'此操作不能變更案件狀態')
 if operation=='submit' and (t['status']!='改善中' or status!='待驗證'):raise HTTPException(422,'改善中的案件才能送交驗證')
 if operation in ('verify','return'):
  auth.authorize(u,t['hospital'],manager=True)
  if t['status']!='待驗證' or status!=('改善完成' if operation=='verify' else '改善中'):raise HTTPException(422,'只有待驗證案件可完成或退回')
 if status not in ('改善中','待驗證','改善完成'):raise HTTPException(422,'案件狀態不正確')
 if operation!='progress' and status in ('待驗證','改善完成') and any(not details[k] for k in ('responsible_unit','measure','due_date','verification','observation_period')):raise HTTPException(422,'送驗證前請填負責單位、措施、期限、驗證方式及觀察期間（每案一次）')
 if status=='改善完成':
  auth.authorize(u,t['hospital'],manager=True)
  if any(not details[k] for k in ('cause','result','completed_date')):raise HTTPException(422,'改善完成須原因、結果及實際完成日期')
  details.update(approved_by=u['id'],approved_at=datetime.now(ZoneInfo('Asia/Taipei')).isoformat())
 if not str(body.get('change_note','')).strip():raise HTTPException(422,'請填本次更新／重啟說明')
 if action=='reopen' or status!=t['status']:
  from .case_problems import groups,DONE
  ps=groups(c,t);results=dict(details.get('problem_results',{}))
  for k,p in ps.items():
   current=results.get(k,{}).get('status',p['status'])
   if action=='reopen':current='改善中'
   elif status=='待驗證' and current=='改善中':current='待驗證'
   elif status=='改善完成':
    if current=='改善中':raise HTTPException(422,'仍有改善中的問題，請先送驗或分別處理')
    if current=='待驗證':current='已驗證改善'
   results[k]={**results.get(k,{}),'status':current,'result':details.get('result',''),'at':datetime.now(ZoneInfo('Asia/Taipei')).isoformat()}
  details['problem_results']=results
 event(c,t['hospital'],'案件重啟' if action=='reopen' else '追加改善／驗證紀錄',dict(before=t,after=dict(title=str(body.get('title',t['title'])).strip() or t['title'],status=status,body=details),note=body['change_note']),u['id'],cid=cid)
 c.execute('UPDATE tracking_cases SET title=%s,status=%s,body=%s,revision=revision+1,updated_by=%s,updated_at=now() WHERE id=%s',(str(body.get('title',t['title'])).strip() or t['title'],status,Jsonb(plain(details)),u['id'],cid));db.audit(c,u['id'],'tracking_case_update',t['hospital'],cid,dict(status=status));return dict(id=cid)
