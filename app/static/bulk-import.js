'use strict';
const bulk={rows:[],next:0,busy:false,running:false,paused:false,checking:0,polling:false,owner:null,selected:new Set(),testMode:true,filter:'',sortKey:'status',sortDirection:1};
const bulkLabels={checking:'辨識中',ready:'待上傳',invalid:'無法匯入',uploading:'上傳中',queued:'排隊檢核',processing:'檢核中',completed:'檢核完成',duplicate:'已存在',failed:'失敗'};
const checkLabels={passed:'啟用中',warning:'啟用中',blocked:'不通過'};
function importDisplayStatus(r){if(['checking','ready','uploading','queued','processing'].includes(r.status))return '—';return r.validation_status==='blocked'?'不通過':r.active?'啟用中':'不通過'}
function importProgress(r){if(['checking','ready','uploading','queued','processing'].includes(r.status))return bulkLabels[r.status];if(r.errors)return r.closed&&r.active?`錯誤${r.errors}項；歷史已關帳來源保留`:`錯誤${r.errors}項，未啟用`;if(r.active)return r.warnings?`警示${r.warnings}項，已自動啟用`:'無錯誤，已啟用';return r.message||'未供分析，請檢視原因'}
const importSortColumns=[['filename','檔名'],['hospital','院別'],['department','科別'],['period','分析年月'],['version','版本'],['status','狀態'],['message','說明'],['operation','操作']];
const importCollator=new Intl.Collator('zh-Hant',{numeric:true,sensitivity:'base'});
function importStatusRank(r){const status=importDisplayStatus(r);return status==='不通過'?0:status==='—'?1:2}
function importSortValue(r,key){if(key==='status')return importStatusRank(r);if(key==='version')return r.version??-1;if(key==='active')return r.batch_id?(r.active?1:0):-1;if(key==='message')return (r.valid_count!=null?`有效${r.valid_count}／隔離${r.excluded_count??'—'} `:'')+importProgress(r);if(key==='operation')return r.batch_id?(r.active?'檢視檢核 取消啟用':r.validation_status==='blocked'?'檢視檢核':'檢視檢核 啟用版本'):'等待檢核';return r[key]||''}
function visibleBulkRows(){const f=bulk.filter.toLowerCase();return bulk.rows.filter(r=>!f||[r.filename,r.hospital,r.department,r.period,r.roc_label].join(' ').toLowerCase().includes(f)).sort((a,b)=>{const av=importSortValue(a,bulk.sortKey),bv=importSortValue(b,bulk.sortKey);return bulk.sortDirection*(typeof av==='number'&&typeof bv==='number'?av-bv:importCollator.compare(String(av),String(bv)))})}
function importSortHeaders(){return importSortColumns.map(([key,label])=>`<th scope="col" aria-sort="none"><button type="button" class="import-sort" data-sort-import="${key}" aria-label="依${label}排序">${label} ⇅</button></th>`).join('')}
function updateImportSortHeaders(){document.querySelectorAll('[data-sort-import]').forEach(button=>{const selected=button.dataset.sortImport===bulk.sortKey,label=importSortColumns.find(x=>x[0]===button.dataset.sortImport)[1];button.parentElement.setAttribute('aria-sort',selected?(bulk.sortDirection===1?'ascending':'descending'):'none');button.textContent=label+' '+(selected?(bulk.sortDirection===1?'↑':'↓'):'⇅');button.title=button.dataset.sortImport==='status'?'不通過在前、啟用中在後；檢核中在說明欄顯示進度，點選可反向排序':'點選切換升冪／降冪'})}
function deletableRow(r){return user.role==='admin'&&r.status!=='uploading'&&(r.batch_id||r.job_id||r.file)}
function canActivateImports(){return user.role==='admin'||user.role==='manager'||user.can_activate}
function canSelectImports(){return user.role==='admin'||canActivateImports()}
function selectableRow(r){return deletableRow(r)||(canActivateImports()&&!!r.batch_id)}
function bulkDraw(){
 if(!$('#bulkRows'))return;
 const rows=visibleBulkRows();
 updateImportSortHeaders();
 $('#bulkSummary').textContent=`共 ${bulk.rows.length} 檔／顯示 ${rows.length} 檔；待上傳 ${bulk.rows.filter(r=>r.status==='ready').length}；處理中 ${bulk.rows.filter(r=>['uploading','queued','processing'].includes(r.status)).length}；選取 ${bulk.selected.size} 筆`;
 $('#bulkStart').disabled=bulk.busy||bulk.running||bulk.checking>0||!bulk.rows.some(r=>r.status==='ready');
 if($('#bulkDelete'))$('#bulkDelete').disabled=!bulk.selected.size||bulk.busy||bulk.running||bulk.checking>0;
 if($('#bulkActivate'))$('#bulkActivate').disabled=bulk.busy||bulk.running||bulk.checking>0||!bulk.rows.some(r=>r.batch_id&&bulk.selected.has(String(r.key)));
 $('#bulkRows').innerHTML=rows.map(r=>`<tr data-import-key="${E(r.key)}">${canSelectImports()?`<td><input type="checkbox" aria-label="選取 ${E(r.filename)}" data-select-import="${E(r.key)}" ${bulk.selected.has(String(r.key))?'checked':''} ${selectableRow(r)?'':'disabled'}></td>`:''}<td class="wrap">${E(r.filename)}</td><td>${E(r.hospital||'—')}</td><td>${E(r.department||'未標示')}</td><td>${E(r.roc_label||r.period||'—')}</td><td>${r.version?'V'+r.version:'—'}</td><td class="import-status"><span class="tag ${importDisplayStatus(r)==='不通過'?'bad':''}">${E(importDisplayStatus(r))}</span></td><td class="wrap">${r.valid_count!=null?`有效 ${r.valid_count}／隔離 ${r.excluded_count??'—'}<br>`:''}${E(importProgress(r))}</td><td>${r.batch_id?`<button class="quiet" data-batch="${r.batch_id}">檢視檢核</button>${!r.active&&r.validation_status!=='blocked'&&(user.role==='admin'||user.role==='manager'||user.can_activate)?`<button class="outline" data-activate="${r.batch_id}">啟用版本</button>`:''}${r.active&&(user.role==='admin'||user.role==='manager'||user.can_activate)?`<button class="quiet" data-deactivate-batch="${r.batch_id}">取消啟用</button>`:''}`:r.job_id?'<span class="muted">檢核完成後可操作版本</span>':''}</td></tr>`).join('')||`<tr><td colspan="${canSelectImports()?9:8}">尚無檔案，請拖入或選取Excel月報</td></tr>`;
 resizeImportColumns();
 const all=$('#bulkAll');if(all){const available=rows.filter(selectableRow);const n=available.filter(r=>bulk.selected.has(String(r.key))).length;all.checked=available.length>0&&n===available.length;all.indeterminate=n>0&&n<available.length}
}
async function bulkRefresh(){
 const result=await api('/import/records');bulk.testMode=result.test_delete_mode;
 const local=bulk.rows.filter(r=>r.file&&['checking','ready','invalid','failed','uploading'].includes(r.status));
 bulk.rows=[...local,...result.rows];const keys=new Set(bulk.rows.map(r=>String(r.key)));bulk.selected=new Set([...bulk.selected].filter(k=>keys.has(k)));bulkDraw();
}
async function bulkAdd(files){
 if(user.role==='viewer')return;const added=[];
 for(const file of files){if(bulk.rows.some(r=>r.file&&r.status==='checking'&&r.filename===file.name&&r.file.size===file.size&&r.file.lastModified===file.lastModified))continue;
  const r={key:'local'+(++bulk.next),file,filename:file.name,status:'checking'};
  if(file.size>15*1024*1024){r.status='invalid';r.message='單檔超過15MB，未上傳'}bulk.rows.push(r);if(r.status==='checking')added.push(r);
 }
 bulk.checking++;bulkDraw();try{for(let i=0;i<added.length;i+=100){const part=added.slice(i,i+100);try{const result=await api('/import/inspect',{method:'POST',body:{filenames:part.map(r=>r.filename)}});result.forEach((m,n)=>Object.assign(part[n],m,{status:m.can_import?'ready':'invalid'}))}catch(e){part.forEach(r=>{r.status='failed';r.message=e.message})}bulkDraw()}}finally{bulk.checking--;bulkDraw()}
}
async function bulkStart(){
 if(bulk.running)return;bulk.running=true;bulk.paused=false;bulkDraw();
 async function send(){while(!bulk.paused&&user&&user.id===bulk.owner){const r=bulk.rows.find(x=>x.status==='ready');if(!r)break;r.status='uploading';r.message='';bulkDraw();
  try{const f=new FormData();f.append('file',r.file);const m=await api('/import/auto',{method:'POST',body:f});Object.assign(r,m);bulk.rows=bulk.rows.filter(x=>x===r||x.file||x.filename?.toLowerCase()!==r.filename.toLowerCase()||x.hospital!==r.hospital||x.period!==r.period||Number(x.version||0)>=Number(m.version||0));r.status=m.status==='already_queued'?'queued':m.status;r.file=null}catch(e){r.status='failed';r.message=e.message}bulkDraw();bulkPoll();
 }}try{await Promise.all([send(),send(),send()])}finally{bulk.running=false;bulkDraw();bulkPoll()}
}
async function bulkPoll(){
 if(bulk.polling)return;bulk.polling=true;
 try{while(user&&user.id===bulk.owner){const pending=bulk.rows.filter(r=>r.job_id&&['queued','processing'].includes(r.status));if(!pending.length){if(!bulk.running)await bulkRefresh();break}
  for(let i=0;i<pending.length;i+=200){const part=pending.slice(i,i+200);const jobs=await api('/import/jobs/status',{method:'POST',body:{job_ids:[...new Set(part.map(r=>r.job_id))]}});
   for(const r of part){const j=jobs.find(j=>j.id===r.job_id);if(!j){r.status='failed';r.message='已被同檔名新版取代，或工作已刪除／權限變更';continue}r.status=j.status;r.message=j.result?.error||'';if(j.status==='completed'){r.batch_id=j.result?.batch_id;r.validation_status=j.result?.status;r.active=!!j.result?.active;r.version=j.result?.version||r.version;r.message=j.result?.duplicate?'相同內容已存在，未重複建立版本':(j.result?.active?'已自動啟用':'有錯誤，未啟用')}}
  }bulkDraw();await new Promise(r=>setTimeout(r,1500));
 }}catch(e){if($('#bulkNotice')){$('#bulkNotice').hidden=false;$('#bulkNotice').textContent='查詢中斷：'+e.message+'。請稍後重新開啟此頁。'}}finally{bulk.polling=false}
}
async function bulkDelete(){
 if(bulk.busy)return;
 const selected=bulk.rows.filter(r=>bulk.selected.has(String(r.key)));if(!selected.length)return;
 const note=bulk.testMode?'測試模式允許刪除啟用中及已關帳的匯入資料。':'正式模式僅允許刪除未啟用且未關帳的資料。';
 if(!confirm(`確認刪除選取的 ${selected.length} 筆？\n${note}\n啟用版本刪除後將停止分析，不會自動換成其他版本。來源與稽核紀錄會保留。`))return;
 const reason=prompt('請填寫本次刪除原因：','測試資料清理');if(!reason?.trim())return;
 bulk.busy=true;bulkDraw();
 try{const bids=[...new Set(selected.filter(r=>r.batch_id).map(r=>r.batch_id))],jids=[...new Set(selected.filter(r=>!r.batch_id&&r.job_id).map(r=>r.job_id))];const items=[...bids.map(id=>['batch',id]),...jids.map(id=>['job',id])];
  for(let i=0;i<items.length;i+=200){const part=items.slice(i,i+200);await api('/import/delete',{method:'POST',body:{batch_ids:part.filter(x=>x[0]==='batch').map(x=>x[1]),job_ids:part.filter(x=>x[0]==='job').map(x=>x[1]),reason,confirmed:true}})}
  bulk.rows=bulk.rows.filter(r=>!bulk.selected.has(String(r.key)));bulk.selected.clear();await bulkRefresh();toast('所選資料已刪除，已停止供分析；來源與稽核紀錄保留。');
 }catch(e){toast('刪除未全部完成：'+e.message,true);await bulkRefresh()}finally{bulk.busy=false;bulkDraw()}
}
async function bulkActivate(){
 if(bulk.busy)return;
 const selected=bulk.rows.filter(r=>bulk.selected.has(String(r.key))),versions=selected.filter(r=>r.batch_id);
 if(!versions.length)return;
 const groups=new Map();for(const r of versions){const scope=r.hospital+'/'+r.period;groups.set(scope,[...(groups.get(scope)||[]),r])}
 const conflicts=[...groups.entries()].filter(([scope,rows])=>new Set(rows.map(r=>r.batch_id)).size>1);
 if(conflicts.length){toast('同院同月選取多個版本，本次尚未啟用任何資料。請每院每月只保留一個版本：'+conflicts.map(([scope,rows])=>scope+' '+rows.map(r=>'V'+r.version).join('、')).join('；'),true);return}
 if(!confirm(`確認啟用選取的 ${versions.length} 個版本？\n同院同月將取代原啟用版本；不通過、已關帳或無有效明細的項目會略過。\n未完成匯入的選取項目不會啟用。`))return;
 let reason='';if(versions.some(r=>!r.active&&r.validation_status==='warning')){reason=prompt('所選版本含警示，請填寫統一的警示確認／啟用理由：');if(!reason?.trim())return}
 bulk.busy=true;bulkDraw();
 try{
  const result=await api('/batches/activate-selected',{method:'POST',body:{batch_ids:[...new Set(versions.map(r=>r.batch_id))],reason,confirmed:true}});
  const skippedLocal=selected.filter(r=>!r.batch_id);
  $('#bulkActionResult').innerHTML=`<p role="status">已啟用 ${result.activated} 筆；原已啟用 ${result.unchanged} 筆；略過 ${result.skipped+skippedLocal.length} 筆。</p>`+table(['來源檔案','院別／月份','版本','處理結果'],[...result.results.map(x=>`<tr><td class="wrap">${E(versions.find(r=>r.batch_id===x.batch_id)?.filename||'')}</td><td>${E(x.hospital)}／${E(x.period)}</td><td>${x.version?'V'+x.version:'—'}</td><td class="wrap">${E(x.message)}</td></tr>`),...skippedLocal.map(x=>`<tr><td>${E(x.filename)}</td><td>${E(x.hospital)}／${E(x.period)}</td><td>—</td><td>尚無可啟用版本，未啟用</td></tr>`)]);
  await bulkRefresh();toast(`批次啟用完成：已啟用${result.activated}筆，略過${result.skipped+skippedLocal.length}筆。`);
 }catch(e){toast(e.message,true);await bulkRefresh()}finally{bulk.busy=false;bulkDraw()}
}
async function renderImport(){
 if(bulk.owner!==user.id){bulk.rows=[];bulk.selected.clear();bulk.owner=user.id}
 if(!bulk.running)await bulkRefresh();const cat=await api('/categories');
 $('#content').innerHTML=panel('分類主檔與檢核原則',`<p>當前分類版本：<strong>${cat.version?'V'+cat.version:'尚未匯入'}</strong>／${cat.codes}個品號。新主檔只用於後續匯入；歷史月報保留當時的主檔版本。依品號套用分類與主檔品名，來源單位不自動換算。</p><button id="viewCategory" class="outline" ${cat.version?'':'disabled'}>查看當前分類版本</button>${user.role==='admin'?'<form id="categoryForm"><label>分類主檔<input type="file" name="file" accept=".xlsx" required></label><button class="outline">匯入分類主檔</button></form>':''}<p class="caption">保留來源列與版本。正負1元內金額勾稽差異預設收合，其餘錯誤及警示仍需確認。</p>`)+panel('批次匯入院別月報',`<p>依檔名自動辨識院別、年月及科別。例如 <strong>11401_DE進銷存_耗材_RCW.xlsx</strong> → DE院／民國114年01月／RCW。</p><div id="bulkDrop" class="bulk-drop" tabindex="0" role="button" aria-label="拖入或選取多個Excel月報">拖曳多個 .xlsx 至此，或點此多選<input id="bulkFiles" type="file" accept=".xlsx" multiple hidden></div><div class="action-row"><button id="bulkStart" class="primary">開始匯入</button><button id="bulkRetry" class="outline">重試失敗檔案</button></div><p id="bulkSummary" role="status"></p><p id="bulkNotice" role="status" hidden></p><label>搜尋院別、月份或檔名<input id="bulkFilter" placeholder="例如 DE、2026-08" value="${E(bulk.filter)}"></label><div class="bulk-selection-tools action-row" id="bulkSelectionTools">${canActivateImports()?'<button id="bulkActivate" class="primary">啟用選取資料</button>':''}${user.role==='admin'?'<button id="bulkDelete" class="danger">刪除選取資料</button>':''}<button id="resetImportWidths" class="quiet" style="margin-left:auto">重設欄寬</button></div><div class="scroll bulk-list"><table id="bulkTable"><thead><tr>${canSelectImports()?'<th><input type="checkbox" id="bulkAll" aria-label="全選目前篩選資料"></th>':''}${importSortHeaders()}</tr></thead><tbody id="bulkRows"></tbody></table></div><div id="bulkActionResult"></div>`)+bedPanel();
 const drop=$('#bulkDrop'),input=$('#bulkFiles');drop.onclick=e=>{if(e.target!==input&&user.role!=='viewer')input.click()};drop.onkeydown=e=>{if(['Enter',' '].includes(e.key)&&user.role!=='viewer'){e.preventDefault();input.click()}};input.onchange=()=>{bulkAdd(input.files);input.value=''};drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging')};drop.ondragleave=()=>drop.classList.remove('dragging');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragging');bulkAdd(e.dataTransfer.files)};
 $('#bulkStart').onclick=bulkStart;
 $('#bulkRetry').onclick=async()=>{const files=bulk.rows.filter(r=>r.status==='failed'&&r.file).map(r=>r.file);bulk.rows=bulk.rows.filter(r=>!(r.status==='failed'&&r.file));await bulkAdd(files)};
 $('#bulkFilter').oninput=e=>{bulk.filter=e.target.value;bulkDraw()};$('#bulkRows').onchange=e=>{const el=e.target.closest('[data-select-import]');if(el){if(el.checked)bulk.selected.add(el.dataset.selectImport);else bulk.selected.delete(el.dataset.selectImport);bulkDraw()}};
 $('#resetImportWidths').onclick=()=>{localStorage.removeItem('inventory.import.widths.v052');resizeImportColumns(true)};
 if($('#bulkAll'))$('#bulkAll').onchange=e=>{for(const r of visibleBulkRows().filter(selectableRow)){if(e.target.checked)bulk.selected.add(String(r.key));else bulk.selected.delete(String(r.key))}bulkDraw()};if($('#bulkDelete'))$('#bulkDelete').onclick=bulkDelete;if($('#bulkActivate'))$('#bulkActivate').onclick=bulkActivate;
 document.querySelectorAll('[data-sort-import]').forEach(button=>button.onclick=()=>{const key=button.dataset.sortImport;bulk.sortDirection=bulk.sortKey===key?-bulk.sortDirection:1;bulk.sortKey=key;bulkDraw()});
 $('#viewCategory').onclick=viewCurrentCategory;
 if($('#categoryForm'))$('#categoryForm').onsubmit=async e=>{e.preventDefault();try{await api('/categories',{method:'POST',body:new FormData(e.target)});await load();toast('分類主檔已建立新版本')}catch(err){toast(err.message,true)}};
 bulkDraw();bulkPoll();bindBeds();
}
window.addEventListener('beforeunload',e=>{if(bulk.rows.some(r=>['ready','uploading','checking'].includes(r.status))){e.preventDefault();e.returnValue=''}});

