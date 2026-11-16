"""AST-based CI gate — the drop-in pattern for `scripts/check_metrics.py`.

Drop-in at `scripts/check_metrics.py` (or wherever your project's
check loop invokes its lint steps from). The gate is AST-based, not
regex-based: regex on Python source is a liability when call sites
split across lines or use unusual formatting.

Invocation:

    python scripts/check_metrics.py \\
        --registry yourapp/shared/metrics.py \\
        --emission-module yourapp/observability.py \\
        --project-root yourapp \\
        [--baseline /tmp/metrics_main.py]

`--baseline` is the registry file as it exists on the main branch
(`git show origin/main:yourapp/shared/metrics.py > /tmp/metrics_main.py`).
Checks 10 and 11 only run when it is given.

Exit code is non-zero on any violation. Run locally via your
project's check loop (`make check`, `npm run lint`, `pre-commit`,
`just check`, `bundle exec rake check`) and wire into CI as a
required status.

Language portability: this reference is a Python `ast`-based
implementation. The same 14 checks port directly to `ts-morph`/
`ast-grep` (TypeScript), `go/ast` (Go), `parser` (Ruby), or any
language with a first-party AST. Keep the check identifiers (M001 …
M014) so reviewers can reference them identically across ports.

The 14 checks (mirroring the enforcement reference):

  1.  `sentry_sdk.metrics.*` called outside the emission module.
  2.  `emit_*` whose first positional argument is not a `MetricDef`
      symbol (raw string, f-string, .format, variable).
  3.  A `MetricDef` (via any classmethod) missing a required kwarg.
  4.  Duplicate metric name in the registry.
  5.  Metric name failing the naming regex.
  6.  `cardinality="medium"` without a justification line in `means=`.
  7.  Group-by tag key outside the metric's `tags=` at a call site
      (best-effort — only checked when `tags=` is a dict literal and
      the metric symbol resolves to a definition).
  8.  Deprecated `MetricDef` with no `replaced_by` or no `retired_at`.
  9.  `retired_at` in the past on a still-present entry.
  10. Identity-tuple change on an existing `MetricDef`
      (diff vs. baseline — optional, requires --baseline).
  11. Non-deprecated entry removed from the registry (requires
      --baseline).
  12. `emit_*` inside a `for`/`while` body for a metric whose
      `loop_policy != "allowed"`, unless wrapped in
      `AggregatingCounter` / `DurationAccumulator` / bears the escape
      comment `# instrumentation: loop-aggregate`. `"forbidden"`
      ignores both escapes.
  13. Dynamic metric name (`.name` field assembled at runtime — any
      non-constant expression as the first argument to a classmethod).
  14. Debug-context attributes: a `context=` declaration that is not a
      literal collection of strings, that repeats a tag key, or that
      names a forbidden / reserved key; and a `context=` key at a call
      site that the metric does not declare.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# --- Configurables ---------------------------------------------------------

METRIC_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+(\.v\d+)?$")

# Classmethods on MetricDef. Each maps to the set of required kwargs.
METRIC_CLASSMETHODS: dict[str, frozenset[str]] = {
    "counter": frozenset({"purpose", "owner", "tags", "means", "emit_frequency"}),
    "latency": frozenset({"owner", "tags", "means", "emit_frequency"}),
    "gauge": frozenset({"unit", "owner", "tags", "means", "emit_frequency"}),
    "resource": frozenset({"unit", "owner", "tags", "means", "emit_frequency"}),
    "failure_counter": frozenset({"owner", "tags", "means", "emit_frequency"}),
}

EMIT_FUNCS: frozenset[str] = frozenset({
    "emit_counter",
    "emit_gauge",
    "emit_distribution",
    "emit_latency",
    "emit_failure",
})

AGGREGATORS: frozenset[str] = frozenset({
    "AggregatingCounter",
    "DurationAccumulator",
    "time_latency",
    "retry_with_instrumentation",
})

LOOP_AGGREGATE_ESCAPE = "instrumentation: loop-aggregate"

# Mirror of `FORBIDDEN_CONTEXT_KEYS` / `RESERVED_CONTEXT_PREFIXES` in
# the registry module — free-form text and direct personal data never
# go on a metric; `sentry.*` / `user.*` are filled in by the SDK.
FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset({
    "email", "user_email", "ip", "ip_address", "user_agent",
    "prompt", "completion", "message", "body", "text",
    "error", "error_message", "exception", "stack", "stacktrace",
    "url", "raw_url", "query", "query_string", "path",
})
RESERVED_CONTEXT_PREFIXES: tuple[str, ...] = ("sentry.", "user.")


# --- Data types ------------------------------------------------------------


@dataclass
class Violation:
    path: Path
    line: int
    code: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


@dataclass
class RegistryEntry:
    name: str
    classmethod: str
    line: int
    kwargs: dict[str, ast.expr] = field(default_factory=dict)
    symbol: str | None = None  # module-level name the MetricDef is bound to

    @property
    def tag_keys(self) -> frozenset[str] | None:
        """Declared tag keys, or None when `tags=` isn't a literal dict."""

        tags = self.kwargs.get("tags")
        if tags is None:
            keys: set[str] = set()
        elif isinstance(tags, ast.Dict) and all(
            isinstance(k, ast.Constant) and isinstance(k.value, str)
            for k in tags.keys
        ):
            keys = {k.value for k in tags.keys}  # type: ignore[union-attr]
        else:
            return None
        if self.classmethod == "failure_counter":
            keys.add("failure_class")
        return frozenset(keys)

    @property
    def context_keys(self) -> frozenset[str] | None:
        """Declared context keys, or None when `context=` isn't a literal."""

        return _literal_str_collection(self.kwargs.get("context"))

    @property
    def loop_policy(self) -> str:
        policy = self.kwargs.get("loop_policy")
        if isinstance(policy, ast.Constant) and isinstance(policy.value, str):
            return policy.value
        return "aggregate_only"

    @property
    def is_deprecated(self) -> bool:
        deprecated = self.kwargs.get("deprecated")
        return bool(isinstance(deprecated, ast.Constant) and deprecated.value)

    def identity(self) -> tuple[str, ...]:
        """Comparable form of (kind, unit, purpose, tags) for check 10."""

        def dump(key: str) -> str:
            node = self.kwargs.get(key)
            return ast.dump(node) if node is not None else ""

        return (self.classmethod, dump("unit"), dump("purpose"), dump("tags"))


