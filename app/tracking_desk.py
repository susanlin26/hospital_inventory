"""Simple tracking presentation. Reuses existing observations, cases and immutable events."""
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal as D,ROUND_HALF_UP
from . import tracking
from .formatting import money,number_text

USAGE={'usage_up','usage_down','standard30_up','standard30_down'}
STOCK={'high_turnover','high_coverage','low_stock','idle','長期未耗用'}

def family(rule):return 'usage' if rule in USAGE else 'stock' if rule in STOCK else 'other'
def product_key(o):
 s=o['snapshot'];return (o['hospital'],s.get('code'))
def data_issue(o):return o['rule']=='data' or o['level']=='資料問題'
def pending(o):return bool(o.get('needs_reconfirm') or o.get('confirmation') and o.get('confirmed_fingerprint')!=o.get('fingerprint') or not o.get('confirmation') and (not o.get('case_id') or o.get('link_origin')=='auto'))
def state(o):
 if o.get('confirmation') and o.get('confirmed_fingerprint')!=o.get('fingerprint'):return '需重新確認'
 if o.get('confirmation'):return '合理原因已確認'
 if o.get('case_id'):return '已納入改善案'
 return '待確認'
def n(v):return format(D(str(v)).quantize(D('0.1'),rounding=ROUND_HALF_UP),',.1f') if v is not None else '無法計算'
def m(v):return money(D(str(v))) if v is not None else '無法計算'
def lead(s):
 r=s['rule'];f=s.get('facts') or {};cur=s.get('current');ref=s.get('reference');diff=s.get('difference');unit=s.get('unit') or '單位未提供';base='上月' if s.get('baseline')=='previous' else '去年同期'
 if r.startswith('usage_'):
  direction='增加' if r=='usage_up' else '減少';pct=f.get('pct')
  return f"本月{m(cur)}元，較{base}{direction}{m(abs(D(str(diff)))) if diff is not None else '無法計算'}元（{('+' if D(str(pct))>0 else '')+n(pct)+'%' if pct is not None else '基準無效'}）。"
 if r.startswith('standard30_'):
  return f"標準30日每床耗用{m(cur)}元／床／30日，{base}{m(ref)}元；差異{m(diff)}元／床／30日（{n(f.get('pct'))}%）。"
 if r=='high_turnover':return f'存貨週轉{n(cur)}天｜{s.get("severity","週轉偏慢")}；提醒門檻{n(ref)}天。'
 if r=='high_coverage':return f'月底庫存金額覆蓋{n(cur)}天，提醒門檻{n(ref)}天（依本月耗用金額計算）。'
 if r=='low_stock':return f'月底庫存推估可用{n(cur)}天，提醒門檻{n(ref)}天（依前三完整月耗用數量）。'
 if r=='idle':return f"本月耗用{m(f.get('used'))}元、{number_text(D(str(f.get('qty',0))),4)}{unit}，期末庫存{m(s.get('ending'))}元。{"｜長期未耗用" if s.get('long_term') else ""}"
 if r=='data':return '；'.join(f.get('reasons') or [f.get('reason') or s.get('formula') or '來源待核對'])
 if r=='長期未耗用':return f"已依完整歷史檢核長期未耗用，期末庫存{m(s.get('ending'))}元；{s.get('formula','')}"
 return f"{s.get('label',r)}：{m(cur) if s.get('value_unit')=='元' else n(cur)}{s.get('value_unit','')}；{s.get('formula','')}"

def compact(o):
 o=dict(o);s=dict(o['snapshot']);s.pop('source',None);o['snapshot']=s;o['family']=family(o['rule']);o['data_issue']=data_issue(o);o['needs_reconfirm']=bool(o.get('confirmation') and o.get('confirmed_fingerprint')!=o['fingerprint']);o['processing']=state(o);o['pending']=pending(o);o['reading']=lead(s)
 if isinstance(o.get('confirmation'),dict):o['confirmation']={k:v for k,v in o['confirmation'].items() if k!='snapshot'}
 return tracking.plain(o)

