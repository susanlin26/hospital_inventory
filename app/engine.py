from .performance import timed
"""純Decimal分析引擎；無資料、零分母及不可比情境以原因呈現。"""
from decimal import Decimal, localcontext
import calendar
from collections import defaultdict
from .excel import period

D=Decimal
TAX=D('1.05')
DEFAULT_RULES={'high_days':'90','severe_days':'180','change_pct':'10','change_amount':'5000','abc_a':'80','abc_b':'95','idle_warn_days':'90','idle_days':'180','purchase_pct':'10','purchase_amount':'3000','low_days':'14'}

def previous(p):
 y,m=map(int,p.split('-'));return f'{y-1:04}-12' if m==1 else f'{y:04}-{m-1:02}'

def calc(line):
 with localcontext() as c:
  c.prec=38
  val=lambda k:D(str(line[k]))
  used=(val('sale_a')-val('adj_a')-val('other_a'))*TAX
  qty=val('sale_q')-val('adj_q')-val('other_q')
  opening=val('open_a')*TAX;ending=val('end_a')*TAX;avg=(opening+ending)/2
  turn=used/avg if avg>0 and used>0 else None
  days=calendar.monthrange(*map(int,line['period'].split('-')))[1]
  incoming=val('in_a')*TAX/val('in_q') if val('in_q')>0 and val('in_a')>0 else None
  reason=None if turn is not None else '平均存貨或耗用不大於0，週轉不適用'
  return dict(used=used,qty=qty,opening=opening,ending=ending,average=avg,turnover=turn,days=D(days)/turn if turn else None,unit_cost=used/qty if qty>0 and used>=0 else None,purchase=incoming,purchase_reason=None if incoming else '本月無有效進貨或數量金額待確認',coverage=ending/used*days if used>0 and ending>=0 else None,reason=reason)

def metrics(rows,beds=None):
 usable=[r for r in rows if r.get('valid',True)]
 total={k:D(0) for k in ('used','opening','ending','average')}
 for row in usable:
  c=calc(row)
  for k in total:total[k]+=c[k]
 turn=total['used']/total['average'] if total['average']>0 and total['used']>0 else None
 n=calendar.monthrange(*map(int,usable[0]['period'].split('-')))[1] if usable else None
 total.update(turnover=turn,days=D(n)/turn if n and turn else None,per_bed=total['used']/D(str(beds)) if beds is not None and D(str(beds))>0 and usable else None,bed_reason=None if beds is not None and D(str(beds))>0 else '未提供有效實際平均住院人數',valid_count=len(usable),excluded_count=len(rows)-len(usable))
 if not usable:
  for k in ('used','opening','ending','average'):total[k]=None
 return total

def delta(current,prior):
 if current is None or prior is None:return dict(amount=None,pct=None,reason='比較資料不足')
 return dict(amount=current-prior,pct=(current-prior)/prior*100 if prior>0 else None,reason=None if prior>0 else '比較基期不大於0')

def factor(a,b,confirmed=False):
 if not b:return dict(reason='沒有比較期資料')
 if (a['code'],a['name'],a['unit'])!=(b['code'],b['name'],b['unit']):return dict(reason='品項、規格或單位不一致')
 ca,cb=calc(a),calc(b)
 return decompose(ca['qty'],ca['used'],cb['qty'],cb['used'])

def decompose(q,u,bq,bu):
 if q<0 or bq<0:return dict(reason='異常：本月或基準耗用量<0',anomaly=True)
 if u<0 or bu<0:return dict(reason='耗用金額為負，不適合拆解')
 total=u-bu
 if q==0 or bq==0:
  return dict(quantity=total,unit_cost=D(0),total=total,reason=None,note='零量情境依指定口徑將金額差異全列數量影響、單位成本影響列0；不推算零量期間單位成本，此為歸列方式，不代表成本沒有改變。')
 bc=bu/bq;quantity=(q-bq)*bc
 return dict(quantity=quantity,unit_cost=total-quantity,total=total,reason=None)

