"""管理總覽共用結果：四指標、同院比較、三段摘要、原精度分類排行與追蹤入口。"""
import calendar
from datetime import date,datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D,ROUND_HALF_UP
from .engine import delta
from .inpatient import pooled_daily,period_turnover
from .analysis_grid import build
from .formatting import money


def number(v):
 return '—' if v is None else f'{v.quantize(D("0.1"),rounding=ROUND_HALF_UP):,.1f}'


def rate_text(ch):
 if ch['pct'] is not None:return number(ch['pct'])+'%'
 if ch.get('baseline')==0:return '基準為零'
 if ch.get('baseline') is not None and ch['baseline']<0:return '基準為負值'
 return '缺少基準資料'


def financial(points,p):
 good=[x for x in points if x.get('used') is not None]
 result={k:sum((x[k] for x in good),D(0)) if good else None for k in ('used','ending','average')}
 result['days']=D(calendar.monthrange(*map(int,p.split('-')))[1])*result['average']/result['used'] if good and result['used']>0 and result['average']>0 else None
 return result


def standard(points):
 pooled=pooled_daily(points)
 valid=pooled['complete'] and pooled['comparison_eligible']
 return dict(value=pooled['per_patient_day']*30 if valid else None,reason='同範圍耗用合計÷住院人日合計×30' if valid else pooled['reason'],patient_days=pooled['patient_days'],patient_days_raw=pooled['patient_days_raw'])


def rank_grid(grid,absolute=True):
 keys=[c['key'] for c in grid['columns']];ranked=[];excluded=[]
 for row in grid['rows']:
  x=dict(zip(keys,row['cells']));x=dict(category=x['category'],current=x['used'],baseline=x['baseline'],difference=x['difference'],pct=x['pct'])
  if x['difference'] is None:excluded.append(dict(category=x['category'],reason='缺少同範圍本期或基準資料，不列排名'));continue
  if not isinstance(x['pct'],(D,int,float)):x['pct']=str(x['pct']).replace('基準耗用為0','基準為零').replace('基準庫存為0','基準為零').replace('基準耗用為負','基準為負值').replace('基準庫存為負','基準為負值')
  ranked.append(x)
 ranked.sort(key=lambda x:(-abs(x['difference']) if absolute else -x['difference'],x['category']))
 return dict(rows=[dict(x,rank=i+1) for i,x in enumerate(ranked[:5])],excluded=excluded,eligible_count=len(ranked),direction_rows=ranked,note='以未取整增減金額絕對值排序，包含增加與減少；前5名不一定等於整體差異。' if absolute else '依未取整增減金額由大到小排列。')


def card(key,title,reports,period,base_periods):
 covered=[d for d in reports if d['total'].get('used') is not None]
 missing=[d['hospital'] for d in reports if d not in covered]
 paired=[];basepts=[]
 for d in covered:
  pts=[next((x for x in d['trend'] if x['period']==bp),{}) for bp in base_periods]
  valid=all(x.get('used') is not None for x in pts)
  if key=='standard30_per_bed':valid=valid and standard([d['total']])['value'] is not None and all(standard([x])['value'] is not None and x.get('care_scope')==d['total'].get('care_scope') for x in pts)
  if valid:paired.append(d);basepts.append(pts)
 current_fin=financial([d['total'] for d in covered],period)
 current=standard([d['total'] for d in reports])['value'] if key=='standard30_per_bed' else current_fin[key]
 current_pair=standard([d['total'] for d in paired])['value'] if key=='standard30_per_bed' else financial([d['total'] for d in paired],period)[key]
 baseline=None
 if paired:
  combined=[]
  for i,bp in enumerate(base_periods):
   pts=[x[i] for x in basepts];point=dict(period=bp,**financial(pts,bp),**standard(pts));point['standard30_per_bed']=point['value'];point['calendar_days']=calendar.monthrange(*map(int,bp.split('-')))[1];combined.append(point)
  if key in ('used','ending'):baseline=sum((x[key] for x in combined),D(0))/len(combined)
  elif key=='days':baseline=period_turnover(combined)['days']
  else:baseline=combined[0]['value'] if len(combined)==1 else None
 ch=delta(current_pair,baseline);ch['baseline']=baseline
 reason=''
 if key=='standard30_per_bed' and current is None:reason=standard([d['total'] for d in reports])['reason']
 elif current is None:
  if key=='days' and current_fin['used']==0 and current_fin['ending'] and current_fin['ending']>0:reason='本期無耗用，週轉天數不適用'
  elif key=='days' and current_fin['used'] is not None and current_fin['used']<=0:reason='本期耗用不大於零，週轉天數不適用'
  elif key=='days' and current_fin['average'] is not None and current_fin['average']<=0:reason='平均庫存不大於零，週轉天數不適用'
  else:reason='缺少本期月報或有效耗用／平均庫存'
 pairnames=[d['hospital'] for d in paired]
 missing_base=[d['hospital']+' '+bp for d in reports for bp in base_periods if not any(x['period']==bp and x.get('used') is not None for x in d['trend'])]
 if baseline is None and key=='days' and paired:
  missing_base.append('基準期無耗用，週轉天數不適用' if all(pt.get('used')==0 for group in basepts for pt in group) else '基準期耗用不大於零或平均庫存無效，週轉天數不適用')
 if baseline is None and key=='standard30_per_bed':missing_base += [d['hospital']+' '+bp+' '+next((x.get('daily_status','範圍不符') for x in d['trend'] if x['period']==bp),'缺少月報／床數') for d in reports for bp in base_periods]
 return dict(key=key,title=title,value=current,baseline=baseline,comparison_current=current_pair,change=ch,covered=[d['hospital'] for d in covered],requested=[d['hospital'] for d in reports],missing=missing,comparison_hospitals=pairnames,missing_baseline=missing_base,reason=reason,comparison_note='比較採共同有效院別：'+('、'.join(pairnames) or '無')+('；比較用本期數值與主數值涵蓋範圍不同。' if len(paired)!=len(covered) else ''))


