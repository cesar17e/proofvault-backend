# ProofVault Mathematical Content Contract — `markdown-latex-v1`

**Status:** Proposed V1 contract; implementation and tests are required before claiming enforcement.  
**Applies to:** `entries.statement` (required) and `entries.proof` (optional).  
**Audience:** Backend/API, frontend/editor, and future embedding/search implementations.

## 1. Purpose and product scope

ProofVault is a private, proof-oriented mathematical library. Users save **theorem statements** and **proof-based problem statements**, together with optional proofs, explanations, or worked solutions. Content may contain serious mathematical notation, including matrices, convergence arguments, piecewise functions, logical symbols, and multiline derivations.

ProofVault **stores and retrieves** mathematical content; V1 does not prove the correctness of a statement, solve arbitrary exercises, or perform symbolic mathematics. The database stores the *original text*, not a compiled TeX document.

## 2. Accepted representation

Both `statement` and `proof` are **UTF-8 Unicode strings containing Markdown with optional LaTeX math**.

- Ordinary prose is plain text/Markdown.
- Inline math uses `$...$`.
- Display math uses `$$...$$` (may span multiple lines).
- Math delimiters may not be nested, and a literal dollar sign should be written as `\$`.
- V1 does **not** support `\(...\)` or `\[...\]` as math delimiters.
- LaTeX commands intended as mathematical notation should appear within math delimiters.
- Preserve source whitespace, line breaks, mathematical symbols, and backslashes. Only examine trimmed text to reject blank required fields; do **not** silently normalize or rewrite stored statements/proofs.
- JSON API clients must escape backslashes (`\\mathbb` in JSON represents `\mathbb` in the stored value). Frontend clients can use `JSON.stringify`.

This is a **math-fragment** format, not a complete `.tex` document format.

## 3. Supported notation (V1 target)

Support standard KaTeX-compatible mathematical notation, including:

- Fractions, radicals, subscripts, superscripts: `\frac`, `\sqrt`, `_`, `^`
- Limits, sums, products, integrals: `\lim`, `\sum`, `\prod`, `\int`
- Sets, relations, logic: `\mathbb`, `\in`, `\subseteq`, `\forall`, `\exists`, `\implies`
- Greek symbols, arrows, accents, and text in math: `\varepsilon`, `\delta`, `\to`, `\hat`, `\bar`, `\text`
- Font and operator commands: `\mathcal`, `\mathbf`, `\mathrm`, `\operatorname`
- Matrix, cases, and multiline equation environments, initially:
  `aligned`, `alignedat`, `array`, `matrix`, `pmatrix`, `bmatrix`, `Bmatrix`, `vmatrix`, `Vmatrix`, `cases`, `gathered`, `smallmatrix`.

Support a limited Markdown subset around math: paragraphs, line breaks, headings, emphasis, lists, blockquotes, and code spans/blocks. **No raw HTML.** If Markdown links are supported, sanitize their destinations and rendered HTML.

### Valid example: theorem statement

```markdown
Suppose $(a_n)$ is a real sequence. Prove that if $a_n \to L$, then $(a_n)$ is bounded.
```

### Valid example: matrix problem

```markdown
Let $A$ be the matrix

$$
A=\begin{bmatrix}
1 & 2 & 3 \\
0 & 1 & 4 \\
0 & 0 & 1
\end{bmatrix}
$$

Prove that $A$ is invertible.
```

### Valid example: aligned proof

```markdown
If $a_n \to L$, then for sufficiently large $n$,

$$
\begin{aligned}
|(3a_n+2)-(3L+2)|
  &=3|a_n-L| \\
  &<\varepsilon.
\end{aligned}
$$

Therefore $3a_n+2\to3L+2$.
```

### Valid example: piecewise function

```markdown
$$
f(x)=\begin{cases}
x^2, & x\ge 0, \\
-x, & x<0.
\end{cases}
$$
```

## 4. Out of scope / prohibited in V1

Do not support entire LaTeX documents, executable TeX, file/network access, raw HTML injection, or user-created macros. Examples of **prohibited commands** (illustrative, not an exhaustive secure-parser specification):

- Document/package commands: `\documentclass`, `\usepackage`, `\begin{document}`, `\end{document}`
- I/O and TeX internals: `\input`, `\include`, `\write`, `\read`, `\openin`, `\openout`, `\immediate`, `\special`, `\catcode`, `\csname`
- Macro/environment definitions: `\def`, `\gdef`, `\edef`, `\xdef`, `\let`, `\newcommand`, `\renewcommand`, `\providecommand`, `\newenvironment`, `\renewenvironment`
- LaTeX links, images, HTML injection: `\href`, `\url`, `\includegraphics`, `\htmlClass`, `\htmlId`, `\htmlStyle`, `\htmlData`

V1 does not support user-defined shortcuts such as `\newcommand{\R}{\mathbb{R}}`; users should write `\mathbb{R}` directly.

Malformed examples:

```text
$x^2 + y^2         # Missing closing math delimiter
\[x^2+y^2\]       # Unsupported delimiter form
\documentclass{article}  # Document-level command
```


## 5. Frontend responsibilities — when built

- Provide an editor for Markdown and `$...$`/`$$...$$` math.
- Render mathematical fragments with KaTeX (or an equivalently safe renderer), with `trust: false`.
- Sanitize Markdown-generated HTML and avoid directly injecting raw user text as HTML.
- Provide a preview and clear errors/warnings for unsupported KaTeX syntax.
- Never transform the persisted source based on rendering or normalization.
- If preview fails, show escaped original source rather than losing access to the entry.
- Match the backend content contract and keep shared tests/documentation synchronized.

## 6. Scope and change control

This document records the **intended contract**, not proof that the API already enforces it. Before marking Phase 3 complete, align Pydantic validators, API tests, frontend test cases, and documentation. Any expansion (new delimiter syntax, document imports, custom macros, formula-specific search) should be explicitly versioned instead of silently changing `markdown-latex-v1`.
