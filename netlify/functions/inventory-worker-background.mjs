import { internal,verifyTicket,wakeWorker,errorResponse } from '../lib/runtime.mjs';
import { safeCode } from '../lib/queue.mjs';
export default async function(request){
 if(request.method!=='POST'||!verifyTicket(request.headers.get('X-Inventory-Worker'))){console.warn('[inventory-worker] rejected invalid ticket');return errorResponse('Not Found',404)}
 console.info('[inventory-worker] started');
 try{
  const response=await internal('/api/_netlify/internal/pump');
  if(!response.ok)throw Error('background_worker_failed_'+response.status);
  const result=await response.json();
  console.info('[inventory-worker] finished',JSON.stringify({processed:result.processed,pending:result.pending,busy:result.busy}));
  if(result.pending&&!result.busy)await wakeWorker(request.url);
  return new Response(null,{status:204});
 }catch(e){console.error('[inventory-worker] failed',safeCode(e));throw Error('inventory_background_failed')}
}
export const config={background:true};
