"""Generic missing-reference feedback; never turn a hash into accepted evidence."""
from copy import deepcopy
from pathlib import Path
from ..common import encoded,sha
from ..paired_v01.review import Reviewer as PreviousReviewer,ReviewerRuntime as PreviousRuntime


def reference_error(ref,error,databases):
    matches=[]
    if ref.startswith('file:'):
        for db in databases:
            matches.extend({'ref':r,'path':p,'sha256':h} for r,p,h in db.execute(
                'SELECT ref,path,hash FROM files WHERE hash=?',(ref[5:],)))
    return encoded({'error':str(error),'invalid_ref':ref,'matching_received_versions':matches,
        'repair':'Cite an exact returned ref. sha256 identifies a version, not a file reference. Read/search the original receipt if no exact version match is available.'})


class Reviewer(PreviousReviewer):
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings)
        settings['paired_v02_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)

    def references(self,refs):
        for ref in refs:
            try:super().references([ref])
            except ValueError as error:
                raise ValueError(reference_error(ref,error,(self.db,self.view.db))) from error

    def context(self):
        ctx=super().context()
        if hasattr(self,'study_budget'):ctx['common_study_usage']=self.study_budget.snapshot()
        return ctx


class ReviewerRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial()
        messages[0]['content']+='\n引用必须使用工具返回的ref字段。sha256是文件版本，不是引用；提交失败时根据invalid_ref和matching_received_versions修正后再提交，不重做已经完成的科学计算。\n'
        return messages
