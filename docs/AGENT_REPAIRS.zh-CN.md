# v0 执行、复核与恢复接口

这些接口保留原始科学记录、付费响应、反证和累计消耗。升级必须使用显式副本迁移。当前已知边界见[评价范围](EVALUATION.md)。

## 前置契约、修复与阶段出口

业务主张必须在request_review之前register_analysis_spec，绑定真实数据文件和Python/SQL源码文件。get_claim_readiness读取任意对象的准确要求；新审查快照冻结对应review_contract。critic使用get_review_contract读取实际计算动作与可用JSON pointer，使用validate_review_submission本地预检。consistent的complete缺少覆盖时拒绝并保留草稿；无法核验时如实insufficient_evidence并声明未查项。

close_research_stage(outcome=unresolved/blocked, reason, unresolved_refs, evidence_refs)结束当前阶段，返回stage_closed及独立交接产物，不创建正式报告或clearance。须独自调用且排空付费工具、传输和计算；完整正式阶段不能改成未决。已有草稿不能靠重复finish复制，明确的受审修订受lineage上限约束。相同证据下4次交付尝试产生阻塞交接；16次无计算内容/契约准备/覆盖改善，或3次相同证据的阶段交接，触发语义停滞保护。

跨阶段精确归档旧活动窗口，保留所有原预测、反证与费用；新阶段以新任务视图开始。旧阻塞主张不会妨碍独立新主张的报告，但原主张及其依赖的科学保护仍保留。

操作方可对暂停项目调用close_project_stage(..., event_id=...)登记已确认的阻塞交接；该操作须取得运行锁，不增加费用/授权、不赋予科学结论。监督器续跑使用--resume-first --deadline-unix ORIGINAL_DEADLINE --continuation-of OLD_OUTPUT，分别记录累计与本段新增消耗。

## 批量只读SQL

两角色获得相同数据任务工具：

1. `get_data_profile()`取得实际表/列/索引、snapshot_ref和资源profile。
2. `start_data_job(snapshot_ref, sql, parameters, resource_profile)`创建持久任务。SQL值使用参数绑定。
3. 运行时在下一模型请求前执行队列；不需要消耗模型请求轮询worker。
4. `get_data_job(job_ref)`读取精简状态和回执；`read_data_result(result_ref, cursor, limit)`读取小型结果页和SQLite产物引用。大行/大结果在隔离Python中分析。
5. `cancel_data_job(job_ref)`取消；`retry_data_job(job_ref)`明确新建attempt重跑原SQL，保留失败部分产物。

默认interactive为30秒/512MiB内存/64MiB输出及临时文件；batch为600秒/1GiB内存/512MiB输出及临时文件。实际执行还受原项目剩余墙钟时间约束。输入、网络和私有源代码仍受原OS隔离保护。限制是执行保护，不能据超限声称科学否证。

SQLite完整执行GROUP BY、AVG、DISTINCT、排序、窗口与JOIN；fetchmany只分批写出结果，不改变SQL计算。已完成结果的游标可恢复；通用SQL内部计算不支持断点续算。显式可分区/可合并计划尚未安装。未完成任务只有incomplete覆盖，不会产生完整result_ref。

`query_data`仍保留约一千万SQLite VM步骤和十万输出行的小查询限制；超限给出类型化错误及批量路径。VM步骤不是扫描输入行数。profile的实际行数须由COUNT任务取得，不估造视图展开行数。

## 原始审查草稿

非法record_review参数保存在该critic私有草稿库，原付费响应仍保留；本批次不会执行部分工具。`repair_packet`在下一请求固定显示草稿入口和精确字段错误。

- `save_review_draft(raw_arguments)`保留原字符串，包括非法JSON。
- `read_review_draft(draft_ref)`读取原稿、错误、目标版本和显式修改历史。
- `patch_review_draft(draft_ref, expected_hash, field_changes)`执行JSON pointer字段操作；每项为`{op: set/remove, path: /issues/0/affected_refs, value: ...}`。旧hash或旧head被拒绝。
- `commit_review(draft_ref, expected_hash)`重新验证并提交，必须独自调用；重复提交返回同一实际审查回执。

程序不自动删除未知科学文本、不补affected_refs、不删除问题或改blocking。无效JSON不能做结构patch时，角色可以保存明确修正后的新草稿，旧原文仍保留。语法通过、审查结束、科学主张获覆盖是不同状态。

## 额度与调度

