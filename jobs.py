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

Review the following items and take appropriate actions using the available tools:

{chr(10).join(parts)}

For completed tasks (status='done'):
- Call update_task to set status='evaluated' if the task appears properly complete with no concerns.
- If there are concerns or follow-up tasks needed, note them in ai_review_notes before evaluating.
- Create follow-up tasks via create_task if warranted.

For scheduled AI review items (next_ai_review has passed):
- Review the item's purpose and ai_review_notes.
- Update ai_review_notes with your current assessment via update_task/update_quest/update_quest_line.
- Set a new next_ai_review date if continued monitoring is needed.
- Flag any concerns that require user attention.

After processing all items, write a concise summary (2-5 sentences) of what you did and any issues that need the user's attention. This summary will be added to the inbox."""

    result = await agent.run(prompt, deps=deps)
    summary = result.output

    report = f"AI Review — {today}\n\n{summary}"
    deps.inbox.create(report)

    return summary
