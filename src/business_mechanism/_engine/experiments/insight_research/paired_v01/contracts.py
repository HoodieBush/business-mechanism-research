"""Common self/independent review and evidence-linked researcher responses."""
from typing import Literal
from pydantic import Field
from .. import robust_contracts as research
from ..contracts import Input, FinishResearch as BaseFinish
from ..contracts_memory import SearchMemory as BaseSearch
from ..critic_v01.contracts import Issue as BaseIssue, RecordReview as BaseReview, TOOLS as CRITIC_TOOLS


class Issue(BaseIssue):
    affected_refs: list[str] = Field(min_length=1, description='Exact affected scientific records; may target an old K while the current A is correct.')
    basis: Literal['observed', 'recomputed', 'conjecture']
    blocking: bool = Field(default=True, description='Conjectures remain advisory; a reviewed object is not a proven premise.')


class Review(BaseReview):
    target_conclusion: Literal['consistent_in_checked_scope', 'changes_needed', 'insufficient_evidence']
    issues: list[Issue]
    prior_issue_updates: dict[str, Literal['resolved', 'retracted', 'still_open']] = Field(default_factory=dict,
        description='Directed recheck only: explicitly resolve/retract/retain each prior issue; omitted issues remain open.')


class SelfReview(Input):
    job_ref: str
    review: Review


class Response(Input):
    review_ref: str
    issue_id: str
    disposition: Literal['accept', 'revise', 'rebut', 'defer']
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    replacement_refs: list[str] = Field(default_factory=list)


class Assessment(research.base.base.RecordAssessment):
    supersedes_assessment_ref: str | None = None


class UpdateState(research.UpdateResearchState):
    pending_claim_refs: list[str] = Field(default_factory=list, description='Unreviewed/disputed claims tracked as objects, not factual premises; checkpoints may keep them here.')
    self_reviews: list[SelfReview] = Field(default_factory=list, max_length=1,
        description='self mode: review a pending job using the same packet and actual event: action refs. independent mode cannot waive peer review.')
    review_responses: list[Response] = Field(default_factory=list, max_length=6,
        description='Evidence-linked response; accept/revise requires actual withdrawal/replacement before closure. Rebut permits one directed recheck.')


class SearchMemory(BaseSearch):
    include_history: bool = Field(default=True, description='Include superseded/withdrawn/quarantined records with lifecycle warnings, not as current facts.')


class FinishResearch(BaseFinish):
    supersedes_draft_ref: str | None = None


TOOLS = dict(research.TOOLS)
for name, model in [('record_assessment', Assessment), ('update_research_state', UpdateState),
                    ('search_memory', SearchMemory), ('finish_research', FinishResearch)]:
    TOOLS[name] = (model, TOOLS[name][1])
TOOLS['record_assessment'] = (Assessment, '保存候选判断并排队核验，不自动成为当前强事实；修订用supersedes_assessment_ref保留原件。')
TOOLS['update_research_state'] = (UpdateState, '先保存认识和可选记忆；self_reviews完成自查，review_responses按意见编号响应/修订/反驳，不能靠回复本身消除错误。')
TOOLS['finish_research'] = (FinishResearch, '生成待核验报告草稿；有当前核验且引用有效时由程序封存，允许诚实未决。必须单独调用。')
REVIEW_TOOLS = dict(CRITIC_TOOLS)
REVIEW_TOOLS['record_review'] = (Review, '保存checkpoint或complete。明确当前目标结论，每条意见指向实际受影响refs，区分观察/复算/推测；推测不是已证事实。必须单独调用。')


def schemas(toolset=TOOLS):
    def strip(value):
        if isinstance(value, dict): return {k: strip(v) for k, v in value.items() if k not in ('title', 'default')}
        if isinstance(value, list): return [strip(v) for v in value]
        return value
    return [{'type': 'function', 'function': {'name': n, 'description': d,
        'parameters': strip(m.model_json_schema())}} for n, (m, d) in toolset.items()]
