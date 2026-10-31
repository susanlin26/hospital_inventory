"""直接使用實際住院人日數；不把未知照護範圍當作RCW。"""
import calendar
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP,localcontext
from .engine import delta

D=Decimal
TOTAL_NAMES={'全院','全院合計','全院平均','全院病床','全院平均床數','ALL','TOTAL'}
SCOPE_NAMES={'unconfirmed':'月報缺少可辨識照護範圍', 'hospital_reference':'全院月報範圍未區分（參考）','hospital':'全院住院服務','RCW':'RCW住院服務'}

def decimal(value):
 try:
  x=D(str(value));return x if x.is_finite() else None
 except (ValueError,TypeError,InvalidOperation):return None

def half_up(x):
 return x.quantize(D('1'),rounding=ROUND_HALF_UP) if x is not None else None

def bed_days(p,value,measurement="average_beds"):
 n=calendar.monthrange(*map(int,p.split('-')))[1];v=decimal(value)
 valid=measurement=='patient_days' and v is not None and v>0 and v==v.to_integral_value()
 with localcontext() as context:
  context.prec=38;raw=v if valid else None
 return {'calendar_days':n,'average_beds':None,'patient_days_raw':raw,'patient_days':half_up(raw),'status':'有效' if valid else ('資料未匯入' if value is None else '住院人日數須為正整數' if measurement=='patient_days' else '舊平均床數未換算，請提供住院人日數')}

def census(records,p):
 rows=[{**x,**bed_days(p,x['value'],x.get('measurement','average_beds'))} for x in records]
 total_rows=[x for x in rows if x['department'].upper() in TOTAL_NAMES]
 selected=total_rows if total_rows else rows
 duplicate_total=len(total_rows)>1
 good=bool(selected) and not duplicate_total and all(x['patient_days_raw'] is not None for x in selected)
 raw=sum((x['patient_days_raw'] for x in selected),D(0)) if good else None
 avg=None
 return {'period':p,'calendar_days':calendar.monthrange(*map(int,p.split('-')))[1],'records':rows,'patient_days_raw':raw,'patient_days':half_up(raw),'average_beds':avg,'provided_departments':[x['department'] for x in rows],'total_record_used':bool(total_rows),'status':('有效' if good else '全院資料重複，須確認' if duplicate_total else '資料未匯入' if not rows else '舊平均床數未換算，請提供住院人日數'),'note':'各床別先保留小數加總，全院只四捨五入一次；全院合計列與床別列並存時以全院列為準，不重複加總。僅代表已提供範圍，不推定未填床別。'}

def fetch_census(c,h,p,scope='hospital'):
 from .db import bed_history
 rows=[{k:x.get(k) for k in ('hospital','period','department','value','source','measurement')} for x in bed_history(c,h).get(p,[])]
 if scope not in ('hospital','全院',''):rows=[x for x in rows if x['department']==scope]
 return census(rows,p)

def row_department(row):
 dep=row.get('filename_department')
 if dep and any(token in dep for token in ('門診','急診','非住院','混合','其他用途')):return 'mixed'
 if dep:return 'hospital' if dep in ('全院住院','全院住院服務') else 'hospital_reference' if dep in TOTAL_NAMES else dep
 raw=row.get('raw') or {}
 for key in ('床別','科別','病房別','照護範圍','耗用範圍','care_scope'):
  v=str(raw.get(key,'')).strip()
  if not v:continue
  if any(token in v for token in ('門診','急診','非住院','混合','其他用途')):return 'mixed'
  u=v.upper().replace('ＲＣＷ','RCW')
  if 'RCW' in u:return 'RCW'
  if v in ('全院住院','全院住院服務','住院','hospital'):return 'hospital'
  if v in ('全院','全院合計','全院月報','TOTAL','ALL'):return 'hospital_reference'
  if key in ('床別','科別','病房別'):return v
  return 'mixed'
 return None

