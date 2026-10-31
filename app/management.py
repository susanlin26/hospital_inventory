"""Import workspace, administrative deletion and department bed census."""
import re
import unicodedata
from collections import Counter
from datetime import date,datetime
from decimal import Decimal,ROUND_HALF_UP
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form
from . import auth,db,excel
from psycopg.types.json import Jsonb

router=APIRouter(prefix='/api')

@router.post('/batches/activate-selected')
def activate_selected(body:dict,u=Depends(auth.current)):
 auth.authorize(u,write=True,activate=True)
 ids=body.get('batch_ids')
 if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(n)is not int or n<=0 for n in ids):raise HTTPException(422,'請選取1至10,000個有效版本')
 ids=list(dict.fromkeys(ids));reason=str(body.get('reason','')).strip()
 if body.get('confirmed') is not True:raise HTTPException(422,'請先確認批次啟用')
 with db.connect() as c:
  db.write_lock(c)
  found=c.execute('SELECT id,hospital,period FROM batches WHERE id=ANY(%s) AND deleted_at IS NULL',(ids,)).fetchall()
  for b in found:auth.authorize(u,b['hospital'])
  for h,p in sorted({(b['hospital'],b['period']) for b in found}):db.scope_lock(c,h,p)
  batches=c.execute('SELECT id,hospital,period,department,version,status,active,report FROM batches WHERE id=ANY(%s) AND deleted_at IS NULL ORDER BY hospital,period,id FOR UPDATE',(ids,)).fetchall()
  scopes=Counter((b['hospital'],b['period'],b['department']) for b in batches)
  conflicts=[(h,p,d) for (h,p,d),n in scopes.items() if n>1]
  mixed=[(h,p) for h,p in {(b['hospital'],b['period']) for b in batches} if any(b['hospital']==h and b['period']==p and not b['department'] for b in batches) and sum(b['hospital']==h and b['period']==p for b in batches)>1]
  if mixed and not conflicts:raise HTTPException(409,'未標示科別的舊月報不可與分科月報同時啟用，請分開選取')
  if conflicts:
   descriptions=[f"{h}／{p}／{d or '未標示'}："+'、'.join('V'+str(b['version']) for b in batches if b['hospital']==h and b['period']==p) for h,p,d in conflicts]
   raise HTTPException(409,'同院同月選取多個版本，本次尚未啟用任何資料。請每院每月每科別僅保留一個版本後再送出：'+'；'.join(descriptions))
  results=[{'batch_id':n,'status':'skipped','message':'版本不存在或已刪除'} for n in ids if not any(b['id']==n for b in batches)]
  for b in batches:
   item={'batch_id':b['id'],'hospital':b['hospital'],'period':b['period'],'version':b['version']}
   if b['active']:results.append({**item,'status':'unchanged','message':'已啟用，未重複切換'});continue
   try:
    db.check_open(c,b['hospital'],b['period'])
    if b['status']=='blocked':raise HTTPException(409,'檢核不通過，不能啟用')
    if not b['report'].get('valid_count'):raise HTTPException(409,'沒有有效明細，不能啟用')
    if b['status']=='warning' and not reason:raise HTTPException(422,'有警示，須填寫確認理由')
   except HTTPException as exc:results.append({**item,'status':'skipped','message':exc.detail});continue
   from .workflow import deactivate_scope
   deactivate_scope(c,b['id'],b['hospital'],b['period'])
   c.execute('UPDATE batches SET active=true WHERE id=%s',(b['id'],))
   db.audit(c,u['id'],'activate_version',b['hospital'],b['id'],{'version':b['version'],'reason':reason,'bulk':True})
   results.append({**item,'status':'activated','message':'版本已啟用'})
 return {'activated':sum(x['status']=='activated' for x in results),'unchanged':sum(x['status']=='unchanged' for x in results),'skipped':sum(x['status']=='skipped' for x in results),'results':results}

