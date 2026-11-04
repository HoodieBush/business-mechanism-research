"""Generic provenance and information handoff checks, across different data types."""
import json
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from provenance import Frame, traced_column, source_entry
from workspace import ResearchWorkspace
from world import OfficeWorld

class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_lineage_');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def frame(self,data,definitions):
        path=self.root/('source_'+str(len(list(self.root.glob('*.csv'))))+'.csv');pd.DataFrame(data).to_csv(path,index=False)
        return Frame(pd.DataFrame(data),{n:traced_column(source_entry(path,'registered',n,d)) for n,d in definitions.items()})
    def test_filter_and_rename_preserve_original_identity_and_units(self):
        f=self.frame({'location':['north','south'],'temperature_c':[10,20]}, {'location':{'unit':'identifier'},'temperature_c':{'meaning':'ambient Celsius temperature','unit':'°C'}})
        result=f[f['location']=='south'][['location','temperature_c']].rename(columns={'temperature_c':'temperature_f'})
        p=self.root/'renamed.csv';result.to_csv(p,interpretations={'temperature_f':{'meaning':'Fahrenheit','unit':'°F'}})
        m=json.loads(Path(str(p)+'.lineage.json').read_text());c=m['columns']['temperature_f']
        self.assertEqual(c['sources'][0]['original_column'],'temperature_c');self.assertEqual(c['sources'][0]['definition']['unit'],'°C')
        self.assertEqual(m['producer_column_interpretations']['temperature_f']['unit'],'°F')
        self.assertEqual(m['row_operations'][0]['predicate']['literal'],'south');self.assertEqual(m['verification_status'],'draft_not_semantically_verified')
    def test_actual_transformation_is_distinct_from_relabelling(self):
        f=self.frame({'temperature_c':[10,20]},{'temperature_c':{'meaning':'Celsius','unit':'°C'}})
        f['temperature_f']=f['temperature_c']*1.8+32
        e=f.lineage['temperature_f']['expression'];self.assertEqual(e['operation'],'__add__');self.assertEqual(e['inputs'][0]['operation'],'__mul__')
        self.assertEqual(f.to_pandas().temperature_f.tolist(),[50,68]);self.assertEqual(f.lineage['temperature_f']['meaning_status'],'derived_interpretation_requires_review')
    def test_aggregation_preserves_source_and_actual_group_keys(self):
        f=self.frame({'customer':['a','a','b'],'amount':[2,3,4]},{'customer':{'unit':'identifier'},'amount':{'meaning':'order value','unit':'currency/order'}})
        r=f.groupby(['customer']).agg(total=('amount','sum'));self.assertEqual(r.to_pandas().total.tolist(),[5,4])
        self.assertEqual(r.lineage['total']['expression']['group_keys'],['customer']);self.assertEqual(r.lineage['total']['expression']['function'],'sum')
        self.assertEqual(r.row_operations[-1]['rows_after'],2)
    def test_join_multiplicity_and_untracked_assignment_are_explicit(self):
        a=self.frame({'id':[1,2],'value':[5,6]},{'id':{'unit':'identifier'},'value':{'unit':'units'}})
        b=self.frame({'id':[1,1,2],'label':['a','b','c']},{'id':{'unit':'identifier'},'label':{'unit':'category'}})
        r=a.merge(b,on='id');self.assertEqual(r.row_operations[-1]['output_rows'],3)
        r['untracked']=[1,2,3];self.assertEqual(r.lineage['untracked']['meaning_status'],'untracked_requires_independent_review')

