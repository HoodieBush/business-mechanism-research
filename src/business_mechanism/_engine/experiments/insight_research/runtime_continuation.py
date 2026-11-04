"""Bounded existing-evidence phase, with the same researcher and twelve tools."""
from .common import encoded
from .runtime_robust import RobustRuntime
from .runtime_memory import MemoryJournal
from token_budget import reservation_bound

CONTINUATION_PROMPT = '''
这是同一研究的续接收尾阶段，不是新发现起点。原始问题、假说/预测、实际结果、记忆与原过程已继承；旧state可能早于新结果，先检查unincorporated_results及原预测。它们是否支持原主张、只覆盖部分条件还是仍未决，需你根据原件判断；不要求得到正结果。
本阶段只使用已收到的证据，允许必要的读取和复算，不启动新供给试验。优先对已有结果登记有范围判断，吸收结果、保存认识/修订有问题的记忆，再用finish_research披露全部分支状态及下一研究问题。无检验的假说可以明确保留未检验；新假说应来自实际证据，不要求再做一轮探索。
台账回执reconciliation_totals区分异常行数、记录件数、库存隐含出库件数和两者差额。数值记忆可绑定实际R引用的mismatched_rows/recorded_total/verified_total/difference_units，value省略即可；这些是同源记录核对，未新增实物测量。
旧原件不覆盖。用原引用回读；附件视图给当前合法路径，原过程中的绝对路径是历史位置。carryover:index是上次状态后的工作导航，不是模型总结或审查答案。新的批次计费从0开始，父批次费用已记在同一总账，先前试验次数继续占用。
不要将阶段报告写出等同科学通过；先核对数值、对象、范围、条件、竞争解释和证据性质。完成必要工作就交付，不为花尽余量继续。
'''


class ContinuationRuntime(RobustRuntime):
    def initial(self):
        messages = super().initial(); messages[0]['content'] += CONTINUATION_PROMPT
        return messages

    def prepare_payload(self, payload):
        payload = super().prepare_payload(payload)
        if isinstance(self.journal, MemoryJournal):
            remaining = min(self.journal.snapshot()['remaining_admission_tokens'],
                self.ws.settings['limits']['token_allowance'] - self.journal.state['accounted_tokens'])
            closeout = remaining < 3 * reservation_bound(payload)
            if closeout or self.ws.unincorporated():
                payload['messages'].append({'role': 'user', 'content':
                    '已有结果待处理或资源需要预留收尾。请优先依据原预测登记判断、保存结果吸收与当前认识，然后完成阶段交付；必要复算请对应一个明确的未决问题。诚实未决可交付。'})
        return payload
