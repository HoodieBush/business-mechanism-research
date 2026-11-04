"""PDF/native source contract and parser fault boundaries; zero LLM calls."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.pdf_text import extract_pdf, PDFTextError, sha
from langgraph_migration.sources import SourceService, enable_research
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles
from world import OfficeWorld

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / 'experiments/business_team/reference_reviews/inventory_censoring_20261015/huh_levi_rusmevichientong_orlin_2011_author.pdf'
URL = 'https://faculty.marshall.usc.edu/Paat-Rusmevichientong/psfiles/km-myopic.pdf'


class CapturedHTTP:
    def __init__(self):
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if 'api.crossref.org/' in url:
            data = json.dumps({'message': {'total-results': 1, 'items': [
                {'DOI': '10.1287/opre.1100.0906', 'URL': 'https://doi.org/10.1287/opre.1100.0906',
                 'title': ['Captured-method metadata fixture'], 'link': [{'URL': URL, 'content-type': 'application/pdf'}]}]}}).encode()
            kind = 'application/json'
        else:
            data, kind = PDF.read_bytes(), 'application/pdf'
        return data, {'url': url, 'final_url': url, 'content_type': kind, 'sha256': sha(data),
                      'retrieved_at': 0., 'cache_hit': True, 'mode': 'captured_bytes_no_network'}


class PDFSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_pdf_sources_')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_crossref_retains_actual_pdf_location_without_claiming_body_read(self):
        service = SourceService(self.root / 'sources', CapturedHTTP())
        result = service.search('analyst', 'censored demand')
        record = result['results'][0]
        self.assertEqual(record['body_urls'], [URL])
        self.assertNotIn('text_file', record)
        exposed = service.read('analyst', record['source_id'], find='Kaplan', length=150)
        self.assertEqual(exposed['status'], 'text_exposed')
        self.assertEqual(exposed['pdf_page_count'], 47)

    def test_all_five_role_menus_expose_actual_pdf_and_register_its_metadata(self):
        ws = enable_research(ScientificWorkspace(self.root / 'team', OfficeWorld('relationship', 17061)), http=CapturedHTTP())
        FrameworkRoles(ws, None, None)
        manual = json.loads((ws.public / 'tool_manual.json').read_text())
        for role in ('manager', 'analyst', 'mechanist', 'verifier', 'engineer'):
            self.assertIn('read_source', manual['roles'][role])
            result = ws.tool(role, 'read_source', {'source': URL, 'length': 150})
            self.assertEqual(result['status'], 'text_exposed')
            self.assertEqual(result['raw_sha256'], sha(PDF.read_bytes()))
            self.assertIn(result['pdf_extraction_file'], ws.registered_sources)
            details = ws.tool(role, 'read_artifact', {'path': result['pdf_extraction_file']})
            self.assertIn('pypdf', str(details))

    def test_native_scripted_role_reads_pdf_through_real_audited_tool(self):
        from run_method_adoption import MethodWorkspace, create_inputs
        from test_langgraph_migration import ScriptedModel, submission
        target = self.root / 'native'
        create_inputs(target, 'M02', 'local_only', self.root, self.root)
        ws = enable_research(MethodWorkspace(target), http=CapturedHTTP())
        model = ScriptedModel(sequence=[('read_source', {'source': URL, 'find': 'Kaplan', 'length': 300}), submission()])
        with sqlite3.connect(self.root / 'native.sqlite', check_same_thread=False) as connection:
            FrameworkRoles(ws, SqliteSaver(connection), lambda _: model).run('verifier', {'id': 'pdf_native', 'question': 'engineering source fixture'})
        logs = [json.loads(line) for line in (target / 'framework_tools.jsonl').read_text().splitlines()]
        result = logs[0]['feedback']['result']
        self.assertEqual(result['pdf_page_count'], 47)
        self.assertEqual(len(result['text']), 300)
        self.assertIn(result['pdf_extraction_file'], ws.registered_sources)
        self.assertTrue(all(x['feedback']['ok'] for x in logs))

    def test_real_timeout_translates_and_child_is_reaped(self):
        original = subprocess.run
        pid_file = self.root / 'child.pid'

        def slow_worker(*args, **kwargs):
            return original([sys.executable, '-c',
                             'import os,sys,time;open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(4)', str(pid_file)],
                            capture_output=True, timeout=.3)
        with patch('langgraph_migration.pdf_text.subprocess.run', side_effect=slow_worker):
            with self.assertRaisesRegex(PDFTextError, 'technical timeout'):
                extract_pdf(b'unused in timeout fixture')
        self.assertTrue(pid_file.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

    def test_malformed_worker_input_and_output_are_explicit_failures(self):
        with self.assertRaisesRegex(PDFTextError, 'PDF worker failed'):
            extract_pdf(b'%PDF-not-a-valid-document')
        for output in [b'not JSON', b'[]', b'{"text":"bad","metadata":{}}']:
            with self.subTest(output=output), patch('langgraph_migration.pdf_text.subprocess.run', return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=b'')):
                with self.assertRaisesRegex(PDFTextError, 'invalid'):
                    extract_pdf(b'data')

    def test_page_map_and_original_are_bound_to_cached_text(self):
        http = CapturedHTTP()
        service = SourceService(self.root / 'cache', http)
        first = service.read('mechanist', URL, length=300)
        second = service.read('mechanist', URL, offset=175, length=50)
        self.assertEqual(http.calls, 1)
        text = Path(second['text_file']).read_text()
        self.assertEqual(second['text'], text[175:225])
        metadata = json.loads(Path(first['pdf_extraction_file']).read_text())
        self.assertEqual(metadata['parser_execution']['mode'], 'disposable_subprocess')
        for page in metadata['pages']:
            self.assertEqual(sha(text[page['text_start']:page['end']].encode()), page['text_sha256'])
        Path(first['pdf_extraction_file']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'page map changed'):
            service.read('mechanist', URL)


if __name__ == '__main__':
    unittest.main()
