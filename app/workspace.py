from .performance import timed
"""管理閱讀共用資料層。保留來源精度；所有頁面與報表共用同一結果。"""
import calendar
from datetime import date
from decimal import Decimal as D
from . import engine
from .inpatient import pooled_daily,period_turnover


def due_metrics(reviews,p):
 end=date(*map(int,p.split('-')),calendar.monthrange(*map(int,p.split('-')))[1])
 def dt(v):
  try:return date.fromisoformat(str(v)[:10]) if v else None
  except ValueError:return None
 reasonable=[r for r in reviews if r['status']=='已結案' and (r.get('details') or {}).get('outcome')=='reasonable' and (dt((r.get('details') or {}).get('completed_date')) or dt(r.get('updated_at'))) and (dt((r.get('details') or {}).get('completed_date')) or dt(r.get('updated_at')))<=end]
 eligible=[r for r in reviews if dt(r.get('due_date')) and dt(r['due_date'])<=end and r not in reasonable]
 def improved(r):
  x=r.get('details') or {};completed=dt(x.get('completed_date'))
  return r['status']=='已結案' and r.get('approved') and r.get('confirmed') and x.get('outcome')=='improved' and x.get('result') and completed and completed<=end
 actual=[r for r in eligible if improved(r)]
 overdue=[r for r in eligible if not improved(r)]
 return dict(due_cases=len(eligible),due_improved_cases=len(actual),due_completion_rate=D(len(actual))*100/len(eligible) if eligible else None,overdue_cases=len(overdue),reasonable_closed_count=len(reasonable),due_case_ids=[r['id'] for r in eligible],overdue_case_ids=[r['id'] for r in overdue],due_definition=f'累計至{end}：立案月份不晚於分析月、期限不晚於月底，排除截至月底已合理原因結案的案件；同批案件中截至月底已覆核且改善完成者為分子。未填期限另列，不混入完成率。',undated_cases=sum(not r.get('due_date') and r['status']!='已結案' for r in reviews))


def monthly_bed_pool(entries):
 """按已登錄月平均床數直接相除；跨院不平均比率，缺漏不補零。"""
 complete=bool(entries) and all(x.get('used') is not None and x.get('total_beds') is not None and x['total_beds']>0 for x in entries)
 beds=sum((x['total_beds'] for x in entries),D(0)) if complete else None
 used=sum((x['used'] for x in entries),D(0)) if complete else None
 return dict(total_beds=beds,monthly_bed_consumption=used/beds*30 if complete else None,bed_month_status='按同月已登錄平均床數合計計算；非核定床數，床別範圍見各院說明。' if complete else '；'.join(x.get('bed_month_status','缺少同院同月耗用或床數') for x in entries if x.get('used') is None or not x.get('total_beds')) or '缺少同院同月耗用或床數')


