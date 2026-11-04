"""Latched, evidence-neutral resource closeout, before unsafe admission."""
from .closeout import CLOSEOUT_TOOLS
from .common import Pending
from .runtime_continuation import ContinuationRuntime
from .runtime_memory import MemoryJournal
from token_budget import reservation_bound

NOTICE = ('资源收尾保护已开启：继续读取/计算可能挤占保存和交付所需额度。本批次暂时只开放'
          'record_assessment、update_research_state、finish_research，原12工具的实现不变。'
          '先保存当前认识、疑点、原预测覆盖和需要的后续证据；证据不足可诚实未决，不要求编造判断或得到支持。'
          '不要把尚未理解的结果写成已验证认识。保存和正式判断是不同动作。')


class CloseoutRuntime(ContinuationRuntime):
    def __init__(self, workspace, model_config, *, journal=None):
        super().__init__(workspace, model_config, journal=journal)
        workspace.closeout_mode = bool(self.cp.get('resource_closeout'))

    def initial(self):
        messages = super().initial()
        messages[0]['content'] += ('\n完整研究上下文在每次请求的第二条消息自动刷新。read_context仅确认版本和入口，'
            '不再把相同完整内容重复返回。资源收尾保护只限制可选动作，不规定科学结论；'
            '可记录缺证据、未理解事项和下批次问题。\n')
        return messages

    def remaining(self):
        if not isinstance(self.journal, MemoryJournal): return None
        return min(self.journal.snapshot()['remaining_admission_tokens'],
            self.ws.settings['limits']['token_allowance'] - self.journal.state['accounted_tokens'])

    def constrained(self, payload):
        if self.cp.get('resource_closeout'):
            payload['tools'] = [t for t in payload['tools'] if t['function']['name'] in CLOSEOUT_TOOLS]
            if not any(m.get('content') == NOTICE for m in payload['messages']):
                payload['messages'].append({'role': 'user', 'content': NOTICE})
        return payload

    def payload(self, messages=None):
        return self.constrained(super().payload(messages))

    def prepare_payload(self, payload):
        remaining = self.remaining()
        if remaining is not None and remaining < 3 * reservation_bound(payload):
            # The fixed multiplier is a conservative transition rule, not a
            # proof of future cost or successful scientific closure.
            self.cp['resource_closeout'] = True
            self.ws.closeout_mode = True
            self.save()
        payload = self.constrained(payload)
        try:
            return self.constrained(super().prepare_payload(payload))
        except Pending as error:
            if remaining is not None and reservation_bound(payload) > remaining and 'saved interpretation' in str(error):
                raise Pending('token admission cannot fit the complete unsaved research suffix; original messages retained. This is not the model context limit.') from error
            raise

    def drain(self, deadline=None):
        self.ws.closeout_mode = bool(self.cp.get('resource_closeout'))
        return super().drain(deadline)
