"""Bounded active context, exact owned transcript archive; no invented science summary."""
import json,re
from pathlib import Path
from ..common import Pending,digest,encoded,write_json
from token_budget import reservation_bound

PREFIXES=('own_context:','own_process:','own_log:')

def own_context(ws):
    folder=ws.private/'context_archives';latest=folder/'latest.json'
    return {'owner_scope':'This role only; never another role private conversation.',
        'latest_archive':json.loads(latest.read_text()) if latest.exists() else None,
        'worklog_ref':'own_log:0','raw_process_ref_format':'own_process:<positive response number>','process_count':len(list((ws.private/'turns').glob('[0-9]*.json'))),
        'policy':'Exact original conversations/actions are memory, not factual premises. Reconstruct uncheckpointed work using the log/raw originals; no automatic interpretation or result incorporation.'}

def read_own_memory(ws,ref,offset=0,limit=12000):
    if ref.startswith('own_context:'):
        name=ref[len('own_context:'):]
        if not re.fullmatch('[a-f0-9]{64}',name):raise ValueError('exact own context archive ID required')
        path=ws.private/'context_archives'/(name+'.json')
        if not path.is_file():raise ValueError('owned context archive not found')
        value=json.loads(path.read_text())
        if digest(value)!=name:raise Pending('owned context archive version changed')
    elif ref.startswith('own_process:'):
        number=ref[len('own_process:'):]
        if not number.isdecimal() or not 0<int(number)<=100000:raise ValueError('exact owned positive process number required')
        path=ws.private/'turns'/(str(int(number))+'.json')
        if not path.is_file():raise ValueError('owned process record not found')
        value=json.loads(path.read_text())
    else:
        start=ref[len('own_log:'):]
        if not start.isdecimal():raise ValueError('owned log offset required')
        start=int(start);peer=(ws.private/'critic.sqlite').exists();entries=[]
        if peer:
            rows=ws.db.execute('SELECT ref,body FROM actions ORDER BY rowid LIMIT 21 OFFSET ?',(start,)).fetchall()
            for ref0,body in rows[:20]:
                item=json.loads(body);result=item['result']
                entries.append({'action_ref':ref0,'tool':item['tool'],'purpose':item['arguments'].get('purpose',''),
                    'file_refs':[f['ref'] for f in result.get('files',[])], 'complete_action':item if len(encoded(item))<5000 else {'original_arguments_and_result':'Read the exact context/process archive; all artifacts stay available by refs.'}})
        else:
            rows=ws.db.execute("SELECT id,body FROM events WHERE json_extract(body,'$.tool')!='model_response' ORDER BY id LIMIT 21 OFFSET ?",(start,)).fetchall()
            for number,body in rows[:20]:
                item=json.loads(body);entries.append({'event_ref':'event:'+str(number),'tool':item['tool'],'purpose':item['arguments'].get('purpose',''),
                    'original_action_ref':'event:'+str(number),'process_ref':item.get('process_ref'),'read_original':'read_memory(event:'+str(number)+')'})
        value={'entries':entries,'next_ref':'own_log:'+str(start+20) if len(rows)>20 else None,'interpretation':'Owned action navigation only, not a scientific summary.'}
    text=encoded(value);end=offset+limit
    return {'ref':ref,'text':text[offset:end],'sha256':digest(value),'next_offset':end if end<len(text) else None,'memory_only':True,'scientific_certification':False}

def rebuild_from_owned_journal(runtime):
    ws=runtime.ws;cp=runtime.cp;journal=runtime.journal
    if cp.get('pending') or not hasattr(journal,'state') or journal.state.get('inflight') or journal.state.get('delivery'):
        raise Pending('drain all paid role work before journal context rebuild')
    number=cp.get('responses',0)
    if not number or not (ws.private/'turns'/(str(number)+'.json')).is_file():
        raise Pending('durable owned model response required for journal context rebuild')
    messages=cp['messages'];archive_id=digest(messages);folder=ws.private/'context_archives';path=folder/(archive_id+'.json')
    if path.exists():
        if json.loads(path.read_text())!=messages:raise Pending('owned context hash collision/change')
    else:write_json(path,messages)
    write_json(folder/'latest.json',{'archive_id':archive_id,'read_ref':'own_context:'+archive_id,'last_model_response':number,
        'no_scientific_summary_generated':True,'no_results_marked_incorporated':True})
    starts=[i for i,m in enumerate(messages) if i>=2 and m['role']=='assistant']
    recent=min(len(starts),ws.settings['limits'].get('recent_turns',4))
    for count in range(recent,0,-1):
        rebuilt=runtime.initial()+messages[starts[-count]:]
        payload=runtime.payload(rebuilt)
        remaining=journal.snapshot()['remaining_admission_tokens']
        if len(encoded(payload).encode())<=ws.settings['limits']['max_request_bytes'] and reservation_bound(payload)<=remaining:
            cp['messages']=rebuilt;cp['context_windows']=cp.get('context_windows',0)+1
            cp['journal_recovery']={'archive_id':archive_id,'retained_complete_recent_turns':count,'summary_generated':False}
            runtime.save();return
    raise Pending('fixed critical context/latest complete turn still exceeds guard; exact archive and paid work retained')
