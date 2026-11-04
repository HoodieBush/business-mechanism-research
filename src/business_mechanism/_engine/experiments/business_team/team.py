"""Five genuine LLM contexts, specialist handoffs and auditable native tools."""
from __future__ import annotations
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "capability_lab"))
from model_protocol import request_model, usage_summary

TEXT = {"type": "string", "minLength": 1}
FILES = {"type": "array", "items": TEXT}


def obj(fields, optional=()):
    return {"type": "object", "properties": fields, "required": [k for k in fields if k not in optional], "additionalProperties": False}


SCHEMAS = {
    "read_context": obj({}), "read_history": obj({}),
    "read_artifact": obj({"path": TEXT, "offset": {"type":"integer", "minimum":0}}, optional=("offset",)),
    "query_data": obj({"sql": TEXT, "output_semantics": TEXT}),
    "run_python": obj({"code": TEXT, "purpose": TEXT, "output_semantics": TEXT}),
    "review_artifact": obj({'artifact_id':{'type':'string','minLength':1,'description':'Exact artifact_id returned by read_artifact, e.g. artifact_0001. No path or explanatory text.'},
        'execution_id':{'type':'string','minLength':1,'description':'Exact execution_id returned by your own run_python, e.g. execution_0002. No path or explanatory text.'},'decision':{'type':'string','enum':['accepted','rejected','unresolved']},
        'checks':{'type':'array','minItems':6,'items':obj({'aspect':{'type':'string','enum':['source_binding','transformation','units','grain','availability','interpretation']},
                      'status':{'type':'string','enum':['checked','problem','not_applicable']},'rationale':TEXT})},'summary':TEXT}),
    "assign_task": obj({"role": {"type": "string", "enum": ["analyst", "mechanist", "verifier", "engineer"]}, "question": TEXT, "inputs": FILES}),
    "save_hypothesis": obj({"explanation": TEXT, "scope": TEXT, "alternatives": FILES, "prediction": TEXT,
                            "falsification": TEXT, "evidence_files": FILES, "change_reason": TEXT, "parent_id": TEXT}, optional=("parent_id",)),
    "record_verdict": obj({"hypothesis_id": TEXT, "status": {"type": "string", "enum": ["supported_in_scope", "refuted", "unresolved"]},
                           "rationale": TEXT, "evidence_files": FILES}),
    "run_experiment": obj({"hypothesis_id": TEXT, "kind": {"type": "string", "enum": ["inventory_audit", "supply_trial"]},
                           "support_sku": TEXT, "product_ids": {"type": "array", "minItems": 1, "items": TEXT},
                           "days": {"type": "integer", "enum": [14]}, "prediction": TEXT, "controls": TEXT, "analysis_plan": TEXT}),
    "evaluate_algorithm": obj({"code_file": TEXT, "hypothesis_ids": FILES, "rationale": TEXT}),
    "submit_result": obj({"summary": TEXT, "evidence_files": FILES, "findings": FILES, "next_step": TEXT}),
}

MENUS = {
    "manager": ["assign_task", "read_artifact", "read_history", "submit_result"],
    "analyst": ["read_context", "read_artifact", "read_history", "query_data", "run_python", "submit_result"],
    "mechanist": ["read_context", "read_artifact", "read_history", "save_hypothesis", "submit_result"],
    "verifier": ["read_context", "read_artifact", "read_history", "query_data", "run_python", "review_artifact", "run_experiment", "record_verdict", "submit_result"],
    "engineer": ["read_context", "read_artifact", "read_history", "run_python", "evaluate_algorithm", "submit_result"],
}

