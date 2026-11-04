import json,unittest
from copy import deepcopy
from unittest.mock import patch
from ..common import ROOT,digest,sha
from ..composed_world import ComposedWorld
from ..paired_v01.budget import StudyBudget
from ..paired_v02 import test_interface as fixtures
from ..test_acceptance import settings,FixtureJournal
from .workspace import ResearchWorkspace
from .continuation import prepare
from .orchestrator import ResearchRun,BaselineRun

class CommonReviewTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=fixtures.MODEL,
            execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16,'review_http_limit':18},workflow_policy={'max_lineage_reviews':4})
        config['limits'].update(token_allowance=1250000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程：回应对象与原件生产动作',ComposedWorld(),config);return self.ws

    def copied(self,name,token_limit=None):
        manifest=json.loads((ROOT/'experiments/insight_research/review/workflow_20261024/continuation_v08'/(name+'.json')).read_text())
        old=manifest['parent_identity'];config=deepcopy(old['settings']);config['execution_policy']['review_http_limit']=18
        identity={**manifest['parent_budget_identity'],'study_id':'engineering_v08_'+name}
        if token_limit is not None:
            config['limits']['token_allowance']=token_limit;identity['token_allowance']=token_limit
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version']);output=self.folder/name
        prepare(output,manifest,old['question'],world,config,identity)
        from .workspace import BaselineWorkspace
        cls=ResearchWorkspace if name=='candidate' else BaselineWorkspace
        ws=cls(output/'researcher',old['question'],world,config,reopen=True);self.addCleanup(ws.close)
        budget=StudyBudget(output/'common_budget.sqlite',identity)
        return output,manifest,ws,budget

    def test_x01_existing_explicit_output_binds_unique_producing_action(self):
        h,r,a=self.assessed();result=self.call('query_data',{'sql':'SELECT count(*) AS n FROM hourly','purpose':'明确被引用的实际复算'})
        issue={'issue_id':'count','type':'methodological_disagreement','description':'工程来源对应','affected_refs':[a['ref']],
            'basis':'recomputed','blocking':False,'evidence_locations':[result['file']['ref']],'action_refs':[],'check_artifact_refs':[],
            'claim_impact':'仅来源字段','minimal_next_step':'核对实际原件'}
        original=fixtures.review(a['ref'],r['action_ref'],issues=[issue]);corrected,changes=self.ws.normalize_submission('review_claim',{'job_ref':self.ws.jobs('pending')[0]['ref'],'review':original})
        self.assertEqual(corrected['review']['issues'][0]['action_refs'],[result['action_ref']])
        self.assertTrue(changes['artifact_writer_links']);self.assertEqual(original['issues'][0]['action_refs'],[])

    def test_x02_public_or_ambiguous_reference_cannot_guess_a_recompute(self):
        h,r,a=self.assessed();issue={'issue_id':'missing','basis':'recomputed','action_refs':[],'evidence_locations':[self.source()],'check_artifact_refs':[]}
        corrected,changes=self.ws.normalize_submission('review_claim',{'review':{'issues':[issue]}})
        self.assertEqual(corrected['review']['issues'][0]['action_refs'],[]);self.assertFalse(changes['artifact_writer_links'])
        output=self.call('query_data',{'sql':'SELECT count(*) FROM hourly','purpose':'明确产物'})
        event=self.ws.db.execute("SELECT body FROM events WHERE id=?",(int(output['action_ref'][6:]),)).fetchone()[0]
        with self.ws.db:self.ws.db.execute('INSERT INTO events(operation,body) VALUES (?,?)',('engineering_duplicate_producer',event))
        issue['evidence_locations']=[output['file']['ref']]
        corrected,changes=self.ws.normalize_submission('review_claim',{'review':{'issues':[issue]}})
        self.assertEqual(corrected['review']['issues'][0]['action_refs'],[]);self.assertFalse(changes['artifact_writer_links'])

    def test_x03_real_baseline_paid_review_repaired_without_new_calls_and_deadline_preserved(self):
        root,manifest,ws,budget=self.copied('baseline');before=budget.snapshot()
        with budget.connect() as db:control=db.execute('SELECT * FROM execution_control').fetchall()
        job=ws.jobs('running')[0];self.assertEqual(job['review_http_limit'],18)
        raw=root/'reviews'/job['ref']/'critic/private/turns/6.json';original=sha(raw)
        run=BaselineRun(root,ws,fixtures.MODEL,budget)
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no new calls')):
            run.review_job(job)
        self.assertEqual(ws.job(job['ref'])['status'],'completed');self.assertEqual(budget.snapshot(),before)
        self.assertEqual(sha(raw),original)
        with budget.connect() as db:after=db.execute('SELECT started,deadline FROM execution_control').fetchall()
        self.assertEqual(after,[(r[1],r[2]) for r in control])

    def test_x04_real_response_targeted_opinion_is_auditable_not_fact_without_new_calls(self):
        root,manifest,ws,budget=self.copied('candidate');before=budget.snapshot();job=ws.jobs('running')[0]
        raw=root/'reviews'/job['ref']/'critic/private/turns/6.json';original=sha(raw)
        run=ResearchRun(root,ws,fixtures.MODEL,budget)
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no new calls')):
            run.review_job(job)
        self.assertEqual(ws.job(job['ref'])['status'],'completed');self.assertEqual(budget.snapshot(),before)
        self.assertEqual(sha(raw),original)
        q=ws.record(ws.job(job['ref'])['review_ref']);target=q['issues'][0]['affected_refs'][0]
        self.assertEqual(ws.record(target)['record_type'],'review_response')
        self.assertIn(target,q['affected_versions'])
        with self.assertRaises(ValueError):ws.premise(target)
        with self.assertRaises(ValueError):ws.premise(q['ref'])

    def test_x05_explicit_local_extension_preserves_all_paid_costs_and_control(self):
        root,manifest,ws,budget=self.copied('candidate',1500000)
        self.assertEqual(budget.snapshot()['accounted_tokens'],manifest['inherited_tokens'])
        self.assertEqual(budget.snapshot()['http_attempts'],manifest['inherited_attempts'])
        self.assertEqual(ws.settings['limits']['token_allowance'],1500000)
        for path in root.glob('reviews/*/critic/private/identity.json'):
            limits=json.loads(path.read_text())['settings']['limits']
            self.assertEqual(limits['token_allowance'],1500000);self.assertEqual(limits['max_http_attempts'],18)
        self.assertTrue(json.loads((root/'review_capacity_migration.json').read_text())['persistent_deadline_and_progress_retained'])

if __name__=='__main__':unittest.main()
