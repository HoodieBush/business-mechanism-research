"""Research-cohort prototype. Private World is never serialized to the agent.

This is not a full replenishment simulator. It isolates observation diagnosis,
non-additive discovery and conditional transfer with a shared action budget.
"""
from __future__ import annotations

import copy
import ast
import hashlib
import itertools
import json
import math
from functools import lru_cache
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


FUNCTIONS = ("heating", "utensils")
OPS = {"add", "sub", "mul", "max", "min", "sigmoid"}
VARIABLES = {"heat", "utensils", "external_heat", "external_utensils", "items"}


def compile_expression(text, parameters=None, variables=None):
    """Compile a restricted arithmetic expression; never execute Python."""
    parameters = parameters or {}
    variables = set(VARIABLES if variables is None else variables)
    if not isinstance(text, str) or len(text) > 2500:
        raise ValueError("provide a short arithmetic expression")
    tree = ast.parse(text, mode="eval")
    count = 0
    def visit(node, depth=0):
        nonlocal count
        count += 1
        if count > 200 or depth > 12:
            raise ValueError("expression too large")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in variables:
                return {"var": node.id}
            if node.id in parameters:
                return float(parameters[node.id])
            raise ValueError(f"unknown variable '{node.id}'; allowed variables={sorted(variables)}, parameters={sorted(parameters)}. New text-grounded factor names must be declared in role_patterns.")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return {"op": "sub", "args": [0, visit(node.operand, depth + 1)]}
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult):
            name = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul"}[type(node.op)]
            return {"op": name, "args": [visit(node.left, depth + 1), visit(node.right, depth + 1)]}
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"min", "max", "sigmoid"} and not node.keywords):
            return {"op": node.func.id, "args": [visit(a, depth + 1) for a in node.args]}
        raise ValueError("only numbers, declared variables/parameters, + - *, min/max/sigmoid are allowed")
    return visit(tree.body)


def evaluate(expr, variables, depth=0):
    """Small, non-executable arithmetic AST. No eval, imports or source access."""
    if depth > 12:
        raise ValueError("expression nesting exceeds 12")
    if isinstance(expr, (float, int)) and not isinstance(expr, bool):
        if not math.isfinite(expr) or abs(expr) > 100:
            raise ValueError("invalid numeric constant")
        return float(expr)
    if not isinstance(expr, dict):
        raise ValueError("expression must be a number or AST object")
    if set(expr) == {"var"} and expr["var"] in variables:
        return float(variables[expr["var"]])
    if set(expr) != {"op", "args"} or expr["op"] not in OPS:
        raise ValueError("unknown operation")
    args = expr["args"]
    if expr["op"] == "sigmoid":
        if not isinstance(args,list) or len(args)!=1:raise ValueError("sigmoid requires exactly one argument")
        value=evaluate(args[0],variables,depth+1)
        return 1/(1+math.exp(-value)) if value>=0 else math.exp(value)/(1+math.exp(value))
    if not isinstance(args, list) or not 2 <= len(args) <= 8:
        raise ValueError("operators require 2 to 8 arguments")
    vals = [evaluate(a, variables, depth + 1) for a in args]
    if expr["op"] == "add":
        return sum(vals)
    if expr["op"] == "sub":
        if len(vals) != 2:
            raise ValueError("sub requires two arguments")
        return vals[0] - vals[1]
    if expr["op"] == "mul":
        return math.prod(vals)
    return (max if expr["op"] == "max" else min)(vals)