def _literal_str_collection(node: ast.expr | None) -> frozenset[str] | None:
    """Resolve `{"a", "b"}` / `["a"]` / `("a",)` / `frozenset({...})`."""

    if node is None:
        return frozenset()
    if (
        isinstance(node, ast.Call)
        and _simple_name(node.func) in {"frozenset", "set"}
        and len(node.args) <= 1
        and not node.keywords
    ):
        return _literal_str_collection(node.args[0]) if node.args else frozenset()
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    ):
        return frozenset(e.value for e in node.elts)  # type: ignore[attr-defined]
    return None


# --- Registry walk (PR-local, one file) ------------------------------------


def collect_registry(
    path: Path,
) -> tuple[list[RegistryEntry], list[Violation]]:
    """Parse the registry file and extract every `MetricDef.<cls>(...)` call."""

    return _collect_from_tree(ast.parse(path.read_text(), filename=str(path)), path)


def _collect_from_tree(
    tree: ast.AST, path: Path
) -> tuple[list[RegistryEntry], list[Violation]]:
    entries: list[RegistryEntry] = []
    violations: list[Violation] = []

    # Map each MetricDef call to the name it is assigned to
    # (`CACHE_HIT = MetricDef.counter(...)`), so call sites can be
    # resolved back to their definition.
    # Module level only: a local `m = MetricDef...` inside a function
    # is not a stable symbol.
    symbol_by_call: dict[int, str] = {}
    for node in getattr(tree, "body", []):
        target: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if isinstance(target, ast.Name) and node.value is not None:  # type: ignore[union-attr]
            symbol_by_call[id(node.value)] = target.id  # type: ignore[union-attr]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match MetricDef.<cls>(...)
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "MetricDef"
            and node.func.attr in METRIC_CLASSMETHODS
        ):
            continue

        classmethod_name = node.func.attr

        # First positional arg = metric name.
        if not node.args:
            violations.append(
                Violation(
                    path, node.lineno, "M013",
                    f"MetricDef.{classmethod_name} called with no name argument.",
                )
            )
            continue
        name_arg = node.args[0]
        if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
            violations.append(
                Violation(
                    path, node.lineno, "M013",
                    f"MetricDef.{classmethod_name} name must be a string literal; "
                    f"dynamic names are forbidden.",
                )
            )
            continue

        name = name_arg.value
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        entries.append(
            RegistryEntry(
                name=name,
                classmethod=classmethod_name,
                line=node.lineno,
                kwargs=kwargs,
                symbol=symbol_by_call.get(id(node)),
            )
        )

    return entries, violations


