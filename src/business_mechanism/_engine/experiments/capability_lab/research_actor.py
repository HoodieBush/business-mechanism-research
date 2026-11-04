"""Bounded real function submissions with role-correct observation feedback."""
import copy
import json

from model_protocol import decode_submission,request_model,structured_request,usage_summary
from research_action_schema import validate_action_args
from native_science_protocol import decode_native,function_definitions
from research_notebook import ResearchNotebook
from scientific_readiness import action_charge,readiness,validate_ready_action,validate_request_bindings
from public_context import NOTE,VERSION as CONTEXT_VERSION,assert_roundtrip,compact_json,unpack
from research_runtime import TOOLS
from run_research import CONFIG

VERSION="research-actor-v0.14-optional-public-confirmation-phases"
SYSTEM="你是固定价格库存机制研究协调器，只见公开事实与已收到证据，不能读取生成器或私有评分。16项科学服务全部可选。通过 submit_research_action 提交恰好 tool,args,rationale,expected_gap；args内理由不代替外层理由，理由/缺口约40字。每响应1..3个真实函数调用，返回顺序执行，依赖未知结果的动作另次提交，不猜ID；finish最后。当前状态与逐调用反馈是权威。商品功能不证明购买效应，源支持不认证目标；价格/范围变化可复核兼容结构、目标重估，源计数不池化。BIC不是后验；自由程序仅 + - * min/max/sigmoid、1..8参数[-6,6]，本体冻结。fit_pool/propose_model需已收到核实目标数据；零样本可用initial_candidate_id采样。sample先冻结完整计划后排队，collect的repair/refit/assess按实际回执执行。确认固定两个新n=800 cohort，最多六项CP(alpha=.05/6,5pp容差)；低功效未决，未启动失败不反驳机制。实际contradicted才reopen_research，最多两次；已见数据不能认证自身新解释。经营目标为每顾客利润。避免重复诊断/资料耗尽确认额度：已有拟合候选时优先新确认，再由反馈决定补资料、修订、再确认或停止。保留至少3次请求机会、1600新会话和2cohort的建议是预算指引，不限制科学动作。未决finish必须unresolved:true；范围内支持不代表所有组合或心理机制。"


SYSTEM=SYSTEM.replace("16项科学服务","18项科学服务")+"可选择sample_and_analyze减少采样/收取/拟合往返，confirm_and_analyze减少确认/收取/分析往返；内部每一步均按真实预算计数，结果不自动触发下一实验、修订或停止。"
SYSTEM=SYSTEM.replace("18项科学服务","19项科学服务")+"public_evidence_store保留原检查条件、区间与依赖，释放训练不擦除原反驳。review_candidate_evidence只回顾诊断，不认证新解释。"


def decode_actions(raw,config):
    if raw["choices"][0].get("finish_reason")=="length":raise ValueError("truncated output")
    calls=raw["choices"][0]["message"].get("tool_calls") or []
    if calls:
        if not 1<=len(calls)<=3:raise ValueError("submit 1..3 real function calls")
        actions=[]
        for c in calls:
            if c.get("type")!="function" or c.get("function",{}).get("name")!="submit_research_action" or not isinstance(c.get("id"),str) or not c["id"]:raise ValueError("wrong function submission envelope")
            action=json.loads(c["function"]["arguments"])
            actions.append(action)
        if len({c["id"] for c in calls})!=len(calls):raise ValueError("duplicate function call identity")
    else:actions=[decode_submission(raw,config,"submit_research_action")]
    required={"tool","args","rationale","expected_gap"}
    for index,a in enumerate(actions):
        if not isinstance(a,dict):raise ValueError(f"action[{index}]: required fields must form an object")
        if set(a)!=required:raise ValueError(f"action[{index}]: required fields missing={sorted(required-set(a))}, unexpected={sorted(set(a)-required)}; outer rationale is separate from args.rationale")
        if not isinstance(a["args"],dict) or any(not isinstance(a[k],str) or not a[k].strip() for k in ("tool","rationale","expected_gap")):raise ValueError(f"action[{index}]: args must be an object; outer tool/rationale/expected_gap must be nonempty strings")
        try:validate_action_args(a["tool"],a["args"])
        except ValueError as error:raise ValueError(f"action[{index}]: {error}") from error
    if any(a["tool"]=="finish" for a in actions[:-1]):raise ValueError("finish must be the last action")
    if any(a["tool"]=="dispatch_research_context" for a in actions[:-1]):raise ValueError("context dispatch must be the last action")
    return actions


