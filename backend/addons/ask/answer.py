"""Claude's step: a question answered from the passages that were found, every claim citing where it comes from.

The passages go to Claude as search results (one per item, each passage a block of its own) with citations on,
so the API itself says which passages each sentence of the answer rests on. That is more exact than asking Claude
to write [3] after a sentence: the quote under a source in the answer is the passage Claude actually used.
"""

from __future__ import annotations

from ... import config, db
from ...ai import client as ai
from ...jobs import Job, JobError
from . import find, store

ANSWER_TOKENS = 2500  # thinking and the answer, as estimated before it is sent
MAX_TOKENS = 16000
TYPE_WORDS = {"article": "article", "news": "news item", "paper": "paper", "report": "report",
              "document": "document", "video": "video (its transcript, written up)",
              "podcast": "podcast episode (its transcript, written up)", "post": "post"}

SYSTEM = """You answer questions from the reader's own library: think-tank publications, papers, reports, news and \
written-up videos and podcasts that they collected. The search results in the message are the passages of that \
library that matched the question best; each search result is one item, its title says the source, the date and \
the kind of item.

How to answer:
- Answer from the search results. Cite them: every claim that comes from them should rest on the passages it comes \
from.
- Start with the answer itself in a sentence or two, then the detail. Plain prose in short paragraphs; a short list \
only where the content is a list. No headings unless the answer is long.
- Where the sources disagree, or one is older than another and things may have changed, say so and say who says what.
- Mention dates when timing matters: the library spans months, and the reader wants to know what is current.
- When the passages do not answer the question, or only in part, say that plainly, and say what they do cover. Do \
not fill the gap from memory. If general knowledge is needed to make sense of something, keep it to a sentence and \
mark it as not from the library ("Outside the library: ...").
- British spelling. Do not mention "search results" or "passages": speak of the library, the sources, the items."""


def model() -> str:
    return str(config.get("model_ask"))


def results(found: find.Found) -> list[dict]:
    """The items as search-result blocks, best first, each passage a citable block."""
    blocks = []
    for item in found.items:
        kind = TYPE_WORDS.get(item["content_type"], item["content_type"])
        blocks.append({
            "type": "search_result",
            "source": item["url"],
            "title": f"{item['title']} ({item['source_name']}, {item['date'][:10]}, {kind})",
            "content": [{"type": "text", "text": passage["text"]} for passage in item["passages"]],
            "citations": {"enabled": True},
        })
    return blocks


def plan(found: find.Found, question: str) -> dict:
    """What the answer will read and cost, before anything is sent."""
    chosen = model()
    return {"model": chosen, "model_label": config.model_label(chosen), "items": len(found.items),
            "passages": found.passages, "library": found.library,
            "weak": bool(found.items) and 0 < found.best < find.WEAK,
            "usd": round(ai.estimated_cost(chosen, len(SYSTEM) + found.chars + len(question), ANSWER_TOKENS), 4)}


def _markdown(reply, found: find.Found) -> tuple[str, list[dict], list[dict]]:
    """Claude's answer as Markdown with [n] after each cited stretch, the cited items numbered in the order they are
    first cited, with the passages quoted, and the items it was given but did not cite."""
    number: dict[int, int] = {}  # index of the search result -> its number in the answer
    quotes: dict[int, list[int]] = {}  # index of the search result -> the positions of its cited passages
    parts = []
    for block in reply.content:
        if block.type != "text":
            continue
        marks = []
        for citation in getattr(block, "citations", None) or []:
            if getattr(citation, "type", "") != "search_result_location":
                continue
            index = citation.search_result_index
            if not 0 <= index < len(found.items):
                continue
            if index not in number:
                number[index] = len(number) + 1
            cited = quotes.setdefault(index, [])
            for block_index in range(citation.start_block_index, citation.end_block_index):
                if block_index not in cited:
                    cited.append(block_index)
            if number[index] not in marks:
                marks.append(number[index])
        text = block.text
        if marks:
            stripped = text.rstrip()
            text = stripped + "".join(f"[{n}]" for n in marks) + text[len(stripped):]
        parts.append(text)
    sources = []
    for index, n in sorted(number.items(), key=lambda pair: pair[1]):
        item = found.items[index]
        passages = item["passages"]
        sources.append({
            "n": n, "article_id": item["id"], "title": item["title"], "url": item["url"],
            "source_name": item["source_name"], "source_icon": item["source_icon"], "date": item["date"][:10],
            "content_type": item["content_type"], "image_url": item["image_url"],
            "quotes": [passages[i]["text"] for i in sorted(quotes[index]) if 0 <= i < len(passages)],
        })
    read = [{"article_id": item["id"], "title": item["title"], "url": item["url"], "source_name": item["source_name"],
             "date": item["date"][:10], "content_type": item["content_type"]}
            for index, item in enumerate(found.items) if index not in number]
    return "".join(parts).strip(), sources, read


def answer(question_id: int, job: Job) -> dict:
    asked = store.question(question_id)
    if asked is None:
        raise JobError("This question no longer exists.")
    scope = asked["scope"]
    try:
        found = find.find(asked["question"], topic_id=scope.get("topic_id"), source_id=scope.get("source_id"),
                          since=scope.get("since") or "")
        if not found.items:
            store.update(question_id, status="done", answered_at=db.now(), passages=0, model=model(),
                         answer="The library has nothing that matches this question"
                                + (" within what you chose to ask." if scope.get("topic_id") or scope.get("source_id")
                                   or scope.get("since") else "."))
            job.log("Nothing in the library matches; Claude was not asked.")
            return {"question_id": question_id, "items": 0}
        chosen = model()
        job.log(f"Reading {found.passages} passages from {len(found.items)} items ({config.model_label(chosen)})…")
        usage = ai.Usage()
        try:
            reply = ai.message(
                model=chosen, usage=usage, stream=True, max_tokens=MAX_TOKENS, system=SYSTEM,
                thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                messages=[{"role": "user", "content": [*results(found), {"type": "text", "text": asked["question"]}]}],
            )
            ai.require_answer(reply, "answer this question")
        finally:
            job.usage = usage.as_dict()
            store.update(question_id, cost_usd=round(usage.cost_usd, 5))
        text, sources, read = _markdown(reply, found)
        store.update(question_id, status="done", answer=text, sources=sources, read=read, passages=found.passages,
                     model=chosen, answered_at=db.now(), error="")
        job.log(f"Answered, citing {len(sources)} of the {len(found.items)} items it read.")
        return {"question_id": question_id, "items": len(found.items), "cited": len(sources)}
    except Exception as error:
        store.update(question_id, status="failed", error=str(error) if isinstance(error, JobError)
                     else f"{type(error).__name__}: {error}")
        raise
