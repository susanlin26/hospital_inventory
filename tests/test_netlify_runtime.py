"""Transport authorization, replay bounds and staged import integrity."""
import hashlib,uuid
from test_workflow import client,sign
from app import db,netlify_runtime as nr
from helpers import make_excel,line
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def netlify_client(client,monkeypatch):
 monkeypatch.setenv('DATABASE_SSLMODE','disable');monkeypatch.setenv('INVENTORY_NETLIFY_ONLY','true');monkeypatch.setenv('INVENTORY_CLOUD','true');monkeypatch.setenv('PUBLIC_ORIGINS','https://127.0.0.1');monkeypatch.setenv('NETLIFY_BRIDGE_SECRET','local-bridge-test-'*4);monkeypatch.setenv('BOOTSTRAP_TOKEN','local-setup-test-'*4)
 with TestClient(client.app,base_url='https://127.0.0.1',headers={'Origin':'https://127.0.0.1','X-Nf-Sign':'local-bridge-test-'*4}) as c:yield c



def test_internal_endpoints_are_not_public(netlify_client):
 client=netlify_client
 sign(client,'admin099')
 assert client.post('/api/_netlify/internal/pump').status_code==404
 assert client.post('/api/_netlify/internal/download',content=b'private').status_code==404


def test_chunk_upload_is_owned_integrity_checked_and_reuses_original_import(netlify_client):
 client=netlify_client
 sign(client,'admin099')
 with db.connect() as c:c.execute(nr.SCHEMA)
 data=make_excel([line()]);meta=dict(path='/api/import/auto',field='file',filename='11509_SM進銷存表_耗材.xlsx',size=len(data),sha256=hashlib.sha256(data).hexdigest(),fields=[])
 r=client.post('/api/netlify/uploads',json={**meta,'path':'/api/users'});assert r.status_code==422
 assert client.post('/api/netlify/uploads',json={**meta,'size':15*1024*1024+1}).status_code==413
 r=client.post('/api/netlify/uploads',json=meta);assert r.status_code==200,r.text
 uid=r.json()['id']
 sign(client,'acct099');assert client.put('/api/netlify/uploads/'+uid+'/0',content=data).status_code==404
 sign(client,'admin099')
 assert client.post('/api/netlify/uploads/'+uid+'/commit').status_code==422
 assert client.put('/api/netlify/uploads/'+uid+'/15',content=data).status_code==422
 assert client.put('/api/netlify/uploads/'+uid+'/0',content=data[:-1]+bytes([data[-1]^1])).status_code==200
 assert client.post('/api/netlify/uploads/'+uid+'/commit').status_code==422
 assert client.put('/api/netlify/uploads/'+uid+'/0',content=data).status_code==200
 r=client.post('/api/netlify/uploads/'+uid+'/commit');assert r.status_code==200,r.text
 with db.connect() as c:
  f=c.execute('SELECT f.content FROM files f JOIN import_jobs j ON j.file_id=f.id WHERE j.id=%s',(r.json()['job_id'],)).fetchone()
  assert bytes(f['content'])==data
 assert client.post('/api/netlify/uploads/'+uid+'/commit').status_code==404


def test_download_is_bound_to_user_session_and_expiry(netlify_client):
 client=netlify_client
 sign(client,'admin099')
 with db.connect() as c:
  c.execute(nr.SCHEMA)
  user=c.execute("SELECT id FROM users WHERE username='admin099'").fetchone()['id']
  from app.auth import hash_token
  session=hash_token(client.cookies.get('inventory_session'));token=str(uuid.uuid4())
  c.execute("INSERT INTO netlify_downloads(token,owner,session_hash,content,content_type,disposition) VALUES(%s,%s,%s,%s,'application/octet-stream','')",(token,user,session,b'abcdef'))
 assert client.get('/api/netlify/downloads/'+token+'?offset=2&length=2').content==b'cd'
 assert client.get('/api/netlify/downloads/'+token+'?length=1048577').status_code==422
 sign(client,'acct099');assert client.get('/api/netlify/downloads/'+token).status_code==404
 sign(client,'admin099');assert client.get('/api/netlify/downloads/'+token).status_code==404 # New session cannot take over a previous download.


def test_worker_cannot_take_over_another_transaction_owner(netlify_client):
 with db.connect() as owner:
  assert owner.execute('SELECT pg_try_advisory_xact_lock(7414099) leader').fetchone()['leader']
  assert nr.pump(seconds=1)==dict(processed=0,pending=False,busy=True)
