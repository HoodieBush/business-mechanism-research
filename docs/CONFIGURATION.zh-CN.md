# 配置与Python API

## 模型

复制`model.example.json`，替换模型ID和API前缀。示例占位值不能用于真实运行。

| 字段 | 含义 |
|---|---|
| model | 服务商实际部署的模型ID |
| base_url | 程序追加`/chat/completions`的API前缀，不是完整请求路径 |
| api_key_file | 包和工作区之外的密钥文件，支持`~` |
| api_key_env | 优先读取的环境变量名，有值时覆盖文件 |
| requires_api_key | true时缺凭据明确报错 |
| request_timeout_seconds | 单次请求超时，示例600秒 |
| bypass_proxy | true绕过系统代理；需通过环境代理联网时设false |
| generation_options | 由服务端支持的thinking/high/max_tokens等字段 |

当前验收采用DeepSeek风格thinking工具协议，网关必须支持：原生Chat Completions消息、`tools`和自动工具选择；`thinking:{"type":"enabled"}`、`reasoning_effort:"high"`、`max_tokens:65536`及足够上下文；响应的`choices[].message.tool_calls`、JSON参数和推理字段`reasoning_content`。最好返回`usage`；缺失时保留保守未知预留，可能提前暂停。

只宣称“兼容OpenAI API”不自动满足这些条件。其他模型/网关需先适配和验证，安装检查不会发送请求或证明服务兼容性。不要将示例的完整容量、角色参数静默降低后算作同条件实验。

普通部署无需`token_budget_pointer`；它仅用于原项目实验总账，不要复制原仓库的绝对路径和账本。输入会在真实run时发送到配置的模型服务。

## 数据

提供真正的SQLite文件`business.sqlite`、`business_brief.md`和`data_dictionary.json`。业务说明需解释目的、行粒度、来源、时间含义及可用测量；字典结构：

```json
{"tables":{"service_windows":{"columns":{
  "window_id":"唯一编号，不代表时间顺序",
  "site":"站点标签",
  "completed_orders":"完成订单数，单位：单",
  "registered_orders":"登记系统订单数，单位：单"
}}}}
```

表/字段可自行命名。程序观察实际schema并保留数据方解释，不自动补业务含义。输入文件不能是符号链接；创建时快照，续接不自动刷新外部输入。包内示例见`examples/README.md`。

## 执行上限

| CLI | Python | 含义 |
|---|---|---|
| --tokens | limits.token_allowance | 全角色、全阶段共享容量，含未知预留 |
| --requests | limits.max_http_attempts | 共享HTTP请求数，含失败/重试 |
| --wall-seconds | wall_seconds | 首次执行开始的持久期限，暂停仍计时 |
| --max-stages | max_stages | 项目总阶段上限 |
| run --stages | run_project(stages=...) | 本次最多推进的阶段数 |

最大输出65,536与总token容量不同。发送前为完整请求保守准入，余额仍可能不足以开始下一次请求。重启不清零，上限耗尽时本版没有自动扩容命令。

## Python接入

```python
import json
from business_mechanism import create_project, run_project, project_status
from business_mechanism.service import request_pause

with open("model.json", encoding="utf-8") as stream:
    model = json.load(stream)

create_project(
    "./work/P002",  # 必须尚不存在；创建不会调用模型
    "研究登记与完成订单差异，解释适用范围及尚缺证据。",
    model, data="./inputs",
    limits={"token_allowance": 2000000, "max_http_attempts": 80},
    wall_seconds=7200, max_stages=2,
)
result = run_project("./work/P002", stages=1)  # 同步阻塞并调用模型
print(result)
print(project_status("./work/P002"))

# 另一控制线程/进程可协作暂停：
# request_pause("./work/P002", reason="operator request")
# result = run_project("./work/P002", stages=1, resume=True)
```

企业服务应将阻塞研究调用放入自己的后台任务执行器，不同课题使用不同目录；同项目仅一个控制器。本包没有HTTP监听、用户管理和远程任务队列。暂停不取消当前HTTP，会在已付费工具批次执行完后生效。

API的completed是执行结果，pending有保留现场。结合reason、交付内容和正式报告判断进度，不以调用成功代替科学正确性。
