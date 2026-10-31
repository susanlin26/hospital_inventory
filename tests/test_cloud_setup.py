import os
from fastapi.testclient import TestClient
from app import db
from test_cloud import config,signed,SETUP,PW


def test_first_cloud_setup_requires_secret_and_stays_disabled_after_use(monkeypatch):
    assert os.environ['DATABASE_URL'].endswith('_test')
    with db.connect() as c:c.execute('DROP SCHEMA public CASCADE');c.execute('CREATE SCHEMA public')
    config(monkeypatch)
    from app.server import app
    with TestClient(app,base_url='https://testserver',headers={'Origin':'https://staging--inventory.netlify.app','X-Nf-Sign':signed()}) as c:
        assert c.get('/api/setup').json()['required']
        payload=dict(username='cloudadmin',name='測試管理員',password=PW)
        assert c.post('/api/setup',json=payload).status_code==403
        assert c.post('/api/setup',json={**payload,'setup_token':SETUP}).status_code==200
        assert c.post('/api/login',json=dict(username='cloudadmin',password=PW)).status_code==200
        assert not c.get('/api/setup').json()['required']
        # Even a lost/deleted user table does not reactivate the initial setup endpoint.
        with db.connect() as conn:conn.execute('TRUNCATE users CASCADE')
        assert not c.get('/api/setup').json()['required']
        assert c.post('/api/setup',json={**payload,'setup_token':SETUP}).status_code==409
