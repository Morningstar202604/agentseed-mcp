<div align="center">

<img src="docs/logo.png" width="96" alt="AgentSeed logo">

# AgentSeed

**AI コーディングエージェントのための反幻覚ゲート。**

AI は存在しない API を捏造し、何も実行せずに「テスト全部通った」と言い、
自信満々に偽のコードを納品します。**AgentSeed は「完了」と宣言する前に
それを止めるゲート**——ゼロ依存のプラグインで、コードを検証してから
「完了」にします。「完了」= **観測された事実**であり、自己申告ではありません。

[![License](https://img.shields.io/badge/license-PolyForm_NC_1.0.0-purple)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.6.2-blue)](https://github.com/Morningstar202604/AgentSeed/releases)
[![CI](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml/badge.svg)](https://github.com/Morningstar202604/AgentSeed/actions/workflows/ci.yml)
[![MCP server score](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed/badges/score.svg)](https://glama.ai/mcp/servers/Morningstar202604/AgentSeed)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Morningstar202604/AgentSeed)
[![Platforms](https://img.shields.io/badge/platform-Cursor%20%7C%20VS%20Code%20%7C%20Claude%20Code%20%7C%20Copilot-blue)](https://agent-plugins.org)

[English](./README.md) · [中文](./README.zh.md) · **日本語**

</div>

---

## なぜ必要か

LLM は幻覚を起こします——コードではそれは**捏造 API・未定義の識別子・
偽のテスト合格・過剰な宣言**を意味します：

- **15.1%** のコード幻覚は、存在しない・インポートされていない API を呼ぶこと
  （[arXiv:2404.00971](https://arxiv.org/abs/2404.00971)）。
- **10% 未満**の幻覚コードしかテストを落とさない——**約 90% は CI をすり抜ける**
  （[arXiv:2404.00971](https://arxiv.org/abs/2404.00971)）。
- **60%+** のモデル出力エラーは**見た目では検証不能**（FAVA、[SoK](https://arxiv.org/abs/2502.18468)）。

プロンプトだけのガードレールは「柔らかい」：モデルは検証に同意したふりをして
スキップできます。**AgentSeed は指示を「硬いゲート」に結びつけます**——
証拠はモデルの自己申告ではなく、実行されたコードから来ます。

## 30 秒でわかる AgentSeed

ドロップインの [Agent Plugins](https://agent-plugins.org) 1.0.0 プラグイン
（Skill + MCP サーバー + 任意のクライアント Hook + CI ゲート）が約束する
3 つのこと：

| 約束 | 実現方法 |
| --- | --- |
| **🚫 API を捏造しない** | `verify_code` が **17 言語**のコードを解析し、「呼ばれたのに定義もインポートもされていない」シンボルを検出 |
| **🚫 偽の「完了」を出さない** | `scan_hallucination` がスタブ・過剰宣言・捏造主張を（**英語+中国語+CJK**）検出；`sandbox_run` が実行時主張を実際に実行して証明 |
| **🚫 検証をスキップさせない** | Skill がワークフローを制約、**クライアント Hook** が `Write`/`Edit` を未検証ファイルでブロック、`guard_cli gate` が CI で同じルールを終了コードで強制 |

1.0.0 仕様が意図的に残した 2 つの穴も埋めます：

| Agent Plugins 1.0.0 の穴 | AgentSeed の答え |
| --- | --- |
| 強制メカニズムがない（skill は任意） | `verify-before-code` skill + 任意の**クライアント強制 Hook** で検証をスキップ不可に |
| 公式 linter がない | `check_plugin` は**最初の厳格な 1.0.0 linter**——しかも AgentSeed 自身が自分の linter を通る（`ok: true`） |

## 幻覚を捕まえる現場を見る

```python
# エージェントが「書き終えた」コード。magic_unknown() を呼ぶ——
# 存在せず、インポートもされていない API：

def f():
    return magic_unknown()      # ← 幻覚 API

# タスクが「完了」になる前に：
$ verify_code(source=..., language="python")
{
  "language": "python",
  "suspects": ["magic_unknown"]       # ← 検出、ブロック
}
```

```text
# 「完了」宣言も生き残れない：
"The feature is production ready, all tests pass. Trust me."

$ scan_hallucination(source=...)
{
  "hits": [
    {"word": "all tests pass",   "group": "oversold",  "line": 1},
    {"word": "production ready", "group": "oversold",  "line": 1},
    {"word": "trust me",         "group": "oversold",  "line": 1}
  ],
  "clean": false                        # ← 検出、ブロック
}
```

判定は**約束ではなく計測値**：シード固定の合成コーパス（5 欠陥クラス、
欠陥 100 + クリーン 40 モジュール）で **precision 1.0 · recall 1.0**
（tp=100, fp=0, fn=0）——回帰テストでロックイン済み。
方法と正直な限界は [docs/BENCHMARK.md](./docs/BENCHMARK.md)。実リポジトリの検証証拠は
[docs/FIELD-TEST.md](./docs/FIELD-TEST.md)。日々の使用ガイド
（開始時の制約プロンプト、受け入れ、警告）は [docs/USAGE.md](./docs/USAGE.md)。

## ゲートの仕組み

1. **コーディング前** — SDD 契約を読み、一文で宣言する。
2. **実装** — 本物のコードだけ：プレースホルダーも捏造 API も禁止。
3. **「完了」の前** — `verify_code` + `scan_hallucination` を実行；実行時主張は
   `sandbox_run` で証明；構造は `schema_validate` で検証。
4. **言語監査** — 完了報告に証拠を添付；過剰語彙は禁止。
5. **すべてのチェックが通った時だけ**「完了」を許す。

## クイックスタート

**A — リリースをダウンロード（git 不要）：**

```bash
# https://github.com/Morningstar202604/AgentSeed/releases から最新アセットを取得
# またはインストーラーでクライアントに配線：
bash install.sh --client auto --hooks        # macOS / Linux
./install.ps1 -Client auto -Hooks            # Windows PowerShell
# --client: claude | opencode | cursor | manual
# --hooks / -Hooks: Claude Code 強制 Hook も登録
```

**B — npm：**

```bash
npm install -g agentseed-mcp     # agentseed-mcp ランチャーをインストール
npx agentseed-mcp                # または stdio MCP サーバーを直接実行
```

クライアントで `npx agentseed-mcp` を `agentseed` という名前の stdio MCP
サーバーとして登録；ランチャーがプラットフォームに合った Python を選ぶ。

**C — クローン：**

```bash
git clone https://github.com/Morningstar202604/AgentSeed.git
```

1. クローンした `AgentSeed/` ディレクトリを Agent Plugins 対応クライアント（Cursor、
   VS Code、Claude Code、Copilot…）に**ドロップ**する。ビルドもインストールも不要。
2. クライアントが `plugin.json` + `mcp.json` から `verify-before-code` skill と
   `agentseed` MCP サーバーを自動発見。
3. **これだけ。** 以降すべてのコーディングタスクがゲートされます：
   契約 → 実装 → 検証 → 証拠。

**あなたのプロジェクト**（クローンした理由となったもの）で使う——コマンド一つ：

```bash
python3 /path/to/AgentSeed/server/guard_cli.py init --root /your/project
```

起動設定 `agentseed.config.json` の生成、プラグインをクローンしてゲートを実行
する CI workflow の生成、最初の gate 実行によるベースラインのブートストラップ、
クライアントへ plugin を向ける MCP スニペットの出力——手編集は不要です。

### プロジェクトシンボルインデックス（ファイル横断判定）

単一ファイルでは、シンボルがプロジェクトのどこかに存在するか判定できません。
内蔵アナライザはキャッシュされ増分再構築されるプロジェクト全体のシンボル
インデックスを参照し、容疑を二つの判定に分けます：

- `suspects` — プロジェクトの**どこにも**定義がない：高信頼の幻覚。最も近い
  実在シンボルの提案付き；
- `missing_imports` — 別ファイルで定義済みだがこのファイルで未インポート：
  実在のバグ、修正方法が違う（定義ファイルを列挙）。

どちらもゲート対象。インデックスは `.agentseed/` 配下で成果物には決して
入らず、設定 `project_index: false` で無効化できます。

### ノイズ減衰ループ

ゲートが生き残る条件は、使うほど静かになることです：

```bash
python3 server/guard_cli.py suppress legacy_helper    # verify がマークしなくなる（suppressed には残る）
python3 server/guard_cli.py allow works-on-my-machine # scan が報告しなくなる（内蔵デフォルトの後に統合）
python3 server/guard_cli.py baseline audit           # 凍結済みシグナルの監査とレビューLoop
```

どちらもプロジェクトの `agentseed.config.json` を原子的に書き換え、パースに
失敗する設定の上書きは拒否します。


単体実行、または人間の PR にも同じ CI ゲート：

```bash
python3 server/guard_engine.py                       # セルフチェック
python3 -m unittest discover -s server               # 全ユニットテスト
python3 server/guard_cli.py gate --root .            # CI 相当のハードゲート
python3 server/guard_cli.py check . --ci             # プラグイン適合のみ
python3 server/guard_cli.py verify src/app.go        # 拡張子から言語を推定
python3 server/guard_cli.py scan src/app.py --strict # インラインでもファイルでも
python3 server/guard_cli.py scan . --baseline baseline-scan.json  # ツリー検索・新規のみ報告
```

> **Windows 注記：** Agent Plugins 仕様上 `mcp.json` の `command` は単一の文字列
> しか書けず、同梱値は `python3`（macOS/Linux/WSL 向け）です。Windows では
> `./install.ps1` を実行するとインストール先の `command` が `python` に書き換え
> られます。手動なら `"command": "python"` + `"args": ["server/guard_server.py"]`
> （配列は `args` 側）。`npx agentseed-mcp` は shim が OS から解釈器を選ぶため
> 編集不要です。

## 10 個の MCP ツール

必須依存**ゼロ**——純 Python 標準ライブラリ。オプション拡張で 2 ツールが
業界標準エンジンにアップグレードされます（下記）。

| ツール | ブロックするもの | 技術 |
| --- | --- | --- |
| `verify_code` | 捏造 API / 未定義シンボル | Python AST + 設定駆動の汎用語彙パス（17 言語） |
| `resolve_symbol` | 呼び出す**前**に幻覚 API を予防 | プロジェクト記号インデックス + stdlib/既知パッケージ照会、類似候補提示 |
| `check_contract` | 仕様に違反するコード | requires/prohibits 契約チェック |
| `check_imports` | 幻覚パッケージ（slopsquatting） | stdlib + known_packages ホワイトリスト検証；`--manifest` は依存マニフェストをスキャンし git HEAD と比較——新規追加のみを疑う |
| `scan_hallucination` | プレースホルダー、誇張、捏造、ファントムドメイン | 4 グループ 50+ シグナル、EN + CJK |
| `check_plugin` | 不適合なプラグイン | 厳格 1.0.0 linter |
| `sandbox_run` | 実行せずに「テスト合格」、実行したが結果が不一致 | 決定的実行チャネル + 振る舞いアサーション（expected_exit / expect_output） |
| `schema_validate` | 不正な構造化出力 | JSON Schema 検証 |
| `record_verification` | 証跡の永続化欠如、未検証の変更ファイル | `PLUGIN_DATA` 配下の JSONL 監査トレイル；`files` エントリは gate のカバレッジ段で利用 |

### 言語カバレッジ（正直な範囲）

| 言語 | `verify_code` 解析 |
| --- | --- |
| Python | フル AST スコープウォーク（pyflakes 時はマージ）、行番号付き |
| TypeScript / JavaScript | 語彙正規表現パス（誤検出クラスを明記） |
| Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin · Swift | 設定駆動の汎用語彙パス |
| Dart · Lua · R · Zig | 設定駆動の汎用語彙パス |
| その他の言語 | `LangSpec` レジストリに追加するだけ——エンジン変更不要 |

正直な限界：属性呼び出し（`obj.m()`）、マクロ、ファイル横断シンボルは解析しません。
Ruby の括弧なし呼び出しは対応済み。

正直な限界：属性呼び出し（`obj.m()`）、マクロ、ファイル横断シンボルは解析しません。

### 他の言語も本当に検出する——実測済み

同じルールが全登録言語に適用されます：「未定義のシンボルの裸呼び出し」は、構文が何であれ
幻覚です：

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

Go · Rust · Java · C · C++ · C# · PHP · Ruby · Kotlin · Swift · TypeScript · Dart · Lua · R · Zig で実測——
全言語が捏造呼び出しを検出し、各言語のクリーンコードは**誤検出ゼロ**。


## クライアント強制 Hook モード

Skill は「説得」、**Hook はクライアント境界で「強制」**します。AgentSeed を
Claude Code hook として登録すると、すべての `Write`/`Edit`/`MultiEdit` が
自動スキャンされます——どのプロンプトもスキップできません：

```bash
python3 server/guard_hook.py register --client claude   # 冪等、settings にマージ
python3 server/guard_hook.py --file path/to/source.py   # 任意のファイルを直接スキャン
```

- **PreToolUse** は内容がディスクに書かれる**前**に検査。ブロック検出は終了コード
  `2` で、エージェントは指摘された行を直す必要があります。
- **PostToolUse** はインライン内容のない書き込みパスで保存後ファイルを再検査。
- **失敗ポリシー（正直な範囲）：** インフラ問題（stdin 不正・ファイル不可読・
  未知のツール形状）は決して作業をブロックしません（fail-open）。ブロックするのは
  検出結果だけです。

## プラットフォーム対応

| クライアント | 状態 | 備考 |
| --- | --- | --- |
| Claude Code | ✅ 検証済み | skills + MCP + 任意の強制 Hook |
| opencode | ✅ 検証済み | `~/.config/opencode/opencode.json` |
| Cursor | ⚪ 仕様互換* | プロジェクトへコピー；安定プラグインディレクトリ未確定 |
| VS Code (+Copilot) | ⚪ 仕様互換* | MCP サポートは展開中 |
| Cline / Windsurf | ⚪ 仕様互換* | stdio サーバーエントリをそのままマッピング |

\* 正直な注記：形式は仕様互換・動作見込みですが、メンテナー未実測。
検証できたら PR でこの表を更新してください。

## オプション依存

```bash
pip install -r server/requirements.txt
```

| 拡張 | アップグレード内容 | 未導入時 |
| --- | --- | --- |
| `jsonschema` | `schema_validate` → 完全 Draft 2020-12 | 内蔵サブセット検証 |
| `pyflakes` | `verify_code` → pyflakes F821 解析 | 内蔵 AST ウォーク |
| `pyyaml` | SKILL.md frontmatter → 完全 YAML | 内蔵ライトパーサー |

## 設定（`agentseed.config.json`）

| キー | 効果 |
| --- | --- |
| `allowlist` | スキャン除外（内蔵のテスト慣用句リストを置換） |
| `severities` | グループ別の重大度上書き（`error` \| `warning` \| `info`） |
| `timeout` | デフォルト `sandbox_run` タイムアウト（秒、1–120） |
| `extra_tokens` | 実行時に幻覚ワードプールを拡張 |
| `suppress_symbols` | `verify_code` が決してフラグしない名前（`suppressed` に表示） |
| `known_packages` | `check_imports` が既知とするパッケージ（stdlib + 一般的 + このリスト） |
| `sandbox_allowed_prefixes` | `sandbox_run` が起動できる**実行ファイルのホワイトリスト**；PATH 解決・区切り境界強制（省略=無制限） |
| `sandbox_env` | `"inherit"` \| `"scrub"` —— `scrub` は認証情報らしき環境変数を起動前に除去 |

未知キーは stderr に警告——タイポは決して黙殺されません。

> ⚠️ **セキュリティ注記：** `sandbox_run` はユーザーの権限で実プロセスを実行します。
> クライアントはユーザー承認の後ろに置いてください。共有/CI 環境では
> `sandbox_allowed_prefixes` を設定。コマンドは実行前に `PATH` 解決され、悪意ある
> `cwd` がホワイトリスト名を偽装できません。未解決・未一致のコマンドは実行せず
> 拒否（終了コード -10）。

## 互換性とグレースフルデグラデーション

| ホスト能力 | 得られるもの |
| --- | --- |
| フル Agent Plugins | ドロップイン：skill + MCP 自動発見、`${PLUGIN_DATA}` 設定尊重 |
| MCP 対応クライアント | 登録で 10 ツールすべて |
| skill のみのクライアント | skill ワークフロー；検証は `guard_cli.py` を shell 経由で実行 |
| ターミナル / CI | 終了コード付き CLI ゲート |

## 内蔵ガードレールライブラリ（EN / 中文 / 日本語）

`PROMPT-POOL`（コピペ即使用プロンプト）· `HALLUCINATION-PATTERNS`（失敗
モードカタログ）· `VERIFICATION-CHECKLIST`（実行可能な完了チェックリスト）·
`SDD-CONTRACT`（全タスクが満たすべき契約）· `DEFAULT-NORMS`（シニアエンジニア
の行動規範とそれを強制するゲート、英語のみ）· `VENDOR-SOLUTIONS`（ベンダー
手法の導入マップ）。すべて `skills/verify-before-code/references/` 配下にあり、
各言語の SKILL ファイルが一覧化しています。

## 代替案との比較

| | プロンプト専用 skill | 静的 import linter（MCP） | **AgentSeed** |
| --- | --- | --- | --- |
| コードに触れる | ❌ プロンプトのみ | ✅ import グラフ | ✅ AST + 語彙（17 言語） |
| 検証ツールを実行 | ❌ | lint ゲート | ✅ 10 MCP ツール（sandbox 含む） |
| 幻覚言語スキャン | ❌ | ❌ | ✅ stub/oversold/fabricated/fabricated_url、EN + CJK |
| 強制力 | 軟（skill 文面） | CI ゲート | **硬**：skill + MCP + hook + CLI 終了コード |
| 1.0.0 適合 linter | ❌ | ❌ | ✅ 最初 |

## FAQ

**特定の LLM が必要？** いいえ——クライアント非依存・モデル非依存。ゲートは
skill + MCP + hook + CI が実行するもので、モデルには依存しません。

**ゼロ依存？** はい。MCP サーバーは純 Python 標準ライブラリです。

**既存の AGENTS.md / CLAUDE.md と共存できる？** できます——補完関係です。
あちらはプロジェクト事実（散文・説得力）、AgentSeed は行動契約とハード強制を
担います。

**新しい言語にどう拡張する？** `server/engine/symbols.py` に `LangSpec` を
1 件追加するだけ——設定のみ、エンジン変更なし。

## コントリビューション

Issue・PR・アイデア歓迎——未収録の幻覚パターンも issue でどうぞ。
詳細は [CONTRIBUTING.md](./CONTRIBUTING.md)。

## ライセンス

PolyForm Noncommercial 1.0.0 © AgentSeed。研究・学習・個人利用は無料；商用は別途許諾が必要。[LICENSE](./LICENSE)。

---

<div align="center">

</div>
