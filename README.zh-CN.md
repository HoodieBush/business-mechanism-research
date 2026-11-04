# 商业机制研究系统 0.1.5

你提供业务问题、数据和字段说明，系统自主分析、提出可证伪假说并检验。独立质疑者读取原件、复算并审查假说、实验、结论、记忆和报告；研究者根据证据回应、修订或重测。系统保存认识变化与证据链，产出有适用范围的业务认识，也允许反驳和未决结果。

当前外部数据接口是只读SQLite，支持SQL和Python分析，适用于销售登记、业务计数和运营差异等研究。没有现场测量服务时，系统只研究收到的观察数据，所需新数据会列入报告。

**状态：macOS/Linux研究原型开源快照。** 使用真实LangGraph，提供CLI和同步Python API。工程夹具已走通两个阶段；此前研发版本已有真实模型的假说、独立质疑、回应和修订记录，本开源快照不提供该私有实验数据，也未认证完整正式报告或24小时运行。见[发布状态](RELEASE_STATUS.json)及[证据范围](docs/EVALUATION.md)。

## 系统做什么

```text
业务问题 + 数据 + 字段定义
             ↓
     研究者自主选择下一步 ←─────────────┐
       ↓ 查询/分析/假说/检验           │
     候选判断或报告草稿                │
       ↓                             │
     质疑者独立核验 → 研究者回应/修订 ──┘
       ↓ 当前报告通过核验与发布检查
     本阶段报告 → 沿原档案进入下一阶段

暂停/资源不足 → 保存可读进展和原件，等待续接
```

研究者决定研究什么、是否补证及何时准备报告；LangGraph负责调度和持久化。没有固定算法设计阶段或第三个主管Agent。质疑者有独立上下文和核验工具，研究者可以接受、修订、有依据反驳或明确暂缓意见。

设计细节见[系统介绍](docs/SYSTEM.zh-CN.md)，部署和接入按下面步骤完成。

## 运行条件

| 项目 | 当前要求 |
|---|---|
| 平台 | macOS arm64使用sandbox-exec；Linux使用bubblewrap，Ubuntu24.04 x86_64进入实际CI矩阵 |
| Python | 3.12，使用独立虚拟环境 |
| 依赖 | 锁文件安装需访问包源；wheel不含第三方依赖 |
| 模型 | 支持当前Chat Completions工具协议及thinking字段，详见[配置契约](docs/CONFIGURATION.zh-CN.md) |
| 数据 | SQLite、业务背景、JSON字段字典；包内提供公开合成样例 |

Linux部署需先安装bubblewrap并通过实际命名空间预检，见[Linux部署](docs/LINUX.md)。当前没有Windows原生隔离适配、Web界面或HTTP监听端口。企业可在自己的服务进程中调用Python API；远程接口与鉴权由接入方提供。

## 1. 获取独立源码

```sh
git clone https://github.com/HoodieBush/business-mechanism-research.git
cd business-mechanism-research
```

以下命令都从这个独立项目根目录执行，不要求原开发仓库。

## 2. 安装并检查

Ubuntu24.04先执行`sudo apt-get install bubblewrap python3.12-venv`；macOS使用系统sandbox-exec。其余Python安装步骤共用。

先提供Python 3.12，确认`python3.12 --version`为3.12；也可将第一条命令换成实际Python 3.12解释器的路径。

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested.txt
python -m pip install --no-deps .
python -m pip check
business-research --help
python tools/check_install.py
```

安装检查验证依赖导入和实际沙箱可用性，不调用模型。全新环境的依赖安装与验收结果见[部署验证](DEPLOYMENT_VERIFICATION.md)。

## 3. 先完成不付费的工程验收

```sh
python scripts/check_release.py
python scripts/check_secrets.py --all-files
python tests/isolation.py --output ./acceptance-isolation
python tests/acceptance.py --output ./acceptance-local
```

输出目录必须尚不存在。预期`acceptance-local/result.json`中`status`为`passed`、17项检查为true、`external_provider_calls`为0。测试用本机HTTP夹具驱动实际图、SQLite、沙箱、双角色、两个阶段、报告归档与暂停恢复，无需密钥。这证明部署工程路径，不代表业务研究效果。

## 4. 配置自己的模型和密钥

```sh
cp model.example.json model.json
mkdir -p ~/.config/business-mechanism
chmod 700 ~/.config/business-mechanism
```

编辑`model.json`的`model`和`base_url`，填写自己有权使用的服务。`base_url`是API前缀，例如`https://your-gateway.example/v1`，不要包含`/chat/completions`；示例占位值不能直接调用。

