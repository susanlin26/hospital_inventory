"""耗用分析表格與Excel共用欄位、篩選、排序及列順序。"""
from decimal import Decimal as D
from functools import cmp_to_key

def threshold(x,rules):
 from .analytics import rule_for
 r=rule_for(rules,x['category']);ch=x['change']
 return bool(x.get('used',D(-1))>=0 and x.get('qty',D(-1))>=0 and ch['pct'] is not None and ch['amount'] is not None and abs(ch['pct'])>=D(r['change_pct']) and abs(ch['amount'])>=D(r['change_amount']))



def change_rate(change,baseline):
 if change['pct'] is not None:return change['pct']
 if baseline is None:return '缺少基準資料'
 if baseline==0:return '基準耗用為0'
 if baseline<0:return '基準耗用為負'
 return '缺少本月資料'


def factor_value(item,key):
 f=item['selected_factor']
 if f.get(key) is not None:return f[key]
 why=f.get('reason') or '不可比較'
 if '耗用量<0' in why:return '異常：本月或基準耗用量<0'
 if '金額為負' in why:return '耗用金額為負'
 if '不足' in why:return '缺少基準品項資料'
 if '單位' in why or '規格' in why:return '品項或單位不一致'
 return why


def inventory_inputs(reports):
 """庫存採選定基準月底金額；缺院月或同品項不補零。"""
 from .engine import calc,delta
 from collections import defaultdict
 current=defaultdict(lambda:D(0));prior=defaultdict(lambda:D(0));incomplete=set();items=[]
 for d in reports:
  historical=[r for r in d['source_rows'] if r['valid'] and r['period'] in d['baseline']]
  by_item=defaultdict(list)
  for r in historical:by_item[(r['code'],r['name'],r['unit'])].append(r)
  for x in d['items']:
   matches=by_item[(x['code'],x['name'],x['unit'])]
   baseline=sum((calc(r)['ending'] for r in matches),D(0))/len(d['baseline']) if len(matches)==len(d['baseline']) else None
   items.append(dict(x,hospital=d['hospital'],baseline_used=baseline,used=x['ending'],change=delta(x['ending'],baseline)))
  for cat in {x['category'] for x in d['items']}:
   current[cat]+=sum((x['ending'] for x in d['items'] if x['category']==cat),D(0))
 # 比較採同一組本月有月報的醫院，分類缺列亦不作零。
 for cat in current:
  for d in reports:
   if d['total']['used'] is None:incomplete.add(cat);continue
   rows=[r for r in d['source_rows'] if r['valid'] and r['category']==cat and r['period'] in d['baseline']]
   if not all(any(r['period']==bp for r in rows) for bp in d['baseline']):incomplete.add(cat)
   else:prior[cat]+=sum((calc(r)['ending'] for r in rows),D(0))/len(d['baseline'])
 total=sum(current.values(),D(0));categories=[]
 for cat,value in current.items():
  baseline=None if cat in incomplete else prior[cat]
  categories.append(dict(category=cat,used=value,baseline_used=baseline,usage_share=value/total*100 if total>0 else None,change=delta(value,baseline)))
 baseline=sum(prior.values(),D(0)) if current and not incomplete else None
 totals=dict(used=total if current else None,baseline_used=baseline,difference=total-baseline if baseline is not None else None)
 converted=[dict(d,items=[x for x in items if x['hospital']==d['hospital']]) for d in reports]
 return converted,dict(categories=categories,category_totals=totals)


