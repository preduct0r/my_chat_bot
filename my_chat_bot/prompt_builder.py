from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .context_store import ChatMessage


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def render_personal_memory(personal_memory: Sequence[Dict[str, str]]) -> str:
    if not personal_memory:
        return "Персональная информация о пользователе пока не накоплена."

    lines = ["Персональная информация о пользователе:"]
    for item in personal_memory:
        category = item.get("category", "general")
        fact = item.get("fact", "")
        if fact:
            lines.append(f"- [{category}] {fact}")
    return "\n".join(lines)


def render_session_summary(summary: Dict[str, object]) -> str:
    dialog_summary = summary.get("dialog_summary", {})
    if not isinstance(dialog_summary, dict):
        return "Суммаризация диалога недоступна."

    lines = [f"Суммаризация диалога #{summary.get('session_id', '?')}:"]
    summary_text = dialog_summary.get("summary", "")
    if isinstance(summary_text, str) and summary_text:
        lines.append(summary_text)

    key_points = dialog_summary.get("key_points", [])
    if isinstance(key_points, list) and key_points:
        lines.append("Ключевые пункты:")
        for item in key_points:
            if isinstance(item, str) and item:
                lines.append(f"- {item}")

    documents = dialog_summary.get("documents", [])
    if isinstance(documents, list) and documents:
        lines.append("Упомянутые документы:")
        for item in documents:
            if isinstance(item, str) and item:
                lines.append(f"- {item}")

    open_questions = dialog_summary.get("open_questions", [])
    if isinstance(open_questions, list) and open_questions:
        lines.append("Открытые вопросы:")
        for item in open_questions:
            if isinstance(item, str) and item:
                lines.append(f"- {item}")

    return "\n".join(lines)


def select_memory_with_budget(
    personal_memory: Sequence[Dict[str, str]],
    summaries: Sequence[Dict[str, object]],
    memory_budget: int,
) -> Tuple[List[Dict[str, str]], List[Dict[str, object]], Dict[str, int]]:
    selected_personal: List[Dict[str, str]] = []
    consumed = 0

    for item in personal_memory:
        candidate = selected_personal + [item]
        candidate_tokens = estimate_token_count(render_personal_memory(candidate))
        if candidate_tokens > memory_budget:
            continue
        selected_personal = candidate
        consumed = candidate_tokens

    personal_tokens = consumed
    selected: List[Dict[str, object]] = []

    if consumed >= memory_budget:
        return selected_personal, selected, {
            "personal_tokens": personal_tokens,
            "selected_summary_tokens": 0,
            "total_tokens": personal_tokens,
        }

    selected_summary_tokens = 0
    for summary in summaries:
        summary_text = render_session_summary(summary)
        summary_tokens = estimate_token_count(summary_text)
        if consumed + summary_tokens > memory_budget:
            continue
        selected.append(summary)
        consumed += summary_tokens
        selected_summary_tokens += summary_tokens

    return selected_personal, selected, {
        "personal_tokens": personal_tokens,
        "selected_summary_tokens": selected_summary_tokens,
        "total_tokens": consumed,
    }


def build_reply_instructions(
    base_system_prompt: str,
    personal_memory: Sequence[Dict[str, str]],
    summaries: Sequence[Dict[str, object]],
) -> str:
    sections = [
        base_system_prompt,
        "Ниже приведена долговременная память пользователя. Используй ее как контекст, но не выдумывай факты.",
        render_personal_memory(personal_memory),
    ]

    if summaries:
        rendered_summaries = "\n\n".join(render_session_summary(item) for item in summaries)
        sections.append("Последние суммаризации предыдущих диалогов:")
        sections.append(rendered_summaries)
    else:
        sections.append("Предыдущих суммаризаций диалогов пока нет.")

    sections.append(
        "Ниже в самих сообщениях придут только последние реплики текущего активного диалога. "
        "Считай их приоритетным контекстом для текущего ответа."
    )
    return "\n\n".join(section for section in sections if section)


def build_prompt_preview(
    base_system_prompt: str,
    personal_memory: Sequence[Dict[str, str]],
    summaries: Sequence[Dict[str, object]],
    current_messages: Sequence[ChatMessage],
) -> str:
    lines = [
        "=== SYSTEM PROMPT ===",
        base_system_prompt,
        "",
        "=== PERSONAL MEMORY ===",
        render_personal_memory(personal_memory),
        "",
        "=== PREVIOUS SESSION SUMMARIES ===",
    ]

    if summaries:
        for summary in summaries:
            lines.append(render_session_summary(summary))
            lines.append("")
    else:
        lines.append("Суммаризации прошлых диалогов отсутствуют.")
        lines.append("")

    lines.append("=== CURRENT SESSION MESSAGES ===")
    for message in current_messages:
        lines.append(f"{message.role}: {message.to_preview_text()}")

    return "\n".join(lines).strip()
