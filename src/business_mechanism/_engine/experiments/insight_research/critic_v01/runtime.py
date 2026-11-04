"""Reuse the existing paid-response/tool recovery loop with a critic prompt."""
from pathlib import Path
from ..common import Pending, encoded
from ..runtime import Journal, Runtime
from token_budget import SharedTokenBudget
from token_budget import reservation_bound

PROMPT = (Path(__file__).parent / 'prompt.txt').read_text()


class CriticRuntime(Runtime):
    def __init__(self, workspace, model_config, *, journal=None):
        if journal is None:
            pointer = model_config.get('token_budget_pointer')
            if not pointer or SharedTokenBudget(pointer).auth['id'] != 'USER-20261022-CRITIC-10M':
                raise ValueError('M0 paid critic requires its explicit project budget pointer')
        super().__init__(workspace, model_config, journal=journal)

    def initial(self):
        return [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': encoded(self.ws.context())}]

    def accept(self, raw, delivery=None):
        # The inherited parser already rejects malformed/truncated batches.
        # Additionally, don't let a checkpoint/final review share a paid batch
        # with actions that would run after completion or escape its coverage.
        try:
            calls = raw['choices'][0]['message'].get('tool_calls') or []
            if len(calls) > 1 and any(c.get('function', {}).get('name') == 'record_review' for c in calls):
                # Retain the original response in the same raw archive. An
                # invalid finish reason makes the existing parser execute zero.
                from copy import deepcopy
                invalid = deepcopy(raw)
                invalid['choices'][0]['finish_reason'] = 'mixed_review_batch'
                super().accept(invalid, delivery)
                from ..common import write_json
                write_json(self.ws.private / 'turns' / (str(self.cp['responses']) + '.json'), raw)
                self.cp['messages'].append({'role': 'user', 'content': 'record_review必须单独调用；本批次0工具执行，原始响应已保存。'})
                self.save(); return
        except (KeyError, TypeError, IndexError, AttributeError): pass
        result = super().accept(raw, delivery)
        if (not self.cp['pending'] and self.cp['messages']
                and 'finish_research登记阶段交付' in self.cp['messages'][-1].get('content', '')):
            self.cp['messages'][-1]['content'] = '请继续用核验工具推进，或用record_review保存checkpoint/complete；普通文本不结束审查。'
            self.save()
        return result

    def context_notice(self):
        return '容量接近保护边界：先用record_review保存checkpoint，列出已做核验、正反证引用、未解决项和下一步。'

    def prepare_payload(self, payload):
        if isinstance(self.journal, Journal):
            attempts_left = self.ws.settings['limits']['max_http_attempts'] - self.journal.state['attempts']
            if attempts_left <= 2:
                payload['messages'].append({'role': 'user', 'content':
                    f'本次累计HTTP额度还剩{max(0, attempts_left)}次请求，包含接下来的这次。请优先用record_review保存已有核验和未查范围（complete或checkpoint）；不要求凑结论，必要回读与复算仍可用，不要重复已完成检查。'})
            remaining = min(self.journal.snapshot()['remaining_admission_tokens'],
                self.ws.settings['limits']['token_allowance'] - self.journal.state['accounted_tokens'])
            if reservation_bound(payload) > remaining:
                try: self.compact()
                except Pending as error:
                    raise Pending('token admission cannot fit complete unsaved critic work; preserve checkpoint/suffix. This is not scientific refutation or a model context-limit finding.') from error
                payload = self.payload()
        return payload

    def run(self, max_model_steps=6):
        result = super().run(max_model_steps)
        if (result['status'] == 'pending' and isinstance(self.journal, Journal)
                and self.journal.state['attempts'] >= self.ws.settings['limits']['max_http_attempts']):
            return self.pause('registered cumulative critic HTTP allocation reached; preserve paid work. More requests require a new explicit continuation allocation, not a counter reset; this is not scientific refutation.')
        return result

    def compact(self):
        if self.cp['pending']: raise Pending('drain already paid critic actions before context rebuild')
        # A saved review checkpoint is required to discard any substantive
        # work. Keep its exact raw assistant turn and all subsequent work.
        state = self.ws.state()
        if not state: raise Pending('critic context needs a saved review checkpoint; original messages retained')
        messages = self.cp['messages']
        for i in range(len(messages)-1, 1, -1):
            if messages[i]['role'] != 'tool': continue
            import json
            try: result = json.loads(messages[i]['content'])
            except (ValueError, TypeError): continue
            if result.get('ref') != state['ref']: continue
            start = next((j for j in range(i-1, 1, -1) if messages[j]['role'] == 'assistant'), None)
            if start is None: break
            rebuilt = self.initial() + messages[start:]
            if len(encoded(self.payload(rebuilt)).encode()) <= self.ws.settings['limits']['max_request_bytes']:
                self.cp['messages'] = rebuilt; self.cp['context_windows'] += 1; self.save(); return
        raise Pending('complete critic checkpoint suffix does not fit; retain original work and pause')
