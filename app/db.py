from contextlib import contextmanager
import json, os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .performance import span,timed,request_stats

class TimedConnection(psycopg.Connection):
 def execute(self,*args,**kwargs):
  stats=request_stats.get()
  if stats is not None:stats['queries']=stats.get('queries',0)+1
  with span('sql'):return super().execute(*args,**kwargs)

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('INVENTORY_DATA',ROOT/'data')).resolve()

def settings():
 path=Path(os.environ.get('INVENTORY_CONFIG',ROOT/'config.json'))
 conf=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
 from . import cloud
 if cloud.enabled():
  conf.update(allowed_hosts=['127.0.0.1' if cloud.netlify_only() else os.environ.get('RENDER_EXTERNAL_HOSTNAME','')],environment=os.environ.get('INVENTORY_ENVIRONMENT','雲端測試環境'),ollama_model='',test_bulk_delete=False)
 return conf

def dsn():
 value=os.environ.get('DATABASE_URL') or settings().get('database_url')
 if not value:raise RuntimeError('尚未設定資料庫，請先執行安裝工具')
 return value

@contextmanager
def connect():
 with span('db_connect'):
  c=TimedConnection.connect(dsn(),row_factory=dict_row,connect_timeout=8,sslmode=os.environ.get('DATABASE_SSLMODE','verify-full' if os.environ.get('INVENTORY_NETLIFY_ONLY','').lower()=='true' else 'require' if os.environ.get('INVENTORY_CLOUD','').lower()=='true' else 'prefer'))
 with c:
  c.execute("SET TIME ZONE 'Asia/Taipei'")
  c.execute("SET statement_timeout = '30s'")
  yield c

def init():
 DATA.mkdir(parents=True,exist_ok=True)
 with connect() as c:
  c.execute('SELECT pg_advisory_xact_lock(7414003)')
  c.execute((ROOT/'app/schema.sql').read_text(encoding='utf-8'))
  for code in ['SM','DE','SN','ZK']:c.execute('INSERT INTO hospitals(code,name) VALUES(%s,%s) ON CONFLICT DO NOTHING',(code,code+'院'))

def audit(c,uid,action,hospital=None,target=None,detail=None):
 c.execute('INSERT INTO audit(user_id,action,hospital,target,detail) VALUES(%s,%s,%s,%s,%s)',(uid,action,hospital,str(target) if target else None,Jsonb(detail or {})))

def write_lock(c):
 # 備份取得獨佔同一把鎖；正常寫入共用鎖，避免備份與寫入交錯。
 c.execute('SELECT pg_advisory_xact_lock_shared(7414001)')

def scope_lock(c,hospital,p):
 c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(hospital+':'+p,))

def check_open(c,hospital,p):
 from fastapi import HTTPException
 if c.execute('SELECT 1 FROM period_closes WHERE hospital=%s AND period=%s AND closed',(hospital,p)).fetchone():raise HTTPException(409,'此院月份已關帳，請主管解鎖後處理')

@timed('source_read')
def rows(c,hospital,through=None):
 # Historical purchases and long-idle checks need all prior rows; never load future rows for a report.
 from .performance import source_revision,source_rows
 revision=source_revision(c);cache=getattr(c,'_source_history',None)
 if cache is None:cache={};c._source_history=cache
 old=cache.get(hospital)
 if old and old[0]==revision and (old[1] is None or through is not None and through<=old[1]):
  return [x for x in old[2] if through is None or x['period']<=through]
 readonly=c.execute('SELECT pg_current_xact_id_if_assigned() xid').fetchone()['xid'] is None
 key=(c.info.dsn,revision,hospital)
 shared=source_rows.get(key) if readonly else None
 if shared and (shared['through'] is None or through is not None and through<=shared['through']):
  cache[hospital]=(revision,shared['through'],shared['rows'])
  return [x for x in shared['rows'] if through is None or x['period']<=through]
 result=c.execute('SELECT b.department filename_department,b.id batch_id,b.hospital,b.period,b.version,b.category_version,b.created_at,b.file_id,f.filename,b.parser_version,l.body FROM batches b JOIN files f ON f.id=b.file_id JOIN lines l ON l.batch_id=b.id WHERE b.hospital=%s AND b.active AND (%s::text IS NULL OR b.period<=%s) ORDER BY b.period,l.row_no',(hospital,through,through)).fetchall()
 data=[{**x['body'],'filename_department':x['filename_department'],'batch_id':x['batch_id'],'hospital':x['hospital'],'period':x['period'],'version':x['version'],'category_version':x['category_version'],'file_id':str(x['file_id']),'filename':x['filename'],'parser_version':x['parser_version']} for x in result]
 cache[hospital]=(revision,through,data)
 if readonly and data and source_revision(c)==revision:source_rows.put(key,dict(through=through,rows=data))
 return data


def rcw_bed(c,hospital,p):
 row=next((x for x in bed_history(c,hospital).get(p,[]) if x['department']=='RCW' and False),None)
 return {k:row.get(k) for k in ('value','source','updated_at','department')} if row else None

def bed_history(c,hospital):
 # Connection-local only: never survives a request/transaction or hides another user's edits.
 cache=getattr(c,'_bed_history',None)
 if cache is None:cache={};c._bed_history=cache
 from .performance import source_revision
 revision=source_revision(c)
 if hospital not in cache or cache[hospital][0]!=revision:
  points={}
  for row in c.execute('SELECT * FROM bed_departments WHERE hospital=%s ORDER BY period,department',(hospital,)):
   points.setdefault(row['period'],[]).append(row)
  for row in c.execute("SELECT *,'RCW' department FROM beds WHERE hospital=%s",(hospital,)):
   if not any(x['department']=='RCW' for x in points.get(row['period'],[])):points.setdefault(row['period'],[]).append(row)
  cache[hospital]=(revision,points)
 return cache[hospital][1]
