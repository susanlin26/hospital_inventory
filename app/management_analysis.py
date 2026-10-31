from .performance import timed
"""住院人日、管理異常及彙總；既有耗用與存貨計價公式保持不變。"""
import calendar
from decimal import Decimal as D
from . import engine
from .inpatient import fetch_census,daily_metrics,pooled_daily,review_kpis,period_turnover,resolve_scope,row_department,census
from .analytics import money,number_text,rule_for


@timed('bed_management')
def enhance(c,d,rule_selector):
 h,p=d['hospital'],d['period'];rules=d['rules'];allrows=d['source_rows']
 current=[x for x in allrows if x['period']==p and x['valid']];bed_scope=d.get('selected_department') or 'hospital';cens=fetch_census(c,h,p,bed_scope)
 if current and all(row_department(x)=='RCW' for x in current):cens=fetch_census(c,h,p,'RCW')
 scope,reason=resolve_scope(current,cens);dm=daily_metrics(d['total']['used'],cens,scope,reason);d['census']=cens;d['total'].update(dm)
 d['total']['legacy_rcw_per_bed']=d['total']['per_bed'];d['total']['per_bed']=dm['monthly_per_bed'];d['total']['bed_reason']=dm['daily_status']
 d['legacy_bed_comparison']={**d['bed_comparison'],'note':'舊RCW分母參考，不作管理績效比較'}
 d['bed_comparison']={'current':dm['average_beds'],'baseline':None,'change':engine.delta(dm['average_beds'],None),'per_bed_baseline':None,'per_bed_change':engine.delta(dm['monthly_per_bed'],None),'note':'改用自動對應範圍；人日比較請見daily_baseline3'}
 trend={}
 for point in d['trend']:
  rp=point['period'];rs=[x for x in allrows if x['period']==rp and x['valid']];rc=fetch_census(c,h,rp,'RCW' if rs and all(row_department(x)=='RCW' for x in rs) else bed_scope);s,why=resolve_scope(rs,rc)
  point.update(daily_metrics(point['used'],rc,s,why));point['per_bed']=point['monthly_per_bed'];trend[rp]=point
 d['window_totals']={}
 for count in (6,12):
  periods=[p]
  for _ in range(count-1):periods.append(engine.previous(periods[-1]))
  d['window_totals'][str(count)]={**period_turnover([trend.get(bp,{}) for bp in periods]),'periods':periods}
 expected=[engine.previous(p)]
 for _ in range(2):expected.append(engine.previous(expected[-1]))
 prior=[trend.get(bp,{}) for bp in expected];pooled=pooled_daily(prior,across_months=True);d['daily_baseline3']=dict(pooled,periods=expected,missing_periods=[bp for bp,point in zip(expected,prior) if point.get('per_patient_day') is None])
 base=pooled['per_patient_day'];ch=engine.delta(dm['per_patient_day'],base);d['total']['daily_change3']=ch
 expected_used=base*dm['patient_days'] if base is not None and dm['per_patient_day'] is not None and pooled['care_scope']==scope else None
 impact=d['total']['used']-expected_used if expected_used is not None else None
 selected=pooled_daily([trend.get(bp,{}) for bp in d['baseline']],across_months=True)
 selected_change=engine.delta(dm['per_patient_day'],selected['per_patient_day'])
 if selected['care_scope']!=scope:selected_change={'amount':None,'pct':None,'reason':'選定比較期照護範圍不一致'}
 d['daily_comparison']={'periods':d['baseline'],'baseline':selected,'change':selected_change}
 d['total']['daily_expected_used']=expected_used;d['total']['daily_impact']=impact
 if base is not None and pooled['care_scope']!=scope:ch.update(amount=None,pct=None,reason='當月與前三月照護範圍不同')
 def add(code,name,rule,value,impact=None,pct=None,basis='',level='品項'):
  d['findings'].append(dict(level=level,code=code,name=name,rule=rule,severity='高' if rule=='每住院人日耗用異常' else '中',value=value,impact_amount=impact,pct=pct,basis=basis))
 rr=rule_for(rules)
 if dm['comparison_eligible'] and ch['pct'] is not None and ch['pct']>=D(rr['change_pct']) and impact is not None and impact>=D(rr['change_amount']):add('ALL','全院','每住院人日耗用異常',ch['amount'],impact,ch['pct'],','.join(expected)+'；前三月合計耗用÷各月住院人日合計',level='整體')
 for cat in d['categories']:
  cat['usage_share']=cat['used']/d['total']['used']*100 if d['total']['used'] and d['total']['used']>0 else None
  cat['per_patient_day']=cat['used']/dm['patient_days'] if dm['per_patient_day'] is not None else None
  cat['standard30_per_bed']=cat['per_patient_day']*30 if cat['per_patient_day'] is not None else None
 history_by_key={}
 for row in allrows:history_by_key.setdefault((row['code'],row['name'],row['unit']),[]).append(row)
 for x in d['items']:
  item_history=history_by_key.get((x['code'],x['name'],x['unit']),[])
  x['per_patient_day']=x['used']/dm['patient_days'] if dm['per_patient_day'] is not None else None
  x['quantity_history']=[{'period':r['period'],'qty':engine.calc(r)['qty']} for r in item_history if r['valid']]
  x['purchase_history']=[{'period':r['period'],'purchase':engine.calc(r)['purchase']} for r in item_history]
  matches=[r for r in item_history if r['period'] in expected and r['valid']]
  x['low_stock_days']=None;x['low_stock_reason']='前三完整月同品項歷史不足或耗用無效，不判定低庫存風險'
  if len(matches)==3:
   quantities=[engine.calc(r)['qty'] for r in matches];days=sum(calendar.monthrange(*map(int,bp.split('-')))[1] for bp in expected)
   if all(q>=0 for q in quantities) and sum(quantities)>0 and D(x['end_q'])>=0:
    cover=D(x['end_q'])/(sum(quantities)/days);x['low_stock_days']=cover;x['low_stock_reason']='依前三完整月平均每日耗用量推估，不含採購交期與安全庫存承諾'
    if cover<D(rule_for(rules,x['category'])['low_days']):add(x['code'],x['name'],'低庫存風險',cover,x['ending'],basis=','.join(expected)+'；'+x['low_stock_reason'])
 from .inventory_rules import flags
 for x in d['items']:x['inventory_flags']=flags(x,d['rules'])
 d['risk_matrix']=[{'code':x['code'],'name':x['name'],'ending':x['ending'],'days':x['days'],'coverage':x['coverage'],'low_stock_days':x['low_stock_days'],'state':'資料問題' if x['used']<0 or x['qty']<0 or x['opening']<0 or x['ending']<0 or ((x['used']==0)!=(x['qty']==0)) else '無耗用但有庫存' if x['used']==0 and x['qty']==0 and x['ending']>0 else '高庫存低週轉' if x['days'] is not None and x['days']>D(rule_for(rules,x['category'])['high_days']) else '低庫存風險' if x['low_stock_days'] is not None and x['low_stock_days']<D(rule_for(rules,x['category'])['low_days']) else '一般／資料不足'} for x in d['items']]
 d['total']['high_low_inventory_amount']=sum((x['ending'] for x in d['risk_matrix'] if x['state'] in ('高庫存低週轉','無耗用但有庫存')),D(0))
 d['total']['high_low_inventory_definition']='與風險矩陣同範圍：高庫存低週轉或本月無耗用但仍有庫存的期末金額，不重複計品項；不等同180天長期未耗用。'
 d['risk_matrix'].sort(key=lambda x:(x['state'] not in ('高庫存低週轉','無耗用但有庫存'),-x['ending']))
 consumption=[f for f in d['findings'] if '耗用差異' in f['rule'] and f['value']>0]
 levels=[sum((f['value'] for f in consumption if f['level']==lev),D(0)) for lev in ('品項','分類','整體')]
 d['total']['consumption_anomaly_impact']=max([D(0),*levels,impact if any(f['rule']=='每住院人日耗用異常' for f in d['findings']) else D(0)])
 d['total']['consumption_impact_definition']='正向耗用異常以品項、分類、整體各層加總及人日超額估算取最大值，層級不重複加總；屬待查影響，不是已確認損失。'
 reviews={(x['code'],x['rule']):x for x in d['reviews']}
 d['open_findings']=[f for f in d['findings'] if (reviews.get((f['code'],f['rule'])) or {}).get('status')!='已結案']
 d['total']['unresolved_count']=len(d['open_findings']);d['total'].update(review_kpis(d['reviews']))
 d['total']['anomaly_items']=len({f['code'] for f in d['findings'] if f['level']=='品項'})
 d['findings'].sort(key=lambda f:(f['severity']!='高',-abs(f.get('impact_amount') or 0),-abs(f.get('pct') or 0)))
 summary=f"{h} {p}當月住院人日{number_text(dm['patient_days'],0)}人日（直接提供住院人日數）；{dm['daily_label']}{money(dm['per_patient_day'])}元；標準30日每床耗用{money(dm['standard30_per_bed'])}元。前三完整月基準{money(base)}元，偏差{number_text(ch['pct'])}%。{dm['daily_status']}。期末存貨{money(d['total']['ending'])}元，週轉{number_text(d['total']['days'])}天；待處理{len(d['open_findings'])}件。原因未確認者維持待確認。"
 d['summary'].insert(0,summary)
 priorities=sorted(d['categories'],key=lambda x:abs(x['change']['amount'] or 0),reverse=True)[:3]
 d['summary'].append('主要分類差異：'+'；'.join(f"{x['category']}：{money(x['change']['amount'])}元" for x in priorities)+'。優先核對高影響耗用異常及高庫存案件，確認原因後記錄改善結果。')
 for s in d['summaries']:
  s['formula']='耗用=(銷貨−調整−其他異動)×1.05；住院人日=直接提供的同月實際住院人日數；每人日耗用=同範圍耗用÷住院人日'
  if s['level']=='整體':s['text']=summary+' '+s['text']
  elif s['level']=='分類':
   cat=next(x for x in d['categories'] if x['category']==s['code']);s['text']+=f"耗用占比{number_text(cat['usage_share'])}%；每住院人日耗用{money(cat['per_patient_day'])}元（{dm['care_scope_name']}）。"
 d['notes']+=['前三月資料未齊：'+('、'.join(d['daily_baseline3']['missing_periods']) or '無缺月')+'；'+pooled['reason']]
 d['notes']+=[dm['scope_note'],dm['daily_status'],cens['note'],d['total']['consumption_impact_definition'],d['total']['definition']]
 d['scope_availability']=[{'hospital':h,'period':x['period'],'scope':x['care_scope'],'calculable':x['per_patient_day'] is not None,'comparison_eligible':x['comparison_eligible'],'reason':x['daily_status']} for x in d['trend']]
 d['bed_breakdown']=[]
 for department in sorted({row_department(x) for x in current if row_department(x) not in (None,'hospital','hospital_reference','mixed')}):
  subset=[x for x in current if row_department(x)==department];bc=census([x for x in cens['records'] if x['department']==department],p)
  bs,why=resolve_scope(subset,bc);value=sum((engine.calc(x)['used'] for x in subset),D(0));d['bed_breakdown'].append({'department':department,'used':value,**daily_metrics(value,bc,bs,why)})
 d['monthly_summary']={'hospital':h,'period':p,'text':summary,'basis3':pooled,'care_scope':scope}
 return d