def check_registry(
    path: Path, entries: list[RegistryEntry]
) -> list[Violation]:
    """Checks 3, 4, 5, 6, 8, 9, and the registry half of 14."""

    violations: list[Violation] = []
    seen_names: dict[str, int] = {}

    for entry in entries:
        # 4. Duplicate name.
        if entry.name in seen_names:
            violations.append(
                Violation(
                    path, entry.line, "M004",
                    f"Duplicate metric name {entry.name!r} "
                    f"(also defined at line {seen_names[entry.name]}).",
                )
            )
        else:
            seen_names[entry.name] = entry.line

        # 5. Name regex.
        if not METRIC_NAME_RE.match(entry.name):
            violations.append(
                Violation(
                    path, entry.line, "M005",
                    f"Metric name {entry.name!r} does not match "
                    f"<domain>.<object>.<action> (got {entry.name!r}).",
                )
            )

        # 3. Required fields.
        required = METRIC_CLASSMETHODS[entry.classmethod]
        missing = required - entry.kwargs.keys()
        if missing:
            violations.append(
                Violation(
                    path, entry.line, "M003",
                    f"MetricDef.{entry.classmethod} {entry.name!r} missing "
                    f"required kwargs: {sorted(missing)}.",
                )
            )

        # 6. medium cardinality requires justification in means=.
        cardinality = entry.kwargs.get("cardinality")
        if (
            isinstance(cardinality, ast.Constant)
            and cardinality.value == "medium"
        ):
            means = entry.kwargs.get("means")
            means_text = (
                means.value if isinstance(means, ast.Constant) else ""
            )
            if "justif" not in (means_text or "").lower():
                violations.append(
                    Violation(
                        path, entry.line, "M006",
                        f"Metric {entry.name!r} has cardinality='medium' but "
                        f"means= does not contain a justification "
                        f"(expect a 'Justification: ...' clause).",
                    )
                )

        # 14. Context declaration is literal, disjoint from tags, and safe.
        context_keys = entry.context_keys
        if context_keys is None:
            violations.append(
                Violation(
                    path, entry.line, "M014",
                    f"Metric {entry.name!r}: context= must be a literal "
                    f"collection of string keys.",
                )
            )
        else:
            overlap = context_keys & (entry.tag_keys or frozenset())
            if overlap:
                violations.append(
                    Violation(
                        path, entry.line, "M014",
                        f"Metric {entry.name!r}: {sorted(overlap)} declared "
                        f"as both a tag and a context attribute.",
                    )
                )
            bad = sorted(
                k for k in context_keys
                if k in FORBIDDEN_CONTEXT_KEYS
                or k.startswith(RESERVED_CONTEXT_PREFIXES)
            )
            if bad:
                violations.append(
                    Violation(
                        path, entry.line, "M014",
                        f"Metric {entry.name!r}: context keys {bad} are not "
                        f"allowed (free-form text, personal data, or an "
                        f"SDK-reserved namespace).",
                    )
                )

        # 8 & 9. Lifecycle.
        deprecated = entry.kwargs.get("deprecated")
        deprecated_value = (
            deprecated.value if isinstance(deprecated, ast.Constant) else False
        )
        if deprecated_value:
            if "replaced_by" not in entry.kwargs:
                violations.append(
                    Violation(
                        path, entry.line, "M008",
                        f"Deprecated metric {entry.name!r} is missing "
                        f"replaced_by=.",
                    )
                )
            if "retired_at" not in entry.kwargs:
                violations.append(
                    Violation(
                        path, entry.line, "M008",
                        f"Deprecated metric {entry.name!r} is missing "
                        f"retired_at=.",
                    )
                )

        retired_at = entry.kwargs.get("retired_at")
        if isinstance(retired_at, ast.Call):
            # Expect date(YYYY, M, D)
            try:
                y, m, d = (
                    arg.value for arg in retired_at.args
                    if isinstance(arg, ast.Constant)
                )
                if date(y, m, d) < date.today():
                    violations.append(
                        Violation(
                            path, entry.line, "M009",
                            f"Metric {entry.name!r} has retired_at in the "
                            f"past ({y}-{m:02d}-{d:02d}); remove the entry.",
                        )
                    )
            except (ValueError, TypeError):
                pass

    return violations


