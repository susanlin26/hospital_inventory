import test from 'node:test';
import assert from 'node:assert/strict';
import {workerTicket,verifyTicket,forward} from '../netlify/lib/runtime.mjs';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
process.env.BOOTSTRAP_TOKEN='adapter-local-test-secret-'.repeat(3);
test('worker only accepts authenticated bounded tickets',()=>{
 const ticket=workerTicket();assert.equal(verifyTicket(ticket),true);assert.equal(verifyTicket(ticket+'f'),false);assert.equal(verifyTicket(''),false);assert.equal(verifyTicket('0.'+ticket.split('.')[1]),false);
});
test('public function never forwards its private endpoints',async()=>{
 const r=await forward(new Request('https://example.netlify.app/api/_netlify/internal/pump'));assert.equal(r.status,404);
 const direct=await forward(new Request('https://example.netlify.app/.netlify/functions/inventory'));assert.equal(direct.status,404);
});
test('bundled interpreter archives match their immutable build manifest',async()=>{
 const manifest=JSON.parse(await readFile(new URL('../backend/runtime/manifest.json',import.meta.url),'utf8'));
 for(const [name,v]of Object.entries(manifest.archives)){const bytes=await readFile(new URL('../backend/runtime/'+name,import.meta.url));assert.equal(createHash('sha256').update(bytes).digest('hex'),v.sha256);assert.equal(bytes.length,v.size)}
});
