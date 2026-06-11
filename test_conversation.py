#!/usr/bin/env python3
"""
Terminal chat client for testing the dental AI receptionist.
Simulates an inbound call from a seeded patient; executes tool calls against dental.db.

Usage:
    python3 test_conversation.py              # interactive patient selection
    python3 test_conversation.py --patient 1  # by patient ID
    python3 test_conversation.py --patient +15550001002  # by phone
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).parent
DB_PATH = ROOT / "dental.db"
PROMPTS_DIR = ROOT / "prompts"


# ── Database helpers ──────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found. Run: python3 db/init_db.py --seed")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def list_patients(conn):
    return conn.execute("SELECT id, name, phone FROM patients ORDER BY id").fetchall()


def find_patient(conn, identifier: str):
    """Lookup by integer ID or E.164 phone number."""
    if identifier.lstrip("+").isdigit() and not identifier.startswith("+"):
        return conn.execute(
            "SELECT id, name, phone FROM patients WHERE id = ?", (int(identifier),)
        ).fetchone()
    return conn.execute(
        "SELECT id, name, phone FROM patients WHERE phone = ?", (identifier,)
    ).fetchone()


def load_upcoming(conn, patient_id: int):
    return conn.execute(
        """SELECT id, type, start_time, duration, provider
           FROM appointments
           WHERE patient_id = ? AND status = 'scheduled'
             AND start_time > datetime('now')
           ORDER BY start_time""",
        (patient_id,),
    ).fetchall()


# ── Patient context (PHI-minimised) ──────────────────────────────────────────

def build_patient_context(patient_id: int, upcoming) -> dict:
    """
    Only appointment IDs, types, and dates go into LLM context.
    Name, DOB, and other PHI stay in the DB.
    """
    return {
        "patient_id": patient_id,
        "upcoming_appointments": [
            {
                "id": row["id"],
                "type": row["type"],
                "date": row["start_time"][:10],
                "provider": row["provider"],
            }
            for row in upcoming
        ],
    }


# ── Tool implementations ──────────────────────────────────────────────────────

def tool_check_availability(conn, date: str, provider: str = None) -> dict:
    try:
        target = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Invalid date '{date}'. Use YYYY-MM-DD."}

    if target.date() < datetime.now().date():
        return {"error": "Cannot check availability for a past date."}

    day_name = target.strftime("%A").lower()

    hours = json.loads(
        conn.execute("SELECT value FROM practice_settings WHERE key='hours'").fetchone()["value"]
    )
    buffer_rules = json.loads(
        conn.execute("SELECT value FROM practice_settings WHERE key='buffer_rules'").fetchone()["value"]
    )

    day_hours = hours.get(day_name)
    if not day_hours:
        return {
            "available": False,
            "reason": f"Practice is closed on {target.strftime('%A')}s.",
        }

    buffer_min = buffer_rules.get("between_appointments_min", 15)
    open_dt = datetime.strptime(f"{date} {day_hours['open']}", "%Y-%m-%d %H:%M")
    close_dt = datetime.strptime(f"{date} {day_hours['close']}", "%Y-%m-%d %H:%M")

    query = """
        SELECT start_time, duration FROM appointments
        WHERE start_time >= ? AND start_time < ? AND status = 'scheduled'
    """
    params: list = [f"{date}T00:00:00Z", f"{date}T23:59:59Z"]
    if provider:
        query += " AND provider LIKE ?"
        params.append(f"%{provider}%")

    busy: list[tuple[datetime, datetime]] = []
    for row in conn.execute(query, params).fetchall():
        # Stored as UTC ISO; treat as practice-local for dev simplicity
        s = row["start_time"].rstrip("Z").replace("T", " ")
        fmt = "%Y-%m-%d %H:%M:%S" if len(s) > 16 else "%Y-%m-%d %H:%M"
        start = datetime.strptime(s, fmt)
        end = start + timedelta(minutes=row["duration"] + buffer_min)
        busy.append((start - timedelta(minutes=buffer_min), end))

    slots = []
    slot_dur = timedelta(minutes=30)
    cur = open_dt
    while cur + slot_dur <= close_dt:
        end = cur + slot_dur
        if not any(not (end <= b_s or cur >= b_e) for b_s, b_e in busy):
            slots.append(cur.strftime("%Y-%m-%dT%H:%M:00"))
        cur += slot_dur

    return {
        "date": date,
        "day": target.strftime("%A"),
        "practice_hours": f"{day_hours['open']}–{day_hours['close']}",
        "provider_filter": provider or "any",
        "available_slots": slots[:12],
    }


def tool_get_appointment(conn, patient_id: int) -> dict:
    rows = conn.execute(
        """SELECT id, type, start_time, duration, provider, status
           FROM appointments
           WHERE patient_id = ? AND status = 'scheduled'
           ORDER BY start_time""",
        (patient_id,),
    ).fetchall()
    if not rows:
        return {"appointments": [], "note": "No upcoming scheduled appointments found."}
    return {
        "appointments": [
            {
                "id": r["id"],
                "type": r["type"],
                "start_time": r["start_time"],
                "duration_min": r["duration"],
                "provider": r["provider"],
            }
            for r in rows
        ]
    }


def tool_reschedule_appointment(
    conn, appointment_id: int, new_time: str, current_patient_id: int
) -> dict:
    row = conn.execute(
        "SELECT id, patient_id, start_time, type, provider, status FROM appointments WHERE id = ?",
        (appointment_id,),
    ).fetchone()
    if not row:
        return {"error": f"Appointment #{appointment_id} not found."}
    if row["patient_id"] != current_patient_id:
        return {"error": "That appointment does not belong to the current patient."}
    if row["status"] != "scheduled":
        return {"error": f"Appointment is {row['status']} and cannot be rescheduled."}

    old_val = json.dumps({"start_time": row["start_time"], "status": "scheduled"})
    new_val = json.dumps({"start_time": new_time, "status": "scheduled"})

    conn.execute(
        "UPDATE appointments SET start_time = ? WHERE id = ?",
        (new_time, appointment_id),
    )
    conn.execute(
        """INSERT INTO appointment_changes (appointment_id, change_type, old_value, new_value)
           VALUES (?, 'reschedule', ?, ?)""",
        (appointment_id, old_val, new_val),
    )
    conn.commit()
    return {
        "success": True,
        "appointment_id": appointment_id,
        "type": row["type"],
        "old_time": row["start_time"],
        "new_time": new_time,
        "provider": row["provider"],
    }


def tool_cancel_appointment(
    conn, appointment_id: int, current_patient_id: int
) -> dict:
    row = conn.execute(
        "SELECT id, patient_id, start_time, type, provider, status FROM appointments WHERE id = ?",
        (appointment_id,),
    ).fetchone()
    if not row:
        return {"error": f"Appointment #{appointment_id} not found."}
    if row["patient_id"] != current_patient_id:
        return {"error": "That appointment does not belong to the current patient."}
    if row["status"] != "scheduled":
        return {"error": f"Appointment is already {row['status']}."}

    old_val = json.dumps({"status": "scheduled", "start_time": row["start_time"]})
    new_val = json.dumps({"status": "cancelled"})

    conn.execute(
        "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
        (appointment_id,),
    )
    conn.execute(
        """INSERT INTO appointment_changes (appointment_id, change_type, old_value, new_value)
           VALUES (?, 'cancel', ?, ?)""",
        (appointment_id, old_val, new_val),
    )
    conn.commit()
    return {
        "success": True,
        "appointment_id": appointment_id,
        "type": row["type"],
        "cancelled_time": row["start_time"],
        "provider": row["provider"],
    }


def tool_escalate_to_human(reason: str) -> dict:
    return {
        "escalated": True,
        "reason": reason,
        "action": "Transfer patient to front desk staff.",
    }


# ── Tool dispatcher ───────────────────────────────────────────────────────────

def execute_tool(conn, name: str, args: dict, current_patient_id: int) -> dict:
    if name == "check_availability":
        return tool_check_availability(conn, **args)
    if name == "get_appointment":
        # Always serve the current patient regardless of what the LLM passes
        return tool_get_appointment(conn, current_patient_id)
    if name == "reschedule_appointment":
        return tool_reschedule_appointment(
            conn, args["appointment_id"], args["new_time"], current_patient_id
        )
    if name == "cancel_appointment":
        return tool_cancel_appointment(conn, args["appointment_id"], current_patient_id)
    if name == "escalate_to_human":
        return tool_escalate_to_human(args.get("reason", ""))
    return {"error": f"Unknown tool: {name}"}


# ── Conversation loop ─────────────────────────────────────────────────────────

def run_conversation(client: OpenAI, conn, patient_id: int, system_prompt: str, tools: list):
    messages = [{"role": "system", "content": system_prompt}]
    escalated = False

    while not escalated:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("exit", "quit", "bye"):
            break

        messages.append({"role": "user", "content": user_input})

        # Inner loop: keep calling the LLM until it returns a plain text response
        while True:
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content})
                print(f"\nAssistant: {msg.content}")
                break

            # Execute each tool call in this batch
            messages.append(msg)
            for tc in msg.tool_calls:
                fn = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                print(f"\n  [TOOL]   {fn}({json.dumps(fn_args)})")
                result = execute_tool(conn, fn, fn_args, patient_id)
                print(f"  [RESULT] {json.dumps(result)}")

                if fn == "escalate_to_human":
                    escalated = True

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })
            # Continue inner loop so LLM can respond to the tool results

    return escalated


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test the dental AI receptionist")
    parser.add_argument("--patient", metavar="ID|PHONE", help="Patient ID or E.164 phone")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set. Copy .env.example → .env and fill it in.")
        sys.exit(1)

    conn = get_conn()
    client = OpenAI(api_key=api_key)

    # ── Select patient ────────────────────────────────────────────────────────
    if args.patient:
        patient = find_patient(conn, args.patient)
        if not patient:
            print(f"No patient found for '{args.patient}'")
            sys.exit(1)
    else:
        patients = list_patients(conn)
        print("Seeded patients:")
        for p in patients:
            print(f"  [{p['id']}] {p['name']:<18} {p['phone']}")
        choice = input("\nSelect patient (ID or phone): ").strip()
        patient = find_patient(conn, choice)
        if not patient:
            print(f"Not found: {choice}")
            sys.exit(1)

    patient_id = patient["id"]
    upcoming = load_upcoming(conn, patient_id)
    patient_context = build_patient_context(patient_id, upcoming)

    # ── Build system prompt ───────────────────────────────────────────────────
    system_template = (PROMPTS_DIR / "system.txt").read_text()
    system_prompt = system_template.replace(
        "{patient_context}", json.dumps(patient_context)
    )
    tools = json.loads((PROMPTS_DIR / "tools.json").read_text())

    # ── Session header ────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"Simulating call from: {patient['name']} ({patient['phone']})")
    print(f"Patient context injected: {json.dumps(patient_context)}")
    print(f"{'─'*60}")
    print("Type your message. 'exit' or Ctrl-C to end.\n")

    escalated = run_conversation(client, conn, patient_id, system_prompt, tools)

    print(f"\n{'─'*60}")
    if escalated:
        print("Session ended: escalated to human staff.")
    else:
        print("Session ended.")
    print(f"{'─'*60}")

    conn.close()


if __name__ == "__main__":
    main()
