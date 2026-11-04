"""Composition over the existing world and sandbox, with no old role workspace.

Trial allocation/measurements adapted from business_team/workspace.py:experiment.
The environment supplies observations, not a truth verdict. Its private world
object and generator are never mounted in the actor's filesystem.
"""
from pathlib import Path
import shutil
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t
from .common import ROOT, write_json
from world import START, BASELINE_CODE
from contracts import dictionary
from experiment_plans import capabilities, match_changed_variables

BRIEF = '''你负责研究办公售货柜业务，发现现有模型忽略的、有实际数据支持且有适用范围的业务关系或机制。当前交付是研究认识及证据。分析、写统计代码、检验和修订由你自主安排。
这是开发仿真，不是企业现场事实。工作日09:00–19:00，晨间补货，无日内补货。销售商品每SKU最多50件；免费配套用品最多80件，通常晨间供应0或80件，按实际发出量计成本。鲜食未售当天报损，其他商品按采购成本回收剩余价值。
收到12周观测；day<56为估计段，56<=day<84为开发段，两段都已公开，不能称为独立未见验证。销量可能受缺货截断和记录质量影响，不等同潜在需求。没有客流、潜在需求或用户级购买记录。
原模型源码作为背景提供：使用柜点、商品、星期和时段，在全程有货行上估计不受库存截断的需求均值，可能有选择偏差。缺货时预测高于销量不自动证明预测错误。无需交付替代算法或利润排名。
字段、粒度、信息可用时点见data_dictionary.json。配套供应计划是晨间信息，不是未来各小时实测库存。协议见experiment_contract.json；记录核对没有新增实物测量，供给试验只改变其声明的变量。结论须对应实际操作、观测和原预测，缺测量可以明确提出请求。'''


def guard_path(root):
    compact = ''.join(c for c in str(Path(root).resolve()).lower() if c.isalnum())
    if any(label in compact for label in ('relationship', 'confounding', 'recordfault', 'siteweekday')):
        raise ValueError('Actor workspace requires a neutral path')


class Environment:
    def __init__(self, world):
        self.world = world

    def materialize(self, public):
        self.world.public_dataset(public)
        # This phase exposes no later algorithm evaluation window.
        (public / 'development_features.csv').unlink()
        (public / 'business_brief.md').write_text(BRIEF)
        (public / 'original_model.py').write_text(BASELINE_CODE)
        with sqlite3.connect(public / 'business.sqlite') as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            schema = {name: [r[1] for r in db.execute('PRAGMA table_info(' + name + ')')] for name in tables}
        write_json(public / 'data_dictionary.json', {**dictionary(schema, structured=True), 'database_file': 'business.sqlite'})
        shutil.copyfile(ROOT / 'experiments/business_team/source_access.py', public / 'source_access.py')
        protocols = capabilities(pd.read_csv(public / 'products.csv'))
        for protocol in protocols.values():
            protocol['backend_analysis'] = ('mean of within-site treated-control daily selected-SKU sales; approximate t interval over 8 sites, alpha=.025'
                if protocol['is_new_sample'] else 'row-wise opening+restock-closing reconciliation and total mismatch count')
            protocol['analysis_contract'] = 'run_test executes this backend analysis; your analysis field states scientific intent. Additional estimands require explicit post-processing and disclosure.'
        write_json(public / 'experiment_contract.json', protocols)
        return protocols

    def execute(self, public, directory, plan, slot):
        """Slot is durably assigned before entry; a crashed call is not resampled."""
        protocol = plan['protocol']
        match_changed_variables(plan['expected_changed_variables'], protocol)
        history = pd.read_csv(public / 'history.csv')
        products = plan['outcome_product_ids']
        if protocol['kind'] == 'inventory_audit':
            rows = history[history.sku.isin(products)].copy()
            rows['verified_sales'] = rows.opening_stock + rows.restock - rows.closing_stock
            assignment = pd.DataFrame(columns=['day', 'site', 'treatment'])
            summary = {'rows': len(rows), 'recorded_total': int(rows.sales.sum()),
                       'verified_total': int(rows.verified_sales.sum()),
                       'mismatched_rows': int((rows.sales != rows.verified_sales).sum()),
                       'limits': protocol['measurement']}
        else:
            if slot not in (0, 1):
                raise ValueError('maximum two new supply trials')
            start = 84 + slot * 14
            days = [d for d in range(start, start + 14) if (START + pd.Timedelta(days=d)).weekday() < 5]
            rng = np.random.default_rng(np.random.SeedSequence([self.world.seed, 701, slot]))
            allocation = {}
            for site in pd.read_csv(public / 'sites.csv').site:
                flags = rng.permutation([0] * (len(days)//2) + [1] * (len(days)-len(days)//2))
                allocation.update({(d, site): int(flag) for d, flag in zip(days, flags)})
            assignment = pd.DataFrame([{'day': d, 'site': s, 'treatment': a} for (d, s), a in allocation.items()])
            write_json(directory / 'allocation_before_sampling.json', assignment.to_dict('records'))
            rows, _ = self.world.generate(start, 14, assignment=allocation,
                                         support_sku=protocol['support_sku'], main_high=True)
            outcome = rows[rows.sku.isin(products)].groupby(['site', 'day', 'treatment']).sales.sum().reset_index()
            means = outcome.groupby(['site', 'treatment']).sales.mean().unstack()
            effects = means[1] - means[0]
            effect = float(effects.mean())
            radius = float(t.ppf(1-.025/2, len(effects)-1) * effects.std(ddof=1) / np.sqrt(len(effects)))
            support = rows[(rows.sku == protocol['support_sku']) & (rows.hour == 9)]
            summary = {'mean_daily_sales_difference': effect, 'cluster_interval_97_5': [effect-radius, effect+radius],
                       'site_clusters': len(effects), 'site_day_units': len(outcome), 'alpha': .025,
                       'analysis': 'mean of within-site differences; approximate t interval over 8 site clusters',
                       'limits': protocol['limits'],
                       'main_stockout_hours': int((rows[rows.sku.isin(products)].available_minutes < 60).sum()),
                       'actual_supply_by_arm': [{'treatment': int(a), 'site_days': len(g),
                            'stock_levels': sorted(map(int, g.opening_stock.unique()))} for a, g in support.groupby('treatment')]}
        rows.to_csv(directory / 'observations.csv', index=False)
        assignment.to_csv(directory / 'assignment.csv', index=False)
        receipt = {'ok': True, 'summary': summary, 'protocol': protocol,
                   'generated_files': [str(directory / n) for n in ('observations.csv', 'assignment.csv')],
                   'execution_directory': str(directory)}
        write_json(directory / 'backend_receipt.json', receipt)
        return receipt
