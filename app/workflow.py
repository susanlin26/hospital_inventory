"""Source replacement and automatic activation policy, with retained audit history."""
from . import db

POLICY='replace-and-auto-activate-1'

def retire(c,batches,job_ids=()):
 ids=[b['id'] for b in batches];files=[b['file_id'] for b in batches]
 c.execute('UPDATE batches SET deleted_at=now(),active=false WHERE id=ANY(%s)',(ids,))
 c.execute("UPDATE import_jobs SET deleted_at=now(),status='failed',result=result || '{\"error\":\"已由同檔名新版本取代\"}'::jsonb,updated_at=now() WHERE deleted_at IS NULL AND (id=ANY(%s) OR file_id=ANY(%s::uuid[]) OR result->>'batch_id'=ANY(%s))",(list(job_ids),files,[str(n) for n in ids]))

def replace_existing(c,h,p,filename,uid):
 """Caller holds the hospital/month lock; version numbers include canceled uploads."""
 version=c.execute('SELECT greatest(coalesce((SELECT max(version) FROM batches WHERE hospital=%s AND period=%s),0),coalesce((SELECT max(import_version) FROM import_jobs WHERE hospital=%s AND period=%s),0))+1 v',(h,p,h,p)).fetchone()['v']
 batches=c.execute('SELECT b.id,b.file_id,b.version FROM batches b JOIN files f ON f.id=b.file_id WHERE b.hospital=%s AND b.period=%s AND lower(f.filename)=lower(%s) AND b.deleted_at IS NULL FOR UPDATE OF b',(h,p,filename)).fetchall()
 jobs=c.execute('SELECT j.id FROM import_jobs j JOIN files f ON f.id=j.file_id WHERE j.hospital=%s AND j.period=%s AND lower(f.filename)=lower(%s) AND j.deleted_at IS NULL FOR UPDATE OF j',(h,p,filename)).fetchall()
 retire(c,batches,[j['id'] for j in jobs])
 db.audit(c,uid,'source_replacement',h,filename,{'version':version,'replaced_batch_ids':[b['id'] for b in batches],'replaced_job_ids':[j['id'] for j in jobs],'policy':POLICY})
 return version,len(batches)

def deactivate_scope(c,bid,h,p):
 dep=c.execute('SELECT department FROM batches WHERE id=%s',(bid,)).fetchone()['department']
 # Unmarked legacy files and explicitly scoped files must not be counted together.
 c.execute("UPDATE batches SET active=false WHERE hospital=%s AND period=%s AND active AND (department=%s OR department='' OR %s='')",(h,p,dep,dep))


def auto_activate(c,bid,h,p,status,valid_count,uid):
 if status=='blocked' or not valid_count:return False
 db.check_open(c,h,p)
 deactivate_scope(c,bid,h,p)
 c.execute('UPDATE batches SET active=true WHERE id=%s AND deleted_at IS NULL',(bid,))
 db.audit(c,uid,'auto_activate_version',h,bid,{'policy':POLICY,'validation_status':status,'reason':'依匯入自動啟用政策：僅警示或通過、無錯誤'})
 return True

def upgrade(c):
 if c.execute('SELECT 1 FROM workflow_migrations WHERE key=%s',(POLICY,)).fetchone():return
 from .management import department
 bedrows=c.execute("SELECT * FROM bed_departments WHERE department<>'RCW' ORDER BY updated_at").fetchall()
 for row in bedrows:
  if department(row['department'])!='RCW':continue
  h,p=row['hospital'],row['period'];db.scope_lock(c,h,p)
  canonical=c.execute("SELECT * FROM bed_departments WHERE hospital=%s AND period=%s AND department='RCW'",(h,p)).fetchone()
  chosen=row if not canonical or row['updated_at']>canonical['updated_at'] else canonical
  c.execute("INSERT INTO bed_departments(hospital,period,department,value,source,updated_by,updated_at) VALUES(%s,%s,'RCW',%s,%s,%s,%s) ON CONFLICT(hospital,period,department) DO UPDATE SET value=excluded.value,source=excluded.source,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(h,p,chosen['value'],chosen['source'],chosen['updated_by'],chosen['updated_at']))
  c.execute('INSERT INTO beds(hospital,period,value,source,updated_by) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(hospital,period) DO UPDATE SET value=excluded.value,source=excluded.source,updated_by=excluded.updated_by',(h,p,chosen['value'],chosen['source'],chosen['updated_by']))
  c.execute('DELETE FROM bed_departments WHERE hospital=%s AND period=%s AND department=%s',(h,p,row['department']))
  db.audit(c,None,'rcw_department_normalization',h,p,{'original_department':row['department'],'original_value':str(row['value']),'original_source':row['source'],'selected_value':str(chosen['value']),'selected_source':chosen['source']})
 scopes=c.execute('SELECT DISTINCT hospital,period FROM batches WHERE deleted_at IS NULL ORDER BY hospital,period').fetchall()
 for scope in scopes:
  h,p=scope['hospital'],scope['period'];db.scope_lock(c,h,p)
  if c.execute('SELECT 1 FROM period_closes WHERE hospital=%s AND period=%s AND closed',(h,p)).fetchone():continue
  batches=c.execute('SELECT b.id,b.file_id,b.version,b.status,b.report,b.operator,f.filename FROM batches b JOIN files f ON f.id=b.file_id WHERE b.hospital=%s AND b.period=%s AND b.deleted_at IS NULL ORDER BY b.version DESC,b.id DESC FOR UPDATE OF b',(h,p)).fetchall()
  seen=set();older=[]
  for b in batches:
   key=b['filename'].casefold()
   if key in seen:older.append(b)
   else:seen.add(key)
  retire(c,older)
  latest=batches[0]
  c.execute('UPDATE batches SET active=false WHERE hospital=%s AND period=%s AND active',(h,p))
  auto_activate(c,latest['id'],h,p,latest['status'],latest['report'].get('valid_count',0),None)
  db.audit(c,None,'auto_import_policy_upgrade',h,p,{'latest_batch':latest['id'],'retired_batch_ids':[b['id'] for b in older],'policy':POLICY})
 c.execute('INSERT INTO workflow_migrations(key) VALUES(%s)',(POLICY,))
