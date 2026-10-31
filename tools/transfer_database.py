"""One-time transfer into an empty cloud database. Stop both applications first."""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import psycopg
from psycopg.conninfo import conninfo_to_dict


def pg_environment(dsn):
    options = conninfo_to_dict(dsn)
    result = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
    for name, variable in [('host','PGHOST'),('hostaddr','PGHOSTADDR'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD'),('dbname','PGDATABASE'),('sslmode','PGSSLMODE')]:
        if name in options:result[variable] = options[name]
    return result


def ensure_empty(dsn):
    with psycopg.connect(dsn) as c:
        for table in ('users','files','batches','monthly_cases','audit'):
            if c.execute('SELECT to_regclass(%s)', ('public.'+table,)).fetchone()[0] and c.execute('SELECT EXISTS(SELECT 1 FROM '+table+')').fetchone()[0]:
                raise ValueError('目標資料庫已有業務資料，已停止；請改用全新資料庫')


def transfer(source, target, check_only=False):
    a,b = conninfo_to_dict(source),conninfo_to_dict(target)
    if all(a.get(k)==b.get(k) for k in ('host','hostaddr','port','dbname')):
        raise ValueError('來源與目標不可為同一資料庫')
    ensure_empty(target)
    with psycopg.connect(source) as c:c.execute('SELECT 1')
    if check_only:return
    for tool in ('pg_dump','pg_restore'):
        if not shutil.which(tool):raise ValueError('找不到'+tool+'，請將PostgreSQL的bin資料夾加入PATH')
    with tempfile.TemporaryDirectory(prefix='inventory-transfer-') as directory:
        dump = Path(directory)/'inventory.dump'
        # Credentials are passed only in environment, never command arguments or output.
        for args, dsn in [(['pg_dump','--format=custom','--no-owner','--no-acl','--file',str(dump)],source),(['pg_restore','--dbname',b['dbname'],'--clean','--if-exists','--no-owner','--no-acl','--exit-on-error','--single-transaction',str(dump)],target)]:
            result = subprocess.run(args,env=pg_environment(dsn),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            if result.returncode:raise ValueError('資料搬移未完成；請確認工具版本、連線及權限，錯誤細節不公開以保護連線資訊')
    with psycopg.connect(target) as c:
        c.execute('DELETE FROM sessions');c.execute('DELETE FROM login_attempts')
        c.execute('CREATE TABLE IF NOT EXISTS deployment_state(key text PRIMARY KEY,created_at timestamptz NOT NULL DEFAULT now())')
        c.execute("INSERT INTO deployment_state(key) SELECT 'bootstrap_complete' WHERE EXISTS(SELECT 1 FROM users) ON CONFLICT DO NOTHING")


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='僅將原資料搬到全新雲端資料庫，請先停止兩邊程式並另做備份')
    parser.add_argument('--source-config',type=Path,help='原安裝資料夾的config.json')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    try:
        source=os.environ.get('SOURCE_DATABASE_URL')
        if not source and args.source_config:source=json.loads(args.source_config.read_text(encoding='utf-8-sig')).get('database_url')
        target=os.environ.get('TARGET_DATABASE_URL') or getpass.getpass('雲端資料庫外部連線網址（不顯示）：')
        if not source or not target:raise ValueError('請設定來源及TARGET_DATABASE_URL；不要將連線密碼貼到對話或上傳到程式庫')
        transfer(source,target,args.check_only)
        print('連線與空白目標檢查完成。' if args.check_only else '資料搬移完成，使用者需重新登入；請確認人數、月報與案件筆數後再使用。')
    except Exception as exc:
        print(str(exc) if isinstance(exc,ValueError) else '作業未完成，請確認連線、工具及權限；為保護帳號不顯示連線細節。')
        raise SystemExit(1)