def observations(c,hs,p,base):
 return [compact(o) for o in c.execute("SELECT id,hospital,period,scope,identity,rule,basis,category,level,snapshot-'source' snapshot,active,fingerprint,confirmed_fingerprint,confirmation-'snapshot' confirmation,case_id,link_origin,revision FROM tracking_observations WHERE hospital=ANY(%s) AND period=%s AND scope='__all__' AND basis IN (%s,'fixed') AND (active OR confirmation IS NOT NULL OR case_id IS NOT NULL) ORDER BY hospital,category,id",(hs,p,base))]

def filtered(rows,kind='all',category='',processing='pending',q='',rule='',issues=False):
 q=q.strip().casefold();result=[]
 for o in rows:
  if o['rule'] in ('high_coverage','長期未耗用') and not rule:continue
  if rule=='long_idle':
   if o['rule']!='idle' or not o['snapshot'].get('long_term'):continue
  if data_issue(o)!=issues:continue
  if not issues and kind not in ('all','') and o['family']!=kind:continue
  if rule and rule!='long_idle' and o['rule']!=rule:continue
  if category and o['category']!=category:continue
  if processing=='pending' and not o['pending']:continue
  if processing not in ('pending','all','') and o['processing']!=processing:continue
  if q and q not in (o['hospital']+' '+str(o['snapshot'].get('code',''))+' '+str(o['snapshot'].get('name',''))).casefold():continue
  if not o['active'] and not o.get('needs_reconfirm') and processing=='pending':continue
  result.append(o)
 return result

def groups(rows):
 cats={}
 for o in rows:
  if o['level']!='品項':continue
  cats.setdefault(o['category'],[]).append(o)
 return [dict(category=cat,count=len({product_key(o) for o in items if o['pending']}),items=len({product_key(o) for o in items}),labels=list(dict.fromkeys(o['snapshot']['label'] for o in items)),ids=[o['id'] for o in items]) for cat,items in cats.items()]

def case_list(c,hs,closed=False):
 cases=c.execute('SELECT * FROM tracking_cases WHERE hospital=ANY(%s) AND (status=ANY(%s))=%s ORDER BY updated_at DESC,id DESC',(hs,list(tracking.CLOSED),closed)).fetchall()
 ids=[t['id'] for t in cases]
 by={row['case_id']:row for row in c.execute("SELECT case_id,array_agg(DISTINCT rule) rules,count(*) n,count(DISTINCT(hospital,snapshot->>'code',snapshot->>'name',snapshot->>'unit')) FILTER(WHERE snapshot->>'code'<>'ALL') items FROM tracking_observations WHERE hospital=ANY(%s) AND case_id=ANY(%s) GROUP BY case_id",(hs,ids))}
 today=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat();out=[]
 for t in cases:
  if (t['status'] in tracking.CLOSED)!=closed:continue
  agg=by.get(t['id'],{});fs={family(rule) for rule in agg.get('rules',[])};oldrule=(t['body'].get('rule') or '')
  if not fs:fs={'stock'} if any(x in oldrule for x in ('庫存','週轉','耗用但')) else {'usage'} if '耗用' in oldrule else {'other'}
  problem='耗用及存貨' if {'usage','stock'}<=fs else '耗用' if 'usage' in fs else '存貨' if 'stock' in fs else '其他提醒／舊案待分類'
  out.append(dict(id=t['id'],hospital=t['hospital'],start_period=t['start_period'],title=t['title'],status=t['status'],revision=t['revision'],legacy_id=t['legacy_id'],problem_type=problem,families=list(fs),item_count=agg.get('items',None if t['legacy_id'] else 0),global_only=bool(agg and not agg['items'] and all(rule.startswith('standard30_') for rule in agg['rules'])),responsible_unit=t['body'].get('responsible_unit') or t['body'].get('owner',''),due_date=t['body'].get('due_date',''),progress=t['body'].get('progress',''),result=t['body'].get('result',''),completed_date=t['body'].get('completed_date',''),legacy_completed_date=(t['body'].get('legacy_record') or {}).get('details',{}).get('completed_date',''),legacy_completed_result=(t['body'].get('legacy_record') or {}).get('details',{}).get('result',''),verified=bool(t['body'].get('approved_by') or t['legacy_id'] and (t['body'].get('legacy_record') or {}).get('approved')),overdue=t['status'] not in tracking.CLOSED and bool(t['body'].get('due_date')) and t['body']['due_date']<today))
 from .case_problems import summary
 for row,t in zip(out,cases):row.update(summary(c,t))
 return tracking.plain(out)

