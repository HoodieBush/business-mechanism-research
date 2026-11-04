"""Public operating contract. Contains no demand rules or private world labels."""
LEGACY_VERSION = 'office-business-v0.2'
VERSION = 'office-business-v0.3'
EXTENDED_VERSION = 'office-business-v0.4'
SALE_STOCK_CAP = 50
SUPPORT_STOCK_CAP = 80


def operating_rules(scenario_version=VERSION):
    if scenario_version not in (VERSION, EXTENDED_VERSION):
        raise ValueError('unknown revised scenario version')
    return {
        'scenario_version': scenario_version,
        'sale_goods': {'daily_stock_cap': SALE_STOCK_CAP, 'intraday_replenishment': False},
        'support_goods': {'daily_stock_cap': SUPPORT_STOCK_CAP,
                          'usual_morning_supply': [0, SUPPORT_STOCK_CAP],
                          'algorithm_decision': 'exogenous in this prediction/replenishment study'},
        'forecast_time': '09:00 before opening; future hourly outcomes are unavailable',
        'forecast_output': 'uncensored hourly demand mean for sale goods, not recorded sales',
        'decision_interface_file': 'decision_interface.json',
        'ordering_policy_file': 'ordering_policy.py',
        'historical_opening_file': 'historical_opening.csv',
        'research_scope': 'Identify business/data mechanisms and improve sale-goods replenishment under the given support supply. Optimising support supply itself is outside this phase.',
        'training': 'day<56 estimate; 56<=day<84 development diagnostics. Refit with received history before later operational development evaluation; disclose training IDs.',
        'costs': 'Fresh leftovers have zero value; other sale goods recover cost. Support cost is charged on units actually issued. Route/labour cost is excluded.',
    }


def business_brief():
    r = operating_rules()
    return f'''你们是办公售货柜经营公司的算法研究团队。从公开数据及原算法定位反复出现的经营问题，提出竞争解释，做可复查检验，再决定是否修改算法。目标是净利润与鲜食报损，不仅是拟合。这是开发仿真，不是企业现场事实。
工作日09:00–19:00营业，每日晨间补货，无日内补货。销售商品每SKU开日最多{r['sale_goods']['daily_stock_cap']}件；免费配套用品每SKU最多{r['support_goods']['daily_stock_cap']}件，通常晨间供应为0或{SUPPORT_STOCK_CAP}件，按实际发出量计成本。鲜食当天未售报损，其他销售商品剩余按采购成本回收。本阶段算法决定销售商品补货，配套供应由给定运营计划决定；改善配套供应策略本身不在本阶段算法动作空间内。
数据对象：hourly是各SKU自身逐小时库存/记录销量；support_plans是柜点×日×配套SKU的09点已知供应计划；prediction_features是晨间可知的逐商品小时预测输入；products/sites是商品/设施属性。history.csv把观测、属性与晨间计划合并供研究。其中planned_*列始终是晨间计划，历史和未来含义相同，不是未来小时实测库存。各实体键、时间点、信息可用时点见数据字典。可自行联接和分析原表，不要把跨时点库存聚合称为晨间量。
提供12周历史：day<56用于估计，56<=day<84用于开发诊断；后续经营开发评价可重估收到的历史，但需保存训练范围。最后独立验收另留。潜在需求与客户偏好不可直接观测，记录销量会受库存截断。原算法用全程有货行的销量近似需求，可能有选择偏差；缺货时预测高于销量不自动代表预测错误。
算法文件定义predict(history:DataFrame,future:DataFrame)->非负数组，输出每个销售商品小时不受库存截断的需求均值，再由固定订货规则计算日补货。future只有预测时点可知字段；sales、closing_stock、available_minutes等事后字段不能作晨间特征。数值参照均提供实际源码，可选择它们或自己编写算法，收益不足可以回退。
decision_interface.json登记实际共享ordering_policy.py的版本、经济参数来源、字段和时序。逐小时预测先聚合为日需求均值，再用固定Poisson分位规则和库存上限得到建议量；该分布是订货规则假设，不是需求真值。开发评价的order_decisions.csv分别记录建议量与实际09点开库存及其差异；后者在订货执行后观测，不能当作predict的事前输入。historical_opening.csv是历史真实09点状态；历史通常配货规则与当前候选predict产生的订货不同，免费配套供给仍由给定运营计划决定。公开规则不扩大本阶段算法动作权限。
可查询原始资料、自己写Python，并申请库存记录核对或配套供给随机试验。describe_experiments返回实际两组操作、固定条件和测量单位；先prepare_experiment，再执行计划，不通过文字增加干预。每项供给试验14日历天、按柜点日分配，两组鲜食均{SALE_STOCK_CAP}件；最多2项新供给试验，每项alpha=.025，按柜点重复测量分析。库存核对只是记录之间的核对，不是新的实物盘点或完整需求。
describe_evaluation返回已注册开发条件、可执行操作、程序版本和逐柜点日评价文件。开发经营结果是仿真观测，不是需求真值；额外随机流不增加独立柜点或机制世界。最终选择冻结后研究角色关闭，最终评价不返回研究角色。'''
