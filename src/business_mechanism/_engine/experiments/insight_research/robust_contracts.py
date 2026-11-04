"""Small, explicit checks and memory reviews on the same twelve tools."""
from typing import Literal
from pydantic import Field
from . import contracts_memory as base


class EffectPrediction(base.base.Input):
    outcome_product_ids: list[str] = Field(min_length=1)
    site_ids: list[str] = Field(default_factory=list)
    direction: Literal['increase','decrease'] = 'increase'
    minimum_effect: float = Field(default=0.,ge=0,allow_inf_nan=False)


class Measurement(base.base.Input):
    source_ref: str = Field(description='Received result reference, or the public observed_facts.json file reference.')
    estimate_key: str = Field(default='primary',description='primary or secondary:<registered group name>')
    field: Literal['estimate','confidence','lower','upper','clusters','site_day_units','business_days_observed',
                   'row_count','business_days','calendar_window_days','sites','skus','hours',
                   'mismatched_rows','recorded_total','verified_total','difference_units']
    value: float | None = Field(default=None,allow_inf_nan=False,description='Omit to bind the exact computed value; if given it must agree.')


class KnowledgeUpdate(base.KnowledgeUpdate):
    measurements: list[Measurement] = Field(default_factory=list)


class MemoryReview(base.base.Input):
    target_ref: str
    decision: Literal['quarantine','withdraw','restore']
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class SaveHypothesis(base.SaveHypothesis):
    effect_prediction: EffectPrediction | None = Field(default=None,
        description='For a quantitative supply trial, predeclare the outcome, sites and minimum directed effect. Compatible numeric evidence is not unique mechanism proof.')


class RegisterTest(base.RegisterTest):
    outcome_groups: dict[str,list[str]] = Field(default_factory=dict,description='Predeclared secondary SKU groups; the primary outcome_product_ids must match the hypothesis numeric prediction.')


class UpdateResearchState(base.UpdateResearchState):
    knowledge_updates: list[KnowledgeUpdate] = Field(default_factory=list,max_length=6)
    memory_reviews: list[MemoryReview] = Field(default_factory=list,max_length=8)


TOOLS=dict(base.TOOLS)
for name,model in [('save_hypothesis',SaveHypothesis),('register_test',RegisterTest),('update_research_state',UpdateResearchState)]:
    TOOLS[name]=(model,TOOLS[name][1])
TOOLS['update_research_state']=(UpdateResearchState,'保存当前认识；knowledge_updates中的measurements核对结果字段，memory_reviews隔离/撤回/复核旧条目；supersedes_ref新增修订版并保留旧原件。')


def schemas():
    def strip(value):
        if isinstance(value,dict): return {k:strip(v) for k,v in value.items() if k not in ('title','default')}
        if isinstance(value,list): return [strip(v) for v in value]
        return value
    return [{'type':'function','function':{'name':name,'description':description,'parameters':strip(model.model_json_schema())}}
            for name,(model,description) in TOOLS.items()]
