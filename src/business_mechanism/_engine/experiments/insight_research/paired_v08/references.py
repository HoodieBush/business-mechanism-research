"""Provenance parsing of explicitly cited produced artifacts, without new claims."""
import fcntl,json,re
from ..common import digest,sha,write_json
from ..memory import file_refs
from ..paired_v06.references import NormalizedCalls as Previous

FILE=re.compile(r'file:[0-9a-f]{24}(?![0-9a-f])')

class NormalizedCalls(Previous):
    def normalize_submission(self,name,args):
        corrected,changes=super().normalize_submission(name,args);writers={}
        review=corrected if name=='record_review' else corrected.get('review') if name=='review_claim' and isinstance(corrected,dict) else None
        if isinstance(review,dict):
            if hasattr(self,'view'):
                actions=[(r,json.loads(b)) for r,b in self.db.execute('SELECT ref,body FROM actions')]
            else:actions=[('event:'+str(n),json.loads(b)) for n,b in self.db.execute('SELECT id,body FROM events')]
            for issue in review.get('issues',[]):
                if issue.get('basis')!='recomputed' or issue.get('action_refs'):continue
                cited=set(FILE.findall(' '.join(issue.get('evidence_locations',[]))))|set(issue.get('check_artifact_refs',[]))
                selected=[];origins=[]
                for ref in sorted(cited):
                    try:path,_=self.file(ref)
                    except (ValueError,KeyError):continue
                    if not path.is_relative_to(self.science):continue
                    producing=[r for r,a in actions if a['tool'] in ('query_data','run_python','run_test') and ref in set(file_refs(a['result']))]
                    if len(producing)==1:
                        selected.append(producing[0]);origins.append({'explicit_artifact_ref':ref,'unique_producing_action':producing[0]})
                if selected:
                    issue['action_refs']=list(dict.fromkeys(selected));changes['explicit_action_links'][issue['issue_id']]=issue['action_refs'];writers[issue['issue_id']]=origins
        changes['artifact_writer_links']=writers;return corrected,changes

    def call(self,name,args,operation_id):
        corrected,changes=self.normalize_submission(name,args)
        # Skip the previous normalizer's call wrapper; validation/dispatch still run.
        result=super(Previous,self).call(name,corrected,operation_id)
        if changes['aliases'] or changes['explicit_action_links']:
            path=self.science/'reference_normalizations'/(digest(operation_id)+'.json')
            item={'operation_id':operation_id,'tool':name,'submitted_arguments':args,'canonical_arguments':corrected,**changes,
                'scope':'Only registered unique version aliases, explicit existing actions, and unique producers of explicitly cited own artifacts. No opinion/scientific wording edits; provenance is not scientific certification.',
                'accepted':result.get('ok') is not False}
            if path.exists():
                if json.loads(path.read_text())!=item:raise ValueError('normalization receipt changed')
            else:write_json(path,item)
        return result

def recover_auditable_response(runtime,tool):
    """Revalidate original paid B-targeted opinion under the new declared policy."""
    ws=runtime.ws;journal=runtime.journal
    if not hasattr(journal,'state') or ws.report():return None
    lock=(ws.private/'runtime.lock').open('a')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return None
        cp=json.loads(runtime.path.read_text());transport=json.loads(journal.path.read_text())
        if cp.get('pending') or transport.get('inflight') or transport.get('delivery'):return None
        if cp.get('delivered_attempt')!=transport['attempts'] or cp['messages'][-1].get('role')!='tool':return None
        last=json.loads(cp['messages'][-1]['content'])
        if last.get('ok') is not False or 'affected_refs must identify actual scientific objects' not in last.get('error',''):return None
        path=ws.private/'turns'/(str(cp['responses'])+'.json');raw=json.loads(path.read_text())
        if json.loads((ws.private/'http'/(str(cp['delivered_attempt'])+'.json')).read_text()).get('response')!=raw:return None
        calls=raw['choices'][0]['message'].get('tool_calls') or []
        if raw['choices'][0].get('finish_reason')!='tool_calls' or len(calls)!=1:return None
        call=calls[0]
        if call['function']['name']!=tool or call['id']!=cp['messages'][-1].get('tool_call_id'):return None
        args=json.loads(call['function']['arguments']);body=args if tool=='record_review' else args.get('review',{})
        record=ws.view.record if hasattr(ws,'view') else ws.record
        try:responses=[r for i in body.get('issues',[]) for r in i.get('affected_refs',[]) if record(r)['record_type']=='review_response']
        except (ValueError,KeyError,TypeError):return None
        if not responses:return None
        key=digest(['auditable_response_policy_v08',sha(path),args]);result=ws.call(tool,args,key)
        receipt={'source_turn_sha256':sha(path),'source_paid_attempt':cp['delivered_attempt'],'policy':'B researcher decisions auditable, still not factual premises',
            'affected_response_refs':responses,'new_model_calls':0,'scientific_wording_edited':False,'result_ref':result.get('ref'),'accepted':result.get('ok') is not False,'prior_error':last}
        out=ws.science/'reference_normalizations'/('policy_recovery_'+key+'.json')
        if not out.exists():write_json(out,receipt)
        return receipt
    finally:lock.close()