def change_sentence(c,unit='元'):
 ch=c['change'];diff=ch['amount'];baseline=c['baseline'];f=number if unit=='天' else money
 if diff is None:return '比較資料不足（'+('；'.join(c['missing_baseline']) or c['reason'] or '無相同範圍可比資料')+'）'
 direction=('延長' if diff>0 else '縮短' if diff<0 else '持平') if unit=='天' else ('增加' if diff>0 else '減少' if diff<0 else '持平')
 return direction+(f(abs(diff))+unit if diff else '')+('（'+rate_text(ch)+'）' if unit!='天' else '')


def concentration(block,diff,label):
 if diff is None:return label+'分類比較資料不足。'
 rows=block['direction_rows']
 if diff==0:
  return '整體接近基準，分類間仍有明顯增減。' if any(x['difference']>0 for x in rows) and any(x['difference']<0 for x in rows) else '分類整體持平。'
 direction='增加' if diff>0 else '減少'
 names=[x['category'] for x in sorted(rows,key=lambda x:-abs(x['difference'])) if x['difference']*diff>0][:2]
 return label+direction+'主要集中於'+('及'.join(names))+'。' if names else label+direction+'的分類來源尚無完整可比資料。'


def build_dashboard(reports,overview,today=None):
 today=today or datetime.now(ZoneInfo('Asia/Taipei')).date();p=overview['period'];base=reports[0]['baseline'] if reports else []
 label='上月' if base==[__import__('app.engine',fromlist=['previous']).previous(p)] else '去年同期' if len(base)==1 and base[0]==str(int(p[:4])-1)+p[4:] else '所選基準'
 specs=[('used','本月實際耗用'),('standard30_per_bed','每床標準月均耗用'),('ending','期末庫存'),('days','存貨週轉天數')]
 cards=[card(key,title,reports,p,base) for key,title in specs]
 grids={kind:overview.get('analysis_grids' if kind=='consumption' else 'inventory_grids',{}).get('category') or build(reports,overview,metric=kind) for kind in ('consumption','inventory')}
 ranks={kind:rank_grid(grid) for kind,grid in grids.items()};report_ranks={kind:rank_grid(grid,False) for kind,grid in grids.items()}
 # 固定選定院別逐月彙總；缺院月保留缺口，不以院數變動製造趨勢。
 periods=[];cursor=p
 for _ in range(12):periods.append(cursor);cursor=__import__('app.engine',fromlist=['previous']).previous(cursor)
 trend=[]
 for month in reversed(periods):
  pts=[next((x for x in d['trend'] if x['period']==month),{}) for d in reports];missing=[d['hospital'] for d,x in zip(reports,pts) if x.get('used') is None];fin=financial(pts,month);s=standard(pts)
  if missing:fin={k:None for k in fin}
  trend.append(dict(period=month,**fin,standard30_per_bed=s['value'],patient_days=s['patient_days'],missing=missing,scope_reason=s['reason'],days_reason='本期無耗用，週轉天數不適用' if fin['used']==0 and fin['ending'] and fin['ending']>0 else '耗用不大於零，週轉天數不適用' if fin['used'] is not None and fin['used']<=0 else '平均庫存不大於零，週轉天數不適用' if fin['average'] is not None and fin['average']<=0 else '缺少有效月報／平均庫存'))
 a,b,c,d=cards
 cohort=lambda x:('（'+x['comparison_note']+'）') if len(x['comparison_hospitals'])!=len(x['covered']) else ''
 consumption=(f"本月耗用{money(a['value'])}元，較{label}{change_sentence(a)}{cohort(a)}；" if a['value'] is not None else '本月耗用無法計算：'+a['reason']+'；')
 standard_text=(f"每床標準月均耗用{money(b['value'])}元，較{label}{change_sentence(b)}{cohort(b)}。" if b['value'] is not None else '每床標準月均耗用無法計算：'+b['reason']+'。')
 inventory=(f"期末庫存{money(c['value'])}元，較{label}{change_sentence(c)}{cohort(c)}；" if c['value'] is not None else '期末庫存無法計算：'+c['reason']+'；')
 turnover=(f"存貨週轉天數由{number(d['baseline'])}天至{number(d['comparison_current'])}天，{change_sentence(d,'天')}{cohort(d)}。" if d['value'] is not None and d['baseline'] is not None else f"本期存貨週轉天數{number(d['value'])}天；{change_sentence(d,'天')}。" if d['value'] is not None else d['reason']+'。')
 paragraphs=['耗用變化：'+consumption+standard_text+concentration(ranks['consumption'],a['change']['amount'],'耗用'),'庫存與週轉：'+inventory+turnover+concentration(ranks['inventory'],c['change']['amount'],'庫存')]

 from .analytics import rule_for
 concern=[]
 for r in reports:
  for x in r['categories']:
   ch=x['change'];rr=rule_for(r['rules'],x['category'])
   if ch['amount'] is not None and ch['pct'] is not None and abs(ch['amount'])>=D(rr['change_amount']) and abs(ch['pct'])>=D(rr['change_pct']):concern.append(x['category'])
  concern += [x['category'] for x in r['items'] if x.get('risk_state') in ('高庫存低週轉','無耗用但有庫存','低庫存風險')]
 concern=list(dict.fromkeys(concern))[:2]
 paragraphs.append('關注方向：建議優先檢視'+('及'.join(concern))+'耗材的耗用數量及進貨情形，差異原因待確認。' if concern else '關注方向：目前可比較資料未見達已設定門檻的明顯異常，持續觀察；缺漏資料請先補齊再判讀。' if any(x['value'] is not None for x in cards) else '關注方向：目前缺少有效月報，請先匯入或啟用資料，再判讀變化。')
 alerts=[];seen=set();cases=[]
 for r in reports:
  for f in r['open_findings']:
   key=(r['hospital'],p,r.get('selected_department') or '',f['level'],f['code'],f['rule'])
   if key not in seen:seen.add(key);alerts.append(dict(hospital=r['hospital'],period=p,department=key[2],level=f['level'],code=f['code'],rule=f['rule']))
  for case in r['case_history']:
   due=case.get('due_date')
   if due and str(due)[:10]<today.isoformat() and case['status']!='已結案':cases.append(case['id'])
 cases=list(dict.fromkeys(cases))
 return dict(period=p,baseline_periods=base,baseline_label=label,hospitals=[r['hospital'] for r in reports],cards=cards,paragraphs=paragraphs,ranks=ranks,report_ranks=report_ranks,trend=trend,entries=dict(pending_alerts=alerts,pending_count=len(alerts),overdue_case_ids=cases,overdue_count=len(cases),as_of=today.isoformat(),note='目前狀態，非分析月底歷史狀態：提醒為所選分析月尚未結案的系統提醒，依醫院／月份／科別／層級／品號或分類／規則去重；逾期為所選醫院、立案月不晚於分析月、截至'+today.isoformat()+'仍未結案且期限早於今日的案件。'))
