"""可重算分析、連續歷史條件、三層摘要及證據鏈。金額只由Decimal運算。"""
import calendar, hashlib, json
from decimal import Decimal as D
from .engine import calc,metrics,delta,factor,previous,DEFAULT_RULES


def rule_for(rules,category=None):
 return {**DEFAULT_RULES,**{k:v for k,v in rules.items() if k in DEFAULT_RULES},**rules.get('categories',{}).get(category,{})}


def pair_key(a,b):
 if not b:return None
 keys=['code','name','unit','period','batch_id','row','sale_a','sale_q','adj_a','adj_q','other_a','other_q']
 return hashlib.sha256(json.dumps([{k:x.get(k) for k in keys} for x in [a,b]],sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


from .formatting import money,number_text


def change_text(label,ch,unit='元'):
 if ch['amount'] is None:return label+'比較資料不足。'
 return f"{label}差異{(money if unit=='元' else number_text)(ch['amount'])}{unit}（{number_text(ch['pct'])}%）；"+('基期不大於0，不判定增減率。' if ch['pct'] is None else '')


def enrich(r,rows,hist,p,beds,purchase_baseline,confirmations):
 rules=r['rules'];byprior={x['code']:x for x in hist if x['period']==previous(p)}
 base=r['baseline'];summaries=[];risk_ending=D(0);total=r['total']
 history_by_key={};history_by_code={}
 for row in hist:
  history_by_key.setdefault((row['code'],row['name'],row['unit']),[]).append(row)
  history_by_code.setdefault(row['code'],{})[row['period']]=row
 # 重新依分類門檻獨立判斷；跨月差異保留。
 r['findings']=[x for x in r['findings'] if x['rule'].startswith('跨月') or x['rule']=='耗用數量異常']
 def finding(level,code,name,rule,value,basis,severity='高',pct=None):
  r['findings'].append(dict(level=level,code=code,name=name,rule=rule,value=value,basis=basis,severity=severity,pct=pct))
 def summary(level,code,text,items,rule):
  summaries.append(dict(level=level,code=code,text=text,rule=rule,baseline=base,sources=[{k:x.get(k) for k in ('code','name','batch_id','version','category_version','sheet','row','period','filename','file_id','parser_version')} for x in items]))
 for x in r['items']:
  rr=rule_for(rules,x['category']);old=byprior.get(x['code']);same=bool(old and (old['name'],old['unit'])==(x['name'],x['unit']))
  key=pair_key(x,old);confirm=confirmations.get(x['code']);approved=bool(confirm and confirm['fingerprint']==key)
  x['factor_key']=key;x['factor_confirmation']=confirm if approved else None
  x['factor']=factor(x,old,confirmed=approved)
  x['factor_candidate']=bool(old and any(D(str(r[k]))!=0 for r in (x,old) for k in ('adj_q','adj_a','other_q','other_a')) and not factor(x,old,confirmed=True).get('reason'))
  item_history=history_by_key.get((x['code'],x['name'],x['unit']),[]);matches=[h for h in item_history if h['period'] in base]
  bm=metrics(matches) if len(matches)==len(base) else None
  # 多月耗用數量取平均，不混合各品項單位。
  bq=sum((calc(h)['qty'] for h in matches),D(0))/len(base) if bm else None
  bu=sum((calc(h)['used'] for h in matches),D(0))/len(base) if bm else None
  x['baseline_used']=bu;x['baseline_qty']=bq;x['qty_change']=delta(x['qty'],bq)
  bc=bu/bq if bu is not None and bq is not None and bq>0 and bu>=0 else None
  x['baseline_unit_cost']=bc;x['unit_cost_change']=delta(x['unit_cost'],bc)
  effective=[h for h in item_history if calc(h)['purchase'] is not None]
  effective.sort(key=lambda h:h['period'],reverse=True)
  chosen=effective[:3] if purchase_baseline=='weighted3' else effective[:1]
  complete=len(chosen)==(3 if purchase_baseline=='weighted3' else 1)
  price=sum((D(h['in_a'])*D('1.05') for h in chosen),D(0))/sum((D(h['in_q']) for h in chosen),D(0)) if complete else None
  x['purchase_basis']=price;x['purchase_periods']=[h['period'] for h in chosen];x['purchase_basis_complete']=complete
  x['purchase_delta']=delta(x['purchase'],price)
  x['purchase_impact']=x['purchase_delta']['amount']*D(x['in_q']) if x['purchase_delta']['amount'] is not None else None
  x['purchase_alert']=bool(x['purchase_delta']['pct'] is not None and abs(x['purchase_delta']['pct'])>=D(rr['purchase_pct']) and abs(x['purchase_impact'])>=D(rr['purchase_amount']))
  if x['purchase_alert']:finding('品項',x['code'],x['name'],'採購單價上漲' if x['purchase_delta']['amount']>0 else '採購單價下降',x['purchase_impact'],','.join(x['purchase_periods'])+'；同數量基準價差估算，非實際損益',pct=x['purchase_delta']['pct'])
  cover=x['coverage'];high=cover is not None and cover>D(rr['high_days'])
  # 長期無耗用：從本月逆推完整連續月份；任何正/負耗用、單位變更、缺品項即停止。
  cursor=p;days=0;target=int(D(rr['idle_days']).to_integral_value(rounding='ROUND_CEILING'));history_map=dict(history_by_code.get(x['code'],{}));history_map[p]=x
  while days<target:
   h=history_map.get(cursor)
   if not h or not h.get('valid',True) or (h['name'],h['unit'])!=(x['name'],x['unit']):break
   c=calc(h)
   if c['used']!=0 or c['qty']!=0:break
   days+=calendar.monthrange(*map(int,cursor.split('-')))[1];cursor=previous(cursor)
  x['idle_observed_days']=days;x['idle_confirmed']=days>=target and x['ending']>0
  x['idle_persistent']=days>=D(rr['idle_warn_days']) and x['ending']>0
  x['idle_level']='長期未耗用' if x['idle_confirmed'] else '持續未耗用' if x['idle_persistent'] else ''
  x['idle_reason']=f'連續完整月報確認{days}天無耗用' if days>=target else f'僅確認連續{days}天，未達{target}天或歷史／品項不足，不判定長期未耗用'
  if x['used']==0 and x['qty']==0 and x['ending']>0 and not x['idle_confirmed']:finding('品項',x['code'],x['name'],'有庫存但本月無耗用',x['ending'],f'本月觀測，持續提醒{rr["idle_warn_days"]}天、長期警示{rr["idle_days"]}天','中')
  if x['idle_persistent'] and not x['idle_confirmed']:finding('品項',x['code'],x['name'],'持續未耗用',x['ending'],x['idle_reason'],'中')
  if x['idle_confirmed']:finding('品項',x['code'],x['name'],'長期未耗用',x['ending'],x['idle_reason'])
  if high:finding('品項',x['code'],x['name'],'高庫存',cover,'期末存貨÷本月耗用×當月天數','高' if cover>D(rr['severe_days']) else '中')
  if high or x['idle_confirmed']:risk_ending+=max(x['ending'],D(0))
  ch=x['change']
  if ch['pct'] is not None and abs(ch['pct'])>=D(rr['change_pct']) and abs(ch['amount'])>=D(rr['change_amount']):finding('品項',x['code'],x['name'],'重大耗用差異',ch['amount'],','.join(base),pct=ch['pct'])
  txt=f"{p} {x['code']} {x['name']}：耗用{money(x['used'])}元，數量{number_text(x['qty'])}{x['unit']}；比較期{','.join(base)}。"+change_text('耗用',ch)+change_text('數量',x['qty_change'],x['unit'])+f"平均單位耗用成本{money(x['unit_cost'],4)}元，比較期{money(bc,4)}元。"
  txt+=f"當月平均採購價{money(x['purchase'],4)}元；進價基準{','.join(x['purchase_periods']) or '無'}，參考價{money(price,4)}元。"+change_text('進價',x['purchase_delta'])
  if x['purchase_impact'] is not None:txt+=f"同數量進貨價差估算{money(x['purchase_impact'])}元，非實際節省或損失。"
  f=x['factor'];txt+=f"與上月因素拆解：{f['reason']}。" if f.get('reason') else f"與上月比較：數量因素{money(f['quantity'])}元、單位耗用成本因素{money(f['unit_cost'])}元，合計{money(f['total'])}元。"
  if approved:txt+='可比性已由主管確認；理由：'+confirm['reason']+'。'
  txt+='建議核對領用、進貨及調整紀錄；數據線索不等於已確認原因。'
  summary('品項',x['code'],txt,[x]+matches+([old] if old and old not in matches else []),'item-v2')
 for cat in r['categories']:
  rr=rule_for(rules,cat['category']);items=[x for x in r['items'] if x['category']==cat['category']]
  cat['inventory_share']=cat['ending']/total['ending']*100 if total['ending'] and total['ending']>0 else None
  impacted=sorted(items,key=lambda x:abs(x['change']['amount']) if x['change']['amount'] is not None else D(-1),reverse=True)
  cat['top_items']=[x['code'] for x in impacted[:10]]
  ch=cat['change']
  if ch['pct'] is not None and abs(ch['pct'])>=D(rr['change_pct']) and abs(ch['amount'])>=D(rr['change_amount']):finding('分類',cat['category'],cat['category'],'分類重大耗用差異',ch['amount'],','.join(base),pct=ch['pct'])
  summary('分類',cat['category'],f"{p} {cat['category']}耗用{money(cat['used'])}元；期末存貨{money(cat['ending'])}元，占全院庫存{number_text(cat['inventory_share'])}%；週轉{number_text(cat['days'])}天。比較期{','.join(base)}。"+change_text('分類耗用',ch)+'主要差異品項：'+('、'.join(cat['top_items']) or '無')+'。請逐品項查核，分類增減可能互抵。',items+[h for h in hist if h['period'] in base and h['category']==cat['category']],'category-v2')
 total['high_inventory_amount']=risk_ending;total['high_inventory_pct']=risk_ending/total['ending']*100 if total['ending'] and total['ending']>0 else None
 ch=total['change'];rr=rule_for(rules)
 if ch['pct'] is not None and abs(ch['pct'])>=D(rr['change_pct']) and abs(ch['amount'])>=D(rr['change_amount']):finding('整體','ALL','全院','整體重大耗用差異',ch['amount'],','.join(base),pct=ch['pct'])
 total['anomaly_items']=len({x['code'] for x in r['findings'] if x['level']=='品項'})
 summary('整體','ALL',f"{p} 全院耗用{money(total['used'])}元，期末存貨{money(total['ending'])}元，平均存貨{money(total['average'])}元，週轉率{number_text(total['turnover'],4)}次，週轉{number_text(total['days'])}天；異常品項{total['anomaly_items']}項。比較期{','.join(base)}。"+change_text('耗用',ch)+f"高庫存／長期未耗用金額占比{number_text(total['high_inventory_pct'])}%。原因待確認。",r['items']+[h for h in hist if h['period'] in base],'overall-v2')
 item_map={x['code']:x for x in r['items']}
 for f in r['findings']:
  x=item_map.get(f['code']);f['impact_amount']=None if f['rule']=='耗用數量異常' else (x['ending'] if f['rule']=='高庫存' and x else None) if f['rule'].endswith('數量') or f['rule']=='高庫存' else (abs(f['value'])*D('1.05') if f['rule'].startswith('跨月') else abs(f['value']))
 r['findings'].sort(key=lambda x:(0 if x['severity']=='高' else 1,-abs(x.get('impact_amount') or 0),-abs(x.get('pct') or 0)))
 r['summaries']=summaries;r['summary']=[x['text'] for x in summaries if x['level']=='整體'];r['purchase_baseline']=purchase_baseline
 return r
