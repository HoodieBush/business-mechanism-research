"""Cross-layer update acceptance. Actual adapters, zero external inference."""
import argparse
from copy import deepcopy
import hashlib,json,re,shutil,sqlite3
import contextlib,importlib.util,io
from pathlib import Path
from unittest.mock import patch
import business_mechanism
from business_mechanism.engine import Reviewer,source_identity
from business_mechanism.engine import ReviewerRuntime
from business_mechanism.transport import ExecutionJournal
from business_mechanism.allocations import review_allocation
from business_mechanism.prompts import compose
from business_mechanism.method_coverage import computation_output,json_pointer,coverage_report
from business_mechanism.submission_protocol import guide,clean_example,PROTOCOL
from business_mechanism.tool_protocol import inline_schema
from business_mechanism.migration import migrate_project_copy
from business_mechanism.service import open_project
from business_mechanism.workflow import action_catalog
from business_mechanism.workflow import close_stage
from business_mechanism.verification_tasks import unpublished_findings,phase
from experiments.insight_research.common import digest,encoded
import test_agent_repairs as fixtures

ROOT=Path(__file__).resolve().parents[1]


def validate_surface(ws,role,*,schemas=None,prompt=None):
    schemas=ws.tool_schemas() if schemas is None else schemas
    names=[s['function']['name'] for s in schemas]
    assert len(names)==len(set(names)) and set(names)==set(ws.tools),'offered schema names differ from executable registry'
    for s in schemas:
        f=s['function'];model,description=ws.tools[f['name']]
        assert f['parameters']==inline_schema(model.model_json_schema()),'stale schema: '+f['name']
        assert f['description']==description,'stale tool description: '+f['name']
    examples=[]
    for name,body in re.findall(r'<example id="([^"]+)">(.*?)</example>',compose(role) if prompt is None else prompt,re.S):
        function=re.search(r'函数：\s*(\w+)',body);raw=re.search(r'```json\s*(.*?)\s*```',body,re.S)
        if not function or not raw:continue
        tool=function.group(1);assert tool in ws.tools,'unavailable example tool: '+tool
        args=json.loads(raw.group(1));ws.tools[tool][0].model_validate(args,strict=True)
        if tool=='record_review' and args.get('phase')=='complete' and args.get('target_conclusion')=='consistent_in_checked_scope':
            assert args.get('coverage_checks'),'complete consistent example has no coverage'
            referenced={c['action_ref'] for c in args['checks_performed']}
            assert all(c['action_ref'] in referenced for c in args['coverage_checks']),'example coverage cites no performed action'
        examples.append(name)
    assert examples,'no visible function examples checked'
    return {'examples':examples,'schema_sha256':digest(schemas),'prompt_sha256':digest(compose(role) if prompt is None else prompt)}


def rejects(function):
    try:function()
    except (AssertionError,ValueError,KeyError,TypeError):return True
    return False


def rows(path,table):
    with sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True) as db:return db.execute('SELECT * FROM "'+table+'" ORDER BY rowid').fetchall()


def inspect_upgrade(project,baseline_project,baseline_package):
    project=Path(project).resolve();baseline_project=Path(baseline_project).resolve();baseline_package=Path(baseline_package).resolve()
    root,cfg,ws,backend=open_project(project)
    try:
        before=backend.budget.snapshot()
        assert cfg['source_identity']==source_identity()==cfg['settings']['release_sources']
        assert rows(project/'researcher/private/records.sqlite','records')==rows(baseline_project/'researcher/private/records.sqlite','records'),'science records changed'
        for table in ('attempts','identity','flags','execution_control'):
            assert rows(project/'common_budget.sqlite',table)==rows(baseline_project/'common_budget.sqlite',table),'ledger/deadline changed: '+table
        checked=[]
        identities=[project/'researcher/private/identity.json',*sorted(project.glob('reviews/*/critic/private/identity.json'))]
        for path in identities:
            identity=json.loads(path.read_text());role='researcher' if path.is_relative_to(project/'researcher') else 'critic'
            proto=(type(ws) if role=='researcher' else Reviewer).__new__(type(ws) if role=='researcher' else Reviewer);proto.configure_tools()
            assert identity['tool_contract']==proto.tool_schemas(),'stale cached tool contract: '+str(path)
            assert identity['settings']['release_sources']==source_identity()
            cp_path=path.with_name('checkpoint.json')
            if cp_path.exists():
                cp=json.loads(cp_path.read_text());assert not cp.get('pending'),'undrained paid batch'
                if cp.get('messages'):assert cp['messages'][0]['content']==compose(role),'stale active prompt: '+str(cp_path)
            transport=path.with_name('transport.json')
            if transport.exists():
                state=json.loads(transport.read_text());assert not state.get('inflight') and not state.get('delivery')
            checked.append(str(path.relative_to(project)))
        receipt=json.loads((project/'migrations'/cfg['migration']['event_id']/'receipt.json').read_text())
        assert receipt['original_source_identity']=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in baseline_package.glob('*.py')}
        assert all(p['current_coverage']['clearance_eligible'] for p in receipt.get('saved_proof_rechecks',[])),'a previously eligible proof failed the new gate'
        assert not receipt['legacy_clearances_invalidated'],'review actual invalidations before deploying'
        assert backend.budget.snapshot()==before
        return {'identities_checked':len(checked),'preserved_scientific_records':receipt['scientific_records_preserved'],
                'retained_clearances':len(receipt['exact_current_clearances_retained']),
                'rechecked_proofs':len(receipt.get('saved_proof_rechecks',[])),'external_provider_calls':0}
    finally:ws.close()


