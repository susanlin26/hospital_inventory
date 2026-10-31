"""Presentation only. Never changes source values or financial calculations."""
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

def money(value,n=None):
 if value is None:return '資料不足'
 with localcontext() as ctx:
  ctx.prec=50
  v=Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
 return f'{abs(v) if v==0 else v:,.0f}'

def number_text(value,n=2):
 return '資料不足' if value is None else f'{Decimal(str(value)):,.{n}f}'

def monetary_label(label):
 if '耗用量' in label:return False
 if any(x in label for x in ('每住院人日耗用','每人日耗用','標準30日每床耗用','每床月耗用','數量因素','單位成本因素')):return True
 if any(x in label for x in ('數量','占比','率','天數','床數','人數','住院人日','未取整人日','覆蓋','數值','年月','月份','版本','原始列','進貨量','案件','件數')):return False
 return any(x in label for x in ('金額','單價','進價','耗用','庫存','存貨','單位成本','單位耗用成本','數量因素','成本因素','價差','差額','與上月單位成本因素'))

def money_in_text(text):
 """Normalize only explicit currency tokens in model or persisted explanatory text."""
 return re.sub(r'(?<![\d.])(-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(元)',lambda m:money(m[1].replace(',',''))+m[2],str(text or ''))

def format_workbook(wb):
 """Excel numeric values retain full precision; format controls presentation only."""
 for ws in wb:
  headers=[str(c.value or '') for c in ws[1]]
  pairs=len(headers)==2 and headers[0] in ('項目','類型')
  for row in ws.iter_rows(min_row=2):
   for i,cell in enumerate(row):
    label=str(row[0].value or '') if pairs and i==1 else headers[i] if i<len(headers) else ''
    if monetary_label(label):cell.number_format='#,##0'
    elif isinstance(cell.value,(float,int,Decimal)) and not isinstance(cell.value,bool):cell.number_format='#,##0.00########'
   # Rule values are mixed money, quantity and days; identify by row's rule.
   if ws.title in ('異常明細','異常改善追蹤報表'):
    rule=str(row[3 if ws.title=='異常明細' else 5].value or '')
    cell=row[5 if ws.title=='異常明細' else 7]
    if not any(x in rule for x in ('高庫存','週轉','低庫存','數量')):cell.number_format='#,##0'
   if ws.title=='檢核結果' and '金額' in str(row[3].value):
    cell=row[4]
    if cell.value is not None:
     try:cell.value=float(str(cell.value).lstrip("'"));cell.number_format='#,##0'
     except ValueError:pass
  for chart in ws._charts:
   # Each chart's numeric money source format is retained in Excel tooltips.
   title=str(chart.title)
   if any(x in title for x in ('耗用','存貨','庫存金額')) and not ('週轉天數' in title and '庫存金額' not in title):
    chart.y_axis.numFmt='#,##0'
    if chart.dataLabels:chart.dataLabels.numFmt='#,##0'
 return wb


def period_text(value):
 return '—' if isinstance(value,str) and ('不適用' in value or value.strip() in ('本期無耗用','本月無耗用')) else value.replace('本月','本期').replace('上月','上期').replace('本期無耗用，週轉天數不適用','本期無耗用') if isinstance(value,str) else value
