# AgentSeed — 技術設計

> AgentSeed の日本語技術設計。英語版 [DESIGN.md](./DESIGN.md)・中文版 [DESIGN.zh.md](./DESIGN.zh.md)。

## 1. 背景と問題

### 1.1 仕様は本物だが、誇張されている

Agent Plugins **1.0.0** は 2026 年 8 月に公開された本物のオープン仕様です。技術運営
委員会には **Amazon、Cursor、Microsoft、OpenAI、Vercel** が各 1 名ずつ代表を送って
います。2 点の訂正：

- **Google は委員会にいません。** 「6 社連合リリース」はコンテンツファームによる
  「ベンダー中立の標準化団体」の誇張表現です。
- これは**パッケージング標準**であり、製品ではありません。「箱」（`plugin.json`、
  `skills/`、`mcp.json`）を標準化していますが、意図的に 2 つの穴を残しています。

### 1.2 仕様の 2 つの穴（＝我々の機会）

1. **強制メカニズムがない。** クライアントは skill を読み込む「ことができます」が、
   モデルに完了前の出力検証を強制する手段はありません。
2. **レジストリ / マーケット / 配布機構がない。** 配布はオープン。さらに MUST/SHOULD
   ルールは定義されているのに、**公式 linter がありません**。

### 1.3 市場の隙間

| 既存 | 機能 | 欠けている点 |
| --- | --- | --- |
| チャット誠実さガードレール（行動系 MCP サーバー） | チャット回答を誠実に保つ（引用/日付の捏造防止） | コード・ツールに非対応 |
| `obra/superpowers` | プロンプトのみのコーディングワークフロー | ハード検証なし |
| 静的 import linter（Rigour 系 MCP） | 言語別の幻覚 import 検出 | 行動言語スキャンなし、skill ワークフローなし |
| 一般的な MCP サーバー | モデルへ API を公開 | モデル自身が書いたコードを検証しない |

AgentSeed は「**コードレベル + 実ツール実行 + Skill/MCP クローズドループ強制**」を
埋めます。`check_plugin` は 1.0.0 初の linter です。

## 2. 設計目標

- **クロスクライアント** — 1.0.0 準拠、仕様対応クライアントでネイティブ読み込み。
- **クローズドループ強制** — 弱い Skill 指示をハードな MCP ゲートに接続。
- **ゼロ依存** — 純標準ライブラリ Python、SDK バージョン非依存。
- **初の linter** — 1.0.0 向け `check_plugin`。

## 3. アーキテクチャ

```
            ┌─────────────────────────────────────────────┐
            │  コーディングエージェント（Cursor/VS Code 等）│
            └───────────────┬───────────────┬─────────────┘
                            │ 読み込み       │ 起動（stdio）
                            ▼                ▼
                 ┌──────────────────┐  ┌──────────────────────────┐
                 │  Skill           │  │  MCP サーバー（agentseed） │
                 │  verify-before-  │  │  guard_server.py          │
                 │  code            │  │    │                      │
                 └────────┬─────────┘  │    ▼                      │
                          │ 指示        │  guard_engine.py          │
                          │            │   ├ verify_code（AST）     │
                          │            │   ├ scan_hallucination     │
                          │            │   ├ check_plugin（linter） │
                          │            │   ├ sandbox_run（実行検証）│
                          │            │   ├ schema_validate        │
                          │            │   └ record_verification    │
                          ▼            └──────────────────────────┘
                 ┌──────────────────┐
                 │ リファレンス     │  SDD-CONTRACT / PROMPT-POOL /
                 │ ライブラリ       │  HALLUCINATION-PATTERNS /
                 │（英/中/日）      │  VERIFICATION-CHECKLIST /
                 └──────────────────┘  VENDOR-SOLUTIONS
```

## 4. MCP インターフェース契約

トランスポート：stdio 上の行区切り JSON-RPC 2.0。サーバー名 `agentseed`、
バージョン `0.6.2`、プロトコル `2024-11-05`。

| ツール | 説明 |
| --- | --- |
| `verify_code` | 未定義/未インポートシンボルの静的検出（Python は AST、他は語彙パス） |
| `resolve_symbol` | 呼び出す前のシンボル存在判定（プロジェクト記号インデックス + stdlib/既知パッケージ、書き込み前予防） |
| `verify_file` | ディスク上のファイルを最適なエンジンで検証（ruff/pyflakes/mypy/tsc/eslint/go vet/cargo/javac、§10.1） |
| `check_contract` | 書かれた契約（requires/prohibits）に対してソースを検証 |
| `check_imports` | stdlib と `known_packages` に無いトップレベル import を報告（slopsquatting ガード） |
| `scan_hallucination` | 4 グループ幻覚シグナルスキャン（stub_code/oversold/fabricated/fabricated_url） |
| `check_plugin` | Agent Plugins 1.0.0 適合性 linter |
| `sandbox_run` | 決定的実行チャネル（サブプロセス・タイムアウト付き） |
| `schema_validate` | JSON Schema サブセット検証（ゼロ依存） |
| `record_verification` | SDD 契約の証跡を `${PLUGIN_DATA}` 配下の JSONL に追記 |

