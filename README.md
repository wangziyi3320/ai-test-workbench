# TraceLab：AI 测试与缺陷工作台

一个可以本地运行的需求到测试证据工作台：导入需求或 OpenAPI JSON，生成用例草稿，人工编辑和审核，导出 CSV/Postman，再记录关联缺陷。适合作为测试开发与 AI 应用开发作品集项目。

> 仓库中的短链需求和接口文档都是虚构示例，与任何企业内部系统无关。

## 功能与技术

- **需求管理**：粘贴需求，或上传 UTF-8 TXT、Markdown、OpenAPI JSON；原文存入 SQLite。
- **两种生成模式**：离线规则模式可复现且不需要密钥；模型 API 模式调用兼容 OpenAI Chat Completions 的真实服务，返回结构化草稿。
- **需求追踪与人工审核**：每条用例保留 `source_ref`，默认 `draft`；人工修改步骤、预期和优先级后可审核通过或弃用。
- **导出**：仅导出已审核通过的用例；CSV 可用于用例归档，Postman Collection 带状态码断言。
- **本机接口执行**：对审核通过、信息完整的 GET 用例执行状态码检查，记录通过/失败、实际状态和耗时。
- **缺陷管理**：缺陷关联需求及用例，记录复现步骤、预期、实际、严重程度和状态。
- **技术栈**：Python、FastAPI、Pydantic、SQLite、原生 HTML/CSS/JavaScript、Pytest。

代码结构：

```text
app/
  db.py            SQLite 表结构与连接（包括执行记录）
  generation.py    OpenAPI/文本离线生成与可选模型适配器
  main.py          HTTP API、导出和页面入口
static/            响应式网页
sample_data/       虚构的 OpenAPI JSON
docs/              PRD、验收标准、演示脚本
tests/             完整业务链路测试
```

## 快速运行

要求 Python 3.10+。在仓库根目录执行：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

打开 <http://127.0.0.1:8766>。接口文档位于 <http://127.0.0.1:8766/docs>。默认使用离线规则模式，不需要 API Key。

macOS/Linux 可将 Python 命令替换成 `python3`、虚拟环境解释器替换成 `.venv/bin/python`。

### 接入真实模型 API（可选）

在启动服务的同一个 PowerShell 窗口设置环境变量：

```powershell
$env:LLM_BASE_URL = "https://api.deepseek.com/v1"
$env:LLM_MODEL = "deepseek-chat"
$env:LLM_API_KEY = "填入自己的密钥"
```

然后重新启动服务，在页面选择“模型 API 模式”。适配器使用 Chat Completions 接口，请求 JSON 结构化草稿并校验来源；不保存密钥，也不会把密钥写入数据库。远程模型可能收费，且文档内容会发送至对应服务。**请先脱敏**。单次模型生成限制 20,000 字符，超限会提示拆分文档；离线模式仍可使用。`.env.example` 只是配置示例，不会自动加载。

| 模式 | 实际行为 | 适用场景 |
|---|---|---|
| 离线规则 | 对文字需求按行拆分，识别简单数值范围；OpenAPI 根据路径、方法、响应码、必填项创建草稿 | 无网络演示、基础覆盖梳理 |
| 模型 API | 请求用户配置的兼容 Chat Completions 服务；校验 JSON 结构及部分来源字段 | 复杂需求的初稿辅助 |
| 自动选择 | 配置完整模型环境变量时选模型，否则选离线规则 | 日常使用 |

两种模式的输出都**只是待审核草稿**。未写明的预期结果会提示人工补充；模型仍可能产生不准确的测试步骤。

## 复现演示

1. 首页点击“载入示例”并保存。
2. 选择离线规则模式，点击“生成用例草稿”，可看到正常、异常及边界用例。
3. 打开用例，补全可观察的步骤/预期，改为“审核通过”。
4. 导出 CSV；未通过的用例不会出现。
5. 导入 [`sample_data/short_link_openapi.json`](sample_data/short_link_openapi.json)，审核通过一条接口用例后导出 Postman Collection。
6. 在缺陷区填写复现步骤、预期与实际，关联一条用例并更新状态。
7. 另导入 [`sample_data/local_health_openapi.json`](sample_data/local_health_openapi.json)，生成并审核 GET `/api/health` 用例；在“本机接口执行”中填当前服务地址（默认是当前网页地址），点击用例的“本机执行”，查看 HTTP 200 和耗时记录。

完整录屏脚本见 [`docs/DEMO.md`](docs/DEMO.md)，需求和验收标准见 [`docs/PRD.md`](docs/PRD.md)。

### Postman 导出的限制

导出集合只提供 `{{base_url}}`、方法、路径和已审核的 HTTP 状态码断言。真实接口调用前，仍要在 Postman 中填写请求参数、Body、Header 和鉴权；部分路径参数也需手动替换。只有文档声明或人工补充且审核通过的状态码会进入断言。**导出成功不代表接口测试已通过。**

### 内置执行器的边界

执行器只接受 `localhost` 或 `127.0.0.1` 的 HTTP 服务地址，只运行审核通过的 GET 用例；请求体、请求头、授权和路径占位符需使用 Postman 或其他专业测试工具。它不使用系统代理，也不跟随重定向。每次执行会在本地 SQLite 留下实际状态、通过/失败、耗时和错误信息。运行前请确认目标是你有权测试的本机服务；不要将工作台公开部署，因为当前没有账号认证。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

测试覆盖需求创建、边界草稿、重复生成、人工审核与 CSV 安全导出、OpenAPI 上传与 Postman 导出、缺陷关联校验、上传大小限制、模拟兼容模型 API 的结构化输出校验，以及本机接口执行的通过、失败、重定向和目标限制。当前本地运行结果：`5 passed`。真实模型输出质量与实际业务接口执行效果尚未测量，因此不在简历中填报准确率或效率提升数字。

## 数据与安全边界

- 默认服务只监听 `127.0.0.1`；没有用户认证，不能直接开放公网。
- 数据库存于 `data/workbench.db`，被 `.gitignore` 忽略。上传文档上限 200 KB；只接收 UTF-8 文本、Markdown、JSON。
- 页面把文档和模型输出作为文本显示，避免 HTML 注入；CSV 对可能被表格软件解释成公式的单元格加前缀。
- 模型模式会把需求发送到你配置的服务；仅使用脱敏素材。不要将密钥提交到 Git。
- OpenAPI 暂不支持 YAML 或 `$ref` 展开；参数和鉴权须人工补足。

## 简历表述建议

“独立开发基于 FastAPI + SQLite 的 AI 测试与缺陷工作台，支持需求/OpenAPI 导入、离线规则或可配置大模型生成测试用例草稿、来源追踪和人工审核；实现 CSV/Postman 导出、本机 GET 接口状态码执行记录与关联缺陷管理，并编写端到端 API 测试。”

这段只描述仓库已经实现的能力；模型效果、真实项目缺陷数和效率数据需要另行实测。
