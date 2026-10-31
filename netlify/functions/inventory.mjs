import { forward,wakeWorker,errorResponse } from '../lib/runtime.mjs';
let lastWake=0;
export default async function(request){
 try{
  const response=await forward(request);
  const path=new URL(request.url).pathname;
  const trigger=path==='/api/import'||path==='/api/import/auto'||path==='/api/categories'||path.endsWith('/commit')||path.startsWith('/api/rules')||path.startsWith('/api/batches')||path.startsWith('/api/jobs')||path.startsWith('/api/monthly-cases');
  if(response.ok&&trigger&&(request.method!=='GET'||Date.now()-lastWake>3000)){
   lastWake=Date.now();
   try{await wakeWorker(request.url)}catch{response.headers.set('X-Inventory-Queue','pending')}
  }
  return response;
 }catch{return errorResponse('服務暫時無法回應，請稍後重試；若持續發生請聯絡管理員')}
}
export const config={path:'/api/*'};
