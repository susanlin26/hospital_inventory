'use strict';
const pageDescriptions097={dashboard:'掌握各院耗用、庫存與異常處理重點。',analysis:'檢視耗用趨勢，追溯分類與品項差異。',turnover:'掌握存貨水位、週轉情形與庫存風險。',compare:'比較授權醫院的主要指標與耗用差異。',findings:'確認異常原因，追蹤處理進度與改善結果。',import:'匯入月報、分類與床數，檢查資料及版本。',settings:'管理異常門檻、帳號與院別授權。'};
const iconPaths097={dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',analysis:'M3 3v18h18 M6 16l5-6 4 3 6-8 M16 5h5v5',turnover:'M3 13h8v8H3z M13 13h8v8h-8z M8 3h8l3 8H5z',compare:'M3 21V3h10v18 M13 9h8v12 M6 7h1 M9 7h1 M6 11h1 M9 11h1 M16 13h2 M16 17h2',findings:'M8 5H5v16h14V5h-3 M8 3h8v5H8z M8 14l3 3 5-6',import:'M5 3h10l5 5v13H5z M15 3v6h5 M12 18v-7 M9 14l3-3 3 3',settings:'M12 3v3 M12 18v3 M3 12h3 M18 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2 M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0'};
function refreshChrome097(){
 const nav=$('#nav');if(!nav||!user)return;
 if(!nav.querySelector('.nav-group')){
  for(const [title,keys] of [['分析與比較',['dashboard','analysis','turnover','compare']],['追蹤與處理',['findings']],['資料與設定',['import','settings']]]){
   const nodes=keys.map(k=>nav.querySelector('[data-page="'+k+'"]')).filter(Boolean);if(!nodes.length)continue;
   const group=document.createElement('div');group.className='nav-group';const heading=document.createElement('p');heading.textContent=title;group.append(heading);nav.append(group);
   nodes.forEach(b=>{const k=b.dataset.page;b.querySelector('.num')?.remove();b.insertAdjacentHTML('afterbegin',`<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${iconPaths097[k]}"/></svg>`);group.append(b)});
  }
 }
 $('#environment').textContent=(user.environment||'環境未設定')+'｜v'+(user.version||window.systemInfo?.version||'');
 $('#pageDescription').textContent='';$('#pageDescription').hidden=true;
 document.querySelectorAll('#nav [data-page]').forEach(b=>{if(b.dataset.page===page)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
 document.querySelectorAll('#content input[type=file]:not([data-localized])').forEach(input=>{
  input.dataset.localized='true';if(input.hidden)return;
  const wrap=document.createElement('div');wrap.className='file-picker';
  const label=document.createElement('span');label.className='file-picker-button';label.textContent='選擇檔案';
  const name=document.createElement('span');name.className='file-picker-name';name.textContent='尚未選擇檔案';
  input.before(wrap);wrap.append(label,name,input);input.addEventListener('change',()=>{name.textContent=[...input.files].map(f=>f.name).join('、')||'尚未選擇檔案'});
 });
 document.querySelectorAll('#content table').forEach(t=>{const headers=[...t.querySelectorAll('thead tr:first-child th')];headers.forEach((h,i)=>{if(/^(狀態|啟用|處理情形|處理進度|處理狀態)$/.test(h.textContent.replace(/[⇅▼▲↑↓]/g,'').trim())){h.classList.add('status-cell');t.querySelectorAll('tbody tr').forEach(r=>r.children[i]?.classList.add('status-cell'))}else if(/金額|單價|成本/.test(h.textContent)){h.classList.add('amount-cell');t.querySelectorAll('tbody tr').forEach(r=>r.children[i]?.classList.add('amount-cell'))}})});
 const actions=$('#pageActions');if(actions.dataset.page!==page){actions.replaceChildren();actions.dataset.page=page}
 const pdf=$('#pagePdf');if(pdf){pdf.disabled=page==='compare'&&(!crossData||crossState.hospitals.length<2);if(page==='dashboard'){const imp=$('#dashboardConditionsHead [data-go=import]');if(imp)actions.append(imp)}actions.append(pdf)}
}
$('#togglePassword').onclick=()=>{const field=$('#loginPassword'),show=field.type==='password';field.type=show?'text':'password';$('#togglePassword').textContent=show?'隱藏':'顯示';$('#togglePassword').setAttribute('aria-label',show?'隱藏密碼':'顯示密碼');$('#togglePassword').setAttribute('aria-pressed',String(show))};
const loadBefore097=load;load=async function(){refreshChrome097();await loadBefore097();refreshChrome097()};
const signBefore097=signedIn;signedIn=async function(){await signBefore097();refreshChrome097()};
// Keep presentation synchronized after existing asynchronous page renderers finish.
new MutationObserver(()=>{if(user&&!$('#shell').hidden)refreshChrome097()}).observe($('#content'),{childList:true,subtree:true});
