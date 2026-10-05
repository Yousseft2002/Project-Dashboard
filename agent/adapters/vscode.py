"""Deferred adapter: not enabled in the Git MVP."""
def status():
    return {"status": "unavailable", "enabled": False, "reason": "Deferred until Git synchronization passes live acceptance"}
