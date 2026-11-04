"""One source of public field meanings and conservative aggregation warnings."""
import re

VERSION = "business-data-contract-v0.3"
HOURS = tuple(range(9, 19))
OPENING_HOURS = "工作日09:00–19:00"

FIELD_MEANINGS = {
    "day": ("日历日编号，0=2026-01-05；不是营业日顺序", "日历日", "标识，不求和"),
    "date": ("业务发生日期，本地时间", "日期", "分组标识"),
    "weekday": ("0周一到6周日；本场景仅工作日营业", "类别", "分组标识"),
    "hour": ("小时开始点，9代表09:00–10:00，18代表18:00–19:00", "本地小时", "时间标识"),
    "site": ("售货柜点位编号；重复小时/日期不是独立柜点", "类别", "分组标识"),
    "sku": ("商品编号", "类别", "分组标识"),
    "price": ("每件售价；免费用品售价为0", "元/件", "不能跨小时相加当总收入"),
    "sales": ("该小时业务记录的售出/免费发出件数，可能有记录错误；不是客流或潜在需求", "件/小时记录", "可跨小时求和为期间记录销量"),
    "opening_stock": ("当前行SKU在该小时开始的实物库存，同一日状态反复记录；开日量取09点首行", "件，时点状态", "跨小时不能求和为每日开库存或进货量"),
    "closing_stock": ("该小时结束的实物库存；日末量取18点末行", "件，时点状态", "跨小时不能求和为日末库存；属于事后信息"),
    "restock": ("小时区间内补入数量。本演示开日补货在09点开库存体现，hourly.restock为0不等于没有每日补货", "件/小时区间", "可对日内补货求和，不包括已进入开库存的晨间补货"),
    "available_minutes": ("售卖商品该小时有货分钟，由售罄时刻记录；60全程有货，0可能开小时已无货；免费用品仅是小时末有货60/无货0的粗指标", "分钟/小时；免费用品为粗指标", "售卖商品可求和得有货时长；低于60提示截断；不可用未来该字段作晨间预测"),
    "s11_hour_start_stock": ("无论当前行SKU是谁，此字段始终是S11餐具该小时开始的实测数量；S12自身库存要取S12行opening_stock", "件，S11小时开始时点", "不能因筛选SKU就改变字段归属，不能跨小时求和为开日库存"),
    "planned_s11_morning_stock": ("预测当天早晨的S11计划开库存；不是未来各小时实际库存", "件，S11计划开日时点", "同日重复特征不相加；后续供给可用性仅是近似"),
    "planned_s12_morning_stock": ("预测当天09点已知的S12计划开库存；不是后续小时实测量", "件，S12计划开日时点", "柜点日特征广播到小时；不跨小时求和"),
    "support_sku": ("这一行供给计划所属的配套商品编号", "商品标识", "实体键；不因联接到别的商品而改变"),
    "planned_opening_stock": ("此柜点日support_sku在开门前已知的09点计划库存", "件，计划时点状态", "按柜点日配套SKU唯一；不是发出量，不跨小时求和"),
    "known_at_hour": ("该日这项计划已提供给决策者的小时开始点", "本地小时", "信息可用时点；不是供给效果或库存持续时长"),
    "category": ("业务商品分类，不表示该分类必然有购买效果", "类别", "分组标识"),
    "description": ("实物包装及用途说明，不是机制结论", "文本", "不聚合"),
    "unit_cost": ("每件采购或发出成本", "元/件", "乘实际数量才是总成本"),
    "salvage": ("未售件的单件剩余价值；鲜食0，其他商品按成本计是本演示简化", "元/件", "乘剩余件数"),
    "shelf_life_days": ("货架期限；鲜食在本演示当天结束报损", "日", "不求和"),
    "includes_cutlery": ("商品包装是否实物附带餐具；描述属性不是已验证购买影响", "0/1", "类别属性"),
    "type": ("柜点类型", "类别", "分组标识"),
    "microwave": ("柜点是否有可用微波炉", "0/1", "设施属性"),
    "pantry_cutlery": ("附近茶水间是否有替代用餐工具", "0/1", "设施属性"),
    "opening_hours": ("本演示工作日09:00–19:00，与10个小时记录一致", "时间区间", "不聚合"),
    "net_profit": ("柜点当日实收收入减采购成本、加剩余价值、减免费用品实际发出成本；非客均利润", "元/柜点日", "可加为总利润、平均为柜日利润；未计路线人工等成本"),
    "fresh_waste": ("该柜点日末鲜食未售件数", "件/柜点日", "可加为期间报损"),
    "observed_stockout_hours": ("该柜点日鲜食SKU小时记录中available_minutes<60的记录数；部分小时也记1，不是实际缺货持续时长", "受影响鲜食SKU-hour记录数/柜点日", "可加为受影响记录总数；不能解释为缺货分钟或全柜点时钟小时"),
    "predicted_demand_mean": ("晨间预测该SKU该小时不受库存截断的需求均值，用于订货；非给定实际库存后的记录销量预测，非独立需求真值", "件/小时需求均值", "对当日小时相加作日需求均值；不能仅因缺货时预测>记录销量就判定错误"),
    "treatment": ("试验的柜点日随机分配：1为保证指定配套用品晨间供应，0为原运营供应；历史CSV恒为0，不是机制标签", "0/1分配", "干预单位为柜点日，重复小时不是独立随机单位"),
    "verified_sales": ("opening_stock+restock-closing_stock推算的实际发出量；是盘点核对，依赖盘点准确且无其他损耗的本演示假设", "件/小时", "可求和；不是完整需求或独立新样本"),
}

