"""Auto-tagging: a lightweight second Claude call that extracts siman/seif refs
and 1-3 topic tags from the Q&A. Best-effort — failures never block the answer."""

import json

import anthropic

from . import config

TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "refs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "siman": {"type": "integer"},
                    "seif": {"type": ["integer", "null"]},
                },
                "required": ["siman", "seif"],
                "additionalProperties": False,
            },
        },
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["refs", "topics"],
    "additionalProperties": False,
}

TAG_PROMPT = """\
You tag halachic Q&A entries about hilchos mikvaos for a research log.

From the question and answer below, extract:
1. refs — every Shulchan Aruch Yoreh De'ah siman (and seif where identifiable) \
that the Q&A is about. Convert Hebrew numerals to numbers (רא = 201). Only simanim \
actually discussed, not passing mentions.
2. topics — 1 to 3 topic tags, lowercase, transliterated Hebrew terms preferred \
(e.g. "chatzitza", "zochalin", "hashaka", "sheuvin", "bor al gabei bor", "chafifa", \
"tevilas keilim", "mei geshamim"). Reuse standard terms, don't invent variants.

<question>
{question}
</question>

<answer>
{answer}
</answer>"""


def tag_question(question: str, answer: str) -> dict:
    """Returns {"refs": [{"siman": int, "seif": int|None}], "topics": [str]}."""
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=config.TAGGING_MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": TAG_PROMPT.format(question=question[:4000],
                                             answer=answer[:8000]),
            }],
            output_config={"format": {"type": "json_schema", "schema": TAG_SCHEMA}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        data["topics"] = [t.strip().lower() for t in data.get("topics", []) if t.strip()][:3]
        data["refs"] = [r for r in data.get("refs", [])
                        if isinstance(r.get("siman"), int) and 1 <= r["siman"] <= 403]
        return data
    except Exception:
        return {"refs": [], "topics": []}
