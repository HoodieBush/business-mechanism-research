"""Frozen cross-task pilot of generic information provenance and handoff review.
Fixtures are deliberately constructed inputs, not autonomous business discovery.
Expected decisions stay in the private specification; Actors see source contracts.
"""
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
from execution import PythonWorkspace
from provenance import Frame,traced_column,source_entry
from workspace import ResearchWorkspace,sha,write_json
from team import ResearchTeam,SCHEMAS,DESCRIPTIONS,ROLE_PROMPTS,usage_summary

ROOT=Path(__file__).resolve().parents[2]

class InformationWorkspace(ResearchWorkspace):
    def __init__(self,root,case):
        self.root=Path(root).resolve();self.public=self.root/'public';self.shared=self.root/'artifacts'
        self.public.mkdir(parents=True);self.shared.mkdir();self.path_aliases={};self.require_artifact_review=True
        self.state={name:[] for name in ('tasks','results','hypotheses','experiments','algorithms','events','artifact_reviews')}
        self.query_count=0;self.operation=None;self.delegate=None
        self.workers={role:PythonWorkspace(self.shared/role,self.public,self.shared) for role in ('manager','analyst','verifier','mechanist','engineer','evaluator')}
        self.tool_menus={'verifier':['read_context','read_artifact','read_history','query_data','run_python','review_artifact','submit_result'],
                         'mechanist':['read_context','read_artifact','read_history','submit_result']}
        self.role_prompts={'verifier':ROLE_PROMPTS['verifier']+' 本次仅复核信息交接，不做因果试验或算法开发。审查全部导出列及产出者解释，不能仅因数值可计算或列名合理就接受。先独立加载原输入，写Python对照，再review_artifact，最后submit_result。',
                           'mechanist':'你是下游研究者。本次只接收已复核资料，准确说明数据含义、单位和适用边界，不开展因果假说或业务实验。遇到输入定义与任务说明冲突，以可追溯源定义为准并报告。读取真实文件后submit_result。'}
        if case['domain']=='sensor':
            self.frame=pd.DataFrame({'station':['north','south','south'],'temperature_c':[10.,20.,25.]})
            definitions={'station':{'meaning':'sensor station identifier','unit':'category'},'temperature_c':{'meaning':'ambient temperature measured in Celsius','unit':'degrees Celsius'}}
            grain='one observation per station measurement; station is not unique'
        else:
            self.frame=pd.DataFrame({'order_id':['o1','o2','o3'],'customer_id':['c1','c1','c2'],'order_value':[20.,30.,40.]})
            definitions={'order_id':{'meaning':'unique order identifier','unit':'identifier'},'customer_id':{'meaning':'customer owning this order','unit':'identifier'},'order_value':{'meaning':'monetary value of this order','unit':'currency per order'}}
            grain='one row per order, several orders may belong to one customer'
        db=self.public/'business.sqlite'
        with sqlite3.connect(db) as con:self.frame.to_sql('observations',con,index=False)
        self.contract={'version':'generic-information-pilot-v1','database_file':str(db),'tables':{'observations':{'columns':definitions,'row_grain':grain}}}
        write_json(self.public/'data_dictionary.json',self.contract)
        self.registered_data_sources={str(db)};self.registered_sources=self.registered_data_sources|{str(self.public/'data_dictionary.json')}
        self.data_source={'database_sha256':sha(db),'dictionary_sha256':sha(self.public/'data_dictionary.json'),'dictionary_version':self.contract['version']}
        shutil.copyfile(Path(__file__).with_name('provenance.py'),self.public/'research_data.py')
        write_json(self.public/'tool_manual.json',{'role_menus':self.tool_menus,'tools':{n:{'description':DESCRIPTIONS[n],'parameters':SCHEMAS[n]} for n in set(sum(self.tool_menus.values(),[]))}})
        source=Frame(self.frame,{c:traced_column(source_entry(db,'observations',c,definitions[c])) for c in self.frame.columns},[{'operation':'read_registered_source','table':'observations','input_row_grain':grain}])
        if case['domain']=='sensor':
            export=source[source['station']=='south'][['station','temperature_c']]
            if case['construction']=='convert':export['temperature_f']=export['temperature_c']*1.8+32;export=export[['station','temperature_f']]
            else:export=export.rename(columns={'temperature_c':'temperature_f'})
            meanings={'station':{'meaning':'station','unit':'category'},'temperature_f':{'meaning':'ambient temperature in Fahrenheit','unit':'degrees Fahrenheit'}}
        else:
            column,func=('order_id','count') if case['construction']=='count' else ('order_value','sum')
            export=source.groupby(['customer_id']).agg(order_count=(column,func))
            meanings={'customer_id':{'meaning':'customer identifier','unit':'identifier'},'order_count':{'meaning':'number of orders of this customer','unit':'orders'}}
        self.draft=self.workers['analyst'].directory/'export.csv'
        export.to_csv(self.draft,interpretations=meanings)
        self.annotate(self.draft,{'producer':'constructed test fixture','output_semantics':meanings,'semantics_status':'draft; not verified',
                                 'fixture_note':'This is a deliberately constructed artifact used to test the generic protocol; not a real autonomous producer discovery.'})
        self.persist()

    def initial_context(self):
        return {'purpose':'Review whether exported information means what its producer claims. Source definitions and operation lineage are authoritative inputs, not the producer conclusion.',
                'public_directory':str(self.public),'shared_artifacts':str(self.shared),'data_dictionary':self.contract,
                'draft_artifact':str(self.draft),'source_contract':str(self.public/'data_dictionary.json'),
                'python_tool':'from research_data import read_table; raw=read_table("observations").to_pandas(); ordinary pandas is available. Independent raw-source accesses are recorded.',
                'handoff_protocol':'draft must be independently reviewed before the downstream role can receive it; acceptance binds data, semantic contract, lineage and source version. Reviewer decisions are not universal semantic proof.'}


