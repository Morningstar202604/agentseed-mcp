# AgentSeed —— 技术设计

> AgentSeed 的中文技术设计。另见 [English](./DESIGN.md) · [日本語](./DESIGN.ja.md)。

## 1. 背景与问题

### 1.1 规范是真的，但被夸大了

Agent Plugins **1.0.0** 是 2026 年 8 月发布的真实开放规范，技术指导委员会由
**Amazon、Cursor、Microsoft、OpenAI、Vercel** 各派一名代表组成。两点澄清：

- **谷歌不在委员会名单里。** "六巨头联合发布"是内容农场把"厂商中立标准体"夸大而成。
- 它是**打包标准**，不是产品。它标准化了"包装盒"（`plugin.json`、`skills/`、`mcp.json`），
  但故意留了两个口子。

### 1.2 规范的两个缺口（我们的机会）

1. **没有强制执行机制。** 客户端"可以"加载 skill，但没有任何手段强迫模型在宣称完成前
   真正验证输出。
2. **没有注册表 / 市场 / 分发机制**——分发是开放的；而且尽管规范定义了 MUST/SHOULD，
   **却没有官方 linter**。

### 1.3 市场缺口

| 现有方案 | 做什么 | 缺什么 |
| --- | --- | --- |
| 聊天诚实护栏（行为类 MCP 服务器） | 让聊天回答诚实（别编引用/日期） | 不碰代码、不跑工具 |
| `obra/superpowers` | 纯 prompt 编码工作流 | 无硬核校验 |
| 静态 import 检查器（Rigour 类 MCP） | 按语言检出幻觉 import | 无行为语言扫描、无 skill 工作流 |
| 典型 MCP 服务器 | 给模型暴露一个 API | 没有"校验模型自己产出的代码" |

AgentSeed 填补：**代码级 + 真跑工具 + Skill/MCP 闭环强制**。`check_plugin` 是
1.0.0 的首个 linter。

## 2. 设计目标

- **跨客户端** —— 符合 1.0.0，在支持规范的客户端原生加载。
- **闭环强制** —— 软的 Skill 指令与硬的 MCP 闸门绑死。
- **零依赖** —— 纯标准库 Python，不挑 SDK 版本。
- **抢首发 linter** —— 面向 1.0.0 的 `check_plugin`。

## 3. 架构

```
            ┌─────────────────────────────────────────────┐
            │  编程智能体（Cursor / VS Code / Copilot）     │
            └───────────────┬───────────────┬─────────────┘
                            │ 加载           │ 启动（stdio）
                            ▼                ▼
                 ┌──────────────────┐  ┌──────────────────────────┐
                 │  Skill           │  │  MCP 服务器（agentseed）   │
                 │  verify-before-  │  │  guard_server.py          │
                 │  code（闸门逻辑）│  │    │                      │
                 │                  │  │    ▼                      │
                 └────────┬─────────┘  │  guard_engine.py          │
                          │ 指示       │   ├ detect_undefined_      │
                          │ 模型调用： │  │   │   symbols（AST）      │
                          │            │  │   ├ scan_hallucination_  │
                          │            │  │   │   words（正则）       │
                          │            │  │   └ check_plugin_        │
                          ▼            │       │ conformance（JSON） │
                 ┌──────────────────┐  └──────────────────────────┘
                 │  SDD-CONTRACT     │
                 │  （写码前加载）   │
                 └──────────────────┘

  流程：加载契约 → 实现 → verify_code + scan_hallucination →
        都通过？→ 标记完成。否则修复并重跑。
```

## 4. MCP 接口契约

传输：基于 stdio 的逐行 JSON-RPC 2.0。服务器名 `agentseed`，版本 `0.6.0`，
协议 `2024-11-05`。

| 方法 | 说明 |
| --- | --- |
| `initialize` | 握手，返回 protocolVersion / capabilities / serverInfo |
| `tools/list` | 返回 10 个工具 |
| `tools/call` | 调用 `verify_code` / `resolve_symbol` / `verify_file` / `check_contract` / `check_imports` / `scan_hallucination` / `check_plugin` / `sandbox_run` / `schema_validate` / `record_verification` |

工具签名：见英文版 §4.2。`verify_file` 在已安装时运行项目自带工具链（ruff/pyflakes/mypy/tsc/eslint/go vet/cargo check/javac），否则回退内置分析器，详见 §10.1。

## 5. 关键算法

