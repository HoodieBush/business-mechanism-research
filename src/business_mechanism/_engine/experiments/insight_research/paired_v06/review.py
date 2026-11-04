from ..paired_v02.review import Reviewer as Previous,ReviewerRuntime as PreviousRuntime
from .references import NormalizedCalls,recover_paid_submission

class Reviewer(NormalizedCalls,Previous):
    pass

class ReviewerRuntime(PreviousRuntime):
    def run(self,max_model_steps=6):
        recover_paid_submission(self,'record_review')
        return super().run(max_model_steps)
