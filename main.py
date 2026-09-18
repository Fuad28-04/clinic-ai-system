import os
import time
import httpx
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, BackgroundTasks
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client
from google import genai
from google.genai import types

# loading secret keys from .env file
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# whatsapp cloud api credentials
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# the approved template we use to reach patients outside the 24h window
FOLLOW_UP_TEMPLATE_NAME = "follow_up_reminder"
FOLLOW_UP_TEMPLATE_LANG = "bn"

# a shared secret so only our scheduler can trigger the daily reminder run
CRON_SECRET = os.getenv("CRON_SECRET", "change-me")

# setting up Gemini AI (new SDK, old google.generativeai package is deprecated now)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL_NAME = "gemini-3.6-flash"

# connecting to Supabase database
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# creating the FastAPI app
app = FastAPI()


@app.get("/")
def home():
    """just to check if the server is running or not"""
    return {"message": "Clinic AI Backend is running!"}


PRIVACY_POLICY_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy - Clinic AI Assistant</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto;
         padding: 0 20px; line-height: 1.7; color: #222; }
  h1 { border-bottom: 2px solid #eee; padding-bottom: 10px; }
  h2 { margin-top: 32px; color: #333; }
</style>
</head>
<body>
<h1>Privacy Policy</h1>
<p><strong>Service:</strong> Clinic AI Assistant<br>
<strong>Last updated:</strong> September 2026</p>

<h2>1. About this service</h2>
<p>Clinic AI Assistant is an automated appointment booking assistant that clinics use to
communicate with their patients over WhatsApp. It helps patients check doctor schedules,
book appointments, view their existing appointments, and cancel appointments.</p>

<h2>2. Information we collect</h2>
<p>When you message the clinic through this service, we collect and store:</p>
<ul>
  <li>Your WhatsApp phone number</li>
  <li>Your name, as you provide it</li>
  <li>The reason for your visit, as you describe it</li>
  <li>Your appointment details (doctor, date, time, status)</li>
  <li>The messages exchanged in your conversation with the assistant</li>
</ul>

<h2>3. How we use your information</h2>
<p>Your information is used only to book and manage your appointments, to remember the
context of your conversation so you do not have to repeat yourself, and to share relevant
details with the doctor you are booking with.</p>

<h2>4. How your information is stored</h2>
<p>Data is stored in a secured cloud database. Message content is processed by Google's
Gemini AI to generate replies. We do not sell your data or use it for advertising.</p>

<h2>5. Who can see your information</h2>
<p>Your information is accessible to the clinic staff and the doctor treating you.
It is not shared with any other third party, except the technical service providers
required to operate this service (cloud hosting, database, AI processing, and WhatsApp).</p>

<h2>6. Data retention and deletion</h2>
<p>Your data is kept while you remain a patient of the clinic. You may request deletion
of your data at any time by contacting the clinic or emailing the address below.
We will delete your records within a reasonable period after such a request.</p>

<h2>7. Medical disclaimer</h2>
<p>This assistant helps with appointment scheduling only. It does not provide medical
advice, diagnosis, or treatment. For medical emergencies, contact emergency services
or visit a hospital immediately.</p>

<h2>8. Contact</h2>
<p>For any question about this policy or your data, contact:
<strong>qutibidiboq55@gmail.com</strong></p>
</body>
</html>
"""


@app.get("/privacy")
def privacy_policy():
    """privacy policy page - meta requires a public privacy policy url to publish the app"""
    return Response(content=PRIVACY_POLICY_HTML, media_type="text/html")


@app.get("/test-database")
def test_database():
    """testing if supabase connection is working properly"""
    try:
        result = supabase.table("doctors").select("*").execute()
        return {
            "status": "success",
            "message": "Database connection is working",
            "doctors": result.data
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/test-ai")
def test_ai():
    """testing if gemini ai is responding properly"""
    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents="Are you working properly? Reply in one short line."
        )
        return {
            "status": "success",
            "message": "Gemini AI connection is working",
            "ai_response": response.text
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================================
# TOOL FUNCTIONS - these are the "actions" the AI can take
# the AI itself decides when to call these based on the conversation
# Gemini reads the docstring + type hints to understand what each tool does
# ==========================================================

def get_all_doctors() -> list:
    """Get the list of all active doctors in the clinic, including their name, specialty, and fee.
    Use this when the patient asks which doctors are available or wants to know about specialties.
    """
    result = supabase.table("doctors").select("*").eq("is_active", True).execute()
    return result.data


def check_doctor_schedule(doctor_name: str) -> dict:
    """Get the schedule (days, start time, end time, fee) for one specific doctor by name.
    Use this when the patient asks about a specific doctor's availability or timing.

    Args:
        doctor_name: the name of the doctor, e.g. "ডা. রহমান" or "Rahman"
    """
    result = supabase.table("doctors").select("*").ilike("name", f"%{doctor_name}%").execute()
    if not result.data:
        return {"found": False, "message": "No doctor found with that name"}
    return {"found": True, "doctor": result.data[0]}


def book_appointment(patient_name: str, patient_phone: str, doctor_name: str,
                      appointment_date: str, appointment_time: str, reason: str) -> dict:
    """Book an appointment for a patient with a specific doctor.
    Only call this after you have collected ALL required details from the patient:
    patient's name, phone number, which doctor, preferred date, preferred time, and reason for visit.

    Args:
        patient_name: full name of the patient
        patient_phone: phone number of the patient
        doctor_name: name of the doctor to book with
        appointment_date: date in YYYY-MM-DD format
        appointment_time: time in HH:MM 24-hour format
        reason: short reason for the visit, e.g. "fever", "checkup"
    """
    # find the doctor first
    doctor_result = supabase.table("doctors").select("*").ilike("name", f"%{doctor_name}%").execute()
    if not doctor_result.data:
        return {"success": False, "message": f"Doctor '{doctor_name}' not found"}
    doctor = doctor_result.data[0]

    # find or create the patient record
    patient_result = supabase.table("patients").select("*").eq("phone", patient_phone).execute()
    if patient_result.data:
        patient_id = patient_result.data[0]["id"]
    else:
        new_patient = supabase.table("patients").insert({
            "name": patient_name,
            "phone": patient_phone
        }).execute()
        patient_id = new_patient.data[0]["id"]

    # work out the serial number: count how many are already booked
    # for this doctor on this date, then this patient is the next one
    existing = (
        supabase.table("appointments")
        .select("id")
        .eq("doctor_id", doctor["id"])
        .eq("appointment_date", appointment_date)
        .eq("status", "booked")
        .execute()
    )
    serial_number = len(existing.data) + 1

    # create the appointment
    new_appointment = supabase.table("appointments").insert({
        "patient_id": patient_id,
        "doctor_id": doctor["id"],
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "serial_number": serial_number,
        "reason": reason,
        "status": "booked"
    }).execute()

    return {
        "success": True,
        "message": "Appointment booked successfully",
        "serial_number": serial_number,
        "appointment": new_appointment.data[0]
    }


def get_patient_appointments(patient_phone: str) -> dict:
    """Get all upcoming (status='booked') appointments for a patient using their phone number.
    Use this when the patient asks to see, check, or confirm their existing appointments.

    Args:
        patient_phone: the patient's phone number
    """
    patient_result = supabase.table("patients").select("*").eq("phone", patient_phone).execute()
    if not patient_result.data:
        return {"found": False, "message": "No patient found with this phone number"}

    patient_id = patient_result.data[0]["id"]
    appointments_result = (
        supabase.table("appointments")
        .select("*, doctors(name, specialty)")
        .eq("patient_id", patient_id)
        .eq("status", "booked")
        .execute()
    )
    return {"found": True, "appointments": appointments_result.data}


def cancel_appointment(patient_phone: str, appointment_date: str, appointment_time: str) -> dict:
    """Cancel a specific booked appointment for a patient.
    Use this only after confirming with the patient which exact appointment they want to cancel
    (use get_patient_appointments first if you're not sure which one they mean).

    Args:
        patient_phone: the patient's phone number
        appointment_date: date of the appointment to cancel, in YYYY-MM-DD format
        appointment_time: time of the appointment to cancel, in HH:MM 24-hour format
    """
    patient_result = supabase.table("patients").select("*").eq("phone", patient_phone).execute()
    if not patient_result.data:
        return {"success": False, "message": "No patient found with this phone number"}

    patient_id = patient_result.data[0]["id"]

    # find the matching booked appointment
    match_result = (
        supabase.table("appointments")
        .select("*")
        .eq("patient_id", patient_id)
        .eq("appointment_date", appointment_date)
        .eq("appointment_time", appointment_time)
        .eq("status", "booked")
        .execute()
    )
    if not match_result.data:
        return {"success": False, "message": "No matching booked appointment found"}

    appointment_id = match_result.data[0]["id"]
    supabase.table("appointments").update({"status": "cancelled"}).eq("id", appointment_id).execute()

    return {"success": True, "message": "Appointment cancelled successfully"}


def check_queue_status(patient_phone: str) -> dict:
    """Check the live queue status for a patient who has an appointment today.
    Tells them which serial number the doctor is currently seeing, their own serial number,
    and roughly how long they still have to wait.
    Use this when the patient asks things like "how long will it take", "what's my turn",
    "koto number cholche", "amar serial koto", or anything about waiting time.

    Args:
        patient_phone: the patient's phone number
    """
    today = datetime.now().strftime("%Y-%m-%d")

    patient_result = supabase.table("patients").select("id").eq("phone", patient_phone).execute()
    if not patient_result.data:
        return {"found": False, "message": "No patient found with this phone number"}
    patient_id = patient_result.data[0]["id"]

    # find their appointment for today
    appt_result = (
        supabase.table("appointments")
        .select("*, doctors(name, avg_consultation_minutes)")
        .eq("patient_id", patient_id)
        .eq("appointment_date", today)
        .eq("status", "booked")
        .execute()
    )
    if not appt_result.data:
        return {"found": False, "message": "This patient has no booked appointment for today"}

    appointment = appt_result.data[0]
    doctor = appointment["doctors"]
    my_serial = appointment.get("serial_number")

    # look up the live queue state for this doctor today
    queue_result = (
        supabase.table("doctor_queue_state")
        .select("*")
        .eq("doctor_id", appointment["doctor_id"])
        .eq("queue_date", today)
        .execute()
    )

    if not queue_result.data or queue_result.data[0]["current_serial"] == 0:
        return {
            "found": True,
            "doctor_name": doctor["name"],
            "my_serial": my_serial,
            "chamber_started": False,
            "message": "The doctor has not started seeing patients yet today",
        }

    current_serial = queue_result.data[0]["current_serial"]
    avg_minutes = doctor.get("avg_consultation_minutes") or 10
    people_ahead = max(0, my_serial - current_serial)
    estimated_wait = people_ahead * avg_minutes

    return {
        "found": True,
        "doctor_name": doctor["name"],
        "chamber_started": True,
        "current_serial": current_serial,
        "my_serial": my_serial,
        "people_ahead": people_ahead,
        "estimated_wait_minutes": estimated_wait,
        "is_my_turn": people_ahead == 0,
    }


# list of tools the AI is allowed to use
CLINIC_TOOLS = [
    get_all_doctors,
    check_doctor_schedule,
    book_appointment,
    get_patient_appointments,
    cancel_appointment,
    check_queue_status,
]


# this defines the shape of the data the /chat endpoint expects
# session_id identifies WHICH conversation this message belongs to
# (later, this will be the patient's phone number when we connect WhatsApp)
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# system prompt now tells the AI it has real tools to use, and not to make up info
CLINIC_SYSTEM_PROMPT = f"""
You are a helpful AI receptionist for a small clinic in Bangladesh.
Patients will message you in Bangla, English, or mixed (Banglish).
Today's date is {datetime.now().strftime('%Y-%m-%d')}.

IMPORTANT RULES:
- ALWAYS reply in the same language the patient wrote to you in. If they write in Bangla,
  reply in Bangla. If English, reply in English. If Banglish (Bangla in Latin letters),
  reply in Banglish. Same for any other language - Hindi, Arabic, Spanish, anything.
  Never switch languages on your own; follow the patient's lead every single message.
- NEVER make up doctor schedules, fees, or availability. Always use the tools to get real data.
- To book an appointment, you MUST collect: patient name, phone number, doctor name,
  preferred date, preferred time, and reason for visit. Ask for anything missing before booking.
  Remember what the patient already told you earlier in this conversation, don't ask again.
- If the patient wants to check their existing appointments, ask for their phone number
  (if not already known) and use get_patient_appointments.
- If the patient wants to cancel an appointment, first check their appointments if you don't
  already know which one they mean, confirm the exact appointment with them, then cancel it.
- If the patient asks about waiting time, their turn, or which serial is running now,
  use check_queue_status. Tell them the current serial, their serial, and the estimated wait
  so they can leave home at the right time.
- When you book an appointment, always tell the patient their serial number.
- Keep replies short, warm, and clear.
- Confirm appointment details back to the patient after successful booking or cancellation.
"""

# ==========================================================
# CONVERSATION MEMORY (database backed)
# every message is saved in supabase, so the conversation survives
# server restarts / sleeps. we load the recent history each time
# and rebuild the chat session from it.
# ==========================================================

# how many past messages to load. keeping this limited so we don't
# send a huge conversation to the AI every single time (costs tokens + slow)
HISTORY_LIMIT = 30


def load_conversation_history(session_id: str) -> list:
    """loads recent messages for this patient from the database,
    formatted the way gemini expects them
    """
    try:
        result = (
            supabase.table("conversation_messages")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(HISTORY_LIMIT)
            .execute()
        )
        # we fetched newest-first (so the limit keeps the RECENT ones),
        # but gemini needs oldest-first, so flip it back
        rows = list(reversed(result.data))

        history = []
        for row in rows:
            history.append(
                types.Content(
                    role=row["role"],
                    parts=[types.Part(text=row["content"])]
                )
            )
        return history
    except Exception as e:
        print(f"[History load ERROR] {e}")
        return []


def save_message(session_id: str, role: str, content: str):
    """saves one message (patient's or AI's) to the database"""
    try:
        supabase.table("conversation_messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content,
        }).execute()
    except Exception as e:
        print(f"[History save ERROR] {e}")


# google's servers get overloaded from time to time and return 503, and the free
# tier hands out 429s. both clear on their own, so a couple of short retries
# turn what would be a dropped patient message into a slightly slower reply.
AI_RETRY_WAITS = [2, 5]


def ask_ai(session_id: str, patient_message: str) -> str:
    """the main brain call.
    loads history -> asks gemini -> saves both messages -> returns the reply
    """
    history = load_conversation_history(session_id)

    last_error = None
    for attempt in range(len(AI_RETRY_WAITS) + 1):
        try:
            chat_session = gemini_client.chats.create(
                model=GEMINI_MODEL_NAME,
                history=history,
                config=types.GenerateContentConfig(
                    tools=CLINIC_TOOLS,
                    system_instruction=CLINIC_SYSTEM_PROMPT
                )
            )
            response = chat_session.send_message(patient_message)
            reply_text = response.text

            # save both sides of the exchange
            save_message(session_id, "user", patient_message)
            save_message(session_id, "model", reply_text)
            return reply_text

        except Exception as e:
            last_error = e
            text = str(e)
            # only worth retrying when the service is busy, not for bad requests
            retryable = "503" in text or "429" in text or "UNAVAILABLE" in text
            if not retryable or attempt >= len(AI_RETRY_WAITS):
                break
            wait = AI_RETRY_WAITS[attempt]
            print(f"[AI retry] attempt {attempt + 1} failed, waiting {wait}s: {text[:120]}")
            time.sleep(wait)

    raise last_error


@app.post("/chat")
def chat(request: ChatRequest):
    """chat endpoint - memory now lives in the database, not RAM"""
    try:
        reply = ask_ai(request.session_id, request.message)
        return {
            "status": "success",
            "reply": reply
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/reset-chat")
def reset_chat(request: ChatRequest):
    """wipes the conversation history for a session - useful for testing"""
    try:
        supabase.table("conversation_messages").delete().eq(
            "session_id", request.session_id
        ).execute()
        return {"status": "success", "message": f"History for '{request.session_id}' cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================================
# WHATSAPP INTEGRATION
# two endpoints needed:
#   GET  /webhook  -> meta calls this once to verify our url is real
#   POST /webhook  -> meta sends us every incoming whatsapp message here
# ==========================================================

def send_whatsapp_message(to_phone_number: str, message_text: str):
    """sends a text message back to the patient through whatsapp cloud api"""
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {"body": message_text},
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=30)
        print(f"[WhatsApp send] status={response.status_code} body={response.text}")
        return response.json()
    except Exception as e:
        print(f"[WhatsApp send ERROR] {e}")
        return None


def build_unsupported_message(session_id: str) -> str:
    """when someone sends a voice note / image / sticker, we can't read it.
    we still want to reply in THEIR language, but a voice note gives us no text
    to detect language from - so we look at what they wrote earlier instead.
    if they've never written anything, we fall back to a bilingual message.
    """
    try:
        result = (
            supabase.table("conversation_messages")
            .select("content")
            .eq("session_id", session_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(3)
            .execute()
        )
    except Exception:
        result = None

    # never written to us before -> cover the two most likely languages
    if not result or not result.data:
        return ("দুঃখিত, এখন শুধু টেক্সট মেসেজ বুঝতে পারি। অনুগ্রহ করে লিখে জানান।\n\n"
                "Sorry, I can only read text messages right now. Please type your message.")

    past_text = "\n".join(row["content"] for row in result.data)

    prompt = f"""Here are the most recent messages a person sent to a clinic assistant:

{past_text}

Write a single short, polite sentence telling them that the assistant can only read
text messages at the moment, and asking them to type their message instead.

Write it in the SAME language and script they used above. Output only that sentence,
nothing else."""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"[Unsupported msg ERROR] {e}")
        return ("দুঃখিত, এখন শুধু টেক্সট মেসেজ বুঝতে পারি।\n"
                "Sorry, I can only read text messages right now.")


@app.get("/webhook")
def verify_webhook(request: Request):
    """meta hits this once when we set up the webhook, to check we own this server.
    we just echo back the challenge if the verify token matches ours.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print("[Webhook] verified successfully")
        return Response(content=challenge, media_type="text/plain")

    print("[Webhook] verification failed")
    return Response(content="Verification failed", status_code=403)


def handle_patient_message(sender_phone: str, patient_text: str):
    """runs after we have already answered meta, so we can take our time.
    if the AI is unreachable even after retries, the patient still gets told
    something rather than being left staring at a silent chat.
    """
    try:
        reply_text = ask_ai(sender_phone, patient_text)
        send_whatsapp_message(sender_phone, reply_text)
    except Exception as e:
        print(f"[AI failed for {sender_phone}] {e}")
        send_whatsapp_message(
            sender_phone,
            "দুঃখিত, এই মুহূর্তে একটু সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার "
            "মেসেজ দিন।\n\n"
            "Sorry, something is not working right now. Please message again in a few minutes."
        )


@app.post("/webhook")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    """this is where every incoming whatsapp message lands.
    we pull out the sender + text, run it through the same AI brain we built,
    then send the reply back to them on whatsapp.
    """
    try:
        data = await request.json()
        print(f"[Webhook] incoming: {data}")

        # meta wraps the message in a deep nested structure, so we dig carefully
        entry = data.get("entry", [])
        if not entry:
            return {"status": "ok"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "ok"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        # if there are no messages, it's probably just a status update (delivered/read)
        # we ignore those
        if not messages:
            return {"status": "ok"}

        message = messages[0]
        sender_phone = message.get("from")          # patient's whatsapp number
        message_type = message.get("type")

        # for now we only handle plain text messages
        if message_type != "text":
            send_whatsapp_message(sender_phone, build_unsupported_message(sender_phone))
            return {"status": "ok"}

        patient_text = message["text"]["body"]
        print(f"[Webhook] {sender_phone} says: {patient_text}")

        # answer meta immediately and do the slow part afterwards. meta gives a
        # webhook only a few seconds before it assumes failure and retries, which
        # would otherwise make the patient receive the same reply twice.
        # the phone number doubles as the session id, so each patient keeps
        # their own conversation.
        background_tasks.add_task(handle_patient_message, sender_phone, patient_text)
        return {"status": "ok"}

    except Exception as e:
        print(f"[Webhook ERROR] {e}")
        # always return 200 to meta, otherwise they keep retrying the same message
        return {"status": "error", "message": str(e)}


# ==========================================================
# DOCTOR QUEUE INTERFACE
# a simple web page the doctor opens on their phone/computer.
# they press "Next Patient" after finishing with each patient,
# which moves the queue forward so waiting patients can see it.
# ==========================================================

def get_or_create_queue(doctor_id: int, queue_date: str) -> dict:
    """gets today's queue row for a doctor, creating it if it's not there yet"""
    result = (
        supabase.table("doctor_queue_state")
        .select("*")
        .eq("doctor_id", doctor_id)
        .eq("queue_date", queue_date)
        .execute()
    )
    if result.data:
        return result.data[0]

    created = supabase.table("doctor_queue_state").insert({
        "doctor_id": doctor_id,
        "queue_date": queue_date,
        "current_serial": 0,
    }).execute()
    return created.data[0]


@app.get("/doctor/queue/{doctor_id}")
def get_queue_info(doctor_id: int):
    """returns the current queue state + today's patient list for one doctor"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        queue = get_or_create_queue(doctor_id, today)

        doctor = supabase.table("doctors").select("name").eq("id", doctor_id).execute()
        doctor_name = doctor.data[0]["name"] if doctor.data else "Unknown"

        appointments = (
            supabase.table("appointments")
            .select("id, patient_id, serial_number, reason, status, follow_up_date, patients(name, phone)")
            .eq("doctor_id", doctor_id)
            .eq("appointment_date", today)
            .eq("status", "booked")
            .order("serial_number")
            .execute()
        )

        return {
            "status": "success",
            "doctor_name": doctor_name,
            "date": today,
            "current_serial": queue["current_serial"],
            "total_patients": len(appointments.data),
            "patients": appointments.data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/doctor/next/{doctor_id}")
def next_patient(doctor_id: int):
    """doctor finished with the current patient - move to the next serial"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        queue = get_or_create_queue(doctor_id, today)
        new_serial = queue["current_serial"] + 1

        supabase.table("doctor_queue_state").update({
            "current_serial": new_serial,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", queue["id"]).execute()

        # mark the previous patient as completed, and note the start time of the new one
        if queue["current_serial"] > 0:
            supabase.table("appointments").update({
                "status": "completed",
                "finished_at": datetime.now().isoformat(),
            }).eq("doctor_id", doctor_id).eq("appointment_date", today).eq(
                "serial_number", queue["current_serial"]
            ).execute()

        supabase.table("appointments").update({
            "started_at": datetime.now().isoformat(),
        }).eq("doctor_id", doctor_id).eq("appointment_date", today).eq(
            "serial_number", new_serial
        ).execute()

        return {"status": "success", "current_serial": new_serial}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class FollowUpRequest(BaseModel):
    # how many days from today the patient should come back.
    # null means "no follow-up needed" and clears whatever was set before.
    days: int | None = None


@app.post("/doctor/follow-up/{doctor_id}")
def set_follow_up(doctor_id: int, request: FollowUpRequest):
    """the doctor sets a return date for the patient who is with them right now.
    done from the queue page, before pressing "call next patient".
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        queue = get_or_create_queue(doctor_id, today)
        current = queue["current_serial"]
        if current == 0:
            return {"status": "error", "message": "No patient is with the doctor yet"}

        follow_up_date = None
        if request.days is not None:
            if request.days < 1 or request.days > 730:
                return {"status": "error", "message": "Days must be between 1 and 730"}
            follow_up_date = (datetime.now() + timedelta(days=request.days)).strftime("%Y-%m-%d")

        updated = (
            supabase.table("appointments")
            .update({"follow_up_date": follow_up_date, "follow_up_sent": False})
            .eq("doctor_id", doctor_id)
            .eq("appointment_date", today)
            .eq("serial_number", current)
            .execute()
        )
        if not updated.data:
            return {"status": "error", "message": "Could not find that appointment"}

        return {
            "status": "success",
            "serial_number": current,
            "follow_up_date": follow_up_date,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/doctor/reset/{doctor_id}")
def reset_queue(doctor_id: int):
    """resets today's queue back to 0 - useful if something goes wrong"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        queue = get_or_create_queue(doctor_id, today)
        supabase.table("doctor_queue_state").update({
            "current_serial": 0,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", queue["id"]).execute()
        return {"status": "success", "current_serial": 0}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/doctor/patient-brief/{patient_id}")
def patient_brief(patient_id: int, lang: str = "bn"):
    """everything the doctor needs to know before calling this patient in:
    their basic info, past visits, and a short AI summary of what they told the assistant.
    """
    try:
        patient_result = supabase.table("patients").select("*").eq("id", patient_id).execute()
        if not patient_result.data:
            return {"status": "error", "message": "Patient not found"}
        patient = patient_result.data[0]

        # past visits (most recent first)
        history_result = (
            supabase.table("appointments")
            .select("appointment_date, appointment_time, reason, status, doctors(name)")
            .eq("patient_id", patient_id)
            .order("appointment_date", desc=True)
            .limit(10)
            .execute()
        )

        # what did they actually say to the assistant?
        messages_result = (
            supabase.table("conversation_messages")
            .select("role, content")
            .eq("session_id", patient["phone"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        recent_messages = list(reversed(messages_result.data))

        summary = generate_patient_summary(patient, recent_messages, lang)

        return {
            "status": "success",
            "patient": {
                "name": patient["name"],
                "phone": patient["phone"],
                "age": patient.get("age"),
                "gender": patient.get("gender"),
                "notes": patient.get("notes"),
            },
            "visit_history": history_result.data,
            "summary": summary,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def generate_patient_summary(patient: dict, messages: list, lang: str = "bn") -> str:
    """asks the AI to turn the patient's chat into a short brief for the doctor.
    lang follows whichever language the doctor has the interface set to.
    NOTE: this is context only - it is not a diagnosis and must never read like one.
    """
    if not messages:
        return ("এই রোগীর কোনো কথোপকথন পাওয়া যায়নি।" if lang == "bn"
                else "No conversation history available for this patient.")

    # flatten the conversation into plain text for the summariser
    transcript_lines = []
    for m in messages:
        speaker = "Patient" if m["role"] == "user" else "Assistant"
        transcript_lines.append(f"{speaker}: {m['content']}")
    transcript = "\n".join(transcript_lines)

    prompt = f"""You are preparing a short pre-consultation brief for a doctor in Bangladesh.

Below is a conversation between a patient and the clinic's booking assistant.

Patient name: {patient.get('name')}
Age: {patient.get('age') or 'not recorded'}

Conversation:
{transcript}

Write a brief of at most 4 short bullet points covering ONLY what the patient actually said:
their stated complaint, how long it has been going on (if mentioned), and anything else
they volunteered that the doctor should know before walking in.

Strict rules:
- Do NOT diagnose, do NOT suggest tests, do NOT suggest treatment.
- Do NOT invent any detail that is not in the conversation.
- If something was not mentioned, simply leave it out.
- Write in {"Bangla" if lang == "bn" else "English"}.
"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"[Summary ERROR] {e}")
        return "Summary could not be generated right now."


# ==========================================================
# FOLLOW-UP REMINDERS
# whatsapp only lets us message a patient freely for 24h after THEY write to us.
# a follow-up is weeks later, so we have to use an approved template instead.
# once the patient replies to the template, the normal AI chat takes over again.
# ==========================================================

def send_whatsapp_template(to_phone_number: str, patient_name: str, doctor_name: str):
    """sends the approved follow-up template to one patient"""
    url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "template",
        "template": {
            "name": FOLLOW_UP_TEMPLATE_NAME,
            "language": {"code": FOLLOW_UP_TEMPLATE_LANG},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": patient_name},
                    {"type": "text", "text": doctor_name},
                ],
            }],
        },
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=30)
        print(f"[Template send] to={to_phone_number} status={response.status_code} body={response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"[Template send ERROR] {e}")
        return False


@app.post("/tasks/send-follow-ups")
def send_follow_ups(request: Request):
    """runs once a day. finds everyone whose follow-up date is today and messages them.
    protected by a secret so nobody else can trigger it.
    """
    if request.headers.get("x-cron-secret") != CRON_SECRET:
        return Response(content="Not allowed", status_code=403)

    today = datetime.now().strftime("%Y-%m-%d")
    sent, failed, skipped = 0, 0, 0

    try:
        due = (
            supabase.table("appointments")
            .select("id, follow_up_date, patients(name, phone), doctors(name)")
            .eq("follow_up_date", today)
            .eq("follow_up_sent", False)
            .execute()
        )

        for row in due.data:
            patient = row.get("patients")
            doctor = row.get("doctors")

            # a patient with no phone on file can't be reached
            if not patient or not patient.get("phone"):
                skipped += 1
                continue

            ok = send_whatsapp_template(
                patient["phone"],
                patient.get("name") or "রোগী",
                (doctor or {}).get("name") or "ডাক্তার",
            )

            if ok:
                # mark it straight away so a retry never double-messages anyone
                supabase.table("appointments").update(
                    {"follow_up_sent": True}
                ).eq("id", row["id"]).execute()
                sent += 1
            else:
                failed += 1

        print(f"[Follow-ups] date={today} sent={sent} failed={failed} skipped={skipped}")
        return {
            "status": "success",
            "date": today,
            "due": len(due.data),
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }
    except Exception as e:
        print(f"[Follow-ups ERROR] {e}")
        return {"status": "error", "message": str(e)}


@app.get("/tasks/follow-ups-due")
def follow_ups_due():
    """read-only peek at who is due today - handy for checking before the job runs"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        due = (
            supabase.table("appointments")
            .select("follow_up_date, follow_up_sent, patients(name, phone), doctors(name)")
            .eq("follow_up_date", today)
            .execute()
        )
        return {"status": "success", "date": today, "count": len(due.data), "rows": due.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}


DOCTOR_PAGE_HTML = """
<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chamber queue</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --ink:      #16262B;
    --ink-soft: #5C6F74;
    --line:     #D6DEE0;
    --bg:       #E9EDEE;
    --surface:  #FFFFFF;
    --accent:   #0F6B5C;
    --accent-d: #0A5145;
    --spent:    #A8B4B8;
    --warn-bg:  #FBF6E9;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "Hind Siliguri", system-ui, "Segoe UI", sans-serif;
    font-size: 16px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  .shell { max-width: 460px; margin: 0 auto; padding: 18px 16px 40px; }

  /* ---------- doctor picker ---------- */
  .picker { margin-bottom: 18px; }
  .picker label { display: block; font-size: 13px; color: var(--ink-soft); margin-bottom: 5px; }
  select {
    width: 100%; padding: 11px 12px; font-size: 16px;
    font-family: inherit; color: var(--ink);
    background: var(--surface); border: 1px solid var(--line);
    border-radius: 8px;
  }

  /* ---------- follow-up for the patient in the room ---------- */
  .inroom {
    background: var(--surface); border-radius: 14px;
    padding: 18px 20px; margin-bottom: 14px;
  }
  .inroom .with { font-size: 14px; color: var(--ink-soft); margin-bottom: 3px; }
  .inroom .pname { font-size: 18px; font-weight: 600; margin-bottom: 14px; }
  .inroom .ask { font-size: 14px; color: var(--ink-soft); margin-bottom: 9px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    padding: 8px 13px; font-size: 14px; font-weight: 500;
    background: var(--bg); color: var(--ink);
    border: 1px solid transparent; border-radius: 20px;
  }
  .chip:active { background: #DDE4E5; }
  .chip.picked { background: var(--accent); color: #fff; }
  .chip.none.picked { background: var(--ink-soft); }
  .fu-note { font-size: 13px; color: var(--accent-d); margin-top: 11px; min-height: 19px; }
  .fu-custom { margin-top: 10px; display: flex; gap: 8px; align-items: center; }
  .fu-custom input {
    flex: 1; padding: 9px 10px; font-family: inherit; font-size: 15px;
    border: 1px solid var(--line); border-radius: 8px; color: var(--ink);
  }
  .fu-custom button {
    padding: 9px 14px; font-size: 14px; background: var(--bg); color: var(--ink);
  }

  /* ---------- the hero: who walks in next ---------- */
  .oncall {
    background: var(--surface); border-radius: 14px;
    padding: 22px 20px 20px; margin-bottom: 14px;
    border-top: 4px solid var(--accent);
  }
  .oncall .cue { font-size: 13px; color: var(--ink-soft); margin-bottom: 10px; }
  .oncall .who { display: flex; align-items: baseline; gap: 12px; }
  .oncall .num {
    font-size: 52px; font-weight: 700; line-height: 1;
    color: var(--accent); letter-spacing: -1px;
  }
  .oncall .name { font-size: 22px; font-weight: 600; }
  .oncall .why { color: var(--ink-soft); font-size: 15px; margin-top: 6px; min-height: 23px; }

  button {
    font-family: inherit; font-size: 16px; font-weight: 600;
    border: none; border-radius: 9px; cursor: pointer;
  }
  button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }

  .call {
    width: 100%; margin-top: 18px; padding: 15px;
    background: var(--accent); color: #fff;
  }
  .call:active { background: var(--accent-d); }
  .call:disabled { background: var(--spent); cursor: default; }

  /* ---------- running strip ---------- */
  .strip {
    display: flex; justify-content: space-between;
    background: var(--surface); border-radius: 10px;
    padding: 12px 16px; margin-bottom: 14px;
    font-size: 14px; color: var(--ink-soft);
  }
  .strip b { color: var(--ink); font-weight: 600; }
  .undo {
    background: none; color: var(--ink-soft); font-size: 13px;
    font-weight: 500; padding: 0; text-decoration: underline;
  }

  /* ---------- queue list ---------- */
  .list { background: var(--surface); border-radius: 12px; padding: 6px 4px 4px; }
  .list h2 { font-size: 14px; font-weight: 600; color: var(--ink-soft);
             margin: 12px 14px 8px; }
  .row {
    display: grid; grid-template-columns: 34px 1fr;
    gap: 10px; padding: 11px 14px; align-items: baseline;
    border-top: 1px solid var(--line); cursor: pointer;
  }
  .row:first-of-type { border-top: none; }
  .row:hover, .row:focus-visible { background: #F3F7F7; outline: none; }
  .row .s { font-weight: 600; color: var(--ink-soft); }
  .row .n { font-weight: 500; }
  .row .r { font-size: 14px; color: var(--ink-soft); }
  .row.current { background: #EAF4F1; }
  .row.current .s, .row.current .n { color: var(--accent-d); }
  .row.seen { color: var(--spent); }
  .row.seen .s, .row.seen .n, .row.seen .r { color: var(--spent); }
  .empty { padding: 18px 14px; color: var(--ink-soft); font-size: 15px; }

  /* ---------- patient brief ---------- */
  .scrim {
    position: fixed; inset: 0; background: rgba(12,28,32,.5);
    display: none; align-items: flex-end; justify-content: center; z-index: 20;
  }
  .scrim.open { display: flex; }
  .brief {
    background: var(--surface); width: 100%; max-width: 460px;
    max-height: 86vh; overflow-y: auto;
    border-radius: 16px 16px 0 0; padding: 24px 20px 20px;
  }
  .brief h3 { margin: 0; font-size: 21px; font-weight: 600; }
  .brief .id { color: var(--ink-soft); font-size: 14px; margin-bottom: 20px; }
  .brief h4 { font-size: 14px; font-weight: 600; color: var(--ink-soft);
              margin: 22px 0 8px; }
  .said {
    background: #F3F7F7; border-left: 3px solid var(--accent);
    border-radius: 0 8px 8px 0; padding: 14px 16px;
    font-size: 15px; line-height: 1.7; white-space: pre-wrap;
  }
  .caveat { color: var(--ink-soft); font-size: 12px; margin-top: 8px; line-height: 1.5; }
  .onfile {
    background: var(--warn-bg); border-left: 3px solid #C9A227;
    border-radius: 0 8px 8px 0; padding: 14px 16px;
    font-size: 15px; line-height: 1.7; white-space: pre-wrap;
  }
  .visit { padding: 10px 0; border-top: 1px solid var(--line); font-size: 15px; }
  .visit:first-of-type { border-top: none; }
  .visit .d { font-weight: 500; }
  .visit .x { color: var(--ink-soft); font-size: 14px; }
  .shut { width: 100%; margin-top: 20px; padding: 13px;
          background: var(--bg); color: var(--ink); }
  .hintbox { display: none; }

  /* ---------- language toggle ---------- */
  .topbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
  .langs { display: inline-flex; background: var(--surface);
           border-radius: 20px; padding: 3px; }
  .langs button {
    padding: 6px 14px; font-size: 14px; font-weight: 500;
    background: none; color: var(--ink-soft); border-radius: 17px;
  }
  .langs button.on { background: var(--accent); color: #fff; }

  /* ---------- desktop: brief lives beside the queue ---------- */
  @media (min-width: 900px) {
    .shell {
      max-width: 1040px; display: grid; gap: 22px;
      grid-template-columns: 420px 1fr;
      grid-template-areas: "top top" "pick brief" "room brief" "call brief" "strip brief" "list brief";
      align-content: start; padding-top: 28px;
    }
    .topbar { grid-area: top; margin-bottom: 0; }
    .picker { grid-area: pick; margin-bottom: 0; }
    .inroom { grid-area: room; margin-bottom: 0; }
    .oncall { grid-area: call; margin-bottom: 0; }
    .strip  { grid-area: strip; margin-bottom: 0; }
    .list   { grid-area: list; }

    /* the mobile rule .scrim.open{display:flex} has higher specificity than a
       plain .scrim, so it has to be overridden by name here - otherwise
       align-items:flex-end shoves the panel to the bottom of a tall column
       and it ends up below the fold. */
    .scrim, .scrim.open {
      grid-area: brief; position: static; display: block;
      background: none; z-index: auto;
    }
    .brief {
      max-width: none; border-radius: 14px; max-height: none;
      padding: 26px 24px; position: sticky; top: 28px;
    }
    .scrim:not(.open) .brief { display: none; }
    .scrim:not(.open) .hintbox {
      display: block; color: var(--ink-soft); font-size: 15px;
      padding: 26px 24px; background: var(--surface); border-radius: 14px;
    }
    .shut { display: none; }
  }

  @media (prefers-reduced-motion: no-preference) {
    .row, .call { transition: background .12s ease; }
  }
</style>
</head>
<body>

<div class="shell">

  <div class="topbar">
    <div class="langs">
      <button id="langBn" onclick="setLang('bn')">বাংলা</button>
      <button id="langEn" onclick="setLang('en')">English</button>
    </div>
  </div>

  <div class="picker">
    <label for="doc" id="lblChamber"></label>
    <select id="doc" onchange="loadQueue()"></select>
  </div>

  <section class="inroom" id="inroom" style="display:none;">
    <div class="with" id="lblWith"></div>
    <div class="pname" id="inroomName"></div>
    <div class="ask" id="lblComeBack"></div>
    <div class="chips" id="fuChips">
      <button class="chip none" data-days="" onclick="setFollowUp(null, this)" id="fu0"></button>
      <button class="chip" data-days="7" onclick="setFollowUp(7, this)" id="fu7"></button>
      <button class="chip" data-days="15" onclick="setFollowUp(15, this)" id="fu15"></button>
      <button class="chip" data-days="30" onclick="setFollowUp(30, this)" id="fu30"></button>
      <button class="chip" data-days="90" onclick="setFollowUp(90, this)" id="fu90"></button>
    </div>
    <div class="fu-custom">
      <input id="fuDays" type="number" min="1" max="730">
      <button onclick="setCustomFollowUp()" id="lblSet"></button>
    </div>
    <div class="fu-note" id="fuNote"></div>
  </section>

  <section class="oncall">
    <div class="cue" id="cue"></div>
    <div class="who">
      <div class="num" id="nextNum">&mdash;</div>
      <div class="name" id="nextName"></div>
    </div>
    <div class="why" id="nextWhy"></div>
    <button class="call" id="callBtn" onclick="callNext()"></button>
  </section>

  <div class="strip">
    <span><span id="lblNowWith"></span> <b id="nowNum"></b></span>
    <span><b id="leftNum">0</b> <span id="lblWaiting"></span></span>
  </div>

  <div class="list">
    <h2><span id="lblTodayList"></span>
        <button class="undo" onclick="resetQueue()" id="lblStartOver"></button></h2>
    <div id="rows"></div>
  </div>

  <!-- kept INSIDE .shell so it can sit in the grid's right-hand column on
       desktop. on phones it is position:fixed, so nesting makes no difference
       there. -->
  <div class="scrim" id="scrim" onclick="shutBrief(event)">
    <div class="hintbox" id="hintbox"></div>
    <div class="brief" onclick="event.stopPropagation()">
      <h3 id="bName">&nbsp;</h3>
      <div class="id" id="bId"></div>

      <div id="bNotesWrap" style="display:none;">
        <h4 id="lblOnFile"></h4>
        <div class="onfile" id="bNotes"></div>
      </div>

      <h4 id="lblTold"></h4>
      <div class="said" id="bSaid"></div>
      <p class="caveat" id="lblCaveat"></p>

      <h4 id="lblEarlier"></h4>
      <div id="bVisits"></div>

      <button class="shut" onclick="shutBrief()" id="lblClose"></button>
    </div>
  </div>

</div>

<script>
// ---------------------------------------------------------------
// every visible string lives here, in both languages.
// the doctor's choice is remembered in localStorage.
// ---------------------------------------------------------------
const STRINGS = {
  bn: {
    chamber: 'চেম্বার',
    withYou: 'এখন আপনার কাছে',
    comeBack: 'পরবর্তী সাক্ষাৎ',
    fuNone: 'লাগবে না',
    fu7: '১ সপ্তাহ',
    fu15: '১৫ দিন',
    fu30: '১ মাস',
    fu90: '৩ মাস',
    daysPlaceholder: 'অথবা দিন লিখুন',
    set: 'সেট',
    firstUp: 'প্রথম রোগী',
    nextIn: 'পরবর্তী রোগী',
    nobodyWaiting: 'কেউ অপেক্ষায় নেই',
    allSeen: 'সবাইকে দেখা হয়ে গেছে',
    nobodyToday: 'আজ কোনো রোগী নেই',
    callNext: 'পরবর্তী রোগীকে ডাকুন',
    listFinished: 'তালিকা শেষ',
    nobodyToCall: 'ডাকার মতো কেউ নেই',
    nowWith: 'এখন দেখছেন:',
    noneYet: 'এখনো শুরু হয়নি',
    stillWaiting: 'জন অপেক্ষায়',
    todayList: 'আজকের তালিকা',
    startOver: 'শুরু থেকে',
    noAppointments: 'আজ কোনো অ্যাপয়েন্টমেন্ট নেই।',
    pickPatient: 'রোগীর তথ্য দেখতে নাম নির্বাচন করুন',
    onFile: 'রেকর্ডে যা আছে',
    told: 'রোগী সহকারীকে যা বলেছেন',
    caveat: 'রোগীর নিজের কথা থেকে তৈরি। শুধু প্রেক্ষাপট, কোনো রোগ নির্ণয় নয়।',
    earlier: 'আগের সাক্ষাৎ',
    close: 'বন্ধ করুন',
    loading: 'লোড হচ্ছে',
    reading: 'বার্তা পড়া হচ্ছে',
    couldNotLoad: 'লোড করা যায়নি',
    briefFailed: 'এই রোগীর তথ্য খোলা গেল না। একটু পরে আবার চেষ্টা করুন।',
    noEarlier: 'আগের কোনো সাক্ষাতের রেকর্ড নেই।',
    reasonMissing: 'কারণ লেখা নেই',
    withDoctor: 'ডাক্তার:',
    unnamed: 'নাম নেই',
    returnSet: 'পরবর্তী সাক্ষাৎ:',
    noReturn: 'পরবর্তী সাক্ষাৎ লাগবে না',
    badDays: '১ থেকে ৭৩০ এর মধ্যে দিন সংখ্যা লিখুন।',
    confirmReset: 'তালিকা কি শুরু থেকে সেট করবেন?',
    age: 'বয়স',
  },
  en: {
    chamber: 'Chamber',
    withYou: 'With you now',
    comeBack: 'Come back after',
    fuNone: 'Not needed',
    fu7: '1 week',
    fu15: '15 days',
    fu30: '1 month',
    fu90: '3 months',
    daysPlaceholder: 'or type days',
    set: 'Set',
    firstUp: 'First up',
    nextIn: 'Next in',
    nobodyWaiting: 'Nobody waiting',
    allSeen: 'Everyone has been seen',
    nobodyToday: 'Nobody booked today',
    callNext: 'Call next patient',
    listFinished: 'List finished',
    nobodyToCall: 'Nobody to call',
    nowWith: 'Now with you:',
    noneYet: 'none yet',
    stillWaiting: 'still waiting',
    todayList: "Today's list",
    startOver: 'start over',
    noAppointments: 'No appointments booked for today.',
    pickPatient: 'Pick a patient to read their notes',
    onFile: 'On file',
    told: 'What they told the assistant',
    caveat: "Written from the patient's own words. Background only, not a clinical opinion.",
    earlier: 'Earlier visits',
    close: 'Close',
    loading: 'Loading',
    reading: 'Reading their messages',
    couldNotLoad: 'Could not load',
    briefFailed: "This patient's notes could not be opened. Try again in a moment.",
    noEarlier: 'No earlier visits on record.',
    reasonMissing: 'reason not recorded',
    withDoctor: 'with',
    unnamed: 'Unnamed',
    returnSet: 'Return visit set for',
    noReturn: 'No return visit needed',
    badDays: 'Enter a number of days between 1 and 730.',
    confirmReset: 'Set the list back to the beginning?',
    age: 'age',
  }
};

let lang = 'bn';
let t = STRINGS.bn;
let docId = null;
let running = 0;
let queue = [];
let openPatientId = null;

function setLang(next) {
  lang = next;
  t = STRINGS[next];
  try { localStorage.setItem('clinicLang', next); } catch (e) {}

  document.getElementById('langBn').classList.toggle('on', next === 'bn');
  document.getElementById('langEn').classList.toggle('on', next === 'en');
  document.documentElement.lang = next;

  applyStaticLabels();
  if (docId) loadQueue();
  // a brief already on screen was written in the old language, so refetch it
  if (openPatientId) openBrief(openPatientId);
}

function applyStaticLabels() {
  const put = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  put('lblChamber', t.chamber);
  put('lblWith', t.withYou);
  put('lblComeBack', t.comeBack);
  put('fu0', t.fuNone);
  put('fu7', t.fu7);
  put('fu15', t.fu15);
  put('fu30', t.fu30);
  put('fu90', t.fu90);
  put('lblSet', t.set);
  put('lblNowWith', t.nowWith);
  put('lblWaiting', t.stillWaiting);
  put('lblTodayList', t.todayList);
  put('lblStartOver', t.startOver);
  put('hintbox', t.pickPatient);
  put('lblOnFile', t.onFile);
  put('lblTold', t.told);
  put('lblCaveat', t.caveat);
  put('lblEarlier', t.earlier);
  put('lblClose', t.close);
  document.getElementById('fuDays').placeholder = t.daysPlaceholder;
}

async function loadDoctors() {
  const res = await fetch('/doctors-list');
  const data = await res.json();
  const sel = document.getElementById('doc');
  sel.innerHTML = '';
  (data.doctors || []).forEach(d => {
    const o = document.createElement('option');
    o.value = d.id;
    o.textContent = d.name + ' · ' + d.specialty;
    sel.appendChild(o);
  });
  if (data.doctors && data.doctors.length) loadQueue();
}

async function loadQueue() {
  docId = document.getElementById('doc').value;
  if (!docId) return;
  const res = await fetch('/doctor/queue/' + docId);
  const data = await res.json();
  if (data.status !== 'success') return;

  running = data.current_serial;
  queue = data.patients || [];

  const waiting = queue.filter(p => p.serial_number > running);
  const upNext = waiting.length ? waiting[0] : null;
  const inRoom = queue.find(p => p.serial_number === running) || null;

  drawInRoom(inRoom);

  document.getElementById('nowNum').textContent = running === 0 ? t.noneYet : running;
  document.getElementById('leftNum').textContent = waiting.length;

  const btn = document.getElementById('callBtn');
  if (upNext) {
    document.getElementById('cue').textContent = running === 0 ? t.firstUp : t.nextIn;
    document.getElementById('nextNum').textContent = upNext.serial_number;
    document.getElementById('nextName').textContent =
        upNext.patients ? upNext.patients.name : t.unnamed;
    document.getElementById('nextWhy').textContent = upNext.reason || '';
    btn.disabled = false;
    btn.textContent = t.callNext;
  } else {
    document.getElementById('cue').textContent = t.nextIn;
    document.getElementById('nextNum').textContent = '—';
    document.getElementById('nextName').textContent =
        queue.length ? t.allSeen : t.nobodyToday;
    document.getElementById('nextWhy').textContent = '';
    btn.disabled = true;
    btn.textContent = queue.length ? t.listFinished : t.nobodyToCall;
  }

  drawRows();
}

function drawInRoom(p) {
  const card = document.getElementById('inroom');
  if (!p) { card.style.display = 'none'; return; }

  card.style.display = '';
  document.getElementById('inroomName').textContent =
      p.serial_number + '  ·  ' + (p.patients ? p.patients.name : t.unnamed);
  document.getElementById('fuDays').value = '';

  const chips = document.querySelectorAll('#fuChips .chip');
  chips.forEach(c => c.classList.remove('picked'));
  const note = document.getElementById('fuNote');

  if (p.follow_up_date) {
    note.textContent = t.returnSet + ' ' + p.follow_up_date;
    const days = Math.round(
      (new Date(p.follow_up_date) - new Date(new Date().toDateString())) / 86400000
    );
    chips.forEach(c => { if (c.dataset.days === String(days)) c.classList.add('picked'); });
  } else {
    note.textContent = '';
  }
}

async function setFollowUp(days, chipEl) {
  if (!docId) return;
  const res = await fetch('/doctor/follow-up/' + docId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ days: days })
  });
  const data = await res.json();
  const note = document.getElementById('fuNote');

  if (data.status !== 'success') {
    note.textContent = data.message || t.briefFailed;
    return;
  }

  document.querySelectorAll('#fuChips .chip').forEach(c => c.classList.remove('picked'));
  if (chipEl) chipEl.classList.add('picked');

  note.textContent = data.follow_up_date
      ? t.returnSet + ' ' + data.follow_up_date
      : t.noReturn;

  const p = queue.find(x => x.serial_number === running);
  if (p) p.follow_up_date = data.follow_up_date;
}

function setCustomFollowUp() {
  const days = parseInt(document.getElementById('fuDays').value, 10);
  if (!days || days < 1 || days > 730) {
    document.getElementById('fuNote').textContent = t.badDays;
    return;
  }
  setFollowUp(days, null);
}

function drawRows() {
  const box = document.getElementById('rows');
  box.innerHTML = '';
  if (!queue.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = t.noAppointments;
    box.appendChild(empty);
    return;
  }
  queue.forEach(p => {
    const row = document.createElement('div');
    row.className = 'row';
    row.tabIndex = 0;
    if (p.serial_number === running) row.classList.add('current');
    else if (p.serial_number < running) row.classList.add('seen');

    const s = document.createElement('div');
    s.className = 's';
    s.textContent = p.serial_number || '-';

    const body = document.createElement('div');
    const n = document.createElement('div');
    n.className = 'n';
    n.textContent = p.patients ? p.patients.name : t.unnamed;
    body.appendChild(n);
    if (p.reason) {
      const r = document.createElement('div');
      r.className = 'r';
      r.textContent = p.reason;
      body.appendChild(r);
    }

    row.appendChild(s);
    row.appendChild(body);
    row.onclick = () => openBrief(p.patient_id);
    row.onkeydown = e => { if (e.key === 'Enter') openBrief(p.patient_id); };
    box.appendChild(row);
  });
}

async function callNext() {
  if (!docId) return;
  document.getElementById('callBtn').disabled = true;
  await fetch('/doctor/next/' + docId, { method: 'POST' });
  await loadQueue();
}

async function resetQueue() {
  if (!docId) return;
  if (!confirm(t.confirmReset)) return;
  await fetch('/doctor/reset/' + docId, { method: 'POST' });
  loadQueue();
}

async function openBrief(patientId) {
  if (!patientId) return;
  openPatientId = patientId;
  document.getElementById('scrim').classList.add('open');
  document.getElementById('bName').textContent = t.loading;
  document.getElementById('bId').textContent = '';
  document.getElementById('bSaid').textContent = t.reading;
  document.getElementById('bVisits').innerHTML = '';
  document.getElementById('bNotesWrap').style.display = 'none';

  // the summary is written by the AI, so it has to be asked for in this language
  const res = await fetch('/doctor/patient-brief/' + patientId + '?lang=' + lang);
  const data = await res.json();
  if (data.status !== 'success') {
    document.getElementById('bName').textContent = t.couldNotLoad;
    document.getElementById('bSaid').textContent = t.briefFailed;
    return;
  }

  const p = data.patient;
  document.getElementById('bName').textContent = p.name;
  let line = p.phone;
  if (p.age) line += ', ' + t.age + ' ' + p.age;
  if (p.gender) line += ', ' + p.gender;
  document.getElementById('bId').textContent = line;

  // standing notes: allergies, chronic conditions, past surgery.
  // shown above the chat summary because it outranks anything said today.
  if (p.notes && p.notes.trim()) {
    document.getElementById('bNotes').textContent = p.notes;
    document.getElementById('bNotesWrap').style.display = '';
  }

  document.getElementById('bSaid').textContent = data.summary;

  const box = document.getElementById('bVisits');
  const past = data.visit_history || [];
  if (!past.length) {
    const none = document.createElement('div');
    none.className = 'visit x';
    none.textContent = t.noEarlier;
    box.appendChild(none);
    return;
  }
  past.forEach(v => {
    const el = document.createElement('div');
    el.className = 'visit';

    const d = document.createElement('div');
    d.className = 'd';
    d.textContent = v.appointment_date;

    const x = document.createElement('div');
    x.className = 'x';
    let detail = v.reason || t.reasonMissing;
    if (v.doctors) detail += ' ' + t.withDoctor + ' ' + v.doctors.name;
    detail += ', ' + v.status;
    x.textContent = detail;

    el.appendChild(d);
    el.appendChild(x);
    box.appendChild(el);
  });
}

function shutBrief(e) {
  if (e && e.target.id !== 'scrim') return;
  openPatientId = null;
  document.getElementById('scrim').classList.remove('open');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    openPatientId = null;
    document.getElementById('scrim').classList.remove('open');
  }
});

let saved = 'bn';
try { saved = localStorage.getItem('clinicLang') || 'bn'; } catch (e) {}
lang = saved;
t = STRINGS[saved];
document.getElementById('langBn').classList.toggle('on', saved === 'bn');
document.getElementById('langEn').classList.toggle('on', saved === 'en');
document.documentElement.lang = saved;
applyStaticLabels();

loadDoctors();
setInterval(loadQueue, 30000);
</script>
</body>
</html>
"""


@app.get("/doctors-list")
def doctors_list():
    """small helper the doctor page uses to fill its dropdown"""
    try:
        result = supabase.table("doctors").select("id, name, specialty").eq(
            "is_active", True
        ).order("id").execute()
        return {"status": "success", "doctors": result.data}
    except Exception as e:
        return {"status": "error", "message": str(e), "doctors": []}


@app.get("/doctor")
def doctor_page():
    """the queue control page the doctor opens"""
    return Response(content=DOCTOR_PAGE_HTML, media_type="text/html")