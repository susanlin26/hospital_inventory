'use strict';
const ruleLabels112={high_days:'高庫存低耗用－週轉偏慢門檻（天）',severe_days:'高庫存低耗用－週轉嚴重偏慢門檻（天）',low_days:'低庫存風險－推估可用天數下限（天）',idle_warn_days:'無耗用仍有庫存－持續未耗用提醒門檻（天）',idle_days:'無耗用仍有庫存－長期未耗用門檻（天）',change_pct:'耗用增減%',change_amount:'耗用增減金額 (元)',purchase_pct:'採購單價增減%',purchase_amount:'單價變動影響金額（元）',abc_a:'ABC分類－A類累計占比上限（%）',abc_b:'ABC分類－B類累計占比上限（%）'};
const ruleMoney112=new Set(['change_amount','purchase_amount']);
function moneyText112(value){const raw=String(value??'').replaceAll(',','');if(!/^\d+(\.\d+)?$/.test(raw))return raw;const [whole,fraction]=raw.split('.');return whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+(fraction?'.'+fraction:'')}
function shiftMonth112(month,offset){const [year,m]=month.split('-').map(Number),total=year*12+m-1+offset;return String(Math.floor(total/12)).padStart(4,'0')+'-'+String(total%12+1).padStart(2,'0')}
// Built-in fallbacks are shown only in gaps left by custom hospital rules.
function ruleSegments112(versions){
 const active=versions.filter(v=>!v.disabled_at),result=[];
 for(const v of active){
  if(!v.body._system_default){result.push({...v,start:v.body.effective_from||'0001-01',end:v.body.effective_until});continue}
  let segments=[{start:v.body.effective_from||'0001-01',end:v.body.effective_until}];
  const overrides=active.filter(x=>!x.body._system_default&&!x.body._category).sort((a,b)=>(a.body.effective_from||'').localeCompare(b.body.effective_from||''));
  for(const x of overrides){const a=x.body.effective_from||'0001-01',b=x.body.effective_until;segments=segments.flatMap(s=>{
   if((s.end&&s.end<a)||(b&&b<s.start))return [s];const parts=[];
   if(s.start<a)parts.push({start:s.start,end:shiftMonth112(a,-1)});
   if(b&&(!s.end||b<s.end))parts.push({start:shiftMonth112(b,1),end:s.end});return parts;
  })}
  result.push(...segments.map(s=>({...v,...s})));
 }
 return result.sort((a,b)=>b.start.localeCompare(a.start)||b.id-a.id);
}
async function drawRulePeriods112(){
 const target=$('#rulePeriods112');if(!target)return;
 const selected=$('#rulesHospitals111')?.value||data.hospital,codes=selected==='ALL'?hs.map(h=>h.code):[selected],request=String(Date.now())+Math.random();target.dataset.request=request;
 try{
 const groups=await Promise.all(codes.map(async h=>({hospital:h,versions:await api('/rules/'+h+'/history')})));if(target.dataset.request!==request||!target.isConnected)return;
 let all=[];const card=(v,h,history=false)=>{const index=all.push({...v,hospital:h})-1;return `<article class="rule-period"><strong>${E(hs.find(x=>x.code===h)?.name||h)}／${E(v.body._category||'整院預設')}／${E(v.start||v.body.effective_from||'舊版')} ～ ${E(v.end||v.body.effective_until||'持續適用')}</strong>${v.body._system_default?'<small>系統預設；僅在未設定自訂門檻的期間適用</small>':''}<div class="rule-actions112"><button class="quiet" data-rule-values112="${index}">查看所有設定值</button>${!history&&!v.body._system_default?`<button class="quiet" data-rule-disable112="${index}">停用門檻</button>`:''}</div></article>`};
 const active=groups.flatMap(g=>ruleSegments112(g.versions).map(v=>card(v,g.hospital))),history=groups.flatMap(g=>g.versions.filter(v=>v.disabled_at).map(v=>card(v,g.hospital,true)));
 target.innerHTML='<h2>異常門檻適用時間段</h2><p class="caption">各段未停用的門檻均列於下方；已結束的期間仍可供該月份查用。</p>'+ (active.join('')||'<p>尚無自訂門檻，使用系統預設。</p>')+'<details id="ruleHistory"><summary>已停用歷史紀錄（'+history.length+'筆）</summary>'+history.join('')+'</details>';
 target.querySelectorAll('[data-rule-values112]').forEach(b=>b.onclick=()=>{
 const v=all[Number(b.dataset.ruleValues112)],body=v.body,categories=body._category?[body._category]:['',...Object.keys(body.categories||{})];
 trackingModal('門檻所有設定值',`<p>${E(hs.find(h=>h.code===v.hospital)?.name||v.hospital)}／${E(v.start||body.effective_from||'舊版')} ～ ${E(v.end||body.effective_until||'持續適用')}</p>`+table(['設定項目',...categories.map(c=>c||'整院預設')],Object.entries(ruleLabels112).map(([key,label])=>'<tr><th>'+E(label)+'</th>'+categories.map(c=>{const value=body._category?body[key]:c?(body.categories[c]?.[key]??body[key]):body[key];return '<td>'+E(value==null?'未記錄':ruleMoney112.has(key)?moneyText112(value):value)+'</td>'}).join('')+'</tr>')));
 });
 target.querySelectorAll('[data-rule-disable112]').forEach(b=>b.onclick=()=>{
 const v=all[Number(b.dataset.ruleDisable112)];trackingModal('停用門檻','<p>停用後保留歷史紀錄，該期間將重新依其他適用門檻判定。</p><form id="disableRule112"><label>停用原因<input name="reason" required></label><button>確認停用門檻</button></form><p id="disableRuleError112" role="alert"></p>');
 $('#disableRule112').onsubmit=async e=>{e.preventDefault();try{await api('/rules/'+v.hospital+'/'+v.id,{method:'DELETE',body:Object.fromEntries(new FormData(e.target))});$('#detail').close();invalidateAnalysisCache();await load()}catch(err){$('#disableRuleError112').textContent=err.message}};
 });
 }catch(err){if(target.isConnected)target.textContent=err.message}
}
const settingsBefore112=renderSettings;
renderSettings=async function(){
 await settingsBefore112();const form=$('#rulesForm');
 if(form){
 const button=form.querySelector('button');button.parentElement.classList.add('rule-save-row112');button.insertAdjacentHTML('afterend','<span id="rulesSaveStatus112" class="rule-save-status112" role="status"></span>');
 for(const key of ruleMoney112){const input=form.querySelector('[name='+key+']');input.type='text';input.dataset.ruleMoney='true';input.inputMode='decimal';input.removeAttribute('step');input.removeAttribute('min');input.pattern='[0-9]+(,[0-9]{3})*(\\.[0-9]+)?';input.onblur=()=>input.value=moneyText112(input.value)}
 const format=()=>form.querySelectorAll('[data-rule-money]').forEach(input=>input.value=moneyText112(input.value));format();
 const category=form.querySelector('[name=category]'),previousCategory=category.onchange;category.onchange=()=>{previousCategory();format()};
 const scope=$('#rulesHospitals111'),previousScope=scope.onchange;scope.onchange=async()=>{await previousScope();format();await drawRulePeriods112()};
 const panel=[...document.querySelectorAll('#content > .panel')].find(p=>p.querySelector('h2')?.textContent==='異常門檻適用時間段');
 if(panel){panel.id='rulePeriods112'}else form.closest('.panel').insertAdjacentHTML('afterend','<section class="panel" id="rulePeriods112"></section>');await drawRulePeriods112();
 }
 if(user.role==='admin'){
 $('#content').insertAdjacentHTML('beforeend',panel('醫院管理',`<p>先建立醫院代號與名稱，即可使用該代號匯入月報，並在帳號設定授權使用。</p><form id="hospitalForm112" class="form-grid"><label>醫院代號<input name="code" required pattern="[A-Za-z][A-Za-z0-9]{1,11}" maxlength="12" placeholder="例如：AB"></label><label>醫院名稱<input name="name" required maxlength="80" placeholder="請輸入醫院名稱"></label><p class="wide caption">代號為2至12碼英文字母或數字，首碼須為英文。月報檔名範例：11509_AB進銷存表_耗材.xlsx。建立後代號固定，請確認後再儲存。</p><div class="wide"><button>新增醫院</button><span id="hospitalNotice112" role="status"></span></div></form>`));
 $('#hospitalForm112').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const created=await api('/hospitals',{method:'POST',body:Object.fromEntries(new FormData(e.target))}),current=$('#hospital').value;hs=await api('/hospitals');$('#hospital').innerHTML='<option value="ALL">醫院合併總覽</option>'+hs.map(h=>'<option value="'+E(h.code)+'">'+E(h.name)+'（'+E(h.code)+'）</option>').join('');$('#hospital').value=current;await load();$('#hospitalNotice112').textContent='已新增 '+created.name+'（'+created.code+'），可匯入月報及設定帳號授權。'}catch(err){$('#hospitalNotice112').textContent=err.message}finally{button.disabled=false}};
 }
};
