"""Source transport, exposure and native-role contracts; no model calls."""
import json
import tempfile
import unittest
import urllib.error
import sqlite3
from pathlib import Path
from unittest.mock import patch,Mock

from langgraph_migration.sources import SourceService,SourceHTTP,public_url,enable_research,digest,SOURCE_CONTRACTS
from langgraph_migration.runtime import FrameworkRoles,role_task_context
from langgraph_migration.science import ScientificWorkspace
from world import OfficeWorld
from langgraph.checkpoint.sqlite import SqliteSaver


PAPER=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
<o:totalResults>2</o:totalResults><entry><id>http://arxiv.org/abs/9999.00001v2</id><title>Fixture on inference</title><author><name>Fixture Author</name></author><summary>Metadata is not a full paper.</summary><published>2020-01-01</published></entry></feed>'''
BODY='<html><script>hidden()</script><article><h1>Fixture</h1><p>ß prefix 研究。 Target assumption.</p><p>Independent units are required.</p><math alttext="V = 1/G">rendered</math><a href="https://github.com/fixture/project">code</a></article><footer>not article</footer></html>'.encode()
COMMIT='a'*40


class FakeHTTP:
    def __init__(self):self.urls=[]
    def get(self,url):
        self.urls.append(url)
        if '/api/query?' in url:data,kind=PAPER,'application/atom+xml'
        elif 'api.crossref.org/' in url:
            data=json.dumps({'message':{'total-results':1,'items':[{'DOI':'10.1/fixture','URL':'https://doi.org/10.1/fixture','title':['Fixture'],'author':[{'family':'Author'}]}]}}).encode();kind='application/json'
        elif url=='https://github.com/fixture/project':data,kind=json.dumps({'currentOid':COMMIT}).encode(),'text/html'
        elif 'raw.githubusercontent.com/' in url:data,kind=b'line one\nline two\nline three\n','text/plain'
        else:data,kind=BODY,'text/html'
        return data,{'url':url,'final_url':url,'http_status':200,'content_type':kind,'retrieved_at':1.,'sha256':digest(data),'cache_hit':False}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_sources_');self.root=Path(self.temp.name);self.http=FakeHTTP();self.service=SourceService(self.root/'sources',self.http)
    def tearDown(self):self.temp.cleanup()

    def test_discovery_and_actual_reading_have_distinct_audit_records(self):
        result=self.service.search('analyst','all:fixture',provider='arxiv')
        self.assertEqual(result['next_start'],1);self.assertEqual(result['total_reported_matches'],2)
        self.assertNotIn('text_file',result['results'][0])
        sid=result['results'][0]['source_id']
        exposure=self.service.read('mechanist',sid,find='target',length=50)
        text=Path(exposure['text_file']).read_text();span=exposure['span']
        self.assertEqual(exposure['text'],text[span['start']:span['end']])
        self.assertEqual(exposure['match_at'],text.index('Target'))  # Unicode offsets survive ß.
        self.assertNotIn('hidden()',text);self.assertNotIn('not article',text)
        self.assertIn('V = 1/G',text)
        events=[json.loads(l) for l in (self.service.directory/'access.jsonl').read_text().splitlines()]
        self.assertEqual([e['action'] for e in events],['search','read'])
        self.assertEqual(events[1]['span'],span)
        restored=SourceService(self.service.directory,self.http)
        self.assertEqual(restored.read('verifier','catalog')['sources'][0]['source_id'],sid)
        self.assertEqual(restored.read('verifier',sid,find='absent')['status'],'text_not_found')
        self.assertEqual(restored.read('verifier',sid,view='links')['links'],['https://github.com/fixture/project'])
        self.assertEqual(restored.read('verifier',sid,offset=len(text)+10)['status'],'end_of_document')

    def test_crossref_without_body_links_is_not_fulltext(self):
        result=self.service.search('verifier','fixture',provider='crossref')
        self.assertEqual(result['status'],'metadata_retrieved')
        self.assertEqual(result['results'][0]['body_urls'],[])
        events=[json.loads(l) for l in (self.service.directory/'access.jsonl').read_text().splitlines()]
        self.assertEqual([e['action'] for e in events],['search'])

    def test_provider_failure_is_not_an_empty_search_result(self):
        with patch.object(self.http,'get',side_effect=urllib.error.HTTPError('https://example.org',429,'rate limit',{},None)):
            result=self.service.search('analyst','fixture',provider='arxiv')
        self.assertEqual(result['status'],'provider_unavailable');self.assertIsNone(result['results'])
        self.assertEqual(result['alternate_provider'],'crossref')

    def test_code_is_commit_pinned_and_exposed_lines_match_archive(self):
        result=self.service.code('engineer','fixture/project',line_start=2,line_count=1)
        self.assertEqual(result['commit'],COMMIT);self.assertEqual(result['text'],'line two\n')
        self.assertIn('/'+COMMIT+'/',result['url'])
        self.assertTrue(Path(result['text_file']).exists())
        with self.assertRaises(ValueError):self.service.code('engineer','fixture/project',path='../private')
        calls=len(self.http.urls)
        self.service.code('engineer','fixture/project',revision=COMMIT,line_start=1,line_count=1)
        self.assertEqual(len(self.http.urls),calls)

    def test_public_url_rejects_local_and_credential_targets_before_http(self):
        for url in ('file:///etc/passwd','https://user:secret@example.org/','http://example.org/'):
            with self.assertRaises(ValueError):public_url(url)
        with patch('langgraph_migration.sources.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaisesRegex(ValueError,'public Internet'):public_url('https://example.org/')

    def test_transient_transport_retries_same_get_then_uses_verified_cache(self):
        url='https://api.crossref.org/fixture';response=Mock()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'{}';response.url=url;response.status=200;response.headers={'Content-Type':'application/json'}
        opener=Mock();opener.open.side_effect=[urllib.error.HTTPError(url,503,'temporary',{},None),response]
        waits=[];http=SourceHTTP(self.root/'http',wait=waits.append)
        with patch('langgraph_migration.sources.public_url',side_effect=lambda u:u),patch('langgraph_migration.sources.urllib.request.build_opener',return_value=opener):
            data,record=http.get(url);again,cached=http.get(url)
        self.assertEqual(data,again);self.assertTrue(cached['cache_hit']);self.assertEqual(opener.open.call_count,2)
        self.assertEqual(opener.open.call_args_list[0].args[0].full_url,opener.open.call_args_list[1].args[0].full_url)
        self.assertEqual(len(waits),1);self.assertEqual(record['sha256'],digest(data))
        (http.cache/(digest(url.encode())+'.bin')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):http.get(url)

    def test_every_scientific_role_has_matching_manual_backend_and_pinned_permissions(self):
        ws=ScientificWorkspace(self.root/'team',OfficeWorld('relationship',1171))
        enable_research(ws,http=self.http);FrameworkRoles(ws,None,None)
        manual=json.loads((ws.public/'tool_manual.json').read_text())
        for role in ('manager','analyst','mechanist','verifier','engineer'):
            self.assertTrue(set(SOURCE_CONTRACTS)<=set(manual['roles'][role]))
            result=ws.tool(role,'search_literature',{'query':'all:fixture'})
            self.assertEqual(result['status'],'metadata_retrieved')
        # Pinned task permissions must follow the same extended registry.
        flow=ws.state['workflow'];flow['phase']='needs_analysis'
        snapshot=ws.capture_task('analyst',{'id':'T_source','inputs':[]},ws.task_binding({'inputs':[]}))
        self.assertTrue(set(SOURCE_CONTRACTS)<=set(snapshot['allowed_tools']))
        token=role_task_context.set(snapshot)
        try:
            result=ws.tool('analyst','read_source',{'source':next(iter(ws.research_service.catalog))})
            self.assertEqual(result['status'],'text_exposed')
            with self.assertRaises(ValueError):ws.tool('engineer','read_source',{'source':result['source_id']})
        finally:role_task_context.reset(token)

    def test_native_agent_can_search_read_and_deliver_through_same_audited_tools(self):
        from run_method_adoption import MethodWorkspace,create_inputs
        from test_langgraph_migration import ScriptedModel,submission
        root=self.root/'native';create_inputs(root,'M02','local_only',self.root,self.root)
        ws=enable_research(MethodWorkspace(root),http=self.http)
        source_id='src_'+digest(b'https://doi.org/10.1/fixture')[:16]
        model=ScriptedModel(sequence=[('search_literature',{'query':'fixture'}),
             ('read_source',{'source':source_id,'find':'Target'}),submission()])
        with sqlite3.connect(self.root/'native.sqlite',check_same_thread=False) as conn:
            result=FrameworkRoles(ws,SqliteSaver(conn),lambda role:model).run('verifier',{'id':'source_fixture','question':'native source protocol'})
        self.assertEqual(result['role'],'verifier')
        logs=[json.loads(l) for l in (ws.root/'framework_tools.jsonl').read_text().splitlines()]
        self.assertEqual([l['tool'] for l in logs],['search_literature','read_source','submit_result'])
        self.assertTrue(all(l['feedback']['ok'] for l in logs))
        self.assertIn(logs[1]['feedback']['result']['text_file'],ws.registered_sources)


if __name__=='__main__':unittest.main()
