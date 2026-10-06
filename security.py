import hashlib, hmac, secrets
from .db import now

KEY_PREFIX = 'cai_live_'

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()

def issue_api_key(prefix=KEY_PREFIX):
    raw = prefix + secrets.token_urlsafe(32)
    return raw, hash_secret(raw)

def verify_api_key(raw: str, stored_hash: str) -> bool:
    if not raw or not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(raw), stored_hash)

def audit(c, customer_id, actor, action, resource_type=None, resource_id=None, metadata=None):
    c.execute('''INSERT INTO audit_log(customer_id,actor,action,resource_type,resource_id,metadata,created_at)
                 VALUES(?,?,?,?,?,?,?)''', (customer_id, actor, action, resource_type, resource_id, metadata or '{}', now()))
    c.commit()
