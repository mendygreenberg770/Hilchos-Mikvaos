"""Detect siman/seif, daf, and mishnah references in a question.

Handles English ("201:5", "siman 201 seif 5", "Niddah 66b", "Mikvaos 2:3")
and Hebrew ("סימן רא סעיף ה", "רא:ה", "נדה סו:", "מקואות ב:ג") formats.
"""

import re
from dataclasses import dataclass

GEMATRIA = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ך": 20, "ל": 30, "מ": 40, "ם": 40, "נ": 50, "ן": 50,
    "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90, "ץ": 90,
    "ק": 100, "ר": 200, "ש": 300, "ת": 400,
}

_QUOTES_RE = re.compile(r"[\"'׳״`]")


def hebrew_to_int(s: str) -> int | None:
    """Gematria of a Hebrew numeral string (geresh/gershayim tolerated)."""
    s = _QUOTES_RE.sub("", s.strip())
    if not s or any(ch not in GEMATRIA for ch in s):
        return None
    return sum(GEMATRIA[ch] for ch in s)


@dataclass(frozen=True)
class Ref:
    kind: str               # 'sa' | 'gemara' | 'mishnah'
    siman: int | None = None
    seif: int | None = None
    masechta: str | None = None
    daf: str | None = None        # e.g. "66b"
    chapter: int | None = None
    mishnah: int | None = None

    def label(self) -> str:
        if self.kind == "sa":
            return f"YD {self.siman}" + (f":{self.seif}" if self.seif else "")
        if self.kind == "gemara":
            return f"{self.masechta} {self.daf}"
        return f"Mikvaos {self.chapter}:{self.mishnah}"


MASECHTOS = {
    "niddah": "Niddah", "nidah": "Niddah", "נדה": "Niddah",
    "chagigah": "Chagigah", "chagiga": "Chagigah", "חגיגה": "Chagigah",
    "shabbos": "Shabbos", "shabbat": "Shabbos", "שבת": "Shabbos",
    "pesachim": "Pesachim", "פסחים": "Pesachim",
}

_HEB_NUM = r"[א-ת]{1,3}[\"'׳״]?[א-ת]?"

# --- English / numeric patterns -------------------------------------------
_GEMARA_EN = re.compile(
    r"\b(" + "|".join(k for k in MASECHTOS if k.isascii()) + r")\.?\s+(\d{1,3})\s*([ab])\b",
    re.IGNORECASE,
)
_MISHNAH = re.compile(
    r"(mikva\'?o[st]|mikvaot|מקוו?אות)\s+(\d{1,2}|" + _HEB_NUM + r")\s*[:.,]\s*(\d{1,2}|" + _HEB_NUM + r")",
    re.IGNORECASE,
)
_SIMAN_EN = re.compile(
    r"\bsiman\s+(\d{1,3})(?:\s*[,:]?\s*se\'?if\s+(\d{1,2}))?", re.IGNORECASE
)
_SA_NUMERIC = re.compile(r"(?<![\d:.])(\d{3})\s*[:.]\s*(\d{1,2})(?![\d:.])")
_SIMAN_BARE = re.compile(r"\b(?:siman|סימן)\s+(\d{1,3})\b")

# --- Hebrew patterns --------------------------------------------------------
_GEMARA_HE = re.compile(r"(נדה|חגיגה|שבת|פסחים)\s+(" + _HEB_NUM + r")\s*([.:])")
_SIMAN_HE = re.compile(r"סימן\s+(" + _HEB_NUM + r")(?:\s+סעיף\s+(" + _HEB_NUM + r"))?")
_SA_HE_COMPACT = re.compile(r"(?<![א-ת])(" + _HEB_NUM + r"):(" + _HEB_NUM + r")(?![א-ת])")


def _to_int(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return hebrew_to_int(s)


def detect_refs(question: str) -> list[Ref]:
    found: list[Ref] = []
    seen: set = set()
    consumed: list[tuple[int, int]] = []

    def add(ref: Ref, span: tuple[int, int] | None = None):
        if ref not in seen:
            seen.add(ref)
            found.append(ref)
        if span:
            consumed.append(span)

    def overlaps(span):
        return any(not (span[1] <= s or span[0] >= e) for s, e in consumed)

    # Named patterns first — they claim their spans so generic a:b doesn't double-match.
    for m in _GEMARA_EN.finditer(question):
        add(Ref(kind="gemara", masechta=MASECHTOS[m.group(1).lower()],
                daf=f"{m.group(2)}{m.group(3).lower()}"), m.span())
    for m in _GEMARA_HE.finditer(question):
        daf_num = hebrew_to_int(m.group(2))
        if daf_num:
            amud = "a" if m.group(3) == "." else "b"
            add(Ref(kind="gemara", masechta=MASECHTOS[m.group(1)],
                    daf=f"{daf_num}{amud}"), m.span())
    for m in _MISHNAH.finditer(question):
        c, mi = _to_int(m.group(2)), _to_int(m.group(3))
        if c and mi and c <= 30:
            add(Ref(kind="mishnah", chapter=c, mishnah=mi), m.span())
    for m in _SIMAN_EN.finditer(question):
        seif = int(m.group(2)) if m.group(2) else None
        add(Ref(kind="sa", siman=int(m.group(1)), seif=seif), m.span())
    for m in _SIMAN_HE.finditer(question):
        siman = hebrew_to_int(m.group(1))
        if siman:
            seif = hebrew_to_int(m.group(2)) if m.group(2) else None
            add(Ref(kind="sa", siman=siman, seif=seif), m.span())

    # Generic numeric "201:5" — three-digit first number reads as a siman.
    for m in _SA_NUMERIC.finditer(question):
        if overlaps(m.span()):
            continue
        siman = int(m.group(1))
        if 100 <= siman <= 403:
            add(Ref(kind="sa", siman=siman, seif=int(m.group(2))), m.span())

    # Hebrew compact "רא:ה" — only when gematria lands in plausible siman range.
    for m in _SA_HE_COMPACT.finditer(question):
        if overlaps(m.span()):
            continue
        siman, seif = hebrew_to_int(m.group(1)), hebrew_to_int(m.group(2))
        if siman and seif and 100 <= siman <= 403 and seif <= 80:
            add(Ref(kind="sa", siman=siman, seif=seif), m.span())

    # Bare "siman 201" without seif (when not already captured with a seif)
    for m in _SIMAN_BARE.finditer(question):
        siman = int(m.group(1))
        if not any(r.kind == "sa" and r.siman == siman for r in found):
            add(Ref(kind="sa", siman=siman))

    return found
