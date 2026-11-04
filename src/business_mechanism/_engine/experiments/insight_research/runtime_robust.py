"""Same researcher, generous context and a separate exact-repeat guard."""
import json
from .common import Pending, digest, encoded, write_json
from .runtime_memory import MemoryRuntime

ROBUST_PROMPT='''
本配置提供结构化事实核对及记忆复核，不增加研究角色。可以同时推进多个假说；一条关系得到支持不代表已找全机制。
供给检验有定量预测时，在save_hypothesis.effect_prediction预先声明目标商品、柜点范围、方向和最小效应（默认0）。register_test的主outcome_product_ids应与之相同；对照商品放outcome_groups。结果statistics.primary/secondary包含实际估计对象、单位、置信水平和区间；calendar区分日历窗口与实际营业日期。检查原条件和竞争解释，程序的兼容性判读不是整个因果机制的认证。
写入数值记忆时使用measurements绑定实际source_ref、estimate_key和field，value可省略以取精确计算值；验证成功的绑定来源会自动补入该条evidence_refs，不必重复填写。历史维度使用observed_facts.json的file引用；任意SQL/Python输出可作为evidence_refs引用，但不是提供primary/secondary的结构化统计回执。自由文本解释尚未被数值程序认证。不要由首末day编号推营业天数。
发现记忆或旧判断错误时，update_research_state.memory_reviews登记target_ref、quarantine/withdraw/restore、reason和证据；supersedes_ref创建正确替代版。复核中的条目和explicit_dependency_reviews不是可直接使用的事实。旧引用读取会显示有效状态与替代入口；原件保留。用evidence_refs表示事实前提，used_memory_refs只追踪如何启发问题/方法，不能当成真值依赖。假说是被检验对象，否定它不会自动使真实反证失效；事实证据、结果或方法自身被撤回才沿相应依赖传播。已有条目可在同一次状态更新中先restore复核再用作evidence_refs；其他明确依赖的下游认识需逐项复核。
相同输入/结果反复出现会有loop_notice；说明此次复核的具体疑点或改变实际分析。已读资料可按精确引用复查，不要为了更新状态而搜索空结果。不要为了花尽预算继续，也不要把循环/容量停止当科学反证。
run_test默认返回实际统计、输出预览与附件引用，完整执行/协议保留在full_record入口。研究状态与可选记忆逐条验收：合法状态可以保存，knowledge_rejections列出的条目没有写入，不能当已获得的记忆；按错误单独修复这些条目。状态保存不是科学判断或记忆认证。
'''


class RobustRuntime(MemoryRuntime):
    def initial(self):
        messages=super().initial(); messages[0]['content']+=ROBUST_PROMPT
        return messages

    def prepare_payload(self,payload):
        row=self.ws.db.execute('SELECT blocked FROM loop_counter WHERE id=1').fetchone()
        if row and row[0]>=2: raise Pending('unchanged repeated action remained blocked twice; branch and full evidence retained for review')
        return super().prepare_payload(payload)
