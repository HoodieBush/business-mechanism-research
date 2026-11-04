from ..common import Pending,encoded,write_json
from ..growth_probe_v03.orchestrator import ResearchRuntime as PreviousRuntime
from token_budget import SharedTokenBudget,reservation_bound


class ResearchRuntime(PreviousRuntime):
    def compact(self):
        try:return super().compact()
        except Pending as error:
            if not str(error).startswith('fixed critical context/latest complete turn still exceeds guard'):
                raise
            messages=self.cp['messages']
            starts=[i for i,m in enumerate(messages) if i>=2 and m['role']=='assistant']
            if not starts:raise
            payload=self.payload(self.initial()+messages[starts[-1]:])
            size=len(encoded(payload).encode());bound=reservation_bound(payload)
            maximum=self.ws.settings['limits']['max_request_bytes']
            local=self.journal.study.snapshot()['remaining_tokens']
            project=SharedTokenBudget(self.config['token_budget_pointer']).snapshot()['remaining_admission_tokens']
            dimensions=[]
            if size>maximum:dimensions.append('request_bytes')
            if bound>local:dimensions.append('study_token_admission')
            if bound>project:dimensions.append('project_token_admission')
            diagnostic={'minimum_retained_complete_turn_bytes':size,'maximum_request_bytes':maximum,
                'minimum_retained_complete_turn_reservation':bound,'study_remaining_tokens':local,
                'project_remaining_tokens':project,'limiting_dimensions':dimensions,
                'paid_tool_work_pending':bool(self.cp.get('pending') or self.journal.state.get('inflight') or self.journal.state.get('delivery')),
                'scientific_record_statuses_unchanged':True,'exact_archive_and_paid_work_retained':True,
                'classification_scope':'Execution admission only, never a scientific refutation or automatic quota extension.'}
            write_json(self.ws.private/'execution_pause_diagnostic.json',diagnostic)
            if dimensions:
                raise Pending('Execution admission stop ['+','.join(dimensions)+']: next complete request reserves '+str(bound)+
                    ' tokens; study remaining '+str(local)+', project remaining '+str(project)+
                    '; bytes '+str(size)+'/'+str(maximum)+'. Exact originals and paid work retained; no scientific verdict inferred.') from error
            raise
