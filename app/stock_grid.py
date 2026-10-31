"""存貨三類風險清單與Excel共用來源、篩選及原精度排序。"""
from decimal import Decimal as D
from functools import cmp_to_key

COLUMNS=[('hospital','醫院','text'),('code','品號','text'),('displayName','品項','text'),('ending','期末庫存','money'),('days','週轉天數','number'),('low_stock_days','推估庫存可用天數','number')]
TITLES={'high':'高庫存低耗用','low':'低庫存風險','idle':'無耗用仍有庫存','insufficient':'資料不足及其他品項'}


def items(reports,kind):
 if kind not in TITLES:raise ValueError('不支援的庫存清單')
 result=[]
 for report in reports:
  for x in report['items']:
   if 'qty' in x and (x['used']<0 or x['qty']<0 or x.get('opening',D(0))<0 or x['ending']<0 or ((x['used']==0)!=(x['qty']==0))):continue
   selected=(x['risk_state']=='高庫存低週轉' if kind=='high' else x['low_stock_days'] is not None and x['low_stock_days']<D(str(x['low_days_threshold'])) if kind=='low' else x['used']==0 and x.get('qty',D(0))==0 and x['ending']>0 if kind=='idle' else x['low_stock_days'] is None)
   if kind in ('high','low','idle') and x.get('inventory_flags'):selected=x['inventory_flags'][kind]
   if selected:result.append(dict(hospital=report['hospital'],code=x['code'],name=x['name'],displayName=x['name'],ending=x['ending'],days=x['days'],low_stock_days=x['low_stock_days'],used=x['used'],inventory_flags=x.get('inventory_flags',{}),marker=('長期未耗用' if x.get('inventory_flags',{}).get('long_term') else '持續未耗用' if x.get('inventory_flags',{}).get('persistent') else x.get('inventory_flags',{}).get('severity',''))))
 return result


def cells(x):
 return [x['hospital'],x['code'],x['displayName']+('｜'+x['marker'] if x.get('marker') else ''),x['ending'],'本期無耗用，週轉天數不適用' if x['used']==0 and x['ending']>0 else x['days'] if x['days'] is not None else '資料不足',x['low_stock_days'] if x['low_stock_days'] is not None else '歷史耗用不足／不適用']


def build(reports,kind,sort='ending',descending=True):
 cols={k:typ for k,_,typ in COLUMNS}
 if sort not in cols:raise ValueError('不支援的庫存排序欄位')
 rows=items(reports,kind)
 def compare(a,b):
  av,bv=a[sort],b[sort];numeric=cols[sort]!='text';ai=av is None or numeric and not isinstance(av,(D,int,float));bi=bv is None or numeric and not isinstance(bv,(D,int,float))
  if ai!=bi:return 1 if ai else -1
  if not (ai and bi):
   n=(av>bv)-(av<bv)
   if n:return -n if descending else n
  ak,bk=a['hospital']+'|'+a['code'],b['hospital']+'|'+b['code'];return (ak>bk)-(ak<bk)
 rows.sort(key=cmp_to_key(compare))
 return dict(kind=kind,title=TITLES[kind],columns=[dict(key=k,label=label,type=typ) for k,label,typ in COLUMNS],items=rows,rows=[cells(x) for x in rows],count=len(rows),sort=sort,descending=descending)


def bundle(reports):
 return {kind:build(reports,kind,sort='low_stock_days' if kind=='low' else 'ending',descending=kind!='low') for kind in TITLES}