def validate_model(model):
    if not isinstance(model, dict) or set(model) != {"role_patterns", "expression"}:
        raise ValueError("model requires role_patterns and expression")
    patterns = model["role_patterns"]
    if not isinstance(patterns, dict) or not set(FUNCTIONS).issubset(patterns) or len(patterns)>8:
        raise ValueError("role_patterns requires heating and utensils; up to 6 additional text-grounded factors may be declared")
    if any(not isinstance(k,str) or not k.isidentifier() or (k in VARIABLES and k not in FUNCTIONS) or k in {"min","max","sigmoid"} for k in patterns):
        raise ValueError("invalid role name or collision with builtin variable")
    for values in patterns.values():
        if (not isinstance(values, list) or not 1 <= len(values) <= 8
                or any(not isinstance(s, str) or not 1 <= len(s) <= 40 for s in values)):
            raise ValueError("role patterns must be short nonempty strings")
    variables = VARIABLES | (set(patterns)-set(FUNCTIONS))
    expr = compile_expression(model["expression"],variables=variables) if isinstance(model["expression"], str) else model["expression"]
    evaluate(expr, {v: 0 for v in variables})


@lru_cache(maxsize=8192)
def prepared_model(serialized):
    model=json.loads(serialized)
    validate_model(model)
    patterns=model["role_patterns"]
    variables=VARIABLES|(set(patterns)-set(FUNCTIONS))
    expression=compile_expression(model["expression"],variables=variables) if isinstance(model["expression"],str) else model["expression"]
    return patterns,expression


def predict(model, catalog, assortment, external):
    patterns,expr=prepared_model(json.dumps(model,sort_keys=True,ensure_ascii=False))
    selected = set(assortment)
    text = [p["description"] for p in catalog if p["id"] in selected]
    variables = {
        "heat": int(any(any(s in t for s in patterns["heating"]) for t in text)),
        "utensils": int(any(any(s in t for s in patterns["utensils"]) for t in text)),
        "external_heat": int(external[0]),
        "external_utensils": int(external[1]),
        "items": len(selected),
    }
    for key,substrings in patterns.items():
        if key not in FUNCTIONS:
            variables[key] = int(any(any(s in t for s in substrings) for t in text))
    return min(1.0, max(0.0, evaluate(expr, variables)))


def catalog_for(seed, namespace):
    # Descriptions are legal product facts, not hypotheses about purchase effects.
    facts = [
        ("可为餐食加热的自热组件", (1, 0)),
        ("提供进餐餐具的便携组件", (0, 1)),
        ("同时提供加热功能和餐具的组合包", (1, 1)),
        ("饮用水，仅用于饮用", (0, 0)),
        ("装饰贴纸，仅用于包装装饰", (0, 0)),
        ("便携礼袋，仅用于携带", (0, 0)),
    ]
    if namespace != "source":
        facts[0] = ("新品牌餐食加热模块", (1, 0))
        facts[1] = ("新品牌可重复使用餐具套装", (0, 1))
        facts[2] = ("新品牌加热与餐具一体套装", (1, 1))
    public, roles = [], {}
    for i, (description, role) in enumerate(facts):
        pid = hashlib.sha256(f"{namespace}:{seed}:{i}".encode()).hexdigest()[:8]
        public.append({"id": pid, "description": description})
        roles[pid] = role
    rng = np.random.default_rng(seed + sum(map(ord, namespace)))
    rng.shuffle(public)
    return public, roles


