import re

import pytest

from app.validation import validate_markdown_latex


@pytest.mark.parametrize(
    "source",
    [
        "Suppose $(a_n)$ is real and $a_n \\to L$.",
        """Let $A$ be the matrix

$$
A=\\begin{bmatrix}
1 & 2 & 3 \\\\
0 & 1 & 4
\\end{bmatrix}
$$
""",
        """$$
\\begin{aligned}
|(3a_n+2)-(3L+2)| &= 3|a_n-L| \\\\
&<\\varepsilon.
\\end{aligned}
$$""",
        """$$
f(x)=\\begin{cases}
x^2, & x\\ge 0, \\\\
-x, & x<0.
\\end{cases}
$$""",
        "The price is \\$5, while $x<y$ is mathematical.",
    ],
)
def test_valid_contract_examples_are_preserved(source: str) -> None:
    assert validate_markdown_latex(source) == source


def test_markdown_code_regions_are_not_interpreted_as_active_markup() -> None:
    source = """Use `\\documentclass`, `$`, and `<b>` as literal examples.

```latex
\\documentclass{article}
<script>not active</script>
$unclosed
```

Then use $x^2$ normally.
"""

    assert validate_markdown_latex(source) == source


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("The value is $x^2.", "inline math delimiter"),
        ("$$x^2", "display math delimiter"),
        (r"Use \(x^2\).", "not supported"),
        (r"Use \[x^2\].", "not supported"),
        ("$x $$ y$", "may not be nested"),
        ("$$x $ y$$", "may not be nested"),
        ("$x\ny$", "may not span multiple lines"),
        ("<script>alert('x')</script>", "raw HTML"),
        (r"$\input{secret}$", r"\input"),
        (r"$\newcommand{\R}{\mathbb{R}}$", r"\newcommand"),
        (r"$\htmlClass{bad}{x}$", r"\htmlClass"),
        (r"\mathbb{R}", "must appear inside math delimiters"),
        (r"$\begin{document}x\end{document}$", "not supported"),
        (r"$\begin{matrix}x\end{cases}$", "not correctly nested"),
        (r"$\begin{matrix}x$", "not closed"),
        (r"$\frac{x{y}$", "unmatched opening brace"),
        ("text\u0000value", "control characters"),
    ],
)
def test_invalid_contract_content_is_rejected(source: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        validate_markdown_latex(source)
