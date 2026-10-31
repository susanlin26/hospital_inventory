import { wakeWorker,origins } from '../lib/runtime.mjs';
export default async function(){const allowed=origins(),source=[process.env.DEPLOY_PRIME_URL,process.env.URL,...allowed].find(url=>url&&allowed.includes(new URL(url).origin));await wakeWorker(source);return new Response(null,{status:204})}
export const config={schedule:'*/5 * * * *'};
