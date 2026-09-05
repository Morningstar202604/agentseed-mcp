<div align="center">

<img src="docs/logo.png" width="96" alt="AgentSeed logo">

# AgentSeed

**AI 编码智能体的反幻觉闸门。**

AI 会编造不存在的 API，会不跑任何测试就说"全部通过"，会自信地交付
虚假代码。**AgentSeed 就是在"完成"之前拦截这一切的闸门**——一个零依赖插件，
在任务被标记为"完成"之前先验证代码，让"完成"= **可观测事实**，而非自说自话。

[![License](https://img.shields.io/badge/license-PolyForm_NC_1.0.0-purple)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.6.3-blue)](https://github.com/Morningstar202604/AgentSeed/releases)
[![CI](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml/badge.svg)](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml)
[![MCP server score](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed/badges/score.svg)](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Morningstar202604/AgentSeed)
[![Platforms](https://img.shields.io/badge/platform-Cursor%20%7C%20VS%20Code%20%7C%20Claude%20Code%20%7C%20Copilot-blue)](https://agent-plugins.org)

[English](./README.md) · **中文** · [日本語](./README.ja.md)

</div>

---

## 为什么你需要它

LLM 会幻觉——放到代码里就是**编造的 API、未定义的标识符、虚假的测试通过、
自信的过度声明**：

- **15.1%** 的代码幻觉是调用不存在的、或从未导入的 API（[arXiv:2404.00971](https://arxiv.org/abs/2404.00971)）。
- **不足 10%** 的幻觉代码会挂掉测试——**约 90% 能溜过 CI**（[arXiv:2404.00971](https://arxiv.org/abs/2404.00971)）。
- **60%+** 的模型输出错误**表面上看不出来**（FAVA，[SoK](https://arxiv.org/abs/2502.18468)）。

纯提示词护栏是"软"的：模型可以嘴上答应验证、然后跳过。
**AgentSeed 把指令绑成一道"硬闸"**——证据来自真正运行的代码，而不是模型的自述。

## 30 秒看懂 AgentSeed 是什么

一个即插即用的 [Agent Plugins](https://agent-plugins.org) 1.0.0 插件
（Skill + MCP 服务器 + 可选的客户端 Hook + CI 门禁），兑现三个承诺：

| 承诺 | 如何兑现 |
| --- | --- |
| **🚫 不编造 API** | `verify_code` 用 **17 种语言**解析你的代码，标记任何"被调用却从未定义/导入"的符号 |
| **🚫 不假报"完成"** | `scan_hallucination` 拦截占位代码、过度声明与虚构内容（**中英双语**）；`sandbox_run` 用真实执行证明运行时声明 |
| **🚫 不跳过验证** | Skill 约束流程、**客户端 Hook** 在 `Write`/`Edit` 落盘前拦截、`guard_cli gate` 用退出码在 CI 强制同一套规则 |

它还填补了 1.0.0 规范故意留下的两个空白：

| Agent Plugins 1.0.0 的空白 | AgentSeed 的答案 |
| --- | --- |
| 没有强制机制（skill 可做可不做） | `verify-before-code` skill + 可选的**客户端强制 Hook**，让验证不可跳过 |
| 没有官方合规 linter | `check_plugin` 是**第一个严格的 1.0.0 linter**——而且 AgentSeed 通过了自己的 linter（`ok: true`） |

## 看它现场抓幻觉

```python
# 你的编码智能体刚刚"写完"这段——它调用了 magic_unknown()，
# 一个不存在、也从未导入的 API：

def f():
    return magic_unknown()      # ← 幻觉 API

# AgentSeed 在任务被标记为"完成"之前：
$ verify_code(source=..., language="python")
{
  "language": "python",
  "suspects": ["magic_unknown"]       # ← 抓到，阻断
}
```

```text
# 智能体的"完成声明"也活不过这一关：
"The feature is production ready, all tests pass. Trust me."

$ scan_hallucination(source=...)
{
  "hits": [
    {"word": "all tests pass",   "group": "oversold",  "line": 1},
    {"word": "production ready", "group": "oversold",  "line": 1},
    {"word": "trust me",         "group": "oversold",  "line": 1}
  ],
  "clean": false                        # ← 抓到，阻断
}
```

判定是**测出来的，不是吹出来的**：在固定种子的合成语料上（5 类缺陷、
100 个缺陷模块 + 40 个干净模块），AgentSeed 得分
**precision 1.0 · recall 1.0**（tp=100, fp=0, fn=0）——并有回归测试锁定。
方法与诚实边界见 [docs/BENCHMARK.md](./docs/BENCHMARK.md)；真实仓库实测证据见
[docs/FIELD-TEST.md](./docs/FIELD-TEST.md)；日常使用指南（开场约束提示词、
收尾验收、警告清单）见 [docs/USAGE.md](./docs/USAGE.md)。

## 闸门如何工作

1. **写码前** —— 加载 SDD 契约，用一句话陈述。
2. **实现** —— 只写真代码：无占位、无编造 API。
3. **说"完成"前** —— 跑 `verify_code` + `scan_hallucination`；运行时声明用
   `sandbox_run` 实证；结构化输出用 `schema_validate` 校验。
4. **语言审计** —— 完成报告必须附证据；禁用夸大词汇。
5. 只有当**所有检查都通过**，任务才允许被标记为完成。

## 快速开始

**方案 A —— 下载发布包（无需 git）：**

```bash
# 从 https://github.com/Morningstar202604/AgentSeed/releases 取最新资产
# 或用安装器一键接入你的客户端：
bash install.sh --client auto --hooks        # macOS / Linux
./install.ps1 -Client auto -Hooks            # Windows PowerShell
# --client: claude | opencode | cursor | manual
# --hooks / -Hooks: 同时注册 Claude Code 强制 Hook
```

**方案 B —— npm：**

```bash
npm install -g agentseed-mcp     # 安装 agentseed-mcp 启动器
npx agentseed-mcp                # 或直接运行 stdio MCP 服务器
```

在你的客户端里把 `npx agentseed-mcp` 注册为名为 `agentseed` 的 stdio MCP
服务器；启动器会按平台自动选择正确的 Python 解释器。

**方案 C —— 克隆：**

```bash
git clone https://github.com/Morningstar202604/AgentSeed.git
```

1. 把克隆出来的 `AgentSeed/` 目录**丢进**任意支持 Agent Plugins 的客户端
   （Cursor、VS Code、Claude Code、Copilot…）。无需构建、无需安装。
2. 客户端从 `plugin.json` + `mcp.json` 自动发现 `verify-before-code` skill
   与 `agentseed` MCP 服务器。
3. **完事。** 从此每个编码任务都被闸门约束：契约 → 实现 → 验证 → 证据。

**用在 你自己的项目**（你克隆它是为了它）——一条命令：

```bash
python3 /path/to/AgentSeed/server/guard_cli.py init --root /你的/项目
```

它会写入起始配置 `agentseed.config.json`、生成会克隆本插件并运行闸门的 CI
workflow、跑第一次 gate 自举基线，并打印把客户端指向本插件的 MCP 片段——
不用手工编辑。

### 项目符号索引（跨文件判定）

单个文件无法判断一个符号是否存在于项目任何地方——内置分析器现在会查询一个
缓存式、增量重建的项目符号索引，把原始嫌疑分成两类判定：

- `suspects` —— 项目里**任何地方**都没有定义：高置信幻觉，附最接近真实符号
  的建议；
- `missing_imports` —— 定义在别的文件但本文件没有导入：真实缺陷，修复方式
  不同（会列出定义所在文件）。

两类都会拦截。索引存放在 `.agentseed/` 下、永不进入发布物，配置
`project_index: false` 可关闭。

### 噪音衰减闭环

门禁只有越用越安静才能活下去：

```bash
python3 server/guard_cli.py suppress legacy_helper   # verify 不再标记（仍在 suppressed 中可见）
python3 server/guard_cli.py allow works-on-my-machine # scan 不再报告（合并在内置默认之后）
python3 server/guard_cli.py baseline audit           # 基线冻结了什么 + 复审闭环
```

两者都原子写入你项目的 `agentseed.config.json`，且拒绝覆盖解析失败的配置。


独立运行，或用人机同规的 CI 门禁：

```bash
python3 server/guard_engine.py                       # 自检演示
python3 -m unittest discover -s server               # 全量单元测试
python3 server/guard_cli.py gate --root .            # CI 等价硬门禁
python3 server/guard_cli.py check . --ci             # 仅插件合规
python3 server/guard_cli.py verify src/app.go        # 按后缀自动选语言
python3 server/guard_cli.py scan src/app.py --strict # 内联或文件，幻觉信号扫描
python3 server/guard_cli.py scan . --baseline baseline-scan.json  # 目录扫描，只报新增
```

> **Windows 提示：** Agent Plugins 规范要求 `mcp.json` 里的 `command` 只能是一
> 个字面量解释器名，仓库里发布的是 `python3`（macOS/Linux/WSL 正确）。Windows 上
> 请直接跑 `./install.ps1`，它会把安装副本里的 `command` 改写成 `python`；手工改
> 的话写成 `"command": "python"` 配 `"args": ["server/guard_server.py"]`——
> `command` 是字符串，数组属于 `args`。用 `npx agentseed-mcp` 则完全不用改：
> npm shim 会按平台自己挑解释器。

## 10 个 MCP 工具

零**必需**依赖——纯 Python 标准库；可选依赖把两个工具升级为行业标准引擎
（见下）。

| 工具 | 拦截什么 | 技术 |
| --- | --- | --- |
| `verify_code` | 编造的 API / 未定义符号 | Python AST + 配置驱动的通用词法扫描（17 语言） |
| `resolve_symbol` | 写码**之前**拦截幻觉 API（写前预防） | 项目符号索引 + stdlib/known_packages 查询，附最接近真实符号建议 |
| `check_contract` | 违反书面规范 | requires/prohibits 契约校验 |
| `check_imports` | 幻觉包导入（slopsquatting 抢注） | stdlib + known_packages 白名单校验；`--manifest` 直接扫依赖清单并按 git 基线对比——只报“新增”的可疑包 |
| `scan_hallucination` | 占位代码、夸大声称、虚构内容、幻觉域名 | 4 组 50+ 信号，中英双语 |
| `check_plugin` | 不合规的插件打包 | 严格 1.0.0 linter |
| `sandbox_run` | 什么都没跑就说"测试通过"、跑了但结果不符声称 | 确定性执行通道 + 行为断言（expected_exit / expect_output） |
| `schema_validate` | 不合法的结构化输出 | JSON Schema 校验 |
| `record_verification` | 没有持久化证据链、改了却没验证的文件 | `PLUGIN_DATA` 下 JSONL 审计轨迹；`files` 条目供 gate 覆盖率阶段使用 |

### 语言覆盖（诚实范围）

| 语言 | `verify_code` 分析 |
| --- | --- |
| Python | 完整 AST 作用域遍历（装 pyflakes 则合并），带行号 |
| TypeScript / JavaScript | 词法正则扫描（有明确记录的误报类别） |
| Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin · Swift | 配置驱动的通用词法扫描 |
| Dart · Lua · R · Zig | 配置驱动的通用词法扫描 |
| 任何其他语言 | 加一条 `LangSpec` 注册即可——无需改引擎 |

诚实边界：属性调用（`obj.m()`）、宏、跨文件符号不分析；Ruby 无括号调用已支持。

### 真的能抓其他语言——实测为证

同一规则适用于所有注册语言：只要「裸调用了从未定义的符号」，无论什么语法，都是幻觉：

```python
# Go       detect_undefined_symbols("func main() { process_data() }", "go")  -> ["process_data"]
# Rust     fn main() { let x = load_config() }        -> ["load_config"]
# Java     class A { void m() { connect_db() } }      -> ["connect_db"]
# C        int main() { ghost(); return 0; }          -> ["ghost"]
# Kotlin   fun main() { fetch_users() }               -> ["fetch_users"]
# Swift    func run() { connect() }                   -> ["connect"]
# Ruby     def run; authenticate; end                 -> ["authenticate"]
# TypeScript function run() { connectDb() }           -> ["connectDb"]
```

已实测 Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin · Swift ·
TypeScript · Dart · Lua · R · Zig——每种语言都能抓出自己的幻觉调用，且各语言干净代码**零误报**。


## 客户端强制 Hook 模式

Skill 靠"劝"，**Hook 在客户端边界"强制执行"**。把 AgentSeed 注册为
Claude Code hook，每个 `Write`/`Edit`/`MultiEdit` 都会自动被扫描——
任何提示词都无法跳过：

```bash
python3 server/guard_hook.py register --client claude   # 幂等，合并进 settings
python3 server/guard_hook.py --file path/to/source.py   # 直接扫描任意文件
```

- **PreToolUse** 在内容落盘**之前**检查；阻断性发现退出码 `2`，智能体必须
  修复被标记的行。
- **PostToolUse** 对无内联内容的写路径再次检查落盘文件。
- **失败策略（诚实）：** 基础设施问题（stdin 畸形、文件不可读）永不阻断
  工作——fail-open；只有真实的扫描发现才阻断。

## 平台支持

| 客户端 | 状态 | 说明 |
| --- | --- | --- |
| Claude Code | ✅ 已验证 | skills + MCP + 可选强制 Hook |
| opencode | ✅ 已验证 | `~/.config/opencode/opencode.json` |
| Cursor | ⚪ 规范兼容* | 拷入项目；尚无稳定插件目录 |
| VS Code (+Copilot) | ⚪ 规范兼容* | MCP 支持逐步开放 |
| Cline / Windsurf | ⚪ 规范兼容* | stdio 服务器条目可直接映射 |

\* 诚实标注：格式与规范兼容、预期可用，但维护者尚未实测。你若验证成功，
欢迎 PR 更新此表。

## 可选依赖

```bash
pip install -r server/requirements.txt
```

| 扩展 | 升级效果 | 无它时 |
| --- | --- | --- |
| `jsonschema` | `schema_validate` → 完整 Draft 2020-12 | 内置子集校验器 |
| `pyflakes` | `verify_code` → pyflakes F821 分析 | 内置 AST 遍历 |
| `pyyaml` | SKILL.md frontmatter → 完整 YAML | 内置轻量解析器 |

## 配置（`agentseed.config.json`）

| 键 | 作用 |
| --- | --- |
| `allowlist` | 扫描排除（替换内置测试惯用语清单） |
| `severities` | 按组覆盖严重度（`error` \| `warning` \| `info`） |
| `timeout` | 默认 `sandbox_run` 超时，秒（1–120） |
| `extra_tokens` | 运行时扩展幻觉词池 |
| `suppress_symbols` | `verify_code` 永不标记的名字（在 `suppressed` 中可见） |
| `known_packages` | `check_imports` 视为已知的包（stdlib + 常见包 + 本列表） |
| `sandbox_allowed_prefixes` | `sandbox_run` 可启动的**可执行文件白名单**；PATH 解析、分隔符边界强制（缺省=不限） |
| `sandbox_env` | `"inherit"` \| `"scrub"` —— `scrub` 在启动前剔除疑似凭据的环境变量 |

未知键会在 stderr 告警——拼错的键绝不会被静默忽略。

> ⚠️ **安全提示：** `sandbox_run` 以你的用户权限执行真实进程。客户端必须将其
> 置于用户批准之后；共享/CI 环境请设置 `sandbox_allowed_prefixes`。命令会先经
> `PATH` 解析为绝对路径再执行，恶意 `cwd` 无法用植入的可执行文件冒充白名单
> 命令；未匹配/无法解析的命令不执行直接拒绝（退出码 -10）。

## 兼容与优雅降级

| 宿主能力 | 得到什么 |
| --- | --- |
| 完整 Agent Plugins | 即插即用：skill + MCP 自动发现，`${PLUGIN_DATA}` 配置生效 |
| 支持 MCP 的客户端 | 注册即得全部 10 个工具 |
| 仅支持 skill 的客户端 | skill 流程；验证降级为 shell 调用 `guard_cli.py` |
| 纯终端 / CI | 带退出码的 CLI 门禁 |

## 内置护栏库（EN / 中文 / 日本語）

`PROMPT-POOL`（即贴即用的护栏提示）· `HALLUCINATION-PATTERNS`（失败模式
目录）· `VERIFICATION-CHECKLIST`（可执行的收尾检查清单）· `SDD-CONTRACT`
（每个任务必须满足的契约）· `DEFAULT-NORMS`（资深工程师行动规范与对应的强制
闸门；仅英文）· `VENDOR-SOLUTIONS`（厂商技术落地地图）。全部位于
`skills/verify-before-code/references/`，并由各语言 SKILL 文件列出。

## 为什么选 AgentSeed 而非替代方案

| | 纯提示词护栏 skill | 静态 import linter（MCP） | **AgentSeed** |
| --- | --- | --- | --- |
| 触碰代码 | ❌ 仅提示 | ✅ import 图 | ✅ AST + 词法（17 语言） |
| 跑验证工具 | ❌ | lint 门禁 | ✅ 10 个 MCP 工具含沙箱 |
| 幻觉语言扫描 | ❌ | ❌ | ✅ stub/oversold/fabricated/fabricated_url，中英双语 |
| 强制力 | 软（skill 文本） | CI 门禁 | **硬**：skill + MCP + hook + CLI 退出码 |
| 1.0.0 合规 linter | ❌ | ❌ | ✅ 首个 |

## FAQ

**需要特定 LLM 吗？** 不需要——客户端无关、模型无关；闸门由 skill + MCP +
hook + CI 执行，与具体模型无关。

**零依赖？** 是的。MCP 服务器是纯 Python 标准库。

**能和现有的 AGENTS.md / CLAUDE.md 共存吗？** 能——它们是互补的。那些文件
承载项目事实（散文、说服力）；AgentSeed 承载行为契约与硬强制。

**怎么扩展到新语言？** 在 `server/engine/symbols.py` 加一条 `LangSpec` 注册
——一份配置，零引擎改动。

## 参与贡献

欢迎 Issue、PR 与想法——或者为尚未收录的幻觉模式开一个 issue。
详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 许可证

PolyForm Noncommercial 1.0.0 © AgentSeed。学习、研究与个人使用免费；商用需另行获取授权。见 [LICENSE](./LICENSE)。

---

<div align="center">

</div>
