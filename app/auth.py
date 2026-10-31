from datetime import datetime,timedelta,timezone
import hashlib,secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError,InvalidHashError
from fastapi import HTTPException,Request
from . import db

hasher=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)

def hash_token(s):return hashlib.sha256(s.encode()).hexdigest()

def password(value):
 if not isinstance(value,str) or not 12<=len(value)<=200:raise HTTPException(422,'密碼需12至200個字元')
 return hasher.hash(value)

def current(request:Request):
 token=request.cookies.get('inventory_session','')
 with db.connect() as c:
  user=c.execute('SELECT u.id,u.username,u.name,u.role,u.can_activate,u.must_change_password,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires>now() AND s.last_seen>now()-interval \'30 minutes\' AND u.active',(hash_token(token),)).fetchone()
  if not user:raise HTTPException(401,'請先登入，或登入已逾時')
  if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):raise HTTPException(403,'操作驗證失敗，請重新登入')
  c.execute('UPDATE sessions SET last_seen=now() WHERE token_hash=%s',(hash_token(token),))
  user['hospitals']=[r['code'] for r in c.execute('SELECT code FROM hospitals WHERE active ORDER BY code')] if user['role']=='admin' else [r['hospital'] for r in c.execute('SELECT hospital FROM grants WHERE user_id=%s ORDER BY hospital',(user['id'],))]
  if user['must_change_password'] and request.url.path not in ('/api/me','/api/logout','/api/password/change'):
   raise HTTPException(403,'請先變更臨時密碼，再使用系統')
  if user['role']=='frontline' and request.method not in ('GET','HEAD','OPTIONS') and request.url.path not in ('/api/logout','/api/password/change','/api/monthly-cases-batch') and not request.url.path.startswith('/api/monthly-cases/'):
   raise HTTPException(403,'前線帳號僅能填寫所屬院別案件，不能修改財務或設定')
  return user

def authorize(user,hospital=None,write=False,manager=False,admin=False,activate=False):
 if admin and user['role']!='admin':raise HTTPException(403,'需要系統管理員權限')
 if user['role']!='admin' and hospital is not None and hospital not in user['hospitals']:raise HTTPException(403,'沒有此醫院的存取權限')
 if write and user['role']=='viewer':raise HTTPException(403,'查詢帳號不能修改資料')
 if manager and user['role'] not in ('manager','admin'):raise HTTPException(403,'需要主管權限')
 if activate and not (user['role'] in ('manager','admin') or user['can_activate']):raise HTTPException(403,'尚未授權啟用版本')

def issue_session(c,user,response,secure):
 token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
 c.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires) VALUES(%s,%s,%s,%s)',(hash_token(token),user['id'],csrf,datetime.now(timezone.utc)+timedelta(hours=8)))
 response.set_cookie('inventory_session',token,httponly=True,secure=secure,samesite='strict',max_age=28800,path='/')
 return csrf
