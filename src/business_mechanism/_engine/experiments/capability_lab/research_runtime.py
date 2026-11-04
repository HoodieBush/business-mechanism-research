"""Public scientific actions and immutable research objects, independent of policy.

The runtime has no generator/scorer import. A supplied public gateway executes
plans; policies may select data diagnosis, memory review, arbitrary safe model
proposals, sampling, confirmation, revision, waiting and scoped stopping.
"""
from __future__ import annotations
import copy
import math
import time

from conditional_memory import ConditionalMemory,context
from confirmation import assess
from lab import predict,validate_model
from mechanism_state import card
from model_order import candidate_key
from numeric_pool import numeric_pool
from public_evidence import PublicEvidenceStore,retrospective_review
from research_organization import ResearchOrganization
from semantic_compile import compile_structured
from symbolic import plan
from temporal_lab import digest
from temporal_plan import register_plan

VERSION="research-runtime-v0.9-optional-discovery-tasks"
TOOLS={
    "diagnose_history":"{}；核对历史供给和原始计数，只做数据诊断，不作为随机训练样本。",
    "open_adaptation":"{}；首次打开必须早于采样以冻结实物角色；已经收到的目录可重复读取，不改变模型/本体，不返回购买结果。",
    "retrieve_memory":"{}；返回全部公开档案的条件、结构、来源依赖和范围变化。",
    "read_memory":"{episode_id}；读取一条完整公共源档案。",
    "review_memory":"{episode_ids:[ID],usage:'structure_refit_only',rationale}；允许兼容本体下范围改变的结构候选，源参数/计数/认证均不继承。",
    "fit_pool":"{}；必须已有收到且核实的目标训练证据；共同公开完整字典搜索与已复核源结构重估，拟合不是独立支持。",
    "propose_model":"{expression:受限程序字符串,parameters:参数->[初值,下界,上界],rationale}；只拟合当前已释放目标数据，本体不改。",
    "read_candidate":"{candidate_id}；读取不可变候选版本、训练引用和诊断。",
    "review_candidate_evidence":"{candidate_id}；在完整已分析条件上回放候选预测，保留负例/区间/训练信息依赖；仅回顾诊断，不是独立支持或后验排名。",
    "dispatch_research_context":"{kind:'select'|'expand',target_id,objective,analysis_ids,candidate_id可选,branch_kind仅C扩展必需}；选择已有研究上下文，C可创建有父节点的安全计算分支；不新建环境/预算，必须为本响应最后动作。",
    "append_research_note":"{kind,text,analysis_ids,candidate_id可选}；保存有来源的模型审查/任务笔记，不改科学状态，不创造证据或独立支持。",
    "suggest_design":"{candidate_id}；返回公开候选分歧/特征覆盖建议，协调器可自行选择其他合法配置。",
    "sample":"{candidate_id,designs:[{stage,site,assortment,n}],rationale}；stage 为 source/adaptation 字符串，source 仅 site='00'，已打开 adaptation 可用 '00','01','10','11'；n 整数100..800；assortment 为该目录 ID 列表。1..3项新发现cohort，先冻结计划后排队。",
    "sample_frontier":"{candidate_id,count:1..3,rationale}；共同数值服务连续选不同公开条件并冻结模型；没有待测结果。",
    "collect":"{until:'next'|'all',repair:布尔,refit:布尔,assess:布尔}；等待/按实际回执修复，可组合已收到证据分析；所有子调用计费并记录。",
    "repair":"{job_id,kind:'execution'|'meter'}；同计划重试或延迟原始计数核对，无失败样本/新独立 cohort。",
    "confirm":"{candidate_id,design:{stage,site,assortment}可选,rationale}；登记一项固定条件检查的两个 n=800 新 cohort，全任务最多六项，alpha=.05/6，5pp 容差。",
    "assess_checks":"{}；仅对两个 cohort 都收到且核实的检查计算 CP；重复分析返回缓存，不增加检查数。",
    "reopen_research":"{check_id,rationale,refit:布尔}；实际已反驳检查才允许释放已完成确认用于后续拟合，最多两次；旧检查不得认证自身修订模型。",
    "finish":"{candidate_id,claims,unresolved:布尔,stop_reason}；停止是合法选择，已完成条件状态与未测范围分开，未决必需如实声明。",
    "sample_and_analyze":"{candidate_id,designs:[{stage,site,assortment,n}],rationale,repair:布尔}；自选采样后 collect(until=all,refit=true,assess=false)；组合服务和每个内部科学动作均计数，返回已收到目标拟合，未成熟不拟合。",
    "confirm_and_analyze":"{candidate_id,design可选,rationale,repair:布尔}；对已选候选冻结确认后 collect(until=all,refit=false,assess=true)，不自动修订/继承支持/停止；组合与内部动作都计数。",
    "start_discovery_task":"{candidate_id,count:1..3,objective,rationale,repair:布尔}；登记有限发现任务，现有公开frontier方法冻结整批设计，原执行worker收取/核验，全部核实才共同拟合并保存产物；3科学动作，所有网关照常收费；拟合不认证。",
    "advance_discovery_task":"{task_id,rationale,repair:布尔}；仅推进该任务原job回执及全部核实后的共同拟合，2科学动作；已完成返回原产物且只收1动作，不生成新计划/重置预算。"}