@timed('workspace')
def enrich(c,d):
 h,p=d['hospital'],d['period'];t=d['total'];base=d['baseline'];rows=d['source_rows'];valid=[x for x in rows if x['valid']]
 from .inpatient import fetch_census
 def bed_point(point,period):
  bc=fetch_census(c,h,period,'hospital');days=point.get('patient_days');good=point.get('standard30_per_bed') is not None
  point.update(total_beds=days if good else None,monthly_bed_consumption=point.get('standard30_per_bed'),bed_month_status=h+' '+period+'；'+point.get('daily_status',bc['status']))
 bed_point(t,p)
 for point in d['trend']:bed_point(point,point['period'])
 history={x['period']:x for x in d['trend']}
 bm=monthly_bed_pool([history.get(bp,{'bed_month_status':h+' '+bp+' 缺少月報或床數'}) for bp in base])
 t['baseline_monthly_bed_consumption']=bm['monthly_bed_consumption'];t['monthly_bed_change']=engine.delta(t['monthly_bed_consumption'],bm['monthly_bed_consumption']);t['baseline_bed_month_status']=bm['bed_month_status']
 def baseline_metric(key,periods):
  pts=[history.get(bp,{}) for bp in periods]
  return sum((x[key] for x in pts),D(0))/len(periods) if all(x.get(key) is not None for x in pts) else None
 t['baseline_used']=baseline_metric('used',base)
 t['baseline_ending']=baseline_metric('ending',base)
 previous=history.get(engine.previous(p),{});t['ending_previous']=previous.get('ending');t['ending_change']=engine.delta(t['ending'],previous.get('ending'))
 bt=period_turnover([history.get(bp,{}) for bp in base]);t['baseline_days']=bt['days'];t['days_change']=engine.delta(t['days'],bt['days'])
 t['baseline_patient_day']=d['daily_comparison']['baseline']['per_patient_day'];t['daily_selected_change']=d['daily_comparison']['change']
 prior3=d['daily_baseline3']['periods'];t['mean3_used']=baseline_metric('used',prior3);t['mean3_change']=engine.delta(t['used'],t['mean3_used']);t['mean3_ending']=baseline_metric('ending',prior3)
 follow=c.execute('SELECT * FROM reviews WHERE hospital=%s AND period<=%s AND (department=%s OR %s) ORDER BY period DESC,id',(h,p,d.get('selected_department') or '',d.get('all_departments',False))).fetchall()
 if d.get('selected_category'):
  codes={x['code'] for x in d['items']};cat=d['selected_category'];follow=[r for r in follow if r['code'] in codes or r['code']==cat or (r.get('details') or {}).get('category')==cat]
 d['case_history']=follow;t.update(due_metrics(follow,p))
 # Index once; preserve all duplicate rows and their original ordering.
 history_by_key={}
 for row in valid:history_by_key.setdefault((row['code'],row['name'],row['unit']),[]).append(row)
 # 原始比較的單位、名稱必須一致；負量顯示異常，零量依指定歸列方式呈現。
 for x in d['items']:
  matches=[r for r in history_by_key.get((x['code'],x['name'],x['unit']),[]) if r['period'] in base]
  f={'reason':'比較月份或同品項資料不足：'+','.join(bp for bp in base if not any(r['period']==bp for r in matches))}
  if x['qty']<0:f={'reason':'異常：本月或基準耗用量<0','anomaly':True}
  elif len(matches)==len(base):
   bq=sum((engine.calc(r)['qty'] for r in matches),D(0))/len(base);bu=sum((engine.calc(r)['used'] for r in matches),D(0))/len(base)
   f=engine.decompose(x['qty'],x['used'],bq,bu)
  x['selected_factor']=dict(f,has_adjustments=any(D(str(r[k]))!=0 for r in [x,*matches] for k in ('adj_q','adj_a','other_q','other_a')),periods=base,formula='數量影響=(本月量−基準月均量)×基準耗用單位成本；成本影響=本月量×(本月耗用單位成本−基準耗用單位成本)；成本影響亦以總差異−數量影響核對。任一期間耗用量為0時，依指定口徑將總差異全列數量影響、單位成本影響列0，不推算零量期間單位成本；此為歸列方式，不代表單位成本沒有變動。兩項相加=耗用總差異。採購單價不代入此式。')
  x['per_patient_day_qty']=x['qty']/t['patient_days'] if t['per_patient_day'] is not None else None
  x['usage_history']=[]
  for r in history_by_key.get((x['code'],x['name'],x['unit']),[]):
   m=engine.calc(r);pt=history.get(r['period'],{});x['usage_history'].append(dict(period=r['period'],used=m['used'],qty=m['qty'],ending=m['ending'],incoming=D(str(r['in_a']))*engine.TAX,per_patient_day_qty=m['qty']/pt['patient_days'] if pt.get('per_patient_day') is not None else None))
  x['related_cases']=[r for r in follow if r['code']==x['code']]
  x['risk_state']=next((r['state'] for r in d['risk_matrix'] if r['code']==x['code']),'一般／資料不足')
  x['low_days_threshold']=__import__('app.analytics',fromlist=['rule_for']).rule_for(d['rules'],x['category'])['low_days']
 for cat in d['categories']:
  cat['baseline_used']=cat['used']-cat['change']['amount'] if cat['change']['amount'] is not None else None
 # 待確認耗用異常僅計達門檻的品項增加；分類、全院與人日提醒仍呈現，不再加入金額。
 closed={(r['code'],r['rule']) for r in d['reviews'] if r['status']=='已結案'}
 unique={f['code']:f for f in d['findings'] if f['level']=='品項' and f['rule']=='重大耗用差異' and f['value']>0 and (f['code'],f['rule']) not in closed}
 d['pending_consumption']=list(unique.values());t['consumption_anomaly_impact']=sum((f['value'] for f in unique.values()),D(0));t['pending_consumption_count']=len(unique)
 t['consumption_impact_definition']='僅合計達百分比及金額雙門檻、尚未結案的品項耗用增加，同品項只計一次；分類、整體、人日提醒不重複加計。屬待確認差異，不代表浪費或可節省金額。'
 missing=[]
 for bp in dict.fromkeys([p,*base,*prior3]):
  point=history.get(bp)
  from .inpatient import fetch_census
  bc=fetch_census(c,h,bp,d.get('selected_department') or 'hospital')
  has_source=bool(c.execute('SELECT 1 FROM batches WHERE hospital=%s AND period=%s AND active AND (department=%s OR department=%s OR %s::text IS NULL) LIMIT 1',(h,bp,d.get('selected_department') or '', '',d.get('selected_department'))).fetchone())
  missing.append(dict(hospital=h,period=bp,report=has_source,beds=bool(bc.get('patient_days_raw') is not None),role='本月' if bp==p else '比較基準' if bp in base else '前三月參考',reason=point.get('daily_status') if point else '來源月報存在，但選定科別／分類缺少有效明細，不視為零' if has_source else '缺少已啟用月報；床數需核對同院同月同科別'))
 d['data_status']=missing
 return d


