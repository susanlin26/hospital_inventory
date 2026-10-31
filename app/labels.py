"""畫面與匯出共用比較基準名稱。"""
from .engine import previous

def baseline_label(period, periods):
 if len(periods)==3:return '近3個月平均'
 if len(periods)==6:return '近6個月平均'
 if periods==[previous(period)]:return '上期'
 if periods==[f'{int(period[:4])-1:04}'+period[4:]]:return '去年同期'
 return '基準'
