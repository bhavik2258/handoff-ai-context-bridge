import os

import httpx


def _local_recap(notes: str, title: str) -> str:
    clean = " ".join(notes.split())
    if not clean:
        return f"{title}: No raw notes were supplied. Add decisions and actions below."
    return (
        f"{title}: {clean[:500]}\n\n"
        "Suggested follow-up: confirm owners and due dates for every open action item."
    )


async def generate_recap(notes: str, title: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _local_recap(notes, title)

    payload = {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"),
        "max_tokens": 500,
        "system": "Turn meeting notes into a concise, useful recap. Use plain text.",
        "messages": [
            {
                "role": "user",
                "content": f"Meeting: {title}\nNotes:\n{notes}",
            }
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return data["content"][0]["text"]
