"""Privacy controls: retention and customer-data lifecycle helpers."""
from datetime import datetime, timezone, timedelta
from .db import connect, now, is_postgres

def purge_expired(db='ci_intelligence.db'):
    c=connect(db); total=0
    customers=c.execute('SELECT id,retention_days FROM customers').fetchall()
    for customer in customers:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=int(customer['retention_days']))).isoformat()
        # Observations and change records are customer-scoped through competitors.
        c.execute('DELETE FROM observations WHERE observed_at<%s AND source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=%s)' if is_postgres(c) else 'DELETE FROM observations WHERE observed_at<? AND source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?)',(cutoff,customer['id']))
        total += c.rowcount
        c.execute('DELETE FROM changes WHERE detected_at<%s AND source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=%s)' if is_postgres(c) else 'DELETE FROM changes WHERE detected_at<? AND source_id IN (SELECT s.id FROM sources s JOIN competitors x ON x.id=s.competitor_id WHERE x.customer_id=?)',(cutoff,customer['id']))
        total += c.rowcount
    c.commit(); return total
