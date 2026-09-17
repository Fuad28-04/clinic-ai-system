import os
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Response
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


def ask_ai(session_id: str, patient_message: str) -> str:
    """the main brain call.
    loads history -> asks gemini -> saves both messages -> returns the reply
    """
    history = load_conversation_history(session_id)

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


@app.post("/webhook")
async def receive_whatsapp_message(request: Request):
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

        # use the phone number as the session id, so each patient gets their own memory
        reply_text = ask_ai(sender_phone, patient_text)

        send_whatsapp_message(sender_phone, reply_text)
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
            .select("id, patient_id, serial_number, reason, status, patients(name, phone)")
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
def patient_brief(patient_id: int):
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

        summary = generate_patient_summary(patient, recent_messages)

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


def generate_patient_summary(patient: dict, messages: list) -> str:
    """asks the AI to turn the patient's chat into a short brief for the doctor.
    NOTE: this is context only - it is not a diagnosis and must never read like one.
    """
    if not messages:
        return "No conversation history available for this patient."

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
- Write in Bangla.
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


DOCTOR_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doctor Queue</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 20px;
         background: #f4f6f8; color: #1a1a1a; }
  .wrap { max-width: 480px; margin: 0 auto; }
  .card { background: #fff; border-radius: 14px; padding: 22px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 16px; }
  h2 { margin: 0 0 4px; font-size: 20px; }
  .sub { color: #666; font-size: 14px; margin-bottom: 18px; }
  .serial-box { text-align: center; padding: 20px 0; }
  .serial-label { color: #666; font-size: 14px; }
  .serial { font-size: 68px; font-weight: 700; color: #1976d2; line-height: 1.1; }
  button { width: 100%; padding: 16px; font-size: 17px; font-weight: 600;
           border: none; border-radius: 10px; cursor: pointer; }
  .next { background: #1976d2; color: #fff; }
  .next:active { background: #145ea8; }
  .reset { background: #eee; color: #444; margin-top: 10px; font-size: 14px; padding: 10px; }
  select { width: 100%; padding: 12px; font-size: 16px; border-radius: 8px;
           border: 1px solid #ccc; margin-bottom: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 9px 6px; border-bottom: 1px solid #eee; }
  th { color: #666; font-weight: 600; }
  .now { background: #e3f2fd; font-weight: 600; }
  .done { color: #aaa; text-decoration: line-through; }
  tbody tr { cursor: pointer; }
  tbody tr:active { background: #f0f0f0; }
  .hint { color: #999; font-size: 12px; margin-top: 10px; }

  /* patient brief panel */
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45);
             display: none; align-items: flex-end; justify-content: center; }
  .overlay.open { display: flex; }
  .sheet { background: #fff; width: 100%; max-width: 480px; max-height: 88vh;
           overflow-y: auto; border-radius: 16px 16px 0 0; padding: 22px; }
  .sheet h3 { margin: 0 0 2px; font-size: 19px; }
  .sheet .meta { color: #666; font-size: 14px; margin-bottom: 16px; }
  .section-title { font-size: 13px; font-weight: 700; color: #1976d2;
                   text-transform: uppercase; letter-spacing: .4px;
                   margin: 20px 0 8px; }
  .summary-box { background: #f4f8fd; border-left: 3px solid #1976d2;
                 padding: 12px 14px; border-radius: 6px; font-size: 14px;
                 line-height: 1.65; white-space: pre-wrap; }
  .visit { border-bottom: 1px solid #eee; padding: 9px 0; font-size: 14px; }
  .visit .date { font-weight: 600; }
  .visit .detail { color: #666; font-size: 13px; }
  .close-btn { background: #eee; color: #333; margin-top: 18px; }
  .disclaimer { color: #999; font-size: 11px; margin-top: 8px; line-height: 1.5; }
</style>
</head>
<body>
<div class="wrap">

  <div class="card">
    <h2>Doctor Queue</h2>
    <div class="sub" id="dateLabel"></div>
    <select id="doctorSelect" onchange="loadQueue()"></select>
  </div>

  <div class="card">
    <div class="serial-box">
      <div class="serial-label">Now serving</div>
      <div class="serial" id="currentSerial">-</div>
      <div class="serial-label" id="totalLabel"></div>
    </div>
    <button class="next" onclick="nextPatient()">Next Patient &rarr;</button>
    <button class="reset" onclick="resetQueue()">Reset queue to 0</button>
  </div>

  <div class="card">
    <h2 style="font-size:16px;margin-bottom:12px;">Today's patients</h2>
    <table>
      <thead><tr><th>#</th><th>Name</th><th>Reason</th></tr></thead>
      <tbody id="patientList"></tbody>
    </table>
    <div class="hint">Tap a patient to see their brief</div>
  </div>

</div>

<div class="overlay" id="overlay" onclick="closeBrief(event)">
  <div class="sheet" onclick="event.stopPropagation()">
    <h3 id="briefName">-</h3>
    <div class="meta" id="briefMeta"></div>

    <div class="section-title">Summary</div>
    <div class="summary-box" id="briefSummary">Loading...</div>
    <div class="disclaimer">
      Auto-generated from what the patient wrote to the assistant.
      Context only &mdash; not a diagnosis.
    </div>

    <div class="section-title">Previous visits</div>
    <div id="briefHistory"></div>

    <button class="close-btn" onclick="closeBrief()">Close</button>
  </div>
</div>

<script>
let doctorId = null;
let currentSerial = 0;

document.getElementById('dateLabel').textContent = new Date().toDateString();

async function loadDoctors() {
  const res = await fetch('/doctors-list');
  const data = await res.json();
  const sel = document.getElementById('doctorSelect');
  sel.innerHTML = '';
  data.doctors.forEach(d => {
    const opt = document.createElement('option');
    opt.value = d.id;
    opt.textContent = d.name + ' (' + d.specialty + ')';
    sel.appendChild(opt);
  });
  if (data.doctors.length > 0) {
    doctorId = data.doctors[0].id;
    loadQueue();
  }
}

async function loadQueue() {
  doctorId = document.getElementById('doctorSelect').value;
  const res = await fetch('/doctor/queue/' + doctorId);
  const data = await res.json();
  if (data.status !== 'success') return;

  currentSerial = data.current_serial;
  document.getElementById('currentSerial').textContent =
      currentSerial === 0 ? '-' : currentSerial;
  document.getElementById('totalLabel').textContent =
      'out of ' + data.total_patients + ' booked today';

  const tbody = document.getElementById('patientList');
  tbody.innerHTML = '';
  if (data.patients.length === 0) {
    tbody.innerHTML = '<tr><td colspan="3" style="color:#999">No patients booked today</td></tr>';
    return;
  }
  data.patients.forEach(p => {
    const tr = document.createElement('tr');
    if (p.serial_number === currentSerial) tr.className = 'now';
    else if (p.serial_number < currentSerial) tr.className = 'done';
    tr.innerHTML = '<td>' + (p.serial_number || '-') + '</td>' +
                   '<td>' + (p.patients ? p.patients.name : '-') + '</td>' +
                   '<td>' + (p.reason || '-') + '</td>';
    tr.onclick = () => openBrief(p.patient_id);
    tbody.appendChild(tr);
  });
}

async function openBrief(patientId) {
  if (!patientId) return;
  document.getElementById('overlay').classList.add('open');
  document.getElementById('briefName').textContent = 'Loading...';
  document.getElementById('briefMeta').textContent = '';
  document.getElementById('briefSummary').textContent = 'Preparing summary...';
  document.getElementById('briefHistory').innerHTML = '';

  const res = await fetch('/doctor/patient-brief/' + patientId);
  const data = await res.json();
  if (data.status !== 'success') {
    document.getElementById('briefSummary').textContent = 'Could not load this patient.';
    return;
  }

  const p = data.patient;
  document.getElementById('briefName').textContent = p.name;
  let meta = p.phone;
  if (p.age) meta += '  |  Age ' + p.age;
  if (p.gender) meta += '  |  ' + p.gender;
  document.getElementById('briefMeta').textContent = meta;
  document.getElementById('briefSummary').textContent = data.summary;

  const hist = document.getElementById('briefHistory');
  if (!data.visit_history || data.visit_history.length === 0) {
    hist.innerHTML = '<div class="visit detail">First visit &mdash; no previous records</div>';
  } else {
    data.visit_history.forEach(v => {
      const div = document.createElement('div');
      div.className = 'visit';
      const doc = v.doctors ? v.doctors.name : '';
      div.innerHTML = '<div class="date">' + v.appointment_date + ' &middot; ' + v.status + '</div>' +
                      '<div class="detail">' + (v.reason || 'no reason recorded') +
                      (doc ? ' &mdash; ' + doc : '') + '</div>';
      hist.appendChild(div);
    });
  }
}

function closeBrief(event) {
  if (event && event.target.id !== 'overlay') return;
  document.getElementById('overlay').classList.remove('open');
}

async function nextPatient() {
  if (!doctorId) return;
  await fetch('/doctor/next/' + doctorId, { method: 'POST' });
  loadQueue();
}

async function resetQueue() {
  if (!doctorId) return;
  if (!confirm('Reset the queue back to 0?')) return;
  await fetch('/doctor/reset/' + doctorId, { method: 'POST' });
  loadQueue();
}

loadDoctors();
setInterval(loadQueue, 30000);   // auto refresh every 30s
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