def check_baseline(
    path: Path, entries: list[RegistryEntry], baseline: list[RegistryEntry]
) -> list[Violation]:
    """Checks 10 and 11 — compare against the main-branch registry."""

    violations: list[Violation] = []
    current = {entry.name: entry for entry in entries}
    for old in baseline:
        new = current.get(old.name)
        if new is None:
            if not old.is_deprecated:
                violations.append(
                    Violation(
                        path, 1, "M011",
                        f"Metric {old.name!r} was removed without first being "
                        f"deprecated (deprecated=True + retired_at).",
                    )
                )
        elif new.identity() != old.identity():
            violations.append(
                Violation(
                    path, new.line, "M010",
                    f"Metric {old.name!r} changed kind, unit, purpose, or "
                    f"tags in place — register a new versioned name instead.",
                )
            )
    return violations


# --- Call-site walk --------------------------------------------------------


def iter_py_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        if any(part in {"migrations", ".venv", "__pycache__"} for part in path.parts):
            continue
        # Tests misuse the helpers on purpose to prove they raise.
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        yield path


def check_call_sites(
    root: Path, emission_module: Path, entries: list[RegistryEntry]
) -> list[Violation]:
    """Checks 1, 2, 7, 12, and the call-site half of 14."""

    violations: list[Violation] = []
    registry_symbols = {e.symbol: e for e in entries if e.symbol}

    for path in iter_py_files(root):
        try:
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        source_lines = source.splitlines()

        # Metric symbols visible here: the registry's, plus any defined
        # in this file (surface patterns define theirs next to the code).
        local_entries, _ = _collect_from_tree(tree, path)
        symbols = {
            **registry_symbols,
            **{e.symbol: e for e in local_entries if e.symbol},
        }

        # Build parent and loop-depth maps via a single walker.
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child._parent = parent  # type: ignore[attr-defined]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # 1. sentry_sdk.metrics.* outside the emission module.
            if (
                path.resolve() != emission_module.resolve()
                and _is_sentry_metrics_call(node)
            ):
                violations.append(
                    Violation(
                        path, node.lineno, "M001",
                        "sentry_sdk.metrics.* may only be called from the "
                        "emission module — use emit_* wrappers.",
                    )
                )

            # The emission module implements the helpers; its internal
            # `emit_counter(self.metric, ...)` forwarding is not a call site.
            if path.resolve() == emission_module.resolve():
                continue

            func_name = _simple_name(node.func)

            # 2 & 13. emit_* first arg must be a Name referencing a MetricDef.
            if func_name in EMIT_FUNCS:
                if not node.args:
                    violations.append(
                        Violation(
                            path, node.lineno, "M002",
                            f"{func_name} called with no metric argument.",
                        )
                    )
                else:
                    first = node.args[0]
                    if not isinstance(first, ast.Name):
                        violations.append(
                            Violation(
                                path, node.lineno, "M002",
                                f"{func_name} first argument must be a "
                                f"MetricDef symbol (got "
                                f"{type(first).__name__}).",
                            )
                        )

                    resolved = (
                        symbols.get(first.id) if isinstance(first, ast.Name) else None
                    )
                    if resolved is not None:
                        violations.extend(
                            _check_attribute_keys(path, node, func_name, resolved)
                        )

                # 12. Loop-policy check.
                if _inside_loop(node) and isinstance(node.args[0] if node.args else None, ast.Name):
                    metric_sym = node.args[0].id  # type: ignore[union-attr]
                    entry = symbols.get(metric_sym)
                    # Unresolvable symbols are treated as the default
                    # policy ("aggregate_only").
                    policy = entry.loop_policy if entry else "aggregate_only"
                    if policy == "allowed":
                        continue
                    if policy == "forbidden":
                        violations.append(
                            Violation(
                                path, node.lineno, "M012",
                                f"{func_name}({metric_sym}) inside a loop — "
                                f"loop_policy='forbidden' for this metric.",
                            )
                        )
                        continue
                    if _has_escape_comment(source_lines, node.lineno):
                        continue
                    if _wrapped_in_aggregator(node):
                        continue
                    violations.append(
                        Violation(
                            path, node.lineno, "M012",
                            f"{func_name}({metric_sym}) inside a loop — wrap "
                            f"with AggregatingCounter / DurationAccumulator, "
                            f"or add '# {LOOP_AGGREGATE_ESCAPE}: <reason>'.",
                        )
                    )

    return violations


