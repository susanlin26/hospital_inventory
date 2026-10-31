"""跨院同月比較與各院自身變化，共用未取整Decimal結果。沒有名稱推測或採購價格比較。"""
import calendar,hashlib,json
from decimal import Decimal as D,ROUND_HALF_UP
from functools import cmp_to_key
from . import engine
from .formatting import money

KEYS={'used':('耗用金額','元'),'standard30':('每床月均耗用（標準30日）','元／床／30日'),'ending':('期末庫存金額','元'),'days':('存貨週轉天數','天'),'quantity_day':('每住院人日耗用數量','數量／人日'),'usage_pct':('耗用金額較自身基準增減%','%')}

def one(v):return format(v.quantize(D('0.1'),rounding=ROUND_HALF_UP),',.1f')

def item_identity(x):
 raw=x.get('raw') or {};spec=str(x.get('specification') or raw.get('規格') or raw.get('specification') or x.get('source_name') or x['name'])
 body=[x['code'],x.get('source_name') or x['name'],spec,x['unit']]
 return hashlib.sha256(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def state(d,p,category=None):
 cache=d.get('_cross_states')
 if cache is None:return raw_state(d,p,category)
 key=(p,category)
 if key not in cache:cache[key]=raw_state(d,p,category)
 return cache[key]

def raw_state(d,p,category=None):
 allrows=[r for r in d['source_rows'] if r['period']==p];valid=[r for r in allrows if r.get('valid',True)];selected=[r for r in valid if not category or r['category']==category];invalid=[r for r in allrows if not r.get('valid',True) and (not category or r['category']==category)]
 point=next((x for x in d['trend'] if x['period']==p),{})
 if p==d['period']:point=d['total']
 exists=bool(allrows);complete=exists and bool(valid) and not invalid
 values=engine.metrics(selected)
 absent=bool(category and not selected and complete)
 if absent:complete=False
 reason=f'{d["hospital"]} {p} 月報未列此分類，無法確認為零' if absent else '' if complete else f'{d["hospital"]} {p} 缺少月報' if not exists else f'{d["hospital"]} {p} 含隔離／無效資料，僅顯示有效列，不作完整排名'
 pd=point.get('patient_days');eligible=bool(complete and not any(not r.get('valid',True) for r in allrows) and point.get('comparison_eligible') and pd and pd>0 and values['used'] is not None and values['used']>=0)
 sr='' if eligible else f'{d["hospital"]} {p} '+('耗用為負值，標準30日每床耗用不適用' if values['used'] is not None and values['used']<0 else '月報含隔離列，耗用範圍未完整' if any(not r.get('valid',True) for r in allrows) else reason or point.get('daily_status') or '缺少同範圍有效床數／住院人日')
 standard=values['used']/pd*30 if eligible else None
 used,avg,ending=values['used'],values['average'],values['ending'];days=D(calendar.monthrange(*map(int,p.split('-')))[1])*avg/used if complete and used is not None and used>0 and avg is not None and avg>0 and ending>=0 else None
 dr='' if days is not None else reason or ('本期無耗用，週轉天數不適用' if used==0 else '耗用為負值，週轉天數不適用' if used is not None and used<0 else '平均庫存不大於零或庫存無效，週轉天數不適用')
 signature=tuple(sorted({str(r.get('filename_department') or '') for r in allrows}))
 return dict(period=p,**{k:values[k] for k in ('used','opening','ending','average')},standard30=standard,days=days,patient_days=pd,patient_days_raw=point.get('patient_days_raw'),scope=point.get('care_scope'),scope_name=point.get('care_scope_name','未標示'),signature=signature,complete=complete,reason=reason,standard_reason=sr,days_reason=dr,rows=selected,zero_proven=bool(selected) and complete and values['used']==0)

def compare_value(current,prior,key):
 value=current.get(key);base=prior.get(key);reason=(current.get('quantity_reason') or current['standard_reason']) if key=='quantity_day' else current['standard_reason'] if key=='standard30' else current['days_reason'] if key=='days' else current['reason']
 br=(prior.get('quantity_reason') or prior['standard_reason']) if key=='quantity_day' else prior['standard_reason'] if key=='standard30' else prior['days_reason'] if key=='days' else prior['reason']
 same=current['signature']==prior['signature'] and (key not in ('standard30','quantity_day') or current['scope']==prior['scope'])
 if not current['complete'] or not prior['complete'] or not same:
  br=br or ('本期與基準月報／照護範圍不同' if not same else current['reason']);base=None
 ch=engine.delta(value,base);rate_reason='' if ch['pct'] is not None else '基準為零' if base==0 else '基準為負值' if base is not None and base<0 else br or '缺少基準資料'
 return dict(value=value,baseline=base,difference=ch['amount'],pct=ch['pct'],rate_reason=rate_reason,reason=reason,baseline_reason=br,period=current['period'],baseline_period=prior['period'])

def cohort(entries,key):
 valid=[x for x in entries if x['current'].get(key) is not None and x['current']['complete']]
 scopes={x['current']['scope'] if key=='standard30' else x['current']['signature'] for x in valid}
 compatible=len(scopes)==1
 included=valid if compatible and len(valid)>=2 else []
 included.sort(key=lambda x:(-x['current'][key],x['hospital']))
 excluded=[dict(hospital=x['hospital'],reason=(x['metrics'][key]['reason'] or ('各院照護／月報範圍不同，不提供跨院排序' if not compatible else '至少需兩院有有效且同範圍資料'))) for x in entries if x not in included]
 return dict(hospitals=[x['hospital'] for x in included],rows=[dict(hospital=x['hospital'],name=x['name'],**x['metrics'][key],scope=x['current']['scope_name']) for x in included],excluded=excluded,note='同月同範圍數值比較；未調整病人組成與照護需求，不代表管理績效。')


def category_turnover(d,p,category):
 """Only turnover-applicable codes contribute; other category metrics keep full totals."""
 point=state(d,p,category);report_state=state(d,p);grouped={}
 for row in point['rows']:grouped.setdefault(row['code'],[]).append(row)
 used=D(0);average=D(0);included=[];excluded=[]
 for code,rows in grouped.items():
  v=engine.metrics(rows)
  if report_state['complete'] and v['used'] is not None and v['used']>0 and v['average'] is not None and v['average']>0:
   included.append(code);used+=v['used'];average+=v['average']
  else:excluded.append(code)
 days=D(calendar.monthrange(*map(int,p.split('-')))[1])*average/used if point['complete'] and included else None
 why=(point['reason'] or report_state['reason'] or ('本期無耗用' if point['used']==0 else '不適用')) if days is None else ''
 point.update(days=days,days_reason=why,turnover_used=used if included else None,turnover_average=average if included else None,turnover_codes=included,turnover_excluded=excluded,turnover_note='僅納入可計算品項：期間天數×適用平均庫存合計÷適用耗用合計；排除不適用品項，不平均各品項天數')
 return point

def compact_point(p):return {k:v for k,v in p.items() if k!='rows'}

def build(reports,names,category_order,category=None):
 entries=[];categories=[];base=reports[0]['baseline'][0] if reports else '';label='去年同期' if reports and int(reports[0]['period'][:4])-int(base[:4])==1 and reports[0]['period'][5:]==base[5:] else '上月'
 allcats=list(dict.fromkeys([*category_order,*[x['category'] for d in reports for x in d['source_rows'] if x.get('valid',True)]]))
 if category:allcats=[category]
 for d in reports:
  current=state(d,d['period'],category);prior=state(d,base,category)
  entries.append(dict(hospital=d['hospital'],name=names.get(d['hospital'],d['hospital']),current=compact_point(current),prior=compact_point(prior),metrics={k:compare_value(current,prior,k) for k in ('used','standard30','ending','days')}))
 for cat in allcats:
  cells={}
  for d in reports:
   cur=category_turnover(d,d['period'],cat);old=category_turnover(d,base,cat)
   cells[d['hospital']]=dict(metrics={k:compare_value(cur,old,k) for k in ('used','standard30','ending','days')},scope=cur['scope'],signature=cur['signature'],complete=cur['complete'],zero_proven=cur['zero_proven'],turnover={k:cur[k] for k in ('turnover_used','turnover_average','turnover_codes','turnover_excluded','turnover_note')})
  categories.append(dict(category=cat,cells=cells))
 charts={k:cohort(entries,k) for k in ('standard30','days')}
 def chosen(key):
  ranked=charts[key]['rows']
  if ranked:return next(e for e in entries if e['hospital']==ranked[0]['hospital']),True
  candidates=[e for e in entries if e['metrics'][key]['value'] is not None]
  if not candidates and key=='standard30':candidates=[e for e in entries if e['metrics']['used']['value'] is not None]
  if not candidates:return None,False
  return max(candidates,key=lambda e:abs(e['metrics'][key if e['metrics'][key]['difference'] is not None else 'used']['difference'] or D(0))),False
 def change(m,unit):
  if m['difference'] is None:return '自身'+label+'無法比較：'+(m['baseline_reason'] or m['rate_reason'])
  diff=m['difference'];word='增加' if diff>0 else '減少' if diff<0 else '持平';value=money(abs(diff)) if unit!='天' else one(abs(diff))
  if unit=='天':word='延長' if diff>0 else '縮短' if diff<0 else '持平'
  return '較自身'+label+word+(value+unit if diff else '')+('（'+one(m['pct'])+'%）' if unit!='天' and m['pct'] is not None else '；'+m['rate_reason'] if unit!='天' else '')
 def concentration(entry,key):
  diff=entry['metrics'][key]['difference']
  if diff is None:return ''
  rows=[(c['category'],c['cells'][entry['hospital']]['metrics'][key]['difference']) for c in categories]
  same=[(c,v) for c,v in rows if v is not None and (v>0 if diff>0 else v<0 if diff<0 else v!=0)]
  same.sort(key=lambda x:-abs(x[1]));return '；'+('耗用金額' if key=='used' else '期末庫存')+'主要'+('增額' if diff>0 else '減額' if diff<0 else '分類增減')+'集中於'+('、'.join(c for c,_ in same[:2])) if same else ''
 e,rank=chosen('standard30');paragraphs=[]
 if e:
  key='standard30' if e['metrics']['standard30']['value'] is not None else 'used';m=e['metrics'][key];paragraphs.append('耗用差異：'+e['name']+KEYS[key][0]+money(m['value'])+'元'+('，在本次可比較院別中最高' if rank else '；跨院每床排序受資料／範圍限制')+'，'+change(m,'元')+concentration(e,'used')+'。')
 else:paragraphs.append('耗用差異：目前缺少有效月報，無法比較；缺漏不補零。')
 e2,rank=chosen('days')
 if e2:
  m=e2['metrics']['days'];paragraphs.append('庫存差異：'+e2['name']+'存貨週轉天數'+one(m['value'])+'天'+('，在本次可比較院別中最長' if rank else '；跨院週轉排序受資料／範圍限制')+'，'+change(m,'天')+concentration(e2,'ending')+'。')
 else:
  valid=[e for e in entries if e['metrics']['ending']['value'] is not None];e2=valid[0] if valid else None
  paragraphs.append('庫存差異：'+(e2['name']+'期末庫存'+money(e2['metrics']['ending']['value'])+'元，'+change(e2['metrics']['ending'],'元')+'；'+e2['metrics']['days']['reason'] if e2 else '缺少有效庫存資料')+'。')
 concerns=[]
 from .analytics import rule_for
 for d in reports:
  entry=next(e for e in entries if e['hospital']==d['hospital'])
  for cat in categories:
   rr=rule_for(d['rules'],cat['category']);m=cat['cells'][d['hospital']]['metrics']['used']
   if m['pct'] is not None and m['difference'] is not None and abs(m['pct'])>=D(rr['change_pct']) and abs(m['difference'])>=D(rr['change_amount']):concerns.append(entry['name']+'「'+cat['category']+'」耗用'+('增加' if m['difference']>0 else '減少'))
  risks=[x for x in d['items'] if (not category or x['category']==category) and x.get('risk_state') in ('高庫存低週轉','低庫存風險','無耗用但有庫存')]
  if risks:concerns.append(entry['name']+'「'+risks[0]['category']+'」庫存品項')
 paragraphs.append('關注方向：建議優先核對'+('、'.join(dict.fromkeys(concerns[:3])))+'的數量、進貨及異動紀錄，原因待確認。' if concerns else '關注方向：目前有效資料未見達已設定門檻的明顯提醒，持續觀察；缺漏資料請先補齊，不強行要求改善。')
 return dict(period=reports[0]['period'] if reports else '',baseline_period=base,baseline_label=label,category=category,category_options=allcats if not category else list(dict.fromkeys([*category_order,*[x['category'] for d in reports for x in d['items']]])),entries=entries,categories=categories,charts=charts,paragraphs=paragraphs,notes=['同月跨院差異與較自身基準變化分開，金額高低不代表績效。','每床耗用需耗用與人日範圍相符；病人組成、照護結構差異未校正。分類沿用各期既有主檔快照，分類組成變動須另行核對。'],item_detail=None)

def item_point(d,p,members,category=None):
 full=state(d,p);indexed=d.get('_cross_members');rows=([r for ident in members for r in indexed.get((p,ident),[]) if not category or r['category']==category] if indexed is not None else [r for r in full['rows'] if item_identity(r) in members and (not category or r['category']==category)])
 if not rows:
  return dict(full,used=None,ending=None,average=None,opening=None,standard30=None,days=None,quantity=None,quantity_day=None,complete=False,reason=f'{d["hospital"]} {p} 無已確認對應品項列，不能推定為零',standard_reason=f'{d["hospital"]} {p} 無已確認對應品項列',days_reason=f'{d["hospital"]} {p} 無已確認對應品項列',codes=[],units=[])
 values=engine.metrics(rows);quantity=sum((engine.calc(r)['qty'] for r in rows),D(0)) if len({r['unit'] for r in rows})==1 else None;pd=full['patient_days'];standard=values['used']/pd*30 if full['standard30'] is not None and values['used']>=0 else None;days=D(calendar.monthrange(*map(int,p.split('-')))[1])*values['average']/values['used'] if full['complete'] and values['used']>0 and values['average']>0 else None
 return dict(full,**{k:values[k] for k in ('used','opening','ending','average')},standard30=standard,days=days,quantity=quantity,quantity_day=quantity/pd if quantity is not None and quantity>=0 and standard is not None else None,quantity_reason='同院對應品項單位不同，不能相加數量' if quantity is None else '淨耗用數量為負，不能比較每人日耗用數量' if quantity<0 else full['standard_reason'],standard_reason='品項耗用為負值，不能計算標準30日每床耗用' if values['used']<0 else full['standard_reason'],days_reason='' if days is not None else '本期無耗用，週轉天數不適用' if values['used']==0 else '負耗用或平均庫存不大於零，週轉天數不適用',codes=sorted({r['code'] for r in rows}),units=sorted({r['unit'] for r in rows}))

def item_detail(reports,groups,members,category,statuses):
 base=reports[0]['baseline'][0];hospitals=[d['hospital'] for d in reports];groupmap={g['id']:g for g in groups};lookup={(m['hospital'],m['identity']):m['group_id'] for m in members};selected={};unmapped=[];seen_items=set()
 for d in reports:
  for x in d['items']:
   if x['category']!=category:continue
   ident=item_identity(x)
   if (d['hospital'],ident) in seen_items:continue
   seen_items.add((d['hospital'],ident));gid=lookup.get((d['hospital'],ident));record=dict(hospital=d['hospital'],identity=ident,code=x['code'],name=x.get('source_name') or x['name'],specification=(x.get('raw') or {}).get('規格') or x.get('source_name') or x['name'],unit=x['unit'],category=category)
   if gid is None:
    cp=item_point(d,d['period'],{ident});bp=item_point(d,base,{ident});unmapped.append(dict(**record,metrics={k:compare_value(cp,bp,k) for k in ('used','standard30','ending','days','quantity_day')},quantity=cp['quantity'],baseline_quantity=bp['quantity'],statuses=statuses.get((d['hospital'],x['code'],x['name'],x['unit']),[]),risks=risks_for(x)))
   else:selected.setdefault(gid,[]).append(record)
 rows=[]
 for gid,records in selected.items():
  group=groupmap[gid];cells={};units={m.get('body',{}).get('unit') for m in members if m['group_id']==gid and m.get('body',{}).get('unit')}
  for d in reports:
   ids={m['identity'] for m in members if m['group_id']==gid and m['hospital']==d['hospital']};cp=item_point(d,d['period'],ids);bp=item_point(d,base,ids);units.update(cp['units'])
   # A mapping to another category is not silently included in this category matrix.
   wrong=[r for r in cp['rows'] if item_identity(r) in ids and r['category']!=category]
   if wrong:cp.update(complete=False,reason='已對應品項跨院中分類不一致，請先核對分類',standard_reason='已對應品項中分類不一致',days_reason='已對應品項中分類不一致')
   metrics={k:compare_value(cp,bp,k) for k in ('used','standard30','ending','days','quantity_day')};metrics['usage_pct']=dict(metrics['used'],value=metrics['used']['pct'],baseline=None,difference=None,reason=metrics['used']['rate_reason'])
   xitems=[x for x in d['items'] if item_identity(x) in ids];cells[d['hospital']]=dict(metrics=metrics,codes=cp['codes'],units=cp['units'],quantity=cp['quantity'],baseline_quantity=bp['quantity'],used=cp['used'],baseline_used=bp['used'],difference=metrics['used']['difference'],scope=cp['scope'],signature=cp['signature'],statuses=list({s['observation_id']:s for x in xitems for s in statuses.get((d['hospital'],x['code'],x['name'],x['unit']),[])}.values()),risks=list(dict.fromkeys(r for x in xitems for r in risks_for(x))),complete=cp['complete'])
  quantity_comparable=len(units)==1
  if not quantity_comparable:
   for cell in cells.values():cell['metrics']['quantity_day']=dict(value=None,baseline=None,difference=None,pct=None,reason='計量單位不同，尚無可靠換算關係，不比較數量',baseline_reason='',rate_reason='計量單位不同')
  rows.append(dict(id=gid,name=group['name'],specification=group['specification'],unit='／'.join(sorted(units)),mapping_version=gid,mapping_at=group['created_at'],quantity_comparable=quantity_comparable,cells=cells))
 return dict(category=category,rows=rows,unmapped=unmapped,note='僅使用管理員已確認的品號、規格及單位對應；名稱相似、同品號或分類相同不自動合併。不同單位沒有換算關係時，數量不比較。')

def risks_for(x):
 return [{'高庫存低週轉':'高庫存低耗用','無耗用但有庫存':'無耗用仍有庫存'}.get(x['risk_state'],x['risk_state'])] if x.get('risk_state') not in (None,'一般／資料不足') else []

def category_gap(row,key):
 cells=list(row['cells'].values())
 if any(not c['complete'] or c['metrics'][key]['value'] is None for c in cells):return None
 signatures={json.dumps(c['scope'] if key=='standard30' else c['signature']) for c in cells}
 if len(signatures)!=1:return None
 values=[c['metrics'][key]['value'] for c in cells];return max(values)-min(values)


def sort_categories(rows,key,hospital='',descending=True):
 if not hospital:return rows
 if hospital=='category':return sorted(rows,key=lambda r:r['category'],reverse=descending)
 def value(r):return category_gap(r,key) if hospital=='__gap__' else r['cells'][hospital]['metrics'][key]['value']
 return sorted(rows,key=lambda r:(value(r) is None,(-value(r) if descending else value(r)) if value(r) is not None else D(0)))


def code_item_point(d,p,ids,code,category=None):
 point=item_point(d,p,ids,category)
 return point


def code_item_detail(reports,category,statuses):
 """User-approved same-code view; money comparable, units never silently converted."""
 from collections import defaultdict
 indexed=[]
 for original in reports:
  d=dict(original,_cross_states={},_cross_members=defaultdict(list),_cross_candidates=defaultdict(list),_cross_items=defaultdict(list),_cross_codes=set())
  for row in d['source_rows']:
   d['_cross_codes'].add((row['period'],row['code']))
   if row.get('valid',True):
    d['_cross_members'][(row['period'],item_identity(row))].append(row)
    if not category or row['category']==category:d['_cross_candidates'][row['code']].append(row)
  for x in d['items']:d['_cross_items'][x['code']].append(x)
  indexed.append(d)
 reports=indexed
 base=reports[0]['baseline'][0];codes=set()
 for d in reports:
  codes.update(r['code'] for r in d['source_rows'] if r['period'] in (d['period'],base) and r.get('valid',True) and (not category or r['category']==category))
 rows=[]
 for code in sorted(codes):
  cells={};allunits=set();allnames=set();allspecs=set()
  for d in reports:
   candidates=[r for r in d['_cross_candidates'].get(code,[]) if r['period'] in (d['period'],base)]
   ids={item_identity(r) for r in candidates};cp=code_item_point(d,d['period'],ids,code,category);bp=code_item_point(d,base,ids,code,category)
   for point in (cp,bp):
    if not point['codes'] and not point.get('inferred_zero'):
     point.update(reason=f'{d["hospital"]} {point["period"]} 月報未列此品號，不能推定為零',standard_reason=f'{d["hospital"]} {point["period"]} 月報未列此品號',days_reason=f'{d["hospital"]} {point["period"]} 月報未列此品號')
   units=set(cp['units'])|set(bp['units']);allunits.update(units)
   metrics={k:compare_value(cp,bp,k) for k in ('used','standard30','ending','days','quantity_day')};metrics['usage_pct']=dict(metrics['used'],value=metrics['used']['pct'],baseline=None,difference=None,reason=metrics['used']['rate_reason'])
   current=[r for r in candidates if r['period']==d['period']];names=sorted({r.get('source_name') or r['name'] for r in current or candidates});specs=sorted({str(r.get('specification') or (r.get('raw') or {}).get('規格') or r.get('source_name') or r['name']) for r in current or candidates});allnames.update(names);allspecs.update(specs)
   xitems=[x for x in d['_cross_items'].get(code,[]) if item_identity(x) in ids]
   cells[d['hospital']]=dict(metrics=metrics,codes=cp['codes'],units=cp['units'],baseline_units=bp['units'],names=names,specifications=specs,category=next((r['category'] for r in current),category or ''),quantity=cp['quantity'],baseline_quantity=bp['quantity'],inferred_zero=bool(cp.get('inferred_zero')),baseline_inferred_zero=bool(bp.get('inferred_zero')),used=cp['used'],baseline_used=bp['used'],difference=metrics['used']['difference'],scope=cp['scope'],signature=cp['signature'],statuses=list({s['observation_id']:s for x in xitems for s in statuses.get((d['hospital'],x['code'],x['name'],x['unit']),[])}.values()),risks=list(dict.fromkeys(r for x in xitems for r in risks_for(x))),complete=cp['complete'])
  comparable=len(allunits)==1
  if not comparable:
   for cell in cells.values():cell['metrics']['quantity_day']=dict(value=None,baseline=None,difference=None,pct=None,reason='本期／基準或跨院計量單位不同，不比較耗用數量',baseline_reason='',rate_reason='計量單位不同')
  rows.append(dict(id=code,code=code,item_name='／'.join(sorted(allnames)),name=code+'／'+'／'.join(sorted(allnames)),specification='／'.join(sorted(allspecs)),unit='／'.join(sorted(allunits)),quantity_comparable=comparable,cells=cells))
 return dict(category=category,rows=rows,unmapped=[],note='未提供資料與不適用指標以「—」呈現。')