def overview(reports,p):
 """部分涵蓋可呈現本月；所有增減一律使用同一批可比醫院。"""
 from .management_analysis import aggregate
 covered=[d for d in reports if d['total']['used'] is not None];t=aggregate(covered,p)
 t.update(due_metrics([r for d in reports for r in d['case_history']],p))
 t.update(monthly_bed_pool([d['total'] for d in reports]))
 bedbase=[]
 for bp in reports[0]['baseline'] if reports else []:
  bedbase.append(monthly_bed_pool([next((x for x in d['trend'] if x['period']==bp),{'bed_month_status':d['hospital']+' '+bp+' 缺少月報或床數'}) for d in reports]))
 # 每期合併先加總，再依同一組醫院求基準；缺少任何院月則不提供比較。
 if bedbase and all(x['monthly_bed_consumption'] is not None for x in bedbase):
  t['baseline_monthly_bed_consumption']=sum((x['monthly_bed_consumption']*x['total_beds'] for x in bedbase),D(0))/sum((x['total_beds'] for x in bedbase),D(0))
 else:t['baseline_monthly_bed_consumption']=None
 t['monthly_bed_change']=engine.delta(t['monthly_bed_consumption'],t['baseline_monthly_bed_consumption']);t['baseline_bed_month_status']='；'.join(x['bed_month_status'] for x in bedbase)

 t['high_low_inventory_amount']=sum((d['total']['high_low_inventory_amount'] for d in covered),D(0));t['pending_consumption_count']=sum(d['total']['pending_consumption_count'] for d in covered)
 pair=[d for d in covered if d['total']['baseline_used'] is not None]
 comparable_current=sum((d['total']['used'] for d in pair),D(0)) if pair else None
 base=sum((d['total']['baseline_used'] for d in pair),D(0)) if pair else None
 t.update(baseline_used=base,comparable_current_used=comparable_current,change=engine.delta(comparable_current,base),comparison_hospitals=[d['hospital'] for d in pair])
 daypair=[d for d in pair if d['total']['comparison_eligible'] and d['daily_comparison']['baseline']['complete'] and d['daily_comparison']['baseline']['care_scope']==d['total']['care_scope']]
 if daypair and len({d['total']['care_scope'] for d in daypair})==1:
  curr=pooled_daily([d['total'] for d in daypair]);bpoints=[]
  for bp in daypair[0]['baseline']:
   bpoints.append(pooled_daily([next((x for x in d['trend'] if x['period']==bp),{}) for d in daypair]))
  b=pooled_daily(bpoints,across_months=True);t['baseline_patient_day']=b['per_patient_day'];t['daily_selected_change']=engine.delta(curr['per_patient_day'],b['per_patient_day']);t['comparable_patient_day']=curr['per_patient_day']
 else:t.update(baseline_patient_day=None,daily_selected_change=engine.delta(None,None),comparable_patient_day=None)
 t['daily_comparison_hospitals']=[d['hospital'] for d in daypair]
 prevpair=[d for d in covered if d['total']['ending_previous'] is not None];t['ending_previous']=sum((d['total']['ending_previous'] for d in prevpair),D(0)) if prevpair else None
 t['ending_change']=engine.delta(sum((d['total']['ending'] for d in prevpair),D(0)) if prevpair else None,t['ending_previous']);t['ending_comparison_hospitals']=[d['hospital'] for d in prevpair]
 stockpair=[d for d in covered if d['total']['baseline_days'] is not None];basepoints=[]
 for bp in reports[0]['baseline'] if reports else []:
  pts=[next((x for x in d['trend'] if x['period']==bp),{}) for d in stockpair]
  if pts and all(x.get('used') is not None for x in pts):basepoints.append(dict(used=sum((x['used'] for x in pts),D(0)),average=sum((x['average'] for x in pts),D(0)),calendar_days=calendar.monthrange(*map(int,bp.split('-')))[1]))
 bt=period_turnover(basepoints);ct=aggregate(stockpair,p);t['baseline_days']=bt['days'];t['days_change']=engine.delta(ct['days'],bt['days']);t['days_comparison_hospitals']=[d['hospital'] for d in stockpair]
 periods=[];cursor=p
 for _ in range(24):periods.append(cursor);cursor=engine.previous(cursor)
 trends=[]
 for bp in reversed(periods):
  pts=[next((x for x in d['trend'] if x['period']==bp),{}) for d in covered];complete=bool(pts) and all(x.get('used') is not None for x in pts)
  point=dict(period=bp,**pooled_daily(pts));point.update({k:sum((x[k] for x in pts),D(0)) if complete else None for k in ('used','ending','average')})
  point.update(monthly_bed_pool([next((x for x in d['trend'] if x['period']==bp),{'bed_month_status':d['hospital']+' '+bp+' 缺少月報或床數'}) for d in reports]))
  point['days']=D(calendar.monthrange(*map(int,bp.split('-')))[1])*point['average']/point['used'] if complete and point['used']>0 and point['average']>0 else None;trends.append(point)
 names=sorted({cat['category'] for d in covered for cat in d['categories']});cats=[]
 for name in names:
  entries=[(d,next((x for x in d['categories'] if x['category']==name),None)) for d in covered]
  items=[x for _,x in entries if x];amount=sum((x['used'] for x in items),D(0));ending=sum((x['ending'] for x in items),D(0))
  paired=[x for _,x in entries if x and x.get('baseline_used') is not None];bc=sum((x['baseline_used'] for x in paired),D(0)) if len(paired)==len(entries) else None
  cats.append(dict(category=name,used=amount,ending=ending,monthly_bed_consumption=amount/t['total_beds'] if t.get('total_beds') and t['total_beds']>0 else None,usage_share=amount/t['used']*100 if t['used'] else None,baseline_used=bc,change=engine.delta(amount,bc),per_patient_day=amount/t['patient_days'] if t['complete'] else None))
 status=[x for d in reports for x in d['data_status']]
 summary=[f"{p}本月涵蓋{len(covered)}/{len(reports)}院；可比耗用增減僅含：{','.join(t['comparison_hospitals']) or '無'}。",t['consumption_impact_definition'] if 'consumption_impact_definition' in t else '待確認差異不等於浪費或節省。',t['due_definition'],'優先確認高影響耗用差異、庫存資金與逾期案件；未確認原因維持待確認。']
 from .formatting import money
 summary += [f'期末庫存{money(t["ending"])}元；高庫存低耗用{money(t["high_low_inventory_amount"])}元。']
 summary += [f'分類{x["category"]}差異{money(x["change"]["amount"])}元；原因待確認。' for x in cats[:3]]
 category_totals={}
 for key in ('used','baseline_used','per_patient_day'):
  category_totals[key]=sum((x[key] for x in cats),D(0)) if cats and all(x.get(key) is not None for x in cats) else None
 category_totals['difference']=sum((x['change']['amount'] for x in cats),D(0)) if cats and all(x['change']['amount'] is not None for x in cats) else None
 return dict(category_totals=category_totals,period=p,total=t,hospitals=reports,covered_hospitals=[d['hospital'] for d in covered],requested_hospitals=[d['hospital'] for d in reports],categories=cats,trend=trends,summary=summary,data_status=status,note=t['note'],scope_note='各院照護範圍須一致才比較人日；本月金額為實際涵蓋院別，增減另標示同範圍院別。')
