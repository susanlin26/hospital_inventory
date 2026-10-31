"""Netlify lifecycle, durable uploads/downloads and bounded worker invocations.
Business rules, money arithmetic and original endpoint authorization stay in place.
"""
import hashlib,hmac,os,secrets,time,uuid
from datetime import datetime,timedelta,timezone
from fastapi import Depends,HTTPException,Request
from fastapi.responses import Response
from psycopg.types.json import Jsonb
from . import db,auth,cloud,__version__

SCHEMA='''
CREATE TABLE IF NOT EXISTS netlify_uploads(id uuid PRIMARY KEY,owner bigint REFERENCES users(id),body jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),expires timestamptz NOT NULL DEFAULT now()+interval '30 minutes');
CREATE TABLE IF NOT EXISTS netlify_upload_chunks(upload uuid REFERENCES netlify_uploads(id) ON DELETE CASCADE,part integer NOT NULL,content bytea NOT NULL,PRIMARY KEY(upload,part));
CREATE TABLE IF NOT EXISTS netlify_downloads(token text PRIMARY KEY,owner bigint NOT NULL REFERENCES users(id),session_hash text NOT NULL,content bytea NOT NULL,content_type text NOT NULL,disposition text NOT NULL,expires timestamptz NOT NULL DEFAULT now()+interval '15 minutes');
'''

def initialize():
 # A database-level deploy marker avoids running historical migrations on every cold start.
 with db.connect() as lock:
  lock.execute('SELECT pg_advisory_xact_lock(7414120)')
  exists=lock.execute("SELECT to_regclass('public.deployment_state') t").fetchone()['t']
  if exists and lock.execute('SELECT 1 FROM deployment_state WHERE key=%s',('netlify-ready:'+__version__,)).fetchone():return
  from . import server
  db.init();server.update_tolerance_reports();server.update_identity_reports()
  from .rule_periods import initialize_defaults
  with db.connect() as c:
   c.execute(SCHEMA);initialize_defaults(c);db.write_lock(c);server.workflow.upgrade(c)
   c.execute('INSERT INTO deployment_state(key) VALUES(%s) ON CONFLICT DO NOTHING',('netlify-ready:'+__version__,))

def internal(request):
 secret=os.environ.get('NETLIFY_BRIDGE_SECRET','')
 if not cloud.netlify_only() or len(secret)<32 or not hmac.compare_digest(request.headers.get('x-inventory-internal',''),secret):raise HTTPException(404,'Not Found')

def pump(seconds=600):
 from . import server
 until=time.monotonic()+max(1,min(650,seconds));count=0
 with db.connect() as lease:
  # Transaction-scoped ownership also works through transaction-mode database poolers.
  lease.execute("SET LOCAL idle_in_transaction_session_timeout = '15min'")
  if not lease.execute('SELECT pg_try_advisory_xact_lock(7414099) leader').fetchone()['leader']:return dict(processed=0,pending=False,busy=True)
  try:
   server.recover_interrupted_work()
   with db.connect() as c:
    c.execute('DELETE FROM netlify_uploads WHERE expires<now()');c.execute('DELETE FROM netlify_downloads WHERE expires<now()')
   while time.monotonic()<until:
    if server.job_once() or server.tracking_history_once():count+=1
    else:break
   with db.connect() as c:
    pending=c.execute("SELECT EXISTS(SELECT 1 FROM import_jobs WHERE status='queued' AND deleted_at IS NULL) OR EXISTS(SELECT 1 FROM tracking_work_state WHERE scan_state='queued') pending").fetchone()['pending']
   return dict(processed=count,pending=pending,busy=False)
  finally:pass # The connection context releases transaction ownership on commit/rollback.

