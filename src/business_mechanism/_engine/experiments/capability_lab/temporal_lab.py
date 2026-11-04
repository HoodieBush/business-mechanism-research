"""Discrete-event cohort gateway: public availability is separate from occurrence.

The executor can pre-sample stationary outcomes internally. The public gateway
never exposes those outcomes, or fits them, before their delivery event.
This is a research-event simulator, not a multi-period inventory simulator.
"""
from __future__ import annotations
import copy
import hashlib
import heapq
import json
import math

from choice_world import ChoiceLab
from lab import predict,validate_model
from public_fitting import check_public_model,fit_public_candidate

PROFILES={"staggered","interruptions"}
VERSION="temporal-lab-v0.2-atomic-budget-preflight"


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class TemporalLab:
    def __init__(self,world,profile="staggered",deadline=120,max_pending=3):
        if profile not in PROFILES or not isinstance(deadline,int) or deadline<1 or max_pending not in (1,2,3):raise ValueError("invalid temporal allocation")
        self._core=ChoiceLab(world,max_sessions=14400,max_arms=24,max_cost=276)
        self._profile=profile;self.clock=0;self.deadline=deadline;self.max_pending=max_pending
        self._queue=[];self._sequence=0;self._jobs={};self._latest={};self._fit_scope=None
        self.events=[];self.tool_calls=0;self.candidates=[];self.final=None
        self.transfer_open=False;self._catalogs={"source":self._core.public_catalog("source")}
        self.limits={**self._core.limits,"logical_time":deadline,"tool_calls":200,"api_calls":8,"api_tokens":60000}

    @property
    def used(self):return {**self._core.used,"logical_time":self.clock,"tool_calls":self.tool_calls}

    def _record(self,kind,payload,occurred_at=None,request=None,request_time=None):
        event={"event_id":len(self.events),"kind":kind,"occurred_at":self.clock if occurred_at is None else occurred_at,
            "available_at":self.clock,"payload":copy.deepcopy(payload),"used":self.used.copy()}
        if request is not None:event.update(request=copy.deepcopy(request),request_time=request_time)
        self.events.append(event);return copy.deepcopy(event)

    def _schedule(self,time,kind,job_id):
        self._sequence+=1;heapq.heappush(self._queue,(time,self._sequence,kind,job_id))

    def _public_job(self,job):
        fields=("job_id","registered_at","plan_id","plan","status","attempts","started_at","collection_complete_at","expected_report_at","experiment_id","measurement","audit_expected_at")
        return {k:copy.deepcopy(job[k]) for k in fields if k in job}

    def public_state(self):
        return {"clock":self.clock,"deadline":self.deadline,"limits":copy.deepcopy(self.limits),"used":self.used,
            "pending_jobs":[self._public_job(j) for j in self._jobs.values() if j["status"] in {"pending","awaiting_audit"}],
            "failed_jobs":[self._public_job(j) for j in self._jobs.values() if j["status"]=="execution_failed"],
            "unverified_jobs":[self._public_job(j) for j in self._jobs.values() if j["status"]=="measurement_unverified"],
            "mature_evidence":[copy.deepcopy(r) for r in self._latest.values()],
            "training_scope":None if self._fit_scope is None else sorted(self._fit_scope),
            "next_delivery_time":min((q[0] for q in self._queue),default=None)}

    def public(self):
        value=self._core.public()
        for h in value["history"]:h.update(occurred_at=h["day"]-4,available_at=h["day"]-3)
        value["limits"]=copy.deepcopy(self.limits)
        value["temporal_contract"]={"gateway_version":VERSION,"time_unit":"研究刻度；400 会话采集需 1 刻度，800 会话需 2 刻度。",
            "report_delay":"采集后报告延迟 1..4 刻度，取决于公开设计的确定性队列；与结果无关。",
            "max_pending_measurements":self.max_pending,"observation_rule":"只能使用 available_at<=clock 的最新有效证据；排队设计可以避免重复，不提供销量。",
            "verification_rule":"执行可能未启动；计数核验可能失败。实际回执优先于计划标记；核验失败的计数不可用于购买概率估计。",
            "deadline_analysis":"截止时停止启动、修复和等待；可用已收到证据作终端拟合并冻结，不能接收截止后的结果。",
            "population":"当前版本效用参数在研究刻度内固定；不宣称经营时间漂移或多期补货。"}
        value["tools"]={
            "audit_history":{},"reconcile_history":{},"open_transfer":{},
            "submit_experiment":{"args":"完整事前计划；先登记哈希，返回排队/执行失败，不含未来销量"},
            "retry_execution":{"args":{"job_id":"未启动且修复次数<2的任务"}},
            "reconcile_measurement":{"args":{"job_id":"已有未核实成熟计数的任务"},"cost":1,"delay":2},
            "await_next":{"args":{},"returns":"前进到下一公开事件或截止时刻；不采新样本"},
            "fit_candidate":{"args":"使用当前可用且在训练范围内的核实证据"},
            "check_model":{"args":{"model":"公开安全程序"}},"finish":{"args":"冻结模型、范围和未决，结束研究"},
            "deployment_catalog":{"args":{},"returns":"finish 后只读新商品事实"}}
        value["research_state"]=self.public_state();return value

    def public_catalog(self,stage):
        if stage not in self._catalogs:raise ValueError("catalog has not been received")
        return copy.deepcopy(self._catalogs[stage])

    def observed_cohorts(self):
        # Pending designs affect coverage only. There are no invented sales.
        rows=[copy.deepcopy(r) for r in self._latest.values()]
        rows += [{k:copy.deepcopy(j["plan"]["action"][k]) for k in ("stage","site","assortment","n")}|{"pending":True}
            for j in self._jobs.values() if j["status"]=="pending"]
        return rows

    def verified_observations(self):
        return [(copy.deepcopy(r),r["observed_sales"]) for r in self._latest.values()
            if r["available_at"]<=self.clock and r["verified_supply"] and r["verified_meter"]
            and (self._fit_scope is None or r["experiment_id"] in self._fit_scope)]

    def set_fit_scope(self,ids):
        if ids is not None and not set(ids)<={r["experiment_id"] for r in self._latest.values() if r["verified_supply"] and r["verified_meter"]}:
            raise ValueError("training scope includes unavailable or unverified evidence")
        self._fit_scope=None if ids is None else set(ids)
        self._record("fit_scope_frozen",{"training_ids":None if ids is None else sorted(ids)})

    def _validate_plan(self,plan):
        required={"claim_id","model","action","estimand","randomization_unit","analysis","stopping","rationale"}
        if not isinstance(plan,dict) or set(plan)!=required:raise ValueError("provide complete registered plan fields")
        validate_model(plan["model"]);action=plan["action"]
        if not isinstance(plan["claim_id"],str) or not plan["claim_id"].strip():raise ValueError("claim ID required")
        fields={"assortment","stage","site","n","verified_supply","verified_meter","prediction","rationale"}
        if not isinstance(action,dict) or set(action)!=fields:raise ValueError("complete action fields required")
        stage=action["stage"];site=action["site"];arm=action["assortment"]
        if stage not in self._catalogs or site not in {"00","10","01","11"} or (stage=="source" and site!="00"):
            raise ValueError("unavailable catalog or illegal site")
        ids={p["id"] for p in self.public_catalog(stage)}
        if not isinstance(arm,list) or any(not isinstance(pid,str) for pid in arm) or len(set(arm))!=len(arm) or not set(arm)<=ids:
            raise ValueError("unknown or duplicate product IDs")
        if type(action["n"]) is not int or not 100<=action["n"]<=800:raise ValueError("n must be 100..800")
        if type(action["prediction"]) not in (int,float) or not math.isfinite(action["prediction"]) or not 0<=action["prediction"]<=1:
            raise ValueError("finite probability required")
        if action["verified_supply"] is not True or action["verified_meter"] is not True:
            raise ValueError("this phase requires planned supply and meter verification")
        if not isinstance(action["rationale"],str) or not action["rationale"].strip():raise ValueError("action rationale required")
        if plan["estimand"]!="purchase_probability_in_fixed_condition" or plan["randomization_unit"]!="qualified_session":raise ValueError("unsupported estimand or randomization unit")
        if plan["stopping"]!={"deadline":self.deadline,"missing_result":"unresolved","execution_failure":"repair_before_science","unverified_meter":"exclude_until_reconciled"}:
            raise ValueError("stopping/missing-data rule differs from environment contract")
        p=predict(plan["model"],self.public_catalog(action["stage"]),action["assortment"],tuple(map(int,action["site"])))
        if abs(p-action["prediction"])>1e-10:raise ValueError("registered probability differs from executable model")
        if plan["analysis"] not in ({"purpose":"discovery","rule":"descriptive_fit_only"},
            {"purpose":"confirmation","rule":"clopper_pearson","max_checks":6,"total_alpha":.05,"tolerance":.05}):
            raise ValueError("unsupported predeclared analysis")
        if not isinstance(plan["rationale"],str) or not plan["rationale"]:raise ValueError("plan must describe evidence gap")

    def _check_launch_budget(self,job_id,attempts,action):
        failed=self._profile=="interruptions" and job_id in {1,15} and attempts==0
        additions={"sessions":0 if failed else action["n"],"arms":0 if failed else 1,"cost":1 if failed else 5+len(action["assortment"])}
        if any(self._core.used[k]+v>self._core.limits[k] for k,v in additions.items()):raise ValueError("shared research budget exhausted")
        return failed

    def _start(self,job):
        if sum(j["status"]=="pending" for j in self._jobs.values())>=self.max_pending:raise ValueError("pending measurement capacity exhausted")
        action=job["plan"]["action"];failed=self._check_launch_budget(job["job_id"],job["attempts"],action)
        job["attempts"]+=1
        if failed:
            self._core._reserve(cost=1);job["status"]="execution_failed"
            return {"job_id":job["job_id"],"plan_id":job["plan_id"],"status":"execution_failed","samples_consumed":0,
                "scientific_interpretation":"操作未启动，不能形成机制反证；可在同一事前计划下有限重试。"}
        r=self._core.call("experiment",job["plan"]["action"])
        action=job["plan"]["action"];end=self.clock+math.ceil(action["n"]/400)
        design={k:action[k] for k in ("stage","site","n")};design["assortment"]=sorted(action["assortment"])
        lag=1+int(digest(design)[:8],16)%4
        job.update(status="pending",started_at=self.clock,collection_complete_at=end,expected_report_at=end+lag,experiment_id=r["experiment_id"])
        job["_private_result"]=copy.deepcopy(r)
        self._schedule(end+lag,"measurement",job["job_id"])
        return {k:copy.deepcopy(job[k]) for k in ("job_id","plan_id","status","started_at","collection_complete_at","expected_report_at","experiment_id")}

    def _deliver(self,kind,job_id):
        job=self._jobs[job_id];r=copy.deepcopy(job["_private_result"])
        r.update(occurred_at=job["collection_complete_at"],available_at=self.clock,job_id=job_id,evidence_version=1)
        if kind=="measurement" and self._profile=="interruptions" and job_id in {3,10,18}:
            r.update(observed_sales=max(0,r["observed_sales"]-math.floor(.12*r["n"])),verified_meter=False)
            r["observed_rate"]=r["observed_sales"]/r["n"];job["status"]="measurement_unverified"
        else:
            job["status"]="mature_verified"
            if kind=="reconciled":r["evidence_version"]=2
        job["measurement"]=copy.deepcopy(r);self._latest[r["experiment_id"]]=copy.deepcopy(r)
        self._record("measurement_received" if kind=="measurement" else "measurement_revised",r,occurred_at=r["occurred_at"])

    def call(self,tool,args):
        if self.tool_calls>=self.limits["tool_calls"]:raise ValueError("shared tool-call limit exhausted")
        self.tool_calls+=1;request_time=self.clock;request={"tool":tool,"args":copy.deepcopy(args)}
        try:
            if not isinstance(args,dict):raise ValueError("args must be an object")
            if self.final is not None and tool!="deployment_catalog":raise ValueError("research already frozen")
            if tool not in {"fit_candidate","check_model","finish","deployment_catalog"} and self.clock>=self.deadline:raise ValueError("research calendar deadline reached")
            if tool in {"audit_history","reconcile_history","open_transfer"}:
                if args:raise ValueError("empty args required")
                core_tool={"audit_history":"audit","reconcile_history":"reconcile","open_transfer":"open_transfer"}[tool]
                result=self._core.call(core_tool,{})
                if tool=="open_transfer":self.transfer_open=True;self._catalogs["adaptation"]=copy.deepcopy(result["catalog"])
            elif tool=="submit_experiment":
                if set(args)!={"plan"}:raise ValueError("submit requires a registered plan")
                plan=copy.deepcopy(args["plan"]);self._validate_plan(plan)
                if sum(j["status"]=="pending" for j in self._jobs.values())>=self.max_pending:raise ValueError("pending measurement capacity exhausted")
                job_id=len(self._jobs);plan_id=digest({"registered_at":self.clock,"job_id":job_id,"plan":plan})
                self._check_launch_budget(job_id,0,plan["action"])
                job={"job_id":job_id,"plan_id":plan_id,"plan":plan,"registered_at":self.clock,"status":"registered","attempts":0}
                self._record("plan_registered",{"job_id":job_id,"plan_id":plan_id,"plan":plan})
                # Registration precedes the executor obtaining any outcome.
                result=self._start(job);self._jobs[job_id]=job
            elif tool=="retry_execution":
                job=self._jobs[args["job_id"]]
                if job["status"]!="execution_failed" or job["attempts"]>=2:raise ValueError("no eligible execution repair")
                result=self._start(job)
            elif tool=="reconcile_measurement":
                job=self._jobs[args["job_id"]]
                if job["status"]!="measurement_unverified":raise ValueError("only mature unverified measurement can be reconciled")
                self._core._reserve(cost=1);job.update(status="awaiting_audit",audit_expected_at=self.clock+2)
                self._schedule(self.clock+2,"reconciled",job["job_id"])
                result={"job_id":job["job_id"],"status":"awaiting_audit","expected_report_at":self.clock+2,"new_samples":0}
            elif tool=="await_next":
                if args or not self._queue:raise ValueError("no pending public event")
                before=len(self.events);self.clock=min(self.deadline,self._queue[0][0])
                while self._queue and self._queue[0][0]<=self.clock:
                    _,_,kind,job_id=heapq.heappop(self._queue);self._deliver(kind,job_id)
                result={"status":"deadline_reached" if self.clock==self.deadline else "events_received","clock":self.clock,"new_events":copy.deepcopy(self.events[before:])}
            elif tool=="fit_candidate":
                result=fit_public_candidate(args,self.verified_observations(),self._catalogs,len(self.candidates),len(self._latest))
                self.candidates.append(copy.deepcopy(result))
            elif tool=="check_model":result=check_public_model(args["model"],self.verified_observations(),self._catalogs,len(self._latest))
            elif tool=="finish":
                validate_model(args["model"])
                if not isinstance(args.get("claims"),str) or not args["claims"]:raise ValueError("finish requires scoped claims")
                if any(j["status"]!="mature_verified" for j in self._jobs.values()) and not args.get("unresolved",False):raise ValueError("pending/failed evidence requires unresolved scope")
                self.final=copy.deepcopy(args);result={"status":"frozen","used":self.used}
            elif tool=="deployment_catalog":
                if self.final is None or args:raise ValueError("deployment facts require frozen model and empty args")
                self._core.final=copy.deepcopy(self.final);result=self._core.deployment_catalog()
            else:raise ValueError("unknown temporal tool")
        except (ValueError,KeyError,TypeError,SyntaxError) as error:
            self._record("tool_failure",{"error":str(error),"new_valid_evidence":False},request=request,request_time=request_time);raise
        self._record("tool_response",result,request=request,request_time=request_time)
        return copy.deepcopy(result)
