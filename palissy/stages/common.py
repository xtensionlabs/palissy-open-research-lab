import json
import re


def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object in model output: {text[:200]!r}")
    return json.loads(match.group(0))


async def complete_json(router, stage: str, messages: list[dict], *, parents=None,
                        **kw) -> tuple[dict, object]:
    """A model call whose reply must hold a JSON object; asks once more if it doesn't.

    Nemotron reasoning models sometimes spend the token budget thinking and stop mid-answer.
    Returns (data, completion) of the call that parsed.
    """
    out = await router.complete(stage, messages, parents=parents, **kw)
    try:
        return extract_json(out.text), out
    except (ValueError, json.JSONDecodeError):
        retry = messages + [
            {"role": "assistant", "content": out.text[-2000:]},
            {"role": "user", "content": "That reply was cut off or had no JSON. Reply again "
                                        "with the JSON object only, shorter."}]
        out = await router.complete(stage, retry, parents=[out.record.id], **kw)
        return extract_json(out.text), out


def extract_code(text: str) -> str:
    # Prefer an explicit python fence: a bare ``` could be the closing fence of a json block.
    match = (re.search(r"```python[ \t]*\n(.*?)```", text, re.DOTALL)
             or re.search(r"```[ \t]*\n(.*?)```", text, re.DOTALL))
    return (match.group(1) if match else text).strip()
