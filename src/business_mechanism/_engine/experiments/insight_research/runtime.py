"""One explicit model/tool loop; paid responses drain before any new request.

No framework supervisor, role chain or implicit completion by plain model text.
Raw wire messages (including reasoning_content) remain in private process logs.
"""
from __future__ import annotations
from copy import deepcopy
import fcntl
import json
import time
from pathlib import Path
from pydantic import ValidationError
from .common import Pending, digest, encoded, now, write_json
from .contracts import TOOLS, schemas
from model_protocol import generation_request, request_model
from token_budget import SharedTokenBudget, TokenBudgetStop, reservation_bound, reported_total

PROMPT = '''你是唯一研究者，负责围绕原业务问题持续研究，获得有范围、有实际数据支持、可复算的insight。自主选择读取、计算、竞争解释、假说和检验，依据结果修订认识。当前交付是研究认识及证据。
把原预测、检验计划、实际观测与解释分开保存。检验成功运行不等于科学结论正确；评估原预测范围、缺货截断、重复测量、选择偏差及竞争解释。当前已公开的历史不能称独立未见验证。工具只保证记录和实际执行，不认证推理。
收到正式结果或改变研究方向后更新research state，说明认识变化、反证、未决项及下一步理由。关键反证放入counterevidence_refs；未吸收结果持续保留。暂不研究的假说在inactive_hypotheses中说明具体理由，原预测和证据保留在档案，暂停不等于否证。修订创建新假说版本。不要因否证就转去写算法，可以继续研究或说明需要的新测量。阶段交付使用finish_research，披露全部假说状态。你可以交付诚实未决。
资料目录、精确字段和实验契约由read_context提供，原件可分页回读。SQL和Python直接可用；Python只写WORK_DIR，PUBLIC_DIR和ARTIFACT_DIR只读。自己的派生分析可直接继续用，但要保留来源和证据性质。原始过程仅通过自己的read_memory回读。
不存在其他专业角色、算法交付、利润排名或强制动作顺序。工具参数必须匹配提供的模式。finish_research必须独自调用。'''


class Journal:
    """Bounded local allowance on top of the unchanged shared transport ledger."""
    def __init__(self, workspace, config):
        self.ws, self.config = workspace, deepcopy(config)
        self.path = workspace.private / 'transport.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'attempts': 0, 'accounted_tokens': 0, 'inflight': None}

    def save(self): write_json(self.path, self.state)

    def persist_request(self, attempt, payload):
        write_json(self.ws.private / 'requests' / (str(attempt) + '.json'), payload)

    def persist_response(self, attempt, record):
        write_json(self.ws.private / 'http' / (str(attempt) + '.json'), record)

    def snapshot(self):
        budget = SharedTokenBudget(self.config['token_budget_pointer']) if self.config.get('token_budget_pointer') else SharedTokenBudget()
        return budget.snapshot()

    def call(self, payload):
        limits = self.ws.settings['limits']
        if self.state.get('delivery'):
            delivery = self.state['delivery']
            if digest(payload) != delivery['request_hash']:
                raise Pending('unacknowledged paid response has a different request; recover original delivery first')
            return json.loads((self.ws.private / 'http' / (str(delivery['attempt']) + '.json')).read_text())
        if self.state['inflight']:
            item = self.state['inflight']
            if digest(payload) != item['request_hash']: raise Pending('inflight request identity differs; inspect original request')
            receipt = self.ws.private / 'http' / (str(item['attempt']) + '.json')
            if not receipt.exists(): raise Pending('transport interrupted without durable response; usage remains reserved, inspect before retry')
            record = json.loads(receipt.read_text())
        else:
            bound = reservation_bound(payload)
            shared = self.snapshot()
            if self.state['attempts'] >= limits['max_http_attempts']: raise Pending('registered HTTP attempt cap reached')
            if bound + self.state['accounted_tokens'] > limits['token_allowance']: raise Pending('local conservative request admission does not fit')
            if shared['status'] != 'open' or bound > shared['remaining_admission_tokens']:
                raise Pending('shared conservative request admission does not fit; no request sent')
            self.state['attempts'] += 1
            item = {'attempt': self.state['attempts'], 'request_hash': digest(payload), 'reservation': bound}
            self.state['inflight'] = item; self.save()
            self.persist_request(item['attempt'], payload)
            record = request_model(self.config, payload)  # Existing credential + shared reserve/settle boundary.
            self.persist_response(item['attempt'], record)
        usage = reported_total(record.get('response', {}).get('usage'))
        self.state['accounted_tokens'] += item['reservation'] if usage is None else usage
        self.state['inflight'] = None
        self.state['delivery'] = item
        self.save()
        return record

    def ack(self):
        self.state['delivery'] = None; self.save()


