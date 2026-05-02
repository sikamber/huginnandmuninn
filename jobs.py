from datetime import date

from review import get_ai_review_items


async def run_ai_review(agent, deps) -> str:
    """Run the nightly AI review job. Returns a summary written to the inbox."""
    today = date.today()
    items = get_ai_review_items(today)

    if not items["done_tasks"] and not items["ai_review_items"]:
        return "No items to review."

    parts = []
    if items["done_tasks"]:
        task_lines = "\n".join(
            f"- [{t['id']}] {t['title']}" + (f" — {t['description']}" if t.get("description") else "")
            for t in items["done_tasks"]
        )
        parts.append(f"Tasks completed but not yet evaluated:\n{task_lines}")

    if items["ai_review_items"]:
        item_lines = "\n".join(
            f"- [{i['type']} {i['id']}] {i['title']}"
            + (f" (notes: {i['ai_review_notes']})" if i.get("ai_review_notes") else "")
            for i in items["ai_review_items"]
        )
        parts.append(f"Items scheduled for AI review:\n{item_lines}")

    prompt = f"""You are running the scheduled AI review job for {today}.

Review the following items and write a structured markdown report. Do NOT call any tools — your text output will be saved to the inbox as a report automatically.

{chr(10).join(parts)}

Write a report with these sections:

## Completed Tasks
For each task marked as done, give a one-line assessment: does it look properly complete? Note any concerns or follow-up needed.

## Scheduled Reviews
For each item with a scheduled AI review, assess it against its ai_review_notes and give a one-line status update.

## Suggested Actions
List specific actions you recommend the user take. Be concrete — name the item and what to do (e.g. "Mark [task title] as evaluated", "Set next_ai_review for [quest] to YYYY-MM-DD", "Create a follow-up task for [item]"). The user will approve and implement these via the chat.

Keep the report concise. Do not implement any changes — only analyse and suggest."""

    result = await agent.run(prompt, deps=deps)
    summary = result.output

    report = f"# AI Review — {today}\n\n{summary}"
    deps.inbox.create(report)

    return summary
