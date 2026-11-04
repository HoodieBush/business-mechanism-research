# System design

[中文](SYSTEM.zh-CN.md)

The system turns a business question into an inspectable research trail: observations, competing explanations, falsifiable predictions, tests, assessments, independent criticism, responses, revisions, and stage reports. A negative or inconclusive finding is legitimate; algorithm improvement and profit are not required outputs.

## Roles and information boundaries

| Component | Responsibility | Information |
|---|---|---|
| Researcher | Choose the next question or action; analyze, hypothesize, test, assess, respond, revise, and prepare reports | Lawful business inputs, its owned process history, hypotheses/memory, and received review/evidence |
| Independent critic | Inspect hypotheses, experiments, assessments, memory and reports; read originals and query/recompute independently | Task input snapshots, relevant original research records, and received prior reviews/actions; not the researcher's private reasoning conversation |
| LangGraph controller | Route work, persist checkpoints, check object/reference/version consistency, enforce finite execution limits, and export delivery | Current objects and execution state; no third scientific adjudicator |

Criticism must have evidence or a logical basis. The researcher may accept, revise, rebut with evidence, or explicitly defer it. Observation, computation and conjecture are distinguished. A review does not automatically become factual memory.

## Research loop

The actual StateGraph has select, researcher, critic, deliver and pause nodes. A role node makes at most one new model request, drains its tool batch, and returns to scheduling. Research direction remains the researcher's decision; a hypothesis can require multiple tests or a changed explanation.

Important judgments trigger independent review. Issues bind to affected objects, versions and evidence. The researcher records both a response and any real replacement objects. Accepting criticism of a report requires a revised successor draft; merely replying cannot publish the old text.

The researcher has16 native tools covering SQL/Python, hypotheses/tests, assessment, state/memory, retrieval/original reading, response and report. The critic has7 tools covering retrieval, original reading, independent SQL/Python, process and review submission. Full schemas and submission examples are included in role prompts.

Directed re-review can reuse an active action explicitly listed in the received parent review. The program checks source and public-input versions and labels it as old computation, not a new independent check. Statistical applicability still requires scientific judgment.

## Data and isolation

The current business SQLite adapter is observational. Running an analysis is not new data collection; repeated computation on the same table is not independent confirmation. If no measurement/intervention service is installed, the report must say what new evidence would be needed.

Python executes under actual macOS sandbox-exec or Linux bubblewrap restrictions. The worker is denied access to private engine source, credentials and network resources. Source reads and computation artifacts remain traceable. Unsupported platforms do not silently run without isolation.

## Context and memory

Active context contains role/tool instructions, current structured research state, relevant hypotheses/predictions/counterevidence, recent turns and original-record entry points. Large tables are processed with SQL/Python rather than accumulated as conversation text.

Complete native messages, reasoning and tool receipts remain in the owning role's archive. Context can be rebuilt from saved owned work. Hypothesis cards, memories and old records are retrievable; withdrawals and replacements preserve provenance. Strong factual memory requires appropriate supporting records, not just critic approval.

Persistence and recall are implemented. Long-term research growth from memory is not established by this release.

## Stages and delivery

A current draft must pass version-bound review and publication checks before a formal report is archived. Reports may support, refute or leave a hypothesis unresolved. The next stage keeps the existing research history; an old draft cannot be republished as new work.

Pause, failure or insufficient capacity produces a readable progress export and recovery entry point. This is deterministic rendering of saved records, not program-authored scientific prose. All stages and roles share project limits. Two real-model completed stages and day-long operation remain unaccepted.