function resizeImportColumns(reset=false){
 const t=$('#bulkTable');if(!t)return;
 let saved={};try{saved=JSON.parse(localStorage.getItem('inventory.import.widths.v052')||'{}')}catch{}
 const headers=[...t.querySelectorAll('thead th')],ctx=document.createElement('canvas').getContext('2d');ctx.font=getComputedStyle(t).font;
 const previous=t.querySelector('colgroup');if(previous)previous.remove();const group=document.createElement('colgroup');t.prepend(group);
 const keys=headers.map((th,i)=>th.querySelector('[data-sort-import]')?.dataset.sortImport||'selection');
 const widths=headers.map((th,i)=>{if(saved[keys[i]]&&!reset)return saved[keys[i]];let max=48;for(const row of t.rows){const cell=row.cells[i];if(cell){for(const line of cell.textContent.split('\n'))max=Math.max(max,ctx.measureText(line.trim()).width)}}return Math.ceil(max+40)});
 widths.forEach(w=>{const col=document.createElement('col');col.style.width=w+'px';group.append(col)});const setWidth=()=>{t.style.width=widths.reduce((a,b)=>a+b,0)+'px'};setWidth();t.style.tableLayout='fixed';
 headers.forEach((th,i)=>{th.querySelector('.column-resizer')?.remove();const handle=document.createElement('span');handle.className='column-resizer';handle.setAttribute('role','separator');handle.setAttribute('aria-label','調整'+(importSortColumns.find(x=>x[0]===keys[i])?.[1]||'選取')+'欄寬');handle.setAttribute('aria-orientation','vertical');handle.tabIndex=0;th.append(handle);
 const save=()=>{saved[keys[i]]=widths[i];localStorage.setItem('inventory.import.widths.v052',JSON.stringify(saved))};
 handle.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();widths[i]=Math.max(64,widths[i]+(e.key==='ArrowLeft'?-16:16));group.children[i].style.width=widths[i]+'px';setWidth();save()};
 handle.onpointerdown=e=>{e.preventDefault();e.stopPropagation();const start=e.clientX,width=widths[i];document.body.classList.add('resizing-columns');const move=ev=>{widths[i]=Math.max(64,width+ev.clientX-start);group.children[i].style.width=widths[i]+'px';setWidth()};const up=()=>{document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.body.classList.remove('resizing-columns');save()};document.addEventListener('pointermove',move);document.addEventListener('pointerup',up)};
 handle.onclick=e=>e.stopPropagation();
 });
}
