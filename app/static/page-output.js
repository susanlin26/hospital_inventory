'use strict';
function installPagePdf094(){
 if(!['dashboard','compare'].includes(page)||$('#pagePdf'))return;
 const host=page==='dashboard'?$('#dashboardConditionsHead'):$('[data-cross-section=conditions] .action-row');
 if(!host)return;
 const b=document.createElement('button');b.id='pagePdf';b.className='outline';b.textContent='轉出PDF';
 b.disabled=page==='compare'&&(!crossData||crossState.hospitals.length<2);
 b.onclick=exportPagePdf094;host.append(b);
}
function pdfDocument094(){
 const cross=page==='compare',title=cross?'跨院比較':'管理總覽';
 const conditions=cross?`比較醫院：${crossState.hospitals.map(h=>crossHospital(h)+'（'+h+'）').join('、')}　分析年月：${crossState.month}　比較基準：${crossData.baseline_label} ${crossData.baseline_period}`:`醫院：${$('#hospital').selectedOptions[0].textContent}　分析年月：${$('#month').value}　比較基準：${$('#baseline').selectedOptions[0].textContent}`;
 const nodes=cross?[$('#cross-summary'),$('#cross-metrics')]:[...document.querySelectorAll('#content [data-dashboard-section]')];
 const html=nodes.filter(Boolean).map(n=>{const x=n.cloneNode(true);x.querySelectorAll('.dashboard-window,.dashboard-entries,.table-resizer,label:has([data-dash-category-filter])').forEach(e=>e.remove());x.querySelectorAll('details:not([open])').forEach(e=>e.remove());x.querySelectorAll('button,input,select').forEach(e=>{if(e.matches('.kpi-link')){const d=document.createElement('div');d.className='kpi';d.innerHTML=e.innerHTML;e.replaceWith(d)}else if(e.closest('table')){e.replaceWith(document.createTextNode(e.textContent))}else e.remove()});if(cross&&x.id==='cross-metrics'){let group=null;for(const node of [...x.children]){if(node.tagName==='H3'){group=document.createElement('div');group.className='pdf-metric-group';node.before(group)}if(group)group.append(node)}}x.querySelectorAll('colgroup').forEach(e=>e.remove());x.querySelectorAll('table').forEach(e=>{e.style.width='100%';e.style.tableLayout='auto'});return x.outerHTML}).join('');
 return `<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>${E(title+'_'+(cross?crossState.month:$('#month').value))}</title><style>
 @page{size:A4 landscape;margin:12mm}*{box-sizing:border-box}body{margin:0;color:#173c50;font:12px/1.55 'Microsoft JhengHei','Noto Sans CJK TC',sans-serif}h1,h2,h3,h4,.panel-head{break-after:avoid;page-break-after:avoid}h1{font-size:24px;margin:0 0 8px}h2{font-size:18px;margin:14px 0 10px;color:#147a76}h3{font-size:15px;margin:12px 0 8px}h4{font-size:13px}.pdf-conditions{padding:10px;background:#edf6f5;border-bottom:1px solid #c8d9dd;margin-bottom:14px}.panel{padding:12px 0;border-bottom:1px solid #dae5eb}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid2>div{min-width:0}.dashboard-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.kpi{border:1px solid #c8d9dd;padding:12px;border-radius:6px}.kpi .label,.kpi strong,.kpi small{display:block}.kpi strong{font-size:22px;margin:8px 0}.kpi small{font-size:10px}.caption,small{font-size:10px;color:#637582}table{border-collapse:collapse;width:100%!important;font-size:11px;table-layout:auto!important}th,td{padding:7px;border-bottom:1px solid #dce6eb;text-align:center;white-space:normal!important;overflow-wrap:anywhere}th{background:#edf3f5}tr,.kpi,.grid2,.pdf-metric-group,.cross-bars{break-inside:avoid}thead{display:table-header-group}.amount-cell,.num{text-align:right}.status-cell{text-align:center}.scroll,.chart-scroll{overflow:visible!important;max-width:100%}svg{width:100%;height:auto;min-width:0!important;max-width:100%}svg text{font-size:11px;fill:#526a78}.cross-bars{margin:10px 0}.cross-bar{display:grid;grid-template-columns:150px 1fr 90px;gap:12px;align-items:center;margin:10px 0;break-inside:avoid}.cross-bar-track{display:block;height:17px;background:#edf3f5}.cross-bar-track>span{display:block;height:100%;background:#147a76}.cross-bar strong{text-align:right}.panel-head{display:flex;justify-content:space-between}.chart-gap{fill:#ad7540}a{color:inherit;text-decoration:none}details{margin:10px 0}
 </style><body><h1>${title}</h1><p class="pdf-conditions">${E(periodText(conditions))}</p>${html}</body></html>`;
}
function exportPagePdf094(){
 if(!['dashboard','compare'].includes(page)||document.querySelector(page==='compare'?'#cross-summary .loading,#cross-metrics .loading':'#content .loading')){toast('資料仍在讀取，請完成後再匯出',true);return}
 const html=pdfDocument094(),preview=window.open('','_blank');
 if(!preview){toast('請允許本系統開啟列印視窗，再按轉出PDF',true);return}
 preview.document.open();preview.document.write(html);preview.document.close();
 preview.document.fonts.ready.then(()=>{preview.focus();preview.print()});
}
const loadBefore094=load;load=async function(){await loadBefore094();installPagePdf094()};
