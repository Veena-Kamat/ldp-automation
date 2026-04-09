from flask import Flask, render_template, request, jsonify, make_response
from dotenv import load_dotenv
import anthropic
import urllib.request
import csv
import io
import os
import sys
from datetime import date

load_dotenv()

app = Flask(__name__)
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

ALL_HRBPS = [
    "Aisha Walker", "Aparna Johnson", "Ishaan Farouk",
    "Mariam Lee", "Meghna Iqbal", "Nawaf Bhat",
    "Pranav Young", "Ryan Venkataraman", "Saif Sivasubramanian",
    "Salman Varma", "Thomas Subramaniam", "Yusuf Jackson",
    "Daniel Smith", "Maria Verma", "Hamdan Malik",
    "Thomas Varma", "Stanley Al-Dhaheri", "Anita Al-Farsi",
    "Varun Al-Farsi"
]

PROGRAMME_DEADLINES = {
    "batch04_nomination_deadline": date(2026, 4, 7),
    "batch04_workshop_day1":       date(2026, 4, 28),
    "batch04_workshop_day2":       date(2026, 4, 29),
    "batch04_vl_deadline":         date(2026, 5, 27),
}

# ── Agent tool definitions ────────────────────────────────────
AGENT_TOOLS = [
    {
        "name": "run_agent1",
        "description": (
            "Run Agent 1 — Nominations Workflow. Reads LDP Tracker for TBD and previous "
            "non-attendee employees, reads nomination form responses, updates tracker with "
            "nominations and deferrals, drafts nomination emails to HRBPs, reminder emails "
            "to non-responders, confirmation emails, and joining emails to participants."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "run_agent2_preworkshop",
        "description": (
            "Run Agent 2 Pre-Workshop — Draft and send day-before reminder emails to "
            "all confirmed participants for the upcoming batch workshop."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "run_agent2_postworkshop",
        "description": (
            "Run Agent 2 Post-Workshop — Read attendance sheet, update tracker with "
            "Day 1 & Day 2 attendance, send thank you emails to attendees, draft "
            "follow-up emails for non-attendees, remove absent employees from this batch."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "run_agent3",
        "description": (
            "Run Agent 3 — VL Tracking & Completion. Read VL report, update VL status "
            "in tracker, draft certificate emails for completers, first and second nudge "
            "emails for non-completers, feedback survey emails, and generate batch closed report."
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

def get_todays_actions(tracker, nominations):
    today = date.today()
    actions = []
    warnings = []

    nom_deadline  = PROGRAMME_DEADLINES["batch04_nomination_deadline"]
    ws_day1       = PROGRAMME_DEADLINES["batch04_workshop_day1"]
    ws_day2       = PROGRAMME_DEADLINES["batch04_workshop_day2"]
    vl_deadline   = PROGRAMME_DEADLINES["batch04_vl_deadline"]

    responded_hrbps = set()
    for nom in nominations:
        for key, value in nom.items():
            if "name" in key.lower() and value.strip():
                responded_hrbps.add(value.strip())
                break
    not_responded = [h for h in ALL_HRBPS if h not in responded_hrbps]

    days_to_nom = (nom_deadline - today).days
    if 0 <= days_to_nom <= 3 and not_responded:
        actions.append(
            f"URGENT: Nomination deadline in {days_to_nom} day(s). "
            f"{len(not_responded)} HRBPs haven't responded: {', '.join(not_responded[:4])}. "
            "Send reminders — Run Agent 1."
        )
    elif days_to_nom < 0 and not_responded:
        warnings.append(
            f"Nomination deadline passed. {len(not_responded)} HRBPs never responded."
        )
    elif not_responded and days_to_nom > 0:
        actions.append(
            f"Batch 04 nominations: {len(responded_hrbps)}/{len(ALL_HRBPS)} HRBPs responded. "
            f"{days_to_nom} days until deadline."
        )

    batch04_confirmed = [
        e for e in tracker
        if e.get("Batch", "").strip() == "Batch-04-2026"
        and e.get("Nomination Status", "").strip() == "Nominated"
    ]
    days_to_ws = (ws_day1 - today).days
    if days_to_ws == 1:
        actions.append(
            f"URGENT: Workshop TOMORROW! Send pre-workshop reminders to "
            f"{len(batch04_confirmed)} participants. Run Agent 2 Pre-Workshop."
        )
    elif days_to_ws == 0:
        actions.append("TODAY is Workshop Day 1 for Batch 04. Ensure attendance tracking is ready.")
    elif (today - ws_day2).days == 1:
        actions.append(
            "Workshop ended yesterday. Run Agent 2 Post-Workshop to update attendance and send emails."
        )
    elif 1 < days_to_ws <= 7:
        actions.append(
            f"Workshop in {days_to_ws} days ({ws_day1.strftime('%d %b')}). "
            f"{len(batch04_confirmed)} participants confirmed."
        )

    vl_pending = [
        e for e in tracker
        if e.get("VL Status", "").strip() in ("Not Started", "In Progress")
        and e.get("Day 1 Attendance", "").strip() == "Attended"
        and e.get("Day 2 Attendance", "").strip() == "Attended"
    ]
    if vl_pending:
        days_to_vl = (vl_deadline - today).days
        actions.append(
            f"{len(vl_pending)} employees have incomplete VL. "
            f"VL deadline: {vl_deadline.strftime('%d %b')} ({days_to_vl} days). Run Agent 3."
        )

    tbd = [e for e in tracker if e.get("Batch", "").strip() == "TBD"]
    if tbd:
        actions.append(f"{len(tbd)} employees still TBD — not yet batched. Run Agent 1.")

    return actions, warnings

def build_summary(tracker, nominations):
    today_str = date.today().strftime("%d %B %Y")
    batches = {}
    vl_not_started = {}
    absent_employees = {}

    for emp in tracker:
        batch = emp.get("Batch", "").strip() or "TBD"
        if batch not in batches:
            batches[batch] = {
                "total": 0, "confirmed": 0, "attended_both": 0,
                "vl_completed": 0, "vl_in_progress": 0,
                "vl_not_started": 0, "training_complete": 0, "certs_issued": 0
            }
            vl_not_started[batch] = []
            absent_employees[batch] = []

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
        elif d1 == "Absent" or d2 == "Absent":
            absent_employees[batch].append(f"{name} (HRBP: {hrbp}, Manager: {mgr})")

        vl = emp.get("VL Status", "").strip()
        if vl == "Completed":
            b["vl_completed"] += 1
        elif vl == "In Progress":
            b["vl_in_progress"] += 1
        elif vl == "Not Started":
            b["vl_not_started"] += 1
            vl_not_started[batch].append(f"{name} ({fn}, HRBP: {hrbp})")

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

    not_responded = [h for h in ALL_HRBPS if h not in hrbp_responses]

    summary = f"TODAY: {today_str}\n\nBATCH STATUS:\n"
    for bn in ["Batch-01-2026", "Batch-02-2026", "Batch-03-2026", "Batch-04-2026", "TBD"]:
        if bn not in batches:
            continue
        b = batches[bn]
        if bn == "TBD":
            summary += f"\nAwaiting future batches: {b['total']} employees\n"
            continue
        summary += f"""
{bn}:
  Confirmed: {b['confirmed']}  Attended both days: {b['attended_both']}
  VL Completed: {b['vl_completed']}  VL In Progress: {b['vl_in_progress']}  VL Not Started: {b['vl_not_started']}
  Training Complete: {b['training_complete']}  Certs Issued: {b['certs_issued']}
"""
        if vl_not_started.get(bn):
            summary += f"  VL not started: {', '.join(vl_not_started[bn])}\n"
        if absent_employees.get(bn):
            summary += f"  Absent: {', '.join(absent_employees[bn])}\n"

    summary += f"""
BATCH 04 NOMINATIONS:
  HRBPs responded: {len(hrbp_responses)} of {len(ALL_HRBPS)}
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

def capture_agent_output(fn, *args, **kwargs):
    """Run a function, capturing all its stdout output."""
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        fn(*args, **kwargs)
        output = buffer.getvalue()
    except Exception as e:
        output = f"[ERROR]: {e}"
    finally:
        sys.stdout = old_stdout
    return output

def execute_agent_tool(tool_name, tool_input):
    """Import and run the requested agent, return its printed output."""
    import importlib.util
    agents_dir = os.path.join(os.path.dirname(__file__), "agents")

    if tool_name == "run_agent1":
        spec = importlib.util.spec_from_file_location("agent1_run", os.path.join(agents_dir, "agent1_run.py"))
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        return capture_agent_output(mod.run_agent1)

    elif tool_name == "run_agent2_preworkshop":
        spec = importlib.util.spec_from_file_location("agent2_pre", os.path.join(agents_dir, "agent2_preWorkshop.py"))
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        return capture_agent_output(mod.run_agent2_preworkshop)

    elif tool_name == "run_agent2_postworkshop":
        spec = importlib.util.spec_from_file_location("agent2_post", os.path.join(agents_dir, "agent2_workshop.py"))
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        return capture_agent_output(mod.run_agent2)

    elif tool_name == "run_agent3":
        spec = importlib.util.spec_from_file_location("agent3", os.path.join(agents_dir, "agent3_completion.py"))
        mod = importlib.util.load_from_spec(spec)
        spec.loader.exec_module(mod)
        vl_id = tool_input.get("vl_sheet_id", VL_REPORT_ID)
        return capture_agent_output(mod.run_agent3, vl_sheet_id=vl_id)

    return f"Unknown agent: {tool_name}"


@app.route("/")
def index():
    response = make_response(render_template("chat.html"))
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response


@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message", "")

    tracker     = read_ldp_tracker()
    nominations = read_nominations()
    summary     = build_summary(tracker, nominations)
    actions, warnings = get_todays_actions(tracker, nominations)

    actions_text = "\n".join(f"• {a}" for a in actions)
    warnings_text = "\n".join(f"⚠ {w}" for w in warnings) if warnings else ""

    context = summary
    if actions_text:
        context += f"\n\nTODAY'S PRIORITY ACTIONS:\n{actions_text}"
    if warnings_text:
        context += f"\n\nWARNINGS:\n{warnings_text}"

    messages = [{
        "role": "user",
        "content": f"""You are the LDP Programme Supervisor Agent with full visibility
of the Leadership Development Programme across all batches.

Current programme data:
{context}

Answer the HR Manager's question clearly and helpfully.
Use structured formatting with headers and bullet points.
Flag urgent items clearly.

If asked to draft emails, create ONE separate ---EMAIL--- block per person:
---EMAIL---
TO: [single person name or email]
SUBJECT: [subject line]
BODY:
[full email body]
---END---

If the user asks you to run an agent or take action on the programme,
use the available tools to do so.

Question: {user_message}"""
    }]

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        tools=AGENT_TOOLS,
        messages=messages,
    )

    # Handle tool calls (agent runs)
    agent_outputs = []
    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                output = execute_agent_tool(block.name, block.input)
                agent_outputs.append({"agent": block.name, "output": output})
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output[:4000],
                })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user",      "content": tool_results})

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=AGENT_TOOLS,
            messages=messages,
        )

    reply = ""
    for block in response.content:
        if hasattr(block, "text"):
            reply = block.text
            break

    return jsonify({"reply": reply, "agent_outputs": agent_outputs})


@app.route("/run_agent", methods=["POST"])
def run_agent():
    """Direct endpoint to run an agent and return its output."""
    data       = request.json or {}
    agent_name = data.get("agent", "")
    vl_id      = data.get("vl_sheet_id", VL_REPORT_ID)

    tool_map = {
        "agent1":         "run_agent1",
        "agent2_pre":     "run_agent2_preworkshop",
        "agent2_post":    "run_agent2_postworkshop",
        "agent3":         "run_agent3",
    }

    tool_name = tool_map.get(agent_name)
    if not tool_name:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 400

    tool_input = {"vl_sheet_id": vl_id} if agent_name == "agent3" else {}
    output = execute_agent_tool(tool_name, tool_input)
    return jsonify({"agent": agent_name, "output": output})


@app.route("/todays_actions", methods=["GET"])
def todays_actions():
    """Return today's priority actions as JSON."""
    tracker     = read_ldp_tracker()
    nominations = read_nominations()
    actions, warnings = get_todays_actions(tracker, nominations)
    return jsonify({"actions": actions, "warnings": warnings})


@app.after_request
def add_headers(response):
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


if __name__ == "__main__":
    app.run(debug=True)