def main(output,*,upgrade_project=None,baseline_project=None,baseline_package=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    checks={};details={};failures={}
    def check(name,function):
        try:details[name]=function();checks[name]=True
        except Exception as error:checks[name]=False;failures[name]=type(error).__name__+': '+str(error)
    fixture=fixtures.AgentRepairs();fixture.setUp();peer=None
    try:
        peer,job,target=fixture.peer();ws=fixture.ws
        check('installed_package_matches_current_source',lambda:source_identity()=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/business_mechanism').glob('*.py')} or (_ for _ in ()).throw(AssertionError('installed/source mismatch')))
        def release_views():
            for name in ('README.md','README.zh-CN.md','DEPLOYMENT_VERIFICATION.md','docs/EVALUATION.md','docs/releases/v0.md'):
                assert json.loads((ROOT/'RELEASE_STATUS.json').read_text())['release_tag'] in (ROOT/name).read_text()[:2048],'stale current version marker: '+name
            assert json.loads((ROOT/'RELEASE_STATUS.json').read_text())['version']==business_mechanism.__version__
            assert re.search(r'^version:\s*'+re.escape(business_mechanism.__version__)+r'\s*$',(ROOT/'CITATION.cff').read_text(),re.M)
            assert 'tests/update_compatibility.py' in (ROOT/'.github/workflows/ci.yml').read_text()
            assert 'tests/update_compatibility.py' in (ROOT/'AGENTS.md').read_text()
            assert (ROOT/'docs/UPDATE_COMPATIBILITY.zh-CN.md').is_file()
            return {'current_views':7,'mandatory_ci_and_contributor_gate':True}
        check('current_version_views_and_mandatory_release_gate_agree',release_views)
        def installation_preflight():
            spec=importlib.util.spec_from_file_location('current_release_preflight',ROOT/'tools/check_install.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):code=module.main()
            result=json.loads(stream.getvalue())
            assert code==0 and all(c['passed'] for c in result['checks']),result
            stream=io.StringIO()
            with patch.object(module.importlib.metadata,'version',return_value='0.0.0-stale'),contextlib.redirect_stdout(stream):code=module.main()
            stale=json.loads(stream.getvalue())
            assert code==2 and not next(c['passed'] for c in stale['checks'] if c['check']=='release_version')
            return {'actual_installation_preflight_passed':True,'stale_installed_metadata_rejected':True,'external_provider_calls':0}
        check('installation_preflight_uses_current_release_version',installation_preflight)
        check('researcher_prompt_examples_schema_and_descriptions',lambda:validate_surface(ws,'researcher'))
        check('critic_prompt_examples_schema_and_descriptions',lambda:validate_surface(peer,'critic'))
        def negative_controls():
            stale=deepcopy(peer.tool_schemas());stale[0]['function']['description']='old cached description'
            assert rejects(lambda:validate_surface(peer,'critic',schemas=stale))
            stale=deepcopy(peer.tool_schemas());r=next(s for s in stale if s['function']['name']=='record_review');r['function']['parameters']['properties'].pop('coverage_checks')
            assert rejects(lambda:validate_surface(peer,'critic',schemas=stale))
            old=compose('critic');old=re.sub(r'"coverage_checks":\s*\[.*?\],\s*"issues"', '"issues"',old,flags=re.S)
            # An exact old positive example must be rejected, independently of
            # the other current examples and without relying on prose scanning.
            bad=clean_example();bad.pop('coverage_checks')
            old='<example id="stale_review">函数：record_review\n```json\n'+json.dumps(bad)+'\n```</example>'
            assert rejects(lambda:validate_surface(peer,'critic',prompt=old))
            return {'stale_description_rejected':True,'stale_schema_rejected':True,'stale_positive_example_rejected':True}
        check('stale_surface_negative_controls',negative_controls)
        def guide_agrees():
            contract=peer.call('get_review_contract',{},'compat-contract');assert contract['submission_format']['protocol']==PROTOCOL
            assert contract['contract']==peer.context()['review_contract']
            required=['claim_evidence','data_scope','sampling','grouping','transformation','estimator','numeric_claim']
            full=guide({'required_components':required},peer.tools['record_review'][0].model_json_schema())
            components={c['component'] for c in full['complete_example']['coverage_checks']+full['method_check_examples']+[full['numeric_check_example']]}
            assert set(required)<=components
            agenda=ws.call('get_research_agenda',{},'compat-agenda');assert agenda['workflow_phase']==ws.context()['workflow_phase']
            return {'full_business_components':required,'workflow_phase':agenda['workflow_phase']}
        check('guides_context_and_agenda_share_current_contract',guide_agrees)
        def actual_paths():
            q=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Compatibility fixture minimum'},'compat-query')
            peer.call('run_python',{'code':"import json\nprint(json.dumps({'minimum':0,'total':1301}))",'purpose':'Structured output compatibility fixture'},'compat-json')
            peer.call('run_python',{'code':"print('minimum=0')\nprint('rows=1301')",'purpose':'Rendered output compatibility fixture'},'compat-text')
            catalog=action_catalog(peer);count=0
            for item in catalog:
                op=peer.action(item['action_ref']);result=op.get('result',{})
                if op['tool']=='run_python':result=computation_output(result['execution'])
                for p in item['actual_output_paths']:
                    assert json_pointer(result,p['output_pointer'])==p['observed'];count+=1
            assert count>=5
            invented={'component':'claim_evidence','action_ref':q['action_ref'],'output_pointer':'/parsed_stdout/nonexistent','relation':'eq','expected':0}
            assert not coverage_report([invented],peer.action)['clearance_eligible']
            return {'real_paths_resolved':count,'invented_path_rejected':True}
        check('displayed_output_paths_resolve_to_actual_receipts',actual_paths)
        def role_slice_contract():
            allocation=review_allocation(ws,fixture.backend.budget,job['ref']);peer.review_allocation=allocation
            journal=ExecutionJournal(peer,fixture.model,fixture.backend.budget,'critic:'+job['ref'],memory=False,guard=fixture.backend.guard)
            runtime=ReviewerRuntime(peer,fixture.model,journal=journal);runtime.cp['messages']=runtime.initial();runtime.save()
            context=peer.context();assert context['resources']['limits']['max_http_attempts']==allocation['maximum_requests']
            journal.state['attempts']=allocation['closeout_start_request']
            payload=runtime.prepare_payload(runtime.payload());names={s['function']['name'] for s in payload['tools']}
            assert len(encoded(payload).encode())<=peer.settings['limits']['max_request_bytes'],'final prepared request exceeds configured byte cap'
            assert 'run_python' not in names and 'query_data' not in names and 'record_review' in names
            assert names<=set(peer.tools)
            return {'normal':allocation['normal_requests'],'maximum':allocation['maximum_requests'],'closeout_tools':sorted(names)}
        check('critic_slice_context_and_actual_offered_tools_agree',role_slice_contract)
        def paid_filter_contract():
            runtime=fixture.backend.runtime;journal=runtime.journal
            runtime.cp['messages']=runtime.initial();runtime.save();payload=runtime.payload()
            payload['tools']=[s for s in payload['tools'] if s['function']['name']=='query_data']
            def response(attempt,calls):
                raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'','tool_calls':calls}}],'usage':{'total_tokens':17}}
                key=digest(['researcher',attempt]);journal.study.reserve(key,'researcher',payload)
                journal.persist_request(attempt,payload);journal.persist_response(attempt,{'response':raw})
                journal.study.settle(key,digest(payload),raw['usage']);journal.state.update(attempts=attempt,accounted_tokens=attempt*17,inflight=None,delivery=None);journal.save()
                runtime.accept(raw,delivery=attempt)
                assert json.loads((ws.private/'turns'/f'{attempt}.json').read_text())==raw
            query={'id':'allowed','type':'function','function':{'name':'query_data','arguments':encoded({'sql':'SELECT COUNT(*) FROM observations','purpose':'Atomic compatibility fixture.'})}}
            hidden={'id':'hidden','type':'function','function':{'name':'get_research_agenda','arguments':'{}'}}
            before=ws.db.execute("SELECT count(*) FROM events WHERE json_extract(body,'$.tool')='query_data'").fetchone()[0]
            response(1,[query,hidden]);assert runtime.cp['pending'] is None
            runtime.run(0)
            assert ws.db.execute("SELECT count(*) FROM events WHERE json_extract(body,'$.tool')='query_data'").fetchone()[0]==before
            receipt=json.loads((ws.private/'wire_normalizations/1.json').read_text())
            assert receipt['errors'][0]['error_code']=='tool_not_admitted_in_original_request'
            response(2,[query]);runtime.run(0)
            assert ws.db.execute("SELECT count(*) FROM events WHERE json_extract(body,'$.tool')='query_data'").fetchone()[0]==before+1
            assert fixture.backend.budget.snapshot()['reported_tokens']==34
            return {'hidden_tool_batch_executed_zero':True,'next_valid_call_executed_once':True,'local_fixture_cost_retained':34}
        check('paid_request_tool_filter_is_enforced_atomically',paid_filter_contract)
        def preserve_proof_and_upgrade():
            q=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Migration compatibility minimum'},'compat-proof')
            args=clean_example();args.update(source_refs=[target['ref']],checks_performed=[{'action_ref':q['action_ref'],'finding':'Exact supplied fixture minimum is zero.','artifact_refs':[]}],
                coverage_checks=[{'component':'claim_evidence','action_ref':q['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
            peer.call('record_review',args,'compat-review');fixture.backend.import_feedback(job,peer)
            assert ws.clearance(target['ref'])
            assert unpublished_findings(ws)
            with ws.db:close_stage(ws,outcome='unresolved',reason='Publication fixture is explicitly handed off without revoking valid evidence.',
                unresolved_refs=[target['ref']],evidence_refs=[],key='compat-publication-handoff')
            assert not unpublished_findings(ws) and unpublished_findings(ws,include_deferred=True)
            assert phase(ws)=='choose_next_goal' and ws.clearance(target['ref']) and not ws.records('report')
            before=fixture.backend.budget.snapshot();package=output/'baseline-package'
            shutil.copytree(Path(business_mechanism.__file__).parent,package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            # Simulate old active caches, leaving old scientific records exact.
            if not (fixture.project/'researcher/private/checkpoint.json').exists():
                fixture.backend.runtime.cp['messages']=fixture.backend.runtime.initial();fixture.backend.runtime.save()
            for identity_path in [fixture.project/'researcher/private/identity.json',*fixture.project.glob('reviews/*/critic/private/identity.json')]:
                identity=json.loads(identity_path.read_text());identity['tool_contract'][0]['function']['description']='old cached interface'
                identity_path.write_text(json.dumps(identity))
                cp_path=identity_path.with_name('checkpoint.json')
                if not cp_path.exists():cp_path.write_text(json.dumps({'responses':0,'pending':None,'messages':[{'role':'system','content':'old active prompt'}]}))
                else:
                    cp=json.loads(cp_path.read_text());cp['messages']=[{'role':'system','content':'old active prompt'}];cp_path.write_text(json.dumps(cp))
            destination=output/'upgraded-project'
            migrate_project_copy(fixture.project,destination,baseline_package=package,event_id='cross-layer-upgrade')
            result=inspect_upgrade(destination,fixture.project,package)
            assert result['retained_clearances']==1 and result['rechecked_proofs']==1
            assert before==fixture.backend.budget.snapshot()
            return result
        check('migration_refreshes_active_caches_and_preserves_exact_proof',preserve_proof_and_upgrade)
        if upgrade_project:
            check('actual_deployment_copy_matches_previous_frozen_run',lambda:inspect_upgrade(upgrade_project,baseline_project,baseline_package))
        result={'passed':all(checks.values()),'checks':checks,'details':details,'failures':failures,
                'external_provider_calls':0,'scope':'Cross-layer interface and migration compatibility, including negative controls. This is not scientific certification or proof of every possible future upgrade.'}
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        (output/'contract-manifest.json').write_text(json.dumps({'package_version':business_mechanism.__version__,'source_identity':source_identity(),
            'submission_protocol':PROTOCOL,'surfaces':{k:details.get(k) for k in ('researcher_prompt_examples_schema_and_descriptions','critic_prompt_examples_schema_and_descriptions')}},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:result[k] for k in ('passed','checks','failures','external_provider_calls')},ensure_ascii=False),flush=True)
        assert result['passed'],failures
    finally:
        if peer:peer.close()
        fixture.tearDown()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--upgrade-project',type=Path);parser.add_argument('--baseline-project',type=Path);parser.add_argument('--baseline-package',type=Path)
    args=parser.parse_args()
    if any((args.upgrade_project,args.baseline_project,args.baseline_package)) and not all((args.upgrade_project,args.baseline_project,args.baseline_package)):parser.error('All three deployment inputs are required together')
    with patch('business_mechanism.transport.call_model',side_effect=AssertionError('External inference forbidden during compatibility acceptance')):
        main(args.output,upgrade_project=args.upgrade_project,baseline_project=args.baseline_project,baseline_package=args.baseline_package)
