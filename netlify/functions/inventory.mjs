import { forward,wakeWorker,errorResponse } from '../lib/runtime.mjs';
import { createHandler } from '../lib/queue.mjs';
export default createHandler({forward,wakeWorker,errorResponse});
export const config={path:'/api/*'};
