"""Explicit public integration seams for data jobs and review repair."""
from copy import deepcopy
import json
import time
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, create_model
from experiments.insight_research.common import Pending, digest, encoded, write_json
from .data_jobs import DataJobs
from .review_drafts import ReviewDrafts
from .tool_protocol import inline_schema, normalize_tool_containers
from .method_coverage import AnalysisSpec, CoverageCheck
from . import convergence
from .tool_errors import durable_call
from .workflow import (review_contract, review_coverage, coverage_errors, action_catalog,
                       close_stage, stage_outcome, stage_health, delivery_preflight)
from . import verification_tasks
from .submission_protocol import guide as submission_guide, draft_receipt


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Empty(Input):
    pass


class StartDataJob(Input):
    snapshot_ref: str
    sql: str = Field(min_length=1, max_length=100000)
    parameters: list[Any] | dict[str, Any] = Field(default_factory=list)
    resource_profile: Literal['interactive', 'batch'] = 'batch'


class Job(Input):
    job_ref: str


class ReadResult(Input):
    result_ref: str
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SaveDraft(Input):
    raw_arguments: str


class ReadDraft(Input):
    draft_ref: str


class ReadDraftPage(ReadDraft):
    section: Literal['raw_arguments','validation_errors'] = 'raw_arguments'
    offset: int = Field(default=0,ge=0)
    limit: int = Field(default=12000,ge=1,le=24000)


class CommitDraft(ReadDraft):
    expected_hash: str


class Change(Input):
    op: Literal['set', 'remove']
    path: str
    value: Any = None


class PatchDraft(CommitDraft):
    field_changes: list[Change] = Field(min_length=1, max_length=30)


class RegisterAnalysis(Input):
    target_ref: str
    spec: AnalysisSpec


class ReviseAnalysis(RegisterAnalysis):
    expected_spec_ref: str


class Revalidation(Input):
    target_ref: str
    expected_review_ref: str
    reason: str = Field(min_length=10)


class Claim(Input):
    target_ref: str


class CloseStage(Input):
    outcome: Literal['unresolved', 'blocked']
    reason: str = Field(min_length=10)
    unresolved_refs: list[str]
    evidence_refs: list[str]


DATA_TOOLS = {
    'get_data_profile': (Empty, 'Read frozen SQLite version, actual schema/indexes and full-query resource profiles.'),
    'start_data_job': (StartDataJob, 'Queue full read-only parameterized SQL. Compute runs before the next model turn; never poll with repeated model requests.'),
    'get_data_job': (Job, 'Read durable job attempts, typed errors, partial coverage and completed result_ref.'),
    'read_data_result': (ReadResult, 'Page an immutable completed result; keep large data in its SQLite artifact.'),
    'cancel_data_job': (Job, 'Cancel this data job without treating partial output as complete.'),
    'retry_data_job': (Job, 'Explicitly retry an incomplete job in a new full-SQL attempt; preserve failed artifacts.'),
}
DRAFT_TOOLS = {
    'save_review_draft': (SaveDraft, 'Preserve exact record_review arguments, including invalid JSON, and return local validation errors.'),
    'read_review_draft': (ReadDraftPage, 'Page exact owned raw_arguments or validation_errors; retain version/hash and explicit repair history.'),
    'patch_review_draft': (PatchDraft, 'Apply explicit JSON-pointer field changes using expected_hash. Scientific changes remain attributed; no automatic deletions.'),
    'commit_review': (CommitDraft, 'Validate current draft and original target before submitting. This is the sole tool in its batch.'),
}