DESCRIPTIONS = {
    "read_context": "读取当前任务的公开上下文与原始数据契约。", "read_history": "读取相关假说、反例、任务结果和算法开发历史。",
    "read_artifact": "读取文本文件及配套来源/含义元数据；每次18000字符，可用offset继续读取。PNG等二进制应通过Python检查。",
    "query_data": "自己写只读SQLite SELECT；说明输出每行粒度、字段单位和聚合含义。返回CSV、预览、来源字段定义和元数据；SQL变换的语义未自动推断，仍需独立复核。最多100000行，可分查询。",
    "run_python": "实际保存并执行Python，pandas/NumPy/SciPy/matplotlib/sklearn/statsmodels可用；说明分析目的与输出文件的粒度/单位/含义。PUBLIC_DIR公开数据、ARTIFACT_DIR共享产物只读，WORK_DIR本角色可写；网络和私有文件不可访问。单脚本45秒，失败可修正再运行。返回完整输出文件、代码哈希、来源版本和语义警告；输出声明仍需复核。",
    "assign_task": "将一个明确任务派发给专业Agent；等待真实结果返回，不替该角色完成工作。",
    "save_hypothesis": "登记一个有证据、竞争解释、预测、反证和父版本的假说。返回新ID；自身不认证。",
    "record_verdict": "保存验证者对现有假说的有范围结论与依据；原负例保留。",
    "run_experiment": "先登记方案，然后执行库存账实核对或14天按柜点-日随机保证配套供应的新试验。返回原始观测和参考统计。",
    "evaluate_algorithm": "冻结已写的predict代码，用新经营模拟比较原算法、重调参数和强数值基准；保存开发结果，后续独立验收另留。",
    "submit_result": "交付实际成果与局限；依据文件及配套语义/来源元数据复制为不可变交接副本。不要把分析者声明当独立认证。",
    'review_artifact':'验证者复核源字段绑定、变换、单位、粒度、预测时可用性和解释。先read_artifact获得artifact_id，再独立读取原始注册输入run_python获得execution_id；原样填入两个ID，不填路径或追加说明，推理只写checks/summary。结论绑定文件及来源图精确版本；接受/退回/未决不等于因果真值。',
}

ROLE_PROMPTS = {
    "manager": "你是研究主管。先派数据分析，再派验证者复核关键产物的字段来源/变换/含义，有错退回分析者修订。只有被复核接受的派生证据才能交机制研究者。之后再验证假说、改算法和评价。主管自己的任务描述不是事实认证，不把上游推测写成确定事实。必须真的派发，不替所有人分析。角色数不增加，信息复核与因果/经营验证是两个阶段，旧失败不可抹去。",
    "analyst": "你是数据分析Agent。独立查询数据和写Python，定位原算法在哪些柜点/商品/时段反复失效，量化损益，先检查库存和记录。保存可复现代码、结果数据、至少一个分析报告或图。不要把销量当完整需求或把相关性当因果。用实际表字段，不凭空猜数据。注册SQLite表可用research_data.read_table(name)，CSV用pandas.read_csv；依据各自字段定义，保留真实来源和实际变换，不把联接CSV当同结构SQL表。若用Frame.to_csv，可用interpretations逐列声明含义/单位，声明与输入定义分开，初始为draft。普通pandas及CSV导出可用；明确未自动追踪部分，不编造lineage或为此强行构造Frame。交付由验证者独立复核，不能自行宣告语义正确。",
    "mechanist": "你是机制研究Agent。读取分析者真正的产物和业务资料，提出少量可区分解释；与已有假说/负例比较，登记save_hypothesis，说明什么新检验会改变判断。不要直接认定合理故事为真。分析不足时向主管明确请求；依据反馈修订时引用parent_id和原反例。数据故障也是合法解释。只能把有当前独立复核回执的派生证据作为观测事实。主管问题与产出者解释是未核实说明，与来源定义有冲突应退回，不靠合理故事补全。",
    "verifier": "你是验证研究Agent，与产出者分开。先审查信息交接：源字段身份不会因筛选行或改列名改变；对比自动来源图与逐列解释，实体、单位、粒度、时间和预测目标须一致。从原始注册输入独立写代码，不仅复用产出者计算。用review_artifact接受/退回/未决具体版本，不能拿哈希或来源存在代替含义正确。任意程序无法追踪的变换明确不确定性，必要时退回补契约。随后再验证假说，排除供给/记录/共同变化，制定新试验与record_verdict。信息复核不认证唯一机制。",
    "engineer": "你是算法工程Agent。读取原baseline.py、历史分析和验证结论，自己编写并保存定义predict(history,future)的Python模块。可增加被支持的特征、修复训练标签或调整结构；不要用未来销量、闭库存和缺货分钟预测。调用evaluate_algorithm比较实绩和强基准，不把多训练数据/调参全归于新机制。收益不足可修订或回退，记录实际代码和适用范围。"
}


