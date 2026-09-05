"""Regression tests for the false-positive classes that made verify_code and
the hook unusable on real code. Each test pins a code shape that a 0.3.x
review flagged as a wrongful suspect, plus the real-hallucination catch that
must survive the fix."""

import unittest

from guard_engine import detect_undefined_symbols


class TestTypeScriptArrayDestructuring(unittest.TestCase):
    REACT = (
        'import { useState } from "react";\n'
        "export function Counter({ initial }: { initial: number }) {\n"
        "  const [count, setCount] = useState(initial);\n"
        "  const inc = () => setCount((c) => c + 1);\n"
        "  return inc();\n"
        "}\n"
    )

    def test_hook_setters_are_not_suspects(self):
        res = detect_undefined_symbols(self.REACT, "typescript")
        self.assertEqual(res["suspects"], [])

    def test_unimported_hook_call_is_still_caught(self):
        src = "function C() {\n  const [n, setN] = useState(0);\n  return setN(n);\n}\n"
        res = detect_undefined_symbols(src, "typescript")
        self.assertIn("useState", res["suspects"])

    def test_rest_and_default_elements_are_collected(self):
        # only CALL positions are checked: `list`/`pair` as initializers are
        # loads (never flagged), `run` is a bare call with no definition
        src = (
            "const [head, ...rest] = list;\n"
            "const [a = 1, b = 2] = pair;\n"
            "run(head, rest, a, b);\n"
        )
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], ["run"])


class TestRubyLocalsAndBlockParams(unittest.TestCase):
    REALISTIC = (
        "def total(items)\n"
        "  sum = 0\n"
        "  items.each { |i| sum += i }\n"
        "  average = sum / items.size\n"
        "  puts average\n"
        "end\n"
    )

    def test_locals_are_not_suspects(self):
        res = detect_undefined_symbols(self.REALISTIC, "ruby")
        self.assertEqual(res["suspects"], [])

    def test_undefined_method_call_is_still_caught(self):
        src = "def run\n  sum = 0\n  authenticate\n  sum\nend\n"
        res = detect_undefined_symbols(src, "ruby")
        self.assertEqual(res["suspects"], ["authenticate"])

    def test_augmented_and_conditional_assignment_are_collected(self):
        src = "cache ||= load_cache()\ncount += 1\nputs cache, count\n"
        res = detect_undefined_symbols(src, "ruby")
        self.assertEqual(res["suspects"], ["load_cache"])


class TestPythonStarImport(unittest.TestCase):
    def test_wildcard_import_disables_detection_honestly(self):
        src = "from os.path import *\nfrom pathlib import Path\np = join('a', 'b')\n"
        res = detect_undefined_symbols(src, "python")
        self.assertEqual(res["suspects"], [])
        self.assertIn("Wildcard import", res["note"])

    def test_no_star_import_detection_unchanged(self):
        src = "import os\ndef f():\n    return magic_unknown()\n"
        res = detect_undefined_symbols(src, "python")
        self.assertIn("magic_unknown", res["suspects"])


class TestCommentApostropheDoesNotSwallowDefs(unittest.TestCase):
    """A 'don't' in a comment opened a multi-line 'rune literal' span that
    blanked following code — a same-file Go definition became a suspect
    (gin/auth.go: processAccounts). Single-quote string patterns for the
    char-literal languages are line-bounded now."""

    GO = (
        "// Credentials doesn't match, we return 401.\n"
        "// The user's id is set to the auth key.\n"
        "func handler(c *Context) { auth(c) }\n"
        "func auth(c *Context) bool { return true }\n"
    )

    def test_go_comment_apostrophe_keeps_definitions(self):
        res = detect_undefined_symbols(self.GO, "go")
        self.assertEqual(res["suspects"], [], res["suspects"])

    def test_go_real_hallucination_still_caught(self):
        src = "// doesn't match\nfunc handler(c *Context) { ghostAuth(c) }\n"
        res = detect_undefined_symbols(src, "go")
        self.assertEqual(res["suspects"], ["ghostAuth"])