@router.post('/batches/{bid}/deactivate')
def deactivate_batch(bid:int,body:dict,u=Depends(auth.current)):
 reason=str(body.get('reason','')).strip()
 if not reason:raise HTTPException(422,'請填寫取消啟用原因')
 with db.connect() as c:
  db.write_lock(c);b=c.execute('SELECT hospital,period FROM batches WHERE id=%s AND deleted_at IS NULL',(bid,)).fetchone()
  if not b:raise HTTPException(404,'版本不存在')
  auth.authorize(u,b['hospital'],write=True,activate=True);db.scope_lock(c,b['hospital'],b['period']);db.check_open(c,b['hospital'],b['period'])
  c.execute('UPDATE batches SET active=false WHERE id=%s',(bid,));db.audit(c,u['id'],'deactivate_version',b['hospital'],bid,{'reason':reason})
 return {'message':'已取消啟用；不會自動切換其他版本'}

@router.get('/categories/current')
def current_category(u=Depends(auth.current)):
 with db.connect() as c:
  row=c.execute('SELECT v.id,v.created_at,v.items,f.filename FROM category_versions v JOIN files f ON f.id=v.file_id ORDER BY v.id DESC LIMIT 1').fetchone()
  if not row:return {'version':None,'items':[]}
  return {'version':row['id'],'created_at':row['created_at'],'filename':row['filename'],'items':[dict(code=code,**{k:v for k,v in x.items() if k!='code'}) for code,items in row['items'].items() for x in items]}

@router.get('/import/records')
def import_records(u=Depends(auth.current)):
 with db.connect() as c:
  batches=c.execute('SELECT b.department,b.id batch_id,b.hospital,b.period,b.version,b.status validation_status,b.active,EXISTS(SELECT 1 FROM period_closes pc WHERE pc.hospital=b.hospital AND pc.period=b.period AND pc.closed) closed,b.report,f.filename FROM batches b JOIN files f ON f.id=b.file_id WHERE b.deleted_at IS NULL AND b.hospital=ANY(%s) ORDER BY b.created_at DESC,b.id DESC',(u['hospitals'],)).fetchall()
  jobs=c.execute("SELECT j.id job_id,j.hospital,j.period,j.import_version version,j.status,j.result,f.filename FROM import_jobs j JOIN files f ON f.id=j.file_id WHERE j.deleted_at IS NULL AND j.hospital=ANY(%s) AND NOT EXISTS(SELECT 1 FROM batches b WHERE b.deleted_at IS NULL AND (b.file_id=j.file_id OR b.id::text=j.result->>'batch_id')) ORDER BY j.id DESC",(u['hospitals'],)).fetchall()
  rows=[{'key':'b'+str(b['batch_id']),'status':'completed',**{k:v for k,v in b.items() if k!='report'},'valid_count':b['report'].get('valid_count'),'excluded_count':b['report'].get('excluded_count'),'warnings':sum(x.get('severity')=='warning' for x in b['report'].get('issues',[])),'errors':sum(x.get('severity')=='error' for x in b['report'].get('issues',[]))} for b in batches]
  for j in jobs:
   try:j['department']=excel.file_identity(j['filename'])['department']
   except ValueError:j['department']=''
 rows += [dict(key='j'+str(j['job_id']),**j,message=j['result'].get('error','')) for j in jobs]
 return {'rows':rows,'test_delete_mode':bool(db.settings().get('test_bulk_delete',False))}

