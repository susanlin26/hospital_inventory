'use strict';
// Keep the tracking controls in a single, predictable toolbar after every redraw.
const arrangeBefore111=mwArrange106;
mwArrange106=function(){
 arrangeBefore111();
 const controls=$('#mwList .value-switch104'),filters=$('#mwPanel > .mw-filters');
 if(controls&&filters){const wrapper=controls.parentElement;filters.append(controls);if(!wrapper.childNodes.length)wrapper.remove()}
 const refresh=$('#mwRefresh'),exportButton=$('#mwExport');
 if(refresh&&exportButton){exportButton.before(refresh);refresh.classList.add('mw-refresh111')}
};
const crossMetricsBefore111=drawCrossMetrics;
drawCrossMetrics=function(){
 crossMetricsBefore111();const root=$('#cross-metrics'),nodes=[...root.children];
 const headings=nodes.filter(n=>n.tagName==='H3');if(headings.length!==2)return;
 const grid=document.createElement('div');grid.className='cross-metric-grid111';
 const blocks=headings.map(h=>{const start=nodes.indexOf(h),end=nodes.findIndex((n,i)=>i>start&&n.classList.contains('scroll')),table=nodes[end],block=document.createElement('section');block.append(...nodes.slice(start,end));return {block,table}});
 grid.append(blocks[0].block,blocks[1].block,blocks[0].table,blocks[1].table);root.querySelector('h2').after(grid);
 grid.querySelectorAll('table').forEach(t=>t.classList.add('unified-table'));
};
const crossCategoriesBefore111=drawCrossCategories;
drawCrossCategories=function(){
 crossCategoriesBefore111();const k=crossState.catMetric,t=$('#cross-categories table');if(!t)return;t.classList.add('unified-table');
 if(!['used','standard30','ending'].includes(k))return;
 const rows=crossSortedCategories(),foot=t.createTFoot();foot.innerHTML='<tr class="analysis-total"><th>合計</th>'+crossState.hospitals.map(h=>{
 const values=rows.map(r=>r.cells[h].metrics[k].value),present=values.filter(v=>v!=null);
 return '<td>'+(present.length?crossValue(sumTrackingDecimals(present),k)+(values.length!==present.length?'<small>僅加總已提供數值</small>':''):'—')+'</td>';
 }).join('')+'</tr>';
};
const crossItemsBefore111=drawCrossItems;
drawCrossItems=async function(...args){await crossItemsBefore111(...args);$('#cross-items table')?.classList.add('unified-table')};

// Each bulk update only changes edited values; each hospital keeps its other rules.
const settingsBefore111=renderSettings;
renderSettings=async function(){
 await settingsBefore111();const old=$('#rulesForm');if(!old)return;
 const f=old.cloneNode(true);old.replaceWith(f);
 f.insertAdjacentHTML('afterbegin','<label>醫院範圍<select id="rulesHospitals111"><option value="ALL">全部醫院</option>'+hs.map(h=>'<option value="'+E(h.code)+'">'+E(h.name)+'</option>').join('')+'</select></label><p class="wide caption" id="rulesScopeNote111"></p>');
 const scope=$('#rulesHospitals111'),category=f.querySelector('[name=category]'),dirty=new Set();let rules=data.rules,serial=0;
 scope.value=selector().hospital==='ALL'?'ALL':data.hospital;
 const apply=()=>{
 const values={...rules,...rules.categories?.[category.value]};
 f.querySelectorAll('input[type=number],input[data-rule-money]').forEach(input=>{input.value=values[input.name]??''});
 f.querySelector('[name=effective_from]').value=scope.value==='ALL'?selector().period:(values.effective_from||selector().period);
 f.querySelector('[name=effective_until]').value=scope.value==='ALL'?'':(values.effective_until||'');dirty.clear();
 $('#rulesScopeNote111').textContent=scope.value==='ALL'?'將套用至全部授權醫院。僅更新您修改的門檻，其餘各院設定保持原值；新增版本依下方生效月份適用。':'顯示所選醫院目前生效的門檻。';
 };
 const refresh=async()=>{const request=++serial;try{const h=scope.value==='ALL'?data.hospital:scope.value;const context=await api('/settings/context?'+new URLSearchParams({hospital:h,month:selector().period}));if(request!==serial)return;rules=context.rules;apply()}catch(err){toast(err.message,true)}};
 scope.onchange=refresh;category.onchange=apply;
 f.querySelectorAll('input[type=number],input[data-rule-money]').forEach(input=>input.addEventListener('input',()=>dirty.add(input.name)));
 apply();f.onsubmit=async e=>{
 e.preventDefault();const full=Object.fromEntries(new FormData(f)),all=scope.value==='ALL';for(const key of ['change_amount','purchase_amount'])if(key in full)full[key]=full[key].replaceAll(',','');
 if(all&&!dirty.size){toast('請先修改要套用至全部醫院的門檻',true);return}
 const body=all?Object.fromEntries(Object.entries(full).filter(([key])=>dirty.has(key)||['category','effective_from','effective_until'].includes(key))):full;
 const url=all?'/rules-batch':'/rules/'+scope.value,submit=()=>api(url,{method:'PUT',body:all?{hospitals:hs.map(h=>h.code),rules:body}:body});
 const button=f.querySelector('button');button.disabled=true;
 try{
  try{await submit()}catch(err){if(!err.message.includes('重疊'))throw err;if(!confirm('生效期間與目前門檻重疊，是否覆蓋？'+(all?'\n將一併套用全部醫院；任一醫院無法更新時，全部取消。':'')))return;body.overwrite=true;await submit()}
  invalidateAnalysisCache();await load();const notice=$('#rulesSaveStatus112');if(notice)notice.textContent='門檻已儲存，異常將依生效設定重新計算';
 }catch(err){toast(err.message,true)}finally{button.disabled=false}
 };
};
