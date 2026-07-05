"""
AI Extractor — School Dashboard
Reads dashboard_data.json, extracts structured info using Claude Haiku,
produces dashboard_display.json for Lovable to consume.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()
from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

TODAY = datetime.now(timezone.utc).strftime('%d %b %Y')

SYSTEM_PROMPT = f"""You are a school communication assistant for a parent with two children:
- Mihika, Grade 8, Middle School
- Ananya, Grade 5D, Primary School
at Sancta Maria school, Hyderabad, India.

Today's date is {TODAY}.

Analyse this school Teams post and extract structured information.
Return JSON only — no other text, no markdown fences.

{{
  "homework": [
    {{
      "subject": "",
      "description": "",
      "due_date": null,
      "urgency": "high|medium|low"
    }}
  ],
  "parent_actions": [
    {{
      "action": "",
      "due_date": null,
      "urgency": "high|medium|low"
    }}
  ],
  "events": [
    {{
      "name": "",
      "date": null,
      "details": "",
      "preparation": null
    }}
  ],
  "fyi": [
    {{
      "summary": ""
    }}
  ]
}}

Rules:
- urgency=high if due within 2 days of today
- urgency=medium if due within 7 days
- urgency=low if due later or no date
- due_date format: DD Mon YYYY e.g. 3 Jul 2026
- Extract homework from daily logs — anything after HW: or Homework: is homework
- Only extract events that are upcoming or within the last 7 days — ignore past events
- If the message is student chat or irrelevant to a parent, return all empty arrays
- If purely informational, use fyi only
- Return valid JSON only, no other text whatsoever

CRITICAL RULES — read carefully:

1. CHILD SPECIFICITY: Only extract parent_actions where this specific child's parent needs to act.
   If the post mentions another student by name as the subject (e.g. "Mokshitha's project",
   "Rahul should submit"), classify as fyi only.

2. DATE AWARENESS: Today is {TODAY}.
   Only include events with future dates in the events array. Events that already happened
   belong in fyi with prefix "Recent: ".

3. EVIDENCE REQUIRED: Only extract items that are explicitly stated in the post. Do not
   infer, assume, or generate items not present in the text. If you cannot find direct evidence
   in the post, do not include the item.

4. HOMEWORK PRECISION: Only extract homework that is explicitly assigned with words like
   "HW:", "Homework:", "for homework", "due".
   Do not extract classwork activities or in-class exercises as homework.

5. OLD POSTS: If the post timestamp is more than 7 days before today ({TODAY}),
   only extract future-dated events and hard deadlines. Do not extract general
   information or volunteer opportunities from old posts.
