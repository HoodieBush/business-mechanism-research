"""Resolve only unique already registered SHA256 versions; never create evidence."""
import fcntl,json,re
from ..common import digest,sha,write_json

PATTERN=re.compile(r'file:([0-9a-f]{64})(?![0-9a-f])')
ACTION_PATTERN=re.compile(r'check:[0-9a-f]{24}|event:[0-9]+|C[0-9a-f]{16}|action:[0-9]+')

def normalize(value,databases):
    aliases={}
    def string(text):
        def replace(match):
            candidates={r for db in databases for r, in db.execute('SELECT ref FROM files WHERE hash=?',(match[1],))}
            if len(candidates)!=1:return match[0]
            canonical=next(iter(candidates));aliases[match[0]]=canonical;return canonical
        return PATTERN.sub(replace,text)
    def walk(item):
        if isinstance(item,str):return string(item)
        if isinstance(item,list):return [walk(x) for x in item]
        if isinstance(item,dict):return {k:walk(v) for k,v in item.items()}
        return item
    return walk(value),aliases

class NormalizedCalls:
    def reference_databases(self):
        return (self.db,self.view.db) if hasattr(self,'view') else (self.db,)

    def call(self,name,args,operation_id):
        corrected,changes=self.normalize_submission(name,args)
        result=super().call(name,corrected,operation_id)
        if changes['aliases'] or changes['explicit_action_links']:
            path=self.science/'reference_normalizations'/(digest(operation_id)+'.json')
            receipt={'operation_id':operation_id,'tool':name,'submitted_arguments':args,'canonical_arguments':corrected,
                     **changes,'scope':'Only unique registered version aliases and already explicit, existing issue action references are parsed; scientific wording and normal validation retained.','accepted':result.get('ok') is not False}
            if path.exists():
                if json.loads(path.read_text())!=receipt:raise ValueError('normalization receipt changed')
            else:write_json(path,receipt)
        return result

    def normalize_submission(self,name,args):
        corrected,aliases=normalize(args,self.reference_databases());links={}
        review=corrected if name=='record_review' else corrected.get('review') if name=='review_claim' and isinstance(corrected,dict) else None
        validator=self.action if hasattr(self,'view') else self.review_action
        if isinstance(review,dict):
            for issue in review.get('issues',[]):
                if not isinstance(issue,dict):continue
                if issue.get('basis')!='recomputed' or issue.get('action_refs'):continue
                refs=[]
                for location in issue.get('evidence_locations',[]):
                    if not isinstance(location,str):continue
                    for ref in ACTION_PATTERN.findall(location):
                        try:validator(ref)
                        except (ValueError,KeyError,TypeError):continue
                        if ref not in refs:refs.append(ref)
                if refs:issue['action_refs']=refs;links[issue['issue_id']]=refs
        return corrected,{'aliases':aliases,'explicit_action_links':links}

def recover_paid_submission(runtime,tool):
    """One narrow replay of the last rejected, fully paid scientific submission.

    No model call, quota reset, opinion edit, arbitrary tool replay or fallback.
    Current schema/reference/object/version checks run again on canonical refs.
    """
    ws=runtime.ws;journal=runtime.journal
    if not hasattr(journal,'state'):return None
    lock=(ws.private/'runtime.lock').open('a')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return None
        if runtime.path.exists():runtime.cp=json.loads(runtime.path.read_text())
        if journal.path.exists():journal.state=json.loads(journal.path.read_text())
        return _recover_locked(runtime,tool)
    finally:lock.close()

def _recover_locked(runtime,tool):
    ws=runtime.ws;cp=runtime.cp;journal=runtime.journal
    if ws.report() or cp.get('pending') or journal.state.get('inflight') or journal.state.get('delivery'):return None
    if cp.get('delivered_attempt')!=journal.state.get('attempts'):return None
    messages=cp.get('messages',[])
    if not messages or messages[-1].get('role')!='tool':return None
    try:last=json.loads(messages[-1]['content'])
    except (ValueError,TypeError):return None
    if last.get('ok') is not False or not any(text in last.get('error','') for text in ('invalid_ref','recomputed issue needs actual check actions')):return None
    path=ws.private/'turns'/(str(cp['responses'])+'.json');raw=json.loads(path.read_text())
    paid=ws.private/'http'/(str(cp['delivered_attempt'])+'.json')
    if not paid.exists() or json.loads(paid.read_text()).get('response')!=raw:return None
    choice=raw['choices'][0]
    calls=choice['message'].get('tool_calls') or []
    if choice.get('finish_reason')!='tool_calls' or len(calls)!=1:return None
    call=calls[0]
    if call['function']['name']!=tool or call['id']!=messages[-1].get('tool_call_id'):return None
    original=json.loads(call['function']['arguments']);corrected,changes=ws.normalize_submission(tool,original)
    if not changes['aliases'] and not changes['explicit_action_links']:return None
    key=digest(['paid_reference_recovery_v1',sha(path),corrected])
    receipt=ws.science/'reference_normalizations'/('recovery_'+key+'.json')
    if receipt.exists():return json.loads(receipt.read_text())
    result=ws.call(tool,original,key)
    body={'source_turn_sha256':sha(path),'source_turn':cp['responses'],'source_paid_attempt':cp['delivered_attempt'],
          'prior_error':last,**changes,'recovery_operation':key,'result_ref':result.get('ref'),'result_ok':result.get('ok') is not False,
          'new_model_calls':0,'costs_and_request_counters_reset':False,'scientific_decision_edited':False}
    if not receipt.exists():write_json(receipt,body)
    return body
