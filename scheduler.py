import argparse
from datetime import datetime, timezone, timedelta
from .db import connect, enqueue

def enqueue_monitor(db='ci_intelligence.db',hours=24):
    c=connect(db); run=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat(); return enqueue(c,'monitor_all',{},run)
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--db',default='ci_intelligence.db'); p.add_argument('--hours',type=int,default=24); a=p.parse_args(); print(enqueue_monitor(a.db,a.hours))