def install(app):
 @app.post('/api/_netlify/internal/pump')
 def run_pump(request:Request):
  internal(request);return pump(int(request.headers.get('x-pump-seconds','600')))

 @app.post('/api/_netlify/internal/download')
 async def stage_download(request:Request):
  internal(request)
  # GET exports may be cached without requiring a new business mutation/CSRF token.
  session=auth.hash_token(request.cookies.get('inventory_session',''))
  with db.connect() as c:
   user=c.execute("SELECT u.id FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=%s AND s.expires>now() AND s.last_seen>now()-interval '30 minutes' AND u.active",(session,)).fetchone()
   if not user:raise HTTPException(401,'請重新登入')
   content=await request.body()
   token=secrets.token_urlsafe(32);ctype=request.headers.get('x-result-type','application/octet-stream');disposition=request.headers.get('x-result-disposition','')
   c.execute('INSERT INTO netlify_downloads(token,owner,session_hash,content,content_type,disposition) VALUES(%s,%s,%s,%s,%s,%s)',(token,user['id'],session,content,ctype,disposition))
  return dict(token=token,size=len(content),type=ctype,disposition=disposition)

 @app.get('/api/netlify/downloads/{token}')
 def download(token:str,request:Request,offset:int=0,length:int=1024*1024,u=Depends(auth.current)):
  if offset<0 or not 1<=length<=1024*1024:raise HTTPException(422,'下載範圍不正確')
  with db.connect() as c:
   row=c.execute('SELECT substring(content FROM %s FOR %s) content FROM netlify_downloads WHERE token=%s AND owner=%s AND session_hash=%s AND expires>now()',(offset+1,length,token,u['id'],auth.hash_token(request.cookies.get('inventory_session','')))).fetchone()
   if not row:raise HTTPException(404,'下載已過期，請重新匯出')
   return Response(bytes(row['content']),media_type='application/octet-stream')

 @app.post('/api/netlify/uploads')
 async def start_upload(body:dict,u=Depends(auth.current)):
  allowed={'/api/import','/api/import/auto','/api/categories','/api/beds/import'}
  if body.get('path') not in allowed or body.get('field')!='file':raise HTTPException(422,'不支援的上傳方式')
  if not isinstance(body.get('size'),int) or not 0<body['size']<=15*1024*1024:raise HTTPException(413,'檔案超過15 MB或為空檔')
  if not isinstance(body.get('sha256'),str) or len(body['sha256'])!=64 or not isinstance(body.get('fields',[]),list):raise HTTPException(422,'上傳資料不正確')
  fields=body.get('fields',[])
  if len(fields)>20 or any(not isinstance(v,list) or len(v)!=2 or any(not isinstance(s,str) or len(s)>500 for s in v) for v in fields):raise HTTPException(422,'上傳欄位不正確')
  if not isinstance(body.get('filename'),str) or not body['filename'].lower().endswith('.xlsx') or len(body['filename'])>250:raise HTTPException(422,'請選擇Excel檔案')
  uid=uuid.uuid4()
  with db.connect() as c:
   if c.execute('SELECT count(*) n FROM netlify_uploads WHERE owner=%s AND expires>now()',(u['id'],)).fetchone()['n']>=20:raise HTTPException(429,'暫存上傳過多，請稍後再試')
   c.execute('INSERT INTO netlify_uploads(id,owner,body) VALUES(%s,%s,%s)',(uid,u['id'],Jsonb(body)))
  return dict(id=str(uid),chunk_size=1024*1024)

 @app.put('/api/netlify/uploads/{uid}/{part}')
 async def upload_chunk(uid:uuid.UUID,part:int,request:Request,u=Depends(auth.current)):
  content=await request.body()
  if not 0<=part<15 or not 0<len(content)<=1024*1024:raise HTTPException(422,'上傳片段不正確')
  with db.connect() as c:
   row=c.execute('SELECT body FROM netlify_uploads WHERE id=%s AND owner=%s AND expires>now() FOR UPDATE',(uid,u['id'])).fetchone()
   if not row:raise HTTPException(404,'上傳已過期，請重試')
   size=row['body']['size'];expected=min(1024*1024,size-part*1024*1024)
   if len(content)!=expected:raise HTTPException(422,'片段大小不符')
   c.execute('INSERT INTO netlify_upload_chunks(upload,part,content) VALUES(%s,%s,%s) ON CONFLICT(upload,part) DO UPDATE SET content=excluded.content',(uid,part,content))
  return dict(saved=part)

 @app.post('/api/netlify/uploads/{uid}/commit')
 async def commit_upload(uid:uuid.UUID,request:Request,u=Depends(auth.current)):
  import httpx
  with db.connect() as c:
   row=c.execute('SELECT body FROM netlify_uploads WHERE id=%s AND owner=%s AND expires>now() FOR UPDATE',(uid,u['id'])).fetchone()
   if not row:raise HTTPException(404,'上傳已過期或已完成')
   meta=row['body'];chunks=c.execute('SELECT part,content FROM netlify_upload_chunks WHERE upload=%s ORDER BY part',(uid,)).fetchall();content=b''.join(bytes(x['content']) for x in chunks)
   if [x['part'] for x in chunks]!=list(range((meta['size']+1024*1024-1)//(1024*1024))) or len(content)!=meta['size'] or hashlib.sha256(content).hexdigest()!=meta['sha256']:raise HTTPException(422,'檔案片段尚未齊全或內容不符，請重新上傳')
   headers={k:v for k,v in request.headers.items() if k.lower() in ('origin','cookie','x-csrf-token','x-nf-sign')};headers['host']='127.0.0.1'
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
    reply=await client.post(meta['path'],headers=headers,data=dict(meta['fields']),files={meta['field']:(meta['filename'],content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
   if reply.status_code<400:c.execute('DELETE FROM netlify_uploads WHERE id=%s',(uid,))
  return Response(reply.content,status_code=reply.status_code,media_type=reply.headers.get('content-type','application/json'))
