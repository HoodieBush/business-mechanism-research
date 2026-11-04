from ..paired_v06.workspace import ResearchWorkspace as OldWorkspace
from ..paired_v07.workspace import ResearchWorkspace as CandidateWorkspace
from .references import NormalizedCalls
from .review_policy import ReviewPolicy

class ReviewCapacity:
    def job(self,ref):
        job=super().job(ref);job['review_http_limit']=18;return job

class BaselineWorkspace(ReviewPolicy,ReviewCapacity,NormalizedCalls,OldWorkspace):
    pass

class ResearchWorkspace(ReviewPolicy,ReviewCapacity,NormalizedCalls,CandidateWorkspace):
    pass
