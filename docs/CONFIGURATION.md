# Configuration and Python API

[中文](CONFIGURATION.zh-CN.md)

## Model service

Copy model.example.json and replace the placeholders with your model ID and API prefix.

| Field | Meaning |
|---|---|
| model | Actual provider deployment ID |
| base_url | API prefix; the program appends /chat/completions |
| api_key_file | Credential file outside the checkout/workspace; supports ~ |
| api_key_env | Environment variable taking priority over the file |
| requires_api_key | Explicitly fail when a key is missing |
| request_timeout_seconds | Per-request timeout; example600 seconds |
| bypass_proxy | true bypasses system proxies; false uses environment proxy settings |
| generation_options | Required thinking/high/max_tokens fields |

The tested protocol is DeepSeek-style thinking with native tools: Chat Completions messages/tools and automatic selection; thinking enabled, reasoning_effort high and max_tokens65536; native tool-call IDs/names/JSON arguments and preserved reasoning_content. The service also needs sufficient context capacity. Usage metadata enables accurate execution accounting; missing usage retains conservative unknown reservations and may pause early.

Generic OpenAI compatibility does not guarantee this entire contract. Other models/gateways require adaptation and validation. The preflight sends no network requests, so it cannot establish live service compatibility. Do not silently lower capacity when claiming the same experimental conditions.

Ordinary deployment does not need token_budget_pointer. That field belongs to the original development experiment ledger; do not copy its private paths or budgets.

## Input contract

Provide a real business.sqlite file, a nonempty business_brief.md and a JSON data_dictionary.json. Explain the business goal, row grain, source, units, time semantics and available measurements. Example dictionary:

```json
{"tables":{"service_windows":{"columns":{
  "window_id":"Unique record ID; not necessarily chronological",
  "site":"Site label",
  "completed_orders":"Completed orders, unit: orders",
  "registered_orders":"Registration-system count, unit: orders"
}}}}
```

Table/column names are arbitrary. The program observes the actual schema and preserves supplied field definitions; it cannot invent missing business semantics. Input files must be regular files, not symlinks. Creation takes a snapshot; editing the external input directory does not update an existing project.

## Finite execution controls

| CLI | Python | Meaning |
|---|---|---|
| --tokens | limits.token_allowance | Shared capacity, including unknown reservations |
| --requests | limits.max_http_attempts | Shared HTTP attempts, including failures/retries |
| --wall-seconds | wall_seconds | Persistent deadline starting when the controller first opens; pause does not freeze it |
| --max-stages | max_stages | Maximum completed stages in the project |
| run --stages | run_project(stages=...) | Maximum stages advanced in this invocation |

The output ceiling65536 differs from total project capacity. Conservative whole-request admission may reject a request even when its eventual actual consumption would fit. Restarting does not reset limits; automatic enlargement is not implemented.

## API example

```python
import json
from business_mechanism import create_project, run_project, project_status
from business_mechanism.service import request_pause

with open("model.json", encoding="utf-8") as stream:
    model = json.load(stream)

create_project(
    "./work/P002",  # must not exist; creation sends no model request
    "Investigate registered/completed order differences and missing evidence.",
    model, data="./inputs",
    limits={"token_allowance": 2000000, "max_http_attempts": 80},
    wall_seconds=7200, max_stages=2,
)
result = run_project("./work/P002", stages=1)  # blocking, provider charges apply
print(result)
print(project_status("./work/P002"))

# Another control thread/process can request cooperative pause:
# request_pause("./work/P002", reason="operator request")
# result = run_project("./work/P002", stages=1, resume=True)
```

An enterprise service should place blocking calls in its own background executor and isolate projects in separate directories. One controller owns a project at a time. This package does not start an HTTP server, user system or remote task queue. Pause drains the current paid tool batch first.

completed is an execution outcome; pending preserves work. Inspect reason, delivered content and current report as well. Neither API success nor report existence proves scientific correctness.
