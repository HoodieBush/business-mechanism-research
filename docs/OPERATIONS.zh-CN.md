# 运维与故障处理

## 暂停和续接

```sh
business-research pause ./work/P001
business-research status ./work/P001
business-research run ./work/P001 --resume --stages 1
```

暂停在安全点生效，当前请求可能等待到超时。主线程收到SIGTERM时也请求协作暂停；强制终止可能留下未知用量，恢复保留其预留，不保证避免重复付费。resume清除操作员暂停，不增加容量/请求或重置期限。

项目时间从首次执行开始计时，暂停仍消耗期限。请求、容量、阶段、时间及无进展保护都可能停止运行；不是所有pending仅靠resume可解。上限耗尽须显式新分配/迁移，本版无受支持的自动扩容命令。

## 文件和备份

project.json保存配置和源身份；researcher/保存科学数据库、过程和记忆；reviews/保存核验快照及过程；两份graph_*.sqlite保存图检查点及节点操作；common_budget.sqlite保存跨角色执行容量、费用预留与请求历史；deliveries/保存进展和正式报告。

控制器停止、数据库连接关闭后备份**整个项目目录**。当前核验同绝对路径、同包版本恢复。不要只复制一份图SQLite、删原生过程或修改源身份绕过检查。跨路径/跨版本可能涉及嵌入引用和源哈希，本版没有通用迁移工具，需独立副本验证。

## 退出码和故障

退出码0表示命令完成，2表示错误，3表示pending。科学未决可以是正常报告结论。

| 现象 | 处理 |
|---|---|
| python3.12找不到 | 提供Python 3.12，或用实际解释器路径创建venv |
| business-research找不到 | 激活对应venv，确认`python -m pip show business-mechanism-research` |
| 依赖版本不可用/安装失败 | 检查包源与网络，保留错误；不要跳过依赖安装，参见部署验证 |
| NumPy/SciPy导入失败 | 新建Python3.12环境按锁安装，再执行pip check和check_install |
| credential missing/401/403 | 检查文件权限、模型权限和环境变量覆盖；不要打印密钥排错 |
| 400、thinking/max_tokens不支持 | 网关协议不匹配，按配置文档确认服务能力或另行适配 |
| timeout/502/429 | 系统有界退避；暂停后检查reason和回执，避免盲目反复重跑 |
| 代理/TLS错误 | 核对bypass_proxy、证书和网络，不关闭TLS验证 |
| sandbox不可用 | 运行check_install；不支持的平台不能直接无隔离部署 |
| Project already exists | 原工作区用原版本续接，新课题使用新目录，不重建清零 |
| another service controller | 同项目已有持锁进程，先检查原任务 |
| Source version differs | 用原包恢复；升级需显式迁移，不改project.json绕过 |
| shared admission不够 | 完整请求预约高于余额，是执行暂停，保存现场和交付 |
| 时间/无进展限制 | 检查reason和状态；resume不会重置上限 |
| 没有F*.md | 正式核验/修订未完，查看阶段进展和待回应项 |
| 新阶段不显示旧正文 | 前阶段F*.md仍在归档，当前文件显示当前阶段 |

运行中的逐回合进展看deliveries/latest.json；status.last_execution是最近结束/暂停的调用，可能落后。创建时就有交接文件，“文件存在”不代表研究成果已完成。

真实run会将研究输入发给配置的服务，接入方需选择有权使用的数据和模型服务。包内无真实凭据和公司数据。当前是本地组件，尚无Windows原生适配、远程鉴权或24小时可靠性承诺。
