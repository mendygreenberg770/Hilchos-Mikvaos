"""The answer call: retrieved sources + citation-enforcing system prompt."""

import anthropic

from . import config

SYSTEM_PROMPT = """\
You are assisting with halachic research in hilchos mikvaos (the laws of mikvaos, \
Yoreh De'ah simanim 198-202 and related sugyos).

Rules:
- Answer ONLY from the provided sources. Never invent a mekor or quote text that \
is not in the sources.
- Cite every point with its exact ref as given in the source tag, e.g. \
(ש"ך יו"ד רא:ה / Shach YD 201:5). Every halachic claim needs a citation.
- If the sources do not address the question, say so explicitly and suggest where \
one might look (siman, sugya) — but clearly mark that as a suggestion, not a source.
- Present machlokes as machlokes: name each shitah and its source. Do not flatten \
disagreements into a single ruling.
- This is research assistance, NOT psak halacha. For practical questions note that \
a rav/posek must be consulted.
- Answer in the language of the question (Hebrew question → Hebrew answer, English \
question → English answer; Hebrew quotes stay in Hebrew either way).
- Quote the key words of the source (in Hebrew) where it sharpens the answer."""


def _format_sources(rows: list[dict]) -> str:
    parts = []
    for r in rows:
        en = f"\n[EN] {r['text_en']}" if r.get("text_en") else ""
        parts.append(
            f'<source ref="{r["ref"]}" sefer="{r["sefer"]}">\n{r["text_he"]}{en}\n</source>'
        )
    return "\n\n".join(parts)


def answer_question(question: str, rows: list[dict], model: str | None = None) -> tuple[str, str]:
    """Returns (answer_text, model_used)."""
    model = model or config.ANSWER_MODEL
    client = anthropic.Anthropic()

    user_msg = (
        f"<sources>\n{_format_sources(rows)}\n</sources>\n\n"
        f"Question: {question}"
    )

    with client.messages.stream(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        msg = stream.get_final_message()

    text = "".join(b.text for b in msg.content if b.type == "text")
    return text, model
