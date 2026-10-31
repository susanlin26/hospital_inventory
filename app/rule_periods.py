"""Effective intervals; soft deletion preserves historical snapshots and references."""
from copy import deepcopy
from fastapi import HTTPException
from psycopg.types.json import Jsonb
from . import engine,db

def selected(c,h,p):
 rows=c.execute("SELECT id,body FROM rule_versions WHERE hospital=%s AND disabled_at IS NULL AND coalesce(body->>'effective_from','0001-01')<=%s ORDER BY coalesce(body->>'effective_from','0001-01') DESC,id DESC",(h,p)).fetchall()
 rows=[x for x in rows if not x['body'].get('effective_until') or p<=x['body']['effective_until']]
 default_row=next((x for x in rows if x['body'].get('_system_default')),None)
 global_row=next((x for x in rows if not x['body'].get('_category') and not x['body'].get('_system_default')),None)
 active=lambda x:not x['body'].get('effective_until') or p<=x['body']['effective_until']
 body=deepcopy(global_row['body']) if global_row and active(global_row) else deepcopy(default_row['body']) if default_row else dict(engine.DEFAULT_RULES,categories={})
 seen=set()
 for x in rows:
  cat=x['body'].get('_category')
  if not cat or cat in seen:continue
  seen.add(cat)
  if active(x):body.setdefault('categories',{})[cat]={k:v for k,v in x['body'].items() if k in engine.DEFAULT_RULES}
  else:body.setdefault('categories',{}).pop(cat,None)
 chosen=next((x for x in rows if not x['body'].get('_system_default')),default_row)
 return dict(id=chosen['id'],body=body) if chosen else None

def prepare_period(c,h,category,start,end,rules,u,overwrite=False):
 from .engine import previous
 rows=c.execute("SELECT id,body FROM rule_versions WHERE hospital=%s AND disabled_at IS NULL AND coalesce(body->>'_category','')=%s AND coalesce(body->>'_system_default','false')<>'true' ORDER BY id FOR UPDATE",(h,category)).fetchall()
 for row in rows:
  b=row['body'];a=b.get('effective_from','0001-01');z=b.get('effective_until')
  if (end and a>end) or (z and z<start):continue
  if not overwrite:raise HTTPException(409,'生效期間重疊，是否覆蓋目前門檻？')
  if a<start:
   # A new start truncates the previous interval, with immutable audit evidence.
   new={**b,'effective_until':previous(start)};c.execute('UPDATE rule_versions SET body=%s WHERE id=%s',(Jsonb(new),row['id']));db.audit(c,u['id'],'rule_period_end',h,row['id'],dict(before=b,after=new))
  else:
   c.execute('UPDATE rule_versions SET disabled_at=now() WHERE id=%s',(row['id'],));db.audit(c,u['id'],'rule_period_overwrite',h,row['id'],dict(before=b))
  if end and (not z or z>end):
   from datetime import date
   year,month=map(int,end.split('-'));after=f'{year+1:04}-01' if month==12 else f'{year:04}-{month+1:02}'
   tail={**b,'effective_from':after}
   c.execute('INSERT INTO rule_versions(hospital,body,operator) VALUES(%s,%s,%s)',(h,Jsonb(tail),u['id']))
 result={**rules,'effective_from':start,'effective_until':end}
 if category:result={k:v for k,v in rules['categories'][category].items() if k in engine.DEFAULT_RULES};result.update(_category=category,effective_from=start,effective_until=end);result['categories']={category:{k:v for k,v in result.items() if k in engine.DEFAULT_RULES}}
 return result

def initialize_defaults(c,hospital=None):
 """Seed a fallback version from the first known report; never overwrite custom rules."""
 rows=c.execute("SELECT hospital,min(period) first_period FROM batches WHERE deleted_at IS NULL AND (%s::text IS NULL OR hospital=%s) GROUP BY hospital ORDER BY hospital",(hospital,hospital)).fetchall()
 if rows:c.execute("SELECT token FROM performance_state WHERE key='financial' FOR UPDATE")
 for row in rows:
  h,start=row['hospital'],row['first_period'];db.write_lock(c)
  c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(h+':rule-defaults',))
  if c.execute("SELECT 1 FROM rule_versions WHERE hospital=%s AND disabled_at IS NULL AND body->>'_system_default'='true' AND body->>'effective_from'<=%s",(h,start)).fetchone():continue
  body={**engine.DEFAULT_RULES,'categories':{},'effective_from':start,'effective_until':None,'_system_default':True}
  rid=c.execute('INSERT INTO rule_versions(hospital,body,operator) VALUES(%s,%s,NULL) RETURNING id',(h,Jsonb(body))).fetchone()['id']
  db.audit(c,None,'rule_defaults_initialized',h,rid,body)