def inventory_department(row):
 dep=row_department(row)
 return '全院' if dep in ('hospital','hospital_reference') else dep if dep and dep!='mixed' else ''

def select_department(rows,p,requested=None):
 if requested is not None:return requested
 current=[x for x in rows if x['period']==p];available=sorted({inventory_department(x) for x in current})
 if len(available)==1 and available[0] and any(x.get('filename_department') for x in current):return available[0]
 return ('RCW' if 'RCW' in available else available[0]) if len(available)>1 else None


def resolve_scope(rows,cens):
 """Only structural source evidence is used; saved supervisor declarations are ignored."""
 if not rows:return 'unconfirmed','沒有此院此月已啟用的有效耗用明細'
 deps={row_department(x) for x in rows};provided=set(cens['provided_departments'])
 if not cens['records']:return 'unconfirmed','資料未匯入：缺少此院此月每月住院人日數（床別、住院人日數）'
 if not cens['patient_days_raw']:return 'unconfirmed','住院人日資料無效：'+cens['status']
 if deps=={'RCW'}:
  if provided=={'RCW'}:return 'RCW','有效：月報科別／床別明確為RCW，對應同月RCW住院人日數'
  return 'unconfirmed','月報為RCW，缺少同院同月RCW床數，不能使用全院床數'
 if deps=={'hospital'} and cens['total_record_used']:return 'hospital','有效：全院住院耗用對應全院住院人日數'
 if None not in deps and deps and deps.issubset(provided) and deps==provided and not cens['total_record_used']:
  return 'beds:'+','.join(sorted(deps)),'有效：月報及床數的已提供床別完整相符；合計僅含這些床別'
 if cens['total_record_used'] and deps.issubset({None,'hospital_reference','mixed'}):
  return 'hospital_reference','參考口徑：整份月報耗用÷全院住院人日；月報未區分住院、門診或其他用途，不作精確住院耗材績效比較'
 if deps=={'hospital'}:return 'unconfirmed','月報為全院住院耗用，但床數只有'+('、'.join(sorted(provided)))+'；缺少全院合計或可完整對應的床別資料'
 if deps=={None}:return 'unconfirmed','月報缺少照護範圍、科別或床別欄位；床數僅有'+('、'.join(sorted(provided)))+'，無法證明整份月報耗用屬此範圍；不可將全院耗用除以RCW床數'
 return 'unconfirmed','月報床別／科別（'+('、'.join(str(x or '未提供') for x in sorted(deps,key=str)))+'）與床數床別（'+('、'.join(sorted(provided)))+'）無法完整對應；需同範圍耗用與床數'


def daily_metrics(used,cens,scope,scope_reason=None):
 n=cens['patient_days'];good=(scope in ('hospital','RCW','hospital_reference') or scope.startswith('beds:')) and used is not None and n is not None and n>0
 reason=(scope_reason or '有效') if good else '月報缺少可辨識照護範圍、科別或床別欄位' if scope not in ('hospital','RCW','hospital_reference') else '沒有已啟用耗用資料' if used is None else '資料未匯入' if cens['patient_days_raw'] is None else '住院人日為零或無效，無法計算'
 if not good and scope_reason and used is not None and n is not None and n>0:reason=scope_reason
 if used is None:reason='沒有此院此月已啟用的有效耗用明細'
 elif cens['patient_days_raw'] is None:reason='資料未匯入：缺少此院此月住院人日數' if not cens['records'] else '此院此月床數為零、無效或全院合計重複：'+cens['status']
 elif n is None or n<=0:reason='此院此月住院人日取整後為零或無效，不能作為分母'
 daily=used/n if good else None
 return {'patient_days':n,'patient_days_raw':cens['patient_days_raw'],'calendar_days':cens['calendar_days'],'average_beds':cens['average_beds'],'per_patient_day':daily,'standard30_per_bed':daily*30 if daily is not None else None,'monthly_per_bed':daily*30 if good else None,'care_scope':scope,'care_scope_name':SCOPE_NAMES.get(scope,'已提供床別：'+scope[5:] if scope.startswith('beds:') else SCOPE_NAMES['unconfirmed']),'daily_label':'全院月報每住院人日耗用（參考）' if scope=='hospital_reference' else '每住院人日耗用','comparison_eligible':good and scope!='hospital_reference','daily_status':reason,'scope_note':'沿用進銷存實際耗用，不另拆倉庫出貨；床別計算僅使用原始可辨識明細，不自行分攤無法歸屬的耗用。住院人日採直接輸入，不由平均床數推估。'}

