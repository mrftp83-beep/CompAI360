import xml.etree.ElementTree as ET
from .collector import normalize, robots_for, fetch

def collect_feed(url):
    url=normalize(url); allowed,state,robots=robots_for(url)
    if not allowed: return {'status':'blocked_robots','url':url,'robots_url':robots,'items':[]}
    data,ctype,final,headers,not_modified=fetch(url,max_bytes=2_000_000)
    if not_modified: return {'status':'not_modified','url':final,'items':[],'headers':headers}
    if len(data) > 2_000_000: raise ValueError('Feed exceeds configured size limit')
    root=ET.fromstring(data); items=[]
    for item in root.findall('.//item'):
        def txt(tag):
            n=item.find(tag); return (n.text or '').strip() if n is not None else ''
        items.append({'title':txt('title'),'url':txt('link'),'published':txt('pubDate'),'summary':txt('description')})
    ns={'a':'http://www.w3.org/2005/Atom'}
    for item in root.findall('.//a:entry',ns):
        title=item.find('a:title',ns); link=item.find('a:link',ns); published=item.find('a:published',ns); updated=item.find('a:updated',ns); summary=item.find('a:summary',ns)
        pub=published if published is not None else updated
        items.append({'title':title.text.strip() if title is not None and title.text else '', 'url':link.attrib.get('href','') if link is not None else '', 'published':pub.text.strip() if pub is not None and pub.text else '', 'summary':summary.text.strip() if summary is not None and summary.text else ''})
    return {'status':'ok','url':final,'robots_url':robots,'items':items[:100],'headers':headers}
