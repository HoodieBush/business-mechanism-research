"""Freeze common scientific capabilities and a bounded actor task matrix."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from conditional_memory import validate_archive

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1]


def launch(spec):
    if spec["runner"]!="run_scientific":raise ValueError("wrong runner")
    for name in ("seeds","families","profiles","strategies"):
        if not spec[name] or len(set(spec[name]))!=len(spec[name]):raise ValueError("empty or duplicate dimension")
    if not set(spec["strategies"])<={"numeric_scoped","numeric_review","llm_scientific","llm_state_aware"} or not set(spec["profiles"])<={"staggered","interruptions"} or not set(spec["families"])<={"source_joint","threeway","mixed_scope","null"}:raise ValueError("invalid task or policy")
    if type(spec["deadline"]) is not int or spec["deadline"]<1 or type(spec["price"]) not in (int,float) or not 6<=spec["price"]<=12:raise ValueError("invalid allocation/context")
    if spec["limits"]!={"sessions":14400,"arms":24,"cost":276,"logical_time":spec["deadline"],"tool_calls":200,"scientific_actions":64,"api_calls":16,"api_tokens":80000}:raise ValueError("common caps mismatch")
    if spec["statistical_protocol"]!={"max_checks":6,"cohorts_per_check":2,"n_per_cohort":800,"total_alpha":.05,"tolerance":.05,"max_revisions":2,"caller_may_stop_early":True}:raise ValueError("analysis mismatch")
    if spec["api_max_output_tokens"]!=1600:raise ValueError("output cap mismatch")
    if spec.get("terminal_policy","received_only") not in {"received_only","settle_committed"}:raise ValueError("invalid terminal receipt policy")
    expected_actor={"real_function_submissions_per_response":[1,3],"execution_order":"returned_order","validate_all_envelopes_before_execution":True,"feedback":"each real tool_call_id","recent_complete_turns":2,"narrative_json_extraction":False,"truncation_repair":False,"missing_field_repair":False}
    if "actor_protocol" in spec and spec["actor_protocol"]!=expected_actor:raise ValueError("actor protocol mismatch")
    if "context_contract" in spec:
        from public_context import VERSION
        expected={"encoding":VERSION,"exact_roundtrip_before_request":True,"candidate_references":"identical current immutable summaries only",
            "job_id_type":"integer","public_fitted_candidates":6,"confirmation_reserve":"advisory 3 request opportunities, 1600 sessions, 2 cohorts; all scientific actions remain available"}
        if spec["context_contract"]!=expected:raise ValueError("public context contract mismatch")
    if "scientific_bundles" in spec and spec["scientific_bundles"]!={"shared_tools":["sample_and_analyze","confirm_and_analyze"],"scientific_action_charge":3,"implicit_revision":False,"implicit_stop":False,"api_event_prefix_committed":True}:raise ValueError("scientific bundle contract mismatch")
    if "native_functions" in spec and spec["native_functions"]!={"one_function_per_service":True,"flat_rationale_and_expected_gap":True,"all_batch_submissions_prevalidated":True,"whole_object_fallback":["tool","arguments"],"coercion_or_repair":False}:raise ValueError("native function contract mismatch")
    if "state_aware_protocol" in spec:
        from scientific_readiness import VERSION as RV
        from research_notebook import VERSION as NV
        expected={"readiness_version":RV,"notebook_version":NV,"input":"public state and successful public read receipts only","mask":"necessary public preconditions and terminal action reserve; no scientific quality mask",
            "per_action_recheck":True,"failed_precondition":"no gateway/sample execution, API attempt retained","cached_source_counts_pooled":False,"implicit_scientific_rescue":False}
        if spec["state_aware_protocol"]!=expected:raise ValueError("state-aware protocol mismatch")
    phase=spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",phase):raise ValueError("invalid phase")
    output=ROOT/"results"/phase;snapshot=ROOT/"snapshots"/phase
    if output.exists() or snapshot.exists():raise ValueError("phase exists")
    memory=(PROJECT/spec["memory_archive"]).resolve()
    if not memory.is_relative_to(PROJECT):raise ValueError("memory must be a project public archive")
    value=validate_archive(json.loads(memory.read_text()))
    spec_file=(PROJECT/"configs"/spec["specification_file"]).resolve()
    if not spec_file.is_relative_to(PROJECT/"configs") or json.loads(spec_file.read_text())!=spec:raise ValueError("specification mismatch")
    tasks=[dict(seed=s,family=f,profile=p,strategy=m) for s in spec["seeds"] for f in spec["families"] for p in spec["profiles"] for m in spec["strategies"]]
    command=[sys.executable,str(ROOT/"run_scientific.py"),"--phase",phase,"--workers",str(spec.get("workers",1)),"--price",str(spec["price"]),"--deadline",str(spec["deadline"]),"--memory-archive",str(memory)]
    for name in ("seeds","families","profiles","strategies"):command.extend(["--"+name,",".join(map(str,spec[name]))])
    command.extend(["--terminal-policy",spec.get("terminal_policy","received_only")])
    files=list(ROOT.glob("*.py"))+[PROJECT/"configs/base_model.json",PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt",memory,spec_file]
    hashes={}
    for p in files:
        rel=p.relative_to(PROJECT);q=snapshot/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q);hashes[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    manifest={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"creation_timing":"before_launch","specification":spec,
        "planned_tasks":tasks,"expected_runs":len(tasks),"source_sha256":hashes,"command_argv":command,
        "snapshot":str(snapshot.relative_to(PROJECT)),"public_archive_id":value["archive_id"],"status":"prepared"}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");(snapshot/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    try:
        for p in ROOT.glob("*.py"):compile(p.read_text(),str(p),"exec")
    except SyntaxError as error:
        manifest.update(status="preflight_failed",exit_code=1,observed_runs=0,preflight={"syntax_passed":False,"error":str(error)})
        (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return 1
    checks=subprocess.run([sys.executable,"-m","unittest","discover","-q"],cwd=ROOT,env=env,text=True,capture_output=True)
    (output/"preflight-tests.log").write_text(checks.stdout+checks.stderr)
    manifest["preflight"]={"syntax_passed":True,"unit_test_exit_code":checks.returncode,"log":"preflight-tests.log"}
    if checks.returncode:
        manifest.update(status="preflight_failed",exit_code=checks.returncode,observed_runs=0)
        (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return checks.returncode
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    process=subprocess.run(command,cwd=ROOT,env=env,check=False)
    manifest.update(status="runner_exited",exit_code=process.returncode,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        observed_runs=sum((output/f"{t['strategy']}_{t['family']}_{t['profile']}_s{t['seed']}.json").exists() for t in tasks))
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return process.returncode