def pooled_daily(entries,across_months=False):
 """跨院加總未取整人日後取整；跨月合計各月住院人日。同範圍且資料完整才計比率。"""
 complete=bool(entries) and all(x.get('used') is not None and x.get('patient_days_raw') is not None and x.get('per_patient_day') is not None for x in entries)
 scopes={x.get('care_scope') for x in entries}
 complete=complete and len(scopes)==1 and None not in scopes and 'unconfirmed' not in scopes
 used=sum((x['used'] for x in entries),D(0)) if complete else None
 raw=sum((x['patient_days_raw'] for x in entries),D(0)) if complete else None
 days=(sum((x['patient_days'] for x in entries),D(0)) if complete else None) if across_months else half_up(raw);valid=days is not None and days>0
 return {'used':used,'patient_days_raw':raw,'patient_days':days,'per_patient_day':used/days if valid else None,'standard30_per_bed':used/days*30 if valid else None,'complete':bool(valid),'care_scope':next(iter(scopes)) if len(scopes)==1 else None,'comparison_eligible':bool(valid) and scopes!={'hospital_reference'},'reason':('參考口徑：月報未區分住院／門診，不作精確住院耗材績效比較' if scopes=={'hospital_reference'} else '有效') if valid else '；'.join(dict.fromkeys(x.get('daily_status','缺少月份的耗用或床數') for x in entries if x.get('per_patient_day') is None)) or '各院或各月照護範圍不同，不能合併比較'}

def review_kpis(reviews):
 candidates=[x for x in reviews if (x.get('details') or {}).get('outcome')!='reasonable' and x.get('measure')]
 actual=[x for x in candidates if x.get('status')=='已結案' and x.get('approved') and (x.get('details') or {}).get('outcome')=='improved' and (x.get('details') or {}).get('result')]
 reasonable=[x for x in reviews if x.get('status')=='已結案' and (x.get('details') or {}).get('outcome')=='reasonable']
 return {'improvement_rate':D(len(actual))/len(candidates)*100 if candidates else None,'improved_cases':len(actual),'improvement_cases':len(candidates),'reasonable_closed_cases':len(reasonable),'review_count':len(reviews),'definition':'已結案且已覆核、結果類別為實際完成改善並填寫結果的案件÷排除合理原因結案後、有改善措施的案件。舊案件未確認結果不算已改善；無案件不顯示100%。'}


def period_turnover(points):
 """期間成本合計÷按各月實際天數加權的平均存貨，非月週轉率平均。"""
 complete=bool(points) and all(x.get('used') is not None and x.get('average') is not None and x.get('calendar_days') for x in points)
 if not complete:return {'used':None,'average':None,'turnover':None,'days':None,'calendar_days':None,'reason':'期間月份不足，不補零'}
 days=sum(x['calendar_days'] for x in points);used=sum((x['used'] for x in points),D(0));avg=sum((x['average']*x['calendar_days'] for x in points),D(0))/days
 ratio=used/avg if avg>0 and used>0 else None
 return {'used':used,'average':avg,'turnover':ratio,'days':D(days)/ratio if ratio else None,'calendar_days':days,'reason':'期間耗用合計÷各月平均存貨依實際天數加權平均；週轉天數=期間日曆天數÷期間週轉率'}
