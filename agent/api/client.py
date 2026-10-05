import platform
from collector import Client, CollectorError
from .. import VERSION

class AgentClient(Client):
    def register_agent(self, config):
        result = self.request('/api/agent/v1/register', {
            'device_id':config['device_id'], 'device_name':config['device_name'],
            'installation_id':config['installation_id'], 'collector_version':VERSION,
            'platform':platform.system(), 'agent_id':config['agent_id']})
        if result.get('registered') is not True or result.get('device_id') != config['device_id']:
            raise CollectorError('Agent registration was not confirmed')
        return result

    def heartbeat_agent(self, config, pending):
        result = self.request('/api/agent/v1/heartbeat', {'device_id':config['device_id'], 'agent_version':VERSION, 'queue_size':pending})
        if result.get('database_write') is not True or result.get('device_id') != config['device_id']:
            raise CollectorError('Agent heartbeat was not confirmed')
        return result
