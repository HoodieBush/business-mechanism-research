"""Public, content-addressed conditional mechanism memory.

No generator, private result reader or scorer is imported here. Source evidence
suggests structures; it never augments a target likelihood or certifies transfer.
"""
from __future__ import annotations
import copy
import hashlib
import itertools
import json
import math

import numpy as np

from confirmation import assess
from lab import VARIABLES,compile_expression,evaluate,predict,validate_model
from mechanism_state import card
from replay_evidence import ReplayEvidence
from symbolic import features

VERSION="conditional-memory-v0.1-public-dependencies"
CONTEXT_KEYS=("target","operating_objective","fact_contract","deployment_contract")


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def context(public_input):
    return {k:copy.deepcopy(public_input[k]) for k in CONTEXT_KEYS}


def text(node):
    """Serialize the small arithmetic AST, without evaluating source code."""
    if type(node) in (int,float):return repr(node)
    if set(node)=={"var"}:return node["var"]
    op=node["op"];args=[text(a) for a in node["args"]]
    if op in {"sigmoid","min","max"}:return op+"("+",".join(args)+")"
    return "("+{"add":"+","sub":"-","mul":"*"}[op].join(args)+")"


def coefficient_template(model):
    """Extract coefficients only; preserve clamp and feature/hinge constants.

    Only additive linear/logit models have this adapter. Other safe programs
    remain archived with an explicit unsupported-template status.
    """
    validate_model(model);variables=VARIABLES|(set(model["role_patterns"])-{"heating","utensils"})
    tree=compile_expression(model["expression"],variables=variables) if isinstance(model["expression"],str) else copy.deepcopy(model["expression"])
    link=None;inner=tree
    if isinstance(tree,dict) and tree.get("op")=="sigmoid":link="logit";inner=tree["args"][0]
    elif isinstance(tree,dict) and tree.get("op")=="min" and tree["args"][0]==.95:
        lower=tree["args"][1]
        if isinstance(lower,dict) and lower.get("op")=="max" and lower["args"][0]==.05:
            link="linear";inner=lower["args"][1]
    if link is None:raise ValueError("memory template adapter requires additive linear/logit model")
    def constant(node):
        if type(node) in (int,float):return float(node)
        if not isinstance(node,dict) or "var" in node:return None
        values=[constant(a) for a in node["args"]]
        return evaluate(node,{}) if all(v is not None for v in values) else None
    def flatten(node,sign=1):
        if isinstance(node,dict) and node.get("op")=="add":
            return [t for a in node["args"] for t in flatten(a,sign)]
        if isinstance(node,dict) and node.get("op")=="sub":
            return flatten(node["args"][0],sign)+flatten(node["args"][1],-sign)
        return [(sign,node)]
    intercept=0.;terms=[];coefs=[]
    for sign,node in flatten(inner):
        c=constant(node)
        if c is not None:intercept+=sign*c;continue
        if not isinstance(node,dict) or node.get("op")!="mul" or constant(node["args"][0]) is None:
            raise ValueError("unsupported non-coefficient term in memory model")
        c=sign*constant(node["args"][0]);rest=node["args"][1:]
        atom=rest[0] if len(rest)==1 else {"op":"mul","args":rest}
        terms.append(text(atom));coefs.append(c)
    if len(terms)>7:raise ValueError("memory template exceeds shared eight-parameter contract")
    lo,hi=(-6.,6.) if link=="logit" else (-1.,1.)
    params={"m0":[intercept,-6.,6.] if link=="logit" else [intercept,.05,.95]}
    pieces=["m0"]
    for i,(atom,value) in enumerate(zip(terms,coefs),1):
        params[f"m{i}"]=[value,lo,hi];pieces.append(f"m{i}*({atom})")
    raw="+".join(pieces)
    template="sigmoid("+raw+")" if link=="logit" else "min(0.95,max(0.05,"+raw+"))"
    return {"expression":template,"parameters":params,"terms":terms,"link":link}