class BusinessTools:
    def configure_tools(self):
        self.tools = {**type(self).tools, **DATA_TOOLS}
        if 'record_review' in self.tools:
            self.tools.update(DRAFT_TOOLS)
            model, description = self.tools['record_review']
            self.tools['record_review'] = (create_model('CoveredReview', __base__=model,
                coverage_checks=(list[CoverageCheck], Field(default_factory=list,description='Explicit actual evidence assertions. complete+consistent requires every component from get_review_contract. Numeric JSON pointers must exist in the cited computation; plain computed text uses /stdout_lines/index with exact eq. Source inspection needs /text contains and component-specific justification.'))), description+' Read get_review_contract.submission_format for the current complete format; old review examples are historical.')
            model,description=self.tools['run_python']
            self.tools['run_python']=(model,description+' For review coverage, emit a single JSON value with print(json.dumps(...)); actual JSON fields determine /parsed_stdout paths. Plain text is available by exact /stdout_lines/index equality.')
            self.tools['get_review_contract'] = (Empty, 'Read frozen requirements and exact successful computation action refs/output JSON pointers. Metadata reads cannot satisfy numeric coverage.')
            self.tools['validate_review_submission'] = (SaveDraft, 'Locally preflight exact record_review JSON, including actual output coverage. No LLM and no review is committed.')
            self.tools['inspect_report_disclosure'] = (Empty, 'Audit a report with no certified findings: actual received hypothesis coverage and absence of certified findings. Only record_fidelity, never numerical/method proof or hypothesis clearance.')
        else:
            model, description = self.tools['save_hypothesis']
            self.tools['save_hypothesis'] = (create_model('QueuedHypothesis', __base__=model,
                activation=(Literal['active', 'backlog'], 'active')), description)
            self.tools['register_analysis_spec'] = (RegisterAnalysis,
                'Bind dataset/filter/sample/entity/grouping/transforms/estimator/code to an immutable scientific target. Changed specs require a new target version.')
            self.tools['close_research_stage'] = (CloseStage, 'Close this stage honestly as unresolved/blocked, retaining all claims and costs. Does not create a formal scientific report or clearance. Sole call in batch.')
            self.tools['close_research_stage']=(CloseStage,self.tools['close_research_stage'][1]+' If publication is blocked, include the verified assessment in unresolved_refs to defer its publication obligation explicitly; its scientific clearance is retained and visible in deferred_verified_findings.')
            self.tools['get_claim_readiness'] = (Claim, 'Read exact review requirements, specification readiness and current clearance for any received claim, including prior stages.')
            self.tools.update({
                'get_research_agenda': (Empty, 'Read durable active hypotheses, immutable goals, budgets, backlog and endpoints. Finish focus before opening new branches.'),
                'request_revalidation': (Revalidation, 'Schedule a bounded directed followup when a completed review left method coverage incomplete. Exact expected_review_ref required; original target/criteria/opinion/costs unchanged. Not a status poll or automatic approval.'),
                'focus_hypothesis': (convergence.Focus, 'Activate/focus an existing backlog H within the WIP bound. Terminal hypotheses require a new version.'),
                'set_hypothesis_goal': (convergence.Goal, 'Freeze claim level, success/falsification and inconclusive criteria BEFORE registering a test. Changed criteria need a new H.'),
                'close_hypothesis': (convergence.CloseHypothesis, 'Record immutable accepted/refuted/inconclusive/abandoned/superseded endpoint. Accepted and refuted require a matching cleared assessment. No evidence is deleted.'),
                'revise_analysis_spec': (ReviseAnalysis, 'Explicit CAS revision before a review snapshot is frozen. Old specs remain archived. Frozen targets require a new scientific version.')})

    def __init__(self, *args, **kwargs):
        self.configure_tools()
        super().__init__(*args, **kwargs)
        self.db.execute('CREATE TABLE IF NOT EXISTS release_draft_commits(ref TEXT PRIMARY KEY,result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_task_state(job TEXT PRIMARY KEY,state TEXT,reason TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_analysis_specs(target TEXT PRIMARY KEY,version TEXT,spec_ref TEXT,body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_stage_outcomes(stage INTEGER PRIMARY KEY,body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_delivery_attempts(operation TEXT PRIMARY KEY,stage INTEGER,fingerprint TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_tool_receipts(operation TEXT PRIMARY KEY,signature TEXT,result TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_analysis_spec_history(ref TEXT PRIMARY KEY,body TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_closeout_turns(attempt INTEGER PRIMARY KEY,stage INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_closeout_scopes(attempt INTEGER PRIMARY KEY,scope TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS release_reported_endpoints(hypothesis TEXT,operation TEXT,report TEXT,PRIMARY KEY(hypothesis,operation))')
        self.db.commit()
        convergence.initialize(self)
        if not hasattr(self, 'view'):
            with self.db:
                convergence.sync(self)
                verification_tasks.initialize_handoffs(self)

    def tool_schemas(self):
        existing = super().tool_schemas()
        names = {s['function']['name'] for s in existing}
        if 'record_review' in names:
            existing = deepcopy(existing)
            for schema in existing:
                if schema['function']['name'] == 'record_review':
                    schema['function']['parameters'] = self.tools['record_review'][0].model_json_schema()
        combined = existing + [{'type': 'function', 'function': {'name': name, 'description': description,
                           'parameters': model.model_json_schema()}}
                          for name, (model, description) in self.tools.items() if name not in names]
        for schema in combined:
            schema['function']['parameters'] = inline_schema(schema['function']['parameters'])
            if schema['function']['name'] in self.tools:
                schema['function']['description']=self.tools[schema['function']['name']][1]
                schema['function']['parameters'] = inline_schema(self.tools[schema['function']['name']][0].model_json_schema())
        return combined

    def context(self):
        context = deepcopy(super().context())
        context['large_data_tools'] = {
            'workflow': 'get_data_profile -> start_data_job -> read_data_result. Compute is scheduled without model polling.',
            'query_data': 'Small interactive path only: 10 million SQLite VM steps and 100000 result rows. Use a full data job for large scans/aggregates.',
            'coverage': 'Job completion covers only its declared query; it does not certify an estimator or causal interpretation.'}
        if 'record_review' in self.tools:
            context['repair_packet'] = ReviewDrafts(self).packet()
            context['review_contract'] = self.packet.get('release_review_contract', {'legacy_snapshot': True})
            context['coverage_action_catalog_tool'] = 'get_review_contract'
            allocation = getattr(self, 'review_allocation', None)
            if allocation:
                context['review_allocation'] = allocation
                resources = context.get('resources', {})
                attempts = resources.get('http_attempts_started', 0)
                resources['limits'] = {**resources.get('limits', {}), 'max_http_attempts': allocation['maximum_requests']}
                resources['remaining_http_attempts'] = max(0, allocation['maximum_requests']-attempts)
                resources['remaining_normal_requests'] = max(0, allocation['normal_requests']-attempts)
            task = context.get('review_task', {})
            for field, value in list(task.items()):
                if len(encoded(value).encode()) > 12000:
                    task[field] = {'navigation_only': True, 'original_version': digest(value),
                        'read_ref': self.packet['target_ref'] if field == 'candidate_record' else 'directory:all',
                        'instruction': 'Read exact frozen target/related records with read_memory/read_artifact by pages. This is not a scientific summary.'}
        else:
            if hasattr(self, 'db') and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='release_stages'").fetchone():
                context['execution_task_view'] = stage_health(self)
                unverified = [a for a in self.records('assessment') if not self.clearance(a['ref'])]
                current = [a for a in unverified if self.after_marker(a['ref'])]
                context['review_readiness'] = [review_contract(self, a['ref']) | {'clearance': False} for a in current[-8:]]
                context['unverified_claim_navigation'] = {'total': len(unverified), 'current_stage': len(current),
                    'current_contracts_shown': min(8, len(current)), 'prior_claim_refs': [a['ref'] for a in unverified if not self.after_marker(a['ref'])][-8:],
                    'tool': 'get_claim_readiness', 'policy': 'Read exact old claims on demand. Prior model-authored state is not an authoritative clearance.'}
                context['research_agenda'] = convergence.agenda(self)
                context['verification_repair_tasks']=verification_tasks.repair_tasks(self)
                context['verified_unpublished_findings']=verification_tasks.unpublished_findings(self)[-8:]
                context['deferred_verified_findings']=[a for a in verification_tasks.unpublished_findings(self,include_deferred=True) if a['publication_handoff']][-8:]
                context['workflow_phase']=verification_tasks.phase(self)
                # Full specs remain available through get_claim_readiness;
                # repeating up to eight complete method bodies grows without bound.
                for contract in context['review_readiness']:
                    contract['analysis_specs'] = [{k:s[k] for k in ('target_ref','analysis_spec_ref')} for s in contract['analysis_specs']]
            # Execution blocks remain distinct from scientific rejection.
            if hasattr(self, 'db') and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='release_task_state'").fetchone():
                context['blocked_execution_tasks'] = [dict(job_ref=r[0], state=r[1], reason=r[2])
                    for r in self.db.execute('SELECT job,state,reason FROM release_task_state ORDER BY rowid DESC LIMIT 8')]
                context['blocked_execution_tasks_total'] = self.db.execute('SELECT count(*) FROM release_task_state').fetchone()[0]
        return context

    def call(self, name, args, operation_id):
        return durable_call(self, name, args, operation_id, lambda: self._business_call(name, args, operation_id))

    def _business_call(self, name, args, operation_id):
        # result_ref is a paging handle, while native scientific records use
        # file refs. Resolve only exact owned completed results, with a durable
        # binding receipt; never guess IDs or replace scientific prose.
        bindings = []
        reference_fields = {'evidence_refs', 'data_refs', 'artifact_refs', 'check_artifact_refs', 'counterevidence_refs', 'source_refs'}
        def canonical(value, field=None):
            if isinstance(value, dict):
                return {k: canonical(v, k) for k, v in value.items()}
            if isinstance(value, list):
                return [canonical(v, field) for v in value]
            if field in reference_fields and isinstance(value, str) and value.startswith('dataresult:'):
                match = next((a for j in DataJobs(self).jobs() for a in j['attempts']
                              if j['status'] == 'completed' and a.get('result_ref') == value), None)
                if match:
                    artifact = next(a for a in match['artifacts'] if a['path'].endswith('result.sqlite'))
                    self.file(artifact['ref'])
                    bindings.append({'requested_ref': value, 'actual_file_ref': artifact['ref'], 'sha256': artifact['sha256']})
                    return artifact['ref']
            return value
        original = args
        args = canonical(args)
        if bindings:
            path = self.science/'reference_bindings'/(digest(operation_id)+'.json')
            receipt = {'operation_id': operation_id, 'tool': name, 'bindings': bindings,
                       'submitted_arguments': original, 'canonical_arguments': args, 'scientific_text_changed': False}
            if path.exists() and json.loads(path.read_text()) != receipt:
                raise ValueError('reference_binding_operation_conflict')
            if not path.exists(): write_json(path, receipt)
            self.file_ref(path)
        if name == 'commit_review':
            try:
                item = ReviewDrafts(self).read(args['draft_ref'])
            except ValueError:
                item = None
            if item:
                row = self.db.execute('SELECT result FROM release_draft_commits WHERE ref=?', (item['draft_ref'],)).fetchone()
                if row:
                    if args['expected_hash'] != item['draft_hash']:
                        return {'ok': False, 'error_code': 'draft_version_conflict', 'draft_ref': item['draft_ref']}
                    return json.loads(row[0])
        result = super().call(name, args, operation_id)
        if name in DATA_TOOLS and result.get('ok') is False:
            result = {**result, 'error_code': result.get('error', 'data_tool_error').split(':', 1)[0],
                      'retryable': False, 'artifact_refs': [], 'scientific_status_changed': False}
        if name == 'record_review' and result.get('ok') is False:
            draft = ReviewDrafts(self).save(encoded(args), key=operation_id)
            result = {**result, 'error_code': 'review_contract_invalid',
                      'draft_ref': draft['draft_ref'], 'draft_hash': draft['draft_hash'],
                      'repair_packet': ReviewDrafts(self).packet()}
        if name == 'query_data' and result.get('ok') is False:
            error = result.get('error', '')
            code = 'vm_step_limit' if 'interrupted' in error else 'output_row_limit' if '100000' in error else 'sql_error'
            result = {**result, 'error_code': code, 'retryable': code != 'sql_error',
                      'query_hash': digest(args.get('sql')), 'limit_kind': code,
                      'limit_units': {'vm_steps': 10000000, 'output_rows': 100000},
                      'next_action': 'Use get_data_profile and start_data_job for complete full-SQL execution; do not repeat the same small query.'}
        return result

    def dispatch(self, name, args, key):
        if not hasattr(self, 'view'):
            if name=='save_hypothesis' and args.get('activation','active')=='active':
                findings=verification_tasks.unpublished_findings(self);repairs=verification_tasks.repair_tasks(self)
                if findings or repairs:
                    return {'ok':False,'error_code':'verification_or_delivery_priority','verified_unpublished_findings':findings[-8:],
                            'verification_repair_tasks':repairs,'next_action':'Finish these existing verification/delivery tasks first, or save the proposal as backlog. No new scientific conclusion is inferred.'}
            failure = convergence.preflight(self, name, args)
            if failure: return failure
            if name == 'get_research_agenda': return convergence.agenda(self) | {'verification_repair_tasks':verification_tasks.repair_tasks(self),'verified_unpublished_findings':verification_tasks.unpublished_findings(self)[-8:],'deferred_verified_findings':[a for a in verification_tasks.unpublished_findings(self,include_deferred=True) if a['publication_handoff']][-8:],'workflow_phase':verification_tasks.phase(self)}
            if name == 'request_revalidation': return verification_tasks.request(self,args,key)
            if name == 'focus_hypothesis': return convergence.activate(self, args['hypothesis_ref'])
            if name == 'set_hypothesis_goal': return convergence.set_goal(self, args)
            if name == 'close_hypothesis': return convergence.close(self, args, key)
            if name == 'save_hypothesis':
                activation = args.pop('activation', 'active')
                result = super().dispatch(name, args, key)
                if result.get('ref'):
                    item = convergence.get(self, result['ref']); item['status'] = activation; convergence.save(self, item)
                return result
        if name == 'get_claim_readiness':
            return review_contract(self, args['target_ref']) | {'clearance': self.clearance(args['target_ref']),'verification_followup':verification_tasks.followup(self,args['target_ref'])}
        if name == 'inspect_report_disclosure': return verification_tasks.inspected_disclosure(self)
        if name == 'close_research_stage':
            return close_stage(self, **args, key=key)
        if name == 'get_review_contract':
            contract=self.packet.get('release_review_contract', {'legacy_snapshot': True})
            return {'contract': contract,
                    'computation_actions': action_catalog(self),
                    'submission_format':submission_guide(contract,self.tools['record_review'][0].model_json_schema()),
                    'failure_exit': 'Declare complete + insufficient_evidence and explicit unchecked_scope when the work cannot be checked; no clearance is then granted.'}
        if name == 'validate_review_submission':
            errors = ReviewDrafts(self).validate(args['raw_arguments'])
            return {'valid': not errors, 'validation_errors': errors, 'committed': False}
        if name == 'record_review':
            errors = coverage_errors(self, args)
            if errors:
                raise ValueError(encoded({'error_code': 'coverage_incomplete', 'validation_errors': errors}))
        if name == 'finish_research':
            findings=verification_tasks.unpublished_findings(self)
            if findings and not args.get('assessment_refs'):
                return {'ok':False,'error_code':'verified_findings_await_delivery','verified_unpublished_findings':findings[-8:],
                        'next_action':'Choose the applicable verified assessments for the report, or explicitly revise/withdraw a finding with evidence. Do not silently discard completed verification.'}
            # Mechanical disclosure of already recorded endpoints, not a new
            # scientific judgment or automatic result incorporation.
            selected={self.record(ref,'assessment')['hypothesis_ref'] for ref in args.get('assessment_refs',[])}
            supplied=dict(args.get('other_hypotheses',{}));added={}
            disclosure_binding=None
            for h in convergence.items(self):
                ref=h['hypothesis_ref']
                if ref not in selected and ref not in supplied and h.get('endpoint'):
                    added[ref]='Recorded endpoint '+h['status']+': '+h['endpoint']['reason']+' (Original records retained; execution failure is not refutation.)'
            if added:
                args={**args,'other_hypotheses':{**supplied,**added}}
                binding_path=self.science/'disclosure_bindings'/(digest(key)+'.json')
                write_json(binding_path,
                    {'operation':key,'explicit_other_hypotheses':supplied,'copied_recorded_endpoints':added,
                     'new_scientific_judgments_inferred':False})
                disclosure_binding=self.file_ref(binding_path,'recorded_endpoint_disclosure')
            failure = delivery_preflight(self, args, key)
            if failure:
                return failure
            result=super().dispatch(name,args,key)
            return {**result,'disclosure_binding':disclosure_binding} if disclosure_binding else result
        if name == 'request_review':
            job = self.job(args['job_ref'])
            if job['status']=='completed' and not self.clearance(job['target_ref']):
                repair=verification_tasks.followup(self,job['target_ref'])
                if repair['eligible']:
                    return {'ok':False,'error_code':'review_complete_but_target_uncleared','verification_followup':repair,
                            'next_action':'Use request_revalidation with this target_ref and expected_review_ref. It schedules a new bounded directed check; the old completed opinion is retained.'}
            contract = review_contract(self, job['target_ref'])
            if not contract['ready'] and job['status'] != 'completed':
                return {'ok': False, 'error_code': 'review_not_ready', 'contract': contract,
                        'model_requests_sent': 0, 'next_action': contract['repair']}
            if contract['ready']:
                # Readiness can improve after registering a spec. This is not
                # a quota extension; local-cap blocks still need allocation.
                self.db.execute("DELETE FROM release_task_state WHERE job=? AND reason LIKE 'review_not_ready:%'", (job['ref'],))
            blocked = self.db.execute('SELECT state,reason FROM release_task_state WHERE job=?', (args['job_ref'],)).fetchone()
            if blocked:
                return {'ok': False, 'error_code': 'blocked_execution', 'job_ref': args['job_ref'],
                        'reason': blocked[1], 'next_action': 'Preserve this unresolved claim. Continue independent work or use an explicit operator allocation event within the original project authorization.'}
        if name in ('register_analysis_spec', 'revise_analysis_spec'):
            target = self.record(args['target_ref'])
            if args['spec'].get('claim_level') == 'causal':
                strategy = args['spec'].get('identification_strategy') or ''
                ids = args['spec'].get('identification_evidence_refs', [])
                if len(strategy.strip()) < 20 or not ids:
                    raise ValueError('causal_identification_required: declare the identification strategy, assumptions and exact received design evidence. Associations alone do not identify direction. A narrower claim requires a new hypothesis, preserving the original as unresolved.')
                self.references(ids)
            for h in ([args['target_ref']] if target['record_type']=='hypothesis' else self.target_hypotheses(args['target_ref'])):
                goal = convergence.get(self, h)['goal']
                if goal and goal['claim_level'] != args['spec'].get('claim_level', 'association'):
                    raise ValueError('claim_level_changed: use a new hypothesis; do not lower the original frozen acceptance level')
            self.references([args['spec']['dataset_ref'], args['spec']['code_ref']])
            if not all(args['spec'][k].startswith('file:') for k in ('dataset_ref', 'code_ref')):
                raise ValueError('analysis_spec_file_refs_required: bind actual versioned dataset and source files, not claims or opinions')
            code_path, _ = self.file(args['spec']['code_ref'])
            if code_path.suffix.lower() not in ('.py', '.sql'):
                raise ValueError('analysis_spec_source_required: code_ref must identify the actual Python/SQL source file')
            prior = self.db.execute('SELECT body FROM release_analysis_specs WHERE target=?', (args['target_ref'],)).fetchone()
            consumed = any((self.root.parent/'reviews'/j['ref']/'inputs').exists()
                           for j in self.jobs() if args['target_ref'] in [j['target_ref'], *self.target_hypotheses(j['target_ref'])])
            if name == 'revise_analysis_spec':
                row = self.db.execute('SELECT spec_ref FROM release_analysis_specs WHERE target=?', (args['target_ref'],)).fetchone()
                if not row or row[0] != args['expected_spec_ref']: raise ValueError('analysis_spec_revision_conflict')
                if consumed: raise ValueError('analysis_spec_consumed: create a new scientific target; frozen review inputs are immutable')
                self.db.execute('INSERT OR IGNORE INTO release_analysis_spec_history VALUES (?,?)', (row[0], prior[0]))
                self.db.execute('DELETE FROM release_analysis_specs WHERE target=?', (args['target_ref'],))
                prior = None
            elif prior and json.loads(prior[0]) != args['spec']:
                raise ValueError('analysis_spec_conflict: create a new scientific target; do not rebind old computations')
            if not prior and name != 'revise_analysis_spec' and any((self.root.parent/'reviews'/j['ref']/'inputs').exists()
                                 for j in self.jobs('pending')+self.jobs('running')
                                 if args['target_ref'] in [j['target_ref'], *self.target_hypotheses(j['target_ref'])]):
                raise ValueError('analysis_spec_after_snapshot: create a new target before changing the review contract')
            ref = 'analysis:'+digest([target, args['spec']])[:24]
            self.db.execute('INSERT OR IGNORE INTO release_analysis_specs VALUES (?,?,?,?)',
                            (args['target_ref'], digest(target), ref, encoded(args['spec'])))
            if not prior:
                self.add('review_note', {'author': 'researcher', 'target_ref': args['target_ref'],
                    'hypothesis_refs': self.target_hypotheses(args['target_ref']),
                    'analysis_spec_ref': ref, 'analysis_spec': args['spec'], 'scientific_certification': False})
            return {'analysis_spec_ref': ref, 'target_ref': args['target_ref'], 'spec': args['spec'],
                    'method_verification': 'Declared specification only; actual checks are still required.'}
        if name in DATA_TOOLS:
            jobs = DataJobs(self)
            if name == 'get_data_profile':
                return jobs.profile()
            if name == 'start_data_job':
                return jobs.describe(jobs.start(**args, key=key))
            if name == 'get_data_job':
                return jobs.describe(jobs.get(args['job_ref']))
            if name == 'read_data_result':
                return jobs.read(**args)
            if name == 'cancel_data_job':
                return jobs.cancel(args['job_ref'])
            return jobs.describe(jobs.retry(args['job_ref'], key=key))
        if name in DRAFT_TOOLS:
            drafts = ReviewDrafts(self)
            if name == 'save_review_draft':
                return draft_receipt(drafts.save(args['raw_arguments'], key=key))
            if name == 'read_review_draft':
                item = drafts.read(args['draft_ref']); section=args['section']
                text = item[section] if section=='raw_arguments' else encoded(item[section])
                end=args['offset']+args['limit']
                return {'draft_ref':item['draft_ref'],'draft_hash':item['draft_hash'],'head_ref':item['head_ref'],
                        'is_head':item['is_head'],'section':section,'text':text[args['offset']:end],
                        'next_offset':end if end<len(text) else None,'total_characters':len(text),
                        'raw_arguments':text[args['offset']:end] if section=='raw_arguments' else None,
                        'repair_packet':drafts.packet()}
            if name == 'patch_review_draft':
                return draft_receipt(drafts.patch(args['draft_ref'], args['expected_hash'], args['field_changes'], key=key))
            return drafts.commit(args['draft_ref'], args['expected_hash'],
                                 lambda body: {**super(BusinessTools, self).dispatch('record_review', body, 'draft:'+args['draft_ref']),
                                               'action_ref': 'check:'+digest(key)[:24]})
        return super().dispatch(name, args, key)


