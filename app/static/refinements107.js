'use strict';
function stockSignal107(x){const marker=x.marker||'',red=['週轉嚴重偏慢','長期未耗用'].includes(marker),yellow=['週轉偏慢','持續未耗用'].includes(marker);return marker?'<small>'+(red||yellow?'<span class="inventory-light105 '+(red?'red':'yellow')+'" role="img" aria-label="'+(red?'紅燈':'黃燈')+'"></span> ':'')+E(marker)+'</small>':''}
