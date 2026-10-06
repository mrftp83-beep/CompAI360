import re
PRICE_RE=re.compile(r'(?i)(?:\$|USD\s*)(\d{1,5}(?:[,.]\d{3})?(?:\.\d{1,2})?)')
KEYWORDS={'pricing':['price','pricing','cost','starting at','from $','per month','per year'],'promotion':['sale','special','discount','off','coupon','deal','limited time'],'service':['services','installation','repair','maintenance','financing','subscription'],'hiring':['careers','jobs','hiring','join our team','open position'],'location':['location','locations','new office','opening','now serving']}
def extract_observations(text):
    low=text.lower(); out=[]; prices=[]
    for m in PRICE_RE.finditer(text):
        try: prices.append(float(m.group(1).replace(',','')))
        except ValueError: pass
    if prices: out.append({'category':'pricing','field':'advertised_prices','value':prices[:20]})
    for cat,words in KEYWORDS.items():
        hits=[w for w in words if w in low]
        if hits: out.append({'category':cat,'field':'signals','value':hits})
    return out

def categorize_change(before,after):
    b=set(x.get('category') for x in extract_observations(before or '')); a=set(x.get('category') for x in extract_observations(after or '')); cats=sorted(a|b)
    return cats[0] if cats else 'website'
