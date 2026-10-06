import json, sqlite3
from datetime import datetime, timezone

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE, created_at TEXT NOT NULL, api_key_hash TEXT UNIQUE, privacy_mode TEXT NOT NULL DEFAULT 'private', retention_days INTEGER NOT NULL DEFAULT 365);
CREATE TABLE IF NOT EXISTS competitors (id INTEGER PRIMARY KEY, customer_id INTEGER, name TEXT NOT NULL, website TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(customer_id) REFERENCES customers(id), UNIQUE(customer_id,website));
CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, competitor_id INTEGER NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL, allowed_by_robots INTEGER NOT NULL, status TEXT NOT NULL, last_checked TEXT, last_hash TEXT, etag TEXT, last_modified TEXT, fail_count INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(competitor_id) REFERENCES competitors(id), UNIQUE(competitor_id,url));
CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, observed_at TEXT NOT NULL, content_hash TEXT, title TEXT, text TEXT, metadata TEXT, FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, detected_at TEXT NOT NULL, change_type TEXT NOT NULL, summary TEXT NOT NULL, old_hash TEXT, new_hash TEXT, evidence TEXT, severity INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(source_id) REFERENCES sources(id));
CREATE TABLE IF NOT EXISTS findings (id INTEGER PRIMARY KEY, competitor_id INTEGER NOT NULL, created_at TEXT NOT NULL, category TEXT NOT NULL, claim TEXT NOT NULL, inference TEXT, confidence REAL, severity INTEGER, evidence TEXT, FOREIGN KEY(competitor_id) REFERENCES competitors(id));
CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, customer_id INTEGER, competitor_id INTEGER, created_at TEXT NOT NULL, period_start TEXT, period_end TEXT, title TEXT, body TEXT, FOREIGN KEY(customer_id) REFERENCES customers(id), FOREIGN KEY(competitor_id) REFERENCES competitors(id));
CREATE TABLE IF NOT EXISTS alert_rules (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, name TEXT NOT NULL, rule_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(customer_id) REFERENCES customers(id));
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, job_type TEXT NOT NULL, payload TEXT, scheduled_for TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, locked_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, customer_id INTEGER, actor TEXT NOT NULL, action TEXT NOT NULL, resource_type TEXT, resource_id INTEGER, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, FOREIGN KEY(customer_id) REFERENCES customers(id));
CREATE TABLE IF NOT EXISTS billing (customer_id INTEGER PRIMARY KEY, stripe_customer_id TEXT UNIQUE, stripe_subscription_id TEXT UNIQUE, plan TEXT, status TEXT, current_period_end TEXT, updated_at TEXT NOT NULL, FOREIGN KEY(customer_id) REFERENCES customers(id));
CREATE TABLE IF NOT EXISTS webhook_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_billing_subscription ON billing(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_audit_customer_time ON audit_log(customer_id,created_at);
CREATE INDEX IF NOT EXISTS idx_sources_competitor ON sources(competitor_id);
CREATE INDEX IF NOT EXISTS idx_changes_source_time ON changes(source_id,detected_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status_time ON jobs(status,scheduled_for);
'''

def now(): return datetime.now(timezone.utc).isoformat()
def connect(path='ci_intelligence.db'):
    c=sqlite3.connect(path, timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON'); c.executescript(SCHEMA); return c

def upsert_customer(c,name,email=None):
    c.execute('INSERT OR IGNORE INTO customers(name,email,created_at) VALUES(?,?,?)',(name,email,now())); c.commit()
    row=c.execute('SELECT id FROM customers WHERE email=?' if email else 'SELECT id FROM customers WHERE name=?',(email,) if email else (name,)).fetchone(); return row['id']

def upsert_competitor(c,name,website,customer_id=None):
    c.execute('INSERT OR IGNORE INTO competitors(customer_id,name,website,created_at) VALUES(?,?,?,?)',(customer_id,name,website,now())); c.commit()
    q='SELECT id FROM competitors WHERE website=? AND (customer_id IS ? OR customer_id=?)'; row=c.execute(q,(website,customer_id,customer_id)).fetchone(); return row['id']

def upsert_source(c,cid,url,kind,allowed,status='ready'):
    c.execute('''INSERT OR IGNORE INTO sources(competitor_id,url,kind,allowed_by_robots,status) VALUES(?,?,?,?,?)''',(cid,url,kind,int(allowed),status)); c.commit()
    return c.execute('SELECT id FROM sources WHERE competitor_id=? AND url=?',(cid,url)).fetchone()['id']

def update_source_headers(c,sid,etag=None,last_modified=None):
    c.execute('UPDATE sources SET etag=COALESCE(?,etag),last_modified=COALESCE(?,last_modified) WHERE id=?',(etag,last_modified,sid)); c.commit()

def record_observation(c,sid,result,changed=False):
    t=now(); old=c.execute('SELECT last_hash FROM sources WHERE id=?',(sid,)).fetchone()['last_hash']
    c.execute('INSERT INTO observations(source_id,observed_at,content_hash,title,text,metadata) VALUES(?,?,?,?,?,?)',(sid,t,result.get('hash'),result.get('title',''),result.get('text',''),json.dumps(result)))
    c.execute('UPDATE sources SET last_hash=?,last_checked=?,status=?,fail_count=0 WHERE id=?',(result.get('hash'),t,result.get('status','ok'),sid))
    if changed:
        c.execute('INSERT INTO changes(source_id,detected_at,change_type,summary,old_hash,new_hash,evidence,severity) VALUES(?,?,?,?,?,?,?,?)',(sid,t,result.get('change_type','content_changed'),result.get('summary','Source content changed'),old,result.get('hash'),json.dumps(result.get('evidence',{})),int(result.get('severity',1))))
    c.commit(); return changed

def record_failure(c,sid,status,error):
    c.execute('UPDATE sources SET status=?,fail_count=fail_count+1,last_checked=? WHERE id=?',(status,now(),sid)); c.commit()

def enqueue(c,job_type,payload=None,scheduled_for=None):
    scheduled_for=scheduled_for or now(); c.execute('INSERT INTO jobs(job_type,payload,scheduled_for) VALUES(?,?,?)',(job_type,json.dumps(payload or {}),scheduled_for)); c.commit(); return c.execute('SELECT last_insert_rowid()').fetchone()[0]


def set_customer_api_key(c, customer_id, key_hash):
    c.execute('UPDATE customers SET api_key_hash=? WHERE id=?', (key_hash, customer_id)); c.commit()

def get_customer_by_key_hash(c, key_hash):
    return c.execute('SELECT * FROM customers WHERE api_key_hash=?', (key_hash,)).fetchone()

def export_customer(c, customer_id):
    data = {}
    data['customer'] = dict(c.execute('SELECT id,name,email,created_at,privacy_mode,retention_days FROM customers WHERE id=?',(customer_id,)).fetchone())
    data['competitors'] = [dict(r) for r in c.execute('SELECT * FROM competitors WHERE customer_id=?',(customer_id,))]
    data['sources'] = [dict(r) for r in c.execute('SELECT s.* FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?',(customer_id,))]
    data['observations'] = [dict(r) for r in c.execute('SELECT o.* FROM observations o JOIN sources s ON s.id=o.source_id JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?',(customer_id,))]
    data['changes'] = [dict(r) for r in c.execute('SELECT ch.* FROM changes ch JOIN sources s ON s.id=ch.source_id JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?',(customer_id,))]
    data['findings'] = [dict(r) for r in c.execute('SELECT * FROM findings WHERE competitor_id IN (SELECT id FROM competitors WHERE customer_id=?)',(customer_id,))]
    data['reports'] = [dict(r) for r in c.execute('SELECT * FROM reports WHERE customer_id=?',(customer_id,))]
    data['alert_rules'] = [dict(r) for r in c.execute('SELECT * FROM alert_rules WHERE customer_id=?',(customer_id,))]
    return data

def upsert_billing(c, customer_id, stripe_customer_id=None, stripe_subscription_id=None, plan=None, status=None, current_period_end=None):
    c.execute("""INSERT INTO billing(customer_id,stripe_customer_id,stripe_subscription_id,plan,status,current_period_end,updated_at)
                 VALUES(?,?,?,?,?,?,?)
                 ON CONFLICT(customer_id) DO UPDATE SET
                 stripe_customer_id=COALESCE(excluded.stripe_customer_id,billing.stripe_customer_id),
                 stripe_subscription_id=COALESCE(excluded.stripe_subscription_id,billing.stripe_subscription_id),
                 plan=COALESCE(excluded.plan,billing.plan), status=COALESCE(excluded.status,billing.status),
                 current_period_end=COALESCE(excluded.current_period_end,billing.current_period_end), updated_at=excluded.updated_at""",
              (customer_id,stripe_customer_id,stripe_subscription_id,plan,status,current_period_end,now()))
    c.commit()

def customer_by_email(c, email):
    return c.execute('SELECT * FROM customers WHERE lower(email)=lower(?)',(email,)).fetchone()

def remember_webhook(c, event_id, event_type):
    cur=c.execute('INSERT OR IGNORE INTO webhook_events(event_id,event_type,received_at) VALUES(?,?,?)',(event_id,event_type,now()))
    c.commit(); return cur.rowcount == 1

def delete_customer(c, customer_id):
    # Delete child records through dependency order; customer-private data only.
    c.execute('DELETE FROM findings WHERE competitor_id IN (SELECT id FROM competitors WHERE customer_id=?)',(customer_id,))
    c.execute('DELETE FROM reports WHERE customer_id=?',(customer_id,))
    c.execute('DELETE FROM alert_rules WHERE customer_id=?',(customer_id,))
    c.execute('DELETE FROM observations WHERE source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?)',(customer_id,))
    c.execute('DELETE FROM changes WHERE source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?)',(customer_id,))
    c.execute('DELETE FROM sources WHERE competitor_id IN (SELECT id FROM competitors WHERE customer_id=?)',(customer_id,))
    c.execute('DELETE FROM competitors WHERE customer_id=?',(customer_id,))
    c.execute('DELETE FROM audit_log WHERE customer_id=?',(customer_id,))
    c.execute('DELETE FROM customers WHERE id=?',(customer_id,)); c.commit()


def upsert_lead(c, business_name, website, email=None, industry=None, status='prospect', score=0, notes=''):
    c.execute('''CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY, business_name TEXT NOT NULL, website TEXT NOT NULL,
        email TEXT, industry TEXT, status TEXT NOT NULL DEFAULT 'prospect',
        score INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(website)
    )''')
    t=now()
    c.execute('''INSERT INTO leads(business_name,website,email,industry,status,score,notes,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(website) DO UPDATE SET business_name=excluded.business_name,email=COALESCE(excluded.email,leads.email),
                 industry=COALESCE(excluded.industry,leads.industry),status=excluded.status,score=excluded.score,
                 notes=excluded.notes,updated_at=excluded.updated_at''',
              (business_name,website,email,industry,status,int(score),notes,t,t))
    c.commit()
    return c.execute('SELECT id FROM leads WHERE website=?',(website,)).fetchone()['id']
