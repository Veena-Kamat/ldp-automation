import anthropic
from dotenv import load_dotenv
import os
import urllib.request
import csv
import io
import json
from datetime import date

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SHEET_ID             = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
VL_REPORT_ID         = "1-cKaveDPqRyj8PR7b2jMegHyNbipyOIT7B7mLi68HRI"

SECTION_LABELS = [
    "IDENTITY & SCOPE ",
    "BATCH & NOMINATION ",
    "WORKSHOP ATTENDANCE ",
    "VIRTUAL LEARNING ",
    "COMPLETION & CERTIFICATION ",
    "FEEDBACK ",
]

# Key programme dates / deadlines for TODAY context
PROGRAMME_DEADLINES = {
    "batch04_nomination_deadline": date(2026, 4, 7),
    "batch04_workshop_day1":       date(2026, 4, 28),
    "batch04_workshop_day2":       date(2026, 4, 29),
    "batch04_vl_deadline":         date(2026, 5, 27),  # ~4 weeks after workshop
    "batch04_vl_second_nudge":     date(2026, 5, 20),  # 1 week before VL deadline
}

ALL_HRBPS = [
    "Aisha Walker", "Aparna Johnson", "Ishaan Farouk",
    "Mariam Lee", "Meghna Iqbal", "Nawaf Bhat",
    "Pranav Young", "Ryan Venkataraman", "Saif Sivasubramanian",
    "Salman Varma", "Thomas Subramaniam", "Yusuf Jackson",
    "Daniel Smith", "Maria Verma", "Hamdan Malik",
    "Thomas Varma", "Stanley Al-Dhaheri", "Anita Al-Farsi",
    "Varun Al-Farsi"
]