- **`detect_undefined_symbols`**：多后端——
  - Python（AST）：`ast` 解析，收集已定义名（builtins、导入别名、def/class 名、
    参数），再扫描不在集合内的 `Name`/`Call`。
  - TypeScript/JavaScript（词法）：正则收集导入（具名/默认/命名空间/解构）、
    声明（function/class/interface/type/enum/const/let/var）、函数参数，再标记
    顶层调用与 `new` 表达式中未定义的被调者（成员访问 `obj.foo()` 不标记，
    关键词/全局白名单）。
  - 通用注册表（词法）：**同一引擎、多语言**。每个 `LangSpec`（go/rust/java/
    c/c++/c#/php/ruby/kotlin/swift/dart/lua/r/zig）声明注释/字符串语法、关键字、全局名、
    定义/导入/参数正则与参数名模式。共享引擎屏蔽注释/字符串、收集定义，再标记
    裸调用与 `new` 中未定义的被调者。加语言=加注册条目，无需改引擎；Ruby 的
    无括号调用由 `bare_calls` 标志支持。
  静态检查、不跑运行时；TS 与通用通道是词法而非类型检查——属性调用
  （`obj.m()`、`a::b()`）、宏、跨文件符号不分析；动态/全局引用可能误报，
  解构边界情况可能漏报。
- **`sandbox_run`**：无 shell 子进程执行（超时 1–120 秒、输出截断），可选行为断言
  （expected_exit / expect_output：退出码与输出子串逐项判定，结果附 expectations
  裁决）——"跑过"升级为"跑出预期结果"（CodeHalu 的执行验证）。CDV 通道 A 的落地。
- **`schema_validate`**：零依赖 JSON Schema 子集校验（type/enum/const/minLength/
  maxLength/pattern/minItems/maxItems/items/properties/required/additionalProperties）。
- **`scan_hallucination_words`**：逐行正则词边界扫描**分组信号池（50+ 词）**：
  - `stub_code`：stub/mock/fake/placeholder/dummy/todo/fixme/xxx/tbd/tba/wip/
    "not implemented"/"coming soon"
  - `oversold`：guaranteed/"definitely works"/"all tests pass"/"everything works"/
    "fully tested"/"production ready"/"no bugs"/"works perfectly"/"should work"/
    "trust me"/"works on my machine"/"100% correct"/"bug free"/"zero errors"，
    另含未验证的安全声称（"no vulnerabilities"/"secure by design"/"unhackable"）
    与性能声称（"highly optimized"/"zero downtime"）
  - `fabricated`：simulated/hypothetical/imaginary/invented/fabricated/fictional/
    pretend/"made up"
  - `fabricated_url`：结构化域名检测——占位域名（"api.yourdomain.com"）、被当作
    真实使用的保留 TLD（"myapp.test"）、把 "example" 编进非保留域名
    （"docs.example-fake-api.dev"）；保留的 example.com/net/org/edu 集合不命中
  返回 `hits[]`（word/group/line）、`clean` 与分组计数。
  来源：SFD Lab 五步反幻觉清单第 5 步；CDV（"'done, all tests pass' 是声明不是
  证据"）；reze83 先验证后声称规则。
- **`check_plugin_conformance`**：校验 `plugin.json`（`$schema`=1.0.0 地址、必填
  `name`、合法 JSON）、各 `skills/*/SKILL.md` 是否存在、`mcp.json`（`$schema`、
  `mcpServers`）。返回 `ok` / `errors[]` / `warnings[]`。

## 6. 1.0.0 合规性核对

| 规范章节 | 要求 | AgentSeed |
| --- | --- | --- |
| §5.2 清单 | 根 `plugin.json`，closed schema（仅 `$schema`/`name`/`version`/`description`/`author`/`homepage`/`repository`/`license`/`keywords`/`extensions`） | ✅ |
| §5.3 必填 | `$schema` = 1.0.0 地址；`name` 必填 | ✅ |
| §5.5 命名 | 1–64 字符，`[a-z0-9.-]`，首尾字母数字，无 `--`/`..` | ✅ |
| §5.4 元数据 | `repository`/`homepage`/`license` 为字符串；`author` 仅限 `name`/`email`/`url` | ✅ |
| §6.1/§7.1 技能 | `skills/<name>/SKILL.md`；Agent Skills frontmatter（name 匹配目录、description ≤1024） | ✅ |
| §7.2 mcp.json | 仅 `$schema` + `mcpServers`；stdio 服务器含 `command`，`cwd` = `${PLUGIN_ROOT}` | ✅ |
| §8 发现 | 客户端读取清单+技能+mcp | ✅（设计如此） |
| §11 linter | （规范无） | ✅ `check_plugin` 严格 1.0.0 linter |

## 7. 竞品对比

| | 纯 prompt 技能（superpowers…） | 静态 import 检查器 | **AgentSeed** |
| --- | --- | --- | --- |
| 碰代码 | ❌ | ✅ import 图 | ✅ AST + 词法 |
| 跑工具 | ❌ | lint 门禁 | ✅ 10 个 MCP 工具含沙箱 |
| 强制 | 软 | CI 门禁 | **硬闸门** |
| 1.0.0 linter | ❌ | ❌ | ✅ |

## 8. 风险与明确的非目标

风险：

- 静态作用域分析 → 对动态/属性访问可能漏报。
- 规范很新（2026-08），客户端 adoption 与 schema 可能变动。
- 强制依赖客户端是否真正遵守 skill 的闸门指令；硬层是 CI 中的
  `guard_cli gate`。

