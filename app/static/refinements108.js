'use strict';
const arrangeBefore108=mwArrange106;
mwArrange106=function(){arrangeBefore108();const input=$('#mwKeyword'),label=input?.closest('label');if(label){for(const node of [...label.childNodes])if(node.nodeType===Node.TEXT_NODE)node.remove();input.setAttribute('aria-label','品號或品名搜尋')}const row=$('#mwList .value-switch104')?.parentElement,batch=$('#mwBatchBar');if(row&&batch)row.after(batch);if(mwTab==='completed'){const refresh=$('#mwRefresh'),controls=$('#mwList .value-switch104');if(refresh&&controls)controls.append(refresh)}};
const drawAnalysisBefore108=drawAnalysis;
drawAnalysis=function(){drawAnalysisBefore108();if(viewTab!=='item')return;const search=$('#analysisKeyword')?.closest('label'),mode=$('#analysisBody .value-switch104');if(search&&mode){mode.classList.add('analysis-mode108');search.after(mode)}};
