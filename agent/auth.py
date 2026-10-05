"""Reuse the already-paired Windows DPAPI credential; never save plaintext."""
from collector import load_token, CollectorError

def credential(config, path):
    token = load_token(config, path)
    if not token: raise CollectorError('No protected credential. Pair this computer first.')
    return token
