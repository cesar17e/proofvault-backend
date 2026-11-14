"""Validation for ProofVault's ``markdown-latex-v1`` content format.

The validator is intentionally a storage-policy validator, not a TeX compiler
or KaTeX renderer. It recognizes Markdown code regions, validates the agreed
math delimiters and environments, and rejects constructs that ProofVault must
never treat as mathematical content.
"""

from __future__ import annotations

import re


ALLOWED_ENVIRONMENTS = frozenset(
    {
        "aligned",
        "alignedat",
        "array",
        "matrix",
        "pmatrix",
        "bmatrix",
        "Bmatrix",
        "vmatrix",
        "Vmatrix",
        "cases",
        "gathered",
        "smallmatrix",
    }
)

# These commands cover the prohibited classes in the V1 contract. The source
# is never executed; this list is an application content policy rather than a
# claim to sandbox a general TeX engine.
PROHIBITED_COMMANDS = frozenset(
    {
        # Complete documents and package loading.
        "documentclass",
        "usepackage",
        "RequirePackage",
        "includeonly",
        "require",
        # File, network, output, and TeX engine primitives.
        "input",
        "include",
        "import",
        "subimport",
        "write",
        "read",
        "openin",
        "openout",
        "closein",
        "closeout",
        "immediate",
        "special",
        "shipout",
        "catcode",
        "csname",
        "endcsname",
        "expandafter",
        "noexpand",
        "global",
        "futurelet",
        "loop",
        "repeat",
        "verb",
        # Macro, operator, and environment definitions.
        "def",
        "gdef",
        "edef",
        "xdef",
        "let",
        "newcommand",
        "renewcommand",
        "providecommand",
        "DeclareMathOperator",
        "newenvironment",
        "renewenvironment",
        # External resources and renderer-specific HTML injection.
        "href",
        "url",
        "includegraphics",
        "htmlClass",
        "htmlId",
        "htmlStyle",
        "htmlData",
    }
)

_COMMAND_RE = re.compile(r"[A-Za-z@]+")
_ENVIRONMENT_RE = re.compile(r"\s*\{([^{}]+)\}")
_RAW_HTML_RE = re.compile(
    r"(?:<!--|<!DOCTYPE\b|<\?|</?[A-Za-z][A-Za-z0-9-]*"
    r"(?:\s+[^<>\n]*)?/?>)",
    re.IGNORECASE,
)


def validate_markdown_latex(value: str) -> str:
    """Validate and return one mathematical Markdown source unchanged.

    Inline/fenced Markdown code regions are deliberately ignored while
    examining LaTeX and raw HTML. This matches their eventual safe-rendering
    semantics: text shown as code is not active mathematical markup.
    """

    _reject_control_characters(value)

    state = "text"
    fence_character: str | None = None
    fence_length = 0
    inline_code_length = 0
    brace_depth = 0
    environment_stack: list[str] = []
    line_start = True
    index = 0

    while index < len(value):
        if state == "fenced_code":
            if line_start:
                closing_length = _closing_fence_length(
                    value,
                    index,
                    fence_character,
                    fence_length,
                )
                if closing_length is not None:
                    index = _after_current_line(value, index)
                    state = "text"
                    fence_character = None
                    fence_length = 0
                    line_start = True
                    continue

            index, line_start = _skip_one_character(value, index)
            continue

        if state == "inline_code":
            if value[index] == "`":
                run_length = _run_length(value, index, "`")
                if run_length == inline_code_length:
                    index += run_length
                    state = "text"
                    line_start = False
                    continue

            index, line_start = _skip_one_character(value, index)
            continue

        if state == "text" and line_start:
            opening_fence = _opening_fence(value, index)
            if opening_fence is not None:
                fence_character, fence_length = opening_fence
                index = _after_current_line(value, index)
                state = "fenced_code"
                line_start = True
                continue

            if value.startswith("    ", index) or value.startswith("\t", index):
                index = _after_current_line(value, index)
                line_start = True
                continue

        character = value[index]

        if state == "text" and character == "`":
            run_length = _run_length(value, index, "`")
            if _has_matching_backtick_run(value, index + run_length, run_length):
                inline_code_length = run_length
                state = "inline_code"
                index += run_length
                line_start = False
                continue

        if state == "text" and character == "<":
            if _RAW_HTML_RE.match(value, index) is not None:
                raise ValueError("raw HTML is not supported")

        if character == "\\" and not _is_escaped(value, index):
            unsupported_delimiter = _unsupported_delimiter_at(value, index)
            if unsupported_delimiter is not None:
                raise ValueError(
                    f"math delimiter '{unsupported_delimiter}' is not supported; "
                    "use '$...$' or '$$...$$'"
                )

            command_match = _COMMAND_RE.match(value, index + 1)
            if command_match is not None:
                command = command_match.group(0)
                _validate_command(command, state)

                if state in {"inline_math", "display_math"} and command in {
                    "begin",
                    "end",
                }:
                    _validate_environment(
                        value,
                        command_match.end(),
                        command,
                        environment_stack,
                    )

                index = command_match.end()
                line_start = False
                continue

            # Escaped punctuation and TeX's ``\\`` line break are data, not
            # the beginning of another command.
            if index + 1 < len(value):
                index += 2
                line_start = False
                continue

        if state == "text" and character == "$" and not _is_escaped(value, index):
            run_length = _run_length(value, index, "$")
            if run_length not in {1, 2}:
                raise ValueError("math delimiters must be '$' or '$$'")

            state = "inline_math" if run_length == 1 else "display_math"
            brace_depth = 0
            environment_stack.clear()
            index += run_length
            line_start = False
            continue

        if state == "inline_math":
            if character == "\n":
                raise ValueError("inline math may not span multiple lines")

            if character == "$" and not _is_escaped(value, index):
                run_length = _run_length(value, index, "$")
                if run_length != 1:
                    raise ValueError("math delimiters may not be nested")
                _ensure_math_expression_closed(brace_depth, environment_stack)
                state = "text"
                index += 1
                line_start = False
                continue

        if state == "display_math" and character == "$" and not _is_escaped(
            value,
            index,
        ):
            run_length = _run_length(value, index, "$")
            if run_length != 2:
                raise ValueError("math delimiters may not be nested")
            _ensure_math_expression_closed(brace_depth, environment_stack)
            state = "text"
            index += 2
            line_start = False
            continue

        if state in {"inline_math", "display_math"}:
            if character == "{" and not _is_escaped(value, index):
                brace_depth += 1
            elif character == "}" and not _is_escaped(value, index):
                brace_depth -= 1
                if brace_depth < 0:
                    raise ValueError("math contains an unmatched closing brace")

        index, line_start = _skip_one_character(value, index)

    if state == "inline_code":
        # This state is currently unreachable because an inline code span is
        # opened only when a matching run exists. Keep the guard defensive.
        raise ValueError("Markdown code span is not closed")
    if state == "inline_math":
        raise ValueError("inline math delimiter '$' is not closed")
    if state == "display_math":
        raise ValueError("display math delimiter '$$' is not closed")

    # CommonMark treats an unclosed fenced block as code until end-of-input,
    # so ``fenced_code`` is a valid terminal state.
    return value


