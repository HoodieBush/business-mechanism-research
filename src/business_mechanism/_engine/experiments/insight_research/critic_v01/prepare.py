"""Developer-only M0 smoke preparation; seeded assertions, not Agent discoveries.

The reviewer never receives this script, case construction labels or expected
answers. Only independently readable public evidence projections are mounted.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from ..common import ROOT, write_json
from ..composed_world import ComposedWorld
from ..test_acceptance import settings, state
from .shared import CheckedWorkspace
from .snapshot import export_snapshot

PROJECT_MODEL = 'experiments/insight_research/review/minimal_critic_v01_20261022/project_model_config.json'


def prepare(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    cases = []; expected = []
    for number, use_weighting in ((1, False), (2, True)):
        name = f'case_{number:02d}'
        config = settings(); config['limits'].update(max_request_bytes=524288, knowledge_context_bytes=24000)
        owner = CheckedWorkspace(output / 'sources' / name,
            '核验提供的候选业务认识。假说、判断和旧笔记由测试脚本准备，未声称Agent自主发现；请独立依据公开原件判断。',
            ComposedWorld(), config)
        counter = 0
        def call(tool, args):
            nonlocal counter
            counter += 1
            result = owner.call(tool, args, 'prepare-' + str(counter))
            if result.get('ok') is False: raise ValueError(result)
            return result
        try:
            source = next(x['ref'] for x in owner.context()['public_files'] if Path(x['path']).name == 'business.sqlite')
            with sqlite3.connect((owner.public / 'business.sqlite').as_uri() + '?mode=ro', uri=True) as db:
                reference, unweighted, numerator, denominator = db.execute(
                    'SELECT sum(price*sales)*1.0/sum(sales),avg(price),sum(price*sales),sum(sales) FROM hourly WHERE price>0').fetchone()
            reported = reference if use_weighting else unweighted
            h = call('save_hypothesis', {'kind': 'business',
                'statement': f'已公开历史中，正价商品的记录销售额除以记录售出件数为{reported:.10f}元/件。',
                'scope': '全部已公开柜点、日期、SKU及小时中price>0的记录；只描述记录量，不指实际实收、潜在需求或未来规律。',
                'prediction': f'按原范围计算sum(price*sales)/sum(sales)，与{reported:.10f}相差不超过1e-7。',
                'falsification': '按同一范围复算超过上述误差界。',
                'alternatives': ['不同加权与总体范围的统计量可能不同；记录度量不能直接当真实需求或实际实收。'],
                'evidence_refs': [source]})
            # Add a nonrecent, unlinked prior method note plus a second page.
            old = {'kind': 'method', 'statement': '历史笔记：每件平均价格可直接取各记录price的算术平均，无需按sales加权。',
                'scope': '正价销售记录的汇总解释，尚未核验', 'status': 'tentative', 'evidence_refs': [source],
                'tags': ['price', 'weighted', '加权', '单价'], 'research_use': '可能影响统计口径选择'}
            saved = call('update_research_state', state(active_hypothesis_refs=[h['ref']],
                focus_hypothesis_refs=[h['ref']], knowledge_updates=[old]))
            old_ref = saved['knowledge_refs'][0]
            for n in range(9):
                note = {'kind': 'method', 'statement': f'研究过程记录{n+1}：保留原件与未决问题入口。',
                    'scope': '本次已见资料', 'status': 'tentative', 'evidence_refs': [source],
                    'tags': ['navigation'], 'research_use': '协助定位过程，不当事实证据'}
                call('update_research_state', state(active_hypothesis_refs=[h['ref']], focus_hypothesis_refs=[h['ref']], knowledge_updates=[note]))
            sql = 'SELECT sum(price*sales)*1.0/sum(sales) FROM hourly WHERE price>0' if use_weighting else 'SELECT avg(price) FROM hourly WHERE price>0'
            code = "import os,sqlite3,json\nfrom pathlib import Path\ncon=sqlite3.connect(Path(os.environ['PUBLIC_DIR'])/'business.sqlite')\nvalue=con.execute(" + repr(sql) + ").fetchone()[0]\nprint(json.dumps({'value':value,'unit':'yuan/item','scope':'price>0; all received history'}))"
            p = call('register_test', {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
                'contrast': '原预测与同范围记录汇总', 'observation_unit': '柜点商品小时记录', 'allocation_unit': '无干预分配',
                'analysis': '描述已见记录；读取实际代码和输出以核查计算口径', 'purpose': '核对候选汇总认识',
                'data_refs': [source], 'mode': 'observational', 'code': code})
            result = call('run_test', {'plan_ref': p['ref']})
            assessment = call('record_assessment', {'hypothesis_ref': h['ref'], 'result_refs': [result['ref']],
                'status': 'supported', 'prediction_coverage': '声称覆盖全部公开历史正价记录的每件平均记录销售额',
                'rationale': f'已执行分析返回{reported:.10f}元/件，因此支持原预测；这是记录汇总而非因果或未见验证。',
                'deviations': [], 'counterevidence_refs': [],
                'limitations': ['仅已见历史和记录字段，不识别真实需求、实际实收、消费者行为或唯一机制。']})
            call('update_research_state', state(active_hypothesis_refs=[h['ref']], focus_hypothesis_refs=[h['ref']],
                incorporated_result_refs=[result['ref']], evidence_refs=[result['ref']], understanding='候选判断已形成，等待独立核验原件。'))
            receipt = export_snapshot(owner, output / 'inputs' / name, assessment['ref'])
            cases.append({'id': 'RC' + str(number).zfill(3), 'case': name, 'split': 'developer_smoke_new_assertions',
                'independent_unit_id': 'same_office_history_price_assertion_pair',
                'snapshot': str(Path(receipt['snapshot']).relative_to(ROOT)),
                'manifest_sha256': receipt['manifest_sha256'], 'target_ref': assessment['ref'],
                'limits': {'token_allowance': 500000, 'max_http_attempts': 6, 'max_transport_retries': 1,
                    'round_wall_seconds': 3600, 'max_request_bytes': 524288, 'recent_turns': 4}})
            expected.append({'case': name, 'target_ref': assessment['ref'], 'hypothesis_ref': h['ref'],
                'original_result_ref': result['ref'], 'target_numerically_correct': use_weighting,
                'reference_value': reference, 'reported_value': reported,
                'recorded_amount': numerator, 'recorded_units': denominator, 'unlinked_prior_note_ref': old_ref,
                'scope': 'Developer seeded finite review checks, not autonomous discovery or independent scientific samples.'})
        finally: owner.close()
    write_json(output / 'tasks.json', {'tasks': cases, 'model_config_file': PROJECT_MODEL,
        'phase_token_cap': 1000000, 'all_role_allowances_sum': sum(c['limits']['token_allowance'] for c in cases),
        'scope': 'M0 isolated review only; no discoverer model, online correction or new physical observation.'})
    write_json(output / 'expected_private.json', {'cases': expected, 'not_actor_input': True})
    return cases


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    args = parser.parse_args(); cases = prepare(args.output)
    print(json.dumps({'cases_prepared': len(cases), 'paid_calls': 0}, ensure_ascii=False))


if __name__ == '__main__': main()
