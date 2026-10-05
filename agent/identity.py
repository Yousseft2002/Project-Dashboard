import uuid
from collector import write_json

def identity(config, path):
    # A new random UUID is independent of hardware and friendly names. Keep the
    # existing server credential identity during migration; never silently re-pair.
    if not config.get('agent_id'):
        config['agent_id'] = str(uuid.uuid4())
        write_json(path, config)
    return str(uuid.UUID(config['agent_id']))
