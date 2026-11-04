"""Six critic actions; review is evidence-linked, never a truth certificate."""
from typing import Literal
from pydantic import Field
from ..contracts import Input, ReadArtifact, QueryData, RunPython


class SearchMemory(Input):
    query: str = ''
    kind: Literal['all', 'hypothesis', 'plan', 'result', 'assessment', 'state', 'knowledge', 'action'] = 'all'
    hypothesis_ref: str | None = None
    status: str | None = None
    lifecycle_status: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=30)


class Check(Input):
    action_ref: str
    finding: str = Field(min_length=1)
    artifact_refs: list[str] = Field(default_factory=list)


class Issue(Input):
    issue_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    type: Literal['reproduced_contradiction', 'missing_evidence', 'methodological_disagreement']
    evidence_locations: list[str] = Field(min_length=1)
    action_refs: list[str] = Field(default_factory=list)
    check_artifact_refs: list[str] = Field(default_factory=list)
    claim_impact: str = Field(min_length=1)
    minimal_next_step: str = Field(min_length=1)


class RecordReview(Input):
    phase: Literal['checkpoint', 'complete']
    checked_scope: list[str] = Field(min_length=1)
    unchecked_scope: list[str]
    source_refs: list[str] = Field(min_length=1)
    checks_performed: list[Check]
    issues: list[Issue]
    open_issue_ids: list[str]
    next_action: str = Field(min_length=1)


TOOLS = {
    'read_artifact': (ReadArtifact, '按ref分页读公开输入、科学原件、代码和核验产物。'),
    'read_memory': (ReadArtifact, '按ref分页读科学记录、card:假说、action:操作事实或check:本次动作；无原私人思考。'),
    'search_memory': (SearchMemory, '分页搜索完整合法档案，含无假说绑定、旧、撤回和替代条目；科学status与lifecycle_status分开。'),
    'query_data': (QueryData, '只读公开business.sqlite，保存SQL、全部输出及回执；不是新观测。'),
    'run_python': (RunPython, '在独立沙箱复算已见资料，来源只读；PUBLIC_DIR/ARTIFACT_DIR/WORK_DIR由系统提供。'),
    'record_review': (RecordReview, '保存核验checkpoint或complete。目标与版本由系统绑定；每个核验引用实际返回的action_ref。无问题时issues可为空。必须单独调用。'),
}


def schemas():
    def strip(value):
        if isinstance(value, dict): return {k: strip(v) for k, v in value.items() if k not in ('title', 'default')}
        if isinstance(value, list): return [strip(x) for x in value]
        return value
    return [{'type': 'function', 'function': {'name': name, 'description': desc,
        'parameters': strip(model.model_json_schema())}} for name, (model, desc) in TOOLS.items()]