"""


def classify_event_by_date(event: dict) -> str:
    date_str = event.get("date", "")
    if not date_str:
        return "future"

    formats = ["%d %b %Y", "%Y-%m-%d", "%d %B %Y"]
    today = datetime.now(timezone.utc).date()

    for fmt in formats:
        try:
            event_date = datetime.strptime(date_str.strip(), fmt).date()
            if event_date < today:
                return "past"
            return "future"
        except Exception:
            continue

    return "future"


def normalise_hw_key(hw: dict) -> str:
    subject = hw.get("subject", "").lower().strip()
    desc = hw.get("description", "").lower().strip()
    desc = re.sub(r'[^a-z0-9]', '', desc)
    return f"{subject}:{desc[:30]}"


def is_grounded(item_text: str, source_post: str) -> bool:
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'for', 'to', 'in', 'of', 'with',
        'is', 'are', 'will', 'be', 'this', 'that', 'have', 'from', 'by',
        'at', 'on', 'as', 'it'
    }

    item_words = set(
        w.lower() for w in item_text.split()
        if len(w) > 3 and w.lower() not in stopwords
    )
    source_words = set(
        w.lower() for w in source_post.split()
        if len(w) > 3 and w.lower() not in stopwords
    )

    return len(item_words & source_words) >= 2


def extract_from_post(post_text: str, team_name: str, child_name: str) -> dict:
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"Team: {team_name}\n"
                    f"Child: {child_name}\n"
                    f"Post: {post_text[:1500]}"
                )
            }]
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)

        # Grounding check — homework
        grounded_homework = []
        for hw in result.get("homework", []):
            hw_text = f"{hw.get('subject', '')} {hw.get('description', '')}"
            if is_grounded(hw_text, post_text):
                grounded_homework.append(hw)
            else:
                result.setdefault("fyi", []).append({
                    "summary": f"Unverified: {hw_text[:80]}"
                })
        result["homework"] = grounded_homework

        # Grounding check — parent_actions
        grounded_actions = []
        for act in result.get("parent_actions", []):
            act_text = act.get("action", "")
            if is_grounded(act_text, post_text):
                grounded_actions.append(act)
            else:
                result.setdefault("fyi", []).append({
                    "summary": f"Unverified action: {act_text[:80]}"
                })
        result["parent_actions"] = grounded_actions

        return result

    except json.JSONDecodeError:
        return {
            "homework": [],
            "parent_actions": [],
            "events": [],
            "fyi": [{"summary": post_text[:100]}],
        }
    except Exception as e:
        print(f"  [warn] Extraction failed: {e}")
        return {"homework": [], "parent_actions": [], "events": [], "fyi": []}


def merge_extractions(extractions: list) -> dict:
    merged = {"homework": [], "parent_actions": [], "events": [], "fyi": []}
    seen_homework = set()
    seen_actions = set()
    seen_events = set()

    for ext in extractions:
        for hw in ext.get("homework", []):
            key = normalise_hw_key(hw)
            if key and key not in seen_homework:
                seen_homework.add(key)
                merged["homework"].append(hw)

        for act in ext.get("parent_actions", []):
            key = act.get("action", "")[:40].lower()
            if key and key not in seen_actions:
                seen_actions.add(key)
                merged["parent_actions"].append(act)

        for evt in ext.get("events", []):
            classification = classify_event_by_date(evt)
            if classification == "past":
                merged["fyi"].append({
                    "summary": f"Recent announcement: {evt['name']}"
                               + (f" — {evt['date']}" if evt.get("date") else "")
                })
            else:
                key = evt.get("name", "")[:40].lower()
                if key and key not in seen_events:
                    seen_events.add(key)
                    merged["events"].append(evt)

        merged["fyi"].extend(ext.get("fyi", []))

    urgency_order = {"high": 0, "medium": 1, "low": 2}
    merged["homework"].sort(key=lambda x: urgency_order.get(x.get("urgency", "low"), 2))
    merged["parent_actions"].sort(key=lambda x: urgency_order.get(x.get("urgency", "low"), 2))

    return merged


def build_overview(merged: dict) -> list:
    lines = []

    for act in merged["parent_actions"]:
        if act.get("urgency") == "high":
            date_str = f" — due {act['due_date']}" if act.get("due_date") else ""
            lines.append(f"🔴 {act['action']}{date_str}")
        if len(lines) >= 4:
            return lines[:4]

    for act in merged["parent_actions"]:
        if act.get("urgency") == "medium":
            date_str = f" — due {act['due_date']}" if act.get("due_date") else ""
            lines.append(f"🟡 {act['action']}{date_str}")
        if len(lines) >= 4:
            return lines[:4]

    for hw in merged["homework"]:
        if hw.get("urgency") == "high":
            subj = hw.get("subject", "")
            desc = hw.get("description", "")
            date_str = f" — due {hw['due_date']}" if hw.get("due_date") else ""
            title = f"{subj}: {desc}" if subj else desc
            lines.append(f"📝 {title}{date_str}")
        if len(lines) >= 4:
            return lines[:4]

    for hw in merged["homework"]:
        if hw.get("urgency") in ("medium", "low"):
            subj = hw.get("subject", "")
            desc = hw.get("description", "")
            date_str = f" — due {hw['due_date']}" if hw.get("due_date") else ""
            title = f"{subj}: {desc}" if subj else desc
            lines.append(f"📝 {title}{date_str}")
        if len(lines) >= 4:
            return lines[:4]

    for evt in merged["events"]:
        date_str = f" — {evt['date']}" if evt.get("date") else ""
        lines.append(f"📅 {evt['name']}{date_str}")
        if len(lines) >= 4:
            return lines[:4]

    return lines[:4]


def eval_check(display: dict) -> None:
    today = datetime.now(timezone.utc).date()
    issues = []

    for child, data in display["children"].items():
        for evt in data.get("events", []):
            date_str = evt.get("date", "")
            if date_str:
                try:
                    evt_date = datetime.strptime(date_str, "%d %b %Y").date()
                    if evt_date < today:
                        issues.append(
                            f"⚠️  {child}: Past event in events — "
                            f"{evt['name']} ({date_str})"
                        )
                except Exception:
                    pass

        hw_count = len(data.get("homework", []))
        if hw_count > 8:
            issues.append(
                f"⚠️  {child}: High homework count ({hw_count}) — possible over-extraction"
            )

        for action in data.get("parent_actions", []):
            if len(action.get("action", "")) < 10:
                issues.append(
                    f"⚠️  {child}: Very short parent action — possible extraction error: "
                    f"'{action['action']}'"
                )

    if issues:
        print("\n⚠️  EVAL WARNINGS:")
        for issue in issues:
            print(f"   {issue}")
        print(f"   Total issues: {len(issues)}")
        print(f"   Review dashboard_display.json before publishing")
    else:
        print("\n✅ Eval checks passed — no issues found")


def process_child(child_name: str, child_data: dict) -> dict:
    print(f"\n[extract] Processing {child_name}...")

    all_extractions = []
    total_posts = 0

    for team in child_data.get("teams", []):
        team_name = team.get("team_name", "Unknown")

        for post in team.get("general_posts", []):
            text = post.get("text", "").strip()
            if len(text) < 20:
                continue
            total_posts += 1
            print(f"  [{team_name[:25]}] post {total_posts}: {text[:50]}...")
            all_extractions.append(extract_from_post(text, team_name, child_name))
            time.sleep(0.5)

        for item in team.get("classwork", []):
            title = item.get("title", "")
            if not title or title in ["CLASSWORK_PAGE_TEXT", "CLASSWORK_NOT_LOADED", "ERROR"]:
                continue
            targets = ["daily log", "school communication", "friday diary"]
            if not any(t in title.lower() for t in targets):
                continue
            text = f"{title}: {item.get('context', '')}"
            total_posts += 1
            print(f"  [{team_name[:25]}] classwork: {title}")
            all_extractions.append(extract_from_post(text, team_name, child_name))
            time.sleep(0.5)

    merged = merge_extractions(all_extractions)

    for section in ["homework", "parent_actions", "events", "fyi"]:
        for item in merged[section]:
            item["source_platform"] = "Teams"

    overview = build_overview(merged)

    print(
        f"[extract] {child_name}: "
        f"{len(merged['homework'])} homework, "
        f"{len(merged['parent_actions'])} actions, "
        f"{len(merged['events'])} events, "
        f"{len(merged['fyi'])} fyi"
    )

    return {**merged, "overview": overview}


def main():
    print("=" * 50)
    print("AI Extractor — School Dashboard")
    print(f"Date: {TODAY}")
    print("=" * 50)

    try:
        with open("dashboard_data.json", "r") as f:
            raw = json.load(f)
    except FileNotFoundError:
        print("[error] dashboard_data.json not found — run teams_scraper.py first")
        return

    children_data = raw.get("children", {})
    if not children_data:
        print("[error] No children data found in JSON")
        return

    display = {
        "extracted_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+05:30'),
        "source": "github_actions",
        "children": {},
    }

    for child_name, child_data in children_data.items():
        display["children"][child_name] = process_child(child_name, child_data)

    with open("dashboard_display.json", "w") as f:
        json.dump(display, f, indent=2)

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for child, data in display["children"].items():
        print(f"\n{child}:")
        print(f"  Homework      : {len(data['homework'])} items")
        print(f"  Parent actions: {len(data['parent_actions'])} items")
        print(f"  Events        : {len(data['events'])} items")
        print(f"  FYI           : {len(data['fyi'])} items")
        if data["overview"]:
            print(f"  Overview:")
            for line in data["overview"]:
                print(f"    {line}")

    print(f"\n✅ dashboard_display.json saved")
    print(f"💰 Estimated cost: ~$0.01-0.02 per run")

    eval_check(display)


if __name__ == "__main__":
    main()
