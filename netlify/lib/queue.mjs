// Progress polling retries dispatch; preview deploys have no automatic schedule.
export function queueTrigger(path){
 return path==='/api/import'||path==='/api/import/auto'||path==='/api/import/jobs/status'||path==='/api/import/records'||path==='/api/categories'||path.endsWith('/commit')||path.startsWith('/api/rules')||path.startsWith('/api/batches')||path.startsWith('/api/jobs')||path.startsWith('/api/monthly-cases');
}
export function createHandler({forward,wakeWorker,errorResponse,now=Date.now,log=console}){
 let lastWake=-Infinity;
 return async function(request){
  try{
   const response=await forward(request),path=new URL(request.url).pathname;
   const polling=path==='/api/import/jobs/status'||path==='/api/import/records';
   let pending=true;
   if(response.ok&&polling){
    const data=await response.clone().json();
    pending=(Array.isArray(data)?data:data.rows||[]).some(row=>row.status==='queued'||row.status==='processing');
   }
   if(response.ok&&queueTrigger(path)&&pending&&((!polling&&request.method!=='GET')||now()-lastWake>3000)){
    lastWake=now();
    try{await wakeWorker(request.url,request.headers.get('origin'))}
    catch(e){lastWake=-Infinity;response.headers.set('X-Inventory-Queue','pending');log.error('[inventory-queue] dispatch failed',safeCode(e))}
   }
   return response;
  }catch(e){log.error('[inventory-api] request failed',safeCode(e));return errorResponse('服務暫時無法回應，請稍後重試；若持續發生請聯絡管理員')}
 };
}
// Never log URLs, tokens, request bodies, SQL, or raw exception messages.
export function safeCode(error){
 const code=String(error?.message||'');
 return /^(missing_runtime|unsupported_architecture|runtime_integrity|missing_configuration|bridge_exit|bridge_timeout|untrusted_worker_origin|worker_dispatch_failed_\d{3}|worker_redirect|background_worker_failed_\d{3})$/.test(code)?code:'runtime_error';
}
