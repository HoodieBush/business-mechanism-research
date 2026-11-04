# 数据接入示例

在交付包根目录运行：

```sh
python examples/create_example_data.py --output ./example-inputs
```

脚本仅用Python标准库，生成SQLite、业务说明和字典，不调用模型；输出目录已存在时拒绝覆盖。数据为4个站点、30天、120行，可用于创建项目和熟悉部署流程。

生成规则公开在脚本中：完成量取随机整数加容量项，登记计数逐单按固定概率采样。它只用于部署演示，不能用来声称盲测发现了隐藏机制或具备真实业务价值。

自己的数据也使用三个文件：business.sqlite、business_brief.md、data_dictionary.json。表和字段名称自由；字典须与实际schema对应。业务说明要解释一行是什么、量值单位、计数口径、缺失值、时间范围和实际可用的测量/干预能力。

已有CSV可在安装依赖后转成SQLite，例如：

```python
import sqlite3
import pandas as pd

with sqlite3.connect("inputs/business.sqlite") as db:
    pd.read_csv("your_data.csv").to_sql("transactions", db, index=False, if_exists="fail")
```

请先创建inputs目录，并自行补写业务说明和字段字典。Excel也可先导出CSV；直接改扩展名不能变成SQLite。

不要将密钥放入输入目录。未知含义应明确写未知，例如登记销量未必是实际需求、唯一记录ID未必表示时间顺序。程序会观察表结构，但无法替数据方补齐真实业务含义。
