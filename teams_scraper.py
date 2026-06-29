# Microsoft Teams Scraper — hardcoded-teams edition
# ===================================================
# Keeps: login, session cookies, .env loading
# Rewrites: everything after login
#
# Usage:
#   pip install playwright python-dotenv beautifulsoup4
#   playwright install chromium
#   cd /Users/nidhibhattacharya/Documents && python3 teams_scraper.py

from dotenv import load_dotenv
load_dotenv()

import json, os, pickle, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ── Credentials ────────────────────────────────────────────────────────────

CHILDREN = [
    {
        "name":         os.environ.get("CHILD1_NAME",     "Mihika"),
        "email":        os.environ.get("CHILD1_EMAIL",    "CHILD1_SCHOOL_EMAIL"),
        "password":     os.environ.get("CHILD1_PASSWORD", "CHILD1_PASSWORD"),
        "session_file": "child1_session.pkl",
        "output_file":  "child1_messages.json",
        # ── Teams config ──────────────────────────────────────────────────
        # Class teacher team: scrape General + Classwork
        # Fill in the EXACT name as it appears in Teams (from a screenshot)
        "class_teacher_team": "Grade 8E Class Teacher_Mr. Devanjay",
        "subject_teams": [
            "Middle school Volunteers",
            "8E Math_Ritu Sharma",
            "GR 8 EG (2026-27) Ms. Rajya",
            "8E FLE_Ms. Femina Shaikh",
            "8E Computing_Sameera&Janani",
            "Grade 8 Future Pathways_Rozy",
            "8E Humanities_Nandita",
            "8E Science_ Shikha & Devanjay",
        ],
    },
    {
        "name":         os.environ.get("CHILD2_NAME",     "Ananya"),
        "email":        os.environ.get("CHILD2_EMAIL",    "CHILD2_SCHOOL_EMAIL"),
        "password":     os.environ.get("CHILD2_PASSWORD", "CHILD2_PASSWORD"),
        "session_file": "child2_session.pkl",
        "output_file":  "child2_messages.json",
        "class_teacher_team": "Grade 5D Class Teacher (2026-27)",
        "subject_teams": [
            "Grade 5 CDE Hindi( 2026-27)",
            "Grade 5E Humanities (2026-27)",
            "Grade 5D Science (2026-27)",
            "Grade 5D Computing (2026-27)",
            "Grade 5D English (2026-27)",
            "Grade 5D Mathematics (2026-27)",
            "Grade 5D Humanities (2026-27)",
        ],
    },
]

DASHBOARD_FILE = "dashboard_data.json"
MFA_WAIT       = 30
POSTS_DAYS     = 7


# ── Helpers ────────────────────────────────────────────────────────────────

def wait(s, msg=""):
    print(f"      [wait] {s}s{' — ' + msg if msg else ''}...")
    time.sleep(s)


def slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text)[:40].strip("_")


def save_screenshot(page, name: str):
    try:
        path = f"{name}.png"
        page.screenshot(path=path)
        print(f"      [screenshot] → {path}")
    except Exception as e:
        print(f"      [screenshot] Failed {name}.png: {e}")


# ── Session persistence ────────────────────────────────────────────────────

def save_session(context, session_file: str):
    with open(session_file, "wb") as f:
        pickle.dump(context.cookies(), f)
    print(f"  [session] Saved → {session_file}")


def load_session(context, session_file: str) -> bool:
    if not Path(session_file).exists():
        return False
    try:
        with open(session_file, "rb") as f:
            context.add_cookies(pickle.load(f))
        print(f"  [session] Loaded from {session_file}")
        return True
    except Exception as e:
        print(f"  [session] Could not load: {e}")
        return False


def is_session_valid(page) -> bool:
    try:
        page.goto("https://teams.cloud.microsoft", wait_until="domcontentloaded")
        time.sleep(5)
        if page.query_selector("input[type='email'],input[name='loginfmt']"):
            return False
        if page.query_selector("button[aria-label^='Activity'],button[aria-label^='Teams']"):
            return True
        time.sleep(4)
        return bool(page.query_selector(
            "button[aria-label^='Activity'],button[aria-label^='Teams']"))
    except Exception:
        return False


