import json,unittest
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
from ..common import ROOT,Pending,digest
from ..paired_v11 import test_scoped as fixtures
from ..paired_v02.test_interface import MODEL
from ..test_acceptance import raw_call
from ..paired_v07.guard import GuardedJournal
from ..paired_v01.budget import StudyBudget
from ..composed_world import ComposedWorld
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .review import Reviewer,ReviewerRuntime
from .continuation import prepare
from . import test_restoration as restore
from token_budget import reservation_bound

class JournalMemoryTests(unittest.TestCase):
    setUp=restore.RestorationTests.setUp
    tearDown=restore.RestorationTests.tearDown
    make=restore.RestorationTests.make
    call=restore.RestorationTests.call
    source=restore.RestorationTests.source
    assessed=restore.RestorationTests.assessed
    save=restore.RestorationTests.save
    budget=restore.RestorationTests.budget

    def test_m01_exact_owner_archive_readable_without_inventing_summary_or_recharging(self):
        h,r,a=self.assessed();b=self.budget();run=ResearchRun(self.folder/'self',self.ws,MODEL,b);number=[0]
        def provider(config,payload):
            number[0]+=1;raw=raw_call('query_data',{'sql':'SELECT '+str(number[0])+' AS counterexample','purpose':'owner_original_'+str(number[0])});raw['usage']={'total_tokens':10};return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):run.runtime.run(6)
        before=deepcopy(run.runtime.cp['messages']);paid=b.snapshot();records=self.ws.db.execute('SELECT ref,body FROM records').fetchall();self.assertIsNone(self.ws.state())
        run.runtime.compact();info=run.runtime.cp['journal_recovery'];archive=self.ws.private/'context_archives'/(info['archive_id']+'.json')
        self.assertEqual(json.loads(archive.read_text()),before);self.assertEqual(b.snapshot(),paid);self.assertEqual(self.ws.db.execute('SELECT ref,body FROM records').fetchall(),records)
        self.assertFalse(info['summary_generated']);self.assertTrue(self.ws.unincorporated());self.assertLess(len(run.runtime.cp['messages']),len(before))
        from ..common import encoded
        position=encoded(before).index('owner_original_1')
        out=self.call('read_memory',{'ref':'own_context:'+info['archive_id'],'offset':max(0,position-100),'limit':1000});self.assertTrue(out['memory_only']);self.assertIn('owner_original_1',out['text'])
        with self.assertRaises(ValueError):self.ws.references(['own_context:'+info['archive_id']])

    def test_m02_paid_pending_delivery_cannot_be_compacted(self):
        h,r,a=self.assessed();b=self.budget();run=ResearchRun(self.folder/'self',self.ws,MODEL,b)
        payload=run.runtime.payload(run.runtime.initial());raw=raw_call('read_context',{});raw['usage']={'total_tokens':10}
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value={'response':raw}):run.journal.call(payload)
        before=b.snapshot()
        with self.assertRaises(Pending):run.runtime.compact()
        self.assertEqual(b.snapshot(),before);self.assertTrue(run.journal.state['delivery'])

    def copied(self,mode):
        m=json.loads((ROOT/'experiments/insight_research/review/workflow_20261024b/continuation_v12'/(mode+'.json')).read_text())
        old=m['parent_identity'];settings=deepcopy(old['settings']);identity={**m['parent_budget_identity'],'study_id':'engineering_v12_'+mode};target=self.folder/('copy_'+mode)
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
        prepare(target,m,old['question'],world,settings,identity)
        ws=ResearchWorkspace(target/'researcher',old['question'],world,settings,reopen=True);self.addCleanup(ws.close)
        return target,m,ws,StudyBudget(target/'common_budget.sqlite',identity)

    def test_m03_real_stopped_owner_and_critic_recover_bound_context_and_original_costs(self):
        root,m,ws,b=self.copied('independent');before=b.snapshot();run=ResearchRun(root,ws,MODEL,b)
        job=ws.jobs('running')[0];peer=Reviewer(root/'reviews'/job['ref']/'critic',root/'reviews'/job['ref']/'inputs',
            {'research_profile':'paired_critic_v1','model_config':MODEL,'limits':{**ws.settings['limits'],'max_http_attempts':18}},reopen=True);self.addCleanup(peer.close);peer.study_budget=b
        journal=run.reviewer_journal_factory(peer,job);runtime=ReviewerRuntime(peer,MODEL,journal=journal);self.assertIsNone(peer.state())
        original=deepcopy(runtime.cp['messages']);runtime.compact();archive_id=runtime.cp['journal_recovery']['archive_id']
        self.assertEqual(json.loads((peer.private/'context_archives'/(archive_id+'.json')).read_text()),original)
        self.assertLessEqual(reservation_bound(runtime.payload()),journal.snapshot()['remaining_admission_tokens']);self.assertEqual(b.snapshot(),before)
        with self.assertRaises(ValueError):peer.references(['own_context:'+archive_id])
        with self.assertRaises(ValueError):peer.dispatch('read_memory',{'ref':'own_context:../../researcher/private/turns/1.json','offset':0,'limit':100},'denied')
        self.assertTrue(peer.dispatch('read_memory',{'ref':'own_log:0','offset':0,'limit':500},'own-log')['memory_only'])
        root2,m2,ws2,b2=self.copied('self');run2=ResearchRun(root2,ws2,MODEL,b2);before2=b2.snapshot();self.assertIsNone(ws2.state())
        run2.runtime.compact();self.assertLessEqual(reservation_bound(run2.runtime.payload()),run2.journal.snapshot()['remaining_admission_tokens']);self.assertEqual(b2.snapshot(),before2)
        self.assertEqual(len(ws2.records('hypothesis')),2);self.assertEqual(len(ws2.records('result')),3)

    def test_m04_unknown_own_memory_ref_is_a_normal_rejection(self):
        r=self.call('read_memory',{'ref':'own_process:99999'});self.assertFalse(r['ok'])
        r=self.call('read_memory',{'ref':'own_context:'+('a'*64)});self.assertFalse(r['ok'])

if __name__=='__main__':unittest.main()
