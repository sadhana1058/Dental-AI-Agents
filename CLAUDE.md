# Dental AI Receptionist — Project Guide

## Vision
AI voice/WhatsApp receptionist for dental practices: handles appointment reminders,
rescheduling, cancellations, and FAQs. Syncs with Google Calendar (source of truth
for practices without a PMS API). Designed to minimize PHI exposure to LLM context.

## Current Stack (dev phase)
- **Telephony**: Twilio (Programmable Voice + WhatsApp)
- **Voice pipeline**: Pipecat (based on `pipecat-examples/twilio-chatbot/inbound`)
- **STT**: Deepgram (free tier credit during dev)
- **LLM**: OpenAI (gpt-4o-mini for live conversation, gpt-4o for post-call extraction)
  - NOTE: Anthropic Claude was the original target for the LLM layer (cheaper +
    faster Haiku tier, prompt caching). We currently only have an OPENAI_API_KEY.
    Build the LLM service behind a thin abstraction so swapping to
    `AnthropicLLMService` later is a one-line change in the pipeline config.
- **TTS**: Cartesia or ElevenLabs (free/dev tier)
- **DB**: Postgres (or SQLite for local dev)
- **Calendar**: Google Calendar API (OAuth, two-way sync)

## LLM Provider Abstraction (IMPORTANT)
- All LLM calls go through Pipecat's LLM service interface
  (`OpenAILLMService` for now, swap to `AnthropicLLMService` later)
- Tool/function definitions must be written in a provider-agnostic schema
  (JSON schema works for both OpenAI function calling and Anthropic tool use)
- System prompt and tool definitions live in `prompts/` as plain text/JSON,
  NOT hardcoded into provider-specific request bodies
- Config flag (env var `LLM_PROVIDER=openai|anthropic`) selects provider at startup

## Core Design Principles
1. **PHI minimization**: Never pass full patient name/DOB/insurance into LLM
   context. Use `patient_id` tokens; resolve to real data only at the DB layer.
2. **Tool-based actions**: All state changes (reschedule, cancel) go through
   defined tools/functions, never inferred from free text directly.
3. **Escalation path**: Low-confidence intent or out-of-scope requests →
   "let me connect you with our staff" + flag in call_logs for human follow-up.
4. **Append-only audit log**: `appointment_changes` table, never UPDATE in place
   — current state = latest row per appointment_id.

## Database Schema (MVP)
```sql
patients (id, name, phone, email, dob, notes)
appointments (id, patient_id, provider, start_time, duration, type, status, calendar_event_id)
appointment_changes (id, appointment_id, changed_at, change_type, old_value, new_value)
practice_settings (hours, appointment_types, providers, buffer_rules)
call_logs (id, patient_id, channel, transcript, outcome, escalated, timestamp)
```

## Tools/Functions (provider-agnostic schema)
- `check_availability(date, provider?)` → returns open slots
- `get_appointment(patient_id)` → returns current appointment(s)
- `reschedule_appointment(appointment_id, new_time)` → updates DB + Google Calendar,
   writes to appointment_changes
- `cancel_appointment(appointment_id)` → same pattern
- `escalate_to_human(reason)` → flags call_logs, ends conversation gracefully

## Channels
- **WhatsApp**: Twilio webhook → same Claude/OpenAI tool-calling logic as voice
- **Voice**: Pipecat pipeline (Twilio Media Streams → Deepgram STT → LLM → TTS → Twilio)
  - Both channels share the same `handle_message(patient_context, user_input)` core function

## Dev Workflow
1. Test conversation logic via text/API console BEFORE wiring voice (cheap iteration)
2. Use Pipecat's `twilio-chatbot/inbound` example as the starting scaffold
3. Test voice locally via ngrok + Twilio number
4. Calendar sync: implement `reschedule_appointment` to also create/update
   Google Calendar event via OAuth

## What's Explicitly Out of Scope for MVP
- HIPAA/BAA compliance infrastructure (note in README, don't implement — no real PHI in dev)
- Multi-tenant / multi-practice support
- PMS integrations beyond Google Calendar
- Outbound reminder calls (inbound + WhatsApp first)

## Cost Notes
- gpt-4o-mini for live turns, gpt-4o only for structured post-call extraction (JSON)
- Cache/reuse system prompt where the provider supports it
- Keep per-turn context small (~200-500 tokens system + patient context)

## Migration Path (OpenAI → Anthropic)
When ANTHROPIC_API_KEY becomes available:
1. Set `LLM_PROVIDER=anthropic` in env
2. Swap `OpenAILLMService` → `AnthropicLLMService` in pipeline config
3. Verify tool schema compatibility (minor field name differences between
   OpenAI function calling and Anthropic tool use — adjust adapter layer)
4. Switch live-conversation model to Claude Haiku, extraction to Sonnet
5. Enable prompt caching on system prompt (`cache_control`)
