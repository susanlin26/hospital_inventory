import { internal,verifyTicket,wakeWorker,errorResponse } from '../lib/runtime.mjs';
export default async function(request){
 if(request.method!=='POST'||!verifyTicket(request.headers.get('X-Inventory-Worker')))return errorResponse('Not Found',404);
 const response=await internal('/api/_netlify/internal/pump');
 if(!response.ok)throw Error('background_worker_failed');
 const result=await response.json();
 if(result.pending&&!result.busy)await wakeWorker(request.url);
 return new Response(null,{status:204});
}
export const config={background:true};