## 5. 主要アルゴリズム

- **`detect_undefined_symbols`** — `ast` 解析で定義済み集合（builtins、インポート、
  def/class、引数）を収集し、外れの `Name`/`Call` を検出。静的スコープのみ、実行
  なし、属性呼び出しは非展開（誤検出の可能性）。Python（AST + pyflakes 併用、
  インストール時）、TypeScript/JavaScript（語彙スキャン）、そして**汎用レジストリ
  （語彙）**に対応：同一エンジンで登録済み全言語を解析（一覧は `canonical_languages()`）。各 `LangSpec` がコメント/文字列構文・キーワード・グローバル名・
  定義/インポート/引数正規表現・引数名モードを宣言し、共有エンジンがコメントと
  文字列をマスク → 定義を収集 → 未定義の裸呼び出し・`new` を検出。言語追加は
  レジストリ追加のみでエンジン変更不要。Ruby の括弧なし呼び出しは `bare_calls`
  フラグで対応。
- **`scan_hallucination_words`** — 50+ シグナルのグループ化ワード境界スキャン（プレースホルダー/予約 TLD ドメインを構造的に検出する `fabricated_url` を含む）。
  出典：SFD Lab 5 ステップチェックリスト、CDV（"'done, all tests pass' は主張であり
  証拠ではない"）、reze83 先検証ルール。
- **`check_plugin_conformance`** — §5/§6/§7 の厳格 linter：閉じたトップレベル
  スキーマ、`name` 制約、SKILL.md frontmatter（ディレクトリ名一致、
  description ≤1024）、mcp.json の閉じたフィールドと cwd 形式。
- **`sandbox_run`** — shell なしサブプロセス実行（タイムアウト 1–120 秒、出力
  トランケート）、任意の振る舞いアサーション（expected_exit / expect_output）
  付き。CDV チャネル A の実装。
- **`schema_validate`** — type/enum/const/minLength/maxLength/pattern/minItems/
  maxItems/items/properties/required/additionalProperties をサポートする
  ゼロ依存サブセット検証。

## 6. 1.0.0 適合性チェックリスト

| 仕様節 | 要件 | AgentSeed |
| --- | --- | --- |
| §5.2 マニフェスト | ルート `plugin.json`、クローズドスキーマ | ✅ |
| §5.3 必須 | `$schema` = 1.0.0 アドレス、`name` 必須 | ✅ |
| §5.5 命名 | 1–64 文字、`[a-z0-9.-]`、`--`/`..` 禁止 | ✅ |
| §5.4 メタデータ | `repository` 等は文字列、`author` は name/email/url のみ | ✅ |
| §6.1/§7.1 スキル | `skills/<name>/SKILL.md`、Agent Skills frontmatter | ✅ |
| §7.2 mcp.json | `$schema`+`mcpServers` のみ、stdio + `cwd=${PLUGIN_ROOT}` | ✅ |
| §8 検出 | マニフェスト+スキル+mcp をクライアントが読む | ✅（設計上） |
| §11 linter | （仕様に無し） | ✅ `check_plugin` が埋める |

## 7. 競合比較

| | プロンプト専用 skill（superpowers…） | 静的 import linter | **AgentSeed** |
| --- | --- | --- | --- |
| コードに触れる | ❌ | ✅ import グラフ | ✅ AST + 語彙解析 |
| ツール実行 | ❌ | lint ゲート | ✅ sandbox 含む 10 MCP ツール |
| 強制 | 弱い | CI ゲート | **ハードゲート** |
| 1.0.0 linter | ❌ | ❌ | ✅ |

## 8. リスクと明示的な非目標

リスク：

- 静的スコープ解析 → 動的/属性アクセスで誤検出の可能性。
- 仕様が新しい（2026-08）。クライアント採用とスキーマが変動しうる。
- 強制はクライアントがスキルのゲート指示を守るかに依存。ハード層は CI の
  `guard_cli gate`。

明示的な非目標（バグと誤解されないよう明記）：

- **意味的正确性**：動くが論理的に誤ったコードは範囲外 —— プラグイン層に
  実行オラクルはない。
- **属性呼び出しの検証**（`obj.missing_method()`）：ファイル横断の型推論が
  要るため、文書済みの見逃しクラス。
- **ファイル横断シンボル解決**：解析は設計上シングルファイル（ゼロ依存、
  O(source)）。
- **完全なサンドボックス隔離**：`sandbox_run` はツリー kill と任意の環境
  スクラブ付きの決定的実行チャネルであり、コンテナではない。

## 9. ビルドとテスト

```bash
python3 server/guard_engine.py                 # 自己テスト + デモ
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' \
            '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 server/guard_server.py
```

## 10. アダプタ、ゲートプロファイル、エビデンスレシート、プラグインツールチェーン

### 10.1 ツールチェーン検証アダプタ（`engine/verifiers.py`）

