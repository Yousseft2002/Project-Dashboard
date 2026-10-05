import json
import re
from collector import CollectorError
from . import VERSION

def flush(client, config, queue, force=False):
    rows=queue.projects(force)
    for offset in range(0,len(rows),20):
        batch=rows[offset:offset+20]
        result=client.request('/api/agent/v1/projects',{'device_id':config['device_id'],'agent_version':VERSION,
            'projects':[json.loads(row['data']) for row in batch],'sources':[{'name':'git','status':'connected'}]})
        ids=result.get('project_ids',[])
        if result.get('database_write') is not True or result.get('device_id')!=config['device_id'] or len(ids)!=len(batch) or any(not isinstance(pid,str) or not re.fullmatch(r'[\w.-]{1,100}',pid) for pid in ids):
            raise CollectorError('Project receipt invalid; local queue retained')
        queue.mapped(batch,ids)
    events=queue.events()
    if events:
        result=client.request('/api/agent/v1/events/batch',{'device_id':config['device_id'],'agent_version':VERSION,'events':events})
        acknowledgements=result.get('acknowledged')
        sent={event['event_id'] for event in events}
        if result.get('ok') is not True or result.get('device_id')!=config['device_id'] or result.get('database_write') is not True or not isinstance(acknowledgements,list) or any(event_id not in sent for event_id in acknowledgements):
            raise CollectorError('Event receipt invalid; local queue retained')
        queue.acknowledge(acknowledgements)
        if result.get('rejected'): raise CollectorError('Some events were rejected; retained locally for diagnostics')
    return bool(rows or events)