def compact_feedback(feedback):
    value=copy.deepcopy(feedback)
    if not value.get("ok"):return value
    result=value["result"]
    if isinstance(result,dict) and "research_state" in result:
        result={k:result[k] for k in ("training_evidence_ids","fit","analysis","bundle_trace","submitted") if k in result}
        if "analysis" in result:result["analysis"]={"completed_checks":[{"check_id":c["check_id"],"candidate_id":c["candidate_id"],"state":c["result"]["state"],"interval":c["result"]["exact_probability_interval"]} for c in result["analysis"]["completed_checks"]],"unavailable_checks":result["analysis"]["unavailable_checks"]}
    elif isinstance(result,dict) and "completed_checks" in result:
        result={"completed_checks":[{"check_id":c["check_id"],"candidate_id":c["candidate_id"],"state":c["result"]["state"],
            "n":c["result"]["n"],"interval":c["result"]["exact_probability_interval"],"experiment_ids":c["result"]["experiment_ids"]} for c in result["completed_checks"]],"unavailable_checks":result["unavailable_checks"]}
    elif isinstance(result,dict) and "episodes" in result:
        result={"archive_id":result["archive_id"],"source_cost_shared":result["source_cost_shared"],"episodes":[{
            "episode_id":e["episode_id"],"source_state":e["source_state"],"scope_flags":e["scope_flags"],"source_price":e["source_context"]["operating_objective"]["retail_price"],
            "template_expression":None if e["template"] is None else e["template"]["expression"],"condition_count":len(e["conditional_claims"]),"usage":e["usage"]} for e in result["episodes"]],
            "projection":"All source IDs retained without ranking; read_memory returns one source's entire claim list and structural template."}
    elif isinstance(result,dict) and "episode_id" in result and "conditional_claims" in result:
        result={k:result[k] for k in ("episode_id","public_context","physical_definitions","source_state","conditional_claims","template","template_error","source_cost","untested_scope_state","transfer_contract")}
        result["projection"]="Entire conditional claim list retained; raw source cohorts and duplicated version lineage omitted from API view, archived in runtime feedback. Source counts cannot enter target fitting."
    elif isinstance(result,dict) and "physical_facts" in result:
        result={"initial_candidate_id":result["initial_candidate_id"],"catalog_received":True,"sites":result["sites"],"note":"商品实物映射已在当前状态，未提供购买效应。"}
    def remove_repeated_roles(obj):
        if isinstance(obj,list):return [remove_repeated_roles(x) for x in obj]
        if not isinstance(obj,dict):return obj
        return {k:remove_repeated_roles(v) for k,v in obj.items() if k not in {"role_patterns","physical_definitions"}}
    return {"ok":True,"result":remove_repeated_roles(result)}


def refer_current_candidates(feedback,state):
    """Replace only identical immutable summaries already in current state."""
    current={c["candidate_id"]:c for c in state["candidates"]}
    def visit(value):
        if isinstance(value,list):return [visit(x) for x in value]
        if not isinstance(value,dict):return value
        cid=value.get("candidate_id");c=current.get(cid)
        if c is not None and "model" in value:
            projected={k:v for k,v in value.items() if k!="model"}|{"expression":value["model"]["expression"]}
            if projected==c:return {"candidate_id":cid,"current_state_reference":"research_state.candidates; identical immutable summary"}
        return {k:visit(v) for k,v in value.items()}
    return visit(copy.deepcopy(feedback))


