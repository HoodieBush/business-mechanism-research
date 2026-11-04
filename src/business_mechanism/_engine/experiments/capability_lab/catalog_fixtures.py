"""Curated physical facts, separate from demand equations and parameters.

Structured tasks expose the facts; text tasks expose descriptions only. Labels
are synthetic fixture annotations, not a claim of independent enterprise data.
"""
FUNCTION_KEYS=("heating","utensils","sealing","decoration","carrying")
DESCRIPTIONS={
    "source":["实物能为餐食加热的自热组件","实物包含用于进餐的餐具套件",
        "实物同时提供餐食加热和餐具的组合包","实物提供防漏密封功能的汤食杯盖",
        "仅印餐具图案的装饰贴纸，不提供进餐餐具","仅便于手提的礼袋，不能为餐食加热"],
    "adaptation":["新品牌实物升温模块，能使冷餐变热","新品牌实物用餐工具，内含进餐用勺",
        "新品牌实物热餐及进餐工具合一套装","新品牌实物密闭防溢封口附件",
        "新品牌装饰图样像勺子，实物不是用餐工具","新品牌实物提手袋，印有发热字样但没有升温功能"],
    "heldout":["另一品牌实物可提高食物温度的便携装置","另一品牌实物含可舀食物的进食器具",
        "另一品牌实物兼具食物增温与进食器具","另一品牌实物阻止汤汁渗出的封盖",
        "另一品牌仅有叉勺图案的饰物，不能用来吃饭","另一品牌仅能手提的袋子，外观像热食套件但不能增温"]}
MEMBERSHIPS=[("heating",),("utensils",),("heating","utensils"),("sealing",),("decoration",),("carrying",)]
UNIT_COSTS=[.06,.03,.10,.08,.02,.03]
