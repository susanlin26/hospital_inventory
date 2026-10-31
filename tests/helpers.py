from io import BytesIO
from openpyxl import Workbook
from app import excel

def line(**kw):
 x={k:'0' for k in excel.FIELDS};x.update(code='TEST',name='測試品項',unit='組',category='測試',period='2026-08',valid=True,row=2,sheet='測試',raw={});x.update(kw);return x

def make_excel(rows):
 w=Workbook();s=w.active;s.title='不固定名稱';s.append(['產品編號','產品名稱','單位',*excel.FIELDS.values()])
 for row in rows:s.append([row.get('code'),row.get('name'),row.get('unit'),*[row.get(k) for k in excel.FIELDS]])
 b=BytesIO();w.save(b);return b.getvalue()

