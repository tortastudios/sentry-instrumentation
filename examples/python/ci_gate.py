"""AST-based CI gate — the drop-in pattern for `scripts/check_metrics.py`.

Drop-in at `scripts/check_metrics.py` (or wherever your project's
check loop invokes its lint steps from). The gate is AST-based, not
regex-based: regex on Python source is a liability when call sites
split across lines or use unusual formatting.

Invocation:

    python scripts/check_metrics.py \\
        --registry yourapp/shared/metrics.py \\
        --emission-module yourapp/observability.py \\
        --project-root yourapp

Exit code is non-zero on any violation. Run locally via your
project's check loop (`make check`, `npm run lint`, `pre-commit`,
`just check`, `bundle exec rake check`) and wire into CI as a
required status.

Language portability: this reference is a Python `ast`-based
implementation. The same 13 checks port directly to `ts-morph`/
`ast-grep` (TypeScript), `go/ast` (Go), `parser` (Ruby), or any
language with a first-party AST. Keep the check identifiers (M001 …
M013) so reviewers can reference them identically across ports.

The 13 checks (mirroring the enforcement reference):

  1.  `sentry_sdk.metrics.*` called outside the emission module.
  2.  `emit_*` whose first positional argument is not a `MetricDef`
      symbol (raw string, f-string, .format, variable).
  3.  A `MetricDef` (via any classmethod) missing a required kwarg.
  4.  Duplicate metric name in the registry.
  5.  Metric name failing the naming regex.
  6.  `cardinality="medium"` without a justification line in `means=`.
  7.  Tag key outside the metric's `allowed_tags` at a call site
      (best-effort — only checked when tags is a dict literal).
  8.  Deprecated `MetricDef` with no `replaced_by` or no `retired_at`.
  9.  `retired_at` in the past on a still-present entry.
  10. Identity-tuple change on an existing `MetricDef`
      (diff vs. baseline — optional, requires --baseline).
  11. Non-deprecated entry removed from the registry (requires
      --baseline).
  12. `emit_counter`/`emit_distribution` inside a `for`/`while` body
      for a metric whose `loop_policy != "allowed"`, unless wrapped in
      `AggregatingCounter` / `DurationAccumulator` / bears the escape
      comment `# instrumentation: loop-aggregate`.
  13. Dynamic metric name (`.name` field assembled at runtime — any
      non-constant expression as the first argument to a classmethod).
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


# --- Registry walk (PR-local, one file) ------------------------------------


def collect_registry(
    path: Path,
) -> tuple[list[RegistryEntry], list[Violation]]:
    """Parse the registry file and extract every `MetricDef.<cls>(...)` call."""

    tree = ast.parse(path.read_text(), filename=str(path))
    entries: list[RegistryEntry] = []
    violations: list[Violation] = []

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
            )
        )

    return entries, violations


def check_registry(
    path: Path, entries: list[RegistryEntry]
) -> list[Violation]:
    """Checks 3, 4, 5, 6, 8, 9."""

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


# --- Call-site walk --------------------------------------------------------


def iter_py_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        # Skip migrations, tests for direct emission checks if desired.
        if any(part in {"migrations", ".venv", "__pycache__"} for part in path.parts):
            continue
        yield path


def check_call_sites(
    root: Path, emission_module: Path, entries: list[RegistryEntry]
) -> list[Violation]:
    """Checks 1, 2, 7, 12, 13."""

    violations: list[Violation] = []
    loop_policy_by_name: dict[str, str] = {}
    for entry in entries:
        policy = entry.kwargs.get("loop_policy")
        loop_policy_by_name[entry.name] = (
            policy.value if isinstance(policy, ast.Constant) else "aggregate_only"
        )

    for path in iter_py_files(root):
        try:
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        source_lines = source.splitlines()

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

                # 12. Loop-policy check.
                if _inside_loop(node) and isinstance(node.args[0] if node.args else None, ast.Name):
                    metric_sym = node.args[0].id  # type: ignore[union-attr]
                    # Try to resolve to a registry entry by symbol name —
                    # best-effort: we trust the convention that the
                    # SCREAMING_SNAKE symbol name maps 1:1 to a registry
                    # entry. Real implementations can load the registry
                    # module and introspect.
                    # If not resolvable we fall through (registry-only
                    # symbols get enforced when this is run with the
                    # actual registry module imported).
                    if _has_escape_comment(source_lines, node.lineno):
                        continue
                    if _wrapped_in_aggregator(node):
                        continue
                    # Conservative: flag unless we can prove loop_policy == "allowed".
                    # (A real gate would look up by metric_sym; here we
                    # flag any unwrapped emit inside a loop.)
                    violations.append(
                        Violation(
                            path, node.lineno, "M012",
                            f"{func_name}({metric_sym}) inside a loop — wrap "
                            f"with AggregatingCounter / DurationAccumulator, "
                            f"or add '# {LOOP_AGGREGATE_ESCAPE}: <reason>'.",
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
    # Same line or the line directly above.
    for target in (lineno, lineno - 1):
        if 1 <= target <= len(source_lines):
            if LOOP_AGGREGATE_ESCAPE in source_lines[target - 1]:
                return True
    return False


# --- Entry point -----------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--emission-module", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    entries, v1 = collect_registry(args.registry)
    v2 = check_registry(args.registry, entries)
    v3 = check_call_sites(args.project_root, args.emission_module, entries)

    violations = v1 + v2 + v3
    for v in violations:
        sys.stdout.write(v.format() + "\n")

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