@dataclass
class World:
    seed: int = 0
    family: str = "complement"
    fault: str = "none"
    random_parameters: bool = False

    def __post_init__(self):
        if self.family not in {"complement", "independent", "substitute", "crowding", "null", "context_gate"}:
            raise ValueError("unknown private family")
        if self.fault not in {"none", "supply", "report"}:
            raise ValueError("unknown private fault")
        self.catalogs, self.roles = {}, {}
        for namespace in ("source", "adaptation", "heldout"):
            self.catalogs[namespace], self.roles[namespace] = catalog_for(self.seed, namespace)
        self.base = 0.55 if self.fault in {"supply", "report"} else 0.30
        self.gain,self.crowding_rate,self.context_loss=.25,.08,.15
        if self.random_parameters:
            rng=np.random.default_rng(self.seed+91191)
            self.base += float(rng.uniform(-.03,.03))
            self.gain=float(rng.uniform(.20,.30))
            self.crowding_rate=float(rng.uniform(.06,.10))
            self.context_loss=float(rng.uniform(.10,.18))

    def probability(self, namespace, assortment, external):
        roles = [self.roles[namespace][pid] for pid in assortment]
        a = max([external[0]] + [r[0] for r in roles])
        b = max([external[1]] + [r[1] for r in roles])
        if self.family in {"complement", "crowding", "context_gate"}:
            effect = self.gain * a * b
        elif self.family == "independent":
            effect = self.gain/2 * (a + b)
        elif self.family == "substitute":
            effect = self.gain * max(a, b)
        else:
            effect = 0.0
        penalty = self.crowding_rate * max(len(assortment) - 2, 0) if self.family == "crowding" else 0
        if self.family == "context_gate":
            selected_heat=max([0]+[r[0] for r in roles])
            penalty=self.context_loss*external[0]*(1-selected_heat)*b
        return min(0.95, max(0.05, self.base + effect - penalty))

    def history_audit(self):
        # Deliberately matched, conditional historical fixture; not a random sample
        # from which world prevalence or ordinary power may be estimated.
        actual_sales = 220 if self.fault == "report" else 120
        actual_opening = 120 if self.fault == "supply" else 240
        return {"physical_opening": actual_opening,
                "physical_closing": actual_opening - actual_sales,
                "recorded_opening": 240, "recorded_closing": 120}


