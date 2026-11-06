"""A typo in a paid critic submission must not crash the entire study."""
import json
import unittest
import test_agent_repairs as fixtures


class PeerReferenceFeedback(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AgentRepairs(); self.fixture.setUp()
        self.peer, self.job, self.target = self.fixture.peer()

    def tearDown(self):
        self.peer.close(); self.fixture.tearDown()

    def test_invalid_file_submission_preserves_rejection_and_replays(self):
        before = self.fixture.backend.budget.snapshot()
        args = fixtures.example('review_clean')
        args.update(source_refs=['file:unreceived_typo'], checks_performed=[], coverage_checks=[],
                    target_conclusion='insufficient_evidence')
        first = self.peer.call('record_review', args, 'invalid-file')
        self.assertFalse(first['ok'])
        self.assertEqual(first['error_code'], 'invalid_object_reference')
        self.assertFalse(first['scientific_status_changed'])
        saved = list((self.peer.science/'tool_errors').glob('*.json'))
        self.assertEqual(json.loads(saved[0].read_text())['arguments'], args)
        self.assertTrue(first['received_reference_examples'])
        for ref in first['received_reference_examples']:
            self.peer.view.record(ref)
        self.assertEqual(first, self.peer.call('record_review', args, 'invalid-file'))
        self.assertFalse(self.peer.records('review'))
        self.assertEqual(before, self.fixture.backend.budget.snapshot())

    def test_invalid_read_uses_received_catalog_and_legal_read_can_follow(self):
        bad = self.peer.call('read_memory', {'ref':'Aunreceived', 'offset':0,'limit':1000}, 'bad-read')
        self.assertFalse(bad['ok'])
        self.assertEqual(bad['error_code'], 'invalid_object_reference')
        good = self.peer.call('read_memory', {'ref':self.target['ref'],'offset':0,'limit':1000}, 'good-read')
        self.assertNotEqual(good.get('ok'), False)
        self.assertIn(self.target['ref'], json.dumps(good))


if __name__ == '__main__': unittest.main()
