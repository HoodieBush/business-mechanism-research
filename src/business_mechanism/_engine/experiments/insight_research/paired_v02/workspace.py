"""Separate verification submission from checkpoint bookkeeping."""
from copy import deepcopy
from pathlib import Path
from ..common import encoded,sha
from ..paired_v01.workspace import ResearchWorkspace as Previous
from ..paired_v01.contracts import TOOLS as PREVIOUS_TOOLS, SelfReview, schemas
from .review import reference_error

TOOLS={**PREVIOUS_TOOLS,'review_claim':(SelfReview,
    'self模式：直接提交一个待审job的结构化核验，不必重填研究状态。independent模式不能用它代替质疑者。')}


class ResearchWorkspace(Previous):
    tools=TOOLS
    def tool_schemas(self):return schemas(TOOLS)

    def __init__(self,*args,**kwargs):
        # settings is positional in the established constructor.
        args=list(args);settings=deepcopy(args[3] if len(args)>3 else kwargs['settings'])
        settings['paired_v02_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        if len(args)>3:args[3]=settings
        else:kwargs['settings']=settings
        super().__init__(*args,**kwargs)

    def _checked_dispatch(self,name,args,key):
        if name=='review_claim':
            if self.settings['verification_mode']!='self':
                raise ValueError('independent mode cannot waive peer review with a self report')
            return self.apply_review(args['job_ref'],args['review'],author='researcher_self_check')
        return super()._checked_dispatch(name,args,key)

    def references(self,refs):
        for ref in refs:
            try:super().references([ref])
            except ValueError as error:
                raise ValueError(reference_error(ref,error,(self.db,))) from error

    def context(self):
        ctx=super().context()
        ctx['verification_submission']='self: review_claim(job_ref,review) saves verification only; use update_research_state separately for understanding/memory. independent: wait for attributed feedback then respond with evidence.'
        if self.jobs_ready and self.settings['verification_mode']=='self' and self.jobs('pending'):
            ctx['current_verification_action']='Review the current queued object before spending its bounded review slice on unrelated work. Full sources and all recomputation tools remain available; after review continue choosing research directions.'
        return ctx
