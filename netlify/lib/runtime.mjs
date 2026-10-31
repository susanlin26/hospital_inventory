import { spawn } from 'node:child_process';
import { createHash,randomBytes,createHmac,timingSafeEqual } from 'node:crypto';
import { readFile,mkdir,chmod,stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getConnectionString } from '@netlify/database';
import { x as untar } from 'tar';
let boot,child,root,bridgeSecret,bridgeBase;
process.once('exit',()=>child?.kill());
process.once('SIGTERM',()=>{child?.kill();process.exit(0)});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
export const errorResponse=(message,status=503)=>Response.json({detail:message},{status,headers:{'Cache-Control':'no-store'}});
export function origins(){return [...new Set((process.env.PUBLIC_ORIGINS||[process.env.DEPLOY_PRIME_URL,process.env.DEPLOY_URL,process.env.URL].filter(Boolean).join(',')).split(',').map(s=>s.trim().replace(/\/$/,'')))].filter(Boolean)}
function projectRoot(){
 const roots=[process.cwd(),resolve(fileURLToPath(new URL('../../',import.meta.url))),'/var/task'];
 const found=roots.find(p=>existsSync(resolve(p,'backend/runtime/manifest.json'))&&existsSync(resolve(p,'app/server.py')));
 if(!found)throw Error('missing_runtime');return found;
}
export async function ready(){
 if(child&&child.exitCode!==null)boot=undefined;
 if(!boot)boot=start().catch(e=>{boot=undefined;throw e});return boot;
}
async function start(){
 root=projectRoot();const manifest=JSON.parse(await readFile(resolve(root,'backend/runtime/manifest.json'),'utf8'));
 if(process.platform!=='linux'||process.arch!=='x64')throw Error('unsupported_architecture');
 const key=createHash('sha256').update(JSON.stringify(manifest)).digest('hex').slice(0,16),target='/tmp/inventory-python-'+key;
 await mkdir(target,{recursive:true});
 if(!existsSync(resolve(target,'complete'))){
  for(const [name,entry] of Object.entries(manifest.archives)){
   const archive=resolve(root,'backend/runtime',name),data=await readFile(archive);
   if(createHash('sha256').update(data).digest('hex')!==entry.sha256)throw Error('runtime_integrity');
   await untar({file:archive,cwd:target,strict:true,preserveOwner:false});
  }
  await chmod(resolve(target,'python/bin/python3'),0o755);
  const {writeFile}=await import('node:fs/promises');await writeFile(resolve(target,'complete'),'ok');
 }
 const database=getConnectionString(),allowed=origins();
 if(!database||!allowed.length||String(process.env.BOOTSTRAP_TOKEN||'').length<32)throw Error('missing_configuration');
 bridgeSecret=randomBytes(40).toString('hex');
 // The listener is loopback-only. It is never published as another service.
 const python=resolve(target,'python/bin/python3');
 child=spawn(python,['-m','uvicorn','app.server:app','--host','127.0.0.1','--port','0','--workers','1','--no-proxy-headers','--no-access-log','--log-level','info'],{cwd:root,env:{...process.env,PYTHONHOME:resolve(target,'python'),PYTHONPATH:root,PYTHONUNBUFFERED:'1',PYTHONDONTWRITEBYTECODE:'1',INVENTORY_DATA:'/tmp/inventory',INVENTORY_CLOUD:'true',INVENTORY_NETLIFY_ONLY:'true',INVENTORY_ENVIRONMENT:'Netlify測試環境',PUBLIC_ORIGINS:allowed.join(','),DATABASE_URL:database,PGSSLROOTCERT:resolve(target,'python/lib/python3.12/site-packages/certifi/cacert.pem'),NETLIFY_BRIDGE_SECRET:bridgeSecret},stdio:['ignore','pipe','pipe']});
 child.unref();child.stdout.unref?.();child.stderr.unref?.();
 let stderr='';let listening;
 const found=new Promise((r,j)=>{listening=r;child.once('error',j);child.once('exit',()=>j(Error('bridge_exit')))});
 const output=chunk=>{const text=String(chunk);if(process.env.INVENTORY_DIAGNOSTICS==='local')console.error(text);stderr=(stderr+text).slice(-4000);const match=stderr.match(/Uvicorn running on http:\/\/127\.0\.0\.1:(\d+)/);if(match)listening('http://127.0.0.1:'+match[1]);};
 child.stdout.on('data',output);child.stderr.on('data',output);
 bridgeBase=await Promise.race([found,new Promise((_,j)=>{const t=setTimeout(()=>j(Error('bridge_timeout')),45000);t.unref()})]);
 return {base:bridgeBase,secret:bridgeSecret};
}
export async function internal(path,{body,headers={}}={}){
 const {base,secret}=await ready();return fetch(base+path,{method:'POST',headers:{origin:origins()[0],'x-nf-sign':secret,'x-inventory-internal':secret,...headers},body,signal:AbortSignal.timeout(path.endsWith('/pump')?780000:45000)});
}
export async function forward(request){
 const url=new URL(request.url);
 if(!url.pathname.startsWith('/api/')||url.pathname.startsWith('/api/_netlify/internal/'))return errorResponse('Not Found',404);
 const {base,secret}=await ready(),headers=new Headers();
 for(const key of ['content-type','cookie','origin','x-csrf-token','accept'])if(request.headers.has(key))headers.set(key,request.headers.get(key));
 headers.set('x-nf-sign',secret);
 const response=await fetch(base+url.pathname+url.search,{method:request.method,headers,body:['GET','HEAD'].includes(request.method)?undefined:Buffer.from(await request.arrayBuffer()),signal:AbortSignal.timeout(52000),redirect:'manual'});
 const out=new Headers(response.headers);out.delete('content-length');out.delete('transfer-encoding');out.delete('connection');out.delete('server');out.set('Cache-Control','no-store');
 const body=Buffer.from(await response.arrayBuffer());
 if(body.length>3*1024*1024&&response.ok){
  const saved=await internal('/api/_netlify/internal/download',{body,headers:{cookie:request.headers.get('cookie')||'','x-result-type':out.get('content-type')||'application/octet-stream','x-result-disposition':out.get('content-disposition')||''}});
  if(!saved.ok)return saved;return Response.json(await saved.json(),{headers:{'X-Inventory-Paged-Download':'1','Cache-Control':'no-store'}});
 }
 return new Response(request.method==='HEAD'?null:body,{status:response.status,headers:out});
}
function workerKey(){const seed=process.env.BOOTSTRAP_TOKEN||'';if(seed.length<32)throw Error('missing_configuration');return createHmac('sha256',seed).update('inventory-worker-v1').digest()}
export function workerTicket(){const value=String(Date.now());return value+'.'+createHmac('sha256',workerKey()).update(value).digest('hex')}
export function verifyTicket(ticket){try{const [time,signature,...extra]=String(ticket||'').split('.');if(extra.length||!/^\d+$/.test(time)||!/^\w{64}$/.test(signature)||!(/^[a-f0-9]+$/).test(signature)||Math.abs(Date.now()-Number(time))>120000)return false;const expected=createHmac('sha256',workerKey()).update(time).digest(),given=Buffer.from(signature,'hex');return given.length===expected.length&&timingSafeEqual(given,expected)}catch{return false}}
export async function wakeWorker(sourceUrl){
 const base=new URL(sourceUrl).origin;if(!origins().includes(base))throw Error('untrusted_worker_origin');
 const response=await fetch(base+'/.netlify/functions/inventory-worker-background',{method:'POST',headers:{'X-Inventory-Worker':workerTicket(),'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(10000)});
 if(!response.ok)throw Error('worker_dispatch_failed');return true;
}
export function stopForTest(){child?.kill();boot=undefined}
