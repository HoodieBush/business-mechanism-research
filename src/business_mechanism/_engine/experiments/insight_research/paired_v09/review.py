from ..paired_v08.review import Reviewer
from ..paired_v06.review import ReviewerRuntime as PreviousRuntime
from ..paired_v08.references import recover_auditable_response

class ReviewerRuntime(PreviousRuntime):
    def run(self,max_model_steps=18):
        if self.path.exists() and self.journal.path.exists():
            recover_auditable_response(self,'record_review')
        return super().run(max_model_steps)
