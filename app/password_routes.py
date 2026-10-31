"""個人變更與管理員重設分開；所有憑證變更撤銷全部登入。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from . import auth, db

router=APIRouter(prefix='/api')

def confirmed(body):
 value=body.get('new_password');again=body.get('confirm_password')
 if not isinstance(value,str) or not 12<=len(value)<=200:raise HTTPException(422,'密碼需12至200個字元')
 if not isinstance(again,str) or not again or value!=again:raise HTTPException(422,'兩次輸入的密碼不一致')
 return value

def matches(hashed,value):
 if not isinstance(value,str) or len(value)>200:return False
 try:return auth.hasher.verify(hashed,value)
 except (auth.VerificationError,auth.InvalidHashError):return False

@router.post('/password/change')
def change_password(body:dict,request:Request,response:Response,u=Depends(auth.current)):
 new=confirmed(body);current=body.get('current_password');bad=False
 if not isinstance(current,str) or not current:raise HTTPException(422,'請輸入目前密碼')
 identity='password-change:'+str(u['id'])
 with db.connect() as c:
  db.write_lock(c)
  row=c.execute('SELECT id,password_hash FROM users WHERE id=%s AND active AND deleted_at IS NULL FOR UPDATE',(u['id'],)).fetchone()
  if not row:raise HTTPException(401,'帳號已停用')
  c.execute("DELETE FROM login_attempts WHERE identity=%s AND created_at<now()-interval '15 minutes'",(identity,))
  if c.execute('SELECT count(*) n FROM login_attempts WHERE identity=%s',(identity,)).fetchone()['n']>=8:raise HTTPException(429,'嘗試次數過多，請15分鐘後再試')
  if not matches(row['password_hash'],current):
   c.execute('INSERT INTO login_attempts(identity) VALUES(%s)',(identity,));bad=True
  else:
   if matches(row['password_hash'],new):raise HTTPException(422,'新密碼不可與目前密碼相同')
   c.execute('UPDATE users SET password_hash=%s,must_change_password=false WHERE id=%s',(auth.password(new),u['id']))
   c.execute('DELETE FROM sessions WHERE user_id=%s',(u['id'],));c.execute('DELETE FROM login_attempts WHERE identity=%s',(identity,))
   db.audit(c,u['id'],'password_changed',target=u['id'],detail={'all_sessions_revoked':True})
 if bad:raise HTTPException(422,'目前密碼不正確')
 response.delete_cookie('inventory_session',path='/')
 return {'message':'密碼已變更，請重新登入'}

@router.post('/users/{uid}/reset-password')
def reset_password(uid:int,body:dict,response:Response,u=Depends(auth.current)):
 auth.authorize(u,admin=True);new=confirmed(body)
 with db.connect() as c:
  db.write_lock(c)
  row=c.execute('SELECT id,username,password_hash FROM users WHERE id=%s AND deleted_at IS NULL FOR UPDATE',(uid,)).fetchone()
  if not row:raise HTTPException(404,'帳號不存在')
  if matches(row['password_hash'],new):raise HTTPException(422,'臨時密碼不可與目前密碼相同')
  c.execute('UPDATE users SET password_hash=%s,must_change_password=true WHERE id=%s',(auth.password(new),uid))
  c.execute('DELETE FROM sessions WHERE user_id=%s',(uid,))
  c.execute('DELETE FROM login_attempts WHERE identity=%s',('password-change:'+str(uid),))
  db.audit(c,u['id'],'password_reset',target=uid,detail={'username':row['username'],'must_change_password':True,'all_sessions_revoked':True})
 if uid==u['id']:response.delete_cookie('inventory_session',path='/')
 return {'message':'密碼已重設，該使用者須重新登入','must_change_password':True}
