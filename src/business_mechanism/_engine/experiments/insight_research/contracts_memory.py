"""Research-memory additions to the same twelve actions. One model, no curator."""
from pydantic import Field
from typing import Literal
from . import contracts as base


class KnowledgeUpdate(base.Input):
    kind: Literal['observation', 'relationship', 'method', 'provided_rule']
    statement: str = Field(min_length=1, max_length=1800)
    scope: str = Field(min_length=1, max_length=1200)
    status: Literal['tentative', 'supported_in_scope', 'refuted', 'needs_review', 'provided']
    evidence_refs: list[str] = Field(min_length=1)
    counterevidence_refs: list[str] = Field(default_factory=list)
    hypothesis_refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=12)
    research_use: str = Field(min_length=1, max_length=1000)
    supersedes_ref: str | None = None
    revision_reason: str = ''


class SaveHypothesis(base.SaveHypothesis):
    tags: list[str] = Field(default_factory=list, max_length=12)
    used_memory_refs: list[str] = Field(default_factory=list)


class RegisterTest(base.RegisterTest):
    used_memory_refs: list[str] = Field(default_factory=list)


class UpdateResearchState(base.UpdateResearchState):
    focus_hypothesis_refs: list[str] = Field(default_factory=list)
    hypothesis_notes: dict[str, str] = Field(default_factory=dict)
    knowledge_updates: list[KnowledgeUpdate] = Field(default_factory=list, max_length=6)
    used_memory_refs: list[str] = Field(default_factory=list)


class SearchMemory(base.Input):
    query: str = ''
    kind: Literal['all', 'hypothesis', 'plan', 'result', 'assessment', 'state', 'process', 'card', 'knowledge'] = 'all'
    hypothesis_ref: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=30)


TOOLS = dict(base.TOOLS)
for name, model in [('save_hypothesis', SaveHypothesis), ('register_test', RegisterTest),
                    ('update_research_state', UpdateResearchState), ('search_memory', SearchMemory)]:
    TOOLS[name] = (model, base.TOOLS[name][1])
TOOLS['update_research_state'] = (UpdateResearchState,
    '保存当前认识和结果吸收；focus指定本次研究焦点，hypothesis_notes补充分支理解，knowledge_updates增量形成带来源的宏观认识/方法经验。暂停用inactive_hypotheses说明理由。')
TOOLS['search_memory'] = (SearchMemory,
    '按问题、标签、原假说或状态检索科学记录/假说卡片/宏观认识。process需明确选择；命中不认证真伪。')
TOOLS['read_memory'] = (base.ReadArtifact,
    '按精确ref分页读取记录、card:假说引用、event:编号或自有process:编号；卡片含完整过程索引入口。')


def schemas():
    # Pydantic display titles are redundant on the wire, constraints stay exact.
    def strip(value):
        if isinstance(value, dict): return {k: strip(v) for k, v in value.items() if k not in ('title', 'default')}
        if isinstance(value, list): return [strip(v) for v in value]
        return value
    return [{'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': strip(model.model_json_schema())}} for name, (model, description) in TOOLS.items()]
