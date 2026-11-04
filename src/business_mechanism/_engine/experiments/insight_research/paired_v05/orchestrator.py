from ..paired_v04.orchestrator import ResearchRun as PreviousRun,ResearchRuntime as PreviousRuntime


class ResearchRuntime(PreviousRuntime):
    def constrained(self,payload):return payload

    def prepare_payload(self,payload):
        payload=super().prepare_payload(payload)
        self.ws.closeout_mode=False
        if self.cp.get('resource_closeout'):
            payload['messages'].append({'role':'user','content':
                '当前版本的低资源标记仅提示先保存工作，全部原研究工具仍按原权限开放，token/HTTP硬上限不变。'
                '可以保存实际形成的假说，注册/运行合法检验，也可以只保存带来源的当前认识。'
                '若尚无H/P/R，先用空的相关引用保存检查点，或实际创建记录；不要用口头编号代替工具返回ref。'
                '上下文压缩仍须保存已有认识，不丢弃尚未解释的付费工作；不要重复无新信息的分析。'})
        return payload


class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)