def validate(value, schema):
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or set(value) - set(schema["properties"]) or set(schema["required"]) - set(value):
            raise ValueError("tool fields must match schema exactly")
        for k, v in value.items():
            validate(v, schema["properties"][k])
    elif kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("nonempty string required")
    elif kind == "integer":
        if type(value) is not int or value < schema.get("minimum", -float("inf")):
            raise ValueError("integer required")
    elif kind == "array":
        if not isinstance(value, list) or len(value) < schema.get("minItems", 0):
            raise ValueError("array required")
        for item in value:
            validate(item, schema["items"])
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("value outside declared options")


class BudgetStop(RuntimeError):
    pass


def decode_actions(raw, role, schemas, menus=None):
    if not raw.get("choices") or raw["choices"][0].get("finish_reason") == "length":
        raise ValueError("transport failure or truncated response")
    message = raw["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if calls:
        if not 1 <= len(calls) <= 3 or len({c.get("id") for c in calls}) != len(calls):
            raise ValueError("one to three uniquely identified function calls required")
        actions = [{"tool": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"])} for c in calls]
    else:
        action = json.loads(message.get("content") or "")
        if not isinstance(action, dict) or set(action) != {"tool", "arguments"}:
            raise ValueError("whole tool/arguments object required")
        actions = [action]
    for i, action in enumerate(actions):
        if action["tool"] not in (menus or MENUS)[role]:
            raise ValueError("tool outside role permissions")
        validate(action["arguments"], schemas[action["tool"]])
        if action["tool"] == "submit_result" and i != len(actions)-1:
            raise ValueError("submit_result must be last")
    return actions


class ResearchTeam:
    def __init__(self, workspace, config, limits, global_usage, recovery=None):
        self.workspace, self.config, self.limits, self.global_usage = workspace, config, limits, global_usage
        self.recovery = recovery or {"initial_wait_seconds":3,"backoff_multiplier":2,"maximum_wait_seconds":45}
        self.messages = {}
        log=workspace.root/"model_calls.jsonl"
        self.calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        for record in self.calls:
            if record not in global_usage:global_usage.append(record)
        starts=workspace.root/"requests_started.jsonl"
        self.request_serial=max([0]+[json.loads(l)["request_index"] for l in starts.read_text().splitlines()]) if starts.exists() else 0
        self.dispatches = {role: 0 for role in MENUS}
        self.checkpoint = workspace.root/"team_checkpoint.json"
        saved=json.loads(self.checkpoint.read_text()) if self.checkpoint.exists() else {}
        self.frames = saved.get("frames",{})
        self.dispatches.update(saved.get("role_dispatches",{}))
        workspace.delegate = self.run_role

    def persist(self):
        from workspace import write_json
        write_json(self.checkpoint,{"version":"team-checkpoint-v1","frames":self.frames,"role_dispatches":self.dispatches})

    def usage(self):
        return usage_summary(self.calls)

    def call(self, role, payload):
        from transport import retryable, retry_delay, interruptible_wait
        failures=self.frames.get(role,{}).get("transport_failures",0)
        while True:
            ratios=[c["response"]["usage"].get("prompt_tokens",0)/max(1,len(json.dumps(c["request"],ensure_ascii=False))) for c in self.global_usage if c.get("response",{}).get("usage",{}).get("prompt_tokens")]
            estimate=int(len(json.dumps(payload,ensure_ascii=False))*max([1.0]+[1.25*r for r in ratios]))+self.limits["max_output_tokens"]
            total=sum(c.get("response",{}).get("usage",{}).get("total_tokens",0) for c in self.global_usage)
            if total+estimate>self.limits["round_reported_token_budget"]:
                raise BudgetStop("whole-round reported-cost admission stop; missing usage is reported separately, never counted as zero or as measured usage")
            self.request_serial+=1
            request_index=self.request_serial
            with (self.workspace.root/"requests_started.jsonl").open("a") as f:
                f.write(json.dumps({"request_index":request_index,"role":role,"request":payload},ensure_ascii=False)+"\n")
            record=request_model(self.config,payload)
            record.update(role=role,request_index=request_index,admission_estimate=estimate,transport_retry_number=failures)
            self.calls.append(record);self.global_usage.append(record)
            with (self.workspace.root/"model_calls.jsonl").open("a") as f:f.write(json.dumps(record,ensure_ascii=False)+"\n")
            if not retryable(record):
                self.frames.get(role,{})["transport_failures"]=0
                if record.get("error_type") or record.get("response",{}).get("error"):
                    raise ConnectionError("permanent/nonretryable API error: "+str(record.get("error") or record.get("response",{}).get("error"))[:1000])
                return record
            failures+=1
            self.frames.get(role,{})["transport_failures"]=failures
            delay=retry_delay(record,failures,self.recovery)
            retry={"request_index":request_index,"role":role,"consecutive_transport_failures":failures,"wait_seconds":round(delay,3),"error_type":record.get("error_type"),"error":record.get("error"),"http_status":record.get("http_status"),"policy":"retry identical request; no scientific action executed and no failure injected into research dialogue"}
            with (self.workspace.root/"retry_events.jsonl").open("a") as f:f.write(json.dumps(retry,ensure_ascii=False)+"\n")
            print(f"RECONNECT request={request_index} role={role} wait={delay:.1f}s error={retry['error']}",flush=True)
            self.persist()
            interruptible_wait(delay)

    def run_role(self, role, task):
        existing=self.frames.get(role)
        same=existing and (role=="manager" or existing["task"].get("id")==task.get("id"))
        if same and existing["status"]=="completed":return existing["result"]
        if same:
            frame=existing
        else:
            self.dispatches[role]+=1
            system=getattr(self.workspace,'role_prompts',ROLE_PROMPTS)[role]+"\n只见公开资料，不读私有生成器/评分。每响应可调用1..3个菜单函数，参数平铺，不嵌套tool/args。依赖新对象或新证据结论另次提交，submit_result最后。大型CSV用Python/SQL分析，不把前几行当全体。若代理忽略tools，只能输出整个JSON对象{\"tool\":函数名,\"arguments\":参数}。不得杜撰结果。任务无固定调用次数；达到任务目标后交付真实成果。先确认数据粒度、单位、时间点、未来可用性和聚合含义；读交接文件同时读元数据。新任务读取可复核档案与旧反例。资料定义冲突须明确报告，不自行补造。连接恢复由系统负责，不把服务失败当科学反驳。"
            frame={"role":role,"task":task,"status":"running","pending":None,"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps({"task":task,"context":self.workspace.initial_context(),"role_workspace":str(self.workspace.workers[role].directory),"previous_hypotheses":self.workspace.state["hypotheses"]},ensure_ascii=False)}]}
            self.frames[role]=frame
        messages=frame["messages"];self.messages[role]=messages
        schemas=copy.deepcopy(SCHEMAS)
        if role=="manager":
            schemas["submit_result"]["properties"]["selected_algorithm_id"]=TEXT
            schemas["submit_result"]["required"].append("selected_algorithm_id")
        menus=getattr(self.workspace,'tool_menus',MENUS)
        definitions=[{"type":"function","function":{"name":name,"description":DESCRIPTIONS[name],"parameters":schemas[name]}} for name in menus[role]]
        self.persist()
        while True:
            if not frame["pending"]:
                payload={"model":self.config["model"],"messages":copy.deepcopy(messages),"temperature":0,"max_tokens":self.limits["max_output_tokens"],"tools":definitions,"tool_choice":"auto",**self.config.get("generation_options",{})}
                record=frame.pop("received_record",None)
                if record is None:
                    self.persist()
                    record=self.call(role,payload)
                    frame["received_record"]=record;self.persist()
                    frame.pop("received_record")
                raw=record.get("response",{})
                message=raw.get("choices",[{}])[0].get("message",{})
                calls=message.get("tool_calls") or []
                assistant={"role":"assistant","content":message.get("content") or ""}
                if "reasoning_content" in message:assistant["reasoning_content"]=message["reasoning_content"]
                if calls:assistant["tool_calls"]=[{k:c[k] for k in ("id","type","function")} for c in calls]
                messages.append(assistant)
                try:actions=decode_actions(raw,role,schemas,menus=menus)
                except Exception as error:
                    feedback={"ok":False,"error_type":type(error).__name__,"error":str(error)[:2000]}
                    key=f"{record['request_index']}_{role}_protocol"
                    self.workspace.event(role,"protocol_error",None,feedback,operation_id=key)
                    content=json.dumps(feedback,ensure_ascii=False)
                    if calls:messages.extend({"role":"tool","tool_call_id":c["id"],"content":content} for c in calls)
                    else:messages.append({"role":"user","content":content})
                    with (self.workspace.root/"tool_actions.jsonl").open("a") as f:f.write(json.dumps({"request_index":record["request_index"],"role":role,"action":{"tool":None},"feedback":feedback},ensure_ascii=False)+"\n")
                    print(f"request={record['request_index']} role={role} protocol_error={feedback['error']}",flush=True)
                    self.persist();continue
                frame["pending"]={"record_index":record["request_index"],"prefix":str(record["request_index"]),"calls":calls,"actions":actions,"index":0,"results":[],"known_hypotheses":[h["id"] for h in self.workspace.state["hypotheses"]],"known_algorithms":["baseline"]+[a["id"] for a in self.workspace.state["algorithms"]],"known_files":[str(p.resolve()) for base in (self.workspace.public,self.workspace.shared) for p in base.rglob('*') if p.is_file()]}
                self.persist()
            pending=frame["pending"]
            while pending["index"]<len(pending["actions"]):
                index=pending["index"];action=pending["actions"][index];name,args=action["tool"],action["arguments"]
                key=f"{pending['prefix']}_{role}_{index}"
                try:
                    if args.get("parent_id") and args["parent_id"] not in pending["known_hypotheses"]:raise ValueError("new parent ID requires next request")
                    if name in ("record_verdict","run_experiment") and args["hypothesis_id"] not in pending["known_hypotheses"]:raise ValueError("new hypothesis requires next request")
                    if name=="submit_result" and role=="manager" and args["selected_algorithm_id"] not in pending["known_algorithms"]:raise ValueError("manager must see algorithm result before selecting it")
                    if name=="record_verdict" and any(str(self.workspace.readable(p)) not in pending["known_files"] for p in args["evidence_files"]):raise ValueError("new validation evidence requires next request before verdict")
                    result=self.workspace.tool(role,name,args,operation_id=key)
                    feedback={"ok":True,"result":result}
                except (BudgetStop,KeyboardInterrupt):raise
                except Exception as error:feedback={"ok":False,"error_type":type(error).__name__,"error":str(error)[:2000]}
                self.workspace.event(role,name,args,feedback,operation_id=key)
                with (self.workspace.root/"tool_actions.jsonl").open("a") as f:f.write(json.dumps({"request_index":pending["record_index"],"operation_id":key,"action_index":index,"role":role,"action":action,"feedback":feedback},ensure_ascii=False,default=str)+"\n")
                content=json.dumps(feedback,ensure_ascii=False,default=str)
                if pending["calls"]:messages.append({"role":"tool","tool_call_id":pending["calls"][index]["id"],"content":content})
                else:messages.append({"role":"user","content":content})
                pending["results"].append(feedback);pending["index"]+=1
                print(f"request={pending['record_index']} role={role} tool={name} ok={feedback['ok']} reported_tokens={self.usage()['total_tokens']}",flush=True)
                if name=="submit_result" and feedback["ok"]:
                    frame.update(status="completed",result=feedback["result"]);frame["pending"]=None;self.persist()
                    return feedback["result"]
                self.persist()
            frame["pending"]=None;self.persist()
