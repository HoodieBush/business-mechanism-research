from ..paired_v06.review import Reviewer as OldReviewer,ReviewerRuntime as PreviousRuntime
from ..critic_v01.workspace import CriticWorkspace
from .references import NormalizedCalls,recover_auditable_response
from .review_policy import validate_review

class Reviewer(NormalizedCalls,OldReviewer):
    def dispatch(self,name,args,key):
        if name=='record_review':
            versions=validate_review(args,self.view.record,self.references,self.action)
            return CriticWorkspace.dispatch(self,name,{**args,'affected_versions':versions},key)
        return super().dispatch(name,args,key)

class ReviewerRuntime(PreviousRuntime):
    def run(self,max_model_steps=18):
        recover_auditable_response(self,'record_review')
        return super().run(max_model_steps)
