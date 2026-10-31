"""Bounded report reuse and request timings; cached reports never bypass authorization."""
from collections import OrderedDict
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import pickle,threading,time

request_stats=ContextVar('request_stats',default=None)

@contextmanager
def span(name):
 start=time.perf_counter()
 try:yield
 finally:
  stats=request_stats.get()
  if stats is not None:stats[name]=stats.get(name,0)+time.perf_counter()-start

def timed(name):
 def decorate(fn):
  @wraps(fn)
  def call(*args,**kwargs):
   with span(name):return fn(*args,**kwargs)
  return call
 return decorate

def source_revision(c):
 return c.execute("SELECT token FROM performance_state WHERE key='financial'").fetchone()['token']

def tracking_revision(c,h):
 row=c.execute('SELECT token FROM performance_state WHERE key=%s',('tracking:'+h,)).fetchone()
 return row['token'] if row else ''

class ReportCache:
 """Only immutable serialized copies, at most 48 MiB / 8 reports / 120 seconds."""
 def __init__(self,max_bytes=48*1024*1024,max_entries=8,ttl=120):
  self.max_bytes=max_bytes;self.max_entries=max_entries;self.ttl=ttl;self.entries=OrderedDict();self.lock=threading.RLock();self.size=0
 def get(self,key):
  with self.lock:
   entry=self.entries.get(key)
   if not entry:return None
   created,body=entry
   if time.monotonic()-created>self.ttl:
    self.size-=len(body);del self.entries[key];return None
   self.entries.move_to_end(key)
  # No cache object is returned to callers that may mutate it.
  with span('cache_copy'):return pickle.loads(body)
 def put(self,key,value):
  body=pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL)
  if len(body)>self.max_bytes:return
  with self.lock:
   if key in self.entries:self.size-=len(self.entries.pop(key)[1])
   self.entries[key]=(time.monotonic(),body);self.size+=len(body)
   while self.size>self.max_bytes or len(self.entries)>self.max_entries:
    _,(_,old)=self.entries.popitem(last=False);self.size-=len(old)
 def clear(self):
  with self.lock:self.entries.clear();self.size=0

reports=ReportCache()

category_orders=ReportCache(max_bytes=2*1024*1024,max_entries=4,ttl=3600)
source_rows=ReportCache(max_bytes=24*1024*1024,max_entries=8,ttl=120)