def run(spec_file):
    spec=json.loads(Path(spec_file).read_text());output=ROOT/'experiments/business_team/results'/spec['phase']
    if output.exists():raise ValueError('phase already exists; never overwrite')
    output.mkdir(parents=True)
    preflight=subprocess.run([sys.executable,'-m','unittest','-v','test_information_protocol.py','test_business_team.py'],cwd=Path(__file__).parent,capture_output=True,text=True)
    (output/'preflight-tests.log').write_text(preflight.stdout+preflight.stderr)
    if preflight.returncode:raise RuntimeError('preflight failed; no API')
    files=list(Path(__file__).parent.glob('*.py'))+[Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'environment.yml',ROOT/'configs/business-team-osx-arm64.lock.txt',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py']
    hashes={}
    for p in files:
        relative=p.relative_to(ROOT);dest=output/'snapshot'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);hashes[str(relative)]=sha(p)
    config=json.loads((ROOT/'configs/base_model.json').read_text());config['request_timeout_seconds']=180
    manifest={'status':'running','created_at':datetime.now(timezone.utc).isoformat(),'specification':spec,'source_sha256':hashes,'cases':[],'scope':'constructed cross-task information review pilot, not a business mechanism or overall robustness study'}
    workspaces=[]
    for c in spec['cases']:
        ws=InformationWorkspace(output/c['id'],c);workspaces.append((c,ws))
        manifest.setdefault('fixture_sha256',{})[c['id']]={'database':sha(ws.public/'business.sqlite'),'contract':sha(ws.public/'data_dictionary.json'),'artifact':sha(ws.draft),'lineage':sha(str(ws.draft)+'.lineage.json')}
    write_json(output/'manifest.json',manifest)  # All source/fixtures frozen before first call.
    global_usage=[]
    for c,ws in workspaces:
        print('START',c['id'],flush=True)
        team=ResearchTeam(ws,config,{'max_output_tokens':7000,'round_reported_token_budget':spec['round_reported_token_budget']},global_usage)
        record={'id':c['id'],'status':'started'}
        try:
            result=team.run_role('verifier',{'id':'T_review','question':'独立复核export.csv的全部列是否确实具有产出者声明的含义。读取原始定义与运行来源图，自己从原始输入写Python复算，核对实体归属/变换/单位/粒度/可用性/解释，用review_artifact接受、退回或未决，再交付真实依据。不要把列名改动、数值相等、来源存在或重复上游方法当成含义正确。','inputs':[str(ws.draft)]})
            ws.state['results'].append(result);ws.persist();record['verifier_result']=result
            reviews=[r for r in ws.state['artifact_reviews'] if r['artifact_sha256']==sha(ws.draft)]
            decision=reviews[-1]['decision'] if reviews else None;record['actual_decision']=decision;record['matches_private_expected_decision']=decision==c['expected_decision']
            task={'role':'mechanist','question':'读取已复核资料，说明它表示什么、单位和边界；本次不提出因果假说。','inputs':[str(ws.draft)]}
            try:
                consumer=ws.tool('manager','assign_task',task,operation_id='protocol_consumer_dispatch')
                record.update(consumer_received=True,consumer_result=consumer)
            except ValueError as e:record.update(consumer_received=False,handoff_block_reason=str(e))
            record['status']='completed'
        except KeyboardInterrupt:
            record.update(status='interrupted');manifest['status']='interrupted'
        except Exception as e:record.update(status='failed',error_type=type(e).__name__,error=str(e)[:2000])
        record['usage']=team.usage();record['reviews']=ws.state['artifact_reviews'];write_json(ws.root/'case_result.json',record)
        manifest['cases'].append(record);manifest['usage']=usage_summary(global_usage);write_json(output/'manifest.json',manifest)
        print('END',c['id'],record['status'],record.get('actual_decision'),flush=True)
        if record['status']=='interrupted':return
    manifest.update(status='completed',completed_at=datetime.now(timezone.utc).isoformat(),frozen_source_hashes_unchanged=all(sha(ROOT/p)==h for p,h in hashes.items()))
    write_json(output/'manifest.json',manifest)
    print(json.dumps({'status':manifest['status'],'usage':manifest['usage'],'decisions':[(c['id'],c.get('actual_decision'),c.get('consumer_received')) for c in manifest['cases']]},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',required=True);run(p.parse_args().spec)
