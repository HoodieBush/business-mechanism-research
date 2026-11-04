"""Ensure acceptance reports cannot promote skips, missing checks or weak freezes."""
from types import SimpleNamespace
import unittest
from process_acceptance import classify,offline_transport_guard


class StrictAcceptanceGateTests(unittest.TestCase):
    def result(self,**changes):
        values=dict(errors=[],failures=[],skipped=[],testsRun=2,expectedFailures=[],unexpectedSuccesses=[])
        return SimpleNamespace(**(values|changes))
    def test_skipped_or_missing_checks_cannot_pass(self):
        self.assertEqual(classify(self.result(skipped=[('check','permission')]),2),'incomplete_skipped_checks')
        self.assertEqual(classify(self.result(testsRun=1),2),'incomplete_test_coverage')
    def test_expected_failures_are_not_evidence_of_success(self):
        self.assertEqual(classify(self.result(expectedFailures=[('check','failure')]),2),'incomplete_expected_failure')
    def test_actual_failures_and_errors_take_precedence(self):
        for key in ('errors','failures'):self.assertEqual(classify(self.result(**{key:[('check','failure')]}),2),'failed')
    def test_all_required_checks_must_execute_and_succeed(self):
        self.assertEqual(classify(self.result(),2),'passed')
    def test_explicit_provider_migration_is_not_a_transient_retry(self):
        from transport import retryable
        moved={'error_type':'http','http_status':503,'response_body':'{"error":{"code":"entry_changed","type":"new_api_error","message":"endpoint moved"}}'}
        self.assertFalse(retryable(moved))
        self.assertTrue(retryable({'error_type':'http','http_status':503}))
        self.assertTrue(retryable({'error_type':'transport'}))
        self.assertTrue(retryable({'error_type':'transport','response':None}))
    def test_guard_blocks_real_credentials_dns_and_connections(self):
        import socket
        with offline_transport_guard():
            import model_protocol
            with self.assertRaisesRegex(AssertionError,'live credentials'):model_protocol.load_api_key({})
            with self.assertRaisesRegex(AssertionError,'network DNS'):socket.getaddrinfo('fixture.invalid',443)
            with socket.socket() as client:
                with self.assertRaisesRegex(AssertionError,'network connection'):client.connect(('127.0.0.1',9))


if __name__=='__main__':unittest.main()
