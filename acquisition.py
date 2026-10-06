import re, json
from datetime import datetime, timezone
from .extract import extract_observations

INDUSTRY_TERMS = {
    'hvac': ['hvac','heating','air conditioning','furnace','ac repair'],
    'plumbing': ['plumbing','plumber','drain cleaning','water heater'],
    'roofing': ['roofing','roof repair','shingles','roof replacement'],
    'electrical': ['electrical','electrician','panel upgrade','wiring'],
    'pest control': ['pest control','exterminator','termite','rodent'],
    'landscaping': ['landscaping','lawn care','tree service','irrigation'],
}

def _domain(url):
    m=re.search(r'https?://(?:www\.)?([^/]+)', url or '')
    return m.group(1).lower() if m else ''

def lead_score(business_name, website, competitor_count=0, industry=''):
    score=0; reasons=[]
    if website.startswith(('https://','http://')):
        score += 15; reasons.append('has a business website')
    if competitor_count >= 3:
        score += 25; reasons.append('has at least three candidate competitors')
    elif competitor_count:
        score += 10; reasons.append('has identified competitors')
    if industry.lower() in INDUSTRY_TERMS:
        score += 20; reasons.append('matches an initially supported local-service vertical')
    if len(business_name.strip()) >= 3:
        score += 10
    return min(score,100), reasons

def build_preview(business_name, competitor, changes=None):
    changes=changes or []
    findings=[]
    for c in changes:
        findings.append({
            'category': c.get('category') or c.get('change_type','website'),
            'claim': c.get('summary','Change detected'),
            'evidence': c.get('evidence',{}),
        })
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'business': business_name,
        'competitor': competitor,
        'preview_notice': 'Preview uses only source-backed observations supplied to the engine. It is not a complete market assessment.',
        'findings': findings[:7],
        'cta': 'Start continuous monitoring to receive recurring competitor intelligence.'
    }

def outreach_draft(business_name, competitor_names, finding_count):
    competitors=', '.join(competitor_names[:3]) if competitor_names else 'several competitors in your market'
    return (f"Hi {business_name} team,\n\n"
            f"We built a tool that continuously monitors competitors and turns meaningful changes into a short intelligence report. "
            f"For your market, we can monitor {competitors}.\n\n"
            f"We found {finding_count} potentially relevant change(s) in the preview data we reviewed. "
            f"The service is designed to separate observed facts from analysis and show the source and date behind each finding.\n\n"
            f"If useful, you can review a free preview before deciding whether ongoing monitoring is worth paying for.\n\n"
            f"— CompAI360")


def build_public_assessment(business_name, industry='', competitors=None, priorities=None):
    """Create a no-cost sales assessment without claiming unverified competitor facts.

    This is intentionally deterministic and does not collect or persist visitor data.
    It tells a prospect what the service can monitor and shows the report format.
    """
    competitors = [str(x).strip() for x in (competitors or []) if str(x).strip()]
    priorities = [str(x).strip() for x in (priorities or []) if str(x).strip()]
    modules = [
        ('Pricing intelligence', 'pricing, packages, fees, discounts and financing language'),
        ('Marketing intelligence', 'promotions, offers, campaigns and positioning changes'),
        ('Reputation intelligence', 'review themes and recurring customer complaints where permitted'),
        ('Expansion intelligence', 'new locations, service areas and expansion signals'),
        ('Workforce intelligence', 'public hiring and role changes where permitted'),
        ('Industry intelligence', 'market and regulatory developments relevant to your business'),
    ]
    selected = [m for m in modules if not priorities or any(p.lower() in m[0].lower() or p.lower() in m[1].lower() for p in priorities)]
    if not selected:
        selected = modules
    cadence = 'Weekly' if len(competitors) <= 15 else 'Daily + weekly digest'
    return {
        'business': business_name,
        'industry': industry or 'your industry',
        'competitors_entered': competitors[:50],
        'monitoring_cadence': cadence,
        'recommended_modules': [{'name': n, 'scope': d} for n,d in selected],
        'sample_finding': {
            'status': 'illustrative',
            'observed_fact': 'A monitored competitor changes a public offer, service page, location, job posting, or other permitted source.',
            'analysis': 'The engine can assess whether the change is likely relevant to your competitive position.',
            'evidence': 'Production findings include source URL and observation date.',
            'confidence': 'Shown with each production finding; no confidence is invented for this assessment.'
        },
        'next_step': 'Review the assessment, then activate continuous monitoring when the value is clear.',
        'disclaimer': 'This assessment is a product demonstration, not a claim that these changes were observed for the businesses entered.'
    }
