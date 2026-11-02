#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idiolect.py: análise estilométrica do corpus do autor e comparação de textos novos com o estilo dele.

Uso:
  python scripts/idiolect.py analyze              lê data/*.md e gera reports/metrics.{json,md} e reports/vocabulary.json
  python scripts/idiolect.py compare ARQUIVO.md   mede um texto contra o corpus e mostra onde ele destoa

Só usa a biblioteca padrão do Python (3.9+). Os resultados de analyze são determinísticos.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LANG_DIR = Path(__file__).resolve().parent / "lang"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
SCHEMA_VERSION = 2

# Seções que nunca entram na análise (não refletem a prosa do autor).
SKIP_SECTIONS = {"front_matter", "references", "acknowledgements", "appendix"}

# Palavras exclusivas de cada idioma, usadas para descartar parágrafos e documentos em outra língua
# (ex.: o "Abstract" de uma dissertação em português). Só entram as palavras que não existem nos outros.
_LANG_WORDS = {
    "pt": "o os do dos da das ao aos não são é à às um uma foi mais também pelo pela pelos pelas seu sua seus "
          "suas isso esse essa esses essas nas nos numa em que para com como se de e ou mas ser está estão",
    "en": "the of and to in is are for with that this by on as an from be which was were it its these their "
          "has have been or not can such than also between into",
    "es": "el los del y es al lo más son fue sus una un está muy pero según entre con por que como se de la "
          "las en para o ser",
}
_LANG_SETS = {k: set(v.split()) for k, v in _LANG_WORDS.items()}
LANG_MARKERS = {k: v - set().union(*(o for j, o in _LANG_SETS.items() if j != k)) for k, v in _LANG_SETS.items()}


def detect_language(tokens: list[str], min_hits: int = 4) -> str | None:
    """Retorna 'pt', 'en', 'es' ou None (texto curto demais para decidir)."""
    scores = {k: sum(1 for t in tokens if t in m) for k, m in LANG_MARKERS.items()}
    best = max(scores, key=scores.get)
    if scores[best] < min_hits:
        return None
    return best

# Marcador neutro usado no lugar de equações, código, citações e citações diretas.
# Não é letra, então não conta como palavra.
P = "∎"

# Frases com menos palavras do que isto são descartadas (restos de títulos, legendas, etc.).
MIN_SENTENCE_TOKENS = 3

# Marcador que substitui o nome do autor numa citação narrativa ("Silva (2019) afirma" -> "‹autor› afirma").
AUTHOR = "‹autor›"

WORD_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)
TOKEN_RE = re.compile(r"‹autor›|[^\W\d_]+(?:[-'’][^\W\d_]+)*", re.UNICODE)
# Versão que mantém a pontuação interna como token, para que expressões não "atravessem" vírgulas.
MATCH_TOKEN_RE = re.compile(r"‹autor›|[^\W\d_]+(?:[-'’][^\W\d_]+)*|[,;:()\[\]—–]", re.UNICODE)
UPPER = "A-ZÀ-ÖØ-Þ"


def setup_stdout() -> None:
    """Garante saída UTF-8 também no console do Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in TOKEN_RE.findall(text)]


def match_tokenize(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in MATCH_TOKEN_RE.findall(text)]


def is_word(token: str) -> bool:
    return not token.startswith("‹")


# ---------------------------------------------------------------------------
# Recursos de idioma
# ---------------------------------------------------------------------------

def read_sectioned(path: Path) -> dict[str, list[str]]:
    """Lê um arquivo com seções [nome] e um item por linha (# inicia comentário)."""
    data: dict[str, list[str]] = defaultdict(list)
    current = "_"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"\[([^\]]+)\]", line)
        if m:
            current = m.group(1).strip()
        else:
            data[current].append(line)
    return data


class PhraseMatcher:
    """Busca expressões (de uma ou várias palavras) numa lista de tokens, com casamento mais longo primeiro."""

    def __init__(self, phrases):
        self.index: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        self.phrases: list[str] = []
        for p in phrases:
            toks = tuple(tokenize(p))
            if toks and toks not in self.index[toks[0]]:
                self.index[toks[0]].append(toks)
                self.phrases.append(" ".join(toks))
        for k in self.index:
            self.index[k].sort(key=len, reverse=True)

    def find(self, tokens: list[str]) -> list[tuple[str, int]]:
        out, i, n = [], 0, len(tokens)
        while i < n:
            hit = None
            for cand in self.index.get(tokens[i], ()):
                if tuple(tokens[i:i + len(cand)]) == cand:
                    hit = cand
                    break
            if hit:
                out.append((" ".join(hit), i))
                i += len(hit)
            else:
                i += 1
        return out


@dataclass
class Resources:
    lang: str
    iso: str
    stopwords: set
    abbreviations: list
    connective_category: dict
    first_person_singular: set
    first_person_plural: set
    plural_verb_exclusions: set
    sections: list
    connectives: PhraseMatcher
    hedges: PhraseMatcher
    boosters: PhraseMatcher
    impersonal: PhraseMatcher
    ai_markers: PhraseMatcher
    abbrev_re: re.Pattern


def available_languages() -> list[str]:
    return sorted(p.stem for p in LANG_DIR.glob("*.txt"))


def load_resources(lang: str) -> Resources:
    path = LANG_DIR / f"{lang}.txt"
    if not path.exists():
        raise SystemExit(
            f"Não há recursos para o idioma '{lang}' em {LANG_DIR}. Disponíveis: {', '.join(available_languages())}. "
            "Para outro idioma, copie pt-BR.txt e traduza as listas."
        )
    d = read_sectioned(path)
    meta = dict(x.split(":", 1) for x in d.get("meta", []) if ":" in x)
    category = {}
    for sec, items in d.items():
        if sec.startswith("connectives."):
            for it in items:
                category[" ".join(tokenize(it))] = sec.split(".", 1)[1]
    sections = []
    for line in d.get("sections", []):
        name, _, rx = line.partition(":")
        sections.append((name.strip(), re.compile(rx.strip())))
    abbrevs = [a.lower() for a in d.get("abbreviations", [])]
    abbrev_re = re.compile(
        r"(?<![\w.])(" + "|".join(re.escape(a) for a in sorted(set(abbrevs), key=len, reverse=True)) + r")",
        re.IGNORECASE,
    )
    return Resources(
        lang=lang,
        iso=meta.get("iso", lang.split("-")[0]).strip(),
        stopwords=set(w.lower() for w in d.get("stopwords", [])),
        abbreviations=abbrevs,
        connective_category=category,
        first_person_singular=set(d.get("first_person.singular", [])),
        first_person_plural=set(d.get("first_person.plural", [])),
        plural_verb_exclusions=set(d.get("first_person.verb_exclusions", [])),
        sections=sections,
        connectives=PhraseMatcher(category.keys()),
        hedges=PhraseMatcher(d.get("hedges", [])),
        boosters=PhraseMatcher(d.get("boosters", [])),
        impersonal=PhraseMatcher(d.get("impersonal", [])),
        ai_markers=PhraseMatcher(d.get("ai_markers", [])),
        abbrev_re=abbrev_re,
    )


# ---------------------------------------------------------------------------
# Front matter (subconjunto simples de YAML, sem dependências)
# ---------------------------------------------------------------------------

def _parse_scalar(v: str):
    v = v.strip()
    if not v:
        return None
    if v[0] in "\"'":
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    if v.startswith("[") and v.endswith("]"):
        return [_parse_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    low = v.lower()
    if low in ("true", "yes", "sim"):
        return True
    if low in ("false", "no", "não", "nao"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    last_key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and last_key:
            if not isinstance(meta.get(last_key), list):
                meta[last_key] = []
            meta[last_key].append(_parse_scalar(item.group(1)))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if kv:
            last_key = kv.group(1)
            meta[last_key] = _parse_scalar(kv.group(2))
    return meta, text[m.end():]


def as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None]
    return [s.strip() for s in str(v).split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Blocos de Markdown e seções
# ---------------------------------------------------------------------------

LIST_RE = re.compile(r"^(?:[-*+]|\d+[.)]|\\item)\s+")


def parse_blocks(body: str) -> list[list]:
    """Divide o corpo em blocos [tipo, texto, nível]. Tipos: heading, paragraph, list, quote, table, footnote."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    blocks: list[list] = []
    buf: list[str] = []
    kind = None

    def flush():
        nonlocal buf, kind
        if buf and kind:
            blocks.append([kind, " ".join(x.strip() for x in buf), 0])
        buf, kind = [], None

    fence = None
    in_math = False
    env = None
    for line in body.splitlines():
        s = line.strip()
        if fence:
            if s.startswith(fence):
                fence = None
            continue
        if in_math:
            if s.endswith("$$") or s.endswith("\\]"):
                in_math = False
            continue
        if env:
            if s.startswith("\\end{" + env + "}"):
                env = None
            continue
        if s.startswith("```") or s.startswith("~~~"):
            flush()
            fence = s[:3]
            continue
        if s.startswith("$$") or s.startswith("\\["):
            flush()
            closed = (len(s) >= 4 and s.endswith("$$")) or (s.startswith("\\[") and s.endswith("\\]") and len(s) > 2)
            if not closed:
                in_math = True
            continue
        mb = re.match(r"\\begin\{([^}]+)\}", s)
        if mb and mb.group(1) not in ("itemize", "enumerate", "quote", "quotation", "citacao"):
            flush()
            if "\\end{" + mb.group(1) + "}" not in s:
                env = mb.group(1)
            continue
        if re.match(r"\\(begin|end)\{", s) or s.startswith(":::"):
            flush()
            continue
        if not s:
            flush()
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", s)
        if h:
            flush()
            blocks.append(["heading", h.group(2), len(h.group(1))])
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
            continue
        if re.match(r"^\[\^[^\]]+\]:", s):
            flush()
            kind, buf = "footnote", [s]
            continue
        if s.startswith(">"):
            if kind != "quote":
                flush()
                kind = "quote"
            buf.append(s.lstrip("> ").strip())
            continue
        if s.startswith("|") or re.fullmatch(r"[\s|:+-]+", s) and "|" in s:
            if kind != "table":
                flush()
                kind = "table"
            buf.append(s)
            continue
        if LIST_RE.match(s):
            flush()
            kind, buf = "list", [LIST_RE.sub("", s)]
            continue
        if kind in ("paragraph", "list", "quote", "footnote"):
            buf.append(s)
        else:
            flush()
            kind, buf = "paragraph", [s]
    flush()
    # Linha inteira em negrito e curta ("**Resumo**", "**AGRADECIMENTOS**") pode ser um título.
    for b in blocks:
        if b[0] == "paragraph" and BOLDLINE_RE.fullmatch(b[1]):
            b[0] = "boldline"
    return blocks


BOLDLINE_RE = re.compile(r"\*\*([^*]{2,100})\*\*\s*:?")


def classify_heading(title: str, res: Resources) -> str | None:
    t = strip_accents(title.lower())
    t = re.sub(r"[*_`#]", "", t).strip()
    t = re.sub(r"^(?:cap[ií]tulo\s+)?(?:\d+(?:\.\d+)*|[ivxlc]+)\s*[.)\-–:]?\s+", "", t)
    for name, rx in res.sections:
        if rx.search(t):
            return name
    return None


def assign_sections(blocks: list[list], res: Resources) -> list[tuple[str, str, str, str]]:
    """Retorna [(tipo, texto, seção_canônica, título_atual)].

    Um título reconhecido (ex.: "Metodologia") define a seção. Um título não reconhecido herda a seção do
    título de nível superior; se não houver, vira "other". O texto antes do primeiro título fica em "body".
    """
    current, heading = "body", ""
    stack: dict[int, str] = {}
    out = []
    for kind, text, lvl in blocks:
        if kind == "boldline":
            if not classify_heading(text, res):
                out.append(("paragraph", text, current, heading))
                continue
            kind, lvl = "heading", 1
        if kind == "heading":
            for k in [k for k in stack if k >= lvl]:
                del stack[k]
            canon = classify_heading(text, res)
            if not canon:
                canon = stack[max(stack)] if stack else "other"
            stack[lvl] = canon
            current, heading = canon, text
        out.append((kind, text, current, heading))
    return out


# ---------------------------------------------------------------------------
# Limpeza inline, citações e frases
# ---------------------------------------------------------------------------

LATEX_CITE_RE = re.compile(r"\\(cite\w*|apud\w*|textcite|parencite|autocite)\*?(?:\[[^\]]*\])*\{")
LATEX_NARRATIVE = {"citeonline", "citet", "textcite", "citeauthor", "citeauthoronline", "citeyear"}


def clean_inline(t: str) -> str:
    t = t.replace("``", "“").replace("''", "”")
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[\^[^\]]+\]", "", t)
    t = re.sub(r"\{[#.][^}]*\}", "", t)
    t = re.sub(r"\$\$.*?\$\$", f" {P} ", t)
    t = re.sub(r"(?<!\\)\$[^$]+?(?<!\\)\$", f" {P} ", t)
    t = re.sub(r"\\\(.*?\\\)", f" {P} ", t)
    t = re.sub(r"`[^`]*`", f" {P} ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    # restos de LaTeX (citação narrativa vira ‹autor›; as demais, marcador neutro)
    t = re.sub(r"\\(?:citeonline|citet|textcite|citeauthor|citeauthoronline)\*?(?:\[[^\]]*\])*\{[^}]*\}",
               f" {AUTHOR} ", t)
    t = re.sub(r"\\(?:cite\w*|apud\w*|textcite|parencite|autocite|ref|eqref|autoref|cref|Cref|label|footnote|url)\*?"
               r"(?:\[[^\]]*\])*\{[^}]*\}(?:\{[^}]*\})?", f" {P} ", t)
    t = re.sub(r"\\(?:textit|textbf|emph|textsc|texttt|underline|mbox|text|textup)\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"\1", t)
    t = re.sub(r"\\([%&_#$])", r"\1", t)
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = t.replace("~", " ").replace("{", "").replace("}", "")
    # ênfase Markdown
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


QUOTE_RES = [
    re.compile(r"“([^“”]{1,2000})”"),
    re.compile(r'"([^"]{1,2000})"'),
    re.compile(r"«([^«»]{1,2000})»"),
]


def remove_long_quotes(t: str) -> tuple[str, int]:
    """Remove citações diretas curtas (entre aspas, 4+ palavras): são palavras de outros autores."""
    n = 0

    def rep(m):
        nonlocal n
        inner = m.group(1)
        if len(WORD_RE.findall(inner)) >= 4:
            n += 1
            end = inner.rstrip()[-1:]
            return f" {P}{end} " if end in ".!?" else f" {P} "
        return m.group(0)

    for rx in QUOTE_RES:
        t = rx.sub(rep, t)
    return t, n


PAREN_CITE_RE = re.compile(
    rf"\((?=[^()]*\b[{UPPER}]{{2,}}[{UPPER}'’\-]*\b)(?=[^()]*(?:\b1[5-9]\d\d|\b20\d\d|s\.\s?d\.))[^()]{{3,400}}\)"
    rf"|\([{UPPER}][^()]{{0,200}}?,\s*(?:1[5-9]\d\d|20\d\d)[a-z]?\b[^()]{{0,80}}\)"
)
PANDOC_PAREN_RE = re.compile(r"\[[^\[\]]*?@[\w:.\-]+[^\[\]]*?\]")
PANDOC_NARR_RE = re.compile(r"(?<![\w@\[])@([A-Za-z_][\w:.\-]*\w)")
NAME = rf"[{UPPER}][\wÀ-ÿ'’\-]+"
CAPS_NARR_RE = re.compile(
    rf"\b([{UPPER}]{{2,}}(?:\s+(?:e|&)\s+[{UPPER}]{{2,}}|\s+et\s+al\.?)?)\s*\(\s*(?:1[5-9]\d\d|20\d\d)[a-z]?[^()]{{0,40}}\)"
)
NARR_RE = re.compile(
    rf"\b({NAME}(?:\s+(?:e|and|&)\s+{NAME}|\s+et\s+al\.?|\s*,\s*{NAME})*)\s*\(\s*(?:1[5-9]\d\d|20\d\d)[a-z]?"
    rf"(?:\s*[,;]\s*(?:p|pp)\.?\s*[\d\-–]+)?\s*\)"
)
STOP_AFTER_CITATION = {"e", "ou", "mas", "que", "a", "o", "as", "os", "de", "da", "do", "em", "no", "na", "um", "uma",
                       "com", "para", "por", "se", "como"}
APUD_RE = re.compile(r"\bapud\b", re.IGNORECASE)
VERB_AFTER_RE = re.compile(r"^\s*(?:,(?:\s*[^\W\d_]+){1,4}\s*,\s*)?([a-zà-ÿ][^\W\d_]*(?:-se)?)")


def detect_citations(t: str, cites: Counter, frames: Counter, verbs: Counter) -> str:
    cites["apud"] += len(APUD_RE.findall(t))

    def paren(m):
        cites["parenthetical"] += 1
        if ";" in m.group(0):
            cites["parenthetical_multiple"] += 1
        return f" {P} "

    def narrative(m):
        cites["narrative"] += 1
        prefix = re.split(r"[.!?;:]\s+", m.string[:m.start()])[-1]
        ptoks = tokenize(prefix)
        if not ptoks:
            frames["(autor como sujeito no início da frase)"] += 1
        elif len(ptoks) <= 4:
            frames[" ".join(ptoks)] += 1
        else:
            frames["(no meio da frase)"] += 1
        vm = VERB_AFTER_RE.match(m.string[m.end():])
        if vm and vm.group(1).lower() not in STOP_AFTER_CITATION:
            verbs[vm.group(1).lower()] += 1
        return f" {AUTHOR} "

    t = PANDOC_PAREN_RE.sub(paren, t)
    t = PAREN_CITE_RE.sub(paren, t)
    t = PANDOC_NARR_RE.sub(narrative, t)
    t = CAPS_NARR_RE.sub(narrative, t)
    t = NARR_RE.sub(narrative, t)
    return t


SENT_SPLIT_RE = re.compile(
    rf"(?:(?<=[.!?…])|(?<=[.!?…][\"”’»)\]]))\s+(?=[\"“«(\[]?[{UPPER}0-9{P}‹])"
)
INITIAL_RE = re.compile(rf"\b([{UPPER}])\.(?=\s*[{UPPER}‹])")


def split_sentences(t: str, res: Resources) -> list[str]:
    t = res.abbrev_re.sub(lambda m: m.group(0).replace(".", "\x00"), t)
    t = INITIAL_RE.sub(lambda m: m.group(1) + "\x00", t)
    parts = SENT_SPLIT_RE.split(t)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------

@dataclass
class Paragraph:
    doc_id: str
    section: str
    kind: str  # "paragraph" ou "list"
    sentences: list
    tokens: list
    mtokens: list  # tokens com pontuação, usados na busca de expressões
    citations: Counter
    cite_frames: Counter
    cite_verbs: Counter
    quotes: int

    @property
    def n_tokens(self) -> int:
        return sum(len(t) for t in self.tokens)


@dataclass
class Document:
    doc_id: str
    path: str
    meta: dict
    paragraphs: list
    block_quotes: int = 0
    language: str = ""
    dropped: Counter = field(default_factory=Counter)
    sections_found: Counter = field(default_factory=Counter)
    sections_excluded: Counter = field(default_factory=Counter)

    @property
    def n_tokens(self) -> int:
        return sum(p.n_tokens for p in self.paragraphs)


def process_paragraph(raw: str, kind: str, section: str, res: Resources, doc_id: str) -> Paragraph:
    cites, frames, verbs = Counter(), Counter(), Counter()
    for m in LATEX_CITE_RE.finditer(raw):
        cites["narrative" if m.group(1).lower() in LATEX_NARRATIVE else "parenthetical"] += 1
    t = clean_inline(raw)
    t, nq = remove_long_quotes(t)
    t = detect_citations(t, cites, frames, verbs)
    sents, toks, mtoks = [], [], []
    for s in split_sentences(t, res):
        tk = tokenize(s)
        if len(tk) >= MIN_SENTENCE_TOKENS:
            sents.append(s)
            toks.append(tk)
            mtoks.append(match_tokenize(s))
    return Paragraph(doc_id, section, kind, sents, toks, mtoks, cites, frames, verbs, nq)


# Legendas, fontes e palavras-chave não são prosa do autor.
CAPTION_RE = re.compile(
    r"^[*_]*(figura|fig\.|tabela|quadro|gr[aá]fico|imagem|ilustra[cç][aã]o|mapa|equa[cç][aã]o|figure|table|chart)"
    r"\s*[\dIVX]+[*_]*\s*[–—\-:.]", re.IGNORECASE)
SOURCE_RE = re.compile(r"^[*_]*(fonte|source|elabora[cç][aã]o|nota)\s*[*_]*\s*:", re.IGNORECASE)
KEYWORDS_RE = re.compile(r"^[*_]*(palavras?[- ]chave|keywords?|key words|palabras clave)", re.IGNORECASE)
ABSTRACT_LABEL_RE = re.compile(r"^\*\*(resumo|abstract|resumen|r[ée]sum[ée])\s*:?\s*\*\*\s*:?\s*", re.IGNORECASE)
SENTENCE_END_RE = re.compile(r"[.!?:;…][\"”’»)\]*_]*\s*$")
# Parágrafos curtos sem pontuação final (capa, título, nome do autor, cabeçalhos soltos) são descartados.
FRAGMENT_MAX_TOKENS = 20
# Legendas de fórmulas: "onde: Xt é a mediana...", "α é o parâmetro de escala...".
WHERE_RE = re.compile(r"^(onde|em que|sendo|no qual|na qual|nas quais|nos quais)\s*(:|∎|[^\W\d_]{1,3}\d*\s)",
                      re.IGNORECASE)
SYMBOL_DEF_RE = re.compile(r"^[*_$\\]*([^\W\d_]{1,3}[\w{}^_]*)[*_$]*\s*(?:\([^)]*\)\s*)?(é|são|representa|corresponde|=)\s")


def guess_type(name: str) -> str:
    n = strip_accents(name.lower())
    for key, t in (("tcc", "undergraduate_thesis"), ("monografia", "undergraduate_thesis"),
                   ("dissert", "dissertation"), ("tese", "doctoral_thesis"), ("thesis", "doctoral_thesis"),
                   ("artigo", "article"), ("article", "article"), ("paper", "article"),
                   ("capitulo", "book_chapter"), ("chapter", "book_chapter")):
        if key in n:
            return t
    return "other"


def process_document(path: Path, res: Resources, apply_filters: bool = True, text: str | None = None) -> Document:
    if text is None:
        text = path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(text)
    doc_id = path.stem
    doc = Document(doc_id, str(path), meta, [])
    own = set(as_list(meta.get("own_sections")))
    excluded = set(as_list(meta.get("exclude_sections")))
    coauthored = bool(meta.get("coauthored"))
    blocks = assign_sections(parse_blocks(body), res)
    has_headings = any(b[0] == "heading" for b in blocks)
    for kind, txt, sec, _heading in blocks:
        if kind == "heading":
            continue
        if kind == "quote":
            doc.block_quotes += 1
            continue
        if kind not in ("paragraph", "list"):
            continue
        if CAPTION_RE.match(txt) or SOURCE_RE.match(txt) or KEYWORDS_RE.match(txt):
            doc.dropped["legendas, fontes e palavras-chave"] += 1
            continue
        if WHERE_RE.match(clean_inline(txt)):
            doc.dropped["legendas de fórmulas"] += 1
            continue
        sd = SYMBOL_DEF_RE.match(txt)
        if sd and sd.group(1).lower() not in res.stopwords and len(txt.split()) < 30:
            doc.dropped["legendas de fórmulas"] += 1
            continue
        m = ABSTRACT_LABEL_RE.match(txt)
        if m:
            sec, txt = "abstract", txt[m.end():]
        elif sec == "body" and has_headings and apply_filters:
            # Texto antes do primeiro título: capa, folha de rosto, afiliações.
            doc.dropped["texto antes do primeiro título (capa, folha de rosto)"] += 1
            continue
        doc.sections_found[sec] += 1
        if sec in SKIP_SECTIONS or sec in excluded:
            doc.sections_excluded[sec] += 1
            continue
        if apply_filters and coauthored and own and sec not in own:
            doc.sections_excluded[sec] += 1
            continue
        cleaned = clean_inline(txt)
        ctoks = tokenize(cleaned)
        if len(ctoks) < FRAGMENT_MAX_TOKENS and not SENTENCE_END_RE.search(cleaned):
            doc.dropped["fragmentos sem pontuação final (capa, títulos)"] += 1
            continue
        lang = detect_language(ctoks)
        if lang and lang != res.iso:
            doc.dropped[f"parágrafos em outro idioma ({lang})"] += 1
            continue
        p = process_paragraph(txt, kind, sec, res, doc_id)
        if p.sentences:
            doc.paragraphs.append(p)
    return doc


def load_corpus(data_dir: Path, res: Resources):
    """Carrega todos os .md de data_dir (recursivo). Arquivos iniciados por '_' e README.md são ignorados.

    O cabeçalho YAML é opcional. Sem ele, o idioma é detectado automaticamente e o tipo é inferido do nome.
    """
    docs, skipped = [], []
    for path in sorted(data_dir.rglob("*.md")):
        if path.name.startswith("_") or path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8-sig")
        meta, body = parse_frontmatter(text)
        if meta.get("include") is False:
            skipped.append({"file": path.name, "reason": "include: false"})
            continue
        declared = meta.get("language")
        lang = str(declared).split("-")[0].lower() if declared else detect_language(tokenize(body)[:20000], 20)
        if lang and lang != res.iso:
            how = "declarado" if declared else "detectado"
            skipped.append({"file": path.name, "reason": f"idioma {how}: {lang} (análise atual: {res.lang})"})
            continue
        doc = process_document(path, res, text=text)
        doc.language = lang or "?"
        doc.meta.setdefault("type", guess_type(path.stem))
        if doc.n_tokens == 0:
            skipped.append({"file": path.name, "reason": "nenhum parágrafo analisável"})
            continue
        docs.append(doc)
    return docs, skipped


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

PASSIVE_RE = re.compile(
    r"\b(é|são|foi|foram|era|eram|será|serão|seria|seriam|seja|sejam|fosse|fossem|for|forem|sido|ser|sendo)"
    r"\s+(?:[^\W\d_]+mente\s+)?([^\W\d_]+)\b"
)
PARTICIPLE_RE = re.compile(r"^[^\W\d_]{2,}(?:ad|id)[oa]s?$")
IRREGULAR_PARTICIPLES = {
    "feito", "feita", "feitos", "feitas", "dito", "dita", "ditos", "ditas", "visto", "vista", "vistos", "vistas",
    "posto", "posta", "postos", "postas", "escrito", "escrita", "escritos", "escritas", "aberto", "aberta",
    "abertos", "abertas", "coberto", "coberta", "descoberto", "descoberta", "proposto", "proposta", "propostos",
    "propostas", "exposto", "exposta", "expostos", "expostas", "imposto", "imposta", "composto", "composta",
    "compostos", "compostas", "disposto", "disposta", "aceito", "aceita", "aceitos", "aceitas", "eleito", "eleita",
    "eleitos", "eleitas", "entregue", "entregues", "pago", "paga", "ganho", "gasto", "gasta", "morto", "morta",
    "preso", "presa", "suspenso", "suspensa", "expresso", "expressa", "impresso", "impressa", "submetido",
    "incluso", "inclusa", "omisso", "extinto", "extinta", "envolto", "envolta", "resolvido", "resolvida",
}
NON_PARTICIPLES = {
    "válido", "válida", "válidos", "válidas", "rápido", "rápida", "rápidos", "rápidas", "sólido", "sólida",
    "líquido", "líquida", "nítido", "nítida", "úmido", "úmida", "lúcido", "lúcida", "tímido", "tímida",
    "ácido", "ácida", "árido", "árida", "pálido", "pálida", "cuidado", "estado", "lado", "mercado", "resultado",
    "resultados", "significado", "passado", "grado", "agrado", "senado", "fado", "dado", "dados",
}
NOMINAL_RE = re.compile(r"(ção|ções|são|sões|mento|mentos|dade|dades|ência|ências|ância|âncias|ismo|ismos|ura|uras)$")
FP_VERB_RE = re.compile(r"^[^\W\d_]{2,}(?:amos|emos|imos|ímos|omos)$")
SUPERLATIVE_RE = re.compile(r"(íssim[oa]s|ésim[oa]s)$")


def describe(values) -> dict | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None

    def pct(q):
        if len(vals) == 1:
            return vals[0]
        k = (len(vals) - 1) * q
        f, c = math.floor(k), math.ceil(k)
        return vals[f] + (vals[c] - vals[f]) * (k - f)

    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "sd": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
        "min": round(vals[0], 3),
        "p10": round(pct(0.10), 3),
        "p25": round(pct(0.25), 3),
        "median": round(pct(0.5), 3),
        "p75": round(pct(0.75), 3),
        "p90": round(pct(0.90), 3),
        "max": round(vals[-1], 3),
    }


def mattr(tokens: list[str], window: int = 100) -> float | None:
    """Moving-Average Type-Token Ratio: diversidade lexical estável para textos de tamanhos diferentes."""
    if not tokens:
        return None
    if len(tokens) < window:
        return len(set(tokens)) / len(tokens)
    counts = Counter(tokens[:window])
    total, n = len(counts), 1
    for i in range(window, len(tokens)):
        out = tokens[i - window]
        counts[out] -= 1
        if counts[out] == 0:
            del counts[out]
        counts[tokens[i]] += 1
        total += len(counts)
        n += 1
    return total / n / window


def is_participle(w: str) -> bool:
    if w in NON_PARTICIPLES:
        return False
    return w in IRREGULAR_PARTICIPLES or bool(PARTICIPLE_RE.match(w))


def analyze(pars: list[Paragraph], res: Resources, detail: bool = True) -> dict:
    """Calcula contagens brutas e distribuições para um conjunto de parágrafos."""
    A = {
        "n_tokens": 0, "n_sentences": 0, "n_paragraphs": 0, "n_list_items": 0,
        "sentence_lengths": [], "paragraph_words": [], "paragraph_sentences": [],
        "single_sentence_paragraphs": 0, "questions": 0,
        "words": Counter(), "chars": 0, "long_words": 0, "nominalizations": 0,
        "conn_total": Counter(), "conn_sentence_initial": Counter(), "conn_paragraph_initial": Counter(),
        "conn_paragraph_final": Counter(), "conn_category": Counter(), "sentences_conn_initial": 0,
        "hedges": Counter(), "boosters": Counter(), "impersonal": Counter(), "ai_markers": Counter(),
        "passive": 0, "passive_examples": Counter(), "se_enclitic": Counter(), "se_free": 0,
        "fp_singular": Counter(), "fp_plural": Counter(), "fp_plural_verbs": Counter(),
        "punct": Counter(), "open1": Counter(), "open2": Counter(), "par_open3": Counter(),
        "ngrams": {2: Counter(), 3: Counter(), 4: Counter()},
        "citations": Counter(), "cite_frames": Counter(), "cite_verbs": Counter(), "quotes": 0,
    }
    stream: list[str] = []
    for p in pars:
        A["citations"].update(p.citations)
        A["cite_frames"].update(p.cite_frames)
        A["cite_verbs"].update(p.cite_verbs)
        A["quotes"] += p.quotes
        is_par = p.kind == "paragraph"
        last = len(p.sentences) - 1
        pw = 0
        for si, (s, tk, mt) in enumerate(zip(p.sentences, p.tokens, p.mtokens)):
            L = len(tk)
            A["n_sentences"] += 1
            A["n_tokens"] += L
            pw += L
            if is_par:
                A["sentence_lengths"].append(L)
            stream.extend(tk)
            A["words"].update(tk)
            for w in tk:
                if not is_word(w):
                    continue
                A["chars"] += len(w)
                if len(w) >= 10:
                    A["long_words"] += 1
                if len(w) > 5 and NOMINAL_RE.search(w):
                    A["nominalizations"] += 1
                if w.endswith("-se") or "-se-" in w:
                    A["se_enclitic"][w] += 1
                elif w == "se":
                    A["se_free"] += 1
                if w in res.first_person_singular:
                    A["fp_singular"][w] += 1
                elif w in res.first_person_plural:
                    A["fp_plural"][w] += 1
                elif FP_VERB_RE.match(w) and w not in res.plural_verb_exclusions and not SUPERLATIVE_RE.search(w):
                    A["fp_plural_verbs"][w] += 1
            pc = A["punct"]
            pc[","] += s.count(",")
            pc[";"] += s.count(";")
            pc[":"] += s.count(":")
            pc["("] += s.count("(")
            pc["—"] += s.count("—") + s.count("–") + len(re.findall(r"\s-\s", s))
            pc["?"] += s.count("?")
            pc["!"] += s.count("!")
            if s.rstrip().endswith("?"):
                A["questions"] += 1
            hits = res.connectives.find(mt)
            for ph, pos in hits:
                A["conn_total"][ph] += 1
                A["conn_category"][res.connective_category.get(ph, "?")] += 1
                if pos == 0:
                    A["conn_sentence_initial"][ph] += 1
                    if si == 0:
                        A["conn_paragraph_initial"][ph] += 1
                    elif si == last:
                        A["conn_paragraph_final"][ph] += 1
            if hits and hits[0][1] == 0:
                A["sentences_conn_initial"] += 1
            for key, matcher in (("hedges", res.hedges), ("boosters", res.boosters),
                                 ("impersonal", res.impersonal), ("ai_markers", res.ai_markers)):
                for ph, _ in matcher.find(mt):
                    A[key][ph] += 1
            for m in PASSIVE_RE.finditer(s.lower()):
                if is_participle(m.group(2)):
                    A["passive"] += 1
                    A["passive_examples"][f"{m.group(1)} {m.group(2)}"] += 1
            A["open1"][tk[0]] += 1
            A["open2"][" ".join(tk[:2])] += 1
            if si == 0:
                A["par_open3"][" ".join(tk[:3])] += 1
            if detail:
                for n in (2, 3, 4):
                    for i in range(L - n + 1):
                        A["ngrams"][n][" ".join(tk[i:i + n])] += 1
        if is_par:
            A["n_paragraphs"] += 1
            A["paragraph_words"].append(pw)
            A["paragraph_sentences"].append(len(p.sentences))
            if len(p.sentences) == 1:
                A["single_sentence_paragraphs"] += 1
        else:
            A["n_list_items"] += 1
    A["mattr_100"] = mattr(stream, 100)
    return A


def _rate(x, n, per):
    return round(per * x / n, 3) if n else 0.0


def scalar_features(A: dict) -> dict:
    """Indicadores numéricos comparáveis entre trechos do corpus e textos novos."""
    n, ns = A["n_tokens"], A["n_sentences"]
    sl = A["sentence_lengths"]
    pw = A["paragraph_words"]
    fp = sum(A["fp_singular"].values()) + sum(A["fp_plural"].values()) + sum(A["fp_plural_verbs"].values())
    cites = A["citations"]["parenthetical"] + A["citations"]["narrative"]
    return {
        "mean_sentence_length": round(statistics.fmean(sl), 3) if sl else None,
        "sd_sentence_length": round(statistics.stdev(sl), 3) if len(sl) > 1 else None,
        "mean_paragraph_words": round(statistics.fmean(pw), 3) if pw else None,
        "mean_paragraph_sentences": round(statistics.fmean(A["paragraph_sentences"]), 3) if pw else None,
        "commas_per_sentence": round(A["punct"][","] / ns, 3) if ns else None,
        "semicolons_per_1k_words": _rate(A["punct"][";"], n, 1000),
        "colons_per_1k_words": _rate(A["punct"][":"], n, 1000),
        "parentheses_per_1k_words": _rate(A["punct"]["("], n, 1000),
        "connectives_per_1k_words": _rate(sum(A["conn_total"].values()), n, 1000),
        "sentence_initial_connective_share": round(A["sentences_conn_initial"] / ns, 3) if ns else None,
        "hedges_per_1k_words": _rate(sum(A["hedges"].values()), n, 1000),
        "boosters_per_1k_words": _rate(sum(A["boosters"].values()), n, 1000),
        "impersonal_per_1k_words": _rate(sum(A["impersonal"].values()), n, 1000),
        "passive_per_100_sentences": _rate(A["passive"], ns, 100),
        "se_enclitic_per_1k_words": _rate(sum(A["se_enclitic"].values()), n, 1000),
        "first_person_per_1k_words": _rate(fp, n, 1000),
        "nominalizations_per_100_words": _rate(A["nominalizations"], n, 100),
        "mean_word_length": round(A["chars"] / n, 3) if n else None,
        "long_word_share": round(A["long_words"] / n, 3) if n else None,
        "mattr_100": round(A["mattr_100"], 4) if A["mattr_100"] is not None else None,
        "citations_per_1k_words": _rate(cites, n, 1000),
    }


FEATURE_LABELS = {
    "mean_sentence_length": "Tamanho médio da frase (palavras)",
    "sd_sentence_length": "Variação do tamanho das frases (desvio-padrão)",
    "mean_paragraph_words": "Tamanho médio do parágrafo (palavras)",
    "mean_paragraph_sentences": "Frases por parágrafo",
    "commas_per_sentence": "Vírgulas por frase",
    "semicolons_per_1k_words": "Ponto e vírgula / 1.000 palavras",
    "colons_per_1k_words": "Dois-pontos / 1.000 palavras",
    "parentheses_per_1k_words": "Parênteses / 1.000 palavras",
    "connectives_per_1k_words": "Conectivos / 1.000 palavras",
    "sentence_initial_connective_share": "Proporção de frases que começam com conectivo",
    "hedges_per_1k_words": "Atenuadores / 1.000 palavras",
    "boosters_per_1k_words": "Intensificadores / 1.000 palavras",
    "impersonal_per_1k_words": "Construções impessoais / 1.000 palavras",
    "passive_per_100_sentences": "Voz passiva analítica / 100 frases (estimativa)",
    "se_enclitic_per_1k_words": "Formas com -se (pode-se, observa-se) / 1.000 palavras",
    "first_person_per_1k_words": "Primeira pessoa / 1.000 palavras (estimativa)",
    "nominalizations_per_100_words": "Nominalizações (-ção, -mento, -dade...) / 100 palavras",
    "mean_word_length": "Tamanho médio da palavra (letras)",
    "long_word_share": "Proporção de palavras longas (10+ letras)",
    "mattr_100": "Diversidade lexical (MATTR, janela 100)",
    "citations_per_1k_words": "Citações / 1.000 palavras",
}


# ---------------------------------------------------------------------------
# Trechos (chunks) e perfil de palavras funcionais (Delta de Burrows)
# ---------------------------------------------------------------------------

def make_chunks(docs: list[Document], size: int) -> list[list[Paragraph]]:
    """Divide cada documento em trechos de ~size palavras, respeitando parágrafos."""
    chunks: list[list[Paragraph]] = []
    for d in docs:
        cur, n, first_of_doc = [], 0, len(chunks)
        for p in d.paragraphs:
            cur.append(p)
            n += p.n_tokens
            if n >= size:
                chunks.append(cur)
                cur, n = [], 0
        if cur:
            if n < size * 0.4 and len(chunks) > first_of_doc:
                chunks[-1].extend(cur)
            elif n >= min(200, size * 0.4):
                chunks.append(cur)
    return chunks


def word_vector(counter: Counter, n: int, words: list[str]) -> list[float]:
    return [1000.0 * counter[w] / n if n else 0.0 for w in words]


def delta(vec: list[float], means: list[float], sds: list[float]) -> float | None:
    zs = [abs((v - m) / s) for v, m, s in zip(vec, means, sds) if s > 0]
    return round(statistics.fmean(zs), 4) if zs else None


# ======================= ANALYZE =======================


TOP_WORDS = 150
TOP_NGRAMS = 60
N_FUNCTION_WORDS = 100


def per10k(x, n):
    return round(10000 * x / n, 2) if n else 0.0


def top_list(counter: Counter, n_tokens: int, k: int, key="item", min_count=1, docfreq=None):
    out = []
    for item, c in counter.most_common():
        if c < min_count or len(out) >= k:
            break
        row = {key: item, "count": c, "per_10k": per10k(c, n_tokens)}
        if docfreq is not None:
            row["docs"] = docfreq.get(item, 0)
        out.append(row)
    return out


def section_summary(pars, res):
    A = analyze(pars, res, detail=False)
    s = scalar_features(A)
    n = A["n_tokens"]
    return {
        "paragraphs": A["n_paragraphs"],
        "words": n,
        "mean_sentence_length": s["mean_sentence_length"],
        "mean_paragraph_words": s["mean_paragraph_words"],
        "sentence_initial_connective_share": s["sentence_initial_connective_share"],
        "hedges_per_1k_words": s["hedges_per_1k_words"],
        "boosters_per_1k_words": s["boosters_per_1k_words"],
        "passive_per_100_sentences": s["passive_per_100_sentences"],
        "first_person_per_1k_words": s["first_person_per_1k_words"],
        "citations_per_1k_words": s["citations_per_1k_words"],
        "top_sentence_initial_connectives": top_list(A["conn_sentence_initial"], n, 8, "phrase"),
        "top_paragraph_openers": top_list(A["par_open3"], n, 8, "opener"),
    }


def compute_baseline(docs, res, size: int, function_words: list[str]) -> dict:
    """Distribuição dos indicadores e do Delta de Burrows entre trechos de ~size palavras do corpus."""
    chunks = make_chunks(docs, size)
    feats, counters = [], []
    for ch in chunks:
        Ac = analyze(ch, res, detail=False)
        feats.append(scalar_features(Ac))
        counters.append((Ac["words"], Ac["n_tokens"]))
    features = {key: describe([f[key] for f in feats]) for key in feats[0]} if feats else {}
    fw_stats, delta_info = {}, None
    if len(chunks) >= 3:
        vecs = [word_vector(c, nt, function_words) for c, nt in counters]
        cols = list(zip(*vecs))
        means = [statistics.fmean(col) for col in cols]
        sds = [statistics.stdev(col) for col in cols]
        fw_stats = {w: [round(m, 4), round(sd, 4)] for w, m, sd in zip(function_words, means, sds)}
        # Delta de cada trecho contra os demais (leave-one-out), para saber a variação natural do autor.
        k = len(vecs)
        sums = [sum(col) for col in cols]
        sqs = [sum(x * x for x in col) for col in cols]
        own = []
        for v in vecs:
            mi = [(sm - x) / (k - 1) for sm, x in zip(sums, v)]
            si = [math.sqrt(max((sq - x * x - (k - 1) * m * m) / (k - 2), 0.0)) if k > 2 else 0.0
                  for sq, x, m in zip(sqs, v, mi)]
            own.append(delta(v, mi, si))
        delta_info = describe(own)
    return {"chunk_size": size, "n_chunks": len(chunks), "features": features,
            "function_words": fw_stats, "delta_own_chunks": delta_info}


def pick_baseline(M: dict, n_words: int) -> dict:
    """Escolhe a linha de base de tamanho mais próximo (sem passar muito) do texto comparado."""
    bl = [b for b in M["baselines"].values() if b["n_chunks"] >= 3] or list(M["baselines"].values())
    bl.sort(key=lambda b: b["chunk_size"])
    fit = [b for b in bl if b["chunk_size"] <= n_words * 1.25]
    return fit[-1] if fit else bl[0]


def build_metrics(docs, skipped, res, chunk_sizes, data_dir):
    all_pars = [p for d in docs for p in d.paragraphs]
    A = analyze(all_pars, res, detail=True)
    n = A["n_tokens"]
    sw = res.stopwords

    # Frequência por documento (em quantos documentos cada item aparece)
    word_docs, ngram_docs, conn_docs = Counter(), Counter(), Counter()
    doc_rows = []
    for d in docs:
        Ad = analyze(d.paragraphs, res, detail=True)
        word_docs.update(set(Ad["words"]))
        for k in (2, 3, 4):
            ngram_docs.update(set(Ad["ngrams"][k]))
        conn_docs.update(set(Ad["conn_total"]))
        sd = scalar_features(Ad)
        m = d.meta
        doc_rows.append({
            "file": Path(d.path).name,
            "title": m.get("title"),
            "type": m.get("type"),
            "year": m.get("year"),
            "coauthored": bool(m.get("coauthored")),
            "own_sections": as_list(m.get("own_sections")),
            "words": Ad["n_tokens"],
            "sentences": Ad["n_sentences"],
            "paragraphs": Ad["n_paragraphs"],
            "mean_sentence_length": sd["mean_sentence_length"],
            "sections_included": dict(Counter(p.section for p in d.paragraphs)),
            "sections_excluded": dict(d.sections_excluded),
            "block_quotes_removed": d.block_quotes,
            "language": d.language,
            "dropped": dict(d.dropped),
        })
    n_docs = len(docs)
    min_docs = 2 if n_docs >= 2 else 1

    content = Counter({w: c for w, c in A["words"].items() if w not in sw and len(w) >= 3 and is_word(w)})

    def content_ngram(g):
        t = g.split()
        return t[0] not in sw and t[-1] not in sw

    def formulaic(g):
        return any(w not in sw for w in g.split())

    bigrams = Counter({g: c for g, c in A["ngrams"][2].items() if content_ngram(g) and c >= 2})
    trigrams = Counter({g: c for g, c in A["ngrams"][3].items() if content_ngram(g) and c >= 2})
    formulas = Counter()
    for k in (3, 4):
        for g, c in A["ngrams"][k].items():
            if c >= 3 and ngram_docs[g] >= min_docs and formulaic(g):
                formulas[g] = c

    conn_items = []
    for ph in res.connectives.phrases:
        c = A["conn_total"][ph]
        if c:
            conn_items.append({
                "phrase": ph,
                "category": res.connective_category.get(ph),
                "count": c,
                "per_10k": per10k(c, n),
                "sentence_initial": A["conn_sentence_initial"][ph],
                "paragraph_initial": A["conn_paragraph_initial"][ph],
                "paragraph_final_sentence_initial": A["conn_paragraph_final"][ph],
                "docs": conn_docs[ph],
            })
    conn_items.sort(key=lambda r: -r["count"])
    never_used = sorted(ph for ph in res.connectives.phrases if not A["conn_total"][ph])

    fp_total = sum(A["fp_singular"].values()) + sum(A["fp_plural"].values()) + sum(A["fp_plural_verbs"].values())
    cites = A["citations"]
    narr, par = cites["narrative"], cites["parenthetical"]
    sl = A["sentence_lengths"]

    # Seções
    by_section = {}
    for sec in sorted({p.section for p in all_pars}):
        by_section[sec] = section_summary([p for p in all_pars if p.section == sec], res)

    # Linhas de base: como cada indicador varia entre trechos do próprio corpus, em vários tamanhos.
    function_words = [w for w, _ in A["words"].most_common(N_FUNCTION_WORDS + 1) if is_word(w)][:N_FUNCTION_WORDS]
    baselines = {str(size): compute_baseline(docs, res, size, function_words) for size in chunk_sizes}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "language": res.lang,
        "settings": {"data_dir": str(data_dir), "chunk_sizes": list(chunk_sizes), "lang": res.lang,
                     "min_sentence_tokens": MIN_SENTENCE_TOKENS},
        "corpus": {
            "documents": doc_rows,
            "skipped": skipped,
            "total_documents": n_docs,
            "total_words": n,
            "total_sentences": A["n_sentences"],
            "total_paragraphs": A["n_paragraphs"],
            "total_list_items": A["n_list_items"],
            "inline_quotes_removed": A["quotes"],
            "block_quotes_removed": sum(d.block_quotes for d in docs),
        },
        "sentences": {
            "length": describe(sl),
            "short_share_le_12_words": round(sum(1 for x in sl if x <= 12) / len(sl), 3) if sl else None,
            "long_share_ge_40_words": round(sum(1 for x in sl if x >= 40) / len(sl), 3) if sl else None,
            "question_share": round(A["questions"] / A["n_sentences"], 4) if A["n_sentences"] else None,
            "top_first_words": top_list(A["open1"], n, 30, "word"),
            "top_first_two_words": top_list(A["open2"], n, 30, "opener"),
        },
        "paragraphs": {
            "words": describe(A["paragraph_words"]),
            "sentences": describe(A["paragraph_sentences"]),
            "single_sentence_share": round(A["single_sentence_paragraphs"] / A["n_paragraphs"], 3)
            if A["n_paragraphs"] else None,
            "top_first_three_words": top_list(A["par_open3"], n, 25, "opener"),
        },
        "lexicon": {
            "mattr_100": round(A["mattr_100"], 4) if A["mattr_100"] else None,
            "mean_word_length": round(A["chars"] / n, 3) if n else None,
            "long_word_share": round(A["long_words"] / n, 3) if n else None,
            "nominalizations_per_100_words": round(100 * A["nominalizations"] / n, 2) if n else None,
            "distinct_words": len(A["words"]),
            "top_content_words": top_list(content, n, TOP_WORDS, "word", docfreq=word_docs),
            "top_content_bigrams": top_list(bigrams, n, TOP_NGRAMS, "ngram", docfreq=ngram_docs),
            "top_content_trigrams": top_list(trigrams, n, TOP_NGRAMS, "ngram", docfreq=ngram_docs),
            "formulaic_sequences": top_list(formulas, n, TOP_NGRAMS, "ngram", docfreq=ngram_docs),
        },
        "connectives": {
            "per_10k_words": per10k(sum(A["conn_total"].values()), n),
            "sentence_initial_share": round(A["sentences_conn_initial"] / A["n_sentences"], 3)
            if A["n_sentences"] else None,
            "by_category": {cat: {"count": c, "per_10k": per10k(c, n)}
                            for cat, c in A["conn_category"].most_common()},
            "items": conn_items,
            "never_used": never_used,
        },
        "modalization": {
            "hedges_per_10k": per10k(sum(A["hedges"].values()), n),
            "boosters_per_10k": per10k(sum(A["boosters"].values()), n),
            "hedges": top_list(A["hedges"], n, 40, "phrase"),
            "boosters": top_list(A["boosters"], n, 40, "phrase"),
            "impersonal": top_list(A["impersonal"], n, 30, "phrase"),
        },
        "voice": {
            "passive_per_100_sentences": round(100 * A["passive"] / A["n_sentences"], 2) if A["n_sentences"] else None,
            "passive_top_forms": top_list(A["passive_examples"], n, 25, "form"),
            "se_enclitic_per_10k": per10k(sum(A["se_enclitic"].values()), n),
            "se_enclitic_top_forms": top_list(A["se_enclitic"], n, 30, "form"),
            "se_free_per_10k": per10k(A["se_free"], n),
            "first_person_per_10k": per10k(fp_total, n),
            "first_person_singular": top_list(A["fp_singular"], n, 10, "form"),
            "first_person_plural_pronouns": top_list(A["fp_plural"], n, 10, "form"),
            "first_person_plural_verbs": top_list(A["fp_plural_verbs"], n, 20, "form"),
        },
        "punctuation": {
            "commas_per_sentence": round(A["punct"][","] / A["n_sentences"], 3) if A["n_sentences"] else None,
            "per_1k_words": {k: round(1000 * v / n, 3) if n else 0 for k, v in A["punct"].items()},
        },
        "citations": {
            "counts": dict(cites),
            "per_10k_words": per10k(narr + par, n),
            "narrative_share": round(narr / (narr + par), 3) if narr + par else None,
            "narrative_frames": top_list(A["cite_frames"], n, 20, "frame"),
            "reporting_verbs": top_list(A["cite_verbs"], n, 30, "verb"),
        },
        "ai_markers_in_your_corpus": top_list(A["ai_markers"], n, 60, "phrase"),
        "sections": by_section,
        "baselines": baselines,
    }


def fmt(v, nd=2):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}".replace(".", ",")
    return str(v)


def table(rows, cols, headers):
    if not rows:
        return "_(nenhum)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    return "\n".join(out) + "\n"


def render_markdown(M: dict) -> str:
    c = M["corpus"]
    L = []
    w = L.append
    w("# Relatório estilométrico do corpus\n")
    w(f"Gerado em {M['generated_at']} por `python scripts/idiolect.py analyze`. Idioma: {M['language']}.\n")
    w("> Este arquivo é gerado automaticamente. Não edite à mão: rode o script de novo.\n")
    w("## 1. Corpus\n")
    w(f"- Documentos analisados: **{c['total_documents']}**")
    w(f"- Palavras: **{c['total_words']:,}**".replace(",", "."))
    w(f"- Frases: {c['total_sentences']} · Parágrafos: {c['total_paragraphs']} · Itens de lista: {c['total_list_items']}")
    w(f"- Citações diretas removidas da análise: {c['inline_quotes_removed']} curtas, {c['block_quotes_removed']} longas\n")
    w(table(c["documents"], ["file", "type", "year", "coauthored", "words", "mean_sentence_length"],
            ["Arquivo", "Tipo", "Ano", "Coautoria", "Palavras", "Frase média"]))
    dropped = Counter()
    for row in c["documents"]:
        dropped.update(row.get("dropped", {}))
    if dropped:
        w("\nDescartados automaticamente: " + ", ".join(f"{k}: {v}" for k, v in dropped.most_common()) + "\n")
    if c["skipped"]:
        w("\nIgnorados:\n")
        for s in c["skipped"]:
            w(f"- `{s['file']}`: {s['reason']}")
        w("")
    if c["total_words"] < 20000:
        w("\n> **Atenção:** corpus com menos de 20 mil palavras. As métricas de vocabulário ficam instáveis;"
          " considere incluir mais textos.\n")

    s = M["sentences"]
    p = M["paragraphs"]
    w("## 2. Ritmo: frases e parágrafos\n")
    sl = s["length"] or {}
    w(f"- Frase: média **{fmt(sl.get('mean'))}** palavras, mediana {fmt(sl.get('median'))}, "
      f"desvio {fmt(sl.get('sd'))}, faixa típica (p10–p90) {fmt(sl.get('p10'))}–{fmt(sl.get('p90'))}")
    w(f"- Frases curtas (≤12 palavras): {fmt(s['short_share_le_12_words'], 3)} · longas (≥40): "
      f"{fmt(s['long_share_ge_40_words'], 3)} · interrogativas: {fmt(s['question_share'], 4)}")
    pw = p["words"] or {}
    ps = p["sentences"] or {}
    w(f"- Parágrafo: média **{fmt(pw.get('mean'))}** palavras e {fmt(ps.get('mean'))} frases; "
      f"parágrafos de uma frase só: {fmt(p['single_sentence_share'], 3)}")
    w(f"- Vírgulas por frase: {fmt(M['punctuation']['commas_per_sentence'])}\n")
    w("Pontuação por 1.000 palavras:\n")
    w(table([{"k": k, "v": v} for k, v in M["punctuation"]["per_1k_words"].items()], ["k", "v"], ["Sinal", "Por 1.000"]))
    w("\n### Como as frases começam\n")
    w(table(s["top_first_two_words"][:20], ["opener", "count", "per_10k"], ["Início", "Ocorrências", "Por 10 mil"]))
    w("\n### Como os parágrafos começam\n")
    w(table(p["top_first_three_words"][:20], ["opener", "count"], ["Início", "Ocorrências"]))

    lx = M["lexicon"]
    w("\n## 3. Vocabulário\n")
    w(f"- Diversidade lexical (MATTR-100): {fmt(lx['mattr_100'], 4)} · palavra média: "
      f"{fmt(lx['mean_word_length'])} letras · palavras longas: {fmt(lx['long_word_share'], 3)}")
    w(f"- Nominalizações: {fmt(lx['nominalizations_per_100_words'])} por 100 palavras\n")
    w("### Palavras de conteúdo mais frequentes\n")
    w(table(lx["top_content_words"][:60], ["word", "count", "per_10k", "docs"],
            ["Palavra", "Ocorrências", "Por 10 mil", "Docs"]))
    w("\n### Expressões recorrentes (sequências formulaicas)\n")
    w(table(lx["formulaic_sequences"][:40], ["ngram", "count", "docs"], ["Expressão", "Ocorrências", "Docs"]))
    w("\n### Combinações de conteúdo (bigramas)\n")
    w(table(lx["top_content_bigrams"][:30], ["ngram", "count", "docs"], ["Bigrama", "Ocorrências", "Docs"]))

    cn = M["connectives"]
    w("\n## 4. Coesão: conectivos\n")
    w(f"- Conectivos por 10 mil palavras: {fmt(cn['per_10k_words'])}")
    w(f"- Frases que começam com conectivo: {fmt(cn['sentence_initial_share'], 3)}\n")
    w(table([{"cat": k, **v} for k, v in cn["by_category"].items()], ["cat", "count", "per_10k"],
            ["Função", "Ocorrências", "Por 10 mil"]))
    w("\n")
    w(table(cn["items"][:50], ["phrase", "category", "count", "per_10k", "sentence_initial", "paragraph_initial",
                               "paragraph_final_sentence_initial", "docs"],
            ["Conectivo", "Função", "Total", "Por 10 mil", "Início de frase", "Início de parágrafo",
             "Abre a última frase", "Docs"]))
    w(f"\nConectivos da lista que **nunca** aparecem: {', '.join(cn['never_used']) or '–'}\n")

    md = M["modalization"]
    w("## 5. Modalização\n")
    w(f"- Atenuadores: {fmt(md['hedges_per_10k'])} por 10 mil · Intensificadores: {fmt(md['boosters_per_10k'])} por 10 mil\n")
    w(table(md["hedges"][:20], ["phrase", "count", "per_10k"], ["Atenuador", "Ocorrências", "Por 10 mil"]))
    w("\n")
    w(table(md["boosters"][:20], ["phrase", "count", "per_10k"], ["Intensificador", "Ocorrências", "Por 10 mil"]))
    w("\n")
    w(table(md["impersonal"][:20], ["phrase", "count", "per_10k"], ["Construção impessoal", "Ocorrências", "Por 10 mil"]))

    v = M["voice"]
    w("\n## 6. Voz e pessoa\n")
    w(f"- Voz passiva analítica (estimativa): {fmt(v['passive_per_100_sentences'])} por 100 frases")
    w(f"- Formas com -se: {fmt(v['se_enclitic_per_10k'])} por 10 mil · \"se\" solto: {fmt(v['se_free_per_10k'])} por 10 mil")
    w(f"- Primeira pessoa (estimativa): {fmt(v['first_person_per_10k'])} por 10 mil\n")
    w(table(v["se_enclitic_top_forms"][:20], ["form", "count"], ["Forma com -se", "Ocorrências"]))
    w("\n")
    w(table(v["passive_top_forms"][:15], ["form", "count"], ["Passiva", "Ocorrências"]))
    w("\n")
    w(table(v["first_person_plural_verbs"][:15], ["form", "count"], ["Verbo 1ª p. plural", "Ocorrências"]))

    ct = M["citations"]
    w("\n## 7. Citações\n")
    w(f"- Contagens: {', '.join(f'{k}: {val}' for k, val in ct['counts'].items()) or '–'}")
    w(f"- Citações por 10 mil palavras: {fmt(ct['per_10k_words'])} · proporção narrativa "
      f"(\"Autor (ano)\"): {fmt(ct['narrative_share'], 3)}\n")
    w(table(ct["narrative_frames"][:15], ["frame", "count"], ["Como introduz o autor", "Ocorrências"]))
    w("\n")
    w(table(ct["reporting_verbs"][:20], ["verb", "count"], ["Palavra após \"Autor (ano)\"", "Ocorrências"]))

    w("\n## 8. Por seção\n")
    rows = [{"sec": k, **val} for k, val in M["sections"].items()]
    w(table(rows, ["sec", "paragraphs", "words", "mean_sentence_length", "sentence_initial_connective_share",
                   "hedges_per_1k_words", "passive_per_100_sentences", "first_person_per_1k_words",
                   "citations_per_1k_words"],
            ["Seção", "Parágr.", "Palavras", "Frase média", "Abre c/ conectivo", "Atenuad./1k",
             "Passiva/100 fr.", "1ª pessoa/1k", "Citações/1k"]))
    for k, val in M["sections"].items():
        tops = ", ".join(f"{r['phrase']} ({r['count']})" for r in val["top_sentence_initial_connectives"][:6])
        if tops:
            w(f"- **{k}**: conectivos em início de frase: {tops}")
    w("")

    w("## 9. Marcadores típicos de IA no seu próprio corpus\n")
    w("Quanto você mesmo usa expressões comuns em textos de LLM (lista `[ai_markers]` em `scripts/lang/`):\n")
    w(table(M["ai_markers_in_your_corpus"][:30], ["phrase", "count", "per_10k"], ["Expressão", "Ocorrências", "Por 10 mil"]))

    b = pick_baseline(M, 1000)
    w("\n## 10. Linha de base (usada por `idiolect.py compare`)\n")
    sizes = ", ".join(f"{x['chunk_size']} ({x['n_chunks']} trechos)" for x in M["baselines"].values())
    w(f"O corpus é dividido em trechos de vários tamanhos: {sizes}. O `compare` usa o tamanho mais próximo do "
      f"texto comparado. A tabela mostra a variação entre os trechos de ~{b['chunk_size']} palavras:\n")
    rows = [{"f": FEATURE_LABELS.get(k, k), **(val or {})} for k, val in b["features"].items()]
    w(table(rows, ["f", "mean", "sd", "p10", "p90"], ["Indicador", "Média", "Desvio", "p10", "p90"]))
    if b["delta_own_chunks"]:
        d = b["delta_own_chunks"]
        w(f"\nDelta de Burrows entre seus próprios trechos: mediana {fmt(d['median'], 3)}, "
          f"p90 {fmt(d['p90'], 3)}, máximo {fmt(d['max'], 3)}. Um texto novo com Delta nessa faixa "
          "tem perfil de palavras funcionais compatível com o seu.\n")
    else:
        w("\nDelta de Burrows indisponível: são necessários pelo menos 3 trechos.\n")
    return "\n".join(L) + "\n"


# ======================= COMPARE =======================


MIN_RELIABLE_WORDS = 200


def load_json(path: Path):
    if not path.exists():
        raise SystemExit(f"Não encontrei {path}. Rode antes: python scripts/idiolect.py analyze")
    return json.loads(path.read_text(encoding="utf-8"))


def status(z):
    if z is None:
        return "–"
    a = abs(z)
    if a <= 1:
        return "ok"
    if a <= 2:
        return "atenção"
    return "FORA"


def compare(text: str, name: str, M: dict, V: dict, res) -> dict:
    doc = process_document(Path(name), res, apply_filters=False, text=text)
    A = analyze(doc.paragraphs, res, detail=False)
    n = A["n_tokens"]
    if n == 0:
        raise SystemExit("O texto não tem frases analisáveis.")
    feats = scalar_features(A)
    B = pick_baseline(M, n)
    base = B["features"]

    rows = []
    for key, val in feats.items():
        b = base.get(key)
        z = None
        if b and val is not None and b.get("sd"):
            z = round((val - b["mean"]) / b["sd"], 2)
        rows.append({"feature": key, "label": FEATURE_LABELS.get(key, key), "text": val,
                     "corpus_mean": b["mean"] if b else None, "corpus_sd": b["sd"] if b else None,
                     "z": z, "status": status(z)})

    # Delta de Burrows
    fw = B.get("function_words") or {}
    d_text = None
    if fw:
        words = list(fw)
        vec = word_vector(A["words"], n, words)
        d_text = delta(vec, [fw[w][0] for w in words], [fw[w][1] for w in words])
    d_own = B.get("delta_own_chunks")
    if d_text is None or not d_own:
        verdict = "indisponível (corpus com menos de 3 trechos)"
    elif d_text <= d_own["p75"]:
        verdict = "dentro do seu padrão típico"
    elif d_text <= d_own["p90"]:
        verdict = "compatível, mas na borda superior"
    elif d_text <= d_own["max"]:
        verdict = "no limite do que aparece no seu corpus"
    else:
        verdict = "fora do seu padrão"

    # Conectivos
    corpus_conn = {r["phrase"]: r for r in M["connectives"]["items"]}
    rare, overused = [], []
    for ph, c in A["conn_total"].most_common():
        t_rate = 10000 * c / n
        cr = corpus_conn.get(ph, {}).get("per_10k", 0.0)
        if cr < 0.5:
            rare.append({"phrase": ph, "count": c, "corpus_per_10k": cr})
        elif c >= 2 and t_rate >= 3 * cr:
            overused.append({"phrase": ph, "count": c, "text_per_10k": round(t_rate, 1), "corpus_per_10k": cr})
    top_corpus = [r["phrase"] for r in M["connectives"]["items"][:12]]
    missing = [ph for ph in top_corpus if not A["conn_total"][ph]] if n >= 600 else []

    # Marcadores de IA que você quase não usa
    corpus_ai = {r["phrase"]: r["per_10k"] for r in M.get("ai_markers_in_your_corpus", [])}
    ai_flags = [{"phrase": ph, "count": c, "corpus_per_10k": corpus_ai.get(ph, 0.0)}
                for ph, c in A["ai_markers"].most_common() if corpus_ai.get(ph, 0.0) < 1.0]

    # Palavras incomuns no seu vocabulário
    vc, vn = V["counts"], V["total_words"]
    unusual = []
    for w, c in A["words"].most_common():
        if c < 2 or w in res.stopwords or len(w) < 4 or not is_word(w):
            continue
        t_rate = c / n
        c_rate = (vc.get(w, 0) + 0.5) / vn
        ratio = t_rate / c_rate
        if ratio >= 8:
            unusual.append({"word": w, "count": c, "corpus_count": vc.get(w, 0), "ratio": round(ratio, 1)})
    unusual = unusual[:20]

    # Inícios de frase repetidos no próprio texto
    repeated = [{"opener": o, "count": c} for o, c in A["open2"].most_common(10) if c >= 3]

    # Citações
    cites = A["citations"]
    narr, par = cites["narrative"], cites["parenthetical"]
    cite_info = None
    if narr + par:
        cite_info = {"narrative": narr, "parenthetical": par,
                     "narrative_share": round(narr / (narr + par), 2),
                     "corpus_narrative_share": M["citations"]["narrative_share"]}

    # Veredito geral. Com ~20 indicadores, alguns ficam entre 1 e 2 desvios mesmo em textos do próprio autor;
    # por isso contam só os indicadores FORA (|z| > 2), o Delta e as expressões com cara de IA.
    # Limiares calibrados com trechos do corpus real (texto do autor -> 0 a 4 FORA, 0 a 3 marcadores de IA).
    n_out = sum(1 for r in rows if r["status"] == "FORA")
    n_ai = len(ai_flags)
    delta_out = verdict == "fora do seu padrão"
    if n_out >= 5 or n_ai >= 5 or (n_out >= 3 and (delta_out or n_ai >= 3)):
        overall = "não soa como você: revise os pontos abaixo"
    elif n_out >= 2 or n_ai >= 2 or delta_out:
        overall = "próximo do seu estilo, com desvios a corrigir"
    else:
        overall = "compatível com o seu estilo"

    return {
        "file": name,
        "overall": overall,
        "words": n,
        "sentences": A["n_sentences"],
        "paragraphs": A["n_paragraphs"],
        "reliable": n >= MIN_RELIABLE_WORDS,
        "baseline_chunk_size": B["chunk_size"],
        "delta": {"text": d_text, "own_chunks": d_own, "verdict": verdict},
        "features": rows,
        "connectives": {"rare_for_you": rare, "overused": overused, "your_usual_missing": missing},
        "ai_markers": ai_flags,
        "unusual_words": unusual,
        "repeated_openers": repeated,
        "citations": cite_info,
    }


def f(v, nd=2):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}".replace(".", ",")
    return str(v)


def render(R: dict) -> str:
    L = []
    w = L.append
    w(f"# Comparação de estilo: {R['file']}\n")
    w(f"{R['words']} palavras · {R['sentences']} frases · {R['paragraphs']} parágrafos · "
      f"comparado com trechos de ~{R['baseline_chunk_size']} palavras do seu corpus\n")
    if not R["reliable"]:
        w(f"> **Atenção:** texto com menos de {MIN_RELIABLE_WORDS} palavras. Os números são indicativos.\n")
    d = R["delta"]
    w("## Visão geral\n")
    if d["text"] is not None and d["own_chunks"]:
        o = d["own_chunks"]
        w(f"- Delta de Burrows: **{f(d['text'], 3)}** (seus trechos: mediana {f(o['median'], 3)}, "
          f"p90 {f(o['p90'], 3)}, máx. {f(o['max'], 3)})")
    w(f"  - Palavras funcionais: {d['verdict']}")
    outs = [r for r in R["features"] if r["status"] == "FORA"]
    warns = [r for r in R["features"] if r["status"] == "atenção"]
    w(f"- Indicadores fora do padrão: {len(outs)} · em atenção: {len(warns)}")
    w(f"- **Veredito geral: {R['overall']}**\n")

    w("## Indicadores\n")
    w("| Indicador | Texto | Seu padrão (média ± desvio) | z | Situação |")
    w("|---|---|---|---|---|")
    for r in sorted(R["features"], key=lambda r: -abs(r["z"] or 0)):
        w(f"| {r['label']} | {f(r['text'])} | {f(r['corpus_mean'])} ± {f(r['corpus_sd'])} | {f(r['z'])} | {r['status']} |")
    w("")

    c = R["connectives"]
    w("## Conectivos\n")
    if c["rare_for_you"]:
        w("Conectivos que **você quase nunca usa** (menos de 0,5 por 10 mil palavras no corpus):\n")
        for r in c["rare_for_you"]:
            w(f"- \"{r['phrase']}\" ({r['count']}×)")
        w("")
    if c["overused"]:
        w("Conectivos usados **bem mais do que você costuma** (3× ou mais):\n")
        for r in c["overused"]:
            w(f"- \"{r['phrase']}\": {f(r['text_per_10k'], 1)} por 10 mil no texto vs. {f(r['corpus_per_10k'], 1)} no corpus")
        w("")
    if c["your_usual_missing"]:
        w("Seus conectivos mais frequentes que **não aparecem** no texto: "
          + ", ".join(f"\"{p}\"" for p in c["your_usual_missing"]) + "\n")
    if not (c["rare_for_you"] or c["overused"] or c["your_usual_missing"]):
        w("Nenhum desvio relevante.\n")

    if R["ai_markers"]:
        w("## Expressões com cara de IA que você quase não usa\n")
        for r in R["ai_markers"]:
            w(f"- \"{r['phrase']}\" ({r['count']}×; no seu corpus: {f(r['corpus_per_10k'], 1)} por 10 mil)")
        w("")

    if R["unusual_words"]:
        w("## Palavras incomuns no seu vocabulário\n")
        w("Podem ser termos do tema (normal) ou escolhas que não são suas (revise):\n")
        for r in R["unusual_words"]:
            w(f"- {r['word']} ({r['count']}× no texto; {r['corpus_count']}× no corpus inteiro)")
        w("")

    if R["repeated_openers"]:
        w("## Inícios de frase repetidos no texto\n")
        for r in R["repeated_openers"]:
            w(f"- \"{r['opener']}...\" ({r['count']}×)")
        w("")

    if R["citations"]:
        ci = R["citations"]
        w("## Citações\n")
        w(f"- Narrativas: {ci['narrative']} · parentéticas: {ci['parenthetical']} · proporção narrativa "
          f"{f(ci['narrative_share'])} (no corpus: {f(ci['corpus_narrative_share'])})\n")
    return "\n".join(L) + "\n"


# ======================= CLI =======================

def cmd_analyze(args) -> None:
    data_dir, out_dir = Path(args.data), Path(args.out)
    if not data_dir.is_dir():
        raise SystemExit(f"Pasta não encontrada: {data_dir}")
    res = load_resources(args.lang)
    docs, skipped = load_corpus(data_dir, res)
    if not docs:
        raise SystemExit(f"Nenhum documento analisável em {data_dir}. Coloque seus textos .md nessa pasta.")
    sizes = sorted({int(x) for x in str(args.chunk_sizes).split(",") if x.strip()})
    M = build_metrics(docs, skipped, res, sizes, data_dir)
    vocab = Counter()
    for d in docs:
        for p in d.paragraphs:
            for tk in p.tokens:
                vocab.update(tk)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(M, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "metrics.md").write_text(render_markdown(M), encoding="utf-8")
    (out_dir / "vocabulary.json").write_text(
        json.dumps({"total_words": sum(vocab.values()), "counts": dict(vocab.most_common())},
                   ensure_ascii=False, indent=0), encoding="utf-8")
    c = M["corpus"]
    print(f"Documentos: {c['total_documents']} | palavras: {c['total_words']} | frases: {c['total_sentences']} "
          f"| linhas de base: " + ", ".join(f"{b['chunk_size']}w x{b['n_chunks']}" for b in M["baselines"].values()))
    for row in c["documents"]:
        print(f"  {row['file']}: {row['words']} palavras ({row['type']})")
    for sk in skipped:
        print(f"  ignorado: {sk['file']} ({sk['reason']})")
    if c["total_words"] < 20000:
        print("  aviso: corpus com menos de 20 mil palavras; as métricas de vocabulário ficam instáveis.")
    if all(b["n_chunks"] < 3 for b in M["baselines"].values()):
        print("  aviso: menos de 3 trechos; compare não terá Delta. Use --chunk-sizes menores ou inclua mais textos.")
    print(f"Gerado em {out_dir}: metrics.json, metrics.md, vocabulary.json")


def cmd_compare(args) -> None:
    reports = Path(args.reports)
    M = load_json(reports / "metrics.json")
    V = load_json(reports / "vocabulary.json")
    res = load_resources(M["settings"].get("lang", "pt-BR"))
    if args.text == "-":
        text, name = sys.stdin.read(), "stdin"
    else:
        path = Path(args.text)
        text, name = path.read_text(encoding="utf-8-sig"), path.name
    R = compare(text, name, M, V, res)
    out = json.dumps(R, ensure_ascii=False, indent=2) if args.json else render(R)
    print(out)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")


def main() -> None:
    setup_stdout()
    ap = argparse.ArgumentParser(prog="idiolect", description="Perfil estilométrico do autor.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="analisa o corpus em data/ e gera reports/")
    a.add_argument("--data", default=str(DATA_DIR), help="pasta com os .md (padrão: data)")
    a.add_argument("--out", default=str(REPORTS_DIR), help="pasta de saída (padrão: reports)")
    a.add_argument("--lang", default="pt-BR", help="arquivo de idioma em scripts/lang (padrão: pt-BR)")
    a.add_argument("--chunk-sizes", default="250,500,1000,2000",
                   help="tamanhos dos trechos das linhas de base, em palavras (padrão: 250,500,1000,2000)")
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("compare", help="compara um texto com o estilo do corpus")
    c.add_argument("text", help="arquivo .md/.txt, ou - para ler da entrada padrão")
    c.add_argument("--reports", default=str(REPORTS_DIR), help="pasta com metrics.json e vocabulary.json")
    c.add_argument("--json", action="store_true", help="saída em JSON")
    c.add_argument("-o", "--output", help="também grava o relatório neste arquivo")
    c.set_defaults(func=cmd_compare)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
