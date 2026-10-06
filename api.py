from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, sqlite3, os, secrets, re
from .db import connect, export_customer, delete_customer, is_postgres
from .security import verify_api_key, hash_secret, audit
from .stripe_billing import create_checkout, construct_event
from .db import upsert_billing, customer_by_email, remember_webhook, upsert_customer, upsert_competitor, upsert_source, enqueue, upsert_lead
from .acquisition import lead_score, build_preview, outreach_draft, build_public_assessment

def db_path(): return os.getenv('CI_DB','ci_intelligence.db')
def admin_key(): return os.getenv('CI_ADMIN_API_KEY')

def _execute(c, sql, params=()):
    if is_postgres(c): sql = sql.replace('?', '%s')
    return c.execute(sql, params)

def _valid_email(value):
    return bool(value and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()) and len(value) <= 320)

def _safe_text(value, limit):
    return str(value or '').strip()[:limit]

class Handler(BaseHTTPRequestHandler):
    def _send(self,data,status=200,content_type='application/json'):
        raw=json.dumps(data, default=str).encode(); self.send_response(status)
        self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(raw)
    def _key(self):
        got=self.headers.get('Authorization','')
        if not got.startswith('Bearer '): return None
        return got[7:].strip()
    def _customer(self):
        key=self._key()
        if not key: return None
        c=connect(db_path()); return _execute(c,'SELECT * FROM customers WHERE api_key_hash=?',(hash_secret(key),)).fetchone()
    def _admin(self):
        key=self._key(); return bool(admin_key() and key and secrets.compare_digest(key,admin_key()))
    def do_GET(self):
        if self.path in ('/','/dashboard'):
            try:
                with open(os.path.join(os.path.dirname(__file__),'..','dashboard.html'),'rb') as f: raw=f.read()
                self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.end_headers(); self.wfile.write(raw); return
            except Exception: return self._send({'error':'dashboard_unavailable'},503)
        if self.path=='/health': return self._send({'ok':True,'service':'competitive-ai-intelligence'})
        customer=self._customer()
        if self.path=='/me':
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); billing=_execute(c,'SELECT plan,status,current_period_end FROM billing WHERE customer_id=?',(customer['id'],)).fetchone(); data={k:customer[k] for k in ('id','name','email','privacy_mode','retention_days')}; data['billing']=dict(billing) if billing else None; return self._send({'customer':data})
        if self.path=='/export':
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); data=export_customer(c,customer['id']); audit(c,customer['id'],'customer','data.export')
            return self._send(data)
        if self.path=='/competitors':
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); rows=_execute(c,'SELECT id,name,website,created_at FROM competitors WHERE customer_id=? ORDER BY id DESC',(customer['id'],))
            return self._send({'competitors':[dict(x) for x in rows]})
        if self.path=='/reports':
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); rows=_execute(c,'SELECT id,title,body,created_at,period_start,period_end FROM reports WHERE customer_id=? ORDER BY id DESC LIMIT 20',(customer['id'],))
            return self._send({'reports':[dict(x) for x in rows]})
        if self.path=='/admin/leads':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            c=connect(db_path())
            return self._send({'leads':[dict(x) for x in c.execute('SELECT * FROM leads ORDER BY score DESC, id DESC')]})
        if self.path=='/admin/preview':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            return self._send({'error':'use_post'},405)
        if self.path=='/public/preview':
            return self._send({'error':'use_post'},405)
        if self.path=='/admin/customers':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); return self._send({'customers':[dict(x) for x in c.execute('SELECT id,name,email,created_at,privacy_mode,retention_days FROM customers ORDER BY id DESC')]})
        return self._send({'error':'not_found'},404)
    def do_POST(self):
        length=int(self.headers.get('Content-Length','0') or 0)
        if length > 256_000: return self._send({'error':'request_too_large'},413)
        body=self.rfile.read(length)
        if self.path == '/public/preview':
            try:
                data=json.loads(body or b'{}')
                name=str(data.get('business_name','')).strip()
                industry=str(data.get('industry','')).strip()
                competitors=list(data.get('competitors') or [])
                priorities=list(data.get('priorities') or [])
                if not name or len(name)>160: return self._send({'error':'business_name_required'},400)
                if len(competitors)>50 or len(priorities)>20: return self._send({'error':'input_limit_exceeded'},400)
                return self._send(build_public_assessment(name,industry,competitors,priorities))
            except Exception as e:
                return self._send({'error':'preview_failed','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Unable to create assessment'},400)
        if self.path == '/public/lead':
            try:
                data=json.loads(body or b'{}')
                business=_safe_text(data.get('business_name'),160)
                email=_safe_text(data.get('email'),320).lower()
                website=_safe_text(data.get('website'),500)
                industry=_safe_text(data.get('industry'),120)
                competitors=data.get('competitors') or []
                if not business or not _valid_email(email):
                    return self._send({'error':'business_name_and_valid_email_required'},400)
                score,reasons=lead_score(business,website,len(competitors),industry)
                c=connect(db_path())
                lead_id=upsert_lead(c,business,website or f'lead:{email}',email,industry,'assessment_requested',score,'; '.join(reasons))
                return self._send({'ok':True,'lead_id':lead_id,'message':'Request received.'},201)
            except Exception:
                return self._send({'error':'invalid_request'},400)
        if self.path == '/admin/lead-update':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            try:
                data=json.loads(body or b'{}')
                lead_id=int(data.get('lead_id'))
                status=_safe_text(data.get('status'),40)
                notes=_safe_text(data.get('notes'),2000)
                allowed={'prospect','assessment_requested','contacted','conversation','pilot','paid','won','lost','do_not_contact'}
                if status not in allowed: return self._send({'error':'invalid_status'},400)
                c=connect(db_path()); _execute(c,'UPDATE leads SET status=?,notes=?,updated_at=? WHERE id=?',(status,notes,__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),lead_id)); c.commit()
                return self._send({'ok':True,'updated':c.total_changes>0})
            except Exception:
                return self._send({'error':'invalid_request'},400)
        if self.path == '/admin/leads':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            try:
                data=json.loads(body or b'{}'); name=str(data.get('business_name','')).strip(); website=str(data.get('website','')).strip(); industry=str(data.get('industry','')).strip(); email=str(data.get('email','')).strip() or None
                competitors=data.get('competitors') or []
                if not name or not website.startswith(('http://','https://')): return self._send({'error':'business_name_and_http_url_required'},400)
                score,reasons=lead_score(name,website,len(competitors),industry)
                c=connect(db_path()); lid=upsert_lead(c,name,website,email,industry,'prospect',score,'; '.join(reasons))
                return self._send({'ok':True,'lead_id':lid,'score':score,'reasons':reasons},201)
            except Exception as e: return self._send({'error':'lead_create_failed','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Unable to create lead'},400)
        if self.path == '/admin/preview':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            try:
                data=json.loads(body or b'{}'); name=str(data.get('business_name','')).strip(); competitor=str(data.get('competitor','')).strip(); changes=data.get('changes') or []
                if not name or not competitor: return self._send({'error':'business_name_and_competitor_required'},400)
                return self._send(build_preview(name,competitor,changes))
            except Exception as e: return self._send({'error':'preview_failed','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Unable to generate preview'},400)
        if self.path == '/admin/outreach':
            if not self._admin(): return self._send({'error':'unauthorized'},401)
            try:
                data=json.loads(body or b'{}'); name=str(data.get('business_name','')).strip(); competitors=list(data.get('competitors') or []); count=int(data.get('finding_count') or 0)
                if not name: return self._send({'error':'business_name_required'},400)
                return self._send({'draft':outreach_draft(name,competitors,count)})
            except Exception as e: return self._send({'error':'outreach_failed','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Unable to draft outreach'},400)
        if self.path == '/competitors':
            customer=self._customer()
            if not customer: return self._send({'error':'unauthorized'},401)
            try:
                data=json.loads(body or b'{}'); name=str(data.get('name','')).strip(); website=str(data.get('website','')).strip()
                if not name or not website.startswith(('http://','https://')): return self._send({'error':'name_and_http_url_required'},400)
                cid=upsert_competitor(connect(db_path()),name,website,customer['id']); c=connect(db_path())
                from .collector import discover
                for src in discover(website): upsert_source(c,cid,src['url'],src['kind'],src['robots_allowed'],'ready' if src['robots_allowed'] else 'blocked_robots')
                enqueue(c,'monitor_source',{'source_id':_execute(c,'SELECT id FROM sources WHERE competitor_id=? ORDER BY id LIMIT 1',(cid,)).fetchone()['id']})
                audit(c,customer['id'],'customer','competitor.create','competitor',cid)
                return self._send({'ok':True,'competitor_id':cid},201)
            except Exception as e: return self._send({'error':'competitor_create_failed','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Unable to add competitor'},400)
        if self.path == '/monitor':
            customer=self._customer()
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); enqueue(c,'monitor_all',{'customer_id':customer['id']}); audit(c,customer['id'],'customer','monitor.queue'); return self._send({'ok':True,'queued':True},202)
        if self.path == '/report':
            customer=self._customer()
            if not customer: return self._send({'error':'unauthorized'},401)
            c=connect(db_path()); enqueue(c,'report',{'customer_id':customer['id']}); audit(c,customer['id'],'customer','report.queue'); return self._send({'ok':True,'queued':True},202)
        if self.path == '/checkout':
            try:
                data=json.loads(body or b'{}')
                email=str(data.get('email','')).strip()
                plan=str(data.get('plan','starter')).strip().lower()
                if not email or '@' not in email: return self._send({'error':'valid_email_required'},400)
                if plan not in {'starter','growth','pro'}: return self._send({'error':'invalid_plan'},400)
                base=os.getenv('CI_PUBLIC_URL','http://localhost:8080').rstrip('/')
                session=create_checkout(email,plan,base+'/billing/success?session_id={CHECKOUT_SESSION_ID}',base+'/pricing')
                return self._send({'checkout_url':session.url,'session_id':session.id},201)
            except Exception as e:
                return self._send({'error':'checkout_unavailable','detail':str(e) if os.getenv('CI_DEBUG')=='1' else 'Payment service is not configured'},503)
        if self.path == '/stripe/webhook':
            try:
                event=construct_event(body,self.headers.get('Stripe-Signature',''))
                c=connect(db_path())
                if not remember_webhook(c,event['id'],event['type']): return self._send({'ok':True,'duplicate':True})
                obj=event['data']['object']; typ=event['type']
                if typ == 'checkout.session.completed' and obj.get('payment_status') == 'paid':
                    email=obj.get('customer_details',{}).get('email') or obj.get('customer_email')
                    if email:
                        row=customer_by_email(c,email)
                        cid=row['id'] if row else upsert_customer(c,email,email)
                        upsert_billing(c,cid,obj.get('customer'),obj.get('subscription'),None,'active')
                elif typ in {'customer.subscription.created','customer.subscription.updated','customer.subscription.deleted'}:
                    bc=_execute(c,'SELECT customer_id FROM billing WHERE stripe_customer_id=?',(obj.get('customer'),)).fetchone()
                    if bc:
                        status='canceled' if typ.endswith('deleted') else obj.get('status')
                        period=obj.get('current_period_end')
                        upsert_billing(c,bc['customer_id'],obj.get('customer'),obj.get('id'),None,status,str(period) if period else None)
                elif typ in {'invoice.paid','invoice.payment_failed'}:
                    bc=_execute(c,'SELECT customer_id FROM billing WHERE stripe_customer_id=?',(obj.get('customer'),)).fetchone()
                    if bc:
                        status='active' if typ.endswith('paid') else 'past_due'
                        upsert_billing(c,bc['customer_id'],obj.get('customer'),None,None,status,None)
                return self._send({'ok':True})
            except Exception:
                return self._send({'error':'invalid_webhook'},400)
        return self._send({'error':'not_found'},404)

    def do_DELETE(self):
        if self.path != '/me': return self._send({'error':'not_found'},404)
        customer=self._customer()
        if not customer: return self._send({'error':'unauthorized'},401)
        c=connect(db_path()); audit(c,customer['id'],'customer','account.delete_requested'); delete_customer(c,customer['id'])
        return self._send({'ok':True,'deleted':True})
    def log_message(self,format,*args): return

def serve(port=8080): ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