def filter_cases(rows,kind='all',unit='',status='',overdue=False,q=''):
 return [t for t in rows if (kind in ('all','') or kind in t['families'] or kind=='both' and {'usage','stock'}<=set(t['families'])) and (not unit or unit.casefold() in t['responsible_unit'].casefold()) and (not status or t['status']==status) and (not overdue or t['overdue']) and (not q or q.casefold() in (t['title']+' '+t['hospital']+' '+t['responsible_unit']).casefold())]

def valid_dates(start,end):
 today=datetime.now(ZoneInfo('Asia/Taipei')).date();a=date.fromisoformat(start) if start else today-timedelta(days=89);b=date.fromisoformat(end) if end else today
 if a>b:raise ValueError('起始日期不可晚於結束日期')
 return a.isoformat(),b.isoformat()

def records(c,hs,kind,start,end,q=''):
 start,end=valid_dates(start,end);rows=[]
 if kind=='reasonable':
  # Read only a summary; original per-alert snapshots stay lazy.
  for b in c.execute("SELECT b.id,b.hospital,b.created_at,b.operator,b.body->>'cause' cause,b.body->>'cause_category' cause_category,b.body->'ids' ids,u.name operator_name FROM tracking_batches b LEFT JOIN users u ON u.id=b.operator WHERE b.hospital=ANY(%s) AND (b.created_at AT TIME ZONE 'Asia/Taipei')::date BETWEEN %s::date AND %s::date ORDER BY b.created_at DESC,b.id DESC",(hs,start,end)):
   obs=c.execute("SELECT hospital,snapshot->>'code' code,snapshot->>'name' name,snapshot->>'unit' unit,confirmation->>'batch_id' current_batch,confirmed_fingerprint<>fingerprint needs_reconfirm FROM tracking_observations WHERE id=ANY(%s)",(b['ids'],)).fetchall()
   current=sum(str(b['id'])==o['current_batch'] for o in obs);affected=sum(str(b['id'])==o['current_batch'] and bool(o['needs_reconfirm']) for o in obs)
   rows.append(dict(id=b['id'],hospital=b['hospital'],date=b['created_at'].astimezone(ZoneInfo('Asia/Taipei')).isoformat(),summary=b['cause'] or '',cause_category=b['cause_category'] or '',item_count=len({(o['hospital'],o['code'],o['name'],o['unit']) for o in obs if o['code']!='ALL'}),alert_count=len(b['ids']),operator=b['operator_name'] or '歷史確認人未記錄',state='全部已撤回或更正' if not current else '部分已撤回或更正' if current<len(b['ids']) else ('需重新確認'+str(affected)+'筆' if affected else '已確認')))
 else:
  allcases=case_list(c,hs,closed=True)+case_list(c,hs)
  completed={}
  if kind=='completed':
   # Completion records are historical facts, even after a case is reopened or edited.
   completed={e['case_id']:e['body']['after'] for e in c.execute("SELECT DISTINCT ON(case_id) case_id,body FROM tracking_events WHERE hospital=ANY(%s) AND body#>>'{after,status}'='改善完成' AND body#>>'{after,body,approved_by}' IS NOT NULL AND body#>>'{after,body,completed_date}' BETWEEN %s AND %s ORDER BY case_id,id DESC",(hs,start,end))}
  for t in allcases:
   if kind=='completed':
    saved=completed.get(t['id']);historical=saved['body'] if saved else {}
    if saved:t={**t,'title':saved.get('title') or t['title'],'result':historical.get('result',''),'completed_date':historical.get('completed_date',''),'responsible_unit':historical.get('responsible_unit',''),'verified':True}
    elif t['legacy_id'] and t['verified'] and t['legacy_completed_date']:t={**t,'result':t['legacy_completed_result'],'completed_date':t['legacy_completed_date']}
    else:continue
   if kind=='legacy' and not(t['legacy_id'] or t['status']=='舊版結案待分類' or t['status']=='改善完成' and not t['verified']):continue
   when=t.get('completed_date') or ''
   if when and not start<=when[:10]<=end:continue
   if kind=='completed' and not when:continue
   rows.append({**t,'date':when or '處理日期未記錄（舊案）','summary':t['result'] or t['title']})
 if kind=='reasonable':
  for e in c.execute("SELECT e.*,u.name operator_name FROM tracking_events e LEFT JOIN users u ON u.id=e.operator WHERE e.hospital=ANY(%s) AND e.action='案件問題整批處理' AND e.body->>'action'='reasonable' AND (e.created_at AT TIME ZONE 'Asia/Taipei')::date BETWEEN %s::date AND %s::date ORDER BY e.id DESC",(hs,start,end)):
   changes=e['body'].get('changes',[]);saved=e['body']['after']['body'].get('problem_results',{});keys=[v['key'] for v in changes];t=c.execute('SELECT * FROM tracking_cases WHERE id=%s',(e['case_id'],)).fetchone()
   from .case_problems import groups
   ps=groups(c,t);count=len({(ps[k]['code'],ps[k]['unit']) for k in keys if k in ps and ps[k]['code']!='ALL'})
   rows.append(dict(id='problem-'+str(e['id']),hospital=e['hospital'],date=e['created_at'].isoformat(),summary=e['body']['note'],cause_category='案件問題合理原因',item_count=count,alert_count=len(keys),operator=e['operator_name'] or '未記錄',state='已確認合理原因（追加紀錄）'))
 if q:rows=[b for b in rows if q.casefold() in ' '.join(str(b.get(k,'')) for k in ('summary','title','hospital','operator','responsible_unit','cause_category')).casefold()]
 return rows,start,end