# ── Login ──────────────────────────────────────────────────────────────────

def login(page, email: str, password: str, child_name: str) -> bool:
    print(f"\n  [login] Starting login for {child_name} ({email})...")
    page.goto("https://teams.cloud.microsoft", wait_until="domcontentloaded")
    time.sleep(5)

    # Email
    email_found = False
    try:
        tb = page.get_by_role("textbox", name="Enter your email, phone, or")
        tb.wait_for(timeout=10_000)
        tb.click()
        tb.fill(email)
        page.keyboard.press("Enter")
        time.sleep(2)
        try:
            page.get_by_role("button", name="Next").click(timeout=4_000)
            time.sleep(2)
        except Exception:
            pass
        email_found = True
        print(f"  [login] Email entered via textbox role")
    except Exception:
        pass

    if not email_found:
        for sel in ["input[type='email']", "input[name='loginfmt']",
                    "input[placeholder*='email' i]"]:
            try:
                el = page.wait_for_selector(sel, timeout=6_000)
                if el:
                    el.click()
                    page.keyboard.type(email, delay=60)
                    page.keyboard.press("Enter")
                    time.sleep(3)
                    email_found = True
                    print(f"  [login] Email entered via CSS ({sel})")
                    break
            except PlaywrightTimeoutError:
                continue

    if not email_found:
        print("  [login] WARNING: email field not found")
        save_screenshot(page, f"login_debug_{slug(child_name)}_email")

    # Password
    pwd_found = False
    for sel in ["#i0118", "input[type='password']", "input[name='passwd']"]:
        try:
            el = page.wait_for_selector(sel, timeout=10_000)
            if el:
                el.fill(password)
                page.get_by_role("button", name="Sign in").click(timeout=5_000)
                time.sleep(5)
                pwd_found = True
                print(f"  [login] Password entered via {sel}")
                break
        except Exception:
            continue

    if not pwd_found:
        print("  [login] WARNING: password field not found")
        save_screenshot(page, f"login_debug_{slug(child_name)}_password")

    # MFA
    try:
        page.wait_for_selector(
            "text=Approve the request,text=Verify your identity,#lightbox",
            timeout=8_000)
        print(f"  [login] MFA detected — please approve on your phone. Waiting {MFA_WAIT}s...")
        time.sleep(MFA_WAIT)
    except PlaywrightTimeoutError:
        pass

    # Stay signed in
    try:
        page.get_by_role("button", name="Yes").click(timeout=8_000)
        print("  [login] Clicked 'Yes' on Stay signed in")
        time.sleep(3)
    except Exception:
        pass

    # Web app fallback
    try:
        page.wait_for_selector(
            "a:has-text('Use the web app instead'),"
            "button:has-text('Use the web app instead')",
            timeout=8_000).click()
        print("  [login] Switched to web app")
        time.sleep(3)
    except PlaywrightTimeoutError:
        pass

    print("  [login] Waiting for Teams to fully load...")
    try:
        page.wait_for_selector(
            "text=We're setting things up for you",
            state="hidden", timeout=90_000)
    except PlaywrightTimeoutError:
        pass
    time.sleep(3)

    logged_in = bool(page.query_selector(
        "button[aria-label^='Activity'],button[aria-label^='Teams']"))
    save_screenshot(page, f"login_{slug(child_name)}")
    if logged_in:
        print(f"  [login] ✅ Login confirmed for {child_name}")
    else:
        print(f"  [login] ⚠️  Could not confirm login — check login_{slug(child_name)}.png")
    return logged_in


# ── Navigate to Teams grid ─────────────────────────────────────────────────