@router.post('/import/delete')
def delete_imports(body:dict,u=Depends(auth.current)):
 auth.authorize(u,admin=True)
 bids=body.get('batch_ids',[]);jids=body.get('job_ids',[])
 if not all(isinstance(x,list) for x in [bids,jids]) or not 0<len(bids)+len(jids)<=500 or any(type(n)is not int or n<=0 for n in bids+jids):raise HTTPException(422,'每批請選取1至500筆有效資料')
 if body.get('confirmed') is not True:raise HTTPException(422,'請先確認所選資料與刪除影響')
 reason=str(body.get('reason','')).strip()
 if not reason:raise HTTPException(422,'請填寫刪除原因')
 test_mode=bool(db.settings().get('test_bulk_delete',False))
 with db.connect() as c:
  db.write_lock(c)
  initial=c.execute('SELECT hospital,period FROM batches WHERE id=ANY(%s) UNION SELECT hospital,period FROM import_jobs WHERE id=ANY(%s)',(bids,jids)).fetchall()
  for h,p in sorted({(x['hospital'],x['period']) for x in initial}):auth.authorize(u,h);db.scope_lock(c,h,p);db.check_open(c,h,p)
  jobs=c.execute('SELECT * FROM import_jobs WHERE id=ANY(%s) AND deleted_at IS NULL FOR UPDATE',(jids,)).fetchall()
  ids=list(set(bids+[int(j['result']['batch_id']) for j in jobs if j['result'].get('batch_id')]))
  fileids=[j['file_id'] for j in jobs]
  batches=c.execute('SELECT id,hospital,period,active,file_id,version FROM batches WHERE (id=ANY(%s) OR file_id=ANY(%s::uuid[])) AND deleted_at IS NULL FOR UPDATE',(ids,fileids)).fetchall()
  for b in batches:
   auth.authorize(u,b['hospital'])
   if not test_mode:
    db.check_open(c,b['hospital'],b['period'])
    if b['active']:raise HTTPException(409,'正式模式請先取消啟用版本再刪除')
  for j in jobs:
   if not test_mode:db.check_open(c,j['hospital'],j['period'])
  ids=[b['id'] for b in batches];fileids += [b['file_id'] for b in batches]
  c.execute('UPDATE batches SET deleted_at=now(),active=false WHERE id=ANY(%s)',(ids,))
  removed=c.execute("UPDATE import_jobs SET deleted_at=now(),status='failed',result=result || '{\"error\":\"管理員已刪除測試匯入資料\"}'::jsonb,updated_at=now() WHERE deleted_at IS NULL AND (id=ANY(%s) OR file_id=ANY(%s::uuid[]) OR result->>'batch_id'=ANY(%s)) RETURNING id",(jids,fileids,[str(n) for n in ids])).fetchall()
  db.audit(c,u['id'],'imports_deleted',detail={'reason':reason,'test_mode':test_mode,'batches':[{**b,'file_id':str(b['file_id'])} for b in batches],'job_ids':[j['id'] for j in removed],'note':'移出清單與分析，來源及明細保留供稽核'})
 return {'deleted_batches':len(ids),'deleted_jobs':len(removed),'message':'所選資料已移出清單與分析；未自動切換到其他版本'}

def department(value):
 s=unicodedata.normalize('NFKC',str(value or '')).strip()
 if not s or len(s)>60:raise ValueError('請選擇或輸入科別（最多60字）')
 return 'RCW' if re.search(r'(?<![A-Za-z])RCW(?![A-Za-z])',s,re.I) or s=='呼吸照護病房' else s

def bed_period(value):
 if isinstance(value,(datetime,date)):return excel.period(value.strftime('%Y-%m'))
 if isinstance(value,(int,float,Decimal)) and Decimal(str(value))==int(value):return excel.period(str(int(value)))
 s=str(value).strip();m=re.fullmatch(r'(\d{3}|\d{4})[年/\-](\d{1,2})月?',s)
 if m:
  year=int(m[1])+(1911 if len(m[1])==3 else 0);return excel.period(f'{year}-{int(m[2]):02d}')
 return excel.period(s)