新项目默认每个review的正常片段10次请求，另有3次有界修复储备。储备仅在存在未提交草稿时开放，期间工具集中到草稿/引用读取和提交。累计请求、共享token、未知用量预留、截止和无进展保护不重置。

局部审查额度耗尽会登记blocked_execution；真正尚待交付的付费批次先排空，之后其他独立工作可继续。阻塞主张不获得clearance。仍依赖该主张的正式报告可能保持未决，这不是假完成。

可通过Python API在原授权内显式、幂等地追加局部片段：

```python
from business_mechanism import allocate_review_requests
allocation = allocate_review_requests(
    project_path, job_ref, 3,
    event_id="repair-continuation-001", reason="继续修复已保留的审查草稿")
```

此操作只调整局部片段，不增加项目共享请求/token总量，不延长原截止；重复event_id不会重复增加分配。event内容改变会被拒绝。

## 科学覆盖门槛

record_review增加`coverage_checks`：component、真实action_ref、计算输出的JSON pointer、relation和expected。程序从实际回执读取数值/对象验证断言；只读原件或检查row_count不能充当完整估计方法的核验。

研究者可在定向快照生成前用`register_analysis_spec(target_ref, spec)`固定数据、过滤、抽样、实体、分组、变换、估计器、不确定性和代码引用。旧目标不能改绑不同spec。business类主张必须有spec，并覆盖data_scope、sampling、grouping、transformation、estimator和numeric_claim。缺失覆盖时保留complete审查，撤除其操作clearance，不改写原结论。

这是结构和实际输出一致性约束，不能认证任意Python程序或因果推理。已加入“原始x先展开x²，再对完整实体分别去均值”的参考函数、周期ROWID抽样日期覆盖与反向数值叙述反例测试；参考函数目前用于工程验证，不是强制替代Agent任意分析的执行器。

## 副本迁移

```python
from business_mechanism import migrate_project_copy
receipt = migrate_project_copy(
    old_project_path, new_project_path,
    baseline_package=old_installed_business_mechanism_directory,
    event_id="upgrade-001")
```

迁移要求提供与旧project逐文件哈希匹配的旧安装包，且两版本engine_manifest完全一致。项目必须暂停、付费工具已排空、传输已确认；不支持外部符号链接或跨引擎升级。迁移取得运行锁，复制到新目录，归档旧源码和每份旧身份，明确登记新工具契约与源身份；科学records、预算行、未知预留和原截止逐项保留。旧clearance须经过新覆盖门槛重核。

新副本默认暂停，不发送模型请求；原项目及其安装环境保留。失败副本带migration_incomplete围栏，不能继续研究。历史原文中的绝对路径保留归属，当前计算路径应由文件ref重新读取。该功能的夹具覆盖旧版草稿和费用保留；每次真实升级仍须对实际前序副本执行部署检查。


## 收敛与恢复

新增get_research_agenda、focus_hypothesis、set_hypothesis_goal、close_hypothesis；最多3个active，backlog提案和已终结对象仍可回读。接受/反驳需相符的clearance，未决/放弃不是否证。目标在计划前固定，范围缩小用新H。

AnalysisSpec支持claim_level和sampling_mode，按实际适用方法验收。revise_analysis_spec只允许冻结审查输入前的显式CAS修订。read_review_draft通过section/offset/limit分页。审查最后2轮开始收尾；可如实complete+insufficient_evidence。

工具引用错误是持久反馈；精确上下文可归档后按页回读。worker使用文件捕获、流式哈希和有限资源，输出超限明确未完成。recover_execution只对已排空的登记停点进行有限任务轮换；authorize_window必须来自明确的新有限授权。费用、原意见、无进展计数和反证保持。


## 方法证据与数字复算

CoverageCheck支持basis=source_inspected，仅用于方法组件；绑定实际.py/.sql读取动作、/text contains的精确片段和justification，不能替代数字复算。联合重算可提供实际执行代码中的method_fragment及逐组件解释，不能只重贴标签。阶段切换先完成活跃H，不强迫另开课题。已核验findings的发布审查可在本job有限轮次内收尾，不能绕过原截止、局部轮数或未核验主张保护。


## 验证任务与诚实交付

request_revalidation对完整但覆盖不足的旧审查发起有界同目标复核，保留原意见/阈值；活动视图和调度器优先完成可修复验证。新有效审查以事件更新目标终点，旧未决理由保存在endpoint_history。无已核验findings的报告使用inspect_report_disclosure和record_fidelity审查，不给H/A科学clearance。已交付范围不重复发布；实际数据计数、有限验证/收尾与真实交付后的工作窗口分别登记。
