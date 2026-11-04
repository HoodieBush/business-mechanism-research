"""The twelve research actions. No role dispatch or algorithm delivery fields."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ReadContext(Input):
    pass


class ReadArtifact(Input):
    ref: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12000, ge=1, le=18000)


class QueryData(Input):
    sql: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class RunPython(Input):
    code: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class SaveHypothesis(Input):
    kind: Literal['business', 'data_quality', 'program_diagnosis']
    statement: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    prediction: str = Field(min_length=1)
    falsification: str = Field(min_length=1)
    alternatives: list[str] = Field(min_length=1)
    evidence_refs: list[str]
    parent_ref: str | None = None


class RegisterTest(Input):
    hypothesis_ref: str
    prediction: str = Field(min_length=1)
    contrast: str = Field(min_length=1)
    observation_unit: str = Field(min_length=1)
    allocation_unit: str = Field(min_length=1)
    analysis: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    data_refs: list[str] = Field(min_length=1)
    mode: Literal['observational', 'protocol']
    code: str | None = None
    protocol_id: str | None = None
    outcome_product_ids: list[str] = Field(default_factory=list)
    expected_changed_variables: list[str] = Field(default_factory=list)
    parent_plan_ref: str | None = None


class RunTest(Input):
    plan_ref: str


class RecordAssessment(Input):
    hypothesis_ref: str
    result_refs: list[str] = Field(min_length=1)
    status: Literal['supported', 'refuted', 'unresolved']
    prediction_coverage: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    deviations: list[str]
    counterevidence_refs: list[str]
    limitations: list[str] = Field(min_length=1)


class UpdateResearchState(Input):
    question: str = Field(min_length=1)
    why: str = Field(min_length=1)
    understanding: str = Field(min_length=1)
    active_hypothesis_refs: list[str]
    inactive_hypotheses: dict[str, str] = Field(default_factory=dict, description='暂停或归档的假说及具体理由；原记录仍可检索，不代表否证。')
    alternative_refs: list[str]
    evidence_refs: list[str]
    counterevidence_refs: list[str]
    incorporated_result_refs: list[str]
    recent_change: str = Field(min_length=1)
    open_questions: list[str]
    next_action: str = Field(min_length=1)
    next_reason: str = Field(min_length=1)


class SearchMemory(Input):
    query: str = ''
    kind: Literal['all', 'hypothesis', 'plan', 'result', 'assessment', 'state', 'process'] = 'all'
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12, ge=1, le=30)


class FinishResearch(Input):
    assessment_refs: list[str]
    other_hypotheses: dict[str, str]
    limitations: list[str] = Field(min_length=1)
    open_questions: list[str]
    measurement_requests: list[str]


TOOLS = {
    'read_context': (ReadContext, '读取研究问题、当前认识、未吸收结果和合法资料目录。'),
    'read_artifact': (ReadArtifact, '按精确引用分页读取原件；大数据文件使用SQL/Python。'),
    'query_data': (QueryData, '只读查询公开数据库；保存查询、完整结果与来源。'),
    'run_python': (RunPython, '沙箱探索计算，只写本次执行目录；不是科学裁决。'),
    'save_hypothesis': (SaveHypothesis, '登记原预测、范围、反证与竞争解释；修订保留父版本。'),
    'register_test': (RegisterTest, '冻结原假说、数据版本、比较目标及可执行代码或真实协议，不执行。'),
    'run_test': (RunTest, '执行冻结方案；同一方案复用执行，不以重试获取新样本。'),
    'record_assessment': (RecordAssessment, '对原预测追加支持/反证/未决判断并披露局限，不自动认证正确。'),
    'update_research_state': (UpdateResearchState, '明确吸收结果、更新认识和下一步理由；原证据不改。'),
    'search_memory': (SearchMemory, '检索完整科学档案及自己的过程记录，可分页；检索命中不是事实认证。'),
    'read_memory': (ReadArtifact, '分页读取科学记录或自己的过程原件。'),
    'finish_research': (FinishResearch, '冻结阶段报告，披露全部假说状态、局限和待测量项。必须单独调用。'),
}


def schemas():
    return [{'type': 'function', 'function': {'name': name, 'description': description,
             'parameters': model.model_json_schema()}} for name, (model, description) in TOOLS.items()]