def open_teams_grid(page):
    """Click the Teams icon in the left nav to show the teams grid."""
    for name in ["Teams", "Teams (⌃ ⇧ 1)", "Teams ("]:
        try:
            page.get_by_role("button", name=name).first.click(timeout=4_000)
            time.sleep(3)
            return
        except Exception:
            pass
    try:
        page.wait_for_selector("button[aria-label^='Teams']", timeout=5_000).click()
        time.sleep(3)
    except Exception:
        save_screenshot(page, "error_teams_nav")


# ── Click a team by its name ───────────────────────────────────────────────

def click_team(page, team_name: str) -> bool:
    """
    Go to the teams grid and click the card whose text matches team_name.
    Returns True if click succeeded.
    """
    open_teams_grid(page)

    # Wait for the grid to render
    try:
        page.wait_for_selector(
            "[data-tid$='-team-card'],[data-tid='team-card'],"
            "[class*='teamCard'],[class*='teamTile']",
            timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    time.sleep(2)

    # Strategy 1 — codegen confirmed: role=button with the team name
    # Teams appends "Team X of Y" to aria-labels so we use partial match
    try:
        page.get_by_role("button", name=team_name).first.click(timeout=5_000)
        time.sleep(3)
        return True
    except Exception:
        pass

    # Strategy 2 — JS: find any card/button whose text contains the team name
    clicked = page.evaluate(f"""
        () => {{
            const label = {json.dumps(team_name)};

            // Try data-tid team cards first
            const cards = document.querySelectorAll(
                '[data-tid$="-team-card"],[data-tid="team-card"],' +
                '[class*="teamCard"],[class*="teamTile"]'
            );
            for (const card of cards) {{
                if ((card.innerText || '').includes(label) ||
                    (card.getAttribute('aria-label') || '').includes(label)) {{
                    card.scrollIntoView({{block: 'nearest'}});
                    card.click();
                    return true;
                }}
            }}

            // Fall back to any large button in the main grid area
            for (const btn of document.querySelectorAll('[role="button"],button')) {{
                const rect = btn.getBoundingClientRect();
                if (rect.left < 60 || rect.width < 100 || rect.height < 60) continue;
                const txt = btn.getAttribute('aria-label') || btn.innerText || '';
                if (txt.includes(label)) {{
                    btn.scrollIntoView({{block: 'nearest'}});
                    btn.click();
                    return true;
                }}
            }}
            return false;
        }}
    """)
    if clicked:
        time.sleep(3)
        return True

    # Strategy 3 — any visible text match
    try:
        page.get_by_text(team_name, exact=False).first.click(timeout=4_000)
        time.sleep(3)
        return True
    except Exception:
        pass

    return False


# ── Click an item in the left sidebar ─────────────────────────────────────

def click_sidebar_item(page, label: str) -> bool:
    """
    Click a sidebar tab or channel by label.
    Uses position (left < 380px) for reliability in Teams' dynamic React DOM.
    """
    # Strategy 1 — codegen confirmed: role=treeitem
    try:
        page.get_by_role("treeitem", name=label, exact=True).first.click(timeout=3_000)
        return True
    except Exception:
        pass

    try:
        page.get_by_role("treeitem", name=label).first.click(timeout=3_000)
        return True
    except Exception:
        pass

    # Strategy 2 — position-based JS (left < 380px = sidebar)
    clicked = page.evaluate(f"""
        () => {{
            const label = {json.dumps(label)};
            const candidates = document.querySelectorAll(
                'a, button, [role="link"], [role="button"], [role="treeitem"], [role="option"]'
            );
            for (const el of candidates) {{
                const rect = el.getBoundingClientRect();
                if (rect.left < 380 && rect.left > 60 && rect.width > 20 && rect.height > 10) {{
                    const txt = (el.getAttribute('aria-label') || el.textContent || '').trim();
                    if (txt === label || txt.startsWith(label)) {{
                        el.scrollIntoView({{block: 'nearest'}});
                        el.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}
    """)
    if clicked:
        return True

    # Strategy 3 — XPath text match
    try:
        page.locator(f"//span[normalize-space(text())='{label}']").first.click(timeout=2_000)
        return True
    except Exception:
        pass

    return False


# ── Smart wait for Teams React content ────────────────────────────────────

def wait_for_teams_content(page, timeout=15_000) -> bool:
    """
    Wait for Teams React app to finish rendering.
    Returns True if content appeared, False if timed out.
    NEVER use page.content() — use inner_text() instead.
    """
    # Wait for any loading spinner to vanish
    try:
        page.wait_for_selector(
            '[class*="spinner"],[class*="loading"],[class*="Spinner"]',
            state="hidden", timeout=5_000)
    except Exception:
        pass

    # Wait for actual rendered content to appear
    content_selectors = (
        '[data-tid="message-body"], '
        '[class*="messageContent"], '
        '[class*="chatMessage"], '
        'div[role="article"], '
        '[class*="assignment"], '
        '[class*="classwork"], '
        '[data-tid="channel-pane-runway"]'
    )
    try:
        page.wait_for_selector(content_selectors, timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False


# ── Scrape General channel posts ───────────────────────────────────────────

def scrape_general_channel(page, team_name: str) -> list[dict]:
    print(f"      [general] Clicking General channel...")

    # Click General — it lives below "Main Channels" in the sidebar
    general_clicked = False
    for attempt_label in ["General", "general"]:
        try:
            page.get_by_role("treeitem", name=attempt_label, exact=True).click(timeout=4_000)
            general_clicked = True
            break
        except Exception:
            pass

    if not general_clicked:
        general_clicked = page.evaluate("""
            () => {
                const els = document.querySelectorAll(
                    '[role="treeitem"], [role="link"], [role="button"], a'
                );
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.left < 380 && rect.left > 60 && rect.top > 200 &&
                        el.textContent.trim() === 'General') {
                        el.click();
                        return true;
                    }
                }
                return false;
            }
        """)

    if not general_clicked:
        # Last resort: click the last "General" text on the page
        try:
            page.get_by_text("General", exact=True).last.click(timeout=3_000)
            general_clicked = True
        except Exception:
            pass

    if not general_clicked:
        print(f"      [general] Could not click General channel")
        save_screenshot(page, f"error_{slug(team_name)}_general")
        return []

    time.sleep(5)

    # Smart wait — don't proceed until content renders or we know it's empty
    content_ready = wait_for_teams_content(page)
    save_screenshot(page, f"general_{slug(team_name)}")

    posts = []

    # ── Primary: Playwright locators with inner_text() ────────────────────
    # inner_text() returns only VISIBLE rendered text — never JS source code
    for selector in [
        '[data-tid="message-body"]',
        '[class*="messageBody"]',
        '[class*="chatMessageBody"]',
        'div[role="article"]',
        '[class*="message-content"]',
        '[class*="messageContent"]',
        '[class*="chatMessage"]',
    ]:
        try:
            elements = page.locator(selector).all()
            if not elements:
                continue
            print(f"      [general] Found {len(elements)} element(s) via '{selector}'")
            for el in elements[:30]:
                try:
                    text = el.inner_text(timeout=3_000).strip()
                    if len(text) < 10:
                        continue
                    # Try to get author and timestamp from the surrounding card
                    # walk up via JS since Playwright locator doesn't have parent()
                    meta = page.evaluate("""
                        (el) => {
                            let node = el.parentElement;
                            let author = '', ts = '';
                            for (let d = 0; d < 8 && node; d++) {
                                if (!author) {
                                    const a = node.querySelector(
                                        '[class*="author"],[class*="sender"],' +
                                        '[class*="displayName"],[data-tid*="author"]'
                                    );
                                    if (a) author = (a.innerText || '').trim();
                                }
                                if (!ts) {
                                    const t = node.querySelector(
                                        'time,[aria-label*="AM"],[aria-label*="PM"],' +
                                        '[data-tid*="timestamp"],[class*="timestamp"]'
                                    );
                                    if (t) ts = t.getAttribute('datetime') ||
                                               t.getAttribute('aria-label') ||
                                               t.innerText || '';
                                }
                                if (author && ts) break;
                                node = node.parentElement;
                            }
                            return { author, ts };
                        }
                    """, el.element_handle())
                    posts.append({
                        "author":    meta.get("author", "").strip(),
                        "text":      text,
                        "timestamp": meta.get("ts", "").strip(),
                    })
                except Exception:
                    continue
            if posts:
                break
        except Exception:
            continue

    # ── Fallback: inner_text() of the whole main content pane ─────────────
    if not posts:
        print(f"      [general] Specific selectors found nothing — trying main pane text")
        try:
            main_text = page.locator('[role="main"]').inner_text(timeout=10_000)
            if len(main_text.strip()) > 50:
                print(f"      [general] Got {len(main_text)} chars from main pane")
                posts.append({
                    "author":    "",
                    "text":      main_text.strip()[:4000],
                    "timestamp": "",
                    "note":      "full_page_text_fallback",
                })
        except Exception:
            pass

    if not posts and not content_ready:
        # Channel is genuinely empty or failed to load
        print(f"      [general] No posts found (channel may be empty)")
        save_screenshot(page, f"empty_{slug(team_name)}_general")

    print(f"      [general] {len(posts)} post(s)")
    return posts


# ── Scrape Classwork tab ────────────────────────────────────────────────────

def scrape_classwork(page, team_name: str) -> list[dict]:
    print(f"      [classwork] Clicking Classwork tab...")

    # Click Classwork in the LEFT sidebar using position-based JS
    clicked = page.evaluate("""
        () => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const rect = el.getBoundingClientRect();
                if (rect.left > 60 && rect.left < 350 &&
                    rect.top > 100 && rect.height < 60 &&
                    el.textContent.trim() === 'Classwork' &&
                    el.children.length <= 1) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """)

    if not clicked:
        # Fallback: codegen-confirmed treeitem role
        try:
            page.get_by_role("treeitem", name="Classwork").first.click(timeout=3_000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        try:
            page.get_by_text("Classwork", exact=True).first.click(timeout=3_000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        print(f"      [classwork] Could not click Classwork tab")
        save_screenshot(page, f"error_{slug(team_name)}_classwork")
        return []

    time.sleep(6)
    save_screenshot(page, f"classwork_{slug(team_name)}")

    # ── Try the embedded iframe first (codegen-confirmed) ─────────────────
    frame = None
    try:
        page.wait_for_selector("iframe[name='embedded-page-container']", timeout=12_000)
        frame = page.frame(name="embedded-page-container")
        if frame:
            print(f"      [classwork] Found embedded iframe — URL: {frame.url[:80]}")
    except PlaywrightTimeoutError:
        # Try any iframe on the page
        for f in page.frames:
            if f != page.main_frame and f.url and "teams" not in f.url.lower():
                continue
            if f != page.main_frame:
                frame = f
                print(f"      [classwork] Using frame: {f.url[:80]}")
                break

    # ── Use inner_text() — NEVER innerHTML / page.content() ───────────────
    # inner_text() returns only rendered visible text, not JS source code.

    items = []

    if frame:
        # Read from the iframe
        try:
            iframe_text = frame.locator("body").inner_text(timeout=12_000)
            print(f"      [classwork] iframe inner_text: {len(iframe_text)} chars")
        except Exception as e:
            print(f"      [classwork] iframe inner_text failed: {e}")
            iframe_text = ""

        if iframe_text and len(iframe_text.strip()) > 20:
            items = _parse_classwork_text(iframe_text, page, slug(team_name))

    if not items:
        # Read from main page [role="main"] — safe, returns rendered text only
        try:
            main_text = page.locator('[role="main"]').inner_text(timeout=12_000)
            print(f"      [classwork] main pane inner_text: {len(main_text)} chars")
        except Exception as e:
            print(f"      [classwork] main pane inner_text failed: {e}")
            main_text = ""

        if main_text and len(main_text.strip()) > 20:
            items = _parse_classwork_text(main_text, page, slug(team_name))

    if not items:
        save_screenshot(page, f"error_{slug(team_name)}_classwork_empty")
        items = [{"title": "CLASSWORK_NOT_LOADED", "date": "", "attachments": [],
                  "note": "Check screenshot for what was on screen"}]

    print(f"      [classwork] {len(items)} item(s)")
    return items


def _parse_classwork_text(text: str, page, team_sl: str) -> list[dict]:
    """
    Parse classwork plain text (from inner_text) into structured items.
    Looks for Daily Log, School Communication, Friday Diary first.
    Falls back to returning a snippet of the full text.
    """
    TARGET_KEYWORDS = ["daily log", "school communication", "friday diary"]
    items = []

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for i, line in enumerate(lines):
        for kw in TARGET_KEYWORDS:
            if kw in line.lower():
                # Collect context lines for date/attachment info
                ctx_lines = lines[max(0, i - 1): min(len(lines), i + 5)]
                items.append({
                    "title":       line,
                    "date":        "",
                    "attachments": [],
                    "context":     " | ".join(ctx_lines),
                })
                break

    if not items:
        # Return the first 3000 chars so we can see what IS on the page
        items.append({
            "title":       "CLASSWORK_PAGE_TEXT",
            "date":        "",
            "attachments": [],
            "raw_text":    text[:3000],
        })

    return items




# ── Per-team scraper ────────────────────────────────────────────────────────

def scrape_team(page, team_name: str, is_class_teacher: bool) -> dict:
    team_sl = slug(team_name)
    print(f"\n    ── {team_name} {'(class teacher)' if is_class_teacher else ''}")

    result = {
        "team_name":          team_name,
        "is_class_teacher_team": is_class_teacher,
        "general_posts":      [],
        "classwork":          [],
    }

    # Navigate to the team
    print(f"      [nav] Clicking team card...")
    if not click_team(page, team_name):
        print(f"      [nav] Could not click team — skipping")
        save_screenshot(page, f"error_{team_sl}_click")
        return result

    save_screenshot(page, f"team_{team_sl}")

    # Wait for sidebar to appear
    try:
        page.wait_for_selector(
            "[role='treeitem'],[data-tid^='channel-list-item-text-']",
            timeout=10_000)
    except PlaywrightTimeoutError:
        print(f"      [nav] Sidebar did not appear")
        save_screenshot(page, f"error_{team_sl}_sidebar")

    time.sleep(2)

    # Scrape General channel
    result["general_posts"] = scrape_general_channel(page, team_name)
    time.sleep(2)

    # Scrape Classwork — class teacher team only
    if is_class_teacher:
        result["classwork"] = scrape_classwork(page, team_name)
        time.sleep(2)

    return result


# ── Per-child orchestrator ─────────────────────────────────────────────────

def scrape_child(pw, child: dict) -> dict:
    name         = child["name"]
    email        = child["email"]
    password     = child["password"]
    session_file = child["session_file"]
    output_file  = child["output_file"]
    ct_team      = child.get("class_teacher_team", "")
    subject_teams = child.get("subject_teams", [])

    print(f"\n{'='*60}")
    print(f"  Scraping: {name} ({email})")
    print(f"{'='*60}")

    try:
        browser = pw.chromium.launch(
            channel="chrome", headless=False, args=["--start-maximized"])
    except Exception:
        browser = pw.chromium.launch(headless=False, args=["--start-maximized"])

    context  = browser.new_context(viewport=None)
    page     = context.new_page()
    login_ok = False
    teams    = []

    try:
        session_loaded = load_session(context, session_file)
        if session_loaded and is_session_valid(page):
            print(f"  [session] Reusing saved session for {name}")
            login_ok = True
        else:
            print(f"  [session] No valid session — fresh login for {name}")
            login_ok = login(page, email, password, name)
            if login_ok:
                save_session(context, session_file)

        if not login_ok:
            browser.close()
            return {"name": name, "login_ok": False, "teams": []}

        # Build ordered list: class teacher first, then subject teams
        all_teams = []
        if ct_team:
            all_teams.append((ct_team, True))
        for t in subject_teams:
            all_teams.append((t, False))

        print(f"\n  [teams] Will scrape {len(all_teams)} team(s):")
        for t_name, is_ct in all_teams:
            print(f"    • {t_name}{'  ← class teacher' if is_ct else ''}")

        for team_name, is_ct in all_teams:
            try:
                team_data = scrape_team(page, team_name, is_ct)
                teams.append(team_data)
            except Exception as e:
                import traceback
                print(f"    ERROR in '{team_name}': {e}")
                traceback.print_exc()
                save_screenshot(page, f"error_{slug(team_name)}")
            time.sleep(2)

    except Exception as e:
        import traceback
        print(f"\n  ERROR scraping {name}: {e}")
        traceback.print_exc()
        browser.close()
        return {"name": name, "login_ok": login_ok, "error": str(e), "teams": []}

    browser.close()

    output = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "login":        "success" if login_ok else "failed",
        "teams":        teams,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return {"name": name, "login_ok": login_ok, "teams": teams}


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    results = []
    with sync_playwright() as pw:
        for child in CHILDREN:
            results.append(scrape_child(pw, child))

    # Build dashboard JSON
    dashboard = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "children": {}
    }
    for r in results:
        dashboard["children"][r["name"]] = {
            "login":    "success" if r.get("login_ok") else "failed",
            "teams":    r.get("teams", []),
        }
        if "error" in r:
            dashboard["children"][r["name"]]["error"] = r["error"]

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    zero_post_teams = []

    for r in results:
        name    = r.get("name", "?")
        login_ok = r.get("login_ok", False)
        teams   = r.get("teams", [])

        if "error" in r:
            print(f"\n  ❌ {name} — FAILED: {r['error']}")
            continue

        print(f"\n  ✅ {name}")
        print(f"     Login        : {'✅ successful' if login_ok else '⚠️  unconfirmed'}")
        print(f"     Teams scraped: {len(teams)}")

        for j, t in enumerate(teams):
            tname  = t.get("team_name", "?")
            is_ct  = t.get("is_class_teacher_team", False)
            gp     = t.get("general_posts", [])
            cw     = t.get("classwork", [])

            prefix = "└──" if j == len(teams) - 1 else "├──"
            ct_tag = " [class teacher]" if is_ct else ""
            print(f"     {prefix} {tname}{ct_tag}")

            inner = "    " if j == len(teams) - 1 else "│   "
            print(f"     {inner}  💬 General posts: {len(gp)}")
            if not gp:
                zero_post_teams.append(f"{name} / {tname}")

            if is_ct:
                print(f"     {inner}  📚 Classwork items: {len(cw)}")
                for item in cw:
                    title  = item.get("title", "")
                    date   = item.get("date", "")
                    attach = item.get("attachments", [])
                    date_str = f" ({date})" if date else ""
                    attach_str = f" 📎 {len(attach)} file(s)" if attach else ""
                    print(f"     {inner}       - {title}{date_str}{attach_str}")

    print(f"\n  📄 {DASHBOARD_FILE} saved")

    screenshots = sorted(Path(".").glob("*.png"))
    errors = [p.name for p in screenshots if p.name.startswith("error_")]
    others = [p.name for p in screenshots if not p.name.startswith("error_")]
    if errors:
        print(f"  📸 Error screenshots: {errors}")
    if others:
        print(f"  📸 Nav screenshots  : {others}")

    if zero_post_teams:
        print(f"\n  ⚠️  Teams where General posts = 0 (check manually):")
        for t in zero_post_teams:
            print(f"      • {t}")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
