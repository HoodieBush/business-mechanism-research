import json
import time
from ..common import Pending,digest,encoded,sha
from ..paired_v16.orchestrator import ResearchRuntime as PreviousRuntime
from ..growth_probe_v02.orchestrator import ResearchRun as PreviousRun


class ResearchRuntime(PreviousRuntime):
    def drain(self,deadline=None):
        proof=self.ws.private/'paid_registration_recovery.json'
        pending=self.cp.get('pending')
        if not proof.exists() or not pending:
            return super().drain(deadline)
        migration=json.loads(proof.read_text())
        if pending['response']!=migration['response']:
            return super().drain(deadline)
        raw=self.ws.private/'turns'/(str(pending['response'])+'.json')
        if sha(raw)!=migration['raw_turn_sha256']:
            raise Pending('Paid registration original changed; no replay')
        self.ws.response_ref='process:'+str(pending['response'])
        while pending['cursor']<len(pending['calls']):
            if deadline is not None and time.monotonic()+45>deadline:
                raise Pending('Tool slice deadline; exact paid remainder retained')
            call=pending['calls'][pending['cursor']]
            if call['name']!='save_hypothesis' or call['id'] not in migration['call_ids']:
                raise Pending('Only proven original side-effect-free registrations can recover')
            # Preserve operation identity of the paid unfinished call. Changing
            # workspace paths must not leave its original prepared row orphaned.
            key=digest([migration['original_workspace'],pending['response'],call['id']])
            result=self.ws.call(call['name'],call['args'],key)
            self.cp['messages'].append({'role':'tool','tool_call_id':call['id'],'content':encoded(result)})
            pending['cursor']+=1;self.save()
        self.cp['pending']=None;self.save()


class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)