レジストリは「安価で広い」ことを証明し、アダプタは「重要な場所で深い」
ことを証明する。`VerifierSpec`（名前・言語・バイナリ・固定引数・パーサ）
がプロジェクト自前のツールチェーンを `sandbox_run` 経由で実行し——
シェルなし・出力上限・タイムアウト・プロセスツリー kill——未定義シンボル
クラス（F821 / TS2304 / `undefined:` / E0425 / no-undef）だけを抽出して、
内蔵アナライザと同じ `suspects` 形に正規化する。ポリシー：

- `auto` = 最初に見つかったインストール済みアダプタ、なければ内蔵
  アナライザにフォールバック（note に明記）。明示指定したアダプタが
  欠落または失敗した場合は大音量でエラー——壊れたアダプタを「クリーン」
  と解釈することこそ、このプロジェクトが排除すべき偽グリーンである。
- アダプタのバイナリは PATH 解決された絶対パス。
  `sandbox_allowed_prefixes` は意図的にアダプタを制約しない
  （AgentSeed を起動すること自体がプロジェクト宣言済みツールチェーンの
  実行を意味する）。
- アダプタ追加 = `VerifierSpec` 1 エントリ + パーサ関数 1 個。

### 10.2 Hook ゲートプロファイル（`guard_hook.py`）

語彙スキャナの偽陽性が正当な作業を妨害できてはならない——狼少年のゲート
は無効化され、無効化されたゲートは何も強制しない。ゆえに hook
は自分の権限をプロファイルで分ける：

| プロファイル | ブロック | 理由 |
| --- | --- | --- |
| `advisory`（既定） | しない | 証拠と可視性；割り込みゼロ |
| `diff` | `group\|word` 計数または容疑シンボルがファイルの直前ディスク内容より**増加**したときのみ | hook レベルの `scan --baseline` 相当 |
| `strict` | error 深刻度のヒットまたは容疑シンボルすべて | 0.4 以前の挙動、オプトイン |

判定の `blocking` フィールドはプロファイルの決定であり生スキャンでは
ない。`status` は `pass` / `flagged` / `blocked` / `skipped`。

### 10.3 検証カバレッジ（`engine/audit.py`）

レシートは「検証したと主張するもの」を凍結する。カバレッジは「変更したが
一度も検証していないファイル」を名指しする——自己認識幻覚クラスである。
gate のカバレッジ段は `git status --porcelain` を
`record_verification(files=...)` の記録と突き合わせ、欠落を列挙する。
デフォルトは報告のみ、`--coverage-strict` で阻断。git ワークツリー外では
偽グリーンではなく誠実な「計算不能」に劣化する。

### 10.4 エビデンスレシート（`engine/receipt.py`）

レシートは完了タスクの検証状態を凍結する：チェック項目（ツール + 判定）、
検証済みファイルごとの SHA256 とサイズ、agentseed/python/プラットフォーム
のバージョン、そしてレシートファイル自体のダイジェスト——再ハッシュすれ
ば後日の改ざんは検出される。監査ログに 1 行がリンクとして追記される。
指定されたファイルが存在しない場合、レシート全体が大音量で失敗する。
完了報告が引用するのは散文ではなくこの成果物である。

### 10.5 プラグインツールチェーン（`guard_cli plugin …`）

`init` は最小プラグインを足場生成し、本物の適合性チェッカで自己検査する——
自前の linter を通れない足場はディスクに残さない。`validate` は linter を
再実行、`pack` は決定論的 zip を構築（スキップ規則はリリースパッカと共有、
`engine/artifact.py` 経由、フォールバック定数はドリフトテストで固定）、
`doctor` はインタプリタ・オプション依存・アダプタ有無・設定警告・実際の
MCP ハンドシェイク（tools/list 数）・適合性を報告する。

## 11. プロジェクトシンボルインデックス（`engine/index.py`）

単一ファイルのスコープ解析は誠実だが、プロジェクトに対して盲目的です。
インデックスは型チェッカーなしで、内蔵アナライザにファイル横断の判定を
与えます：

- 収集は `defined_symbols` 背後の言語別コレクタをそのまま再利用——
  ドリフトしうる第二のパーサは存在しない。
- エントリは `<root>/.agentseed/index.json` にファイルごとキャッシュされ、
  内容ハッシュをキーとする。未変更のファイルは再スキャンされず、大規模
  リポジトリのゲートも秒単位。
- 差分判定：インデックスに存在する容疑は `missing_imports`
  （別ファイル定義・本ファイル未インポート——実在のバグ、修正が異なる、
  定義ファイルを列挙）に再分類され、インデックスに存在しない容疑は
  `suspects` のまま、プロジェクト全体のシンボルプールから「もしかして」
  提案が付く。
- 両判定ともゲート対象。`verify_file`（builtin 経路）、`guard_cli verify`、
  `gate` のシンボル段階が参照し、設定 `project_index: false` で無効、
  プロジェクトルートが検出できない場合は 0.3.x の単一ファイル解析と
  完全に同じ挙動。