def _check_attribute_keys(
    path: Path, call: ast.Call, func_name: str, entry: RegistryEntry
) -> list[Violation]:
    """Checks 7 (tags=) and 14 (context=) for one resolved emit call."""

    violations: list[Violation] = []
    for kwarg, code, declared, label in (
        ("tags", "M007", entry.tag_keys, "tag"),
        ("context", "M014", entry.context_keys, "context"),
    ):
        value = next((kw.value for kw in call.keywords if kw.arg == kwarg), None)
        if declared is None or not isinstance(value, ast.Dict):
            continue  # best-effort: literals only
        for key in value.keys:
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value not in declared:
                violations.append(
                    Violation(
                        path, call.lineno, code,
                        f"{func_name}({entry.symbol}): {label} key "
                        f"{key.value!r} is not declared on {entry.name!r} "
                        f"(declared: {sorted(declared)}).",
                    )
                )
    return violations


# --- AST helpers -----------------------------------------------------------


def _simple_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _is_sentry_metrics_call(call: ast.Call) -> bool:
    # sentry_sdk.metrics.incr(...) / distribution(...) / gauge(...)
    fn = call.func
    if not isinstance(fn, ast.Attribute):
        return False
    if not isinstance(fn.value, ast.Attribute):
        return False
    if fn.value.attr != "metrics":
        return False
    if not isinstance(fn.value.value, ast.Name):
        return False
    return fn.value.value.id == "sentry_sdk"


def _inside_loop(node: ast.AST) -> bool:
    cur = getattr(node, "_parent", None)
    while cur is not None:
        if isinstance(cur, (ast.For, ast.AsyncFor, ast.While)):
            return True
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # Nested function scope — treat as a fresh frame; emits
            # inside a helper called from a loop aren't detectable
            # statically.
            return False
        cur = getattr(cur, "_parent", None)
    return False


def _wrapped_in_aggregator(node: ast.AST) -> bool:
    """True if an ancestor is a `with AggregatingCounter(...)` (etc.) block."""

    cur = getattr(node, "_parent", None)
    while cur is not None:
        if isinstance(cur, (ast.With, ast.AsyncWith)):
            for item in cur.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call):
                    name = _simple_name(ctx.func)
                    if name in AGGREGATORS:
                        return True
        cur = getattr(cur, "_parent", None)
    return False


def _has_escape_comment(source_lines: list[str], lineno: int) -> bool:
    # Trailing comment on the same line, or a comment-only line directly
    # above (a trailing comment on the previous statement doesn't count).
    if 1 <= lineno <= len(source_lines):
        if LOOP_AGGREGATE_ESCAPE in source_lines[lineno - 1]:
            return True
    if 2 <= lineno <= len(source_lines) + 1:
        above = source_lines[lineno - 2].strip()
        if above.startswith("#") and LOOP_AGGREGATE_ESCAPE in above:
            return True
    return False


# --- Entry point -----------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--emission-module", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="Registry file from the main branch; enables checks M010/M011.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries, v1 = collect_registry(args.registry)
    v2 = check_registry(args.registry, entries)
    v3 = check_call_sites(args.project_root, args.emission_module, entries)

    violations = v1 + v2 + v3
    if args.baseline is not None:
        baseline_entries, _ = collect_registry(args.baseline)
        violations += check_baseline(args.registry, entries, baseline_entries)
    for v in violations:
        sys.stdout.write(v.format() + "\n")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
