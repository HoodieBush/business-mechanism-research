from typing import Literal
from pydantic import Field
from ..contracts import Input
from ..paired_v10.contracts import TOOLS as PreviousTools,Response,schemas
from ..paired_v01.contracts import Assessment as BaseAssessment,FinishResearch as BaseFinish

class InspectEvidence(Input):
    source_ref: str
    analysis: Literal['daily_sales_effect','inventory_by_arm','record_balance']
    product_ids: list[str]=Field(min_length=1)
    site_ids: list[str]=Field(default_factory=list)
    site_groups: dict[str,list[str]]=Field(default_factory=dict)
    comparison_product_ids: list[str]=Field(default_factory=list)
    confidence: float=Field(default=.975,gt=0,lt=1,allow_inf_nan=False)
    first_day: int|None=None
    last_day: int|None=None

class ObjectReview(Input):
    target_ref: str
    expected_version: str|None=Field(default=None,description="Omit to bind the exact affected_versions entry of this received review; an explicit value must match. Not a view/file hash.")
    decision: Literal['withdraw','quarantine','restore']
    reason: str=Field(min_length=1)
    evidence_refs: list[str]=Field(min_length=1)

class Respond(Response):
    object_reviews: list[ObjectReview]=Field(default_factory=list,max_length=8,
        description='Explicit version-bound lifecycle action on an object affected by this exact issue. A reply alone is not repair.')

class ComponentAdjudication(Input):
    original_criterion: str=Field(min_length=1,description='Exact text from the original hypothesis falsification, not a posthoc invented rule.')
    disposition: Literal['triggered','not_triggered','unresolved']
    rationale: str=Field(min_length=1)
    evidence_refs: list[str]=Field(min_length=1)

class Assessment(BaseAssessment):
    supporting_artifact_refs: list[str]=Field(default_factory=list,description='Auxiliary received file refs; do not put files/actions/opinions into formal result_refs.')
    component_adjudications: list[ComponentAdjudication]=Field(default_factory=list,max_length=8,
        description='Original falsifiers adjudicated separately; status retains primary numeric compatibility, not automatic certification of the whole mechanism.')

class FinishResearch(BaseFinish):
    deferred_review_jobs: dict[str,str]=Field(default_factory=dict,
        description='Explicitly defer UNSTARTED assessment reviews excluded from published assessment_refs; reason required. Objects quarantined, all originals disclosed. Paid reviewer work cannot be deferred here.')

TOOLS={**PreviousTools,'inspect_evidence':(InspectEvidence,'沙箱复算已见数据：销量效应/按组库存/记录一致性；附完整范围、单位与自由度，不证明因果或等效。'),
 'respond_to_review':(Respond,'独立证据回应，可显式按版本隔离/撤回/复核该意见影响的对象；保留原件与下游检查，不能自动修复。'),
 'record_assessment':(Assessment,'保存候选判断；result_refs只含正式R，普通文件放supporting_artifact_refs；逐项记录原反证条件，主数值门禁不变。'),
 'finish_research':(FinishResearch,'形成待审阶段报告；可明确暂缓不发布的未启动判断审查并隔离其资格，披露所有过程；报告仍须核验。')}
from ..paired_v01.contracts import REVIEW_TOOLS as PreviousReviewTools
REVIEW_TOOLS={**PreviousReviewTools,'inspect_evidence':TOOLS['inspect_evidence']}
