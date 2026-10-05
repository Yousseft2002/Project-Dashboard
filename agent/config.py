from pathlib import Path
from collector import DEFAULT_CONFIG, read_json, server_url, PRODUCTION_URL
from .security import workspace

def load(path=DEFAULT_CONFIG, local_development=False):
    path = Path(path).resolve()
    config = read_json(path)
    origin = server_url(config, local_development)
    if not local_development and origin != PRODUCTION_URL:
        raise ValueError('Agent production target must be the approved Project Dashboard origin')
    if not config.get('device_id') or not config.get('installation_id'):
        raise ValueError('Pair this computer with setup_collector.ps1 first')
    roots = config.get('workspaces')
    if not isinstance(roots, list) or not 1 <= len(roots) <= 100:
        raise ValueError('Select 1–100 approved repository folders')
    config['workspaces'] = list(dict.fromkeys(str(workspace(root)) for root in roots))
    config['server'] = origin
    config['reconcile_seconds'] = max(600, int(config.get('reconcile_seconds', 900)))
    return config, path