class ResearchRuntime:
    def __init__(self,gateway,public_archive=None,terminal_policy="received_only",organization_mode=None,use_discovery_tasks=False):
        from terminal_receipts import POLICIES
        if terminal_policy not in POLICIES:raise ValueError("unknown terminal receipt policy")
        self.gateway=gateway;self.initial=gateway.public();self.facts=compile_structured(gateway.public_catalog("source"))
        self.discovery_tasks=None
        if use_discovery_tasks:
            from discovery_tasks import DiscoveryTasks,CONTRACT
            self.discovery_tasks=DiscoveryTasks();self.initial["discovery_task_contract"]=copy.deepcopy(CONTRACT)
        self.initial["terminal_receipt_contract"]={"policy":terminal_policy,"decision_model_frozen_before_settlement":True,"max_settlement_steps":100,
            "no_new_designs_hypotheses_or_parameter_fit":True,"retry_existing_execution_attempts_max":2,"gateway_calls_reserved_for_finish_and_deployment":2,
            "settlement_scientific_action_charge":1 if terminal_policy=="settle_committed" else 0,"missing_at_deadline":"unresolved"}
        self.events=[];self.objects={"problems":[],"evidence":[],"candidates":[],"plans":[],"checks":[]}
        self.calls=0;self.max_calls=64;self.revisions=0;self.training_ids=set();self.jobs={};self.checks=[];self.versions=[]
        self.pool=[];self.registry={};self._fit_key=None;self.memory=None;self.memory_archive=copy.deepcopy(public_archive)
        self.memory_reviews=[];self.memory_retrieved=False;self.closed=False;self.final=None;self.last_feedback=None
        self.public_evidence=PublicEvidenceStore()
        self.organization=None if organization_mode is None else ResearchOrganization(organization_mode)
        if self.organization is not None:self.initial["research_organization_contract"]=self.organization.contract()
        self._evidence_keys=set();self._new_problem("initial_record_quality","unclassified",[],"核对销量、实际供给和计数；随后识别可执行关系及范围。")
        self.terminal_policy=terminal_policy;self.decisions_closed=False;self.terminal_commitment=None;self.terminal_settlement=None
        self.initial_candidate=self._candidate({"model":{"role_patterns":self.facts["role_patterns"],"expression":.3},
            "terms":[],"rank":0,"bic":0.,"deviance":None,"origin":"public_initial_constant"},[])

    def _event(self,kind,payload):
        body={"sequence":len(self.events),"kind":kind,"available_at":self.gateway.clock,"payload":copy.deepcopy(payload),
            "previous_hash":self.events[-1]["event_hash"] if self.events else None}
        event=body|{"event_hash":digest(body)};self.events.append(event);self.public_evidence.observe(event)
        if self.organization is not None:self.organization.observe(event)
        return copy.deepcopy(event)

    def _new_problem(self,trigger,issue_class,refs,objective):
        p={"problem_id":f"P{sum(p.get('version',0)==0 for p in self.objects['problems']):04d}","version":0,"model_version":None,"data_version":digest(sorted(self.training_ids)),
            "scope":"公开 source/adaptation 固定价格研究任务","trigger":trigger,"observation_contract_id":digest(self.initial["temporal_contract"]),
            "evidence_refs":list(refs),"issue_class":issue_class,"research_objective":objective,"candidate_actions":list(TOOLS),
            "budget":copy.deepcopy(self.gateway.limits),"status":"open"}
        self.objects["problems"].append(p);self._event("problem_created",p);return p

    def _problem_update(self,pid,status,issue_class,refs):
        old=next(p for p in reversed(self.objects["problems"]) if p["problem_id"]==pid)
        new=copy.deepcopy(old);new.update(version=old["version"]+1,parent_hash=digest(old),status=status,issue_class=issue_class,
            evidence_refs=sorted(set(old["evidence_refs"])|set(refs)),data_version=digest(sorted(self.training_ids)))
        self.objects["problems"].append(new);self._event("problem_updated",new)

    def _candidate(self,row,training_ids,parent=None,fit_args=None):
        information=set(row.get("information_evidence_ids",[]))
        if row["origin"]=="policy_proposal":information|={r["experiment_id"] for r in self.gateway.public_state()["mature_evidence"] if r["verified_supply"] and r["verified_meter"]}
        if row["origin"]=="conditional_memory":
            refs=set(row.get("memory_episode_refs",[]))
            information|={i for review in self.memory_reviews if refs&set(review["episode_ids"]) for i in review.get("target_exposure_ids",[])}
        item={**copy.deepcopy(row),"training_evidence_ids":sorted(training_ids),"available_at":self.gateway.clock,
            "information_evidence_ids":sorted(information),"parent_candidate_id":parent,"physical_definitions":copy.deepcopy(self.facts["ontology"]),"fit_args":copy.deepcopy(fit_args)}
        key=digest(item)
        for old in self.registry.values():
            if old["content_hash"]==key:return old["candidate_id"]
        cid=f"C{len(self.registry):04d}";item.update(candidate_id=cid,content_hash=key)
        self.registry[cid]=item;self.objects["candidates"].append(copy.deepcopy(item));self._event("candidate_registered",item)
        return cid

    def _memory(self):
        if self.memory_archive is None:raise ValueError("no public memory archive provided")
        if self.memory is None:
            self.memory=ConditionalMemory(self.memory_archive,self.gateway.public(),self.facts,"unscoped")
            for entry in self.memory.entries:
                entry["eligible"]=False;entry["retrieval"]["status"]="requires_explicit_scope_review"
        return self.memory

    def _scope(self):
        if self.gateway.public_state()["training_scope"]!=sorted(self.training_ids):self.gateway.set_fit_scope(sorted(self.training_ids))

    def _sync(self):
        rows=self.gateway.public_state()["mature_evidence"]
        for r in rows:
            j=self.jobs.get(r["job_id"])
            if j and j["purpose"]=="discovery" and r["verified_supply"] and r["verified_meter"]:self.training_ids.add(r["experiment_id"])
            key=(r["experiment_id"],r["evidence_version"])
            if key in self._evidence_keys:continue
            payload={"evidence_id":digest(r),"source_type":"experimental_measurement","query":{"job_id":r["job_id"]},
                "data_version":r["evidence_version"],"occurred_at":r["occurred_at"],"available_at":r["available_at"],
                "processing_version":VERSION,"scope":{k:r[k] for k in ("stage","site","assortment")},
                "independence_group":r["independence_group"],"validity":"verified" if r["verified_supply"] and r["verified_meter"] else "unverified", "measurement":copy.deepcopy(r)}
            self.objects["evidence"].append(payload);self._evidence_keys.add(key);self._event("evidence_received",payload)
            if not r["verified_meter"]:self._new_problem("unverified_measurement","data_quality",[payload["evidence_id"]],"取得原始计数；核验前不用于科学拟合或反证。")
        self._scope()

    def _fit(self):
        self._sync()
        if not self.training_ids:raise ValueError("no verified released target evidence")
        key=digest({"training":[(r["experiment_id"],r["evidence_version"],k) for r,k in self.gateway.verified_observations()],
            "facts":self.facts["role_patterns"],"memory_reviews":self.memory_reviews})
        if key!=self._fit_key:
            start=time.monotonic();rows=numeric_pool(self.gateway,self.facts["role_patterns"],True)
            if self.memory is not None:rows+=self.memory.fit_candidates(self.gateway)
            # Every safe freely proposed expression is re-estimated through the
            # same target-only service on later released evidence.
            proposals={digest(c["fit_args"]):c for c in self.registry.values() if c.get("fit_args") and c["origin"]=="policy_proposal"}
            for c in proposals.values():
                f=self.gateway.call("fit_candidate",c["fit_args"]);rank=len(c["fit_args"]["parameters"])
                rows.append(self._fit_row(f,rank,"policy_proposal",c["fit_args"]["expression"])|{"fit_args":c["fit_args"],"parent_candidate_id":c["candidate_id"],"information_evidence_ids":c.get("information_evidence_ids",[])})
            rows.sort(key=candidate_key);self.pool=[]
            for row in rows[:48]:
                cid=self._candidate(row,self.training_ids,row.get("parent_candidate_id"),row.get("fit_args"));self.pool.append(cid)
            self._fit_key=key;self._event("public_pool_fitted",{"training_evidence_ids":sorted(self.training_ids),"candidate_ids":self.pool.copy(),"cpu_wall_seconds":time.monotonic()-start})
        return {"training_evidence_ids":sorted(self.training_ids),"candidates":[self._summary(c) for c in self.pool[:6]],
            "interpretation":"有限 beam 的公开字典/自由程序/记忆结构共同排序；BIC 不是校准后验，拟合不是独立确认。"}

    def _fit_row(self,f,rank,origin,term):
        n=sum(r["n"] for r,_ in self.gateway.verified_observations())
        return {"model":f["model"],"terms":[term],"rank":rank,"bic":f["binomial_deviance"]+rank*math.log(n),
            "deviance":f["binomial_deviance"],"max_residual":max(abs(r["standardized_residual"]) for r in f["residuals"]),
            "optimizer_success":f["optimizer_success"],"origin":origin}

    def _summary(self,cid):
        c=self.registry[cid]
        return {k:copy.deepcopy(c[k]) for k in ("candidate_id","model","terms","rank","bic","deviance","origin","training_evidence_ids","information_evidence_ids","memory_episode_refs") if k in c}

    def _selection_pool(self,cid):
        if cid not in self.registry:raise ValueError("unknown immutable candidate")
        selected=self.registry[cid];ids=[cid]+[x for x in self.pool if x!=cid]
        # Re-centre design competition around a caller-selected hypothesis,
        # without altering any fitted BIC or assigning scientific certification.
        rows=[copy.deepcopy(self.registry[x]) for x in ids]
        if selected["origin"]=="public_initial_constant":rows[0]["bic"]=min([r["bic"] for r in rows]+[0.])
        return rows

    def _submit(self,cid,design,purpose,reason,check_id=None):
        model=self.registry[cid]["model"]
        action={**copy.deepcopy(design),"verified_supply":True,"verified_meter":True,"prediction":0.,"rationale":reason}
        registered=register_plan(self.gateway,model,action,cid,purpose)
        self.gateway._validate_plan(registered)
        response=self.gateway.call("submit_experiment",{"plan":registered});j=response["job_id"]
        item={"job_id":j,"candidate_id":cid,"purpose":purpose,"check_id":check_id,"plan_id":response["plan_id"],
            "registered_at":self.gateway.clock,"plan":registered,"training_evidence_ids":self.registry[cid]["training_evidence_ids"].copy()}
        self.jobs[j]=item;self.objects["plans"].append(copy.deepcopy(item));self._event("registered_plan_linked",item)
        return response

    def _validate_sampling_batch(self,cid,designs,reason):
        if not isinstance(designs,list) or not 1<=len(designs)<=3:raise ValueError("submit 1..3 discovery designs")
        if cid not in self.registry:raise ValueError("unknown candidate")
        for d in designs:
            if not isinstance(d,dict) or set(d)!={"stage","site","assortment","n"}:raise ValueError("exact design fields required")
            a={**copy.deepcopy(d),"verified_supply":True,"verified_meter":True,"prediction":0.,"rationale":reason}
            self.gateway._validate_plan(register_plan(self.gateway,self.registry[cid]["model"],a,cid))
        state=self.gateway.public_state();pending=sum(j["status"]=="pending" for j in state["pending_jobs"])
        if pending+len(designs)>self.gateway.max_pending:raise ValueError("insufficient pending capacity for batch")
        used=self.gateway.used
        if used["sessions"]+sum(d["n"] for d in designs)>self.gateway.limits["sessions"] or used["arms"]+len(designs)>self.gateway.limits["arms"] or used["cost"]+sum(5+len(d["assortment"]) for d in designs)>self.gateway.limits["cost"]:raise ValueError("insufficient common allocation for batch")
    def _sample(self,cid,designs,reason):
        self._validate_sampling_batch(cid,designs,reason)
        return {"submitted":[self._submit(cid,d,"discovery",reason) for d in designs]}

    def _frontier_designs(self,cid,count):
        class PendingDesignView:
            def __init__(view,gateway):
                view.used=gateway.used.copy();view.limits=gateway.limits;view.transfer_open=gateway.transfer_open
                view.public_catalog=gateway.public_catalog;view.rows=gateway.observed_cohorts()
            def observed_cohorts(view):return copy.deepcopy(view.rows)
        view=PendingDesignView(self.gateway);designs=[]
        for _ in range(count):
            action=plan(view,self._selection_pool(cid),novelty=True)
            if action is None:raise ValueError("no feasible public design")
            d={k:action[k] for k in ("stage","site","assortment","n")};designs.append(d);view.rows.append(d|{"pending":True})
            view.used["cost"]+=5+len(d["assortment"])
        return designs

    def _assess(self):
        rows={r["job_id"]:r for r in self.gateway.public_state()["mature_evidence"]};out=[]
        for c in self.checks:
            if c.get("result") is not None:out.append(copy.deepcopy(c));continue
            if len(c["job_ids"])!=2 or any(j not in rows or not rows[j]["verified_supply"] or not rows[j]["verified_meter"] for j in c["job_ids"]):continue
            cohort=[copy.deepcopy(rows[j]) for j in c["job_ids"]];prediction=cohort[0]["frozen_prediction"]
            result=assess(sum(r["observed_sales"] for r in cohort),1600,prediction,max_checks=6)
            result.update(round=c["check_index"],experiment_id=cohort[0]["experiment_id"],experiment_ids=[r["experiment_id"] for r in cohort],
                cohort_results=cohort,design=copy.deepcopy(self.jobs[c["job_ids"][0]]["plan"]["action"]),available_at=self.gateway.clock)
            c["result"]=result;self.objects["checks"].append(copy.deepcopy(c));self._event("independent_check_assessed",c);out.append(copy.deepcopy(c))
            if result["state"]=="contradicted":self._new_problem("fresh_prediction_contradicted","candidate_structure_or_parameters",result["experiment_ids"],"区分参数估计与结构遗漏，修订前保持当前条件反驳。")
        return {"completed_checks":out,"unavailable_checks":[c["check_id"] for c in self.checks if c.get("result") is None]}

    def _collect(self,args):
        if set(args)!={"until","repair","refit","assess"} or args["until"] not in {"next","all"} or any(type(args[k]) is not bool for k in ("repair","refit","assess")):raise ValueError("complete collection arguments required")
        while self.gateway.clock<self.gateway.deadline:
            state=self.gateway.public_state()
            if args["repair"]:
                for j in state["failed_jobs"]:
                    if sum(x["status"]=="pending" for x in self.gateway.public_state()["pending_jobs"])<self.gateway.max_pending:self.gateway.call("retry_execution",{"job_id":j["job_id"]})
                for j in state["unverified_jobs"]:self.gateway.call("reconcile_measurement",{"job_id":j["job_id"]})
            if not self.gateway.public_state()["pending_jobs"]:break
            self.gateway.call("await_next",{});self._sync()
            if args["until"]=="next":break
        self._sync();result={"research_state":self.gateway.public_state(),"training_evidence_ids":sorted(self.training_ids)}
        if args["assess"]:result["analysis"]=self._assess()
        if args["refit"]:result["fit"]=self._fit()
        return result

    def _finish(self,args):
        if set(args)!={"candidate_id","claims","unresolved","stop_reason"} or type(args["unresolved"]) is not bool or not isinstance(args["claims"],str) or not args["claims"].strip() or not isinstance(args["stop_reason"],str) or not args["stop_reason"].strip():raise ValueError("complete scoped stopping fields required")
        cid=args["candidate_id"];c=self.registry[cid];model=c["model"]
        if self.terminal_policy=="settle_committed" and not args["unresolved"]:raise ValueError("declare unresolved=True before settling future committed receipts; only the scoped card may gain support")
        if self.decisions_closed and cid!=self.terminal_commitment["candidate_id"]:raise ValueError("terminal model selection is already frozen")
        if not self.decisions_closed:
            self._sync();self._assess()
            if not args["unresolved"]:
                tentative={"phase":"confirmation_model_frozen","round":len(self.checks),"model":model,"training_evidence_ids":c["training_evidence_ids"],"information_evidence_ids":c.get("information_evidence_ids",[])}
                current=card(model,self.facts["ontology"],self.versions+[tentative],[ch["result"] for ch in self.checks if ch["result"] is not None])
                if any(self.gateway.public_state()[k] for k in ("pending_jobs","failed_jobs","unverified_jobs")) or current["state"]!="supported_in_listed_conditions":raise ValueError("unverified/pending/refuted/unconfirmed scope must be unresolved")
            self.terminal_commitment={"policy":self.terminal_policy,"candidate_id":cid,"model_sha256":digest(model),"registered_at":self.gateway.clock,
                "job_ids":sorted(self.jobs),"check_ids":[ch["check_id"] for ch in self.checks],"registry_sha256":digest(self.registry),
                "plans_sha256":digest(self.objects["plans"]),"revisions":self.revisions,"training_evidence_ids":c["training_evidence_ids"].copy(),
                "information_evidence_ids":c.get("information_evidence_ids",[]).copy(),"reason":args["stop_reason"]}
            self.decisions_closed=True;self._event("research_decisions_closed",self.terminal_commitment)
            if self.discovery_tasks is not None:self.discovery_tasks.close(self)
            from terminal_receipts import settle
            if self.terminal_policy=="received_only":self.terminal_settlement={"reason":"received_only","extra_api_calls":0,"new_designs":0,"new_hypotheses":0,"parameter_refits":0}
            elif self.calls<self.max_calls:
                self.calls+=1;before=copy.deepcopy(self.gateway.used)
                self.terminal_settlement=settle(self,self.terminal_commitment)
                self._event("scientific_tool_response",{"request":{"tool":"settle_committed_receipts","args":{"policy":self.terminal_policy},
                    "rationale":"事前冻结的执行终止规则。","expected_gap":"完成已承诺测量和核验，不追加研究。"},
                    "feedback":{"ok":True,"result":self.terminal_settlement},"used_before":before,"used_after":copy.deepcopy(self.gateway.used),"wall_seconds":0.})
            else:self.terminal_settlement={"reason":"no_scientific_action_allocation","extra_api_calls":0,"new_designs":0,"new_hypotheses":0,"parameter_refits":0}
            if digest(self.registry)!=self.terminal_commitment["registry_sha256"] or digest(self.objects["plans"])!=self.terminal_commitment["plans_sha256"] or [ch["check_id"] for ch in self.checks]!=self.terminal_commitment["check_ids"] or self.revisions!=self.terminal_commitment["revisions"]:raise ValueError("scientific decision changed during settlement")
            self._event("committed_receipts_settled",self.terminal_settlement)
        self._sync();self._assess()
        # A fresh final version is explicit even if the policy stops before any
        # independent confirmation. It cannot recycle a check used in training.
        terminal={"phase":"confirmation_model_frozen","round":len(self.checks),"clock":self.gateway.clock,
            "model":copy.deepcopy(model),"training_evidence_ids":c["training_evidence_ids"].copy(),"information_evidence_ids":c.get("information_evidence_ids",[]).copy(),"terminal_analysis":True}
        completed=[ch["result"] for ch in self.checks if ch.get("result") is not None]
        result=card(model,self.facts["ontology"],self.versions+[terminal],completed)
        state=self.gateway.public_state();unfinished=any(state[k] for k in ("pending_jobs","failed_jobs","unverified_jobs"))
        unresolved=unfinished or result["state"]!="supported_in_listed_conditions"
        if unresolved and not args["unresolved"]:raise ValueError("unverified/pending/refuted/unconfirmed scope must be unresolved")
        result.update(completed_checks=len(completed),registered_checks=len(self.checks),max_checks=6,
            research_coverage_state="registered_checks_incomplete" if len(completed)<len(self.checks) else "registered_checks_complete",
            source_dependency_scope="memory supplies structural candidates only")
        self.gateway.call("finish",{"model":copy.deepcopy(model),"claims":args["claims"],"unresolved":args["unresolved"],"stop_reason":args["stop_reason"]})
        self.versions.append(terminal)
        self.closed=True;self.final={"candidate_id":cid,"mechanism_card":result,"frozen_final":copy.deepcopy(self.gateway.final)}
        return copy.deepcopy(self.final)

    def call(self,tool,args,rationale="",expected_gap=""):
        if self.closed:raise ValueError("research already frozen")
        if self.decisions_closed and tool!="finish":raise ValueError("research decisions are closed; only frozen terminal analysis remains")
        if self.calls>=self.max_calls:raise ValueError("shared scientific-action budget exhausted")
        self.calls+=1;start=time.monotonic();before=copy.deepcopy(self.gateway.used)
        request={"tool":tool,"args":copy.deepcopy(args),"rationale":rationale,"expected_gap":expected_gap}
        try:
            if not isinstance(args,dict) or tool not in TOOLS:raise ValueError("unknown scientific tool or non-object args")
            if self.gateway.clock>=self.gateway.deadline and tool not in {"fit_pool","assess_checks","read_candidate","review_candidate_evidence","finish"}:raise ValueError("calendar deadline reached")
            if tool=="diagnose_history":
                if args:raise ValueError("empty args required")
                supply=self.gateway.call("audit_history",{});meter=self.gateway.call("reconcile_history",{})
                issue="observed_supply_discrepancy" if supply["physical_opening"]!=supply["recorded_opening"] else "observed_recording_discrepancy" if meter["recorded_sales"]!=meter["verified_sales"] else "no_identified_history_discrepancy"
                raw={"supply_receipt":supply,"meter_receipt":meter};eid=digest(raw)
                self.objects["evidence"].append({"evidence_id":eid,"source_type":"historical_inventory_and_meter_audit","query":{"tool":"diagnose_history"},
                    "data_version":1,"occurred_at":-1,"available_at":self.gateway.clock,"processing_version":VERSION,"scope":"matched_conditional_history",
                    "independence_group":"matched_conditional_history","validity":"diagnostic_only","measurement":raw})
                self._problem_update("P0000","history_fields_diagnosed",issue,[eid])
                result={**raw,"observed_issue":issue,"interpretation":"条件历史只作诊断，不是随机训练数据或机制反证；没有发现账差不认证潜在需求。"}
            elif tool=="open_adaptation":
                if args:raise ValueError("empty args required")
                if self.gateway.transfer_open:
                    r=copy.deepcopy(next(e["payload"] for e in self.gateway.events if e["kind"]=="tool_response" and e.get("request",{}).get("tool")=="open_transfer"))
                else:
                    if self.jobs:raise ValueError("open new public facts before any planned experiments")
                    r=self.gateway.call("open_transfer",{});self.facts=compile_structured(self.gateway.public_catalog("source")+r["catalog"])
                    self.initial_candidate=self._candidate({"model":{"role_patterns":self.facts["role_patterns"],"expression":.3},"terms":[],"rank":0,"bic":0.,"deviance":None,"origin":"public_initial_constant"},[],self.initial_candidate)
                    self.memory=None;self._fit_key=None
                result={"catalog":r["catalog"],"sites":r["sites"],"physical_facts":copy.deepcopy(self.facts),"initial_candidate_id":self.initial_candidate}
            elif tool=="retrieve_memory":
                if args:raise ValueError("empty args required")
                mem=self._memory();self.memory_retrieved=True
                result={"archive_id":mem.archive["archive_id"],"source_cost_shared":mem.archive["source_acquisition_cost"],
                    "episodes":[{"episode_id":e["episode"]["episode_id"],"source_state":e["episode"]["source_state"],
                        "template":copy.deepcopy(e["episode"]["template"]),"scope_flags":e["retrieval"]["scope_flags"],
                        "source_context":e["episode"]["public_context"],"conditional_claims":copy.deepcopy(e["episode"]["conditional_claims"]),
                        "usage":"reviewed structure proposal only; target unconfirmed"} for e in mem.entries]}
            elif tool=="read_memory":
                if set(args)!={"episode_id"}:raise ValueError("episode ID required")
                result=copy.deepcopy(next(e for e in self._memory().archive["episodes"] if e["episode_id"]==args["episode_id"]))
            elif tool=="review_memory":
                if set(args)!={"episode_ids","usage","rationale"} or args["usage"]!="structure_refit_only" or not isinstance(args["rationale"],str) or not args["rationale"].strip():raise ValueError("explicit structural scope-review rationale required")
                mem=self._memory();ids=args["episode_ids"]
                if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids):raise ValueError("unique nonempty source IDs required")
                entries={e["episode"]["episode_id"]:e for e in mem.entries}
                if not set(ids)<=set(entries):raise ValueError("unknown public source")
                if any(entries[i]["episode"]["physical_definitions"]!=self.facts["ontology"] or entries[i]["episode"]["template"] is None for i in ids):raise ValueError("incompatible ontology or unsupported source program")
                review={"sequence":len(self.memory_reviews),"episode_ids":ids.copy(),"usage":args["usage"],"rationale":args["rationale"],
                    "scope_flags":{i:entries[i]["retrieval"]["scope_flags"] for i in ids},"target_state":"unconfirmed","source_counts_pooled":False,"available_at":self.gateway.clock}
                review["target_exposure_ids"]=[r["experiment_id"] for r in self.gateway.public_state()["mature_evidence"] if r["verified_supply"] and r["verified_meter"]]
                for i in ids:entries[i]["eligible"]=True;entries[i]["retrieval"]["status"]="reviewed_structure_requires_target_fit_and_check"
                self.memory_reviews.append(review);self._event("memory_scope_reviewed",review);self._fit_key=None;result=review
            elif tool=="fit_pool":
                if args:raise ValueError("empty args required")
                result=self._fit()
            elif tool=="propose_model":
                if set(args)!={"expression","parameters","rationale"} or not isinstance(args["rationale"],str) or not args["rationale"].strip():raise ValueError("safe expression, parameters and scientific rationale required")
                self._sync();fit_args={"role_patterns":self.facts["role_patterns"],"expression":args["expression"],"parameters":args["parameters"]}
                fitted=self.gateway.call("fit_candidate",fit_args);row=self._fit_row(fitted,len(args["parameters"]),"policy_proposal",args["expression"])
                cid=self._candidate(row,self.training_ids,fit_args=fit_args);self.pool.insert(0,cid);self._fit_key=None;result=self._summary(cid)|{"proposal_rationale":args["rationale"]}
            elif tool=="read_candidate":
                if set(args)!={"candidate_id"}:raise ValueError("candidate ID required")
                result=copy.deepcopy(self.registry[args["candidate_id"]])
            elif tool=="suggest_design":
                if set(args)!={"candidate_id"}:raise ValueError("candidate ID required")
                action=plan(self.gateway,self._selection_pool(args["candidate_id"]),novelty=True)
                result={"design":action,"interpretation":"公开候选代理；不是私有真值信息增益或唯一正确干预。"}
            elif tool=="sample":
                if set(args)!={"candidate_id","designs","rationale"}:raise ValueError("complete sample fields required")
                result=self._sample(args["candidate_id"],args["designs"],args["rationale"])
            elif tool=="sample_frontier":
                if set(args)!={"candidate_id","count","rationale"} or type(args["count"]) is not int or not 1<=args["count"]<=3:raise ValueError("complete frontier request required")
                result=self._sample(args["candidate_id"],self._frontier_designs(args["candidate_id"],args["count"]),args["rationale"])
            elif tool in {"start_discovery_task","advance_discovery_task"}:
                from research_action_schema import validate_action_args
                validate_action_args(tool,args)
                if self.discovery_tasks is None:raise ValueError("discovery task component is disabled")
                result=self.discovery_tasks.start(self,args) if tool=="start_discovery_task" else self.discovery_tasks.advance(self,args)
            elif tool=="collect":result=self._collect(args)
            elif tool=="repair":
                if set(args)!={"job_id","kind"} or args["kind"] not in {"execution","meter"}:raise ValueError("repair kind and job required")
                result=self.gateway.call("retry_execution" if args["kind"]=="execution" else "reconcile_measurement",{"job_id":args["job_id"]});self._sync()
            elif tool=="confirm":
                if set(args) not in ({"candidate_id","rationale"},{"candidate_id","rationale","design"}) or len(self.checks)>=6:raise ValueError("invalid confirmation or six checks already registered")
                cid=args["candidate_id"];self._sync();c=self.registry[cid]
                action=copy.deepcopy(args.get("design"))
                if action is None:
                    suggested=plan(self.gateway,self._selection_pool(cid),novelty=True)
                    if suggested is None:raise ValueError("no feasible confirmation design")
                    action={k:suggested[k] for k in ("stage","site","assortment")}
                if set(action)!={"stage","site","assortment"}:raise ValueError("fixed condition fields required")
                design=action|{"n":800}
                proposed={**copy.deepcopy(design),"verified_supply":True,"verified_meter":True,"prediction":0.,"rationale":args["rationale"]}
                self.gateway._validate_plan(register_plan(self.gateway,c["model"],proposed,cid,"confirmation"))
                # Check both sample/slot allocations before registration. Plan
                # validation itself is public and obtains no future result.
                pending=sum(j["status"]=="pending" for j in self.gateway.public_state()["pending_jobs"])
                if pending+2>self.gateway.max_pending or self.gateway.used["sessions"]+1600>self.gateway.limits["sessions"] or self.gateway.used["arms"]+2>self.gateway.limits["arms"] or self.gateway.used["cost"]+2*(5+len(action["assortment"]))>self.gateway.limits["cost"]:raise ValueError("insufficient shared allocation for independent check")
                index=len(self.checks);check_id=f"K{index:03d}"
                self.versions.append({"phase":"confirmation_model_frozen","round":index,"clock":self.gateway.clock,"model":copy.deepcopy(c["model"]),"training_evidence_ids":c["training_evidence_ids"].copy(),"information_evidence_ids":c.get("information_evidence_ids",[]).copy(),"candidate_id":cid})
                check={"check_id":check_id,"check_index":index,"candidate_id":cid,"registered_at":self.gateway.clock,"training_evidence_ids":c["training_evidence_ids"].copy(),"job_ids":[],"result":None,"released":False}
                self.checks.append(check);self._event("check_frozen_before_execution",check)
                for _ in range(2):check["job_ids"].append(self._submit(cid,design,"confirmation",args["rationale"],check_id)["job_id"])
                result=copy.deepcopy(check)
            elif tool=="assess_checks":
                if args:raise ValueError("empty args required")
                result=self._assess()
            elif tool=="review_candidate_evidence":
                if set(args)!={"candidate_id"}:raise ValueError("exact immutable candidate ID required")
                cid=args["candidate_id"];candidate=self.registry[cid]
                catalogs={stage:self.gateway.public_catalog(stage) for stage in ("source","adaptation") if stage=="source" or self.gateway.transfer_open}
                result=retrospective_review(cid,candidate,self.public_evidence,catalogs,predict)
            elif tool in {"dispatch_research_context","append_research_note"}:
                from research_action_schema import validate_action_args
                validate_action_args(tool,args)
                if self.organization is None:raise ValueError("no research organization attached")
                result=self.organization.dispatch(args,self) if tool=="dispatch_research_context" else self.organization.note(args,self)
            elif tool=="reopen_research":
                if set(args)!={"check_id","rationale","refit"} or type(args["refit"]) is not bool or self.revisions>=2:raise ValueError("revision fields or allocation invalid")
                trigger=next(c for c in self.checks if c["check_id"]==args["check_id"])
                if trigger["released"] or not trigger["result"] or trigger["result"]["state"]!="contradicted":raise ValueError("actual unreleased independent refutation required")
                self.revisions+=1
                for c in self.checks:
                    if c["result"] is not None:self.training_ids.update(c["result"]["experiment_ids"]);c["released"]=True
                self._scope();self._fit_key=None;result={"revision":self.revisions,"training_evidence_ids":sorted(self.training_ids),"trigger_check_id":trigger["check_id"]}
                self._event("confirmation_evidence_released",result)
                if args["refit"]:result["fit"]=self._fit()
            elif tool in {"sample_and_analyze","confirm_and_analyze"}:
                from research_action_schema import validate_action_args
                validate_action_args(tool,args)
                if self.calls+2>self.max_calls:raise ValueError("insufficient scientific actions for charged bundle")
                primitive="sample" if tool=="sample_and_analyze" else "confirm"
                first=self.call(primitive,{k:copy.deepcopy(v) for k,v in args.items() if k!="repair"},rationale,expected_gap)
                if not first["ok"]:raise ValueError("bundle stopped after primitive failure: "+first["error"])
                trace=[{"tool":primitive,"ok":True,"event_hash":self.events[-1]["event_hash"]}]
                collection=self.call("collect",{"until":"all","repair":args["repair"],"refit":primitive=="sample","assess":primitive=="confirm"},rationale,expected_gap)
                trace.append({"tool":"collect","ok":collection["ok"],"event_hash":self.events[-1]["event_hash"]})
                if not collection["ok"]:raise ValueError("bundle stopped after collection failure; prior receipts retained: "+collection["error"])
                result=copy.deepcopy(collection["result"]);result["bundle_trace"]=trace
                if "submitted" in first["result"]:result["submitted"]=copy.deepcopy(first["result"]["submitted"])
            elif tool=="finish":result=self._finish(args)
            else:raise ValueError("unsupported research tool")
        except (ValueError,KeyError,TypeError,SyntaxError,StopIteration) as error:
            feedback={"ok":False,"error":type(error).__name__+": "+str(error),"valid_new_scientific_evidence":False}
        else:feedback={"ok":True,"result":copy.deepcopy(result)}
        self.last_feedback=feedback;self._event("scientific_tool_response",{"request":request,"feedback":feedback,
            "used_before":before,"used_after":copy.deepcopy(self.gateway.used),"wall_seconds":time.monotonic()-start})
        return copy.deepcopy(feedback)

    def state(self):
        if not self.closed:self._sync()
        value={"runtime_version":VERSION,"clock":self.gateway.clock,"limits":self.gateway.limits,"used":self.gateway.used,
            "scientific_actions_used":self.calls,"scientific_actions_limit":self.max_calls,"revisions_used":self.revisions,"max_revisions":2,
            "initial_candidate_id":self.initial_candidate,"training_evidence_ids":sorted(self.training_ids),
            "catalogs":{s:self.gateway.public_catalog(s) for s in ("source","adaptation") if s=="source" or self.gateway.transfer_open},
            "physical_role_patterns":copy.deepcopy(self.facts["role_patterns"]),"physical_definitions":copy.deepcopy(self.facts["ontology"]),
            "observations":self.gateway.public_state(),"current_candidates":[self._summary(cid) for cid in self.pool[:6]],
            "registered_checks":copy.deepcopy(self.checks),"memory_reviews":copy.deepcopy(self.memory_reviews),"memory_archive_available":self.memory_archive is not None,
            "available_memory_episode_ids":[] if self.memory is None else [e["episode"]["episode_id"] for e in self.memory.entries],
            "last_feedback":copy.deepcopy(self.last_feedback),"closed":self.closed,"public_evidence_store":self.public_evidence.view()}
        if self.discovery_tasks is not None:value["discovery_tasks"]=self.discovery_tasks.view()
        if self.organization is not None:
            visible=self.pool[:6]+[c["candidate_id"] for c in self.checks]+[c["candidate_id"] for c in self.registry.values() if c["origin"]=="policy_proposal"]
            value["research_organization"]=self.organization.view(value["observations"],visible)
        return value

    def snapshot(self):
        value={"version":VERSION,"objects":copy.deepcopy(self.objects),"events":copy.deepcopy(self.events),"jobs":copy.deepcopy(self.jobs),
            "training_evidence_ids":sorted(self.training_ids),"checks":copy.deepcopy(self.checks),"versions":copy.deepcopy(self.versions),
            "memory_reviews":copy.deepcopy(self.memory_reviews),"memory_trace":None if self.memory is None else self.memory.trace(),
            "calls":self.calls,"revisions":self.revisions,"final":copy.deepcopy(self.final),"terminal_policy":self.terminal_policy,
            "decisions_closed":self.decisions_closed,"terminal_commitment":copy.deepcopy(self.terminal_commitment),"terminal_settlement":copy.deepcopy(self.terminal_settlement),
            "public_evidence_store":self.public_evidence.snapshot()}
        if self.discovery_tasks is not None:value["discovery_tasks"]=self.discovery_tasks.view()
        if self.organization is not None:value["research_organization"]=self.organization.snapshot(self.gateway.public_state())
        return value
