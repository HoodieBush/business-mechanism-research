# 商业机制研究系统 v0

提供业务问题、SQLite数据和字段说明，由研究者自主分析、提出可检验假说、执行计算；独立质疑者读取原件并复核，研究者据此回应、修订或保留未决。科学记录、反证、原始意见和累计消耗可追溯。

v0提供本地CLI和同步Python API，使用真实LangGraph调度。运行环境为Python3.12；Linux使用bubblewrap，macOS使用sandbox-exec。当前随包的本地验证覆盖Linux，macOS结果以对应提交的CI为准。科学机制正确性及连续24小时可用性尚未认证，见[评价范围](docs/EVALUATION.md)。

## 主要能力

- 只读SQLite查询和隔离Python分析；大查询落盘、结果分页、取消和新attempt重试。
- 独立复核、持久审查草稿、明确字段修复、幂等提交和实际计算输出核对。
- 活跃假说与阶段终结管理，支持接受、反驳和诚实未决；有限无进展保护与任务恢复。
- 上下文归档、阶段报告、协作暂停、后台监督，以及保留原记录和费用的显式副本迁移。

工具成功、质疑者同意和报告生成都需要与科学结论正确性分开判断。[执行与复核接口](docs/AGENT_REPAIRS.zh-CN.md)说明具体边界。

## 安装

SQLite须支持`PRAGMA hard_heap_limit`，安装预检会检查。Linux先按[隔离部署说明](docs/LINUX.md)配置bubblewrap。准备Python3.12后，在源码目录执行：

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install --no-deps .
python -m pip check
python tools/check_install.py
```

## 无模型验收

```sh
python scripts/check_release.py
python scripts/check_secrets.py --all-files
python tests/isolation.py --output ./acceptance-isolation
python tests/acceptance.py --output ./acceptance-local
python tests/update_compatibility.py --output ./acceptance-update
```

每次使用新的输出目录。这些检查使用本地回环夹具，外部模型调用为0。测试范围见[部署验收](DEPLOYMENT_VERIFICATION.md)。

## 开始研究

将`model.example.json`复制为`model.json`，填写有权使用的模型服务。密钥存放在仓库和工作区之外，或使用配置指定的环境变量。接口要求见[模型与API配置](docs/CONFIGURATION.zh-CN.md)。

业务输入包括`business.sqlite`、`business_brief.md`和`data_dictionary.json`。可先生成透明的合成部署样例：

```sh
python examples/create_example_data.py --output ./example-inputs
python tools/check_install.py --model-config ./model.json --data ./example-inputs
business-research create ./work/P001 \
  --question '研究登记数量与完成数量的差异，区分已有证据和待验证解释。' \
  --model-config ./model.json --data ./example-inputs \
  --tokens 2000000 --requests 80 --wall-seconds 7200 --max-stages 2
business-research run ./work/P001 --stages 1
```

`create`只建工作区；`run`开始调用配置的模型并产生费用。示例额度不保证研究或报告完成。FreshRetailNet输入另见[数据准备](docs/FRESHRETAILNET.zh-CN.md)，数据文件不随发行包分发。

## 状态、暂停与续跑

```sh
business-research status ./work/P001
business-research report ./work/P001
business-research pause ./work/P001
business-research run ./work/P001 --resume --stages 1
```

暂停会先排空已付费工具批次。续跑保留累计请求、费用、未知用量预留和原期限。后台运行、备份及升级见[运维说明](docs/OPERATIONS.zh-CN.md)。

`deliveries/`保存阶段进展、执行交接和已形成的独立报告；`researcher/`、`reviews/`及图数据库保留原件与执行状态。未决交接与正式核验报告有明确区分。

## 文档

[English](README.md) · [系统](docs/SYSTEM.zh-CN.md) · [复现](docs/REPRODUCIBILITY.md) · [版本说明](docs/releases/v0.md) · [源码来源](docs/SOURCE_PROVENANCE.md) · [贡献](CONTRIBUTING.md) · [引用](CITATION.cff)

按[MIT许可证](LICENSE)发布。发行内容包含源码、必要文档、测试和部署工具；私有实验时间线、真实数据、模型配置、密钥、运行日志及未采用原型不随包发布。