def aggregate(reports,p):
 """同月份按合計成本重新計算週轉，絕不平均比率。"""
 complete=bool(reports) and all(d['total']['used'] is not None for d in reports)
 total={key:sum((d['total'][key] for d in reports),D(0)) if complete else None for key in ('used','opening','ending','average')}
 ratio=total['used']/total['average'] if complete and total['average']>0 and total['used']>0 else None
 total['turnover']=ratio;total['days']=D(calendar.monthrange(*map(int,p.split('-')))[1])/ratio if ratio else None
 total.update(pooled_daily([d['total'] for d in reports]));total['used']=sum((d['total']['used'] for d in reports),D(0)) if complete else None
 total['consumption_anomaly_impact']=sum((d['total']['consumption_anomaly_impact'] for d in reports),D(0)) if complete else None
 total['unresolved_count']=sum(d['total']['unresolved_count'] for d in reports)
 total.update(review_kpis([r for d in reports for r in d['reviews']]))
 total['calendar_days']=calendar.monthrange(*map(int,p.split('-')))[1]
 total['note']='只彙總本次選取且有權限的醫院；缺任一院月報時合計財務指標不補零；人日比率須所有選取院的照護範圍一致可自動對應；未區分住院／門診者只提供標示口徑的參考值。'
 return total
