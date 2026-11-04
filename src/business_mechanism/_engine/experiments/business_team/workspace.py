"""Small shared research archive and role tools, with actual code execution."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
import shutil
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t
from execution import PythonWorkspace,last_number
from contracts import dictionary, VERSION, FIELD_MEANINGS, field_definition
from world import PUBLIC_TASK, BASELINE_CODE, STRONG_CODE, START, operating_orders
from scenario_contract import business_brief, operating_rules


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+".pending")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temporary.replace(path)


class ResearchWorkspace:
    def __init__(self, root, world, resume_from=None, reopen=False, require_artifact_review=True,evaluation_only=False):
        self.root = Path(root).resolve()
        self.public, self.shared = self.root / "public", self.root / "artifacts"
        self.world = world
        self.business_task=business_brief() if world.revised else PUBLIC_TASK
        self.require_artifact_review=require_artifact_review
        self.actor_closed=(self.root/'decision_freeze.json').exists()
        if evaluation_only and not (reopen and self.actor_closed):raise ValueError('evaluation-only reopening requires an actually closed case')
        if self.actor_closed and not (reopen and evaluation_only):raise ValueError('closed research cannot resume after final evaluation')
        self.path_aliases = json.loads((self.root/"path_aliases.json").read_text()) if reopen and (self.root/"path_aliases.json").exists() else {}
        if resume_from:
            parent = Path(resume_from).resolve()
            if (parent/"decision_freeze.json").exists():
                raise ValueError("closed research cannot resume after final evaluation")
            shutil.copytree(parent/"public", self.public)
            shutil.copytree(parent/"artifacts", self.shared)
            # Preserve the exact serialized feedback at execution time. Old
            # in-memory event objects could alias subsequently updated state.
            journals=[parent/name for name in ('operational_history.jsonl','framework_tools.jsonl') if (parent/name).is_file()]
            if journals:
                self.root.mkdir(parents=True,exist_ok=True)
                (self.root/'operational_history.jsonl').write_bytes(b''.join(p.read_bytes().rstrip(b'\n')+b'\n' for p in journals))
            # Preserve historical namespaces through more than one continuation.
            aliases=parent/"path_aliases.json"
            if aliases.exists():
                for old,target in json.loads(aliases.read_text()).items():
                    target=Path(target)
                    self.path_aliases[old]=str(self.root/target.relative_to(parent)) if target.is_relative_to(parent) else str(target)
            self.path_aliases[str(parent)] = str(self.root)
            self.history = pd.read_csv(self.public/"history.csv")
        elif reopen:
            if self.actor_closed and not evaluation_only:raise ValueError("closed research cannot resume after final evaluation")
            self.history=pd.read_csv(self.public/"history.csv")
        else:
            self.history = world.public_dataset(self.public)
        self.shared.mkdir(parents=True, exist_ok=True)
        if resume_from or reopen:
            self.business_task = (self.public / 'business_brief.md').read_text()
        self.workers = {role: PythonWorkspace(self.shared / role, self.public, self.shared) for role in ("analyst", "mechanist", "verifier", "engineer", "manager", "evaluator")}
        self.state = json.loads((self.shared/"research_history.json").read_text()) if resume_from or reopen else {"tasks": [], "results": [], "hypotheses": [], "experiments": [], "algorithms": [], "events": []}
        self.state.setdefault('artifact_reviews',[])
        write_json(self.root/"path_aliases.json",self.path_aliases)
        self.query_count = last_number(self.shared, 'query_', '.csv')
        self.delegate = None
        self.operation = None
        if not resume_from and not reopen:
            (self.public / "business_brief.md").write_text(self.business_task)
            (self.public / "baseline.py").write_text(BASELINE_CODE)
            (self.public / "numeric_refit.py").write_text(BASELINE_CODE.replace("history['day'] < 56", "history['day'] < 84"))
            (self.public / "strong_numeric.py").write_text(STRONG_CODE.replace("history['day'] < 56", "history['day'] < 84"))
        if world.revised and not resume_from and not reopen:
            strong=STRONG_CODE.replace("history['day'] < 56", "history['day'] < 84")
            strong=strong.replace("    future = future.rename(columns={'planned_s11_morning_stock':'s11_hour_start_stock'})\n",'')
            strong=strong.replace("'s11_hour_start_stock'","'planned_s11_morning_stock','planned_s12_morning_stock'")
            (self.public/'strong_numeric.py').write_text(strong)
            if not resume_from and not reopen:
                write_json(self.public/'operating_rules.json',operating_rules(world.scenario_version))
        if not resume_from and not reopen:shutil.copyfile(Path(__file__).with_name('provenance.py'),self.public/'research_data.py')
        frame=None
        if not resume_from and not reopen:
            predictions, _ = self.workers["evaluator"].forecast(self.public / "baseline.py", self.public / "history.csv", self.world.features(0, 84), "baseline")
            frame = self.world.features(0, 84)[["day", "date", "site", "sku", "hour"]]
            frame["predicted_demand_mean"] = predictions
        if not resume_from and not reopen:
            with sqlite3.connect(self.public / "business.sqlite") as db:
                if frame is not None:frame.to_sql("baseline_predictions", db, index=False, if_exists="replace")
                names=['hourly','products','sites','daily_finance','baseline_predictions']
                if world.revised:names+=['support_plans','prediction_features']
                schemas = {name: [r[1] for r in db.execute(f'PRAGMA table_info("{name}")')] for name in names}
            meanings = dictionary(schemas,structured=world.revised)
            meanings['database_file']=str(self.public/'business.sqlite')
            meanings["row_count"] = len(self.history)
            meanings["history_csv"] = {"row_grain": meanings["tables"]["hourly"]["row_grain"],
                                      "columns": {name:field_definition(name,world.revised) for name in self.history.columns}}
            write_json(self.public / "data_dictionary.json", meanings)
        else:
            # Relocation is a runtime binding, not a new scientific contract.
            # Keep copied definitions/sidecars byte-identical so reviewed inputs
            # and exact reference versions remain valid across continuations.
            meanings=json.loads((self.public/'data_dictionary.json').read_text())
        self.data_source = {"dictionary_version": meanings['version'], "dictionary_sha256": sha(self.public/"data_dictionary.json"),
                            "history_sha256": sha(self.public/"history.csv"), "database_sha256": sha(self.public/"business.sqlite")}
        self.registered_sources={str(self.public/name) for name in ('business.sqlite','history.csv','products.csv','sites.csv','development_features.csv')}
        self.registered_data_sources=set(self.registered_sources)
        if world.revised:
            self.registered_sources.update(str(self.public/name) for name in ('support_plans.csv','prediction_features.csv','operating_rules.json'))
            self.registered_data_sources.update(str(self.public/name) for name in ('support_plans.csv','prediction_features.csv'))
        self.registered_sources.add(str(self.public/'data_dictionary.json'))
        from team import SCHEMAS, MENUS, DESCRIPTIONS
        if not resume_from and not reopen:
            write_json(self.public/"tool_manual.json", {"version":VERSION,"role_menus":MENUS,
                       "tools":{name:{"description":DESCRIPTIONS[name],"parameters":schema} for name,schema in SCHEMAS.items()},
                       "manager_submit_extra":"主管submit_result还必须提供selected_algorithm_id=baseline或已收到的算法ID",
                       "execution":"每次Python脚本45秒是执行保护，不是任务调用次数额度；可修正和重跑。整轮成本单独记账。"})
        if not resume_from and not reopen:
            filenames=['history.csv','products.csv','sites.csv','development_features.csv']
            if world.revised:filenames+=['support_plans.csv','prediction_features.csv']
            for filename in filenames:
                self.annotate(self.public/filename,{"producer":"environment","semantics_status":"backend public contract", "field_definitions": {
                    name:field_definition(name,world.revised) for name in pd.read_csv(self.public/filename,nrows=0).columns},
                    "row_grain":{'products.csv':'商品','sites.csv':'柜点','support_plans.csv':'柜点×日×配套SKU'}.get(filename,'柜点×商品×小时')})
        self.registered_sources.update(str(self.public/name) for name in
            ('data_dictionary.json','business_brief.md','tool_manual.json','baseline.py','numeric_refit.py','strong_numeric.py')
            if (self.public/name).is_file())
        if world.revised:
            from decision_interface import initialize as initialize_decision_interface
            initialize_decision_interface(self, fresh=not resume_from and not reopen)
        self.persist()

    def annotate(self, path, metadata):
        path = Path(path)
        note = {**self.data_source, **metadata, "artifact_sha256":sha(path), "artifact":str(path)}
        sidecar = Path(str(path)+".meta.json")
        write_json(sidecar, note)
        return str(sidecar)

    def persist(self):
        write_json(self.shared / "research_history.json", self.state)

    def event(self, role, tool, args, result, operation_id=None):
        if operation_id and any(e.get("operation_id")==operation_id for e in self.state["events"]):return
        entry = {"index": len(self.state["events"]), "role": role, "tool": tool,
                 "args": deepcopy(args), "result": deepcopy(result), "operation_id":operation_id,
                 "previous_hash": self.state["events"][-1]["hash"] if self.state["events"] else None}
        entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        self.state["events"].append(entry)
        self.persist()

    def readable(self, filename):
        references=self.state.get('references',{})
        reference=None
        if str(filename) in references:
            reference=references[str(filename)]
            filename=reference['path']
        for before,after in self.path_aliases.items():
            if str(filename)==before or str(filename).startswith(before+'/'):
                filename=after+str(filename)[len(before):]
                break
        path = Path(filename)
        if not path.is_absolute():
            path = self.root / filename
        path = path.resolve()
        if not any(path.is_relative_to(base) for base in (self.public, self.shared)) or not path.is_file():
            if any(path.is_relative_to(base) for base in (self.public,self.shared)):
                raise ValueError('file does not exist in the received workspace: '+str(path)+'. Copy exact returned paths or reference IDs; a global execution ID is not a per-directory filename. This is a reference error, not failure of your previous computation.')
            raise ValueError("path is outside the received public/artifact workspace")
        if reference and self.reference_version(path)!=reference['version']:
            raise ValueError('reference version changed; read the current artifact again to obtain a new ID')
        return path

    def reference_version(self,path):
        path=Path(path)
        return {'sha256':sha(path), **{suffix:sha(str(path)+suffix) if Path(str(path)+suffix).exists() else None
                                      for suffix in ('.meta.json','.lineage.json')}}

    def reference(self,path,kind='artifact'):
        path=self.readable(path);version=self.reference_version(path)
        references=self.state.setdefault('references',{})
        for identifier,record in references.items():
            if record=={'path':str(path),'version':version,'kind':kind}:return identifier
        identifier=f"{kind}_{len(references)+1:04d}"
        references[identifier]={'path':str(path),'version':version,'kind':kind};self.persist()
        return identifier

    def resolve_reference(self,identifier,kind):
        record=self.state.get('references',{}).get(identifier)
        if not record or record['kind']!=kind:
            available=[k for k,v in self.state.get('references',{}).items() if v['kind']==kind]
            raise ValueError(f'{kind} ID required, copied exactly from tool feedback with no path or commentary; available IDs: {available[-12:]}')
        return self.readable(identifier)

    def refs(self, files):
        paths=[]
        for index,ref in enumerate(files):
            try:
                path=self.readable(ref)
            except ValueError as error:
                experiment=next((e for e in self.state.get('experiments',[]) if e['id']==ref),None)
                hint='Copy an exact returned file path or registered artifact_/execution_ reference; object IDs are not file references.'
                if experiment:
                    # Suggest the actual received observation, never silently
                    # substitute it or discard the invalid item from evidence.
                    observation=self.readable(experiment['observations'])
                    hint='This is an experiment object ID, not a file reference. Its observation file is '+str(observation)+'. Cite the exact file/reference you inspected.'
                raise ValueError(f'evidence_files[{index}]={ref!r}: {hint} Original error: {error}') from error
            paths.append(str(path))
        for path in paths:
            if path in self.state.get('operational_records',{}):
                raise ValueError('operational navigation record is not standalone scientific evidence; cite its original data, execution or reviewed packet')
        return paths

    def current_review(self, filename):
        path=self.readable(filename)
        lineage=Path(str(path)+'.lineage.json')
        current_lineage=sha(lineage) if lineage.exists() else None
        metadata=Path(str(path)+'.meta.json')
        current_contract=sha(metadata) if metadata.exists() else None
        handoff=Path(str(path)+'.handoff.json')
        origin=json.loads(handoff.read_text())['origin_identity'] if handoff.exists() else str(path)
        for review in reversed(self.state['artifact_reviews']):
            if review['artifact_sha256']==sha(path) and review['lineage_sha256']==current_lineage and review['metadata_sha256']==current_contract and review['origin_identity']==origin:
                if review['decision']!='accepted':return None
                try:
                    current=all(sha(self.readable(s['path']))==s['sha256'] for s in review['independent_source_reads'])
                except ValueError:
                    current=False
                if current:return review
                return None
        return None

    def requires_independent_review(self, filename):
        """One source-authority policy for reads, dispatch and task snapshots.

        Supplied original data/contracts/programs still have immutable version
        checks. Their origin is distinct from an Agent's derived measurements;
        review exemption says nothing about their scientific or algorithm quality.
        """
        path=self.readable(filename)
        supplied={'data_dictionary.json','business_brief.md','tool_manual.json','python_api.json','baseline.py','numeric_refit.py','strong_numeric.py'}
        return str(path) not in self.registered_sources and not (path.parent==self.public and path.name in supplied)

    def require_reviewed(self, files):
        for path in self.refs(files):
            # Registered original data and environment-owned contracts are inputs,
            # not an upstream Agent's interpretation. Imported analysis is a draft.
            if not self.requires_independent_review(path):continue
            if not self.current_review(path):raise ValueError('derived artifact has no current independent review: '+path)

    def initial_context(self):
        meanings = json.loads((self.public / "data_dictionary.json").read_text())
        meanings.pop("history_csv")  # Exact joined-CSV definitions remain readable in the file/sidecar.
        return {"business_task": self.business_task, "public_directory": str(self.public), "shared_artifacts": str(self.shared),
                "imported_analysis_index": str(self.public/"imported_analysis/index.json") if (self.public/"imported_analysis/index.json").exists() else None,
                "data_dictionary": meanings, "data_dictionary_file":str(self.public/"data_dictionary.json"),
                "tool_manual":str(self.public/"tool_manual.json"),
                "python_api_reference":str(self.public/'python_api.json') if (self.public/'python_api.json').exists() else None,
                "information_protocol":{"artifact_default":"draft", "handoff":"producer declarations and runtime source lineage are separate; derived evidence needs independent review before mechanism research",
                    "python_data_access":"from research_data import read_table, concat; tracked filtering/rename/aggregation/join/export preserve original column identities; arbitrary pandas remains possible via to_pandas(), but lineage may be untracked and needs review",
                    "review_requirement":"verifier independently loads original registered data, checks binding/units/grain/transformation/availability/interpretation, then reviews exact artifact and lineage hashes; reviewer judgment is not causal truth"},
                "resumption_path_mapping":self.path_aliases,
                "resumption_instruction":"历史文件引用由read_artifact映射到本次不可变副本。新Python用PUBLIC_DIR/ARTIFACT_DIR/WORK_DIR，不直接访问旧轮路径。",
                "products": pd.read_csv(self.public / "products.csv").to_dict("records"),
                "sites": pd.read_csv(self.public / "sites.csv").to_dict("records"),
                "baseline_code": str(self.public / "baseline.py"), "history_csv": str(self.public / "history.csv"),
                "business_database": str(self.public / "business.sqlite")}

    def query(self, role, sql, output_semantics="未声明输出语义；需复核"):
        db = sqlite3.connect(f"file:{self.public / 'business.sqlite'}?mode=ro", uri=True)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        db.set_authorizer(lambda action, p1, p2, *_: sqlite3.SQLITE_OK if action in allowed and str(p2).lower() != "load_extension" else sqlite3.SQLITE_DENY)
        steps = [0]
        def stop():
            steps[0] += 1
            return int(steps[0] > 10000)
        db.set_progress_handler(stop, 1000)
        try:
            cursor = db.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(100001)
            if len(rows) > 100000:
                raise ValueError("query exceeds 100000 rows; aggregate or narrow it")
        finally:
            db.close()
        self.query_count += 1
        path = self.workers[role].directory / f"query_{self.query_count:03d}.csv"
        frame = pd.DataFrame(rows, columns=columns)
        with path.open('x') as output:frame.to_csv(output, index=False)
        metadata = {"producer":role,"sql":sql,"output_semantics":output_semantics,
                    "semantics_status":"LLM producer declaration, not independent certification",
                    "source_field_definitions":json.loads((self.public/"data_dictionary.json").read_text())["tables"],
                    "aggregation_warnings":["SQL operation lineage is not automatically inferred; inspect the saved query and independently review declared meaning."], "row_count":len(frame),"columns":columns}
        sidecar = self.annotate(path, metadata)
        return {"file": str(path), "metadata_file":sidecar, "row_count": len(frame), "columns": columns,
                "output_semantics":output_semantics,"aggregation_warnings":metadata["aggregation_warnings"],"preview": frame.head(12).to_dict("records")}

    def experiment(self, args):
        h = next((x for x in self.state["hypotheses"] if x["id"] == args["hypothesis_id"]), None)
        if h is None:
            raise ValueError("received hypothesis required")
        eid = f"E{len(self.state['experiments'])+1:03d}"
        directory = self.shared / "experiments" / eid
        if args["kind"] == "inventory_audit":
            rows = self.history[self.history.sku.isin(args["product_ids"])].copy()
            rows["verified_sales"] = rows.opening_stock + rows.restock - rows.closing_stock
            summary = {"rows": len(rows), "recorded_total": int(rows.sales.sum()), "verified_total": int(rows.verified_sales.sum()),
                       "mismatched_rows": int((rows.sales != rows.verified_sales).sum()), "scope": "同一批已提供库存与销售记录的守恒核对；没有新增实物盘点，不是独立样本，不认证需求机制"}
            assignment = pd.DataFrame()
        elif args["kind"] == "supply_trial":
            ntrial = sum(x["kind"] == "supply_trial" for x in self.state["experiments"])
            if ntrial >= 2:
                raise ValueError("preregistered maximum two new trials")
            if args["support_sku"] not in ("S11", "S12") or args["days"] != 14:
                raise ValueError("14-calendar-day trial and received support SKU required")
            days = [d for d in range(84 + ntrial*14, 98 + ntrial*14) if (START + pd.Timedelta(days=d)).weekday() < 5]
            rng = np.random.default_rng(np.random.SeedSequence([self.world.seed, 701, ntrial]))
            allocations = {}
            for site in pd.read_csv(self.public / "sites.csv").site:
                flags = rng.permutation([0]*(len(days)//2) + [1]*(len(days)-len(days)//2))
                allocations.update({(day, site): int(flag) for day, flag in zip(days, flags)})
            frozen = {"id": eid, "plan": args, "alpha": .025, "allocation": [{"day": d, "site": s, "treatment": a} for (d,s),a in allocations.items()]}
            write_json(directory / "registered_plan.json", frozen)  # before any new observations
            assignment = pd.DataFrame(frozen["allocation"])
            rows, _ = self.world.generate(84+ntrial*14, 14, assignment=allocations, support_sku=args["support_sku"], main_high=True)
            outcome = rows[rows.sku.isin(args["product_ids"])].groupby(["site", "day", "treatment"]).sales.sum().reset_index()
            effects = outcome.groupby(["site", "treatment"]).sales.mean().unstack()[1] - outcome.groupby(["site", "treatment"]).sales.mean().unstack()[0]
            mean, se = float(effects.mean()), float(effects.std(ddof=1)/np.sqrt(len(effects)))
            radius = float(t.ppf(1-.025/2, len(effects)-1)*se)
            summary = {"mean_daily_sales_difference": mean, "cluster_interval_97_5": [mean-radius, mean+radius],
                       "site_clusters": len(effects), "site_day_units": len(outcome), "alpha": .025,
                       "analysis": "mean of within-site treated-control means; t interval over 8 sites, approximate small-cluster development analysis",
                       "scope": "selected SKUs under fixed high main-stock, chosen support availability and received sites; no global/unique mechanism proof",
                       "main_stockout_hours": int((rows[rows.sku.isin(args["product_ids"])].available_minutes < 60).sum())}
            support_morning=rows[(rows.sku==args['support_sku']) & (rows.hour==9)]
            summary['actual_supply_by_arm']=[{'treatment':int(arm),'site_days':len(data),
                'mean_opening_stock':float(data.opening_stock.mean()),'observed_stock_levels':sorted(map(int,data.opening_stock.unique()))}
                for arm,data in support_morning.groupby('treatment')]
            summary['supply_interpretation']='Realised treatment contrast in the manipulated stock, separately from outcome effects; no unique mechanism certification.'
        else:
            raise ValueError("unknown experiment kind")
        directory.mkdir(parents=True, exist_ok=True)
        rows.to_csv(directory / "observations.csv", index=False)
        assignment.to_csv(directory / "assignment.csv", index=False)
        self.annotate(directory/"observations.csv", {"producer":"experiment backend","row_grain":"柜点×商品×小时",
                      "field_definitions":{name:dict(zip(("meaning","unit","aggregation"),FIELD_MEANINGS[name])) for name in rows.columns},
                      "experiment_kind":args["kind"],"is_new_sample":args["kind"]=="supply_trial","plan":args,
                      "caution":"新试验干预为配套晨间80件 vs 原运营供应；不保证对照配套为0，主品晨间50件固定；阴性不能证明无效应"})
        if not assignment.empty:
            self.annotate(directory/"assignment.csv", {"producer":"experiment backend","row_grain":"柜点×日", "field_definitions": {
                name:dict(zip(("meaning","unit","aggregation"),FIELD_MEANINGS[name])) for name in assignment.columns}})
        record = {"id": eid, "kind": args["kind"], "hypothesis_id": h["id"], "plan": args,
                  "operation_id":self.operation["id"] if self.operation else None,
                  "observations": str(directory / "observations.csv"), "summary": summary}
        write_json(directory / "receipt.json", record)
        self.state["experiments"].append(record)
        self.persist()
        return record

    def evaluate_code(self, filename, first_day=112, days=14, name="development"):
        if (getattr(self,'actor_closed',False) or (self.root/'decision_freeze.json').exists()) and not name.startswith('final_'):raise ValueError('closed case permits final evaluator work only')
        if self.world.revised and not name.startswith('final_'):
            if first_day!=112 or days!=14:raise ValueError('development window is fixed by the public evaluation contract')
            from development_evaluation import evaluate
            return evaluate(self,filename,name=name)
        code = self.readable(filename)
        features = self.world.features(first_day, days)
        forecasts, execution = self.workers["evaluator"].forecast(code, self.public / "history.csv", features, name)
        orders = operating_orders(features, forecasts)
        rows, finances = self.world.generate(first_day, days, orders=orders)
        return {"code_sha256": sha(code), "mean_net_profit_per_site_day": float(finances.net_profit.mean()),
                "mean_fresh_waste_per_site_day": float(finances.fresh_waste.mean()),
                "observed_stockout_hours": int((rows[rows.category == "鲜食"].available_minutes < 60).sum()) if "category" in rows else int((rows[rows.sku.isin(["S01","S02"])].available_minutes < 60).sum()),
                "site_days": len(finances), "evaluation_dates": [str((START+pd.Timedelta(days=first_day)).date()), str((START+pd.Timedelta(days=first_day+days-1)).date())],
                "note": "new operational simulation receipts, shared demand random streams, daily newsvendor with 50/SKU cap; not true-demand RMSE or oracle score",
                "execution_receipt": execution}

    def tool(self, role, name, args, operation_id=None):
        if getattr(self,'actor_closed',False) or (self.root/'decision_freeze.json').exists():raise ValueError('Actor closed; no research tools during evaluation-only recovery')
        if not operation_id:return self._tool(role,name,args)
        receipt=self.root/"tool_receipts"/(operation_id+".json")
        signature=hashlib.sha256(json.dumps([role,name,args],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        saved=json.loads(receipt.read_text()) if receipt.exists() else None
        if saved and saved["signature"]!=signature:raise ValueError("operation ID reused with different arguments")
        if saved and saved["status"]=="completed":return saved["result"]
        operation=saved or {"id":operation_id,"signature":signature,"status":"prepared","role":role,"tool":name,"args":args}
        write_json(receipt,operation)
        previous=self.operation
        self.operation={**operation,"receipt_path":str(receipt)}
        try:
            # A completed state-changing tool can be recovered even if its outer
            # receipt write was interrupted. Never blindly repeat an ambiguous trial.
            if saved:
                collection={"save_hypothesis":"hypotheses","run_experiment":"experiments","evaluate_algorithm":"algorithms","review_artifact":"artifact_reviews"}.get(name)
                found=next((x for x in self.state.get(collection,[]) if x.get("operation_id")==operation_id),None) if collection else None
                if found:result=found
                elif name in ("run_experiment","evaluate_algorithm"):
                    raise RuntimeError("ambiguous interrupted scientific tool; inspect its frozen receipt before resuming, do not resample")
                else:result=self._tool(role,name,args)
            else:result=self._tool(role,name,args)
            write_json(receipt,{**self.operation,"status":"completed","result":result})
            return result
        finally:self.operation=previous

    def _tool(self, role, name, args):
        from team import MENUS
        if name not in getattr(self,'tool_menus',MENUS).get(role, []):
            raise ValueError("tool outside role permissions")
        service=getattr(self,'research_service',None)
        if service and name in ('search_literature','read_source','read_source_code'):
            method={'search_literature':service.search,'read_source':service.read,'read_source_code':service.code}[name]
            result=method(role,**args)
            self.registered_sources.update(map(str,service.original_files()))
            return result
        identity=getattr(self,'object_identity',None)
        if name=='inspect_object' and identity:
            return identity.inspect(role,args['reference'])
        if name == "read_context":
            return self.initial_context()
        if name == "read_artifact":
            p = self.readable(args["path"])
            from langgraph_migration.operational_memory import view
            operational=view(self,p,role,args.get('offset',0))
            if operational is not None:return operational
            if self.require_artifact_review and role in ('mechanist','engineer'):self.require_reviewed([str(p)])
            text = p.read_text()
            offset = args.get("offset",0)
            sidecar = Path(str(p)+".meta.json")
            return {"path": str(p), "artifact_id":self.reference(p), "sha256": sha(p), "text": text[offset:offset+18000],
                    "truncated":len(text)>offset+18000,"next_offset":offset+18000 if len(text)>offset+18000 else None,
                    "metadata":json.loads(sidecar.read_text()) if sidecar.exists() else None,
                    "column_lineage":json.loads(Path(str(p)+'.lineage.json').read_text()) if Path(str(p)+'.lineage.json').exists() else None,
                    "independent_review":self.current_review(p)}
        if name == "read_history":
            output={k: self.state[k] for k in ("hypotheses", "experiments", "algorithms", "results","artifact_reviews")}
            if self.require_artifact_review and role in ('mechanist','engineer'):
                output['results']=[{k:v for k,v in r.items() if k not in ('summary','findings','next_step')} for r in output['results']]
                output['unverified_producer_commentary']='Producer conclusions are omitted until evidence review; read reviewed source artifacts instead.'
            output['hypotheses']=[{**h,'current_evidence_validity':'needs_review' if any(p not in self.registered_sources and not self.current_review(p) for p in h.get('evidence_files',[])) else 'current'} for h in output['hypotheses']]
            return output
        if name == "query_data":
            return self.query(role, args["sql"], args["output_semantics"])
        if name == "run_python":
            worker=self.workers[role]
            expected=self.operation.get("python_receipt") if self.operation else None
            if expected and Path(expected).exists():
                result=json.loads(Path(expected).read_text())
            else:
                if self.operation:
                    run_dir=worker.directory/'executions'/f'run_{worker.count+1:03d}' if worker.per_execution else worker.directory
                    self.operation["python_receipt"]=str(run_dir/f"execution_{worker.count+1:03d}.json")
                    write_json(self.operation["receipt_path"],self.operation)
                result = worker.run(args["code"])
            metadata = {"producer":role,"purpose":args["purpose"],"output_semantics":args["output_semantics"],
                        "semantics_status":"LLM producer declaration; reviewer must check code, units and interpretation",
                        "code_file":result["code_file"],"code_sha256":sha(result["code_file"]),
                        "aggregation_warnings":[],"execution_ok":result["ok"],
                        "execution_receipt":result["execution_receipt"], "input_lineage_limit":"Declared source version is the public history; arbitrary Python may read other shared files; inspect saved code for exact inputs."}
            result["metadata_files"] = [self.annotate(path,metadata) for path in result["generated_files"]+[result["code_file"]]]
            result['lineage_files']=[p+'.lineage.json' for p in result['generated_files'] if Path(p+'.lineage.json').exists()]
            result['untracked_outputs']=[p for p in result['generated_files'] if Path(p).suffix=='.csv' and not Path(p+'.lineage.json').exists()]
            result.update(purpose=args["purpose"],output_semantics=args["output_semantics"],aggregation_warnings=metadata["aggregation_warnings"])
            write_json(result["execution_receipt"],result)
            result['execution_id']=self.reference(result['execution_receipt'],'execution')
            return result
        if name=='review_artifact':
            path=self.resolve_reference(args['artifact_id'],'artifact')
            # Evidence must come from an actual independent verifier execution,
            # loading a registered original source after receiving the artifact.
            execution=self.resolve_reference(args['execution_id'],'execution')
            if not execution.is_relative_to(self.workers['verifier'].directory):raise ValueError('review needs verifier-owned execution receipt')
            receipt=json.loads(execution.read_text())
            if not receipt.get('ok'):raise ValueError('independent execution failed')
            sources=[s for s in receipt.get('source_reads',[]) if s['path'] in self.registered_sources]
            if not any(s['path'] in self.registered_data_sources for s in sources):raise ValueError('verifier must independently load registered original inputs, not only the producer result')
            required={'source_binding','transformation','units','grain','availability','interpretation'}
            aspects={c['aspect'] for c in args['checks']}
            if aspects!=required or len(args['checks'])!=len(required):raise ValueError('each generic review aspect must be addressed exactly once')
            if args['decision']=='accepted' and any(c['status']=='problem' for c in args['checks']):raise ValueError('cannot accept a review containing unresolved problems')
            if args['decision']=='accepted' and any(c['status']!='checked' for c in args['checks'] if c['aspect'] in ('source_binding','transformation','units','grain','interpretation')):raise ValueError('core information aspects cannot be skipped')
            lineage=Path(str(path)+'.lineage.json')
            if lineage.exists() and json.loads(lineage.read_text()).get('artifact_sha256')!=sha(path):raise ValueError('runtime provenance does not match current artifact bytes')
            if lineage.exists():
                origins=[s for c in json.loads(lineage.read_text())['columns'].values() for s in c['sources']]
                if any(not any(s['path']==origin['source_path'] and s['sha256']==origin['source_sha256'] and
                               s['table']==origin['table'] and origin['original_column'] in s['columns'] for s in sources)
                       for origin in origins):
                    raise ValueError('independent execution must cover every tracked original input column and its exact source version')
            review={**args,'path':str(path),'execution_receipt':str(execution),'id':f"V{len(self.state['artifact_reviews'])+1:03d}",'author':role,'artifact_sha256':sha(path),'lineage_sha256':sha(lineage) if lineage.exists() else None,
                    'metadata_sha256':sha(str(path)+'.meta.json') if Path(str(path)+'.meta.json').exists() else None,
                    'origin_identity':json.loads(Path(str(path)+'.handoff.json').read_text())['origin_identity'] if Path(str(path)+'.handoff.json').exists() else str(path),
                    'operation_id':self.operation['id'] if self.operation else None,
                    'independent_source_reads':sources,'note':'Independent Agent review with execution provenance; not universal semantic proof, physical truth or causal certification.'}
            self.state['artifact_reviews'].append(review);write_json(self.shared/'reviews'/(review['id']+'.json'),review);self.persist()
            return review
        if name == "save_hypothesis":
            refs = self.refs(args["evidence_files"])
            if self.require_artifact_review:self.require_reviewed(refs)
            parent = args.get("parent_id")
            if parent and not any(h["id"] == parent for h in self.state["hypotheses"]):
                raise ValueError("unknown parent hypothesis")
            item = {**args, "evidence_files": refs, "id": f"H{len(self.state['hypotheses'])+1:03d}", "status": "proposed", "author": role,
                    "operation_id":self.operation["id"] if self.operation else None}
            self.state["hypotheses"].append(item)
            write_json(self.shared / "hypotheses" / (item["id"]+".json"), item)
            self.persist()
            return item
        if name == "record_verdict":
            h = next((x for x in self.state["hypotheses"] if x["id"] == args["hypothesis_id"]), None)
            if h is None:
                raise ValueError("unknown hypothesis")
            if self.require_artifact_review:self.require_reviewed(h['evidence_files'])
            operation_id=self.operation["id"] if self.operation else None
            previous=next((v for v in h.get("verdicts",[]) if operation_id and v.get("operation_id")==operation_id),None)
            if previous:return previous
            verdict = {**args, "evidence_files": self.refs(args["evidence_files"]), "author": role,
                       "subject": {"type":"hypothesis_prediction","hypothesis_id":h['id'],"scope":h['scope'],"prediction":h['prediction'],
                                   "definition_sha256":hashlib.sha256(json.dumps({k:h.get(k) for k in ('id','explanation','scope','alternatives','prediction','falsification','evidence_files','parent_id')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()},
                       "operation_id":operation_id,
                       "note": "Verifier LLM interpretation; backend statistical receipts separately available. Not evaluator ground truth."}
            h.setdefault("verdicts", []).append(verdict)
            statuses = sorted({v['status'] for v in h['verdicts']})
            h["status"] = statuses[0] if len(statuses)==1 else 'mixed'
            h['verdict_statuses'] = statuses
            h['status_interpretation'] = 'All recorded verdicts retained; mixed means differing scoped interpretations, not automatic scientific resolution. Revise with a new hypothesis ID to change the prediction.'
            write_json(self.shared / "hypotheses" / f"{h['id']}_verdict_{len(h['verdicts']):02d}.json", verdict)
            self.persist()
            return verdict
        if name == "run_experiment":
            if self.require_artifact_review:
                h=next((h for h in self.state['hypotheses'] if h['id']==args['hypothesis_id']),None)
                if h:self.require_reviewed(h['evidence_files'])
            return self.experiment(args)
        if name == "evaluate_algorithm":
            source = self.readable(args["code_file"])
            aid = f"A{max(len(self.state['algorithms']),last_number(self.shared/'algorithms','A','.py'))+1:03d}"
            code = self.shared / "algorithms" / (aid+".py")
            code.parent.mkdir(parents=True, exist_ok=True)
            with code.open('xb') as output:output.write(source.read_bytes())
            if any(not any(h['id']==hid for h in self.state['hypotheses']) for hid in args['hypothesis_ids']):raise ValueError("unknown hypothesis reference")
            if self.require_artifact_review:
                for hypothesis in self.state['hypotheses']:
                    if hypothesis['id'] in args['hypothesis_ids']:self.require_reviewed(hypothesis['evidence_files'])
            item = {"id": aid, "code_file": str(code), "code_sha256": sha(code), "rationale": args["rationale"],
                    "operation_id":self.operation["id"] if self.operation else None,
                    "hypothesis_ids": args["hypothesis_ids"], "development": self.evaluate_code(code, name=aid)}
            for label in ("baseline", "numeric_refit", "strong_numeric"):
                item[label] = self.evaluate_code(self.public / (label+".py"), name=aid+"_"+label)
            from behavior_comparison import compare
            item['behavior_comparisons']={label:compare(item['development'],item[label]) for label in ('baseline','numeric_refit','strong_numeric')}
            self.state["algorithms"].append(item)
            self.persist()
            return item
        if name == "assign_task":
            if args["role"] == "manager" or not self.delegate:
                raise ValueError("specialist dispatch only")
            if self.require_artifact_review and args['role'] in ('mechanist','engineer'):self.require_reviewed(args['inputs'])
            task_id=self.operation.get("task_id") if self.operation else None
            task=next((t for t in self.state['tasks'] if t['id']==task_id),None)
            if task is None:
                task = {**args, "inputs": self.refs(args["inputs"]), "id": f"T{len(self.state['tasks'])+1:03d}"}
                self.state["tasks"].append(task)
                self.persist()
                if self.operation:
                    self.operation['task_id']=task['id'];write_json(self.operation['receipt_path'],self.operation)
            result = self.delegate(args["role"], task)
            if not any(r.get('result_number')==result.get('result_number') and r.get('role')==result.get('role') for r in self.state['results']):self.state["results"].append(result)
            self.persist()
            return result
        if name == "submit_result":return self.deliver(role,args)
        raise ValueError("unknown tool")

    def selectable_program_ids(self):
        """Selection policy hook shared by terminal delivery and adapters.

        Legacy workspaces expose baseline plus registered candidates. A domain
        adapter with a published programme catalogue overrides this policy;
        terminal delivery must not maintain a second, contradictory whitelist.
        """
        return {'baseline'} | {a['id'] for a in self.state['algorithms']}

    def deliver(self, role, args):
        """Backend immutable delivery, called after a registered tool validates its role."""
        operation_id=self.operation["id"] if self.operation else None
        if operation_id:
            for receipt in (self.shared/role).glob("result_*.json"):
                existing=json.loads(receipt.read_text())
                if existing.get("operation_id")==operation_id:return existing
        if role == "manager" and getattr(self,'manager_selects_program',True) and args.get("selected_algorithm_id") not in self.selectable_program_ids():
            raise ValueError("manager must choose a selectable program ID from the current catalogue")
        number = len(self.state["results"])+1
        received = self.shared / "received" / f"R{number:03d}_{role}"
        received.mkdir(parents=True, exist_ok=True)
        files = []
        for index, source in enumerate(self.refs(args["evidence_files"])):
            target = received / f"{index:02d}_{Path(source).name}"
            shutil.copyfile(source, target)
            sidecar = Path(source+".meta.json")
            if sidecar.exists():
                shutil.copyfile(sidecar,Path(str(target)+".meta.json"))
            lineage=Path(source+'.lineage.json')
            if lineage.exists():shutil.copyfile(lineage,Path(str(target)+'.lineage.json'))
            prior_handoff=Path(source+'.handoff.json')
            origin=json.loads(prior_handoff.read_text())['origin_identity'] if prior_handoff.exists() else source
            write_json(str(target)+'.handoff.json',{'origin_identity':origin,'source_path':source,'artifact_sha256':sha(target),'copied_by':'backend handoff'})
            files.append(str(target))
        item = {**args, "role": role, "evidence_files": files, "result_number": number,
                "operation_id":operation_id,
                "evidence_sha256": {p: sha(p) for p in files},
                "metadata_files":[p+".meta.json" for p in files if Path(p+".meta.json").exists()],
                "metadata_sha256":{p+".meta.json":sha(p+".meta.json") for p in files if Path(p+".meta.json").exists()}}
        write_json(self.shared / role / f"result_{item['result_number']:03d}.json", item)
        return item