class Runtime:
    def __init__(self, workspace, model_config, *, journal=None):
        self.ws, self.config = workspace, deepcopy(model_config)
        if workspace.settings['model_config'] != model_config:
            raise ValueError('model configuration differs from frozen study identity')
        limits = workspace.settings['limits']
        for key in ('token_allowance', 'max_http_attempts', 'max_transport_retries', 'round_wall_seconds', 'max_request_bytes', 'recent_turns'):
            if type(limits.get(key)) is not int or limits[key] < (0 if key in ('token_allowance', 'max_http_attempts', 'max_transport_retries', 'recent_turns') else 1):
                raise ValueError('explicit nonnegative registered resource bound required: ' + key)
        self.path = workspace.private / 'checkpoint.json'
        self.cp = json.loads(self.path.read_text()) if self.path.exists() else {
            'status': 'running', 'reason': None, 'messages': [], 'pending': None,
            'responses': 0, 'context_windows': 0, 'transport_failures': 0}
        self.journal = journal or Journal(workspace, self.config)

    def save(self): write_json(self.path, self.cp)

    def pause(self, reason):
        self.cp.update(status='pending', reason=reason); self.save()
        return {'status': 'pending', 'reason': reason, 'responses': self.cp['responses']}

    def initial(self):
        return [{'role': 'system', 'content': PROMPT},
                {'role': 'user', 'content': encoded(self.ws.context())}]

    def payload(self, messages=None):
        return generation_request({'model': self.config['model'], 'messages': deepcopy(messages if messages is not None else self.cp['messages']),
            'tools': self.ws.tool_schemas(), 'tool_choice': 'auto'}, self.config)

    def prepare_payload(self, payload):
        return payload

    def context_notice(self):
        return '上下文接近保护边界：请先更新带来源的研究状态并吸收未决检验结果，以便继续同一研究。'

    def compact(self):
        if self.cp['pending']: raise Pending('complete already-paid tool calls before changing context')
        if self.ws.records('hypothesis') and not self.ws.state():
            raise Pending('context boundary requires source-linked research state; unincorporated results remain pinned')
        messages = self.cp['messages']
        starts = [i for i, m in enumerate(messages) if m['role'] == 'assistant']
        keep = self.ws.settings['limits']['recent_turns']
        recent = messages[starts[-min(keep, len(starts))]:] if keep and starts else []
        rebuilt = self.initial() + recent
        # Drop whole optional turns only; fixed scientific fields are never sliced.
        while len(encoded(self.payload(rebuilt)).encode()) > self.ws.settings['limits']['max_request_bytes'] and recent:
            next_turn = next((i for i, m in enumerate(recent[1:], 1) if m['role'] == 'assistant'), len(recent))
            recent = recent[next_turn:]; rebuilt = self.initial() + recent
        if len(encoded(self.payload(rebuilt)).encode()) > self.ws.settings['limits']['max_request_bytes']:
            raise Pending('fixed research view exceeds capacity; explicitly narrow active scope while retaining counterevidence and archive refs')
        self.cp['messages'] = rebuilt; self.cp['context_windows'] += 1; self.save()

    def accept(self, raw, delivery=None):
        """Save raw response before decoding; never execute a truncated batch."""
        number = self.cp['responses'] + 1
        write_json(self.ws.private / 'turns' / (str(number) + '.json'), raw)
        if delivery is not None: self.cp['delivered_attempt'] = delivery
        try:
            choice = raw['choices'][0]
            original = choice['message']
            if not isinstance(original, dict): raise ValueError('assistant message must be an object')
        except (TypeError, KeyError, IndexError, ValueError) as error:
            self.cp['messages'].append({'role': 'user', 'content': encoded({'protocol_error': str(error),
                'executed_tools': 0, 'action': 'Return a valid assistant function-call message.'})})
            self.cp['responses'] = number; self.save(); return
        message = {'role': 'assistant', 'content': original.get('content') or ''}
        if 'reasoning_content' in original: message['reasoning_content'] = original['reasoning_content']
        calls = original.get('tool_calls') or []
        parsed = []
        try:
            if choice.get('finish_reason') == 'length': raise ValueError('truncated response; no returned tool will execute')
            if choice.get('finish_reason') not in ('stop', 'tool_calls'):
                raise ValueError('incomplete or unknown finish reason; no tools execute')
            if not isinstance(calls, list): raise ValueError('tool_calls must be an array')
            ids = [c.get('id') for c in calls]
            if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
                raise ValueError('tool calls require unique nonempty IDs')
            if len(calls) > 1 and any(c.get('function', {}).get('name') == 'finish_research' for c in calls):
                raise ValueError('finish_research must be the only call')
            for call in calls:
                name = call['function']['name']
                if call.get('type') != 'function' or name not in self.ws.tools: raise ValueError('unknown function tool')
                args = json.loads(call['function']['arguments'])
                args = self.ws.tools[name][0].model_validate(args).model_dump()
                parsed.append({'id': call['id'], 'name': name, 'args': args})
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError) as error:
            # Invalid original is retained in owner archive. A valid conversation
            # repair does not put duplicated/unacknowledgeable tool IDs on wire.
            self.cp['messages'].extend([message, {'role': 'user', 'content': encoded({
                'protocol_error': str(error), 'executed_tools': 0,
                'action': 'Resubmit complete valid tool calls; original response remains archived.'})}])
            self.cp['responses'] = number; self.save(); return
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['function']['name'], 'arguments': c['function']['arguments']}} for c in calls]
        self.cp['messages'].append(message)
        self.cp['responses'] = number
        self.cp['pending'] = {'response': number, 'calls': parsed, 'cursor': 0} if parsed else None
        if not parsed:
            self.cp['messages'].append({'role': 'user', 'content': '请继续用研究工具推进，或用finish_research登记阶段交付。普通文本不结束研究。'})
        self.save()

    def drain(self, deadline=None):
        pending = self.cp['pending']
        if not pending: return
        while pending['cursor'] < len(pending['calls']):
            if deadline is not None and time.monotonic() + 45 > deadline:
                raise Pending('round time cannot admit another tool; paid remainder retained')
            call = pending['calls'][pending['cursor']]
            op = digest([str(self.ws.root), pending['response'], call['id']])
            result = self.ws.call(call['name'], call['args'], op)
            self.cp['messages'].append({'role': 'tool', 'tool_call_id': call['id'], 'content': encoded(result)})
            pending['cursor'] += 1; self.save()
        self.cp['pending'] = None; self.save()

    def run(self, max_model_steps=8):
        lock = (self.ws.private / 'runtime.lock').open('a')
        try:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return {'status': 'pending', 'reason': 'study is owned by another runtime'}
            # Another runtime may have advanced after this object was constructed.
            if self.path.exists(): self.cp = json.loads(self.path.read_text())
            if isinstance(self.journal, Journal) and self.journal.path.exists():
                self.journal.state = json.loads(self.journal.path.read_text())
            if self.ws.report():
                self.cp.update(status='completed', reason=None); self.save()
                return {'status': 'completed', 'report': self.ws.report()['ref']}
            self.cp.update(status='running', reason=None); self.save()
            if isinstance(self.journal, Journal) and self.journal.state.get('delivery'):
                attempt = self.journal.state['delivery']['attempt']
                if self.cp.get('delivered_attempt') == attempt:
                    self.journal.ack()
                else:
                    raw_record = json.loads((self.ws.private / 'http' / (str(attempt) + '.json')).read_text())
                    if raw_record.get('response', {}).get('choices'):
                        self.accept(raw_record['response'], attempt)
                        self.journal.ack()
                    else:
                        raise Pending('unacknowledged transport error requires original request recovery')
            deadline = time.monotonic() + self.ws.settings['limits']['round_wall_seconds']
            if not self.cp['messages']: self.cp['messages'] = self.initial(); self.save()
            for _ in range(max_model_steps):
                self.drain(deadline)  # Drain first, even with no allowance for another request.
                if self.ws.report():
                    self.cp.update(status='completed', reason=None); self.save()
                    return {'status': 'completed', 'report': self.ws.report()['ref']}
                if time.monotonic() >= deadline: raise Pending('registered round wall limit reached')
                if self.cp['transport_failures'] > self.ws.settings['limits']['max_transport_retries']:
                    raise Pending('bounded transport retry allowance exhausted; do not resume by resetting retries')
                size = len(encoded(self.payload()).encode())
                maximum = self.ws.settings['limits']['max_request_bytes']
                if size > maximum: self.compact()
                # Source-linked fixed fields refresh on every request; complete recent
                # raw turns remain intact. User research question cannot be overwritten.
                self.cp['messages'][1] = self.initial()[1]
                payload = self.payload()
                size = len(encoded(payload).encode())
                if size > maximum:
                    self.compact(); payload = self.payload()
                elif size > maximum * .70:
                    notice = self.context_notice()
                    if notice:
                        payload['messages'].append({'role': 'user', 'content': notice})
                        if len(encoded(payload).encode()) > maximum: raise Pending('request guard including context notice exceeded')
                payload = self.prepare_payload(payload)
                # Leave enough wall time for the configured transport plus one tool.
                if time.monotonic() + self.config.get('request_timeout_seconds', 600) + 45 > deadline:
                    raise Pending('remaining round time cannot admit a model request plus tool feedback')
                record = self.journal.call(payload)
                delivery = self.journal.state.get('delivery', {}).get('attempt') if isinstance(self.journal, Journal) else None
                raw = record.get('response')
                if not raw or not raw.get('choices'):
                    self.cp['transport_failures'] += 1; self.save()
                    if isinstance(self.journal, Journal): self.journal.ack()
                    if self.cp['transport_failures'] > self.ws.settings['limits']['max_transport_retries']:
                        raise Pending('bounded transport retry allowance exhausted; attempt evidence retained')
                    continue
                self.cp['transport_failures'] = 0
                self.accept(raw, delivery)
                if isinstance(self.journal, Journal): self.journal.ack()
            self.drain(deadline)
            if self.ws.report():
                self.cp.update(status='completed', reason=None); self.save()
                return {'status': 'completed', 'report': self.ws.report()['ref']}
            return self.pause('registered model-step slice reached; study can resume')
        except (Pending, TokenBudgetStop) as error:
            return self.pause(str(error))
        finally:
            lock.close()
