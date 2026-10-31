"""Maintainer-only: rebuild private Linux Python archives after dependency updates.
Use a relocatable Linux x86_64 Python 3.12 prefix and a clean backend-only site-packages.
Never use a system Python prefix that depends on files outside the supplied directory.
"""
import argparse,hashlib,json,platform,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def package(prefix,site):
 if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):raise ValueError('須在Linux x86_64維護環境封裝')
 binary=prefix/'bin/python3.12'
 version=subprocess.check_output([str(binary),'--version'],text=True).strip()
 if not version.startswith('Python 3.12.'):raise ValueError('僅接受已驗證的Python 3.12系列')
 destination=ROOT/'backend/runtime';destination.mkdir(parents=True,exist_ok=True)
 with tarfile.open(destination/'python.tar.gz','w:gz',compresslevel=6,dereference=True) as out:
  out.add(binary,arcname='python/bin/python3',recursive=False)
  for f in sorted((prefix/'lib/python3.12').rglob('*')):
   rel=f.relative_to(prefix/'lib/python3.12')
   if any(v in rel.parts for v in ('site-packages','__pycache__','test','tests','tkinter','idlelib','ensurepip','turtledemo')):continue
   if f.is_file() and f.suffix not in ('.pyc','.pyo'):out.add(f,arcname='python/lib/python3.12/'+rel.as_posix(),recursive=False)
  needed=subprocess.check_output(['ldd',str(binary)],text=True)
  if 'libpython' in needed:
   for f in (prefix/'lib').glob('libpython*.so*'):out.add(f,arcname='python/lib/'+f.name,recursive=False)
 def clean(info):return None if any(v in info.name.split('/') for v in ('__pycache__','tests','test')) or info.name.endswith(('.pyc','.pyo')) else info
 with tarfile.open(destination/'packages.tar.gz','w:gz',compresslevel=6,dereference=True) as out:
  for f in sorted(site.iterdir()):
   if f.name.startswith(('pip','setuptools','_distutils','wheel')):continue
   out.add(f,arcname='python/lib/python3.12/site-packages/'+f.name,filter=clean)
 manifest={'python':version,'architecture':'x86_64','system':'linux','archives':{}}
 for f in destination.glob('*.gz'):
  if f.stat().st_size>25*1024*1024:raise ValueError('單一執行壓縮檔超過GitHub網頁上傳上限，須改用其他程式上傳方式')
  manifest['archives'][f.name]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'size':f.stat().st_size}
 (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print('封裝完成；必須重新驗證原生函式與所有功能後才能交付。')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--python-prefix',type=Path,required=True);parser.add_argument('--site-packages',type=Path,required=True);args=parser.parse_args();package(args.python_prefix.resolve(),args.site_packages.resolve())