def audit(reports,base):
 out=[]
 for d in reports:
  generated=tracking.observations(d,base);ups=[o for o in generated if o['rule']=='usage_up'];ok=sum(o['snapshot']['facts'].get('pct') is not None and o['snapshot']['facts'].get('valid') and o['snapshot']['facts'].get('zero_consistent') for o in ups)
  up=sum(o['active'] for o in ups);down=sum(o['active'] for o in generated if o['rule']=='usage_down');problems=list(dict.fromkeys(reason for o in generated if o['rule']=='data' and o['active'] for reason in (o['snapshot']['facts'].get('reasons') or [o['snapshot']['facts'].get('reason') or o['snapshot']['formula']]) if reason))
  out.append(dict(hospital=d['hospital'],eligible_items=ok,increase=up,decrease=down,issues=problems,limitations=[x for x in problems if '不判定低庫存' not in x],message=('本月無符合門檻的耗用提醒' if ok and not up and not down else f'耗用增加{up}筆、耗用下降{down}筆' if up or down else '耗用提醒無法完整判讀：'+('；'.join(problems[:2]) or '缺少有效月報或比較期資料')),thresholds=list({(o['category'],o['snapshot']['facts']['change_pct'],o['snapshot']['facts']['change_amount']):dict(category=o['category'],percent=o['snapshot']['facts']['change_pct'],amount=o['snapshot']['facts']['change_amount']) for o in ups}.values()),threshold_pct=d['rules']['change_pct'],threshold_amount=d['rules']['change_amount'],baseline_periods=d['baseline']))
 return tracking.plain(out)
