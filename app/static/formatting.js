'use strict';
// String/BigInt decimal rounding avoids binary float ties. Presentation only.
function moneyFmt(value){
 if(value===null||value===undefined||value==='')return '—';
 const m=String(value).replace(/,/g,'').match(/^([+-]?)(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);if(!m)return '—';
 const digits=m[2]+(m[3]||''),point=m[2].length+Number(m[4]||0);if(Math.abs(point)>100)return '—';
 let whole=point<=0?'0':digits.slice(0,point).padEnd(point,'0');const first=point<0?'0':digits[point]||'0';
 let result=BigInt(whole||'0')+(first>='5'?1n:0n);return (m[1]==='-'&&result!==0n?'-':'')+result.toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');
}
const moneyKeys=new Set(['monthly_bed_consumption','baseline_monthly_bed_consumption','amount','used','ending','opening','average','purchase','per_bed','monthly_per_bed','per_patient_day','standard30_per_bed','unit_cost','impact','consumption_anomaly_impact']);
function metricFmt(value,key,n=2){return key==='qty'?moneyFmt(value):moneyKeys.has(key)?moneyFmt(value):fmt(value,n)}
function currencyText(text){return String(text||'').replace(/(-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*元/g,(_,v)=>moneyFmt(v)+'元')}
function findingFmt(x){return /高庫存|週轉|低庫存|數量/.test(x.rule)?fmt(x.value,2):moneyFmt(x.value)}
