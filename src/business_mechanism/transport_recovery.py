"""Persistent transport cooldowns; paid counters and failure history never reset."""
import json
import time
from experiments.insight_research.common import Pending, write_json
from experiments.insight_research.langgraph_release_v02.transport import transient


def cooldown(journal):
    if journal.state.get('inflight') or journal.state.get('delivery'): return
    attempt=journal.state['attempts']; path=journal.ws.private/'http'/f'{attempt}.json'
    if not attempt or not path.exists() or not transient(json.loads(path.read_text())): return
    marker=journal.ws.private/'transport_cooldown.json'
    saved=json.loads(marker.read_text()) if marker.exists() else {}
    if saved.get('after_attempt') != attempt:
        streak=1
        for n in range(attempt-1,max(0,attempt-8),-1):
            previous=journal.ws.private/'http'/f'{n}.json'
            if not previous.exists() or not transient(json.loads(previous.read_text())): break
            streak+=1
        saved={'after_attempt':attempt,'failure_streak':streak,'until_unix':time.time()+min(300,30*2**min(streak-1,4))}
        write_json(marker,saved)
    if time.time()<saved['until_unix']: raise Pending('transport_cooldown:'+str(saved['until_unix']))


def resume_transient_window(runtime):
    """Only transient, acknowledged failures may enter another finite slice."""
    limit=runtime.ws.settings['limits']['max_transport_retries']
    if runtime.cp.get('transport_failures',0)<=limit: return None
    journal=runtime.journal; attempt=journal.state['attempts']; path=runtime.ws.private/'http'/f'{attempt}.json'
    if not path.exists() or not transient(json.loads(path.read_text())): return None
    if runtime.cp.get('pending') or journal.state.get('inflight') or journal.state.get('delivery'): return None
    try: cooldown(journal)
    except Pending as error: return runtime.pause(str(error))
    history=runtime.cp.setdefault('transport_retry_windows',[])
    if sum(v['at_unix']>time.time()-3600 for v in history)>=8:
        return runtime.pause('transport_cooldown:'+str(min(v['at_unix'] for v in history if v['at_unix']>time.time()-3600)+3600))
    history.append({'after_attempt':attempt,'at_unix':time.time(),'consecutive_failures':runtime.cp['transport_failures'],
                    'reason':'Acknowledged transient failures; start a new bounded retry slice after persisted backoff. Paid totals unchanged.'})
    runtime.cp['transport_failures_total_before_retry']=runtime.cp.get('transport_failures_total_before_retry',0)+runtime.cp['transport_failures']
    runtime.cp['transport_failures']=0  # Native field is consecutive failures in this retry slice.
    runtime.save(); return None
