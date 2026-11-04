from copy import deepcopy
from pathlib import Path
from ..common import sha
from ..paired_v08.review import Reviewer as Previous
from ..paired_v09.review import ReviewerRuntime as PreviousRuntime
from .contracts import REVIEW_TOOLS,schemas
from .statistic import inspect

class Reviewer(Previous):
    tools=REVIEW_TOOLS
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v11_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)
    def tool_schemas(self):return schemas(REVIEW_TOOLS)
    def dispatch(self,name,args,key):
        if name=='inspect_evidence':return inspect(self,args,key,lambda data,op:super(Reviewer,self).dispatch('run_python',data,op))
        return super().dispatch(name,args,key)

class ReviewerRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial();messages[0]['content']+='\ninspect_evidence在原沙箱复算已见资料并返回范围与自由度。区分首个观测小时/真实开柜、处理/对照/全体、6点位/8点位区间。不显著不等于无效应，无法拒绝相等不等于等效。报告可能明确暂缓未启动判断、隔离其当前资格；核验实际发表的主张与未决披露，不要求所有探索都得到正面裁决。'
        return messages
