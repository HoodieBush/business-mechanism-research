"""Developer-only task preparation; expected answers never enter actor roots."""
import argparse
import json
from pathlib import Path
import sqlite3

from ..common import ROOT, write_json
from ..composed_world import ComposedWorld
from ..test_acceptance import settings, state
from .workspace import ResearchWorkspace
from .initialization import export_initial

MODEL_FILE='experiments/insight_research/review/minimal_critic_v01_20261022/project_model_config.json'


def prepare_controlled(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    model=json.loads((ROOT/MODEL_FILE).read_text());config=settings()
    config.update(research_profile='paired_research_v1',verification_mode='self',model_config=model)
    config['limits'].update(token_allowance=0,max_http_attempts=0,max_request_bytes=524288,knowledge_context_bytes=24000)
    world=ComposedWorld(kind='composed',seed=27491,scenario_version='office-business-v0.5')
    owner=ResearchWorkspace(output/'source','核验已有认识并继续研究',world,config)
    counter=0
    def call(name,args):
        nonlocal counter
        counter+=1;result=owner.call(name,args,'provided-'+str(counter))
        if result.get('ok') is False:raise ValueError(result)
        return result
    def save(**changes):return call('update_research_state',state(**changes))
    try:
        source=next(x['ref'] for x in owner.context()['public_files'] if Path(x['path']).name=='business.sqlite')
        with sqlite3.connect((owner.public/'business.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            total,units=db.execute('SELECT sum(net_profit),count(*) FROM daily_finance').fetchone()
            duplicated=db.execute('SELECT sum(f.net_profit) FROM daily_finance f JOIN hourly h ON f.site=h.site AND f.day=h.day').fetchone()[0]
        old={'kind':'method','statement':'柜点日财务台账与小时商品记录按柜点和日期连接后，可以直接对连接表net_profit求和来汇总原柜日总净利润。',
            'scope':'给定历史财务与小时记录的汇总方法，尚待核验','status':'tentative','evidence_refs':[source],
            'tags':['finance','join','柜日','台账'],'research_use':'帮助选择跨表汇总口径'}
        k1=save(knowledge_updates=[old])['knowledge_refs'][0]
        bad=call('query_data',{'sql':'SELECT sum(f.net_profit) AS history_profit FROM daily_finance f JOIN hourly h ON f.site=h.site AND f.day=h.day',
            'purpose':'提供已有派生分析的完整原件，尚未独立核验其口径'})
        derived={'kind':'observation','statement':f'依据历史汇总方法，这段已见历史的柜日净利润总额为{duplicated:.8f}元。',
            'scope':'给定全部daily_finance对应的柜点日','status':'tentative','evidence_refs':[k1,bad['file']['ref']],
            'tags':['finance','净利润'],'research_use':'帮助理解现有经营记录'}
        k2=save(evidence_refs=[k1],knowledge_updates=[derived])['knowledge_refs'][0]
        h=call('save_hypothesis',{'kind':'business','statement':f'给定历史daily_finance中全部柜点日的记录net_profit加总为{total:.8f}元。',
            'scope':'全部公开历史daily_finance的柜点日记录，只描述该台账，不外推未来经营或客户行为。',
            'prediction':f'对给定daily_finance的net_profit求和，与{total:.8f}元的差不超过0.000001。',
            'falsification':'同范围独立汇总超出上述误差界。','alternatives':['其他分组、重复测量或统计口径可能回答不同问题。'],
            'evidence_refs':[source]})
        save(active_hypothesis_refs=[h['ref']],focus_hypothesis_refs=[h['ref']],evidence_refs=[k2],
            understanding=f'此前历史笔记按既有方法得到总额{duplicated:.8f}元；当前新问题有待依据原件核验。',
            open_questions=['已有认识与新结果是否覆盖同一范围，如何修订并继续研究？'])
        code="import os,sqlite3,json\nfrom pathlib import Path\nc=sqlite3.connect(Path(os.environ['PUBLIC_DIR'])/'business.sqlite')\nprint(json.dumps({'sum_net_profit':c.execute('SELECT sum(net_profit) FROM daily_finance').fetchone()[0],'scope':'all received daily_finance rows','nature':'seen historical record sum'}))"
        p=call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'原数值预测与同范围台账汇总',
            'observation_unit':'柜点日台账','allocation_unit':'无干预分配','analysis':'完整保留代码与输出，核验记录汇总',
            'purpose':'已提供的观测分析结果，等待研究者形成判断','data_refs':[source],'mode':'observational','code':code})
        result=call('run_test',{'plan_ref':p['ref']})
        export_initial(owner,output/'initial')
        task={'id':'PAIR-CONTROL-01','split':'new_controlled_repair','independent_unit_id':'office_27491_initial_record_repair',
            'question':'围绕提供的原假说与已有结果核验认识，并复核有影响的历史方法与派生笔记；依据证据修订、决定下一步并阶段交付。输入为脚本提供的遗留状态，不是你的自主发现，不能假定每条旧笔记正确。',
            'environment':{'kind':'composed','seed':27491,'scenario_version':'office-business-v0.5'},
            'initial_manifest':str((output/'initial/manifest.json').relative_to(ROOT)),
            'initialization_notice':'科学初始记录和旧笔记由脚本提供，未经本轮Agent认证；需要按原件核验。旧过程可回读，执行成功不是口径认证。',
            'limits':{'token_allowance':2000000,'max_http_attempts':80,'max_transport_retries':1,'round_wall_seconds':3600,
                'max_request_bytes':524288,'recent_turns':4,'knowledge_context_bytes':24000}}
        write_json(output/'tasks.json',{'tasks':[task],'model_config_file':MODEL_FILE})
        write_json(output/'expected_private.json',{'not_actor_input':True,'true_record_total':total,'row_units':units,
            'duplicated_join_total':duplicated,'wrong_method_ref':k1,'dependent_note_ref':k2,'provided_hypothesis_ref':h['ref'],
            'provided_result_ref':result['ref'],'evaluation':'Retain the correct finite-record claim; actually correct/retire the wrong method and dependent use, not merely write a new note. No autonomous discovery credit.'})
        return task
    finally:owner.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    task=prepare_controlled(parser.parse_args().output)
    print(json.dumps({'task_prepared':task['id'],'paid_calls':0}))
