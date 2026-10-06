import argparse, json
from .db import connect,upsert_customer,upsert_competitor,upsert_source,record_observation
from .collector import discover
from .monitor import run_source

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--name',required=True); ap.add_argument('--website',required=True); ap.add_argument('--customer'); ap.add_argument('--email'); ap.add_argument('--db',default='ci_intelligence.db'); args=ap.parse_args()
    c=connect(args.db); customer_id=upsert_customer(c,args.customer,args.email) if args.customer else None; cid=upsert_competitor(c,args.name,args.website,customer_id)
    for src in discover(args.website):
        sid=upsert_source(c,cid,src['url'],src['kind'],src['robots_allowed'],'blocked_robots' if not src['robots_allowed'] else 'ready'); print(json.dumps({'source':src,'result':run_source(args.db,sid)}))
if __name__=='__main__': main()