def save_bed(c,body,u):
 h=str(body.get('hospital','')).strip().upper();p=bed_period(body.get('period',''));d=department(body.get('department','RCW'))
 auth.authorize(u,h,write=True);v=excel.number(body.get('value'));source=str(body.get('source','')).strip()
 if not 0<v<=1000000 or v!=v.to_integral_value() or not source or len(source)>500:raise HTTPException(422,'當月住院人日數須為正整數且不超過1,000,000，並填寫資料來源（最多500字）')
 if not c.execute('SELECT 1 FROM hospitals WHERE code=%s AND active',(h,)).fetchone():raise HTTPException(422,'院別不存在或停用')
 db.scope_lock(c,h,p);db.check_open(c,h,p)
 old=c.execute('SELECT value,source,measurement FROM bed_departments WHERE hospital=%s AND period=%s AND department=%s',(h,p,d)).fetchone()
 if old and body.get('no_overwrite'):raise ValueError('此院月科別已有資料；未勾選覆寫，已略過')
 c.execute('INSERT INTO bed_departments(hospital,period,department,value,source,updated_by) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(hospital,period,department) DO UPDATE SET value=excluded.value,source=excluded.source,updated_by=excluded.updated_by,updated_at=now()',(h,p,d,v,source,u['id']))
 c.execute("UPDATE bed_departments SET measurement='patient_days' WHERE hospital=%s AND period=%s AND department=%s",(h,p,d))
 if d=='RCW':c.execute('INSERT INTO beds(hospital,period,value,source,updated_by) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(hospital,period) DO UPDATE SET value=excluded.value,source=excluded.source,updated_by=excluded.updated_by,updated_at=now()',(h,p,v,source,u['id']))
 db.audit(c,u['id'],'beds_update',h,p,{'department':d,'before':{'value':str(old['value']),'source':old['source'],'measurement':old['measurement']} if old else None,'value':str(v),'source':source,'measurement':'patient_days'})
 return {'hospital':h,'period':p,'department':d,'value':str(v)}

@router.get('/beds/records')
def bed_records(u=Depends(auth.current)):
 with db.connect() as c:
  rows=c.execute('SELECT hospital,period,department,value::text,source,updated_at,measurement FROM bed_departments WHERE hospital=ANY(%s) ORDER BY period DESC,hospital,department',(u['hospitals'],)).fetchall()
 from .inpatient import bed_days
 return [{**r,**bed_days(r['period'],r['value'],r['measurement'])} for r in rows]

def parse_beds(data):
 w=excel.workbook(data);headers=['年度月份','醫院別','科別','當月住院人日數'];matches=[]
 for s in w:
  for row in s.iter_rows(min_row=1,max_row=min(20,s.max_row)):
   mapping={str(c.value).strip():c.column-1 for c in row if c.value is not None}
   if all(h in mapping for h in headers):matches.append((s,row[0].row,mapping));break
 if len(matches)!=1:raise ValueError('請提供唯一資料工作表，欄位須含：年度月份、醫院別、科別、當月住院人日數')
 s,head,mapping=matches[0]
 if s.max_row>20000:raise ValueError('床數資料最多支援20,000列，請分檔')
 out=[]
 for row in s.iter_rows(min_row=head+1):
  if not any(c.value is not None for c in row):continue
  get=lambda k:row[mapping[k]].value
  r={'row':row[0].row,'valid':False}
  try:
   r.update(period=bed_period(get('年度月份')),hospital=str(get('醫院別') or '').strip(),department=department(get('科別')),value=str(excel.number(get('當月住院人日數'))))
   if Decimal(r['value'])<=0:raise ValueError('當月住院人日數須大於0')
   r['valid']=True
  except (ValueError,TypeError) as e:r['message']=str(e)
  out.append(r)
 if not out:raise ValueError('床數檔案沒有資料列')
 return out