用编辑器将密钥写入`~/.config/business-mechanism/api_key`，然后执行：

```sh
chmod 600 ~/.config/business-mechanism/api_key
```

密钥不写入JSON、命令参数或研究数据。也支持`BUSINESS_RESEARCH_API_KEY`环境变量；它优先于密钥文件，切换密钥时应检查旧环境覆盖。保持thinking开启、high、65,536最大输出，不发送temperature。仅宣称“兼容OpenAI API”的网关未必支持这些字段，请核对[实际模型接口](docs/CONFIGURATION.zh-CN.md)。

## 5. 准备数据

先生成合成样例，再校验实际配置；样例不代表真实企业证据。

```sh
python examples/create_example_data.py --output ./example-inputs
python tools/check_install.py --model-config ./model.json --data ./example-inputs
```

自己的业务输入目录需要：

```text
inputs/
  business.sqlite         # 任意业务表和字段
  business_brief.md       # 问题背景、粒度、来源、时间含义、可用操作
  data_dictionary.json    # 字段含义、单位、计数/缺失定义
```

格式见[示例说明](examples/README.md)。创建项目时快照数据库和说明；更新外部原文件不会自动替换已有项目的研究输入。

## 6. 创建、运行和暂停

`create`只建工作区，不调用模型。`run`开始发送研究输入到所配置的模型服务并产生费用。

```sh
business-research create ./work/P001 \
  --question '研究不同站点登记量与完成量的差异，区分数据支持的认识和仍需补充的证据。' \
  --model-config ./model.json --data ./example-inputs \
  --tokens 2000000 --requests 80 --wall-seconds 7200 --max-stages 2

business-research status ./work/P001
business-research run ./work/P001 --stages 1
```

`run`在当前终端同步阻塞。另一终端激活同一虚拟环境后，可以查看进展或请求协作暂停：

```sh
business-research status ./work/P001
business-research report ./work/P001
business-research pause ./work/P001
```

暂停在当前已付费工具批次执行完后的安全点生效。用原路径、原版本继续：

```sh
business-research run ./work/P001 --resume --stages 1
```

`--stages 1`表示本次最多完成一个研究阶段，`--max-stages 2`是项目总阶段上限。第一阶段有有效正式报告后，再次运行可进入第二阶段，沿用原证据、假说与记忆。

tokens、请求数和时间均是全角色、全阶段共享且重启后保留的上限；项目时间从首次执行开始持续计时，暂停也计入。2M是示例容量，不保证一定完成正式报告。上限耗尽时`--resume`不会自动补额度或重置期限。

CLI退出码：0为命令完成，3为pending/暂停，2为配置或运行错误。科学未决可以是正常报告结论，不能只看退出码评价研究正确性。

## 7. 找到交付物

```text
work/P001/deliveries/
  当前研究报告.md        # 有当前正式报告时为正文，否则是未完成进展
  阶段进展报告.md        # 假说、候选判断、质疑、回应、下一步
  阶段交接.md            # 状态与恢复入口
  latest.json            # 完整版本记录和证据索引
  F....md / F....json     # 每份正式报告独立归档
```

正式报告解释问题、预测、数据/检验、支持或反驳的认识、质疑处置、适用范围和下一步。无正式报告时仍能读到阶段进展，但它不是核验通过的成果。`report`仅重新导出保存原件，不调用模型。

运行中的逐回合进展看`latest.json`；`status.last_execution`是最近结束或暂停的调用，可能落后于当前运行。前阶段正式报告仍保存在`F*.md`。

## 进一步接入

- [系统介绍](docs/SYSTEM.zh-CN.md)：角色、循环、工具、上下文、记忆与交付条件。
- [配置与Python API](docs/CONFIGURATION.zh-CN.md)：模型/数据契约、资源上限、同步服务接口。
- [运维与故障处理](docs/OPERATIONS.zh-CN.md)：退出码、暂停、备份、常见故障。
- [部署验证](DEPLOYMENT_VERIFICATION.md)、[发布状态](RELEASE_STATUS.json)、[修订记录](CHANGELOG.md)。

备份前停止控制器并备份整个项目目录；本版只核验同路径、同版本恢复。本开源快照不含真实业务数据、密钥、历史实验或原项目总账。0.1.4剔除了旧本地包误带的开发期探针记录，详见[来源说明](docs/SOURCE_PROVENANCE.md)。