class TestTypeScriptObjectDestructuring(unittest.TestCase):
    """`const {getPrototypeOf} = Object` is idiomatic real-world JS (axios);
    object destructuring was only collected for require()/import() calls, and
    raw-source scanning flagged JSDoc text ('EF BB BF (the UTF-8 BOM)') as a
    call."""

    AXIOS_LIKE = (
        "/**\n"
        " * Remove byte order marker. This catches EF BB BF (the UTF-8 BOM)\n"
        " */\n"
        "const {getPrototypeOf} = Object;\n"
        "const {isArray} = Array;\n"
        "const {a, b: renamed, c = 1, ...rest} = source;\n"
        "const stripBOM = (content) => content;\n"
        "if (isArray(list) || getPrototypeOf(obj)) { renamed(a, c, rest); }\n"
    )

    def test_destructured_names_and_comment_parens_are_clean(self):
        res = detect_undefined_symbols(self.AXIOS_LIKE, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])

    def test_object_destructure_hallucination_still_caught(self):
        src = "const {readFile: rf} = require('fs');\nreadFileGhost(path);\n"
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], ["readFileGhost"])

    def test_string_with_call_shape_is_not_a_call(self):
        src = 'const hint = "call help() if stuck";\n'
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])


    def test_browser_globals_are_known(self):
        src = (
            "const req = new XMLHttpRequest();\n"
            "new ReadableStream();\n"
            "unescape(x);\n"
            "new TypeError('e');\n"
        )
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])


class TestTypeScriptClassMethodsAndChains(unittest.TestCase):
    """Real-world class/object shapes (axios): definition sites that look
    like calls, method params, arrows reassigned to an existing variable,
    and member chains split across lines."""

    def test_class_methods_and_their_params_are_collected(self):
        src = (
            "class Client {\n"
            "  constructor(config) {\n"
            "    this.request(config);\n"
            "  }\n"
            "  request(config, cb) {\n"
            "    cb(null, config);\n"
            "  }\n"
            "}\n"
            "const http2Sessions = {\n"
            "  getSession(authority, options) {\n"
            "    return authority;\n"
            "  },\n"
            "};\n"
        )
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])

    def test_chained_call_split_across_lines_is_not_bare(self):
        src = (
            "const q = encodeURIComponent(value).\n"
            "  replace(/%3A/gi, ':').\n"
            "  replace(/%24/g, '$');\n"
        )
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])

    def test_chain_start_hallucination_still_caught(self):
        src = (
            "const q = ghostEncode(value).\n"
            "  replace(/%3A/gi, ':');\n"
        )
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], ["ghostEncode"])

    def test_arrow_reassigned_to_existing_var_collects_params(self):
        src = "let lookup;\nlookup = (hostname, opt, cb) => {\n  cb(null, opt);\n};\n"
        res = detect_undefined_symbols(src, "typescript")
        self.assertEqual(res["suspects"], [], res["suspects"])


class TestPythonNoqaAndDunder(unittest.TestCase):
    """Ecosystem conventions found in the django field test: forward-reference
    annotations marked `# NOQA: F821` (django's own tests) and dunder
    protocol names (__path__) must not be suspects."""

    def test_noqa_marked_line_is_not_flagged(self):
        src = "def func(arg: SomeType):  # NOQA: F821\n    return arg\n"
        res = detect_undefined_symbols(src)
        self.assertEqual(res["suspects"], [])

    def test_unmarked_forward_reference_still_caught(self):
        src = "def func(arg: SomeType):\n    return arg\n"
        res = detect_undefined_symbols(src)
        self.assertIn("SomeType", res["suspects"])

    def test_dunder_protocol_names_are_not_suspects(self):
        src = "for p in __path__:\n    print(p, __version__)\n"
        res = detect_undefined_symbols(src)
        self.assertEqual(res["suspects"], [])

    def test_noqa_name_on_another_line_is_still_caught(self):
        src = "def a():\n    return Ghost()\ndef b():\n    return Ghost()  # noqa\n"
        res = detect_undefined_symbols(src)
        self.assertIn("Ghost", res["suspects"])
        self.assertEqual(res["suspects_detail"][0]["line"], 2)


if __name__ == "__main__":
    unittest.main()