class DurableToolsRuntime:
    def recover_rejected_draft(self):
        if 'record_review' not in self.ws.tools or self.cp.get('pending'):
            return
        if not self.cp.get('messages'):
            return
        value = None
        for last in reversed(self.cp['messages']):
            if last.get('role') == 'assistant':
                break
            try:
                candidate = json.loads(last.get('content', ''))
            except (ValueError, TypeError):
                continue
            if isinstance(candidate, dict) and (candidate.get('protocol_error') or candidate.get('ok') is False):
                value = candidate; break
            if last.get('role') == 'tool':
                break
        if value is None:
            return
        path = self.ws.private/'turns'/(str(self.cp['responses'])+'.json')
        if not path.exists():
            return
        try:
            calls = json.loads(path.read_text())['choices'][0]['message'].get('tool_calls') or []
            for index, call in enumerate(calls):
                if call.get('function', {}).get('name') == 'record_review':
                    ReviewDrafts(self.ws).save(call['function']['arguments'], key=['response', self.cp['responses'], index])
        except (KeyError, TypeError, IndexError, AttributeError):
            pass

    def accept(self, raw, delivery=None):
        # Native parsing still controls batch atomicity and protocol continuity.
        # Draft copies are private recovery data, never tool calls on the wire.
        if delivery is not None and self.cp.get('delivered_attempt', -1) >= delivery:
            self.recover_rejected_draft()
            return
        original = raw
        normalized, changes, wire_errors = normalize_tool_containers(raw, self.ws.tools)
        if delivery is not None and (self.ws.private/'requests'/f'{delivery}.json').exists():
            from experiments.insight_research.runtime_memory import reconstruct_request
            request=reconstruct_request(self.ws.private,delivery)
            offered={t['function']['name'] for t in request.get('tools',[])}
            try:calls=normalized['choices'][0]['message'].get('tool_calls') or []
            except (KeyError,TypeError,IndexError,AttributeError):calls=[]
            if not isinstance(calls,list):calls=[]
            for index,call in enumerate(calls):
                if not isinstance(call,dict):continue
                function=call.get('function')
                if not isinstance(function,dict):continue
                name=function.get('name')
                if name not in offered:
                    wire_errors.append({'call':index,'error_code':'tool_not_admitted_in_original_request','tool':name,
                        'allowed_tools':sorted(offered),'repair':'Use only the exact tools offered by this paid request; the entire batch executed zero tools.'})
        if changes or wire_errors:
            number = self.cp['responses']+1
            write_json(self.ws.private/'wire_originals'/f'{number}.json', original)
            write_json(self.ws.private/'wire_normalizations'/f'{number}.json', {
                'source_response': number, 'source_attempt': delivery, 'changes': changes, 'errors': wire_errors,
                'original_response_hash': digest(original), 'no_scientific_fields_inferred_or_deleted': True})
            raw = normalized
            if wire_errors: raw['choices'][0]['finish_reason'] = 'invalid_tool_json'
        try:
            calls = raw['choices'][0]['message'].get('tool_calls') or []
            if len(calls) > 1 and any(c.get('function', {}).get('name') in ('commit_review', 'close_research_stage', 'close_hypothesis') for c in calls):
                raw = deepcopy(raw)
                raw['choices'][0]['finish_reason'] = 'mixed_review_commit_batch'
        except (KeyError, TypeError, IndexError, AttributeError):
            pass
        super().accept(raw, delivery)
        if raw is not original:
            write_json(self.ws.private/'turns'/(str(self.cp['responses'])+'.json'), original)
        if wire_errors:
            self.cp['messages'].append({'role': 'user', 'content': encoded({'wire_errors': wire_errors, 'executed_tools': 0})})
            self.save()
        if 'record_review' not in self.ws.tools or self.cp.get('pending'):
            return
        try:
            calls = raw['choices'][0]['message'].get('tool_calls') or []
            for index, call in enumerate(calls):
                if call.get('function', {}).get('name') != 'record_review':
                    continue
                ReviewDrafts(self.ws).save(call['function']['arguments'], key=['response', self.cp['responses'], index])
            packet = ReviewDrafts(self.ws).packet()
            if packet:
                self.cp['messages'].append({'role': 'user', 'content': encoded({'repair_packet': packet})})
                self.save()
        except (KeyError, TypeError, IndexError, AttributeError):
            pass  # The original malformed transport is retained by native accept.

    def prepare_payload(self, payload):
        self.recover_rejected_draft()
        payload = super().prepare_payload(payload)
        if 'record_review' in self.ws.tools:
            packet = ReviewDrafts(self.ws).packet()
            allocation = getattr(self.ws, 'review_allocation', {})
            if allocation:
                attempts = self.journal.state['attempts']
                payload['messages'].append({'role': 'user', 'content': encoded({'review_slice': allocation,
                    'requests_started': attempts, 'normal_requests_remaining': max(0, allocation['normal_requests']-attempts),
                    'maximum_requests_remaining': max(0, allocation['maximum_requests']-attempts)})})
            if packet:
                payload['messages'].append({'role': 'user', 'content': encoded({'repair_packet': packet,
                    'review_allocation': allocation, 'policy': 'Repair locally with explicit field patches. Repeated unchanged errors end in blocked_execution; retain unresolved scope.'})})
            if allocation and self.journal.state['attempts'] >= allocation.get('closeout_start_request', allocation['normal_requests']):
                allowed = {*DRAFT_TOOLS, 'record_review', 'read_memory', 'read_artifact', 'get_review_contract', 'validate_review_submission'}
                payload['tools'] = [s for s in payload['tools'] if s['function']['name'] in allowed]
                payload['messages'].append({'role': 'user', 'content': 'Review closeout: no new computations or research questions. Submit checks already performed and exact unchecked scope now. If coverage is incomplete, complete with insufficient_evidence; do not remain in a checkpoint or invent coverage. Remaining requests are for submission and explicit field repair.'})
        else:
            if verification_tasks.phase(self.ws)=='choose_next_goal':
                payload['tools']=[s for s in payload['tools'] if s['function']['name']!='finish_research']
                payload['messages'].append({'role':'user','content':'Prior findings were delivered or closed unresolved tasks have an explicit saved execution handoff. A handoff does not grant clearance or constitute a formal report. Choose the next worthwhile concrete hypothesis or state a real external/data blocker; do not repeatedly resubmit old unverified findings. New work remains bounded by the original authorization.'})
            selected = convergence.focus(self.ws)
            if selected:
                u = convergence.usage(self.ws, selected['hypothesis_ref']); p = convergence.policy(self.ws)
                if u['requests'] >= p['hypothesis_requests'] or u['test_runs'] >= p['hypothesis_test_runs']:
                    blocked = {'save_hypothesis','register_test','run_test','run_python','start_data_job','retry_data_job'}
                    payload['tools'] = [s for s in payload['tools'] if s['function']['name'] not in blocked]
                    payload['messages'].append({'role': 'user', 'content': 'Focus closeout due: evaluate the original prediction and close_hypothesis now. Accepted/refuted needs the matching cleared assessment. Otherwise close inconclusive/abandoned with evidence and reason. Do not open another branch or change the old prediction.'})
            if not selected and verification_tasks.phase(self.ws)!='choose_next_goal' and self.ws.records('hypothesis') and self.journal.guard.inspect()['effective_requests_without_progress']>=self.journal.guard.stop:
                allowed={'read_context','get_research_agenda','get_claim_readiness','request_revalidation','read_memory','read_artifact',
                         'update_research_state','finish_research','close_research_stage','close_hypothesis'}
                payload['tools']=[s for s in payload['tools'] if s['function']['name'] in allowed]
                payload['messages'].append({'role':'user','content':'All empirical H tasks are closed; use the bounded verification/delivery closeout. Prior recorded endpoint dispositions are mechanically disclosed by finish_research. Do not repeatedly rebuild historical IDs or start new computations in this closeout slice.'})
        if len(encoded(payload).encode()) > self.ws.settings['limits']['max_request_bytes']:
            raise Pending('request including pinned repair packet exceeds capacity; raw draft retained')
        return payload

    def run(self, *args, **kwargs):
        if 'record_review' not in self.ws.tools and stage_outcome(self.ws):
            # Recover a crash after the close transaction but before the paid
            # cursor checkpoint. Drain only; never buy a post-terminal turn.
            args = (0,); kwargs = {}
        # Called with one model step by the graph. Complete queued compute before
        # another request. No LLM spends a turn polling its own running worker.
        import fcntl
        lock = (self.ws.private/'runtime.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return {'status': 'pending', 'reason': 'another data worker owns this task'}
        try:
            if self.path.exists():
                self.cp = json.loads(self.path.read_text())
            from .transport_recovery import resume_transient_window
            transient_pause=resume_transient_window(self)
            if transient_pause: return transient_pause
            original = self.ws.private/'wire_originals'/(str(self.cp['responses'])+'.json')
            if original.exists():
                write_json(self.ws.private/'turns'/(str(self.cp['responses'])+'.json'), json.loads(original.read_text()))
            self.recover_rejected_draft()
            guard = getattr(self.journal, 'guard', None)
            jobs = DataJobs(self.ws)
            compute_deadline = time.monotonic()+self.ws.settings['limits']['round_wall_seconds']
            while True:
                remaining = guard.inspect()['remaining_wall_seconds'] if guard else 600
                result = jobs.run_next(remaining_seconds=min(remaining, compute_deadline-time.monotonic()))
                if not result:
                    break
                if result['status'] == 'waiting_for_authorized_time':
                    return self.pause('persistent study wall deadline cannot admit queued compute')
                self.ws.db.commit()
                # Stored in owned checkpoint; initial/context compaction can
                # recover the same state using get_data_job after a crash.
                if not self.cp['messages']:
                    self.cp['messages'] = self.initial()
                self.cp['messages'].append({'role': 'user', 'content': encoded({'data_job_update': {
                    k: result.get(k) for k in ('job_ref', 'status', 'result_ref', 'coverage', 'error')}})})
                self.save()
        finally:
            lock.close()
        result = super().run(*args, **kwargs)
        if result.get('status')=='pending' and result.get('reason','').startswith('bounded transport retry allowance exhausted'):
            from .transport_recovery import resume_transient_window
            transient_pause=resume_transient_window(self)
            if transient_pause: return transient_pause
            if self.cp.get('transport_failures')==0:
                return self.pause('transport_cooldown:'+str(time.time()+1))
        if 'record_review' not in self.ws.tools:
            outcome = stage_outcome(self.ws)
            if outcome:
                return {'status': 'stage_closed', 'stage_outcome': outcome, 'scientific_certification': False}
        return result
