"""Freeze a small development matrix, run genuine role interactions, retain failures."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from world import OfficeWorld
from workspace import ResearchWorkspace, sha, write_json
from team import ResearchTeam, BudgetStop, usage_summary, decode_actions, SCHEMAS

ROOT = Path(__file__).resolve().parents[2]


def import_legacy_checkpoint(parent, ws):
    """Resume an interrupted old synchronous manager→specialist dispatch.

    All old messages stay exact; a factual path notice is appended. No new
    hypothesis or scientific result is fabricated to prime the model.
    """
    records=[json.loads(l) for l in (parent/"model_calls.jsonl").read_text().splitlines()]
    starts=[json.loads(l) for l in (parent/"requests_started.jsonl").read_text().splitlines()]
    child=starts[-1]["role"]
    task=next(t for t in reversed(ws.state["tasks"]) if t['role']==child)
    ancestor=next(r for r in reversed(records) if r['role']=='manager' and any(c.get('function',{}).get('name')=='assign_task' for c in r.get('response',{}).get('choices',[{}])[0].get('message',{}).get('tool_calls',[])))
    raw=ancestor['response'];message=raw['choices'][0]['message'];calls=message['tool_calls']
    assistant={'role':'assistant','content':message.get('content') or '', 'tool_calls':[{k:c[k] for k in ('id','type','function')} for c in calls]}
    actions=decode_actions(raw,'manager',SCHEMAS)
    if len(actions)!=1 or actions[0]['tool']!='assign_task':raise ValueError('legacy import supports one interrupted dispatch only')
    prefix='ancestor_'+parent.parent.name+'_'+str(ancestor['request_index'])
    manager_messages=ancestor['request']['messages']+[assistant]
    child_messages=starts[-1]['request']['messages']+[{"role":"user","content":json.dumps({'resumption_notice':'继续原任务，已有代码/数据/查询均原样保留，刚才中断未产生工具结果。系统负责连接重试。旧引用可用read_artifact映射，新Python使用本次环境目录。','path_mapping':ws.path_aliases,'PUBLIC_DIR':str(ws.public),'ARTIFACT_DIR':str(ws.shared),'WORK_DIR':str(ws.workers[child].directory)},ensure_ascii=False)}]
    pending={'record_index':ancestor['request_index'],'prefix':prefix,'calls':calls,'actions':actions,'index':0,'results':[], 'known_hypotheses':[h['id'] for h in ws.state['hypotheses']],'known_algorithms':['baseline']+[a['id'] for a in ws.state['algorithms']],'known_files':[str(p.resolve()) for base in (ws.public,ws.shared) for p in base.rglob('*') if p.is_file()]}
    frames={'manager':{'role':'manager','task':{'question':'继续原研究主管任务','inputs':[]},'status':'running','messages':manager_messages,'pending':pending},child:{'role':child,'task':task,'status':'running','messages':child_messages,'pending':None}}
    write_json(ws.root/'team_checkpoint.json',{'version':'team-checkpoint-v1','frames':frames,'role_dispatches':{'manager':1,child:1},'legacy_source':str(parent),'legacy_request_awaiting_response':starts[-1]['request_index']})
    action=actions[0];key=prefix+'_manager_0'
    signature=hashlib.sha256(json.dumps(['manager',action['tool'],action['arguments']],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    write_json(ws.root/'tool_receipts'/(key+'.json'),{'id':key,'signature':signature,'status':'prepared','role':'manager','tool':'assign_task','args':action['arguments'],'task_id':task['id']})


def run(specification, resume=False):
    spec = json.loads(Path(specification).read_text())
    output = ROOT / "experiments/business_team/results" / spec["phase"]
    if resume and not (output/'manifest.json').exists():raise ValueError('resume requires existing phase manifest')
    if output.exists() and not resume:
        raise ValueError("result phase exists; never overwrite")
    output.mkdir(parents=True,exist_ok=True)
    preflight = subprocess.run([sys.executable, "-m", "unittest", "-v", "test_business_team.py"], cwd=Path(__file__).parent, capture_output=True, text=True)
    preflight_name='preflight-resume-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'.log' if resume else 'preflight-tests.log'
    (output / preflight_name).write_text(preflight.stdout + preflight.stderr)
    if preflight.returncode:
        write_json(output / "manifest.json", {"specification": spec, "status": "preflight_failed", "planned_cases": len(spec["cases"]), "api_calls": 0})
        raise RuntimeError("preflight failed; no paid calls")
    config = json.loads((ROOT / "configs/base_model.json").read_text())
    config["request_timeout_seconds"] = spec.get("request_timeout_seconds", 90)
    files = list(Path(__file__).parent.glob("*.py")) + [Path(specification).resolve(), ROOT/"configs/base_model.json", ROOT/"environment.yml", ROOT/"configs/business-team-osx-arm64.lock.txt",
            ROOT/"experiments/capability_lab/model_protocol.py", ROOT/"experiments/capability_lab/model_credentials.py"]
    for case in spec["cases"]:
        if case.get("import_analyst_from"):
            parent = ROOT/case["import_analyst_from"]
            files.extend(p for p in parent.glob("*") if p.is_file() and p.suffix in (".py",".csv",".json",".md",".png"))
            files.append(parent.parent.parent/"public/history.csv")
        if case.get('resume_from'):
            parent=ROOT/case['resume_from']
            files.extend(p for base in (parent/'public',parent/'artifacts') for p in base.rglob('*') if p.is_file() and not any(part in ('tmp','.matplotlib') for part in p.relative_to(parent).parts))
            files.extend([parent/'model_calls.jsonl',parent/'requests_started.jsonl',parent.parent/'manifest.json'])
    snapshot = output / "snapshot"
    hashes = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        if not resume:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        hashes[str(relative)] = sha(path)
    if resume:
        manifest=json.loads((output/'manifest.json').read_text())
        if spec!=manifest['specification'] or any(sha(ROOT/p)!=h for p,h in manifest['source_sha256'].items()):raise ValueError('resume requires identical frozen specification and sources')
        manifest['status']='running';manifest.setdefault('resumptions',[]).append(datetime.now(timezone.utc).isoformat())
    else:
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "creation_timing": "before any paid call",
                    "specification": spec, "source_sha256": hashes, "planned_cases": len(spec["cases"]), "status": "running", "cases": []}
    write_json(output / "manifest.json", manifest)
    global_usage = []
    for case in spec["cases"]:
        existing=next((r for r in manifest['cases'] if r['id']==case['id']),None)
        if resume and existing and existing['status'] not in ('interrupted','started'):
            log=output/case['id']/'model_calls.jsonl'
            if log.exists():global_usage.extend(json.loads(l) for l in log.read_text().splitlines())
            continue
        print(f"START {case['id']}", flush=True)
        record = {"id": case["id"], "status": "started"}
        team, ws = None, None
        try:
            case_root=output/case['id']
            parent=ROOT/case['resume_from'] if case.get('resume_from') else None
            reopen=resume and (case_root/'public/history.csv').exists()
            if parent and not reopen:
                parent_spec=json.loads((parent.parent/'manifest.json').read_text())['specification']
                previous=next(c for c in parent_spec['cases'] if c['id']==case['id'])
                if (previous['private_kind'],previous['seed'])!=(case['private_kind'],case['seed']):raise ValueError('continuation requires identical private environment')
            ws = ResearchWorkspace(case_root, OfficeWorld(case["private_kind"], case["seed"]),resume_from=parent if not reopen else None,reopen=reopen)
            if parent and not reopen:
                if sha(parent/'public/history.csv')!=sha(ws.public/'history.csv'):raise ValueError('continuation history changed')
                import_legacy_checkpoint(parent,ws)
            if case.get("import_analyst_from"):
                parent = ROOT/case["import_analyst_from"]
                if sha(parent.parent.parent/"public/history.csv")!=sha(ws.public/"history.csv"):
                    raise ValueError("continuation requires identical public history")
                copied=[]
                for source in sorted(parent.glob("*")):
                    if source.is_file() and source.suffix in (".py",".csv",".json",".md",".png"):
                        target=ws.public/"imported_analysis"/source.name
                        target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(source,target)
                        copied.append({"file":str(target),"parent_source":str(source.relative_to(ROOT)),"sha256":sha(source)})
                write_json(ws.public/"imported_analysis/index.json",{"note":"此前真实分析Agent未交付的代码/数据/输出，原样复制。需要复核并形成报告，不算新独立发现；源代码中旧路径应改为本次PUBLIC_DIR。", "files":copied})
            team = ResearchTeam(ws, config, {**spec["limits"],"round_reported_token_budget":spec["round_reported_token_budget"]}, global_usage,recovery=spec.get('recovery'))
            final = team.run_role("manager", {"question": "定位一个值得研究的具体业务/算法问题，真实派发专业角色完成分析、假说、验证和有依据的算法修改；需要时根据负反馈修订。交付清晰业务研究故事，明确最终选择的算法ID或baseline。", "inputs": []})
            record["manager_result"] = final
            record["status"] = "manager_finished" if final.get("selected_algorithm_id") else "manager_incomplete"
        except BudgetStop as error:
            record.update(status="budget_stopped", error=str(error))
        except KeyboardInterrupt:
            record.update(status='interrupted',error='explicit runner interrupt; preserve checkpoint, do not freeze selection or evaluate future dates')
        except Exception as error:
            record.update(status="execution_failed", error_type=type(error).__name__, error=str(error)[:3000])
        if team:
            record.update(usage=team.usage(), role_dispatches=team.dispatches,
                          role_calls={role: sum(c["role"]==role for c in team.calls) for role in team.dispatches})
        if ws and record['status']!='interrupted':
            selected = record.get("manager_result", {}).get("selected_algorithm_id")
            frozen = {"selected_algorithm_id": selected, "selection_source": "model" if selected else "no model selection; baseline evaluation only",
                      "hypotheses": ws.state["hypotheses"], "algorithms": ws.state["algorithms"], "event_count": len(ws.state["events"])}
            write_json(ws.root / "decision_freeze.json", frozen)  # no subsequent Actor requests
            try:
                selected_code = next((a["code_file"] for a in ws.state["algorithms"] if a["id"]==selected), str(ws.public/"baseline.py"))
                record["final_evaluation"] = {}
                for name, code in (("selected", selected_code), ("baseline",ws.public/"baseline.py"), ("numeric_refit",ws.public/"numeric_refit.py"), ("strong_numeric",ws.public/"strong_numeric.py")):
                    score = ws.evaluate_code(code, first_day=140, days=28, name="final_"+name)
                    score.pop("execution_receipt")
                    record["final_evaluation"][name] = score
                record["science_counts"] = {"hypotheses":len(ws.state["hypotheses"]), "parented_revisions":sum(bool(h.get("parent_id")) for h in ws.state["hypotheses"]),
                                            "new_trials":sum(e["kind"]=="supply_trial" for e in ws.state["experiments"]),
                                            "inventory_audits":sum(e["kind"]=="inventory_audit" for e in ws.state["experiments"]), "algorithm_versions":len(ws.state["algorithms"])}
                record["actual_specialist_results"] = [{"role": r["role"], "summary":r["summary"], "status":r.get("status","submitted"), "evidence_files":r.get("evidence_files",[])} for r in ws.state["results"]]
            except Exception as error:
                record["final_evaluation_error"] = str(error)[:3000]
            write_json(ws.root / "case_result.json", record)
        if existing:manifest['cases'].remove(existing)
        manifest["cases"].append(record)
        write_json(output / "manifest.json", manifest)
        print(f"END {case['id']} status={record['status']} tokens={record.get('usage',{}).get('total_tokens',0)}", flush=True)
        if record['status']=='interrupted':
            write_json(ws.root/'case_result.json',record)
            manifest.update(status='interrupted',usage=usage_summary(global_usage));write_json(output/'manifest.json',manifest)
            return
    manifest.update(status="completed", completed_at=datetime.now(timezone.utc).isoformat(), usage=usage_summary(global_usage),
                    unknown_usage_reserve_tokens=sum(c.get("admission_estimate",0) for c in global_usage if not c.get("response",{}).get("usage")),
                    frozen_source_hashes_unchanged=all(sha(ROOT/p)==h for p,h in hashes.items()))
    write_json(output / "manifest.json", manifest)
    print(json.dumps({"phase":spec["phase"],"statuses":[r['status'] for r in manifest['cases']],"usage":manifest['usage']},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--spec", default=str(ROOT/"configs/development_business_team_v01.json"))
    parser.add_argument('--resume',action='store_true',help='resume identical frozen version from API/tool checkpoints')
    args=parser.parse_args()
    run(args.spec,resume=args.resume)
