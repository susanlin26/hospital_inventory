"""Netlify-only browser build; runtime archives remain private function assets."""
import os,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(root=ROOT):
 global ROOT
 ROOT=Path(root)
 if os.environ.get('CONTEXT')=='production' and os.environ.get('ALLOW_PRODUCTION_BUILD')!='true':raise ValueError('尚未允許正式建置；請先使用預覽')
 for name,entry in json.loads((ROOT/'backend/runtime/manifest.json').read_text(encoding='utf-8'))['archives'].items():
  if hashlib.sha256((ROOT/'backend/runtime'/name).read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('執行元件完整性檢查失敗')
 dist=ROOT/'dist'
 if dist.exists():shutil.rmtree(dist)
 dist.mkdir();source=ROOT/'app/static';shutil.copyfile(source/'index.html',dist/'index.html');shutil.copytree(source,dist/'assets',ignore=shutil.ignore_patterns('index.html','__pycache__','*.pyc'))
 if any(f.suffix in ('.py','.sql','.gz','.env','.toml') for f in dist.rglob('*')):raise ValueError('網站包含非公開程式，已停止建置')
 print('Netlify-only網頁建置完成；尚未發布網站。')
if __name__=='__main__':build()