@router.post('/beds/import')
def import_beds(file:UploadFile=File(...),overwrite:bool=Form(False),u=Depends(auth.current)):
 auth.authorize(u,write=True)
 if not file.filename.lower().endswith('.xlsx'):raise HTTPException(422,'床數只接受.xlsx')
 data=file.file.read(15*1024*1024+1);rows=parse_beds(data)
 with db.connect() as c:
  db.write_lock(c);hospitals=c.execute('SELECT code,name FROM hospitals WHERE active').fetchall()
  aliases={x['name']:x['code'] for x in hospitals};aliases.update({x['code']:x['code'] for x in hospitals})
  aliases.update({'第一':'DE','第一醫院':'DE','勝美':'SM','勝美醫院':'SM','祥恩':'SN','祥恩醫院':'SN','忠港':'ZK','忠港醫院':'ZK'})
  for r in rows:
   if r['valid']:r['hospital']=aliases.get(r['hospital'],aliases.get(r['hospital'].upper(),r['hospital']))
  counts=Counter((r['hospital'],r['period'],r['department']) for r in rows if r['valid'])
  # Stable lock order across all rows prevents cross-file deadlocks.
  for h,p in sorted({(r['hospital'],r['period']) for r in rows if r['valid']}):db.scope_lock(c,h,p)
  for r in rows:
   if not r['valid']:continue
   try:
    if counts[(r['hospital'],r['period'],r['department'])]>1:raise ValueError('檔內同一院月科別重複，相關列均未匯入')
    save_bed(c,{**r,'source':file.filename,'no_overwrite':not overwrite},u);r['message']='已儲存'
   except (ValueError,HTTPException) as e:r['valid']=False;r['message']=e.detail if isinstance(e,HTTPException) else str(e)
  db.audit(c,u['id'],'beds_file_import',detail={'filename':file.filename,'saved':sum(r['valid'] for r in rows),'rejected':sum(not r['valid'] for r in rows),'overwrite':overwrite})
 return {'saved':sum(r['valid'] for r in rows),'rejected':sum(not r['valid'] for r in rows),'rows':rows}


@router.delete('/beds')
def delete_bed(body:dict,u=Depends(auth.current)):
 h=str(body.get('hospital','')).strip().upper();p=bed_period(body.get('period',''));d=department(body.get('department','RCW'))
 auth.authorize(u,h,write=True)
 expected=body.get('expected_updated_at')
 try:stamp=datetime.fromisoformat(str(expected).replace('Z','+00:00'))
 except ValueError:raise HTTPException(422,'請重新讀取床數後再刪除')
 with db.connect() as c:
  db.write_lock(c);db.scope_lock(c,h,p);db.check_open(c,h,p)
  row=c.execute('SELECT * FROM bed_departments WHERE hospital=%s AND period=%s AND department=%s FOR UPDATE',(h,p,d)).fetchone()
  if not row:raise HTTPException(404,'此筆床數已不存在')
  if stamp.tzinfo is None or row['updated_at']!=stamp:raise HTTPException(409,'床數已更新，請重新整理後再確認刪除')
  c.execute('DELETE FROM bed_departments WHERE hospital=%s AND period=%s AND department=%s',(h,p,d))
  if d=='RCW':c.execute('DELETE FROM beds WHERE hospital=%s AND period=%s',(h,p))
  db.audit(c,u['id'],'beds_delete',h,p,{'department':d,'before':{k:(v.isoformat() if hasattr(v,'isoformat') else str(v) if isinstance(v,Decimal) else v) for k,v in row.items()}})
  scopes={x['scope'] for x in c.execute('SELECT DISTINCT scope FROM tracking_work_state WHERE hospital=%s AND period=%s',(h,p))}|{'__all__'}
  for scope in sorted(scopes):
   for basis in ('previous','year'):
    c.execute("INSERT INTO tracking_work_state(hospital,period,scope,basis,scan_state) VALUES(%s,%s,%s,%s,'queued') ON CONFLICT(hospital,period,scope,basis) DO UPDATE SET scan_state='queued',source_token=NULL,last_error=NULL",(h,p,scope,basis))
 return {'deleted':True,'hospital':h,'period':p,'department':d}
