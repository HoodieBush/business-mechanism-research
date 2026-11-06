# FreshRetailNet-50K 接入

从[发布方的官方数据集](https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K)下载公开的 FreshRetailNet-50K，保留原始文件，并转换为本系统的只读 SQLite 输入。数据使用 CC BY 4.0 许可；下载清单、字段字典和业务说明保存来源、版本与署名。数据论文：https://arxiv.org/abs/2505.16319。

准备脚本不调用模型，也不开始研究。它不安装官方预测基线，不拟合需求，不向研究者提供论文的实验结论。

## 准备

在项目根目录执行。PyArrow仅用于读取原始Parquet，安装在独立的数据工具环境中，不改变运行系统的锁定依赖。

```sh
python3.12 -m venv acceptance-host/data-tools
acceptance-host/data-tools/bin/python -m pip install --index-url https://pypi.org/simple pyarrow==26.0.1

acceptance-host/data-tools/bin/python tools/prepare_freshretailnet.py \
  --raw-dir ./inputs/freshretailnet-50k-raw \
  --output ./inputs/freshretailnet-50k \
  --revision c374e85975c82816c495acfa904cc55ab14a47d3
```

需要先完成[系统安装与隔离验收](../README.zh-CN.md)。若Python 3.12具有其他路径，使用实际解释器。仅下载可加`--download-only`，此时不需要PyArrow。

官方大文件下载遇到网络问题时可显式加`--mirror`，通过hf-mirror.com直连传输文件；元数据与预期SHA-256仍从官方Hub获取，镜像文件必须与官方校验一致。下载清单分别记录官方来源和实际传输地址。

脚本以官方数据集提交和LFS SHA-256检查两份Parquet，按批次转换，保留全部train行及原始字段，检查SQLite完整性、行数守恒、主键唯一性及原值往返。原始缺失或字段一致性异常按审计计数保留，不擅自补全为需求。输出目录已存在时拒绝覆盖；中断的`.preparing`目录保留现场，重试转换应另选输出。原始文件可复用，但须再次通过校验。

## 文件和表

```text
inputs/freshretailnet-50k-raw/
  README.md                  官方数据卡原件
  download_manifest.json     固定提交、来源、长度和SHA-256
  data/train.parquet         原始train
  data/eval.parquet          原始eval，独立保留

inputs/freshretailnet-50k/
  business.sqlite
  business_brief.md
  data_dictionary.json
  conversion_receipt.json    全量转换及一致性检查回执
```

`retail_daily`的一行是一个门店商品日，包含原始19个字段。`hours_sale`和`hours_stock_status`为24元素JSON数组。`retail_hourly`是按需展开这些数组的视图，包含门店、商品、日期、小时、小时观测销量、缺货标记、折扣和活动字段；查询时优先限定门店、商品和日期，避免无意展开上亿行。

本研究输入仅包含train。eval保存在另一个原件目录，创建研究项目时不会进入其快照。尚未实现由控制器自动执行的独立eval评价；需要另行冻结分析或预测，再使用eval验证。不能因为保留了eval就宣称已通过留出验证。

## 使用范围

- 日销量和小时销量使用发布方的全局缩放。未公开缩放系数及原始量纲，不称为人民币、订单数或未截断需求。
- 小时缺货标记为1表示缺货、0表示未标注缺货。`stock_hour6_22_cnt`对应小时6至21，即Python切片`[6:22]`，与[官方基线](https://github.com/Dingdong-Inc/frn-50k-baseline)一致。
- 匿名商品及品类ID不提供商品名称或功能角色。天气字段未明确的单位保持未知。
- 数据是既有经营策略下的观察记录。没有补货动作、库存水平、成本、报废、随机分配或现场测量接口；需要将识别假设、相关关系和因果主张分别说明。
- 保留时间、同店和同商品依赖，不能把每行都视为独立随机实验。缺货时的观测销量不能直接当作完整需求真值。

## 开始研究前

使用准备好的`model.json`和`--data ./inputs/freshretailnet-50k`创建新的项目。`create`只创建快照，`run`才调用模型。研究问题和全角色共享的token、请求、时间及阶段上限应先明确；按[配置说明](CONFIGURATION.zh-CN.md)完成有限运行。

本机安装验收使用回环夹具，不证明Qwen的thinking、工具调用及推理字段已兼容，也不证明真实研究已取得结果。
