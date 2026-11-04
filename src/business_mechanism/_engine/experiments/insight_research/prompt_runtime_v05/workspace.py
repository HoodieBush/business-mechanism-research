import json
from ..growth_probe_v14.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def context(self):
        context=super().context()
        row=self.db.execute("SELECT id,body FROM events WHERE json_extract(body,'$.tool')='update_research_state' AND json_array_length(json_extract(body,'$.arguments.knowledge_updates'))>0 ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            event=json.loads(row[1]);result=event.get('result',{})
            context['latest_memory_write_receipt']={
                'action_ref':'event:'+str(row[0]),'state_ref':result.get('ref'),
                'created_memory_refs':result.get('knowledge_refs',[]),
                'knowledge_rejections':result.get('knowledge_rejections',[])[:3],
                'rejection_count':len(result.get('knowledge_rejections',[])),
                'read_full_receipt':{'tool':'read_memory','ref':'event:'+str(row[0])},
                'call_ok':result.get('ok',True),
                'call_error':result.get('error'),
                'meaning':'Execution receipt only. A saved state does not imply optional knowledge was saved; inspect returned refs and rejections. Not scientific truth.'}
        return context

    def _checked_dispatch(self, name, args, key):
        result = super()._checked_dispatch(name, args, key)
        if name == 'read_context' and 'context_location' in result:
            result = {**result, 'context_location': 'Automatically refreshed versioned current_research_context_v1 message; read_context receipt is navigation only.'}
        return result
