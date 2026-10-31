"""Netlify signed proxy boundary. No database or deployment secrets enter static assets."""
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlsplit
from fastapi import HTTPException


def netlify_only():
    return os.environ.get('INVENTORY_NETLIFY_ONLY','').lower()=='true'


def enabled():
    return os.environ.get('INVENTORY_CLOUD', '').lower() == 'true'


def origins():
    values = [v.strip().rstrip('/') for v in os.environ.get('PUBLIC_ORIGINS', '').split(',') if v.strip()]
    for value in values:
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment or '*' in value:
            raise RuntimeError('PUBLIC_ORIGINS 必須為完整 HTTPS 網站來源，不可包含路徑或萬用字元')
    return values


def validate():
    if not enabled():
        return
    if netlify_only():
        if not os.environ.get('DATABASE_URL') or not origins() or len(os.environ.get('NETLIFY_BRIDGE_SECRET',''))<32 or len(os.environ.get('BOOTSTRAP_TOKEN',''))<32:
            raise RuntimeError('尚未完成Netlify資料庫、網站來源或首次設定金鑰')
        return
    if not os.environ.get('DATABASE_URL') or not origins() or not os.environ.get('NETLIFY_SITE_ID'):
        raise RuntimeError('尚未完成雲端資料庫、網站來源或 Netlify 網站識別設定')
    for key in ('NETLIFY_PROXY_SECRET', 'BOOTSTRAP_TOKEN'):
        if len(os.environ.get(key, '')) < 32:
            raise RuntimeError(key + ' 至少需要32個字元')
    if not os.environ.get('RENDER_EXTERNAL_HOSTNAME'):
        raise RuntimeError('尚未設定後端主機名稱')


def verify_proxy(token):
    """Verify documented Netlify HS256 JWS, expiry, issuer and exact site identity."""
    if netlify_only():
        expected=os.environ.get('NETLIFY_BRIDGE_SECRET','')
        return len(expected)>=32 and isinstance(token,str) and hmac.compare_digest(token,expected)
    try:
        if not token or len(token) > 8192:
            return False
        head, payload, signature = token.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        header = json.loads(decode(head))
        claims = json.loads(decode(payload))
        if not isinstance(header, dict) or not isinstance(claims, dict):
            return False
        secret = os.environ.get('NETLIFY_PROXY_SECRET', '')
        if len(secret) < 32 or header.get('alg') != 'HS256':
            return False
        expected = hmac.new(secret.encode(), (head + '.' + payload).encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, decode(signature)):
            return False
        expiry = claims.get('exp')
        return bool(type(expiry) in (int, float) and expiry > time.time() and claims.get('iss') == 'netlify' and claims.get('netlify_id') == os.environ.get('NETLIFY_SITE_ID'))
    except (ValueError, TypeError, KeyError, UnicodeError):
        return False


def check_bootstrap(body):
    expected = os.environ.get('BOOTSTRAP_TOKEN', '')
    supplied = body.get('setup_token', '')
    if len(expected) < 32 or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, '首次設定金鑰不正確，請由部署管理員操作')