# ── Agent tool definitions for Claude tool_use ────────────────
AGENT_TOOLS = [
    {
        "name": "run_agent1",
        "description": (
            "Run Agent 1 — Nominations Workflow. "
            "Reads LDP Tracker for TBD employees, finds previous non-attendees, "
            "reads nomination form responses, updates tracker with nominations/deferrals, "
            "drafts nomination emails to HRBPs, reminder emails to non-responders, "
            "confirmation emails, and joining emails to participants."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "run_agent2_preworkshop",
        "description": (
            "Run Agent 2 Pre-Workshop — Send reminder emails to confirmed participants "
            "the day before the workshop. Reads confirmed participants from tracker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "run_agent2_postworkshop",
        "description": (
            "Run Agent 2 Post-Workshop — Reads attendance sheet, updates tracker with "
            "Day 1 & Day 2 attendance, sends thank you emails to attendees, drafts "
            "follow-up emails for non-attendees, removes absent employees from this batch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "run_agent3",
        "description": (
            "Run Agent 3 — VL Tracking & Completion. Reads the VL report, updates "
            "VL status in tracker, drafts certificate emails for completers, nudge emails "
            "for non-completers (1st and 2nd), feedback survey emails, and generates "
            "a batch closed report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vl_sheet_id": {
                    "type": "string",
                    "description": f"VL Report Google Sheet ID. Default: {VL_REPORT_ID}"
                }
            },
            "required": []
        }
    }
]


def clean_header(h):
    for label in SECTION_LABELS:
        if h.startswith(label):
            return h.replace(label, "")
    return h

def read_ldp_tracker():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=LDP%20Tracker"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    all_rows = list(reader)
    headers = [clean_header(h) for h in all_rows[0]]
    data = []
    for row in all_rows[1:]:
        if any(cell.strip() for cell in row):
            data.append(dict(zip(headers, row)))
    return data

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv&gid=1000019961"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def get_todays_actions(tracker, nominations, today=None):
    """
    Analyse the programme state relative to today's date and
    return a structured list of urgent actions.
    """
    if today is None:
        today = date.today()

    actions = []
    warnings = []

    # ── Nomination deadline check ─────────────────────────────
    nom_deadline = PROGRAMME_DEADLINES["batch04_nomination_deadline"]
    days_to_nom_deadline = (nom_deadline - today).days

    responded_hrbps = set()
    for nom in nominations:
        for key, value in nom.items():
            if "name" in key.lower() and value.strip():
                responded_hrbps.add(value.strip())
                break

    not_responded = [h for h in ALL_HRBPS if h not in responded_hrbps]

    if days_to_nom_deadline >= 0:
        if days_to_nom_deadline <= 3 and not_responded:
            actions.append(
                f"URGENT: Batch 04 nomination deadline is in {days_to_nom_deadline} day(s) "
                f"({nom_deadline.strftime('%d %b')}). "
                f"{len(not_responded)} HRBPs have NOT responded: {', '.join(not_responded[:5])}{'...' if len(not_responded) > 5 else ''}. "
                "Send reminders NOW."
            )
        elif not_responded:
            actions.append(
                f"Nomination deadline: {days_to_nom_deadline} day(s) away. "
                f"{len(not_responded)} HRBPs not yet responded. Consider sending reminders."
            )

    if days_to_nom_deadline < 0 and not_responded:
        warnings.append(
            f"Nomination deadline has passed. {len(not_responded)} HRBPs never responded — "
            "decide whether to extend or proceed without them."
        )

    # ── Workshop day check ────────────────────────────────────
    ws_day1 = PROGRAMME_DEADLINES["batch04_workshop_day1"]
    ws_day2 = PROGRAMME_DEADLINES["batch04_workshop_day2"]
    days_to_workshop = (ws_day1 - today).days

    batch04_confirmed = [
        e for e in tracker
        if e.get("Batch", "").strip() == "Batch-04-2026"
        and e.get("Nomination Status", "").strip() == "Nominated"
    ]

    if 0 < days_to_workshop <= 1:
        actions.append(
            f"URGENT: Batch 04 workshop starts TOMORROW ({ws_day1.strftime('%d %b')}). "
            f"Send pre-workshop reminders to {len(batch04_confirmed)} confirmed participants NOW. "
            "Run Agent 2 Pre-Workshop."
        )
    elif 1 < days_to_workshop <= 7:
        actions.append(
            f"Workshop in {days_to_workshop} days ({ws_day1.strftime('%d %b')}). "
            f"{len(batch04_confirmed)} participants confirmed. "
            "Prepare logistics and run Agent 2 Pre-Workshop the day before."
        )
    elif days_to_workshop == 0:
        actions.append(
            f"TODAY is Workshop Day 1 for Batch 04. "
            "Ensure attendance sheet is ready. After Day 2, run Agent 2 Post-Workshop."
        )
    elif (today - ws_day2).days == 1:
        actions.append(
            "Workshop ended YESTERDAY. Run Agent 2 Post-Workshop to update attendance, "
            "send thank you emails, and follow up with non-attendees."
        )

    # ── VL tracking check ─────────────────────────────────────
    vl_deadline = PROGRAMME_DEADLINES["batch04_vl_deadline"]
    second_nudge_date = PROGRAMME_DEADLINES["batch04_vl_second_nudge"]
    days_to_vl_deadline = (vl_deadline - today).days

    batch03_vl_pending = [
        e for e in tracker
        if e.get("Batch", "").strip() == "Batch-03-2026"
        and e.get("VL Status", "").strip() in ("Not Started", "In Progress")
        and e.get("Day 1 Attendance", "").strip() == "Attended"
        and e.get("Day 2 Attendance", "").strip() == "Attended"
    ]
    batch03_completed = [
        e for e in tracker
        if e.get("Batch", "").strip() == "Batch-03-2026"
        and e.get("Training Complete", "").strip() == "Yes"
    ]

    if batch03_vl_pending:
        if today >= second_nudge_date:
            actions.append(
                f"URGENT: {len(batch03_vl_pending)} Batch 03 employees still haven't completed VL "
                f"(deadline: {vl_deadline.strftime('%d %b')}). Send second nudge emails. Run Agent 3."
            )
        else:
            actions.append(
                f"{len(batch03_vl_pending)} Batch 03 employees still completing VL. "
                f"Deadline: {vl_deadline.strftime('%d %b')} ({days_to_vl_deadline} days). "
                "Run Agent 3 for nudge emails."
            )

    if batch03_completed:
        cert_missing = [e for e in batch03_completed if not e.get("Certificate Issued Date", "").strip()]
        if cert_missing:
            actions.append(
                f"{len(cert_missing)} Batch 03 employees completed training but certificates not yet issued. "
                "Run Agent 3 to draft certificate emails."
            )

    # ── TBD employees ─────────────────────────────────────────
    tbd = [e for e in tracker if e.get("Batch", "").strip() == "TBD"]
    if tbd:
        actions.append(
            f"{len(tbd)} employees are still TBD (not assigned to a batch). "
            "Consider running Agent 1 to send nomination emails for the next batch."
        )

    return actions, warnings

def build_programme_summary(tracker, nominations):
    today_str = date.today().strftime("%d %B %Y")
    batches = {}
    vl_details = {}
    attendance_details = {}

    for emp in tracker:
        batch = emp.get("Batch", "").strip() or "TBD"
        if batch not in batches:
            batches[batch] = {
                "total": 0, "confirmed": 0, "attended_both": 0,
                "vl_completed": 0, "vl_in_progress": 0, "vl_not_started": 0,
                "training_complete": 0, "certs_issued": 0,
            }
            vl_details[batch] = {"completed": [], "in_progress": [], "not_started": []}
            attendance_details[batch] = {"attended_both": [], "absent": [], "partial": []}

        b = batches[batch]
        name   = emp.get("Employee Name", "").strip()
        hrbp   = emp.get("HRBP Name", "").strip()
        fn     = emp.get("Function", "").strip()
        mgr    = emp.get("Manager Name", "").strip()
        vl_pct = emp.get("VL Completion %", "").strip()

        b["total"] += 1
        if emp.get("Nomination Status", "").strip() == "Confirmed":
            b["confirmed"] += 1

        d1 = emp.get("Day 1 Attendance", "").strip()
        d2 = emp.get("Day 2 Attendance", "").strip()
        if d1 == "Attended" and d2 == "Attended":
            b["attended_both"] += 1
            attendance_details[batch]["attended_both"].append(name)
        elif d1 == "Absent" and d2 == "Absent":
            attendance_details[batch]["absent"].append(f"{name} (HRBP: {hrbp}, Manager: {mgr})")
        elif d1 == "Attended" or d2 == "Attended":
            attendance_details[batch]["partial"].append(f"{name} (HRBP: {hrbp})")

        vl = emp.get("VL Status", "").strip()
        if vl == "Completed":
            b["vl_completed"] += 1
            vl_details[batch]["completed"].append(name)
        elif vl == "In Progress":
            b["vl_in_progress"] += 1
            vl_details[batch]["in_progress"].append(f"{name} ({vl_pct})")
        elif vl == "Not Started":
            b["vl_not_started"] += 1
            vl_details[batch]["not_started"].append(f"{name} (HRBP: {hrbp})")

        if emp.get("Training Complete", "").strip() == "Yes":
            b["training_complete"] += 1
        if emp.get("Certificate Issued Date", "").strip() not in ("", "—"):
            b["certs_issued"] += 1

    # Build name → function lookup from tracker for nominee enrichment
    name_to_function = {
        emp.get("Employee Name", "").strip(): emp.get("Function", "").strip()
        for emp in tracker
        if emp.get("Employee Name", "").strip()
    }

    hrbp_responses = {}
    all_nominees = []
    special_cases = []

    for nom in nominations:
        hrbp = ""
        nominees = []
        comments = ""
        for key, value in nom.items():
            if "name" in key.lower():
                hrbp = value.strip()
            if "nominate" in key.lower() or "eligible" in key.lower():
                nominees = [n.strip() for n in value.split(",") if n.strip()]
            if "comment" in key.lower() or "special" in key.lower():
                comments = value.strip()
        if hrbp:
            hrbp_responses[hrbp] = {"nominees": nominees, "comments": comments}
            all_nominees.extend(nominees)
            if comments:
                special_cases.append(f"{hrbp}: {comments}")

    responded  = list(hrbp_responses.keys())
    not_responded = [h for h in ALL_HRBPS if h not in responded]

    summary = f"TODAY: {today_str}\n\nBATCH STATUS:\n"
    for bn in ["Batch-01-2026", "Batch-02-2026", "Batch-03-2026", "Batch-04-2026", "TBD"]:
        if bn not in batches:
            continue
        b = batches[bn]
        vl  = vl_details.get(bn, {})
        att = attendance_details.get(bn, {})

        if bn == "TBD":
            summary += f"\nAwaiting future batches: {b['total']} employees\n"
            continue

        summary += f"""
{bn}:
  Confirmed nominations: {b['confirmed']}
  Attended both days:    {b['attended_both']}
  Absent both days:      {len(att.get('absent', []))}
  Partial attendance:    {len(att.get('partial', []))}
  VL Completed:          {b['vl_completed']}
  VL In Progress:        {b['vl_in_progress']}
  VL Not Started:        {b['vl_not_started']}
  Training Complete:     {b['training_complete']}
  Certificates Issued:   {b['certs_issued']}
"""
        if att.get("absent"):
            summary += f"  Absent: {', '.join(att['absent'])}\n"
        if att.get("partial"):
            summary += f"  Partial: {', '.join(att['partial'])}\n"
        if vl.get("not_started"):
            summary += f"  VL not started: {', '.join(vl['not_started'])}\n"
        if vl.get("in_progress"):
            summary += f"  VL in progress: {', '.join(vl['in_progress'])}\n"

    summary += f"""
BATCH 04 NOMINATIONS:
  Total HRBPs: {len(ALL_HRBPS)}
  Responded:   {len(hrbp_responses)}
  Not responded: {', '.join(not_responded) if not_responded else 'All responded'}
  Total nominees: {len(all_nominees)}
  Deadline: 7 April 2026
"""
    for hrbp, data in hrbp_responses.items():
        nominees_with_fn = [
            f"{n} ({name_to_function.get(n, 'Unknown')})"
            for n in data["nominees"]
        ]
        summary += f"  {hrbp}: {', '.join(nominees_with_fn)}\n"
        if data["comments"]:
            summary += f"    Note: {data['comments']}\n"

    if special_cases:
        summary += "\nSPECIAL CASES:\n"
        for case in special_cases:
            summary += f"  {case}\n"

    return summary

def execute_agent_tool(tool_name, tool_input):
    """Run the requested agent and return its output as a string."""
    import sys, io as sysio
    old_stdout = sys.stdout
    sys.stdout = buffer = sysio.StringIO()
    try:
        if tool_name == "run_agent1":
            import importlib.util, os
            spec = importlib.util.spec_from_file_location(
                "agent1_run",
                os.path.join(os.path.dirname(__file__), "..", "agents", "agent1_run.py")
            )
            mod = importlib.util.load_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_agent1()

        elif tool_name == "run_agent2_preworkshop":
            import importlib.util, os
            spec = importlib.util.spec_from_file_location(
                "agent2_preWorkshop",
                os.path.join(os.path.dirname(__file__), "..", "agents", "agent2_preWorkshop.py")
            )
            mod = importlib.util.load_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_agent2_preworkshop()

        elif tool_name == "run_agent2_postworkshop":
            import importlib.util, os
            spec = importlib.util.spec_from_file_location(
                "agent2_workshop",
                os.path.join(os.path.dirname(__file__), "..", "agents", "agent2_workshop.py")
            )
            mod = importlib.util.load_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_agent2()

        elif tool_name == "run_agent3":
            import importlib.util, os
            vl_id = tool_input.get("vl_sheet_id", VL_REPORT_ID)
            spec = importlib.util.spec_from_file_location(
                "agent3_completion",
                os.path.join(os.path.dirname(__file__), "..", "agents", "agent3_completion.py")
            )
            mod = importlib.util.load_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run_agent3(vl_sheet_id=vl_id)

        output = buffer.getvalue()
    except Exception as e:
        output = f"[ERROR running {tool_name}]: {e}"
    finally:
        sys.stdout = old_stdout
    return output

def ask_supervisor(question, programme_summary, todays_actions=None):
    """Answer a question using Claude with agent tool-use capabilities."""
    context = programme_summary
    if todays_actions:
        actions_text = "\n".join(f"  • {a}" for a in todays_actions[0])
        warnings_text = "\n".join(f"  ⚠ {w}" for w in todays_actions[1])
        context += f"\n\nTODAY'S PRIORITY ACTIONS:\n{actions_text}"
        if warnings_text:
            context += f"\n\nWARNINGS:\n{warnings_text}"

    messages = [
        {
            "role": "user",
            "content": f"""You are the LDP Programme Supervisor Agent with full visibility
of the Leadership Development Programme across all batches.

Current programme data:
{context}

Answer the following question from the HR Manager clearly and helpfully.
Be specific with numbers. Use structured formatting.
Highlight anything urgent. If the user asks you to run an agent or take action,
use the available tools.

Question: {question}"""
        }
    ]

    # First call — may return tool_use blocks
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        tools=AGENT_TOOLS,
        messages=messages,
    )

    # Handle tool calls (agent execution requests)
    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\n[Supervisor] Running {block.name}...")
                output = execute_agent_tool(block.name, block.input)
                print(output[:500] + ("..." if len(output) > 500 else ""))
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output[:4000],  # truncate for context
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=AGENT_TOOLS,
            messages=messages,
        )

    # Extract final text response
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return "No response generated."


# ── CLI entry point ────────────────────────────────────────────
if __name__ == "__main__":
    print("="*60)
    print("LDP PROGRAMME SUPERVISOR")
    print("Type your question. Type 'today' for today's actions. Type 'exit' to quit.")
    print("="*60)
    print("\nSupervisor ready. Data reloads with every question.\n")

    while True:
        print("-"*60)
        question = input("You: ").strip()

        if question.lower() in ("exit", "quit", "bye"):
            print("\nSupervisor: Goodbye!")
            break
        if not question:
            continue

        print("\nLoading latest data...")
        tracker     = read_ldp_tracker()
        nominations = read_nominations()
        summary     = build_programme_summary(tracker, nominations)
        todays      = get_todays_actions(tracker, nominations)

        if question.lower() == "today":
            print("\n--- TODAY'S PRIORITY ACTIONS ---")
            for action in todays[0]:
                print(f"  • {action}")
            if todays[1]:
                print("\n--- WARNINGS ---")
                for warning in todays[1]:
                    print(f"  ⚠ {warning}")
            continue

        print("Supervisor: thinking...\n")
        response = ask_supervisor(question, summary, todays)
        print(f"Supervisor: {response}\n")
