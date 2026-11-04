import json,unittest
from copy import deepcopy
from ..common import ROOT
from ..composed_world import ComposedWorld
from ..paired_v02.test_interface import MODEL
from ..paired_v12 import test_restoration as fixtures
from ..paired_v12.orchestrator import ResearchRuntime as OldRuntime
from ..paired_v01.budget import StudyBudget
from .workspace import ResearchWorkspace
from .continuation import prepare
from .orchestrator import ResearchRun
from token_budget import reservation_bound

class AdmissionTests(unittest.TestCase):
    setUp=fixtures.RestorationTests.setUp
    tearDown=fixtures.RestorationTests.tearDown
    make=fixtures.RestorationTests.make

    def copied(self,mode):
        m=json.loads((ROOT/'experiments/insight_research/review/workflow_20261024b/continuation_v13'/(mode+'.json')).read_text());old=m['parent_identity'];settings=deepcopy(old['settings']);identity={**m['parent_budget_identity'],'study_id':'engineering_admission_'+mode};root=self.folder/('copy_'+mode)
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version']);prepare(root,m,old['question'],world,settings,identity)
        ws=ResearchWorkspace(root/'researcher',old['question'],world,settings,reopen=True);self.addCleanup(ws.close);return root,ws,StudyBudget(root/'common_budget.sqlite',identity)

    def check(self,mode):
        root,ws,b=self.copied(mode);run=ResearchRun(root,ws,MODEL,b);self.assertIsNotNone(ws.state());before=b.snapshot();original=deepcopy(run.runtime.cp['messages']);records=ws.db.execute('SELECT ref,body FROM records ORDER BY rowid').fetchall()
        # Real v12 stopped checkpoint: byte compaction alone remains unaffordable.
        old=OldRuntime(ws,MODEL,journal=run.journal);old.compact();self.assertGreater(reservation_bound(old.payload()),run.journal.snapshot()['remaining_admission_tokens'])
        run.runtime.cp['messages']=original;run.runtime.compact();payload=run.runtime.prepare_payload(run.runtime.payload())
        self.assertLessEqual(reservation_bound(payload),run.journal.snapshot()['remaining_admission_tokens']);self.assertEqual(b.snapshot(),before);self.assertEqual(ws.db.execute('SELECT ref,body FROM records ORDER BY rowid').fetchall(),records)
        ref=run.runtime.cp['journal_recovery']['archive_id'];self.assertEqual(json.loads((ws.private/'context_archives'/(ref+'.json')).read_text()),original)

    def test_a01_real_self_with_saved_state_meets_remaining_admission(self):self.check('self')
    def test_a02_real_owner_after_peer_feedback_meets_remaining_admission(self):self.check('independent')

if __name__=='__main__':unittest.main()
