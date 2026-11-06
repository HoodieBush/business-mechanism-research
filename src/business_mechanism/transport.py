"""Native model wire protocol; an external research ledger is optional."""
from copy import deepcopy
import json
import time
import urllib.error
import urllib.request
from experiments.insight_research.common import Pending, digest, encoded
from experiments.insight_research.runtime import Journal
from experiments.insight_research.cost_context_v01.runtime import ContextStudyJournal
from experiments.insight_research.langgraph_release_v02.transport import Cooldown
from model_credentials import load_api_key
from model_protocol import generation_request, request_model
from token_budget import SharedTokenBudget, reservation_bound


def normalize_provider_response(value):
    """vLLM uses reasoning; preserve it while supplying the runtime wire alias."""
    normalized = deepcopy(value)
    changes = []
    choices = normalized.get('choices')
    if not isinstance(choices, list):
        return normalized, changes
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get('message')
        if isinstance(message, dict) and 'reasoning_content' not in message and isinstance(message.get('reasoning'), str):
            message['reasoning_content'] = message['reasoning']
            changes.append({'choice': index, 'from': 'reasoning', 'to': 'reasoning_content'})
    return normalized, changes


def call_model(config, payload):
    if config.get('token_budget_pointer'):
        return request_model(config, payload)
    payload = generation_request(payload, config)
    key = load_api_key(config)
    redact = lambda text: text.replace(key, '[REDACTED]') if key else text
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer '+key
    request = urllib.request.Request(config['base_url'].rstrip('/')+'/chat/completions',
                                     data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if config.get('bypass_proxy', True) else urllib.request.build_opener()
    result = {'request': deepcopy(payload), 'cache_hit': False}
    started = time.monotonic()
    try:
        with opener.open(request, timeout=config.get('request_timeout_seconds', 600)) as response:
            result['http_status'] = response.status
            raw = redact(response.read().decode('utf-8', errors='replace'))
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError('API envelope must be an object')
                normalized, changes = normalize_provider_response(value)
                result['response'] = normalized
                if changes:
                    result['provider_response'] = value
                    result['response_normalization'] = changes
            except ValueError as error:
                result.update(error_type='response_envelope', error=str(error), response_body=raw)
    except urllib.error.HTTPError as error:
        result.update(error_type='http', http_status=error.code, error=redact(str(error)),
                      response_body=redact(error.read().decode('utf-8', errors='replace')))
    except (OSError, urllib.error.URLError) as error:
        result.update(error_type='transport', error=redact(type(error).__name__+': '+str(error)))
    result['elapsed_seconds'] = round(time.monotonic()-started, 3)
    return result


class ExecutionJournal(Cooldown, ContextStudyJournal):
    def persist_request(self, attempt, payload):
        super().persist_request(attempt, payload)
        if self.role == 'researcher':
            from .convergence import account_request
            account_request(self.ws, attempt)
            if getattr(self,'_planning_closeout_admitted',False):
                from .workflow import stage_number
                with self.ws.db:
                    self.ws.db.execute('INSERT OR IGNORE INTO release_closeout_turns VALUES (?,?)',(attempt,stage_number(self.ws)))
                    self.ws.db.execute('INSERT OR IGNORE INTO release_closeout_scopes VALUES (?,?)',(attempt,self._planning_closeout_scope))
    """All roles share finite local execution caps; no mandatory billing setup."""
    def __init__(self, workspace, model, budget, role, *, memory, guard):
        Journal.__init__(self, workspace, model)
        self.study, self.role, self.memory, self.guard = budget, role, memory, guard

    def snapshot(self):
        local = self.study.snapshot()
        remaining = local['remaining_tokens']
        status = 'halted' if local['halted'] else 'open'
        if self.config.get('token_budget_pointer'):
            shared = SharedTokenBudget(self.config['token_budget_pointer']).snapshot()
            remaining = min(remaining, shared['remaining_admission_tokens'])
            status = shared['status'] if status == 'open' else status
        return {'status': status, 'remaining_admission_tokens': remaining, 'study_usage': local}

    def call(self, payload):
        from .transport_recovery import cooldown
        cooldown(self)
        paid = self.state.get('inflight') or self.state.get('delivery')
        if paid:
            from experiments.insight_research.runtime_memory import reconstruct_request
            payload = reconstruct_request(self.ws.private, paid['attempt'])
        else:
            allocation = getattr(self.ws, 'review_allocation', None)
            if allocation:
                from .review_drafts import ReviewDrafts
                maximum = allocation['maximum_requests']
                if self.state['attempts'] >= maximum:
                    raise Pending('review_execution_blocked: local review allocation exhausted; draft, costs and unverified scope retained. Continue independent work or explicitly allocate another slice within original authorization.')
            packet=getattr(self.ws,'packet',{}); candidate=packet.get('candidate_record',{})
            findings=candidate.get('assessment_refs',[])
            publication=(bool(allocation) and candidate.get('record_type')=='report_draft' and bool(findings)
                         and all(self.guard.owner.clearance(ref) for ref in findings))
            if allocation and candidate.get('record_type')=='report_draft' and not findings:
                from .convergence import active_refs
                publication=(not active_refs(self.guard.owner) and
                             {h['ref'] for h in self.guard.owner.records('hypothesis')}<=set(candidate.get('other_hypotheses',{})))
            # A bounded independent verification slice is useful work even
            # when it reproduces exactly the original numerical data.
            verification=(bool(allocation) and candidate.get('record_type')!='report_draft'
                          and packet.get('release_review_contract',{}).get('ready',False))
            planning=False
            bounded_goal=False
            if self.role=='researcher' and self.ws.records('hypothesis'):
                from .convergence import active_refs,focus,usage,policy
                from .workflow import stage_number
                from .verification_tasks import unpublished_findings,pending_disclosures,closeout_scope
                self._planning_closeout_scope=closeout_scope(self.ws)
                used=self.ws.db.execute('SELECT count(*) FROM release_closeout_scopes WHERE scope=?',(self._planning_closeout_scope,)).fetchone()[0]
                planning=(not active_refs(self.ws) and used<4 and bool(unpublished_findings(self.ws) or pending_disclosures(self.ws)))
                selected=focus(self.ws)
                if selected:
                    limits=policy(self.ws)
                    bounded_goal=usage(self.ws,selected['hypothesis_ref'])['requests']<limits['hypothesis_requests']+limits['closeout_requests']
            self._planning_closeout_admitted=(planning and self.guard.inspect()['effective_requests_without_progress']>=self.guard.stop)
            state = self.guard.admit(self.config.get('request_timeout_seconds', 600),workflow_closeout=publication or verification or planning,bounded_goal=bounded_goal)
            left = self.study.snapshot()['remaining_http_attempts']
            if left <= 8 or state['requests_without_structural_progress'] >= self.guard.warn:
                payload = {**payload, 'messages': [*payload['messages'], {'role': 'user', 'content':
                    f'Execution notice: {left} shared requests remain. Save actual evidence and revisions, or deliver an honest unresolved stage. Reuse unchanged work; necessary checks remain available.'}]}
            if len(encoded(payload).encode()) > self.ws.settings['limits']['max_request_bytes']:
                raise Pending('request including execution notice exceeds context bound')
        if paid and digest(payload) != paid['request_hash']:
            raise Pending('durable role request identity mismatch')
        if self.state.get('delivery'):
            item = self.state['delivery']
            return json.loads((self.ws.private/'http'/f"{item['attempt']}.json").read_text())
        item = self.state.get('inflight')
        if item:
            receipt = self.ws.private/'http'/f"{item['attempt']}.json"
            if not receipt.exists():
                # No scientific action is inferred from an absent response.
                # Preserve the reservation. Local deployments may pay again;
                # experiment-ledger recovery remains explicit and conservative.
                if self.config.get('token_budget_pointer'):
                    raise Pending('interrupted external-ledger request has no durable response; inspect its reservation before retry')
                from experiments.insight_research.common import write_json
                write_json(receipt, {'error_type': 'transport', 'error': 'Process interrupted before durable response; usage unknown, reservation retained.'})
            record = json.loads(receipt.read_text())
        else:
            snap = self.snapshot()
            if self.state['attempts'] >= self.ws.settings['limits']['max_http_attempts']:
                raise Pending('registered role request cap reached')
            if snap['status'] != 'open' or reservation_bound(payload) > snap['remaining_admission_tokens']:
                raise Pending('shared execution admission does not fit; no request sent')
            attempt = self.state['attempts']+1
            key = digest([self.role, attempt])
            self.study.reserve(key, self.role, payload)
            item = {'attempt': attempt, 'study_key': key, 'request_hash': digest(payload),
                    'reservation': reservation_bound(payload)}
            self.state['attempts'] = attempt; self.state['inflight'] = item; self.save()
            self.persist_request(attempt, payload)
            record = call_model(self.config, payload)
            self.persist_response(attempt, record)
        cost = self.study.settle(item['study_key'], item['request_hash'], (record.get('response') or {}).get('usage'))
        self.state['accounted_tokens'] += cost
        self.state['inflight'] = None; self.state['delivery'] = item; self.save()
        return record
