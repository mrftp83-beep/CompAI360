import json
from datetime import datetime, timezone
SEVERITY={'pricing':5,'promotion':4,'location':5,'hiring':3,'service':4,'website':2,'news':3}

def build_findings(changes):
    out=[]
    for c in changes:
        cat=c.get('category') or c.get('change_type','website'); sev=SEVERITY.get(cat,2)
        out.append({'category':cat,'claim':c.get('summary','Change detected'),'finding_type':'fact','inference':None,'confidence':0.95,'severity':sev,'evidence':c.get('evidence',[])})
    return sorted(out,key=lambda x:(x['severity'],x['confidence']),reverse=True)

def llm_prompt(changes):
    return {'system':'You are a competitive-intelligence analyst. Separate observed facts from inference. Never invent evidence. Return strict JSON.', 'schema':{'findings':[{'category':'pricing|promotion|location|hiring|service|website|news','claim':'string','inference':'string|null','confidence':'0..1','severity':'1..5','evidence_ids':['string']} ]}, 'changes':changes}

def render_report(competitor_name,findings,period_start=None,period_end=None):
    d=datetime.now(timezone.utc).date().isoformat(); lines=[f'# Competitive Intelligence Report — {d}','',f'## {competitor_name}','',f'Period: {period_start or "previous run"} → {period_end or d}','']
    if not findings: return '\n'.join(lines+['No material changes detected in the collected sources.'])
    lines+=['## Material Changes','']
    for f in findings: lines.append(f"- **Severity {f['severity']}/5 — {f['category']}**: {f['claim']} (confidence {f['confidence']:.0%})")
    lines += ['','## Facts vs. Inference','','The findings above are source-backed observations. Strategic interpretations are generated separately and must cite the underlying evidence.']
    return '\n'.join(lines)