def _reject_control_characters(value: str) -> None:
    for character in value:
        code_point = ord(character)
        if (code_point < 32 and character not in {"\t", "\n", "\r"}) or (
            127 <= code_point <= 159
        ):
            raise ValueError("control characters are not supported")


def _validate_command(command: str, state: str) -> None:
    if command in PROHIBITED_COMMANDS or command.lower().startswith("html"):
        raise ValueError(f"LaTeX command '\\{command}' is not supported")

    if "@" in command:
        raise ValueError("internal TeX commands are not supported")

    if state == "text":
        raise ValueError(
            f"LaTeX command '\\{command}' must appear inside math delimiters"
        )


def _validate_environment(
    value: str,
    command_end: int,
    command: str,
    environment_stack: list[str],
) -> None:
    environment_match = _ENVIRONMENT_RE.match(value, command_end)
    if environment_match is None:
        raise ValueError(f"LaTeX command '\\{command}' requires an environment name")

    environment = environment_match.group(1)
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ValueError(f"LaTeX environment '{environment}' is not supported")

    if command == "begin":
        environment_stack.append(environment)
        return

    if not environment_stack or environment_stack[-1] != environment:
        raise ValueError(f"LaTeX environment '{environment}' is not correctly nested")
    environment_stack.pop()


def _ensure_math_expression_closed(
    brace_depth: int,
    environment_stack: list[str],
) -> None:
    if brace_depth != 0:
        raise ValueError("math contains an unmatched opening brace")
    if environment_stack:
        raise ValueError(
            f"LaTeX environment '{environment_stack[-1]}' is not closed"
        )


def _unsupported_delimiter_at(value: str, index: int) -> str | None:
    for delimiter in ("\\(", "\\)", "\\[", "\\]"):
        if value.startswith(delimiter, index):
            return delimiter
    return None


def _is_escaped(value: str, index: int) -> bool:
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def _run_length(value: str, index: int, character: str) -> int:
    cursor = index
    while cursor < len(value) and value[cursor] == character:
        cursor += 1
    return cursor - index


def _has_matching_backtick_run(value: str, start: int, length: int) -> bool:
    cursor = start
    while cursor < len(value):
        if value[cursor] != "`":
            cursor += 1
            continue

        run_length = _run_length(value, cursor, "`")
        if run_length == length:
            return True
        cursor += run_length
    return False


def _opening_fence(value: str, index: int) -> tuple[str, int] | None:
    line_end = value.find("\n", index)
    if line_end == -1:
        line_end = len(value)
    line = value[index:line_end]
    match = re.match(r" {0,3}(`{3,}|~{3,})", line)
    if match is None:
        return None
    marker = match.group(1)
    return marker[0], len(marker)


def _closing_fence_length(
    value: str,
    index: int,
    fence_character: str | None,
    minimum_length: int,
) -> int | None:
    if fence_character is None:
        return None

    line_end = value.find("\n", index)
    if line_end == -1:
        line_end = len(value)
    line = value[index:line_end]
    match = re.fullmatch(
        rf" {{0,3}}({re.escape(fence_character)}{{{minimum_length},}})[ \t]*",
        line,
    )
    if match is None:
        return None
    return len(match.group(1))


def _after_current_line(value: str, index: int) -> int:
    newline_index = value.find("\n", index)
    if newline_index == -1:
        return len(value)
    return newline_index + 1


def _skip_one_character(value: str, index: int) -> tuple[int, bool]:
    return index + 1, value[index] == "\n"