class ResearchLab:
    def __init__(self, world, max_sessions=6400, max_arms=16, max_cost=96):
        self._world = world
        self.limits = {"sessions": max_sessions, "arms": max_arms, "cost": max_cost}
        self.used = {"sessions": 0, "arms": 0, "cost": 0}
        self.events = []
        self.receipts = []
        self.transfer_open = False
        self.final = None
        self.candidates = []
        self.checked_executions = set()
        self.checked_meters = set()

    def public(self):
        return {
            "task": "研究即食餐食销量低的原因与可操作关系，冻结可执行购买概率模型，并检验换商品与柜点后的适用范围。允许未决，不要求猜世界名称。",
            "target": "即食餐食；价格固定；每个受控会话最多购买一个目标商品；辅助商品免费提供功能，不计目标销售；无价格、促销或复购效应。",
            "history": [{"day": d, "eligible_sessions": 400, "recorded_sales": 120,
                         "planned_opening": 240, "recorded_closing": 120,
                         "assortment": [], "external_heating": False,
                         "external_utensils": False} for d in range(4)],
            "history_note": "只有账面记录，实际送达与销售事件尚未核对。历史会话来自同一可比场景，但不能确定是否被库存或记录过程影响。",
            "catalog": copy.deepcopy(self._world.catalogs["source"]),
            "sites": {"00": {"external_heating": False, "external_utensils": False}},
            "initial_working_model": "仅作起点：常数购买率、各辅助商品独立增减购买率。可以修改或扩张，不保证候选充分。",
            "protocol": "受控 cohort 使用独立新会话且场景分配随机；n 为已核实的合格会话数，不是从销量推算。一个 cohort 隔离资源，不发生组间抢库存。结果含二项抽样波动。操作一次可设多个商品；使用组合包也合法。",
            "tools": {
                "audit": {"args": {}, "cost": 1, "returns": "历史实际开场与结束盘点"},
                "reconcile": {"args": {"experiment_id": "可选"}, "cost": 1,
                              "returns": "核对历史或一项已完成 cohort 的原始销售事件"},
                "inspect_execution": {"args": {"experiment_id": "必需"}, "cost": 1,
                                      "returns": "核对某 cohort 的实际开场可售数量"},
                "experiment": {"args": {"assortment": "商品 ID 数组", "site": "00/10/01/11",
                                            "stage": "source/adaptation", "n": "100..800",
                                            "verified_supply": "布尔", "verified_meter": "布尔",
                                            "prediction": "事前购买概率 0..1", "rationale": "为什么需要此观察"},
                               "cost": "1+商品数+2*verified_supply+2*verified_meter",
                               "returns": "已成熟的观测销量、冻结预测及执行回执；默认模式不担保账面等于实际。供给核实保证所有会话能买到目标；计数核实保证原始事件计数。"},
                "open_transfer": {"args": {}, "cost": 0,
                                  "returns": "新商品事实和外部已有功能的四类新柜点，仍可用剩余预算采集适应数据；最终在第三组商品评价，无结果回流。"},
                "fit_candidate": {"args": {"role_patterns": "与模型相同", "expression": "含自选参数的算术字符串",
                                              "parameters": "参数名 -> [初值,下界,上界]"},
                                  "cost": 0, "returns": "仅拟合已核实的实验；输出 candidate_id、数值模型、预测残差与近似 lack-of-fit。例：expression=b+g*heat，parameters={b:[0.3,0.05,0.9],g:[0.1,-0.5,0.5]}；这个例子不保证正确。"},
                "check_model": {"args": {"model": "数值模型"}, "cost": 0,
                                "returns": "在已核实数据上核验实际程序的预测；不读取真值"},
                "suggest_probe": {"args": {"candidate_id": "已拟合模型编号"}, "cost": 0,
                                  "returns": "仅用候选预测与合法动作找尚未检验的预测不变转换；不保证候选充分或建议有真实效果。"},
                "finish": {"args": {"model": "role_patterns+expression", "claims": "带范围、依据和未决项的文字"},
                           "cost": 0, "returns": "冻结成功；没有正确答案或分数反馈"},
            },
            "model_format": {"role_patterns": {"heating": ["你选择的商品描述子串"],
                                                "utensils": ["你选择的商品描述子串"]},
                             "expression": {"op": "add", "args": [0.1, {"op": "mul", "args": [0.2, {"var": "heat"}]}]},
                             "syntax_note": "以上仅演示类型，不是正确机制。expression 也可使用受限算术字符串。允许 + - * min/max、单参数 sigmoid、数值及声明变量。sigmoid 是固定安全的概率链接，不执行 Python。role_patterns 可声明额外文本因素，表达式随后可以引用该因素（是否有商品匹配）；额外因素不自动成为已确认的原因。参数界限为 [-6,6]，先 fit_candidate 再 finish。AST op 为 add/sub/mul/max/min（2..8 个参数）或 sigmoid（1 个参数）；变量节点恰好是 {\"var\":\"变量名\"}。claims 放在 finish.args，与 model 平级。",
                             "variables": {"heat": "选中商品是否匹配 heating 子串",
                                           "utensils": "选中商品是否匹配 utensils 子串",
                                           "external_heat": "柜点是否已提供加热", "external_utensils": "柜点是否已提供餐具",
                                           "items": "选中辅助商品数"}},
            "evaluation_contract": "最终模型预测供给和记录均核实后的购买概率；私有评价使用未查询源组合，以及第三组新商品×外部功能条件。既报总体误差，也报零效应、相互作用及上下文效应，额外报告观测诊断。",
            "limits": self.limits.copy(),
        }

    def _reserve(self, sessions=0, arms=0, cost=0):
        additions = {"sessions": sessions, "arms": arms, "cost": cost}
        if any(self.used[k] + additions[k] > self.limits[k] for k in additions):
            raise ValueError("shared research budget exhausted")
        for k in additions:
            self.used[k] += additions[k]

    def call(self, tool, args):
        if self.final is not None:
            raise ValueError("research already frozen")
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        request = copy.deepcopy({"tool": tool, "args": args})
        if tool == "audit":
            self._reserve(cost=1)
            result = self._world.history_audit()
        elif tool == "reconcile":
            idx = args.get("experiment_id")
            receipt = self._receipt(idx) if idx is not None else None
            self._reserve(cost=1)
            result = {"recorded_sales": receipt["result"]["observed_sales"] if receipt else 120,
                      "verified_sales": receipt["true_sales"] if receipt else (220 if self._world.fault == "report" else 120)}
            if idx is not None:
                self.checked_meters.add(idx)
        elif tool == "inspect_execution":
            receipt = self._receipt(args["experiment_id"])
            self._reserve(cost=1)
            result = {"physical_opening": receipt["physical_opening"], "n": receipt["result"]["n"]}
            self.checked_executions.add(args["experiment_id"])
        elif tool == "experiment":
            result = self._experiment(args)
        elif tool == "open_transfer":
            self.transfer_open = True
            result = {"catalog": copy.deepcopy(self._world.catalogs["adaptation"]),
                      "sites": {f"{a}{b}": {"external_heating": bool(a), "external_utensils": bool(b)}
                                for a, b in itertools.product((0, 1), repeat=2)}}
        elif tool == "fit_candidate":
            result = self._fit_candidate(args)
        elif tool == "check_model":
            validate_model(args["model"])
            result = self._check_model(args["model"])
        elif tool == "suggest_probe":
            result = self._suggest_probe(args["candidate_id"])
        elif tool == "finish":
            if "candidate_id" in args:
                args = copy.deepcopy(args)
                args["model"] = self._candidate(args.pop("candidate_id"))["model"]
            validate_model(args["model"])
            if not isinstance(args.get("claims"), str) or not args["claims"].strip():
                raise ValueError("claims must describe evidence, scope and unresolved issues")
            self.final = copy.deepcopy(args)
            result = {"status": "frozen", "used": self.used.copy()}
        else:
            raise ValueError("unknown tool")
        result = copy.deepcopy(result)
        self.events.append({"event_id": len(self.events), "request": request,
                            "response": result, "used": self.used.copy()})
        return result

    def _candidate(self, idx):
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(self.candidates):
            raise ValueError("unknown candidate_id")
        return self.candidates[idx]

    def public_catalog(self,namespace):
        if namespace not in {"source","adaptation"} or (namespace=="adaptation" and not self.transfer_open):
            raise ValueError("catalog is not available to the research process")
        return copy.deepcopy(self._world.catalogs[namespace])

    def observed_cohorts(self):
        return [copy.deepcopy(receipt["result"]) for receipt in self.receipts]

    def verified_observations(self):
        return copy.deepcopy(self._valid_data())

    def _valid_data(self):
        result = []
        for idx, receipt in enumerate(self.receipts):
            r = receipt["result"]
            supply_ok = r["verified_supply"] or (idx in self.checked_executions and receipt["physical_opening"] >= r["n"])
            meter_ok = r["verified_meter"] or idx in self.checked_meters
            if supply_ok and meter_ok:
                result.append((r, receipt["true_sales"] if idx in self.checked_meters else r["observed_sales"]))
        return result

    def _check_model(self, model):
        data = self._valid_data()
        if not data:
            raise ValueError("no jointly verified cohorts; verify supply and event counting first")
        rows = []
        deviance = 0
        for r, k in data:
            p = np.clip(predict(model, self._world.catalogs[r["stage"]], r["assortment"], tuple(map(int, r["site"]))), 1e-6, 1-1e-6)
            n = r["n"]
            z = (k - n*p) / math.sqrt(n*p*(1-p))
            if k:
                deviance += 2*k*math.log(k/(n*p))
            if n-k:
                deviance += 2*(n-k)*math.log((n-k)/(n*(1-p)))
            rows.append({"experiment_id": r["experiment_id"], "observed_rate": k/n,
                         "program_probability": float(p), "standardized_residual": round(float(z), 3)})
        return {"verified_cohorts": len(data), "unverified_cohorts_excluded": len(self.receipts)-len(data),
                "binomial_deviance": round(float(deviance), 4), "residuals": rows,
                "note": "训练拟合诊断，不是独立确认；修订机制需要新条件的冻结预测与测量。"}

    def _fit_candidate(self, args):
        params = args.get("parameters")
        if not isinstance(params, dict) or not 1 <= len(params) <= 8:
            raise ValueError("declare 1..8 parameters")
        names, starts, bounds = [], [], []
        for name, spec in params.items():
            if not name.isidentifier() or name in VARIABLES or name in {"min", "max", "sigmoid"}:
                raise ValueError("invalid parameter name")
            if not isinstance(spec, list) or len(spec) != 3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in spec):
                raise ValueError("parameter spec is [start,lower,upper]")
            start, lo, hi = spec
            if not -6 <= lo <= start <= hi <= 6 or lo >= hi:
                raise ValueError("invalid parameter bounds")
            names.append(name); starts.append(start); bounds.append((lo,hi))
        data = self._valid_data()
        if not data:
            raise ValueError("no jointly verified cohorts available")
        patterns, text = args["role_patterns"], args["expression"]
        if any(name in patterns for name in names):
            raise ValueError("parameter names cannot collide with declared role factors")
        def make_model(values):
            return {"role_patterns": patterns, "expression": compile_expression(text, dict(zip(names, values)), VARIABLES | (set(patterns)-set(FUNCTIONS)))}
        validate_model(make_model(starts))
        def objective(values):
            model = make_model(values)
            loss = 0.0
            for r,k in data:
                p = np.clip(predict(model, self._world.catalogs[r["stage"]], r["assortment"], tuple(map(int,r["site"]))), 1e-6,1-1e-6)
                loss -= k*math.log(p)+(r["n"]-k)*math.log(1-p)
            return loss
        trials = [np.array(starts)]
        rng = np.random.default_rng(0)
        trials += [np.array([rng.uniform(lo,hi) for lo,hi in bounds]) for _ in range(2)]
        fitted = [minimize(objective,start,method="L-BFGS-B",bounds=bounds,options={"maxiter":150}) for start in trials]
        best = min(fitted,key=lambda fit:fit.fun)
        model = make_model(best.x)
        result = {"candidate_id": len(self.candidates), "model": model,
                  "parameters": {name:round(float(x),6) for name,x in zip(names,best.x)},
                  "optimizer_success": bool(best.success), "template": text, **self._check_model(model)}
        self.candidates.append(copy.deepcopy(result))
        return result

    def _suggest_probe(self, idx):
        model = self._candidate(idx)["model"]
        seen = [r["result"] for r in self.receipts]
        catalog = self._world.catalogs["source"]
        ids = [p["id"] for p in catalog]
        existing = {tuple(sorted(r["assortment"])) for r in seen if r["stage"]=="source"}
        anchors = [r for r in seen if r["stage"]=="source"]
        candidates = []
        for flags in itertools.product((0,1),repeat=len(ids)):
            arm = [pid for pid,f in zip(ids,flags) if f]
            if tuple(sorted(arm)) in existing:
                continue
            p = predict(model,catalog,arm,(0,0))
            for anchor in anchors:
                p0 = predict(model,catalog,anchor["assortment"],(0,0))
                if abs(p-p0) <= 0.02:
                    distance = len(set(arm).symmetric_difference(anchor["assortment"]))
                    # A truth-free coverage objective: large, untested alteration
                    # under the current program's invariant prediction, per cost.
                    score = distance * distance / (1+len(arm)+4)
                    candidates.append((score,len(arm),arm,p,anchor["experiment_id"]))
        if not candidates:
            return {"status":"no_unqueried_near_invariant_found"}
        candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
        score,_,arm,p,anchor = candidates[0]
        return {"assortment":arm,"stage":"source","site":"00","n":400,
                "verified_supply":True,"verified_meter":True,"prediction":round(p,6),
                "rationale":f"候选 {idx} 对实验 {anchor} 与此转换预测近似相同；检验尚未覆盖的预测不变前提。",
                "selection_note":"score is a coverage heuristic, not true EIG or a promised effect"}

    def _receipt(self, idx):
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(self.receipts):
            raise ValueError("unknown experiment_id")
        return self.receipts[idx]

    def _experiment(self, args):
        assortment = args.get("assortment", [])
        stage, site = args.get("stage", "source"), args.get("site", "00")
        n = args.get("n", 400)
        if stage not in {"source", "adaptation"}:
            raise ValueError("only source/adaptation may be queried")
        if stage == "adaptation" and not self.transfer_open:
            raise ValueError("open_transfer first")
        if site not in {"00", "10", "01", "11"} or (stage == "source" and site != "00"):
            raise ValueError("illegal site")
        if (not isinstance(assortment, list) or any(not isinstance(i, str) for i in assortment)
                or len(set(assortment)) != len(assortment)
                or any(pid not in self._world.roles[stage] for pid in assortment)):
            raise ValueError("unknown or duplicate product ID")
        if isinstance(n, bool) or not isinstance(n, int) or not 100 <= n <= 800:
            raise ValueError("n must be 100..800")
        frozen = args.get("prediction")
        if isinstance(frozen, bool) or not isinstance(frozen, (float, int)) or not math.isfinite(frozen) or not 0 <= frozen <= 1:
            raise ValueError("freeze a numeric prediction before execution")
        if not isinstance(args.get("rationale"), str) or not args["rationale"].strip():
            raise ValueError("explain the evidence sought before execution")
        supply, meter = args.get("verified_supply", False), args.get("verified_meter", False)
        if not isinstance(supply, bool) or not isinstance(meter, bool):
            raise ValueError("verification flags must be boolean")
        self._reserve(sessions=n, arms=1, cost=1 + len(assortment) + 2 * supply + 2 * meter)
        idx = len(self.receipts)
        ext = tuple(map(int, site))
        p = self._world.probability(stage, assortment, ext)
        # Design-keyed streams support paired method comparisons without reuse as
        # independent evidence. Repeating one design draws a new repeat stream.
        design = json.dumps([stage, site, sorted(assortment), n, supply, meter])
        repeat = sum(r["design"] == design for r in self.receipts)
        digest = hashlib.sha256(f"{self._world.seed}:{design}:{repeat}".encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        demand = int(rng.binomial(n, p))
        opening = n if supply or self._world.fault != "supply" else math.floor(0.3 * n)
        sales = min(demand, opening)
        observed = min(sales, math.floor(0.3 * n)) if self._world.fault == "report" and not meter else sales
        result = {"experiment_id": idx, "n": n, "observed_sales": observed,
                  "observed_rate": observed / n, "frozen_prediction": frozen,
                  "assortment": assortment.copy(), "site": site, "stage": stage,
                  "verified_supply": supply, "verified_meter": meter,
                  "measurement_state": "mature", "independence_group": f"cohort-{idx}",
                  "sampling_note": "销量在默认模式下可受库存/计数影响；二项估计须先确认该影响。"}
        self.receipts.append({"result": copy.deepcopy(result), "true_sales": sales,
                              "physical_opening": opening, "design": design})
        return result


def private_score(lab):
    """Only the evaluator invokes this, after the agent finishes."""
    if lab.final is None:
        raise ValueError("no frozen model")
    world, model = lab._world, lab.final["model"]
    measured = {(r["result"]["stage"], r["result"]["site"],
                 tuple(sorted(r["result"]["assortment"]))) for r in lab.receipts}
    scores = {}
    for namespace in ("source", "heldout"):
        ids = [p["id"] for p in world.catalogs[namespace]]
        errors, causal_effect_errors = [], []
        sites = ["00"] if namespace == "source" else ["00", "10", "01", "11"]
        for site in sites:
            ext = tuple(map(int, site))
            for flags in itertools.product((0, 1), repeat=len(ids)):
                assortment = [pid for pid, flag in zip(ids, flags) if flag]
                if (namespace, site, tuple(sorted(assortment))) in measured:
                    continue
                predicted = predict(model, world.catalogs[namespace], assortment, ext)
                true = world.probability(namespace, assortment, ext)
                errors.append((predicted - true) ** 2)
                p0 = predict(model, world.catalogs[namespace], [], ext)
                t0 = world.probability(namespace, [], ext)
                causal_effect_errors.append(((predicted - p0) - (true - t0)) ** 2)
        scores[namespace + "_probability_rmse"] = math.sqrt(float(np.mean(errors)))
        scores[namespace + "_effect_rmse"] = math.sqrt(float(np.mean(causal_effect_errors)))
        scores[namespace + "_conditions"] = len(errors)
    scores["used"] = lab.used.copy()
    # Identifiable operational signatures, not labels for latent psychology.
    catalog=world.catalogs["heldout"]
    h=next(p["id"] for p in catalog if world.roles["heldout"][p["id"]]==(1,0))
    u=next(p["id"] for p in catalog if world.roles["heldout"][p["id"]]==(0,1))
    combo=next(p["id"] for p in catalog if world.roles["heldout"][p["id"]]==(1,1))
    unrelated=[p["id"] for p in catalog if world.roles["heldout"][p["id"]]==(0,0)]
    def signatures(function):
        p00=function([], (0,0));ph=function([h],(0,0));pu=function([u],(0,0));pb=function([h,u],(0,0))
        return [ph-p00,pu-p00,pb-ph-pu+p00,function([combo],(0,0))-pb,
                function([h,u,unrelated[0]],(0,0))-pb,function([h,u]+unrelated[:2],(0,0))-pb,
                function([u],(1,0))-function([h,u],(1,0)),function([h],(0,1))-function([h,u],(0,1)),
                function([u],(1,0))-function([],(1,0)),function([h],(0,1))-function([],(0,1))]
    estimated=signatures(lambda arm,ext:predict(model,catalog,arm,ext))
    true=signatures(lambda arm,ext:world.probability("heldout",arm,ext))
    error=np.array(estimated)-np.array(true)
    scores["signature_names"]=["heat_effect","utensils_effect","interaction","combo_equivalence",
                              "one_extra_item","two_extra_items","external_heat_equivalence",
                              "external_utensils_equivalence","utensils_effect_with_external_heat",
                              "heat_effect_with_external_utensils"]
    scores["estimated_signature"]=estimated
    scores["true_signature"]=true
    scores["signature_rmse"]=float(np.sqrt(np.mean(error**2)))
    scores["signature_max_error"]=float(np.max(np.abs(error)))
    scores["operational_identification_pass_5pp"]=bool(scores["signature_max_error"]<=.05 and scores["heldout_effect_rmse"]<=.05)
    scores["private_family"] = world.family
    scores["private_fault"] = world.fault
    scores["note"] = "conditional fixture / selected seeds; not a population or real-world claim"
    return scores


def var(name):
    return {"var": name}


def op(name, *args):
    return {"op": name, "args": list(args)}


def model_with(expression):
    return {"role_patterns": {"heating": ["加热"], "utensils": ["餐具"]},
            "expression": expression}


def factorial_expression(table, include_external=True):
    """Saturated role-cell interpolation; not restricted to an AND/OR label."""
    h = op("max", var("heat"), var("external_heat")) if include_external else var("heat")
    u = op("max", var("utensils"), var("external_utensils")) if include_external else var("utensils")
    return op("add", table[0, 0], op("mul", table[1, 0] - table[0, 0], h),
              op("mul", table[0, 1] - table[0, 0], u),
              op("mul", table[1, 1] - table[1, 0] - table[0, 1] + table[0, 0], h, u))
