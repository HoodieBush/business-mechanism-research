"""Keep native examples, align the role's reuse instructions with the contract."""
from experiments.insight_research.langgraph_release_v02.prompts import compose as previous


def compose(role):
    text=previous(role)
    if role=='critic':
        text=text.replace('| checks_performed[].action_ref | 本任务工具回执返回的check:核验动作 | 研究者action:、科学记录、文件 |',
            '| checks_performed[].action_ref | 本轮check:，或当前定向父审查已列明且输入版本核对通过的C核验动作 | 研究者action:、未知/撤回/输入改变的动作 |')
        text=text.replace('| issues[].action_refs | 你本任务实际执行的check:动作 | 研究者action:编号 |',
            '| issues[].action_refs | 本轮check:；复用父审查的计算时明确引用该C动作并声明复用 | 研究者action:、未收到或不适用的旧动作 |')
        text+='\n\n定向再核验可复用父审查已列明的实际工具结果。C引用明确指向过去的归属动作，不是你本轮重算；finding中说明来源、未变输入与适用范围，basis=recomputed表示有工具计算证据，程序另外记录本轮新执行还是过去计算复用。公开输入变化、原件缺失或动作撤回时不能复用，需重算或明确未查。不要把同一个计算结果复用称为新的独立验证。checks_performed的动作编号是证据输出的主索引，程序可从该真实动作补全直接返回的文件编号；不要猜编号，不把未知编号当有效。数值、意见、适用范围和未决问题仍由你依据证据填写。\n'
    return text
