import unittest
from ..common import digest
from ..critic_v01.shared import lifecycle
from ..paired_v11 import test_scoped as fixtures
from ..paired_v11.workspace import ResearchWorkspace as OldWorkspace
from ..composed_world import ComposedWorld
from .workspace import ResearchWorkspace

class RestorationTests(unittest.TestCase):
    setUp=fixtures.ScopedTests.setUp
    tearDown=fixtures.ScopedTests.tearDown
    call=fixtures.ScopedTests.call
    source=fixtures.ScopedTests.source
    assessed=fixtures.ScopedTests.assessed
    save=fixtures.ScopedTests.save
    budget=fixtures.ScopedTests.budget
    issue=fixtures.ScopedTests.issue
    seeded=fixtures.ScopedTests.seeded
    reply=fixtures.ScopedTests.reply
    closeout=fixtures.ScopedTests.closeout

    def make(self,mode):
        if self.ws:self.ws.close()
        from ..test_acceptance import settings
        from ..paired_v02.test_interface import MODEL
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL,workflow_policy={'max_lineage_reviews':4},execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16,'review_http_limit':18,'closeout_reserve_tokens':1300000})
        config['limits'].update(token_allowance=3000000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        cls=getattr(self,'workspace_class',ResearchWorkspace)
        self.ws=cls(self.folder/mode/'researcher','工程：跨入口恢复规则',ComposedWorld(),config);return self.ws

    def replace(self):
        h,r,a,q=self.seeded();self.call('respond_to_review',self.reply(q,r))
        args={k:a[k] for k in ['hypothesis_ref','result_refs','status','prediction_coverage','rationale','deviations','counterevidence_refs','limitations']};args.update(status='unresolved',supersedes_assessment_ref=a['ref'])
        new=self.call('record_assessment',args);self.assertIn('ref',new,new);return h,r,a,q,new

    def test_r01_prior_v11_legacy_restore_counterexample_is_reproduced(self):
        self.workspace_class=OldWorkspace
        # setUp has already made v12self; use a separate actual workspace.
        self.make('independent');h,r,a,q,new=self.replace()
        out=self.save(memory_reviews=[{'target_ref':a['ref'],'decision':'restore','reason':'工程反例：旧入口不查A替代链','evidence_refs':[r['ref']]}])
        self.assertIn('ref',out,out);self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'active');self.ws.premise(a['ref'])

    def test_r02_both_restore_paths_reject_superseded_original_even_after_label_drift(self):
        h,r,a,q,new=self.replace()
        with self.ws.db:self.ws._flag(a['ref'],'quarantine','工程模拟标签漂移',None)
        action={'target_ref':a['ref'],'decision':'restore','reason':'不得复活旧版','evidence_refs':[r['ref']]}
        self.assertFalse(self.save(memory_reviews=[action])['ok'])
        reply=self.reply(q,r,'revise');reply['object_reviews']=[action];self.assertFalse(self.call('respond_to_review',reply)['ok'])
        self.assertFalse(lifecycle(self.ws.db,a['ref'])['eligible_as_current_premise'])

    def test_r03_stage_deferral_preserves_superseded_history_and_rebuild(self):
        h,r,a=self.assessed();args={k:a[k] for k in ['hypothesis_ref','result_refs','status','prediction_coverage','rationale','deviations','counterevidence_refs','limitations']};args.update(status='unresolved',supersedes_assessment_ref=a['ref'])
        new=self.call('record_assessment',args);self.save();self.closeout();jobs=self.ws.jobs('pending')
        draft=self.call('finish_research',{'assessment_refs':[],'other_hypotheses':{h['ref']:'判断暂缓，原版本链保留'},'limitations':['工程'],'open_questions':['待核验'],'measurement_requests':[],'deferred_review_jobs':{j['ref']:'未付费未发表' for j in jobs}})
        self.assertIn('ref',draft,draft);self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'superseded');self.assertEqual(lifecycle(self.ws.db,new['ref'])['status'],'quarantine')
        self.ws._rebuild_reviews();self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'superseded')

    def test_r04_correct_current_quarantine_remains_restorable(self):
        h,r,a,q=self.seeded();self.call('respond_to_review',self.reply(q,r));self.save(memory_reviews=[{'target_ref':a['ref'],'decision':'quarantine','reason':'工程待核验','evidence_refs':[r['ref']]}])
        restored=self.save(memory_reviews=[{'target_ref':a['ref'],'decision':'restore','reason':'原件支持当前版本；不存在替代链','evidence_refs':[r['ref']]}])
        self.assertIn('ref',restored,restored);self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'active');self.ws.premise(a['ref'])

if __name__=='__main__':unittest.main()
