from pathlib import Path
from copy import deepcopy
from ..common import Pending,sha
from ..paired_v11.review import Reviewer as PreviousReviewer,ReviewerRuntime as PreviousRuntime
from .journal_memory import own_context,read_own_memory,rebuild_from_owned_journal,PREFIXES

class Reviewer(PreviousReviewer):
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v12_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)
    def context(self):return {**super().context(),'own_journal_memory':own_context(self)}
    def dispatch(self,name,args,key):
        if name in ('read_memory','read_artifact') and args['ref'].startswith(PREFIXES):return read_own_memory(self,**args)
        return super().dispatch(name,args,key)

class ReviewerRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial();messages[0]['content']+='\n上下文若已从自己的完整档案重建，own_journal_memory提供精确归档及own_log/own_process入口。它不是自动科学总结；先结合原假说、结果、审查和近期完整回合恢复当前问题，必要时分页回读自己档案。日志/私人推理不能当事实证据，不必重做已完成计算。'
        return messages
    def compact(self):
        try:return super().compact()
        except Pending:return rebuild_from_owned_journal(self)