def build(reports,overview,kind='category',category='',sort='difference',descending=True,limit=10,metric='consumption',exceeded=False,keyword='',value_mode='amount'):
 if metric not in ('consumption','inventory'):raise ValueError('不支援的分析指標')
 original_reports=reports
 if value_mode not in ('amount','quantity'):raise ValueError('檢視模式不正確')
 if metric=='inventory':reports,overview=inventory_inputs(reports)
 if kind=='category':
  cols=[('category','分類','text'),('used','本月耗用金額','money'),('share','占比%','number'),('baseline','基準耗用金額','money'),('difference','增減金額','money'),('pct','增減%','number')]
  values=[]
  for x in overview['categories']:
   values.append(dict(id=x['category'],category=x['category'],used=x['used'],share=x['usage_share'],baseline=x['baseline_used'],difference=x['change']['amount'],pct=change_rate(x['change'],x['baseline_used'])))
  t=overview['category_totals'];footer=['合計',t['used'],None,t['baseline_used'],t['difference'],None]
 else:
  cols=[('hospital','醫院','text'),('code','品號','text'),('name','品名','text'),('unit','單位','text'),('category','分類','text'),('used','本月耗用金額','money'),('baseline','基準耗用金額','money'),('difference','增減金額','money'),('pct','增減%','number'),('quantity_impact','耗用數量影響','money'),('cost_impact','單價變動影響','money')]
  values=[]
  for d in reports:
   for x in d['items']:
    if category and x['category']!=category:continue
    if keyword.strip() and keyword.strip().casefold() not in (x['code']+' '+x['name']).casefold():continue
    if exceeded and metric=='consumption' and not threshold(x,d['rules']):continue
    values.append(dict(id=d['hospital']+'|'+x['code'],hospital=d['hospital'],code=x['code'],name=x['name'],unit=x['unit'],category=x['category'],exceeded=threshold(x,d['rules']) if metric=='consumption' else False,used=x['used'],baseline=x['baseline_used'],difference=x['change']['amount'],pct=change_rate(x['change'],x['baseline_used']),quantity_impact=factor_value(x,'quantity') if metric=='consumption' else None,cost_impact=factor_value(x,'unit_cost') if metric=='consumption' else None))
  footer=None
 if metric=='inventory':
  cols=[(k,{'used':'本月庫存金額','baseline':'基準庫存金額'}.get(k,label),typ) for k,label,typ in cols if k not in ('quantity_impact','cost_impact')]
  for x in values:
   if isinstance(x.get('pct'),str):x['pct']=x['pct'].replace('耗用','庫存')
 from .labels import baseline_label
 base_label=baseline_label(reports[0]['period'],reports[0]['baseline']) if reports and reports[0].get('period') and reports[0].get('baseline') else '基準'
 cols=[(k,base_label+('庫存金額' if metric=='inventory' else '耗用金額') if k=='baseline' else label,typ) for k,label,typ in cols]
 if kind=='item' and value_mode=='quantity':
  from .engine import calc,delta
  lookup={}
  for d in original_reports:
   for x in d['items']:
    history=[v for v in d['source_rows'] if v.get('valid') and v['period'] in d['baseline'] and (v['code'],v['name'],v['unit'])==(x['code'],x['name'],x['unit'])]
    valid=len(history)==len(d['baseline']) and len({v['period'] for v in history})==len(d['baseline']) and bool(history)
    base=sum((D(str(v['end_q'])) if metric=='inventory' else calc(v)['qty'] for v in history),D(0))/len(d['baseline']) if valid else None
    current=next((D(str(v['end_q'])) for v in d['source_rows'] if v.get('valid') and v['period']==d['period'] and (v['code'],v['name'],v['unit'])==(x['code'],x['name'],x['unit'])),None) if metric=='inventory' else x['qty']
    lookup[d['hospital']+'|'+x['code']]=(current,base)
  for v in values:
   current,base=lookup[v['id']];ch=delta(current,base);v.update(used=current,baseline=base,difference=ch['amount'],pct=ch['pct'])
  noun='庫存數量' if metric=='inventory' else '耗用數量'
  cols=[(k,{'used':'本期'+noun,'baseline':base_label+noun,'difference':'增減數量','pct':'增減率'}.get(k,l),'number' if k in ('used','baseline','difference','pct') else t) for k,l,t in cols if k not in ('quantity_impact','cost_impact')]
 keys={k:typ for k,_,typ in cols}
 if sort not in keys:raise ValueError('不支援的排序欄位')
 def compare(a,b):
  av,bv=a[sort],b[sort];numeric=keys[sort]!='text'
  ai=av is None or numeric and not isinstance(av,(D,int,float));bi=bv is None or numeric and not isinstance(bv,(D,int,float))
  if ai!=bi:return 1 if ai else -1
  if ai and bi:return (a['id']>b['id'])-(a['id']<b['id'])
  result=(av>bv)-(av<bv)
  if result:return -result if descending else result
  return (a['id']>b['id'])-(a['id']<b['id'])
 values.sort(key=cmp_to_key(compare));count=len(values)
 if kind=='item' and limit:values=values[:limit]
 return dict(kind=kind,columns=[dict(key=k,label=label,type=typ) for k,label,typ in cols],rows=[dict(id=x['id'],hospital=x.get('hospital'),code=x.get('code'),category=x['category'],exceeded=x.get('exceeded',False),cells=[x[k] for k,_,_ in cols]) for x in values],footer=footer,matched_count=count,displayed_count=len(values),sort=sort,descending=descending,limit=limit)


def bundle(reports,overview,metric='consumption'):
 """一次建立兩張完整表，排序與篩選使用同一載入快照。"""
 return {**{kind:build(reports,overview,kind=kind,sort='difference',descending=True,limit=0,metric=metric) for kind in ('category','item')},'item_quantity':build(reports,overview,kind='item',sort='difference',descending=True,limit=0,metric=metric,value_mode='quantity')}
