import argparse, json, time
from datetime import datetime, timezone, timedelta
from .db import connect, now, is_postgres
from .monitor import run_source
from .analyst import build_findings, render_report

def claim(c):
    if is_postgres(c):
        row=c.execute("SELECT * FROM jobs WHERE status='queued' AND scheduled_for<=%s ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",(now(),)).fetchone()
        if not row:
            c.commit(); return None
        c.execute("UPDATE jobs SET status='running',attempts=attempts+1,locked_at=%s WHERE id=%s AND status='queued'",(now(),row['id']))
        c.commit(); return c.execute("SELECT * FROM jobs WHERE id=%s",(row['id'],)).fetchone()
    c.execute("BEGIN IMMEDIATE")
    row=c.execute("SELECT * FROM jobs WHERE status='queued' AND scheduled_for<=? ORDER BY id LIMIT 1",(now(),)).fetchone()
    if not row: c.commit(); return None
    c.execute("UPDATE jobs SET status='running',attempts=attempts+1,locked_at=? WHERE id=? AND status='queued'",(now(),row['id']))
    c.commit(); return c.execute("SELECT * FROM jobs WHERE id=?",(row['id'],)).fetchone()

def recover_stale_jobs(c,minutes=15):
    cutoff=(datetime.now(timezone.utc)-timedelta(minutes=minutes)).isoformat()
    q="UPDATE jobs SET status='queued',last_error='Recovered stale worker lock',locked_at=NULL WHERE status='running' AND locked_at<%s" if is_postgres(c) else "UPDATE jobs SET status='queued',last_error='Recovered stale worker lock',locked_at=NULL WHERE status='running' AND locked_at<?"
    c.execute(q,(cutoff,)); c.commit()

def run_job(db,job):
    payload=json.loads(job['payload'] or '{}')
    if job['job_type']=='monitor_all':
        c=connect(db); cid=payload.get('customer_id')
        if cid is None: raise ValueError('customer_id required for monitor_all')
        q="SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=%s AND s.status!='blocked_robots'" if is_postgres(c) else "SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=? AND s.status!='blocked_robots'"
        ids=[r['id'] for r in c.execute(q,(cid,))]
        return {'monitored':len(ids),'results':[run_source(db,i) for i in ids]}
    if job['job_type']=='monitor_source': return run_source(db,int(payload['source_id']))
    if job['job_type']=='report': return generate_reports(db,payload.get('customer_id'))
    raise ValueError('unknown job type')

def generate_reports(db,customer_id=None):
    c=connect(db); out=[]
    if customer_id is None:
        query='SELECT * FROM competitors'; params=()
    else:
        query='SELECT * FROM competitors WHERE customer_id=%s' if is_postgres(c) else 'SELECT * FROM competitors WHERE customer_id=?'; params=(customer_id,)
    for comp in c.execute(query,params):
        q='SELECT ch.*, s.url, s.kind FROM changes ch JOIN sources s ON s.id=ch.source_id WHERE s.competitor_id=%s ORDER BY ch.detected_at DESC LIMIT 50' if is_postgres(c) else 'SELECT ch.*, s.url, s.kind FROM changes ch JOIN sources s ON s.id=ch.source_id WHERE s.competitor_id=? ORDER BY ch.detected_at DESC LIMIT 50'
        rows=c.execute(q,(comp['id'],)).fetchall()
        findings=build_findings([dict(r) for r in rows]); body=render_report(comp['name'],findings)
        iq='INSERT INTO reports(competitor_id,customer_id,created_at,title,body) VALUES(%s,%s,%s,%s,%s)' if is_postgres(c) else 'INSERT INTO reports(competitor_id,customer_id,created_at,title,body) VALUES(?,?,?,?,?)'
        c.execute(iq,(comp['id'],comp['customer_id'],now(),f"Competitive Intelligence — {comp['name']}",body)); out.append(comp['name'])
    c.commit(); return {'reports_created':len(out),'competitors':out}

def worker_loop(db='ci_intelligence.db',poll=5,once=False):
    while True:
        c=connect(db); recover_stale_jobs(c); job=claim(c)
        if not job:
            if once: return
            time.sleep(poll); continue
        try:
            result=run_job(db,job); c.execute("UPDATE jobs SET status='done',finished_at=%s,last_error=%s,locked_at=NULL WHERE id=%s" if is_postgres(c) else "UPDATE jobs SET status='done',finished_at=?,last_error=?,locked_at=NULL WHERE id=?",(now(),json.dumps(result)[:4000],job['id'])); c.commit()
        except Exception as e:
            status='failed' if job['attempts']>=5 else 'queued'; c.execute('UPDATE jobs SET status=%s,last_error=%s,locked_at=NULL WHERE id=%s' if is_postgres(c) else 'UPDATE jobs SET status=?,last_error=?,locked_at=NULL WHERE id=?',(status,str(e),job['id'])); c.commit()
        if once: return

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default='ci_intelligence.db'); ap.add_argument('--poll',type=float,default=5); ap.add_argument('--once',action='store_true'); a=ap.parse_args(); worker_loop(a.db,a.poll,a.once)
