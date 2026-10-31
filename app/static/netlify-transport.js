'use strict';
// Preserve existing forms/download buttons; split only payloads that exceed function limits.
(()=>{
 const original=window.fetch.bind(window);
 async function checked(url,options){const response=await original(url,options);if(!response.ok){let message='檔案傳輸失敗，請重新操作';try{message=(await response.json()).detail||message}catch{}throw Error(message)}return response}
 window.fetch=async function(input,options={}){
  const url=new URL(typeof input==='string'?input:input.url,location.href);
  if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))return original(input,options);
  if(options.body instanceof FormData){
   const entries=[...options.body.entries()],files=entries.filter(([,v])=>v instanceof Blob);
   if(files.length===1&&files[0][1].size>2*1024*1024){
    const [field,file]=files[0],headers=new Headers(options.headers);headers.delete('Content-Type');
    const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer()),sha256=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');
    const created=await checked('/api/netlify/uploads',{method:'POST',headers:new Headers([...headers,['Content-Type','application/json']]),body:JSON.stringify({path:url.pathname,field,filename:file.name,size:file.size,sha256,fields:entries.filter(([,v])=>!(v instanceof Blob))})});
    const data=await created.json();
    for(let offset=0,part=0;offset<file.size;offset+=data.chunk_size,part++)await checked('/api/netlify/uploads/'+data.id+'/'+part,{method:'PUT',headers,body:file.slice(offset,offset+data.chunk_size)});
    return original('/api/netlify/uploads/'+data.id+'/commit',{method:'POST',headers});
   }
  }
  const response=await original(input,options);
  if(response.headers.get('X-Inventory-Paged-Download')!=='1')return response;
  const info=await response.json(),parts=[];
  for(let offset=0;offset<info.size;offset+=1024*1024){const part=await checked('/api/netlify/downloads/'+encodeURIComponent(info.token)+'?offset='+offset);parts.push(await part.arrayBuffer())}
  const headers=new Headers({'Content-Type':info.type,'Cache-Control':'no-store'});if(info.disposition)headers.set('Content-Disposition',info.disposition);
  return new Response(new Blob(parts,{type:info.type}),{status:200,headers});
 };
})();
