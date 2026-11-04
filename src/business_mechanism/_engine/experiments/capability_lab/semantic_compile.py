"""Compile public physical facts, with no outcomes, mechanisms, or scorer input."""
import copy
import hashlib
import json
from pathlib import Path
import threading

from lab import validate_model
from model_protocol import decode_submission,request_model,structured_request,submission_transport

ROOT=Path(__file__).resolve().parent
LOCK=threading.Lock()
SCHEMA={"type":"object","properties":{
    "ontology":{"type":"object","additionalProperties":{"type":"string"}},
    "catalog_roles":{"type":"object","additionalProperties":{"type":"array","items":{"type":"string"}}}},
    "required":["ontology","catalog_roles"],"additionalProperties":False}
VERSION="physical-facts-v0.2-declarations-to-rules"


class CompilationError(ValueError):
    def __init__(self,message,records):
        super().__init__(message);self.records=records


def validate_compilation(proposal,catalog,ontology=None):
    patterns=proposal["role_patterns"];definitions=proposal["ontology"];facts=proposal["catalog_roles"]
    validate_model({"role_patterns":patterns,"expression":0})
    if set(definitions)!=set(patterns) or any(not isinstance(v,str) or not v for v in definitions.values()):
        raise ValueError("each role requires a physical definition")
    if ontology is not None and definitions!=ontology:raise ValueError("frozen role definitions changed")
    if set(facts)!={p["id"] for p in catalog}:raise ValueError("cover each public product exactly")
    for p in catalog:
        declared=facts[p["id"]]
        if not isinstance(declared,list) or len(set(declared))!=len(declared) or not set(declared)<=set(patterns):
            raise ValueError("invalid per-product function declaration")
        matched={k for k,values in patterns.items() if any(s in p["description"] for s in values)}
        if matched!=set(declared):raise ValueError("fact/rule inconsistency for "+p["id"]+": declared="+str(declared)+", matched="+str(sorted(matched)))
    if any(not any(s in p["description"] for p in catalog) for values in patterns.values() for s in values):
        raise ValueError("pattern has no public textual evidence")
    return copy.deepcopy(proposal)


def compile_structured(catalog):
    keys=set(catalog[0]["functions"])
    if not {"heating","utensils"}<=keys:raise ValueError("missing public core function fields")
    patterns={k:[p["description"] for p in catalog if p["functions"][k]] for k in sorted(keys)}
    proposal={"role_patterns":patterns,"ontology":{k:"公开 functions 字段 "+k for k in sorted(keys)},
        "catalog_roles":{p["id"]:[k for k in sorted(keys) if p["functions"][k]] for p in catalog}}
    return validate_compilation(proposal,catalog)


def compile_declarations(declarations,catalog,ontology=None):
    """Compile public per-product labels, without correcting semantic labels."""
    definitions=declarations["ontology"];roles=declarations["catalog_roles"]
    if not isinstance(definitions,dict) or not {"heating","utensils"}<=set(definitions):
        raise ValueError("declare the two core physical functions")
    if set(roles)!={p["id"] for p in catalog}:raise ValueError("cover each public product exactly")
    for values in roles.values():
        if not isinstance(values,list) or len(set(values))!=len(values) or not set(values)<=set(definitions):
            raise ValueError("invalid declared physical roles")
    patterns={name:list(dict.fromkeys(p["description"] for p in catalog if name in roles[p["id"]]))
              for name in definitions}
    return validate_compilation({"ontology":definitions,"catalog_roles":roles,"role_patterns":patterns},catalog,ontology)


def compile_text(catalog,config,ontology=None):
    system="你只识别商品的实物功能事实，不研究购买效应，不接收销量或机制。核心名称 heating 表示能提高餐食温度，utensils 表示实际可用于进餐的器具。可另声明目录明确提供、能在不同商品实现上复用的实物功能；不要另建单一 SKU 类型、材料、外观或构造的角色。总角色不超过 8 个，名称用英文 snake_case，不与 heat/external_heat/external_utensils/items/min/max/sigmoid 冲突。图案、宣传字样、包装相似和否定句不提供被否定的功能。不得把心理、购买率或商业效果声明为功能。只输出 ontology（角色名到简短实物定义）、catalog_roles（每个 id 的实物角色列表）。确定性编译器会将这些逐商品声明编译为可执行规则；不会替你纠正实物判断。"
    if ontology is not None:system+="\n变量定义已经冻结，必须逐字保留 ontology，不能新增、删去或重命名角色。只将新商品描述按这些定义编译，合并覆盖目录中的全部旧/新商品。"
    context={"catalog":catalog,"frozen_ontology":ontology}
    records=[];correction=None
    for _ in range(2):
        messages=[{"role":"system","content":system},{"role":"user","content":json.dumps(context,ensure_ascii=False)}]
        if correction:messages.append({"role":"user","content":json.dumps(correction,ensure_ascii=False)})
        payload={"model":config["model"],"messages":messages,"temperature":0,"max_tokens":1800,
                 **config.get("generation_options",{})}
        payload=structured_request(payload,config,"submit_physical_facts",SCHEMA)
        digest=hashlib.sha256(json.dumps({"base_url":config["base_url"],"request":payload},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        path=ROOT/"results/semantic_cache"/(digest+".json");path.parent.mkdir(parents=True,exist_ok=True)
        with LOCK:
            if path.exists():record=json.loads(path.read_text());record["cache_hit"]=True
            else:
                record=request_model(config,payload)
                if "response" in record:path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
        records.append(record)
        if "response" not in record:raise CompilationError(record["error"],records)
        try:
            proposal=decode_submission(record["response"],config,"submit_physical_facts")
            record["submission_transport"]=submission_transport(record["response"]);record["proposal"]=proposal
            compiled=compile_declarations(proposal,catalog,ontology)
            record["compiler_version"]=VERSION;record["compiled_facts"]=compiled
            return compiled,records
        except (ValueError,KeyError,TypeError) as error:
            record["compilation_error"]=str(error)
            correction={"previous_submission":record.get("proposal"),"contract_error":str(error),
                        "instruction":"只修正目录事实与规则，不猜测任何购买效果。"}
    raise CompilationError(records[-1]["compilation_error"],records)
