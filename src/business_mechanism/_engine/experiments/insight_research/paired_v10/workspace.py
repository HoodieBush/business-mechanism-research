from copy import deepcopy
from pathlib import Path
from ..common import encoded,sha
from ..paired_v08.workspace import ResearchWorkspace as Previous
from .contracts import TOOLS,schemas

class ResearchWorkspace(Previous):
    tools=TOOLS
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings)
        self.review_limit=settings.get('execution_policy',{}).get('review_http_limit',18)
        if type(self.review_limit)is not int or not 1<=self.review_limit<=18:raise ValueError('registered review_http_limit must be1..18')
        settings['paired_v10_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)

    def tool_schemas(self):return schemas(TOOLS)

    def job(self,ref):
        job=super().job(ref);job['review_http_limit']=self.review_limit;return job

    def _checked_dispatch(self,name,args,key):
        if name=='respond_to_review':
            # respond() checks actual Q/issue/evidence and keeps normal lifecycle
            # and recheck behavior. No new S or invented understanding is added.
            return self.respond(args,(self.state() or {}).get('ref'))
        if name in ('finish_research','review_claim') and self.unanswered():
            raise ValueError(encoded({'error':'review opinions need explicit evidence-linked responses first','unanswered':self.unanswered(),
                'repair':'Use respond_to_review(review_ref,issue_id,disposition,rationale,evidence_refs,replacement_refs), or update_research_state.review_responses. A response is not automatic repair or scientific certification.'}))
        if name=='record_assessment':
            for ref in args['result_refs']:
                try:self.record(ref,'result')
                except ValueError as error:
                    raise ValueError(encoded({'error':str(error),'invalid_ref':ref,'field':'result_refs',
                        'expected_kind':'result','repair':'Use formal R refs testing this exact original H in result_refs. Read the schema and original receipt; do not replace an R with a file/action/opinion. Auxiliary evidence must be explicitly typed; no automatic promotion.'})) from error
        return super()._checked_dispatch(name,args,key)

    def context(self):
        context=super().context();cap=self.workflow.get('max_lineage_reviews',4)
        context['review_policy']=f'Each review allows{self.review_limit}modelrequests; at most{cap}reviews per explicit lineage,within shared budget and persisted wall/progress guards. Every changed object needs its own review; no automatic scientific clearance.'
        context['verification_submission']='self: review_claim; independent: attributed peer feedback. Either mode: respond_to_review saves one evidence-linked response without rewriting research state; update_research_state remains available.'
        context['feedback_workflow']='Respond to every delivered issue using respond_to_review or update_research_state.review_responses. You choose research direction. A response records a disposition, not scientific truth; defer preserves an unresolved issue.'
        return context