def export_episode(public_input,facts,events,versions,checks,used):
    """Export whitelisted public evidence and conditional claims, not a result."""
    # The caller passes these individual objects, never private configuration,
    # deployment truth, scores, model requests or filesystem source names.
    view=ReplayEvidence(public_input,events);patterns=facts["role_patterns"]
    evidence=[];by_id={}
    for r,k in view.verified_observations():
        payload={"source_experiment_id":r["experiment_id"],"stage":r["stage"],"site":r["site"],
            "n":r["n"],"verified_sales":k,"supply_verified":True,"meter_verified":True,
            "features":features(patterns,view.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"]))),
            "frozen_prediction":r["frozen_prediction"],"validity":"verified"}
        item={"evidence_id":digest(payload),**payload};evidence.append(item);by_id[r["experiment_id"]]=item
    frozen=[v for v in versions if v["phase"]=="confirmation_model_frozen"]
    if not frozen:raise ValueError("source has no frozen research model")
    model=frozen[-1]["model"];source_card=card(model,facts["ontology"],versions,checks)
    historical=[]
    for c in checks:
        rows=[by_id[i] for i in c.get("experiment_ids",[c["experiment_id"]])]
        expected=assess(sum(r["verified_sales"] for r in rows),sum(r["n"] for r in rows),c["frozen_prediction"],
            max_checks=c.get("max_checks",4))
        if expected["state"]!=c["state"] or expected["exact_probability_interval"]!=c["exact_probability_interval"]:
            raise ValueError("source confirmation disagrees with public counts")
        v=next(v for v in frozen if v["round"]==c["round"])
        if set(v["training_evidence_ids"])&set(c.get("experiment_ids",[c["experiment_id"]])):
            raise ValueError("source confirmation entered its own fitted model")
        historical.append({"round":c["round"],"model_instance_id":digest(v["model"]),"features":rows[0]["features"],
            "state":c["state"],"exact_probability_interval":c["exact_probability_interval"],
            "frozen_prediction":c["frozen_prediction"],"dependencies":[r["evidence_id"] for r in rows]})
    claims=[]
    for c in source_card["conditional_claims"]:
        rows=[by_id[i] for i in c["experiment_ids"]]
        if any(r["features"]!=rows[0]["features"] for r in rows):raise ValueError("source pooled check changes condition")
        claim={"features":rows[0]["features"],"state":c["state"],"n":c["n"],
            "frozen_prediction":c["frozen_prediction"],"tolerance":c["tolerance"],
            "exact_probability_interval":c["exact_probability_interval"],
            "dependencies":[r["evidence_id"] for r in rows]}
        claims.append({"claim_id":digest(claim),**claim})
    lineage=[{"round":v["round"],"model":copy.deepcopy(v["model"]),
        "training_dependencies":[by_id[i]["evidence_id"] for i in v["training_evidence_ids"]],
        "check_states":[c["state"] for c in checks if c["round"]==v["round"]]} for v in frozen]
    try:template=coefficient_template(model);template_error=None
    except ValueError as error:template=None;template_error=str(error)
    body={"public_context":context(public_input),"physical_definitions":copy.deepcopy(facts["ontology"]),
        "source_model":copy.deepcopy(model),"source_state":source_card["state"],
        "conditional_claims":claims,"historical_checks":historical,"evidence":evidence,"version_lineage":lineage,
        "template":template,"template_error":template_error,"source_cost":copy.deepcopy(used),
        "untested_scope_state":"unresolved_extrapolation",
        "transfer_contract":"结构候选；目标参数仅用目标已释放证据拟合。源检查不提供目标认证，未测条件仍未决。"}
    return {"episode_id":digest(body),**body}


def archive(episodes):
    if not episodes or len({e["episode_id"] for e in episodes})!=len(episodes):raise ValueError("empty or duplicate public memory episodes")
    episodes=sorted(copy.deepcopy(episodes),key=lambda e:e["episode_id"])
    body={"version":VERSION,"episodes":episodes,"source_acquisition_cost":{k:sum(e["source_cost"][k] for e in episodes) for k in ("sessions","arms","cost")}}
    return {"archive_id":digest(body),**body}


def validate_archive(value):
    if set(value)!={"archive_id","version","episodes","source_acquisition_cost"} or value["version"]!=VERSION:
        raise ValueError("unrecognized memory archive contract")
    if value["archive_id"]!=digest({k:v for k,v in value.items() if k!="archive_id"}):raise ValueError("memory archive hash mismatch")
    if not value["episodes"] or len(value["episodes"])>64 or len({e["episode_id"] for e in value["episodes"]})!=len(value["episodes"]):
        raise ValueError("invalid memory episode matrix")
    expected_keys={"episode_id","public_context","physical_definitions","source_model","source_state","conditional_claims",
        "historical_checks","evidence","version_lineage","template","template_error","source_cost","untested_scope_state","transfer_contract"}
    for episode in value["episodes"]:
        if set(episode)!=expected_keys or set(episode["public_context"])!=set(CONTEXT_KEYS):raise ValueError("unrecognized public episode fields")
        body={k:v for k,v in episode.items() if k!="episode_id"}
        if episode["episode_id"]!=digest(body):raise ValueError("memory episode hash mismatch")
        known={r["evidence_id"]:r for r in episode["evidence"]}
        if len(known)!=len(episode["evidence"]):raise ValueError("duplicate source evidence identity")
        for r in known.values():
            if r["evidence_id"]!=digest({k:v for k,v in r.items() if k!="evidence_id"}):raise ValueError("source evidence hash mismatch")
        for c in episode["conditional_claims"]:
            if c["claim_id"]!=digest({k:v for k,v in c.items() if k!="claim_id"}):raise ValueError("source claim hash mismatch")
            if not c["dependencies"] or not set(c["dependencies"])<=set(known):raise ValueError("dangling source claim dependency")
        validate_model(episode["source_model"])
    if value["source_acquisition_cost"]!={k:sum(e["source_cost"][k] for e in value["episodes"]) for k in ("sessions","arms","cost")}:
        raise ValueError("source acquisition cost disagrees with episodes")
    return copy.deepcopy(value)


class ConditionalMemory:
    """A per-target view; immutable source archive plus append-only target states."""
    def __init__(self,value,public_input,facts,mode="scoped"):
        if mode not in {"scoped","unscoped","disabled"}:raise ValueError("unknown memory policy")
        self.archive=validate_archive(value);self.mode=mode;self.facts=copy.deepcopy(facts)
        self.withdrawn=set();self.updates=[];self.target_links=[];self.diagnostics=[];self.entries=[]
        for e in self.archive["episodes"]:
            reasons=[]
            if e["public_context"]!=context(public_input):reasons.append("public_context_changed")
            if e["physical_definitions"]!=facts["ontology"]:reasons.append("physical_definitions_changed")
            if not any(c["state"]=="supported_within_tolerance" for c in e["conditional_claims"]):reasons.append("no_supported_source_condition")
            if e["template"] is None:reasons.append("template_not_supported")
            compatible=set(e["physical_definitions"])<=set(facts["ontology"])
            eligible=mode!="disabled" and compatible and e["template"] is not None and (mode=="unscoped" or not reasons)
            self.entries.append({"episode":e,"eligible":eligible,"retrieval":{
                "episode_id":e["episode_id"],"source_state":e["source_state"],"scope_flags":reasons,
                "status":"candidate_requires_target_validation" if eligible else "not_reused",
                "source_conditions":[{k:copy.deepcopy(c[k]) for k in ("claim_id","features","state","dependencies")} for c in e["conditional_claims"]],
                "target_evidence_status":"unconfirmed","source_data_pooled":False}})

    def invalidate_evidence(self,evidence_id,reason):
        known={r["evidence_id"] for e in self.archive["episodes"] for r in e["evidence"]}
        if evidence_id not in known:raise ValueError("unknown source evidence")
        self.withdrawn.add(evidence_id)
        affected=[]
        for entry in self.entries:
            e=entry["episode"];deps=set(e["version_lineage"][-1]["training_dependencies"])
            deps|={d for c in e["conditional_claims"] for d in c["dependencies"]}
            if evidence_id in deps:
                entry["eligible"]=False;entry["retrieval"]["status"]="stale_requires_source_review";affected.append(e["episode_id"])
        for v in self.target_links:
            if set(v["memory_episode_refs"])&set(affected):
                v["source_dependency_state"]="stale_requires_review"
        update={"sequence":len(self.updates),"evidence_id":evidence_id,"reason":reason,"affected_episodes":affected}
        self.updates.append(update);return copy.deepcopy(update)

    def fit_candidates(self,lab):
        data=lab.verified_observations();n=sum(r["n"] for r,_ in data);candidates=[];groups={}
        for entry in self.entries:
            if not entry["eligible"]:continue
            t=entry["episode"]["template"];groups.setdefault(digest({"expression":t["expression"],"terms":t["terms"]}),[]).append(entry)
        rows=[features(self.facts["role_patterns"],lab.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"]))) for r,_ in data]
        for entries in groups.values():
            t=entries[0]["episode"]["template"];trees=[compile_expression(a,variables=set(rows[0])) for a in t["terms"]]
            x=np.array([[1.]+[evaluate(tree,r) for tree in trees] for r in rows])
            # Source variation cannot manufacture target parameter identification.
            if np.linalg.matrix_rank(x)<x.shape[1]:continue
            args={k:copy.deepcopy(t[k]) for k in ("expression","parameters")};args["role_patterns"]=self.facts["role_patterns"]
            fit=lab.call("fit_candidate",args);deviance=0.;residuals=[]
            for r,k in data:
                p=min(1-1e-6,max(1e-6,predict(fit["model"],lab.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"])))))
                if k:deviance+=2*k*math.log(k/(r["n"]*p))
                if r["n"]>k:deviance+=2*(r["n"]-k)*math.log((r["n"]-k)/(r["n"]*(1-p)))
                residuals.append(abs((k-r["n"]*p)/math.sqrt(r["n"]*p*(1-p))))
            refs=[e["episode"]["episode_id"] for e in entries];rank=len(args["parameters"])
            candidates.append({"model":fit["model"],"terms":t["terms"],"rank":rank,"bic":deviance+rank*math.log(n),
                "deviance":deviance,"max_residual":max(residuals),"optimizer_success":fit["optimizer_success"],
                "origin":"conditional_memory","memory_episode_refs":refs,"target_training_ids":[r["experiment_id"] for r,_ in data]})
        return candidates

    def prior_predictions(self,lab,action):
        records=[]
        for entry in self.entries:
            if not entry["eligible"]:continue
            e=entry["episode"];model={"expression":e["source_model"]["expression"],"role_patterns":self.facts["role_patterns"]}
            f=features(self.facts["role_patterns"],lab.public_catalog(action["stage"]),action["assortment"],tuple(map(int,action["site"])))
            matches=[c for c in e["conditional_claims"] if c["features"]==f]
            source_state="unresolved_extrapolation" if not matches else (
                "contradicted" if any(c["state"]=="contradicted" for c in matches) else
                "supported_within_tolerance" if all(c["state"]=="supported_within_tolerance" for c in matches) else "inconclusive")
            records.append({"episode_id":e["episode_id"],"prediction":predict(model,lab.public_catalog(action["stage"]),action["assortment"],tuple(map(int,action["site"]))),
                "features":f,"source_condition_state":source_state,"matching_claim_refs":[c["claim_id"] for c in matches]})
        return records

    def observe_prior_predictions(self,predictions,response,max_checks):
        for prior in predictions:
            check=assess(response["observed_sales"],response["n"],prior["prediction"],max_checks=max_checks)
            self.diagnostics.append({**prior,**check,"target_experiment_id":response["experiment_id"],
                "interpretation":"旧参数的新任务条件检查；反驳要求重新估参/研究，不自动否定结构或源任务证据。"})

    def record_target_version(self,best,training_ids,round_index,checks):
        self.target_links.append({"round":round_index,"instance_id":digest(best["model"]),
            "origin":best.get("origin","unknown"),"memory_episode_refs":best.get("memory_episode_refs",[]),
            "source_dependency_state":"active_proposal_only",
            "target_training_ids":list(training_ids),"target_check_ids":[i for c in checks for i in c["experiment_ids"]],
            "state":"refuted_in_target_conditions" if any(c["state"]=="contradicted" for c in checks) else
                "supported_in_target_conditions" if all(c["state"]=="supported_within_tolerance" for c in checks) else "pending_target_confirmation"})

    def trace(self):
        return {"archive_id":self.archive["archive_id"],"mode":self.mode,
            "source_acquisition_cost_shared":copy.deepcopy(self.archive["source_acquisition_cost"]),
            "retrieval":[copy.deepcopy(e["retrieval"]) for e in self.entries],
            "evidence_updates":copy.deepcopy(self.updates),"target_versions":copy.deepcopy(self.target_links),
            "prior_parameter_checks":copy.deepcopy(self.diagnostics),
            "target_likelihood_uses_source_counts":False}