class ScienceActor:
    def __init__(self,rt,view_factory,schema,limits,wire_mode="wrapper",state_aware=False,use_state_brief=False,use_reference_contract=False,use_confirmation_phase=False):
        self.rt=rt;self.view_factory=view_factory;self.schema=schema;self.limits=limits
        self.history=[];self.last_protocol_error=None;self.last_preflight=None;self.wire_mode=wire_mode
        if wire_mode not in {"wrapper","native"}:raise ValueError("unknown scientific wire protocol")
        self.state_aware=state_aware;self.notebook=ResearchNotebook();self.use_state_brief=use_state_brief
        if use_state_brief and not state_aware:raise ValueError("state brief requires the public state-aware actor")
        self.use_reference_contract=use_reference_contract
        if use_reference_contract and (not state_aware or wire_mode!="native"):raise ValueError("reference contract requires a state-aware native actor")
        self.use_confirmation_phase=use_confirmation_phase
        if use_confirmation_phase and not state_aware:raise ValueError("confirmation phases require the public state-aware actor")

    def next(self,records):
        state=self.view_factory(self.rt);state["last_feedback"]=compact_feedback(state["last_feedback"]) if state["last_feedback"] else None
        if self.history:state["last_feedback"]={"reference":"逐调用反馈见最近 assistant/tool 消息。"}
        state.pop("physical_role_patterns",None)
        state["expression_variables"]={"heating":"heat","utensils":"utensils","external_heating":"external_heat","external_utensils":"external_utensils","item_count":"items",**{k:k for k in self.rt.facts["role_patterns"] if k not in {"heating","utensils"}}}
        state["catalogs"]={stage:[{k:p[k] for k in ("id","description","functions","retailer_cost_per_session") if k in p} for p in rows] for stage,rows in state["catalogs"].items()}
        state["executed_scientific_tools"]={}
        for e in self.rt.events:
            if e["kind"]=="scientific_tool_response" and e["payload"]["feedback"]["ok"]:
                name=e["payload"]["request"]["tool"];state["executed_scientific_tools"][name]=state["executed_scientific_tools"].get(name,0)+1
        state["last_protocol_error"]=self.last_protocol_error
        usage=usage_summary(records)
        if self.state_aware:
            state["action_preconditions"]=readiness(state);state["reading_notebook"]=self.notebook.view()
            state["research_gaps"]={"target_training_sessions":sum(r["n"] for r in state["verified_condition_table"] if r["experiment_id"] in state["training_evidence_ids"]),
                "independent_checks_completed":sum(c["result"] is not None for c in self.rt.checks),
                "scope_limits":"候选拟合不认证；源资料已读对象有稳定引用，不能替代新目标测量和独立确认。"}
        if self.use_state_brief:
            from state_brief import state_brief
            state["workflow_brief"]=state_brief(state)
        if self.use_confirmation_phase:
            from confirmation_phase import from_events
            state["confirmation_status"]=from_events(self.rt.events,state["clock"])
        state["api_resource_review"]={"calls_left":self.limits["calls"]-usage["api_calls"],"reported_tokens_left":self.limits["reported_tokens"]-usage["total_tokens"],
            "confirmation_checks_completed":sum(c["result"] is not None for c in self.rt.checks),
            "confirmation_reserve_advisory":{"api_call_opportunities":3,"fresh_sessions":1600,"fresh_cohorts":2,"mandatory_action_restriction":False},
            "advice":"已有拟合候选时，优先保留新确认、收取/分析和条件停止的额度；不要把预算耗在重复资料或重复拟合。真实反驳可重新研究，低功效保持未决。所有科学动作仍可选。"}
        public={k:self.rt.initial[k] for k in ("task","target","history","history_note","operating_objective","temporal_contract","terminal_receipt_contract")}
        if "discovery_tasks" in state:public["discovery_task_contract"]=copy.deepcopy(self.rt.initial["discovery_task_contract"])
        tools={k:v.split("；",1)[-1] for k,v in TOOLS.items() if "discovery_tasks" in state or k not in {"start_discovery_task","advance_discovery_task"}}
        context={"actor_protocol":VERSION,"context_encoding":CONTEXT_VERSION,"encoding_note":NOTE,"task_contract":public,"scientific_tools":tools,"research_state":state,
            "api_limits":self.limits,"api_usage":usage}
        recent=[copy.deepcopy(m) for turn in self.history[-2:] for m in turn]
        for message in recent:
            if message["role"]=="tool":
                value=unpack(json.loads(message["content"]))
                message["content"]=compact_json(assert_roundtrip(refer_current_candidates(value,state)))
        system=SYSTEM
        if self.wire_mode=="native":
            context.pop("scientific_tools")
            system="你是固定价格库存机制研究协调器，只见公开事实与已收到证据。直接调用18个具名科学函数，不使用submit_research_action、不嵌套tool/args。函数参数平铺，rationale与expected_gap各写一次约40字。每响应1..3个真实函数调用，依赖未知结果的动作另次提交，finish最后；ID保留原类型。选择诊断、读目录/记忆、结构复核、采样、拟合、自由解释、确认、反驳后重新研究或停止；没有固定科学顺序。优先sample_and_analyze/confirm_and_analyze减少往返，它们不会自动修订或停止。零样本可用initial_candidate_id采样；需要adaptation时在首次采样前open_adaptation。fit_pool/propose_model需要已收到核实目标数据；表达式必须是算术字符串，如sigmoid(b+g*heat)只示范语法，不保证正确，参数必须是[初值,下界,上界]数组，1..8个、界限[-6,6]；不要把_ast的展示编码当表达式字符串。商品功能不证明购买效应，源结构复核后目标重估，源计数/支持不继承；BIC非后验。确认固定两个新n=800 cohort、最多六项、总alpha=.05、5pp容差；实际contradicted才重新研究最多两次，已见数据不能认证自身解释，低功效未决。所有角色共用预算，已有拟合候选时优先预留独立确认/分析/停止额度。未决finish需unresolved:true；未测范围和心理中介未决。经营目标每顾客利润，私有评分不可见。"
        messages=[{"role":"system","content":system}]+recent+[{"role":"user","content":compact_json(assert_roundtrip(context))}]
        if self.state_aware:messages[0]["content"]+="函数目录已按真实公开前置条件筛选，research_gaps与reading_notebook保存进度；已经读过同版本资料不会带来新目标数据。若已有拟合候选却无独立检查，优先新确认；收到真实反驳再决定修订或补区分数据。未决可停，不要求用完预算。"
        if self.use_state_brief:messages[0]["content"]+="workflow_brief列出公开待办、已收到分析引用和资源，不是科学答案或固定顺序；多项待办可以并存，执行失败、未核实计数、实际反驳分开处理。"
        if self.use_confirmation_phase:messages[0]["content"]+="confirmation_status分别表示回执/核验、独立分析和训练权限。ready_to_assess说明该原冻结检查两份回执已核实，可用assess_checks或collect(assess:true)分析；protected_from_fitting仅禁止用于拟合，不阻止独立分析。assessed保留原条件结果，只有真实反驳且明确释放才能用于后续训练；投影不执行分析、不创建支持、不要求固定科学顺序。"
        if "discovery_tasks" in state:messages[0]["content"]+="可用有限发现任务start_discovery_task：明确objective并选择已登记候选、1..3条件，worker沿用现有公开frontier设计、冻结整批、执行核验，全部收到才共同拟合并留下版本化artifact。3科学动作及所有真实网关/样本照常收费，不带来独立支持。需要修复/未决任务用advance_discovery_task，不猜未收到task_id；completed只表示该批产物齐全，仍须独立确认和范围判断。你也可选择原细粒度工具，不要求固定科学顺序或用完预算。"
        if "public_evidence_store" in state:messages[0]["content"]=messages[0]["content"].replace("18个具名科学函数","19个具名科学函数")+"public_evidence_store保留所有已分析检查的固定条件、区间、原候选及训练/信息依赖；释放训练不改写原反驳。review_candidate_evidence是旧结果上的回顾诊断，无独立支持；新解释仍需新确认，未测范围始终未决。"
        if "research_organization" in state:
            org=state["research_organization"]
            messages[0]["content"]+="本任务另有两个共同组织服务，收费1科学动作，共用原预算。你当前上下文="+org["current_context_id"]+"，职责="+org["current_role_objective"]+"。dispatch_research_context选择下一个已有上下文，C可expand创建子节点，须最后调用，新ID下一响应才可使用。append_research_note保存可复查批评/任务依据，只是模型评价，不是科学证据。所有上下文可调用同一科学工具，待收实验不阻止在其他上下文处理已有公开资料；不读未来计数、不重置环境。"
        payload={"model":CONFIG["model"],"messages":messages,"temperature":0,"max_tokens":self.limits["max_output_tokens"],
            "parallel_tool_calls":False,**CONFIG.get("generation_options",{})}
        if self.wire_mode=="native":
            definitions=function_definitions(state if self.state_aware else None,reference_contract=self.use_reference_contract)
            if "research_organization" not in state:definitions=[d for d in definitions if d["function"]["name"] not in {"dispatch_research_context","append_research_note"}]
            payload.update(tools=definitions,tool_choice="auto")
            if CONFIG.get("plain_json_fallback",False):payload["messages"][0]["content"]+="若接口只能返回content，兼容输出必须是完整JSON对象，恰好tool与arguments两个字段，arguments为对应具名函数的平铺参数；不写Markdown或长报告。"
        else:payload=structured_request(payload,CONFIG,"submit_research_action",self.schema)
        preflight=len(json.dumps(payload,ensure_ascii=False).encode())+self.limits["max_output_tokens"]
        from model_admission import estimate
        admission=estimate(payload,records,self.limits.get("admission_policy","serialized_bytes"))
        self.last_preflight={"next_request_byte_plus_output_bound":preflight,"reported_usage":usage,"calls_left":self.limits["calls"]-usage["api_calls"],
            "tokens_left":self.limits["reported_tokens"]-usage["total_tokens"],"context_encoding":CONTEXT_VERSION,"admission_estimate":admission,
            "basis":"Admission estimate is separate from measured provider usage; no verified provider tokenizer."}
        if usage["api_calls"]>=self.limits["calls"] or usage["calls_without_reported_usage"] or usage["total_tokens"]+admission["estimated_tokens"]>self.limits["reported_tokens"]:return None
        event_count=len(self.rt.events)
        from temporal_lab import digest
        gateway_count=len(self.rt.gateway.events);gateway_prefix=digest(self.rt.gateway.events)
        record=request_model(CONFIG,payload);record.update(actor_protocol=VERSION,clock=self.rt.gateway.clock,public_training_ids=sorted(self.rt.training_ids),preflight_byte_plus_output_bound=preflight,
            public_research_event_count=event_count,public_research_prefix_hash=self.rt.events[-1]["event_hash"] if event_count else None)
        record["public_gateway_event_count"]=gateway_count
        record["public_gateway_prefix_sha256"]=gateway_prefix
        record["state_aware"] = self.state_aware
        record["admission_estimate"]=admission
        if self.wire_mode=="native":
            from native_science_protocol import VERSION as NATIVE_VERSION
            record["native_protocol_version"]=NATIVE_VERSION
        if self.use_state_brief:record["state_brief_version"]=state["workflow_brief"]["version"]
        if self.use_confirmation_phase:record["confirmation_phase_version"]=state["confirmation_status"]["version"]
        if self.use_reference_contract:
            from reference_contract import VERSION as REFERENCE_VERSION
            record["reference_contract_version"]=REFERENCE_VERSION
        if "research_organization" in state:record["organization_context_id"]=state["research_organization"]["current_context_id"]
        if self.state_aware:record["notebook_before_request"]=self.notebook.snapshot()
        feedbacks=[];reviews=[]
        try:
            if "response" not in record:raise ValueError("no decoded API response")
            actions=decode_native(record["response"],CONFIG) if self.wire_mode=="native" else decode_actions(record["response"],CONFIG)
            charged=sum(action_charge(a,state) for a in actions)
            reserve=0 if actions[-1]["tool"]=="finish" else 1
            if self.rt.calls+charged+reserve>self.rt.max_calls:raise ValueError("scientific batch exceeds remaining action allocation including terminal finish")
            record["actions"]=copy.deepcopy(actions)
            for a in actions:
                if self.state_aware:
                    before_state=self.view_factory(self.rt)
                    try:
                        if self.use_reference_contract:
                            from reference_contract import validate_action as validate_references
                            validate_references(a,state);validate_references(a,before_state)
                        validate_request_bindings(a,state);validate_ready_action(a,before_state)
                        reviews.append({"action":copy.deepcopy(a),"state":before_state,"accepted":True,"research_event_count":len(self.rt.events)})
                    except ValueError as error:
                        reviews.append({"action":copy.deepcopy(a),"state":before_state,"accepted":False,"error":str(error),"research_event_count":len(self.rt.events)})
                        feedback={"ok":False,"error":str(error),"executed":False,"public_precondition_rejected":True,"valid_new_scientific_evidence":False};feedbacks.append(feedback);continue
                feedback=self.rt.call(a["tool"],a["args"],a["rationale"],a["expected_gap"]);feedbacks.append(feedback)
                if self.state_aware:self.notebook.observe(a,feedback,self.rt.gateway.clock)
            record["tool_feedbacks"]=feedbacks;record["submission_transport"]=("native_" if self.wire_mode=="native" else "")+("function_call_batch" if len(actions)>1 else "function_call" if record["response"]["choices"][0]["message"].get("tool_calls") else "plain_json_content")
            if self.state_aware:record["public_precondition_reviews"]=reviews
            self.last_protocol_error=None
        except (ValueError,KeyError,TypeError,SyntaxError) as error:
            self.last_protocol_error=str(error);record["submission_error"]=str(error)
        if "response" in record:
            message=record["response"].get("choices",[{}])[0].get("message",{})
            calls=message.get("tool_calls") or []
            if calls and all(isinstance(c,dict) and isinstance(c.get("id"),str) and c["id"] and c.get("type")=="function" and isinstance(c.get("function"),dict) for c in calls):
                turn=[{"role":"assistant","content":message.get("content") or "","tool_calls":[{k:c[k] for k in ("id","type","function")} for c in calls]}]
                for i,c in enumerate(calls):
                    feedback=feedbacks[i] if i<len(feedbacks) else {"ok":False,"error":self.last_protocol_error,"executed":False}
                    turn.append({"role":"tool","tool_call_id":c["id"],"content":compact_json(assert_roundtrip(compact_feedback(feedback)))})
            else:
                turn=[{"role":"assistant","content":message.get("content") or ""},{"role":"user","content":compact_json(assert_roundtrip({"tool_feedback":compact_feedback(feedbacks[0]) if feedbacks else {"ok":False,"error":self.last_protocol_error}}))}]
            self.history.append(turn)
        return record