class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_review_');cls.root=Path(cls.temp.name)
        cls.ws=ResearchWorkspace(cls.root/'case',OfficeWorld('relationship',7101))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def artifact(self,name):
        p=self.ws.workers['analyst'].directory/name;p.write_text('x\n1\n');return p
    def aspects(self):
        return [{'aspect':a,'status':'checked','rationale':'unit protocol fixture, not real scientific review'} for a in ('source_binding','transformation','units','grain','availability','interpretation')]
    def execution(self):
        r=self.ws.tool('verifier','run_python',{'code':"from research_data import read_table\nx=read_table('products');print(x.shape)",'purpose':'independent source access fixture','output_semantics':'shape only'})
        return r['execution_id']
    def review(self,p,decision='accepted'):
        artifact=self.ws.tool('verifier','read_artifact',{'path':str(p)})['artifact_id']
        return self.ws.tool('verifier','review_artifact',{'artifact_id':artifact,'execution_id':self.execution(),'decision':decision,'checks':self.aspects(),'summary':'unit-only protocol review'})
    def test_unreviewed_artifact_cannot_reach_mechanism_worker(self):
        p=self.artifact('draft.csv');self.ws.delegate=lambda role,task:{'role':role}
        with self.assertRaisesRegex(ValueError,'no current independent review'):self.ws.tool('manager','assign_task',{'role':'mechanist','question':'draft','inputs':[str(p)]})
        with self.assertRaises(ValueError):self.ws.tool('mechanist','read_artifact',{'path':str(p)})
        with self.assertRaises(ValueError):self.ws.tool('analyst','review_artifact',{'path':str(p)})
    def test_review_requires_independent_original_input_access(self):
        p=self.artifact('no_input.csv');r=self.ws.tool('verifier','run_python',{'code':'print("no input")','purpose':'no source','output_semantics':'constant'})
        artifact=self.ws.tool('verifier','read_artifact',{'path':str(p)})['artifact_id']
        with self.assertRaisesRegex(ValueError,'independently load'):self.ws.tool('verifier','review_artifact',{'artifact_id':artifact,'execution_id':r['execution_id'],'decision':'accepted','checks':self.aspects(),'summary':'invalid fixture'})
    def test_reference_rejects_commentary_and_stale_versions(self):
        p=self.artifact('reference.csv');identifier=self.ws.reference(p)
        with self.assertRaisesRegex(ValueError,'copied exactly'):self.ws.resolve_reference(identifier+' (looks valid)','artifact')
        p.write_text('x\n3\n')
        with self.assertRaisesRegex(ValueError,'version changed'):self.ws.resolve_reference(identifier,'artifact')
        fresh=self.ws.reference(p);self.assertNotEqual(fresh,identifier)
        self.ws.annotate(p,{'interpretation':'new meaning, same bytes'})
        with self.assertRaisesRegex(ValueError,'version changed'):self.ws.resolve_reference(fresh,'artifact')
    def test_reviewed_copy_retains_status_while_changed_version_needs_review(self):
        p=self.artifact('version.csv');self.review(p)
        r=self.ws.tool('analyst','submit_result',{'summary':'unit','evidence_files':[str(p)],'findings':[],'next_step':'test'})
        copy=Path(r['evidence_files'][0]);self.ws.require_reviewed([str(copy)])
        p.write_text('x\n2\n');self.assertIsNone(self.ws.current_review(p));self.assertIsNotNone(self.ws.current_review(copy))
    def test_later_rejection_revokes_handoff_without_rewriting_history(self):
        p=self.artifact('revoke.csv');one=self.review(p);self.review(p,'rejected')
        self.assertIsNone(self.ws.current_review(p));self.assertEqual(one['decision'],'accepted')
    def test_runtime_column_provenance_survives_immutable_handoff(self):
        r=self.ws.tool('analyst','run_python',{'code':"from research_data import read_table\nx=read_table('products')[['sku','unit_cost']].rename(columns={'unit_cost':'selling_price'});x.to_csv('renamed.csv',interpretations={'selling_price':{'meaning':'selling price','unit':'currency'}})",'purpose':'misleading rename fixture','output_semantics':'unverified renamed column'})
        p=self.ws.workers['analyst'].directory/'renamed.csv';self.assertTrue(Path(str(p)+'.lineage.json').exists())
        q=self.ws.tool('analyst','submit_result',{'summary':'draft','evidence_files':[str(p)],'findings':[],'next_step':'review'})
        m=json.loads(Path(q['evidence_files'][0]+'.lineage.json').read_text());self.assertEqual(m['columns']['selling_price']['sources'][0]['original_column'],'unit_cost')
        self.assertEqual(len(r['source_reads']),2)
    def test_review_access_must_cover_actual_column_origins(self):
        r=self.ws.tool('analyst','run_python',{'code':"from research_data import read_table\nx=read_table('sites')[['site']];x.to_csv('sites_review.csv',interpretations={'site':{'meaning':'site identifier','unit':'identifier'}})",'purpose':'source coverage fixture','output_semantics':'site identifier'})
        p=self.ws.workers['analyst'].directory/'sites_review.csv'
        artifact=self.ws.reference(p)
        with self.assertRaisesRegex(ValueError,'every tracked original input'):self.ws.tool('verifier','review_artifact',{'artifact_id':artifact,'execution_id':self.execution(),'decision':'accepted','checks':self.aspects(),'summary':'products access cannot verify sites fields'})

if __name__=='__main__':unittest.main()