明确的非目标（写清楚，免得被当成 bug）：

- **语义正确性**：能跑但逻辑错的代码不在范围内——插件层没有运行时真值。
- **属性调用验证**（`obj.missing_method()`）：需要跨文件类型推断，属已声明的漏报类别。
- **跨文件符号解析**：分析按设计是单文件的（零依赖、O(source)）。
- **完整沙箱隔离**：`sandbox_run` 是带树杀与可选环境清洗的确定性执行通道，
  不是容器。

## 9. 构建与测试

```bash
python3 server/guard_engine.py                 # 自测 + 演示
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' \
            '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 server/guard_server.py
```

## 10. 适配器、门禁分级、证据凭据与插件工具链

### 10.1 工具链验证适配器（`engine/verifiers.py`）

注册表证明"廉价且广"；适配器证明"关键处深"。一个 `VerifierSpec`
（名称、语言、二进制、固定参数、解析器）通过 `sandbox_run` 运行项目自带的
工具链——无 shell、输出封顶、超时、进程树终结——并只提取未定义符号类
（F821 / TS2304 / `undefined:` / E0425 / no-undef），归一化为内置分析器
相同的 `suspects` 形状。策略：

- `auto` = 第一个已安装的适配器，否则回退内置分析器（在 note 中说明）；
  显式指定的适配器缺失或运行失败时大声报错，绝不静默降级——把坏掉的
  适配器解析成"干净"正是本项目要消灭的假绿。
- 适配器二进制经 PATH 解析为绝对路径；`sandbox_allowed_prefixes`
  有意不约束适配器（调用 AgentSeed 本身就意味着运行项目声明的工具链）。
- 新增适配器 = 一个 `VerifierSpec` 条目 + 一个解析函数。

### 10.2 Hook 门禁分级（`guard_hook.py`）

词法扫描器的误报必须永远不能拦截正常工作——一个狼来了的门禁会被关闭，
被关闭的门禁什么也管不了。因此 hook 给自己的权力分级：

| 分级 | 阻断 | 理由 |
| --- | --- | --- |
| `advisory`（默认） | 从不 | 证据与可见性；零打断 |
| `diff` | 仅当 `group\|word` 计数或嫌疑符号相对文件原有磁盘内容**新增** | hook 层的 `scan --baseline` 等价物 |
| `strict` | 任何 error 级命中或嫌疑符号 | 0.4 之前的行为，显式开启 |

裁决中的 `blocking` 字段是分级的决定而非原始扫描结果；`status` 取值
`pass` / `flagged` / `blocked` / `skipped`。

### 10.3 验证覆盖率（`engine/audit.py`）

凭据冻结的是你声称验证过的东西；覆盖率指名你改了却从未验证的文件——
自我认知幻觉类。gate 的覆盖率阶段用 `git status --porcelain` 对照
`record_verification(files=...)` 记录过的文件并列出缺口。默认只报告、
`--coverage-strict` 才阻断；非 git 工作树降级为诚实的“无法计算”，
绝不假绿。

### 10.4 证据凭据（`engine/receipt.py`）

凭据把一个已完成任务的验证状态冻结下来：检查项（工具 + 结论）、每个被
验证文件的 SHA256 与大小、agentseed/python/平台版本，以及凭据文件自身的
摘要——重新哈希即可发现任何后续篡改。审计日志追加一行与之关联。被点名的
文件不存在时整个凭据大声失败。这是完成报告引用的工件，而不是散文。

### 10.5 插件工具链（`guard_cli plugin …`）

`init` 生成最小插件脚手架，随后用真实的合规检查器自检，不能通过则删除
整棵树（过不了自家 linter 的脚手架不配留在磁盘上）；`validate` 重跑
linter；`pack` 构建确定性 zip（跳过规则与发布打包器共享，经
`engine/artifact.py`，回退常量由漂移测试钉住）；`doctor` 报告解释器、
可选依赖、适配器在位情况、配置告警、真实 MCP 握手（tools/list 数）与
合规结论。

## 11. 项目符号索引（`engine/index.py`）

单文件作用域分析诚实但对项目视而不见。索引让内置分析器获得跨文件判定，
而无需类型检查器：

- 符号收集复用 `defined_symbols` 背后的逐语言收集器——没有第二套解析器可漂移。
- 条目按文件缓存在 `<root>/.agentseed/index.json`，以内容哈希为键；未变动的
  文件永不重扫，大仓库的 gate 也在秒级。
- 差分判定：索引中存在的嫌疑被重分类为 `missing_imports`（定义在别处、本文件
  未导入——真实缺陷，修复方式不同，列出定义文件）；索引中不存在的嫌疑仍是
  `suspects`，并从全项目符号池给出"你是不是想用"建议。
- 两类判定都拦截；`verify_file`（builtin 路径）、`guard_cli verify`、`gate`
  的符号阶段都会查询；配置 `project_index: false` 关闭；检测不到项目根时行为
  与 0.3.x 的单文件分析完全一致。
