"""Public fixed sales-goods ordering rule, also used by the actual backend.

No demand generator, private condition, future outcome or model verdict lives
here. `operating_orders` returns the old quantities; with_trace=True also gives
their arithmetic inputs. `attach_execution` adds actually observed opening
inventory, preserving discrepancies rather than assuming the plan happened.
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson

VERSION = 'daily-poisson-quantile-v1'
KEY = ['day', 'site', 'sku']
EXECUTION_FIELDS = ('executed_opening_stock', 'execution_difference')
PREDICTION_MIN = 0
PREDICTION_MAX = 100
MINIMUM_MEAN = .01
HISTORICAL_FRESH_STOCK = 35
HISTORICAL_OTHER_SALE_STOCK = 45


def historical_sale_stock(category):
    """Usual historical sales-goods allocation, before any trial/override."""
    return HISTORICAL_FRESH_STOCK if category == '鲜食' else HISTORICAL_OTHER_SALE_STOCK


def operating_orders(features, predictions, products, stock_cap, *, with_trace=False):
    """Same fixed policy for research calculations and backend execution.

    Keys/features identify sale goods. Products supply price, unit_cost and
    salvage. Hourly predictions are clipped to [0,100] then summed per key;
    a Poisson daily quantile is a decision assumption, not demand truth.
    A critical fractile >=1 uses the cap directly; its unconstrained finite
    quantile is undefined and recorded as null, never an invented number.
    """
    f = features.copy()
    f['prediction'] = np.clip(np.asarray(predictions, float), PREDICTION_MIN, PREDICTION_MAX)
    totals = f.groupby(KEY)['prediction'].sum()
    product_rows = products.set_index('sku')
    orders, records = {}, []
    for key, mean in totals.items():
        p = product_rows.loc[key[2]]
        fractile = (p.price - p.unit_cost) / (p.price - p.salvage)
        decision_mean = max(MINIMUM_MEAN, mean)
        unconstrained = None if fractile >= 1 else int(poisson.ppf(fractile, decision_mean))
        quantity = stock_cap if fractile >= 1 else min(stock_cap, unconstrained)
        orders[key] = quantity
        if with_trace:
            records.append(dict(zip(KEY, key), daily_forecast_mean=mean,
                poisson_mean=decision_mean, critical_fractile=fractile,
                unconstrained_quantity=unconstrained, stock_cap=stock_cap,
                order_quantity=quantity, cap_applied=fractile >= 1 or unconstrained > stock_cap))
    trace_columns = KEY + [name for name in DECISION_FIELDS if name not in EXECUTION_FIELDS]
    return (orders, pd.DataFrame(records, columns=trace_columns)) if with_trace else orders


def attach_execution(trace, observed_hourly, opening_hour=9):
    """Join the actual post-action state. Do not force it to equal the plan."""
    opening = observed_hourly[(observed_hourly.hour == opening_hour) &
                               observed_hourly.sku.isin(trace.sku.unique())]
    opening = opening[KEY + ['opening_stock']].rename(columns={'opening_stock': 'executed_opening_stock'})
    result = trace.merge(opening, on=KEY, how='left', validate='one_to_one')
    if result.executed_opening_stock.isna().any():
        raise ValueError('missing actually observed opening inventory for a decision key')
    result['execution_difference'] = result.executed_opening_stock - result.order_quantity
    return result


def definition(meaning, unit, aggregation, event, *, nullable=False, available_at=None):
    return {'meaning': meaning, 'unit': unit, 'aggregation': aggregation,
            'entity': 'row.sku within row.site/day', 'observation_time': event,
            'available_at': available_at or ('09:00 after prediction/ordering' if event != '09:00 actual opening after order execution' else '09:00 after actual order execution; not a pre-forecast input'),
            'nullable': nullable}


DECISION_FIELDS = {
    'daily_forecast_mean': definition('当日该销售SKU逐小时预测经[0,100]裁剪后求和；不是记录销量或需求真值', '件/柜点日SKU，预测均值', '不可再次按小时重复相加', '09:00 forecast-derived daily total'),
    'poisson_mean': definition('固定订货函数使用的Poisson均值=max(0.01,daily_forecast_mean)；是规则假定', '件/柜点日SKU，规则参数', '不作为实际需求或销量求和', '09:00 decision parameter'),
    'critical_fractile': definition('(price-unit_cost)/(price-salvage)，来自公开商品经济参数', '无量纲分位', '不可相加；不是估计成功概率', 'public economic parameter', available_at='before morning forecast, from known product prices/costs/salvage'),
    'unconstrained_quantity': definition('有限Poisson分位订货量，尚未应用上限；分位>=1时无有限值，以空值记录而直接采用上限', '件/柜点日SKU，有限时为整数', '空值不是零件；不能把空值当缺数据自行补零', '09:00 decision output before cap', nullable=True),
    'stock_cap': definition('该销售SKU每日开日库存上限', '件/柜点日SKU', '同一约束，不跨小时相加', 'public operating constraint', available_at='before morning forecast'),
    'order_quantity': definition('应用上限后的建议开日订货量；预测输出之后、实际执行之前的决策，不是预测特征', '件/柜点日SKU，整数', '可按实际决策键加总；不在逐小时行重复相加', '09:00 order decision'),
    'cap_applied': definition('分位>=1或有限分位量超过上限，因而使用库存上限', '布尔', '计数需说明决策键；不是履约成功标志', '09:00 cap branch'),
    'executed_opening_stock': definition('实际营业观测中该SKU09点开库存；独立取自observed_hourly，不用建议量代填', '件/柜点日SKU，实物时点状态', '只取一次09点状态；不是整日销量', '09:00 actual opening after order execution'),
    'execution_difference': definition('实际09点开库存减建议订货量；保留执行差异，不自动归因为需求或具体故障', '件/柜点日SKU', '可汇总差异，不能直接解释为利润损失', '09:00 actual opening after order execution'),
}


def specification(stock_cap):
    return {'policy_version': VERSION,
            'prediction_clip': [PREDICTION_MIN, PREDICTION_MAX],
            'minimum_poisson_mean': MINIMUM_MEAN, 'sale_stock_cap': stock_cap,
            'daily_model_assumption': 'Poisson quantile on summed hourly predicted means; a fixed decision rule, not certification of the actual demand distribution.',
            'optimality_scope': 'A fixed common operating policy, not a guarantee of globally optimal business decisions.',
            'critical_fractile': '(price-unit_cost)/(price-salvage)',
            'history_sale_supply': {'fresh': HISTORICAL_FRESH_STOCK, 'other_sale_goods': HISTORICAL_OTHER_SALE_STOCK,
                'scope': 'Usual historical initial allocations, not outputs of the supplied predict programs. Registered trial/operating overrides are separate. Support supply is exogenous and described in operating_rules/support_plans.'},
            'temporal_order': ['09:00 available prediction inputs', 'hourly prediction output',
                               'daily aggregation and order decision', 'actual opening stock', 'hourly sales/inventory outcomes']}
