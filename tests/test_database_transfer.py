"""Exercise pg_dump/restore against two isolated databases and guard a populated target."""
import os
import importlib.util
from pathlib import Path
import pytest
import psycopg
from test_workflow import client
from app import db


def test_transfer_only_to_empty_database_and_clear_old_sessions(client):
    source=db.dsn();assert source.endswith('_test')
    target=source.rsplit('/',1)[0]+'/browser099_test'
    with psycopg.connect(target) as c:c.execute('DROP SCHEMA public CASCADE');c.execute('CREATE SCHEMA public')
    path=Path(__file__).parents[1]/'tools/transfer_database.py';spec=importlib.util.spec_from_file_location('transfer',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.transfer(source,target,check_only=True)
    m.transfer(source,target)
    with psycopg.connect(target) as c:
        assert c.execute('SELECT count(*) FROM users').fetchone()[0]==5
        assert c.execute('SELECT count(*) FROM batches').fetchone()[0]==7
        assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
        assert c.execute("SELECT 1 FROM deployment_state WHERE key='bootstrap_complete'").fetchone()
    with pytest.raises(ValueError,match='目標資料庫已有業務資料'):m.transfer(source,target)
    with pytest.raises(ValueError,match='同一資料庫'):m.transfer(source,source)
