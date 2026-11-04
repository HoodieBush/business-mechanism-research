"""Independent heterogeneous binary-choice generator; never send to an agent.

Probability is a mixture over consumer utilities, not the legacy linear model.
The cohort sampler marginalizes independent consumer classes exactly.
"""
from __future__ import annotations
from dataclasses import dataclass
import copy
import hashlib
import math

import numpy as np

from catalog_fixtures import DESCRIPTIONS,FUNCTION_KEYS,MEMBERSHIPS,UNIT_COSTS
from lab import ResearchLab

FAMILIES={"source_joint","threeway","mixed_scope","null"}


def sigmoid(value):
    return 1/(1+math.exp(-value)) if value>=0 else math.exp(value)/(1+math.exp(value))


def economics(retail_price=8.):
    return {"customers_per_day":80,"days_per_profile":40,"retail_price":float(retail_price),
        "purchase_cost":3.,"salvage_value":.5,"stock_capacity":60,
        "auxiliary_slot_profiles":[1,2,3],
        "material_cost_timing":"辅助物料对每个合格会话配置，成本每会话发生；商品对顾客免费。",
        "inventory_protocol":"每日一次采购，目标商品当日到期，无跨日结存；需求超过可售数为损失销售。"}


@dataclass
class ChoiceWorld:
    seed:int=0
    family:str="threeway"
    fault:str="none"
    fact_mode:str="structured"
    retail_price:float=8.

    def __post_init__(self):
        if self.family not in FAMILIES:raise ValueError("unknown private choice family")
        if self.fault not in {"none","supply","report"}:raise ValueError("unknown private fault")
        if self.fact_mode not in {"structured","text"}:raise ValueError("unknown public fact mode")
        if type(self.retail_price) not in (int,float) or not 6<=self.retail_price<=12:raise ValueError("unsupported public retail price")
        self.catalogs={};self.roles={}
        for stage in ("source","adaptation","heldout"):
            catalog=[];roles={}
            for index,(description,membership,cost) in enumerate(zip(DESCRIPTIONS[stage],MEMBERSHIPS,UNIT_COSTS)):
                pid=hashlib.sha256(f"choice-catalog:{self.seed}:{stage}:{index}".encode()).hexdigest()[:10]
                facts={name:name in membership for name in FUNCTION_KEYS}
                item={"id":pid,"description":description,"retailer_cost_per_session":cost}
                if self.fact_mode=="structured":item["functions"]=facts.copy()
                catalog.append(item);roles[pid]=facts
            np.random.default_rng(self.seed+sum(map(ord,stage))).shuffle(catalog)
            self.catalogs[stage]=catalog;self.roles[stage]=roles
        rng=np.random.default_rng(self.seed+712311)
        w=float(rng.uniform(.45,.65));self.weights=(w,1-w)
        self.intercepts=(-1.25+float(rng.normal(0,.12)),-.6+float(rng.normal(0,.12)))
        self.gains=(float(rng.uniform(1.8,2.4)),float(rng.uniform(1.0,1.6)))
        self.queue_losses=(float(rng.uniform(.65,.95)),float(rng.uniform(.25,.55)))
        self.frictions=(float(rng.uniform(.35,.55)),float(rng.uniform(.15,.3)))

    def class_probabilities(self,stage,assortment,external):
        selected=[self.roles[stage][pid] for pid in assortment]
        h=any(r["heating"] for r in selected);u=any(r["utensils"] for r in selected)
        s=any(r["sealing"] for r in selected)
        a=max(int(h),external[0]);b=max(int(u),external[1])
        gate=a*b if self.family=="source_joint" else a*b*int(s)
        probabilities=[]
        # Explicit public price change is a development transfer boundary. The
        # default price leaves every previously generated probability unchanged.
        for intercept,gain,queue,friction,price_sensitivity in zip(self.intercepts,self.gains,self.queue_losses,self.frictions,(.55,.25)):
            utility=intercept-price_sensitivity*(self.retail_price-8)+(0 if self.family=="null" else gain*gate)
            if self.family=="mixed_scope":
                utility-=queue*external[0]*(1-int(h))*b*int(s)
                utility-=friction*max(len(assortment)-2,0)
            probabilities.append(sigmoid(utility))
        return probabilities

    def probability(self,stage,assortment,external):
        return sum(w*p for w,p in zip(self.weights,self.class_probabilities(stage,assortment,external)))

    def purchases(self,stage,assortment,external,class_uniforms,buy_uniforms):
        probabilities=np.asarray(self.class_probabilities(stage,assortment,external))
        classes=(np.asarray(class_uniforms)>=self.weights[0]).astype(int)
        return np.asarray(buy_uniforms)<probabilities[classes]

    def history_audit(self):
        # Matched diagnostic fixture, separately labelled as conditional history.
        sales=220 if self.fault=="report" else 120
        opening=120 if self.fault=="supply" else 240
        return {"physical_opening":opening,"physical_closing":opening-sales,
                "recorded_opening":240,"recorded_closing":120}


class ChoiceLab(ResearchLab):
    def public(self):
        public=super().public()
        public["task"]="识别可操作购买概率及适用范围，冻结模型；部署时只允许读取新商品事实，随后由共同优化器选择物料配置与每日采购量。允许未决，不要求猜隐藏类型。"
        public["target"]="固定价格即食带汤餐食；每个合格会话最多购买一个目标；辅助物料对顾客免费，零售商成本由目录提供。研究 cohort 供给核实时没有销售截断。"
        public["history_note"]+=" 此历史为条件化诊断案例，不用于估计总体购买率或样本功效。"
        public["deployment_contract"]="冻结后可以读取第三组商品描述或公开功能字段，按已冻结变量定义编译事实；不能改写概率关系或参数、查询销量或重新拟合。"
        public["operating_objective"]=economics(self._world.retail_price)
        public["tools"]["deployment_catalog"]={"args":{},"cost":0,"returns":"仅在 finish 后可读取部署商品事实，无销量或评分。"}
        if self._world.fact_mode=="structured":
            public["fact_contract"]="functions 是可核查的实物功能，不是购买效应。额外功能可形成新变量，但因果关系须实验检验。"
        else:
            public["fact_contract"]="仅依据实物功能描述；图案、宣传字样与否定句不代表实物具备该功能。额外功能可形成新变量，不预设购买效应。"
        return public

    def deployment_catalog(self):
        if self.final is None:raise ValueError("freeze the mechanism before deployment facts")
        return copy.deepcopy(self._world.catalogs["heldout"])

    def call(self,tool,args):
        if tool!="deployment_catalog":return super().call(tool,args)
        if not isinstance(args,dict) or args:raise ValueError("deployment_catalog takes an empty object")
        result=self.deployment_catalog()
        self.events.append({"event_id":len(self.events),"request":{"tool":tool,"args":{}},
            "response":copy.deepcopy(result),"used":self.used.copy()})
        return result
