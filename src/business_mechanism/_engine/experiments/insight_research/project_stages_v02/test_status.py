import json
from unittest.mock import patch
from ..common import sha,digest
from ..project_stages_v01 import test_stages as fixture
from .controller import Project
from .workspace import ResearchWorkspace
from .review import Reviewer
from .orchestrator import ResearchRun
class SourceStatusTests(fixture.StageTests):
    def setUp(self):
        self.patches=[patch.object(fixture,k,v) for k,v in [('Project',Project),('ResearchWorkspace',ResearchWorkspace),('Reviewer',Reviewer),('ResearchRun',ResearchRun)]]
        for p in self.patches:p.start()
        super().setUp()
    def tearDown(self):
        super().tearDown()
        for p in reversed(self.patches):p.stop()
    def test_r01_strong_old_label_and_active_status_do_not_hide_pending_review(self):
        old=self.f.ws.record(self.a['ref']);self.close1();ws,run=self.second()
        try:
            out=ws.call('read_memory',{'ref':'archive:s1:'+self.a['ref']},'old_supported_but_unreviewed')
            self.assertEqual(json.loads(out['text'])['original'],old);status=out['separate_source_review_status']
            self.assertFalse(status['stored_clearance_version_matches_original']);self.assertEqual(status['source_review_jobs'][0]['status'],'pending')
            self.assertFalse(status['scientific_certification']);source,_=ws.file(out['source_review_status_file']['ref']);self.assertEqual(json.loads(source.read_text()),status)
            self.assertNotIn('source_review_jobs',json.loads(out['text'])['original']);self.assertNotIn('source_review_jobs',json.loads(open(out['compute_path']).read())['original'])
        finally:ws.close()
    def test_r02_actual_completed_source_review_is_reported_without_current_K_promotion(self):
        self.fx.clear(self.a,self.r['action_ref']);self.close1();ws,run=self.second()
        try:
            out=ws.call('read_memory',{'ref':'archive:s1:'+self.a['ref']},'old_reviewed');status=out['separate_source_review_status']
            self.assertTrue(status['stored_clearance_version_matches_original']);self.assertTrue(all(j['status']=='completed' for j in status['source_review_jobs']))
            self.assertFalse(ws.records('knowledge'));self.assertFalse(ws.records('assessment'))
            result=ws.call('search_memory',{'archive_stage':'s1','kind':'assessment','query':''},'source_status_in_search');self.assertTrue(result['hits'][0]['source_review_status']['stored_clearance_version_matches_original'])
        finally:ws.close()
    def test_r03_source_status_receipt_has_same_bytes_for_owner_and_peer(self):
        from ..paired_v01.evidence import export_snapshot
        from ..paired_v01.test_pairing import MODEL
        self.close1();ws,run=self.second('independent')
        try:
            self.f.ws,old=ws,self.f.ws
            try:h,r,a=self.fx.assessed()
            finally:self.f.ws=old
            inputs=self.f.folder/'status_peer_inputs';export_snapshot(ws,inputs,a['ref']);peer=Reviewer(self.f.folder/'status_peer',inputs,{'research_profile':'paired_critic_v1','model_config':MODEL,'limits':ws.settings['limits'],'project_archives':self.project.archives()});self.peers.append(peer)
            args={'ref':'archive:s1:'+self.a['ref']};one=ws.call('read_memory',args,'status_owner');two=peer.call('read_memory',args,'status_peer')
            self.assertEqual(one['separate_source_review_status'],two['separate_source_review_status']);self.assertEqual(one['source_review_status_file']['sha256'],two['source_review_status_file']['sha256'])
        finally:ws.close()
