import hashlib, ipaddress, os, re, socket, threading, time, urllib.parse, urllib.request, urllib.error, urllib.robotparser
from html.parser import HTMLParser

CONTACT=os.getenv('CI_BOT_CONTACT','support@example.invalid')
UA=f'CompetitiveAIIntelligenceBot/1.0 (+{CONTACT})'
MAX_REDIRECTS=int(os.getenv('CI_MAX_REDIRECTS','5'))
MAX_BYTES=int(os.getenv('CI_MAX_RESPONSE_BYTES','2000000'))
REQUEST_TIMEOUT=int(os.getenv('CI_REQUEST_TIMEOUT','15'))
ROBOTS_TIMEOUT=int(os.getenv('CI_ROBOTS_TIMEOUT','10'))
MIN_HOST_INTERVAL=float(os.getenv('CI_MIN_HOST_INTERVAL','1.0'))

_rate_lock=threading.Lock()
_last_request={}

class PageParser(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.title=[]; self.skip=0; self.in_title=False
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg'): self.skip+=1
        if tag=='title': self.in_title=True
    def handle_endtag(self,tag):
        if tag=='title': self.in_title=False
        if tag in ('script','style','noscript','svg') and self.skip: self.skip-=1
    def handle_data(self,data):
        if self.skip==0:
            d=' '.join(data.split())
            if d:
                self.parts.append(d)
                if self.in_title: self.title.append(d)

def normalize(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or not p.netloc: raise ValueError('Only http/https URLs are supported')
    if p.username or p.password: raise ValueError('URLs with embedded credentials are not supported')
    if not p.hostname: raise ValueError('Missing host')
    return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))

def _host_ips(host):
    try: return [ipaddress.ip_address(host)]
    except ValueError: pass
    infos=socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)
    return list({ipaddress.ip_address(x[4][0]) for x in infos})

def _is_blocked_ip(ip):
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or
            ip.is_reserved or ip.is_unspecified or ip.is_broadcast)

def assert_public_target(url):
    p=urllib.parse.urlsplit(url); host=p.hostname
    if not host: raise ValueError('Missing host')
    host_l=host.lower().rstrip('.')
    if host_l in {'localhost','localhost.localdomain'} or host_l.endswith(('.localhost','.local','.internal')):
        raise ValueError('Local/internal host targets are blocked')
    for ip in _host_ips(host):
        if _is_blocked_ip(ip): raise ValueError('Private/reserved network targets are blocked')

def _pace(host):
    now=time.monotonic()
    with _rate_lock:
        last=_last_request.get(host)
        wait=MIN_HOST_INTERVAL-(now-last) if last is not None else 0
        if wait>0: time.sleep(wait)
        _last_request[host]=time.monotonic()

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER=urllib.request.build_opener(_NoRedirect())

def _open_once(url,headers,timeout):
    p=urllib.parse.urlsplit(url)
    assert_public_target(url)
    _pace(p.hostname.lower())
    req=urllib.request.Request(url,headers=headers)
    try:
        return _OPENER.open(req,timeout=timeout)
    except urllib.error.HTTPError as e:
        return e

def robots_for(url):
    p=urllib.parse.urlsplit(url); robots=urllib.parse.urlunsplit((p.scheme,p.netloc,'/robots.txt','',''))
    try:
        r=_open_once(robots,{'User-Agent':UA,'Accept':'text/plain,*/*;q=0.5'},ROBOTS_TIMEOUT)
        status=getattr(r,'status',200)
        if 200 <= status < 300:
            data=r.read(512_000); r.close()
            rp=urllib.robotparser.RobotFileParser(); rp.parse(data.decode('utf-8','ignore').splitlines())
            return rp.can_fetch(UA,url),'ok',robots
        if 400 <= status < 500: return True,'unavailable_4xx',robots
        return False,'unavailable_error',robots
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500: return True,'unavailable_4xx',robots
        return False,'unavailable_error',robots
    except Exception:
        return False,'unavailable_error',robots

def _header_map(headers):
    return dict(headers.items()) if headers else {}

def fetch(url,timeout=None,max_bytes=None,etag=None,last_modified=None):
    timeout=timeout or REQUEST_TIMEOUT; max_bytes=max_bytes or MAX_BYTES
    current=normalize(url)
    headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5'}
    if etag: headers['If-None-Match']=etag
    if last_modified: headers['If-Modified-Since']=last_modified
    for _ in range(MAX_REDIRECTS+1):
        try:
            r=_open_once(current,headers,timeout)
            status=getattr(r,'status',200)
            if status == 304:
                h=_header_map(r.headers); r.close(); return b'',None,current,h,True
            if 300 <= status < 400:
                location=r.headers.get('Location')
                r.close()
                if not location: raise ValueError('Redirect response missing Location')
                current=normalize(urllib.parse.urljoin(current,location))
                continue
            data=r.read(max_bytes+1)
            ctype=r.headers.get_content_type()
            final=r.geturl()
            # Validate the resolved destination even if the handler did not redirect.
            assert_public_target(final)
            h=_header_map(r.headers); r.close()
            if len(data)>max_bytes: raise ValueError('Response exceeds configured size limit')
            return data,ctype,final,h,False
        except urllib.error.HTTPError as e:
            if e.code == 304: return b'',None,current,_header_map(e.headers),True
            if 300 <= e.code < 400:
                location=e.headers.get('Location')
                if not location: raise ValueError('Redirect response missing Location')
                current=normalize(urllib.parse.urljoin(current,location)); continue
            raise
    raise ValueError('Too many redirects')

def parse_html(data):
    p=PageParser(); p.feed(data.decode('utf-8','ignore')); text=re.sub(r'\s+',' ',' '.join(p.parts)).strip(); title=' '.join(p.title).strip() or (text[:160] if text else '')
    return title,text

def content_hash(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()

def discover(url):
    url=normalize(url); allowed,state,robots=robots_for(url); sources=[{'url':url,'kind':'website','robots_allowed':allowed,'robots_state':state}]
    base=f'{urllib.parse.urlsplit(url).scheme}://{urllib.parse.urlsplit(url).netloc}'
    for path in ('/feed/','/feed.xml','/rss.xml','/atom.xml'):
        u=base+path
        a,s,_=robots_for(u); sources.append({'url':u,'kind':'feed','robots_allowed':a,'robots_state':s})
    return list({x['url']:x for x in sources}.values())

def collect(url,etag=None,last_modified=None,kind='website'):
    url=normalize(url); allowed,state,robots=robots_for(url)
    if not allowed: return {'url':url,'kind':kind,'status':'blocked_robots','text':'','hash':None,'robots_url':robots}
    data,ctype,final,headers,not_modified=fetch(url,etag=etag,last_modified=last_modified)
    if not_modified: return {'url':final,'kind':kind,'status':'not_modified','hash':None,'headers':headers,'robots_url':robots}
    if 'html' in (ctype or '') or final.endswith(('.html','.htm','/')):
        title,text=parse_html(data)
    else: title=final; text=data.decode('utf-8','ignore')
    return {'url':final,'kind':kind,'status':'ok','text':text,'hash':content_hash(text),'title':title,'content_type':ctype,'headers':headers,'robots_url':robots}
