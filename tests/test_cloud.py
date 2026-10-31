import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import importlib.util
import pytest
from app import cloud,db
from test_workflow import client,sign,PW

ROOT=Path(__file__).resolve().parents[1]
SECRET='proxy-test-secret-only-'*3
SETUP='setup-test-secret-only-'*3
SITE='site-id-test'

def signed(**claims):
    enc=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
    parts=enc({'alg':'HS256','typ':'JWT'})+'.'+enc(dict(iss='netlify',netlify_id=SITE,exp=time.time()+60,**claims))
    return parts+'.'+base64.urlsafe_b64encode(hmac.new(SECRET.encode(),parts.encode(),hashlib.sha256).digest()).decode().rstrip('=')


def config(monkeypatch):
    for k,v in dict(INVENTORY_CLOUD='true',PUBLIC_ORIGINS='https://staging--inventory.netlify.app',NETLIFY_SITE_ID=SITE,NETLIFY_PROXY_SECRET=SECRET,BOOTSTRAP_TOKEN=SETUP,RENDER_EXTERNAL_HOSTNAME='testserver',DATABASE_SSLMODE='disable').items():monkeypatch.setenv(k,v)


def test_signed_gateway_rejects_unsigned_tampered_expired_wrong_site(monkeypatch):
    config(monkeypatch);cloud.validate();token=signed();assert cloud.verify_proxy(token)
    assert not cloud.verify_proxy('') and not cloud.verify_proxy(token+'x') and not cloud.verify_proxy('a.b.c')
    # Explicitly produce valid HMAC but wrong claims.
    for change in [dict(exp=time.time()-1),dict(netlify_id='other'),dict(iss='other')]:
        enc=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
        p=enc({'alg':'HS256'})+'.'+enc({**dict(iss='netlify',netlify_id=SITE,exp=time.time()+60),**change})
        t=p+'.'+base64.urlsafe_b64encode(hmac.new(SECRET.encode(),p.encode(),hashlib.sha256).digest()).decode().rstrip('=')
        assert not cloud.verify_proxy(t)
    assert not cloud.verify_proxy('W10.W10.abc')


def test_cloud_boundary_origin_secure_cookie_and_existing_roles(client,monkeypatch):
    config(monkeypatch)
    assert client.get('/api/setup').status_code==403
    client.headers['X-Nf-Sign']=signed()
    r=client.get('/api/setup');assert r.status_code==200 and r.json()['setup_token_required'] and not r.json()['required']
    r=client.post('/api/login',json=dict(username='admin099',password=PW));assert r.status_code==403
    client.base_url='https://testserver'
    client.headers['Origin']='https://staging--inventory.netlify.app'
    r=client.post('/api/login',json=dict(username='admin099',password=PW));assert r.status_code==200,r.text
    assert 'Secure' in r.headers['set-cookie'] and 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    client.headers['X-CSRF-Token']=r.json()['csrf']
    assert client.get('/api/hospitals').status_code==200
    assert client.post('/api/setup',json=dict(username='attacker',name='外人',password=PW)).status_code==403
    assert client.post('/api/setup',json=dict(username='attacker',name='外人',password=PW,setup_token=SETUP)).status_code==409
    assert client.get('/api/health',headers={'X-Nf-Sign':''}).status_code==200
    client.headers.pop('X-Nf-Sign');client.headers['Origin']='http://testserver';client.base_url='http://testserver'


def test_build_contains_only_browser_assets_and_blocks_auto_production(tmp_path,monkeypatch):
    import shutil
    for f in ['netlify.toml']:shutil.copyfile(ROOT/f,tmp_path/f)
    shutil.copytree(ROOT/'app/static',tmp_path/'app/static')
    def module(name):
        spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    import hashlib,json
    runtime=tmp_path/'backend/runtime';runtime.mkdir(parents=True);archive=runtime/'test.gz';archive.write_bytes(b'test-private-runtime')
    (runtime/'manifest.json').write_text(json.dumps({'archives':{'test.gz':{'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}}}),encoding='utf-8')
    build=module('build_netlify_only')
    monkeypatch.setenv('CONTEXT','deploy-preview');dist=build.build(tmp_path)
    dist=tmp_path/'dist'
    assert (dist/'index.html').exists() and not list(dist.rglob('*.py')) and not list(dist.rglob('*.sql')) and not list(dist.rglob('*.gz'))
    text=''.join(p.read_text(encoding='utf-8') for p in dist.rglob('*') if p.is_file())
    assert SECRET not in text and SETUP not in text and 'postgresql://' not in text
    monkeypatch.setenv('CONTEXT','production');monkeypatch.delenv('ALLOW_PRODUCTION_BUILD',raising=False)
    with pytest.raises(ValueError):build.build(tmp_path)
    monkeypatch.setenv('CONTEXT','deploy-preview');archive.write_bytes(b'changed')
    with pytest.raises(ValueError):build.build(tmp_path)


def test_cloud_background_worker_lease_has_only_one_owner(client):
    with db.connect() as first,db.connect() as second:
        assert first.execute('SELECT pg_try_advisory_lock(7414099) AS leader').fetchone()['leader']
        assert not second.execute('SELECT pg_try_advisory_lock(7414099) AS leader').fetchone()['leader']
        first.execute('SELECT pg_advisory_unlock(7414099)')
        assert second.execute('SELECT pg_try_advisory_lock(7414099) AS leader').fetchone()['leader']
        second.execute('SELECT pg_advisory_unlock(7414099)')
