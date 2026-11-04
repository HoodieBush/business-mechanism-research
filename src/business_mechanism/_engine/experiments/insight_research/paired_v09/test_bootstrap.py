import json,sqlite3,unittest
from copy import deepcopy
from unittest.mock import patch
from ..common import ROOT,Pending
from ..composed_world import ComposedWorld
from ..paired_v08.workspace import ResearchWorkspace,BaselineWorkspace
from ..paired_v01.budget import StudyBudget
from ..paired_v02 import test_interface as fixtures
from ..test_acceptance import settings,raw_call
from .orchestrator import ResearchRun
from .continuation import capture,prepare
from .run import execute

class BootstrapTests(unittest.TestCase):
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
            execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16},workflow_policy={'max_lineage_reviews':4})
        config['limits'].update(token_allowance=1500000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程：有传输状态的新核验者首启',ComposedWorld(),config);return self.ws

    def copied(self,name):
        m=json.loads((ROOT/'experiments/insight_research/review/workflow_20261024/continuation_v09'/(name+'.json')).read_text())
        old=m['parent_identity'];settings=deepcopy(old['settings']);identity={**m['parent_budget_identity'],'study_id':'engineering_bootstrap_'+name}
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version']);target=self.folder/name
        prepare(target,m,old['question'],world,settings,identity)
        cls=ResearchWorkspace if name=='candidate' else BaselineWorkspace
        ws=cls(target/'researcher',old['question'],world,settings,reopen=True);self.addCleanup(ws.close)
        return target,m,ws,StudyBudget(target/'common_budget.sqlite',identity)

    def test_b01_fresh_critic_with_real_journal_state_creates_checkpoint_and_completes(self):
        self.make('independent');h,r,a=self.assessed();budget=self.budget();root=self.folder/'independent';job=self.ws.jobs('pending')[0]
        peer=root/'reviews'/job['ref']/'critic/private';self.assertFalse((peer/'checkpoint.json').exists())
        def provider(config,payload):
            if not (peer/'transport.json').exists() or json.loads((peer/'transport.json').read_text())['attempts']==1:
                raw=raw_call('query_data',{'sql':'SELECT count(*) FROM hourly','purpose':'实际查询后完成工程核验'})
            else:
                with sqlite3.connect(peer/'critic.sqlite') as db:action=db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                raw=raw_call('record_review',fixtures.review(a['ref'],action))
            raw['usage']={'total_tokens':11};return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider) as model:
            ResearchRun(root,self.ws,fixtures.MODEL,budget).review_job(job)
        self.assertEqual(model.call_count,2);self.assertEqual(budget.snapshot()['http_attempts'],2)
        self.assertEqual(json.loads((peer/'checkpoint.json').read_text())['status'],'completed')
        self.assertEqual(len(self.ws.records('review')),1)

    def test_b02_unstarted_initialized_role_preserved_and_paid_review_has_priority(self):
        root,m,ws,budget=self.copied('candidate');before=budget.snapshot()
        with budget.connect() as db:paid={x for x, in db.execute('SELECT DISTINCT role FROM attempts')}
        jobs=ws.jobs('running')+ws.jobs('pending');old=next(j for j in jobs if 'critic:'+j['ref'] in paid)
        fresh=next(j for j in jobs if 'critic:'+j['ref'] not in paid);path=root/'reviews'/fresh['ref']/'critic/private/checkpoint.json'
        self.assertFalse(path.exists())
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('paid review first,0newcalls')):
            ResearchRun(root,ws,fixtures.MODEL,budget).run(1)
        self.assertEqual(ws.job(old['ref'])['status'],'completed');self.assertFalse(path.exists());self.assertEqual(budget.snapshot(),before)

    def test_b03_missing_paid_checkpoint_cannot_be_reclassified_as_unstarted(self):
        root,m,ws,budget=self.copied('candidate')
        (root/'research_run.lock').touch()
        with budget.connect() as db:paid={x for x, in db.execute('SELECT DISTINCT role FROM attempts')}
        job=next(j for j in ws.jobs('running') if 'critic:'+j['ref'] in paid)
        (root/'reviews'/job['ref']/'critic/private/checkpoint.json').unlink()
        with self.assertRaisesRegex(Pending,'paid role missing checkpoint'):capture(root)

    def test_b04_uncheckpointed_local_critic_actions_not_discarded_as_unstarted(self):
        root,m,ws,budget=self.copied('candidate')
        (root/'research_run.lock').touch()
        path=next(p for p in root.glob('reviews/*/critic/private/critic.sqlite') if not (p.parent/'checkpoint.json').exists())
        with sqlite3.connect(path) as db:db.execute('INSERT INTO actions VALUES (?,?)',('engineering_pending_action','{}'))
        with self.assertRaisesRegex(Pending,'uncheckpointed actions'):capture(root)

    def test_b05_host_error_preserves_execution_and_fee_status_without_refutation(self):
        class Runner:
            budget=type('Budget',(),{'snapshot':lambda self:{'accounted_tokens':123,'http_attempts':2,'unknown_reserve':50}})()
            def run(self,steps):raise FileNotFoundError('engineering bootstrap failure')
        with self.assertRaises(FileNotFoundError):execute(Runner(),self.folder,1)
        status=json.loads((self.folder/'runtime_status.json').read_text());cost=json.loads((self.folder/'common_budget_snapshot.json').read_text())
        self.assertEqual(status['category'],'host_error');self.assertFalse(status['scientific_refutation']);self.assertEqual(cost['accounted_tokens'],123)

if __name__=='__main__':unittest.main()