GRAINS = {
    "hourly": "一行=一个柜点×一个商品×一个自然小时，工作日09–19；销售区间量与库存时点量区别",
    "products": "一行=一个商品",
    "sites": "一行=一个柜点",
    "daily_finance": "一行=一个柜点×一个营业日",
    "baseline_predictions": "一行=一个柜点×一个商品×一个预测小时，晨间作出预测",
    "support_plans": "一行=一个柜点×一个日历日×一个配套SKU的09点供给计划",
    "prediction_features": "一行=一个柜点×一个销售SKU×一个将来小时，特征全部在当日09点预测时已知",
}


def field_definition(name, structured=False):
    result=dict(zip(('meaning','unit','aggregation'),FIELD_MEANINGS[name]))
    if not structured:return result
    if name.startswith('planned_'):
        entity='support_sku' if name=='planned_opening_stock' else name.removeprefix('planned_').split('_')[0].upper()
        result.update(entity=entity,observation_time='09:00 opening plan, site-day grain',available_at='09:00 before forecast')
    elif name in ('sales','restock','available_minutes','verified_sales'):
        result.update(entity='row.sku',observation_time='[hour, hour+1) interval',available_at='after hour+1, observed outcome')
    elif name in ('opening_stock','closing_stock'):
        result.update(entity='row.sku',observation_time='hour start' if name=='opening_stock' else 'hour end',
                      available_at='at this observed instant; later hours are unavailable to morning forecast')
    elif name in ('net_profit','fresh_waste','observed_stockout_hours'):
        result.update(entity='row.site',observation_time='whole business day',available_at='after business-day close')
    elif name=='predicted_demand_mean':
        result.update(entity='row.sku',observation_time='target future hour',available_at='09:00 forecast output, not observed demand')
    else:
        result.update(entity='row key or product/site attribute',observation_time='calendar/identifier/static attribute',available_at='before morning forecast; not a measured outcome')
    return result


def dictionary(schemas, structured=False):
    missing = {name for columns in schemas.values() for name in columns} - set(FIELD_MEANINGS)
    if missing:
        raise ValueError("undefined public column semantics: " + str(sorted(missing)))
    return {"version": 'business-data-contract-v0.4' if structured else VERSION, "tables": {table: {"row_grain": GRAINS[table], "columns": {
        name: field_definition(name,structured) for name in columns}} for table, columns in schemas.items()},
        "limits": ["没有客流、潜在需求、真实机制或用户级购买转化数据", "行数不是销量，也不是独立消费者数",
                   "营业时间由共同常量生成，数据库模式逐字段核对说明", "历史拟合、开发观察、新试验、最终评价分开，不能用同一结果认证自身修订"]}


def aggregation_warnings(text):
    compact = re.sub(r"\s+", "", text.lower())
    matches = [r"sum\(opening_stock\)", r"['\"]opening_stock['\"],['\"]sum['\"]", r"\[['\"]opening_stock['\"]\]\.sum\("]
    if any(re.search(pattern, compact) for pattern in matches):
        return ["开库存求和涉及重复时点状态。请明确是否跨小时；每日開库存应取09点首行，不能把此求和叫日进货量。若研究库存时间暴露需另述单位。"]
    return []
