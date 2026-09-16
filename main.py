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
    return {"message": "Clinic AI Backend is running! ✅"}


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
            "message": "Database connection is working ✅",
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
            "message": "Gemini AI connection is working ✅",
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

    # create the appointment
    new_appointment = supabase.table("appointments").insert({
        "patient_id": patient_id,
        "doctor_id": doctor["id"],
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "reason": reason,
        "status": "booked"
    }).execute()

    return {
        "success": True,
        "message": "Appointment booked successfully",
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


# list of tools the AI is allowed to use
CLINIC_TOOLS = [
    get_all_doctors,
    check_doctor_schedule,
    book_appointment,
    get_patient_appointments,
    cancel_appointment,
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
- NEVER make up doctor schedules, fees, or availability. Always use the tools to get real data.
- To book an appointment, you MUST collect: patient name, phone number, doctor name,
  preferred date, preferred time, and reason for visit. Ask for anything missing before booking.
  Remember what the patient already told you earlier in this conversation, don't ask again.
- If the patient wants to check their existing appointments, ask for their phone number
  (if not already known) and use get_patient_appointments.
- If the patient wants to cancel an appointment, first check their appointments if you don't
  already know which one they mean, confirm the exact appointment with them, then cancel it.
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
            send_whatsapp_message(
                sender_phone,
                "দুঃখিত, এখন শুধু টেক্সট মেসেজ বুঝতে পারি। অনুগ্রহ করে লিখে জানান।"
            )
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