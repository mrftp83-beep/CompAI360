import json
from .collector import collect
from .extract import categorize_change, extract_observations
from .feeds import collect_feed
from .db import now, record_failure, record_observation, update_source_headers, connect

def run_source(db,source_id):
    c=connect(db); q='SELECT * FROM sources WHERE id=%s' if c.__class__.__module__.startswith('psycopg') else 'SELECT * FROM sources WHERE id=?'; s=c.execute(q,(source_id,)).fetchone()
    if not s: raise ValueError('source not found')
    if not s['allowed_by_robots']: return {'status':'blocked_robots'}
    try:
        if s['kind']=='feed':
            r=collect_feed(s['url']);
            if r['status']=='not_modified': return r
            text=json.dumps(r.get('items',[]),sort_keys=True); h=__import__('hashlib').sha256(text.encode()).hexdigest(); old=s['last_hash']; changed=bool(old and old!=h)
            result={'status':r['status'],'hash':h,'title':'RSS/Atom feed','text':text,'headers':r.get('headers',{}),'change_type':'news','summary':'Feed items changed','evidence':{'url':r['url'],'items':r.get('items',[])[:10]},'severity':3}
        else:
            r=collect(s['url'],s['etag'],s['last_modified']);
            if r['status']=='not_modified': return r
            old=s['last_hash']; changed=bool(old and old!=r.get('hash')); result={**r,'change_type':categorize_change('',r.get('text','')),'summary':'Competitor source content changed','evidence':{'url':r.get('url'),'observed_at':now()},'severity':2}
        record_observation(c,source_id,result,changed); hdr=result.get('headers',{}); update_source_headers(c,source_id,hdr.get('ETag'),hdr.get('Last-Modified'))
        return {'status':result['status'],'changed':changed,'signals':extract_observations(result.get('text','')),'url':result.get('url')}
    except Exception as e:
        record_failure(c,source_id,'error',str(e)); return {'status':'error','error':str(e),'url':s['url']}
