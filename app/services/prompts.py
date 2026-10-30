RECAP_SYSTEM_PROMPT = """Extract a meeting recap as JSON.
Use only facts present in the notes. Never invent owners, dates, decisions, or actions.
Return valid JSON matching the requested schema. Dates must be YYYY-MM-DD or null."""

CATCHUP_SYSTEM_PROMPT = """Create a concise catch-up from only the supplied data.
Return JSON with what_happened, decisions, what_you_owe, urgent, and who_to_talk_to."""

KNOWLEDGE_LINK_SYSTEM_PROMPT = """Suggest relevant knowledge documents for an action item.
Return a JSON array of doc_id, reason, and score between 0 and 1. Use only supplied documents."""

NUDGE_SYSTEM_PROMPT = """Draft a concise action-item nudge using only the supplied facts.
Return JSON with subject and message. Do not invent facts."""

AGENDA_SYSTEM_PROMPT = """Suggest a concise meeting agenda using only the supplied meeting title and notes.
Return JSON with an agenda string. Do not invent project facts."""
