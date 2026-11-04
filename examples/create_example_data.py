"""Generate deployment-only synthetic data with Python's standard library."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import random
import sqlite3


def main(output):
    output=output.expanduser().resolve()
    if output.exists():
        raise ValueError('Output already exists; choose a new directory instead of overwriting data.')
    output.mkdir(parents=True)
    rng=random.Random(20261104)
    rows=[]
    for day in range(30):
        for index,site in enumerate(('A','B','C','D')):
            capacity=1+(day+index)%2
            completed=rng.randint(8,24)+capacity*3
            registered=sum(rng.random()<(0.96 if site in ('A','B') else 0.88) for _ in range(completed))
            rows.append(((date(2026,1,1)+timedelta(days=day)).isoformat(),site,capacity,completed,registered))
    with sqlite3.connect(output/'business.sqlite') as db:
        db.execute('CREATE TABLE service_windows(day TEXT, site TEXT, capacity_units INTEGER, completed_orders INTEGER, registered_orders INTEGER, PRIMARY KEY(day,site))')
        db.executemany('INSERT INTO service_windows VALUES(?,?,?,?,?)',rows)
    (output/'business_brief.md').write_text('''# 合成部署样例

本数据仅供安装、输入适配和操作流程演示，不是真实公司数据，也不是正式科学能力评价材料。
每行是一个站点的一天，共4个站点、30天、120行。day为合成日历日期，不是业务现场时间。
completed_orders和registered_orders是两个演示计数；字段定义见字典。没有额外业务日志、订单级匹配、现场干预或新测量服务。
研究时可比较计数关系和描述性差异；不要声称有真实商业收益或由此确认真实公司机制。
''',encoding='utf-8')
    dictionary={'tables':{'service_windows':{'columns':{
        'day':'合成观测日期，ISO格式；一行代表该站点该日',
        'site':'合成站点标签A/B/C/D',
        'capacity_units':'演示容量等级，单位：档',
        'completed_orders':'合成完成订单数，单位：单',
        'registered_orders':'合成登记计数，单位：单；不自动等于潜在需求'}}}}
    (output/'data_dictionary.json').write_text(json.dumps(dictionary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'created','output':str(output),'rows':len(rows),'synthetic':True,'model_calls':0},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:main(args.output)
    except (ValueError,OSError) as error:parser.exit(2,str(error)+'\n')
