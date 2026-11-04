from copy import deepcopy
from pathlib import Path
from ..common import sha
from ..paired_v02.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings)
        settings['paired_v03_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)

    def job(self,ref):
        job=super().job(ref)
        job['review_http_limit']=18 if job['round']==1 else 6
        return job

    def context(self):
        ctx=super().context()
        if self.settings.get('continuation_binding'):
            ctx['execution_continuation']={**self.settings['continuation_binding'],
                'same_research':True,'cumulative_usage_retained':True,
                'path_policy':'Original receipts retain historical paths. Read exact refs for current compute_path; use the current workspace, not the old parent paths.'}
        return ctx