@timed('financial')
def analyze(rows,history,p,beds=None,rules=None,baseline='previous',purchase_baseline='last',confirmations=None):
 rules={**DEFAULT_RULES,**(rules or {})};p=period(p)
 active=[r for r in rows if r['valid']];hist=[r for r in history if r['valid'] and r['period']<p]
 base_periods=[previous(p)]
 if baseline in ('mean3','mean6'):
  for _ in range((3 if baseline=='mean3' else 6)-1):base_periods.append(previous(base_periods[-1]))
 if baseline=='year':base_periods=[f'{int(p[:4])-1:04}'+p[4:]]
 available={r['period'] for r in hist}
 base_complete=all(x in available for x in base_periods)
 prior_rows=[r for r in hist if r['period']==previous(p)]
 prior_by={r['code']:r for r in prior_rows}
 history_by_key={}
 for row in hist:history_by_key.setdefault((row['code'],row['name'],row['unit']),[]).append(row)
 result=[];findings=[]
 for row in active:
  c=calc(row);pr=prior_by.get(row['code']);item_history=history_by_key.get((row['code'],row['name'],row['unit']),[]);base_matches=[x for x in item_history if x['period'] in base_periods]
  # 不將缺列或缺月視為0；近三月必須完整。
  baseline_used=sum((calc(x)['used'] for x in base_matches),D(0))/len(base_periods) if base_complete and len(base_matches)==len(base_periods) else None
  change=delta(c['used'],baseline_used)
  purch=[x for x in item_history if calc(x)['purchase'] is not None]
  purch.sort(key=lambda x:x['period'],reverse=True)
  last=purch[0] if purch else None;last_price=calc(last)['purchase'] if last else None
  weighted=None
  if len(purch)>=3:
   nearest=purch[:3];weighted=sum((D(x['in_a'])*TAX for x in nearest),D(0))/sum((D(x['in_q']) for x in nearest),D(0))
  item={**row,**c,'change':change,'factor':factor(row,pr),'last_purchase_period':last['period'] if last else None,'last_purchase':last_price,'purchase_change':delta(c['purchase'],last_price),'weighted3_purchase':weighted}
  result.append(item)
  if c['qty']<0:findings.append(dict(level='品項',code=row['code'],name=row['name'],rule='耗用數量異常',severity='高',value=c['qty'],basis='淨耗用量<0；請核對銷貨、調整及其他異動'))
  if c['coverage'] is not None and c['coverage']>D(rules['high_days']):findings.append(dict(level='品項',code=row['code'],name=row['name'],rule='高庫存',severity='高' if c['coverage']>D(rules['severe_days']) else '中',value=c['coverage'],basis='期末存貨÷本月耗用×當月天數'))
  if change['pct'] is not None and abs(change['pct'])>=D(rules['change_pct']) and abs(change['amount'])>=D(rules['change_amount']):findings.append(dict(level='品項',code=row['code'],name=row['name'],rule='重大耗用差異',severity='高',value=change['amount'],basis=','.join(base_periods)))
  if pr:
   for k,end in [('open_q','end_q'),('open_a','end_a')]:
    diff=D(row[k])-D(pr[end])
    if diff:findings.append(dict(level='品項',code=row['code'],name=row['name'],rule='跨月期初不符'+('數量' if k.endswith('q') else '金額'),severity='中',value=diff,basis=previous(p)))
 total=metrics(active,beds)
 base_rows=[r for r in hist if r['period'] in base_periods]
 base_total=sum((calc(r)['used'] for r in base_rows),D(0))/len(base_periods) if base_complete else None
 total['change']=delta(total['used'],base_total)
 groups=defaultdict(list)
 for r in active:groups[r['category']].append(r)
 categories=[]
 for category,items in groups.items():
  met=metrics(items);base_cat=[r for r in base_rows if r['category']==category]
  cat_baseline=sum((calc(r)['used'] for r in base_cat),D(0))/len(base_periods) if base_complete and all(any(x['period']==bp for x in base_cat) for bp in base_periods) else None
  met.update(category=category,change=delta(met['used'],cat_baseline));categories.append(met)
  ch=met['change']
  if ch['pct'] is not None and abs(ch['pct'])>=D(rules['change_pct']) and abs(ch['amount'])>=D(rules['change_amount']):findings.append(dict(level='分類',code=category,name=category,rule='分類重大耗用差異',severity='高',value=ch['amount'],basis=','.join(base_periods)))
 ch=total['change']
 if ch['pct'] is not None and abs(ch['pct'])>=D(rules['change_pct']) and abs(ch['amount'])>=D(rules['change_amount']):findings.append(dict(level='整體',code='ALL',name='全院',rule='整體重大耗用差異',severity='高',value=ch['amount'],basis=','.join(base_periods)))
 positive=sum((x['used'] for x in result if x['used']>0),D(0));cumulative=D(0)
 for item in sorted(result,key=lambda x:x['used'],reverse=True):
  before=cumulative;cumulative+=max(item['used'],D(0))
  item['abc']='不適用' if item['used']<=0 or positive<=0 else ('A' if before/positive*100<D(rules['abc_a']) else 'B' if before/positive*100<D(rules['abc_b']) else 'C')
  item['cumulative_pct']=cumulative/positive*100 if positive>0 else None
 notes=['180天未耗用按完整連續月報覆蓋天數判斷；缺月、缺品項或單位變更均不當作零。']
 if not base_complete:notes.append('比較月份不足，缺月份不當成零。')
 notes.append('各品項的庫存覆蓋天數與期間週轉天數定義不同。')
 summary=[f"{p} 本月耗用{__import__('app.formatting',fromlist=['money']).money(total['used'])}元，期末存貨{__import__('app.formatting',fromlist=['money']).money(total['ending'])}元；分析{len(active)}項，隔離{len(rows)-len(active)}項。"] if active else ['本月尚無可計算資料。']
 if ch['pct'] is not None:summary.append(f"較比較基準{','.join(base_periods)}，耗用差異{__import__('app.formatting',fromlist=['money']).money(ch['amount'])}元（{ch['pct']:.2f}%）。")
 summary.append(f'共觸發{len(findings)}筆規則；原因尚待主責單位查核，不能由數字推定。')
 reconciliation={'prior_period':previous(p),'available':bool(prior_rows),'opening':sum((D(x['open_a']) for x in active),D(0))*TAX if active else None,'previous_ending':sum((D(x['end_a']) for x in prior_rows),D(0))*TAX if prior_rows else None,'new_codes':sorted({x['code'] for x in active}-{x['code'] for x in prior_rows}) if prior_rows else [],'missing_codes':sorted({x['code'] for x in prior_rows}-{x['code'] for x in active}) if prior_rows else []}
 reconciliation['difference']=reconciliation['opening']-reconciliation['previous_ending'] if reconciliation['opening'] is not None and reconciliation['previous_ending'] is not None else None
 from .analytics import enrich
 return enrich(dict(total=total,items=result,categories=categories,findings=findings,summary=summary,notes=notes,baseline=base_periods,rules=rules,reconciliation=reconciliation),rows,hist,p,beds,purchase_baseline,confirmations or {})
