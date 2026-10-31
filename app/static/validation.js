'use strict';
function validationDetails(b){
 const issues=b.report.issues||[],regular=issues.filter(x=>x.severity!=='tolerance').sort((a,b)=>(a.severity==='error'?0:1)-(b.severity==='error'?0:1)),tolerated=issues.filter(x=>x.severity==='tolerance');
 const issueTable=items=>table(['原始列','品號','程度','檢核原因','差額'],items.map(x=>`<tr><td>${E(x.row)}</td><td>${E(x.code)}</td><td>${E(({error:'錯誤',warning:'警示',tolerance:'容許誤差'})[x.severity]||x.severity)}</td><td class="wrap">${E(currencyText(x.reason))}</td><td>${x.difference_unit==='元'||/金額/.test(x.reason)?moneyFmt(x.difference):E(x.difference??'')}${x.difference_unit?' '+E(x.difference_unit):''}</td></tr>`));
 const summary=b.report.tolerance_summary||{};
 return `<p>有效${b.report.valid_count??'—'}列／隔離${b.report.excluded_count??'—'}列，略過空白${b.report.blank_rows??'—'}列。${E(b.report.control_note||'歷史版本未保存完整檢核摘要')}</p><p class="code">SHA256 ${E(b.file_hash)}</p><a href="/api/files/${b.file_id}">下載原始Excel</a><h3>錯誤與警示（${regular.length}筆）</h3>${regular.length?issueTable(regular):'<p>沒有錯誤或待確認警示。</p>'}${tolerated.length?`<div class="tolerance-box"><button type="button" class="outline" id="toleranceToggle" aria-expanded="false" aria-controls="toleranceDetails">展開容許誤差（${tolerated.length}筆）</button><div id="toleranceDetails" hidden><p>僅收合逐品號進銷存金額差額在正負1元內（含）的項目；原始金額與分析計算未調整。數量差異列為錯誤；其他檢核依規則顯示。</p><p>差額淨合計：${moneyFmt(summary.net_difference)}元；差額絕對值合計：${moneyFmt(summary.absolute_difference)}元。</p>${issueTable(tolerated)}</div></div>`:''}`;
}
function bindToleranceToggle(){
 const button=$('#toleranceToggle');if(!button)return;
 button.addEventListener('click',()=>{const expanded=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(expanded));$('#toleranceDetails').hidden=!expanded;button.textContent=(expanded?'收合':'展開')+button.textContent.replace(/^(展開|收合)/,'')});
}
