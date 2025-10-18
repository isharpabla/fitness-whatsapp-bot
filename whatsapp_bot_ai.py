# whatsapp_bot_ai.py

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os, sys, traceback, redis, json

app = Flask(__name__)

# --- env config ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REDIS_URL      = os.environ.get("REDIS_URL", "redis://localhost:6379")
FREE_LIMIT     = int(os.environ.get("FREE_LIMIT", "10"))
PAYMENT_LINK   = os.environ.get("PAYMENT_LINK", "https://rzp.io/i/your-link")
MAX_HISTORY    = int(os.environ.get("MAX_HISTORY", "8"))  # pairs to retain

PAYWALL_TEXT = "You’ve reached your free limit. Unlock unlimited chat for 30 days: " + PAYMENT_LINK
SUGGESTIONS = [
    "Correct my squat or deadlift cues",
    "Give me a 4-day upper/lower plan",
    "High-protein Indian veg meal ideas",
    "How to take creatine safely?",
    "Quick hotel-room or home workout",
]

# --- clients ---
client = OpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)

SYSTEM_PROMPT = """
You are a comprehensive fitness and nutrition coach for everyday Indians training at home or in the gym. 
Speak like an experienced, calm gym trainer: clear, practical, encouraging, never emotional or dramatic.

Provide detailed, actionable guidance on:
• Workout planning: full-body, push–pull–legs, upper/lower, cardio, and home-based routines using bodyweight or minimal equipment.
• Form correction and injury prevention: explain movement mechanics, tempo, range of motion, and warm-up requirements.
• Diet and nutrition: balanced Indian meal ideas, macronutrient basics, hydration, and recovery foods.
• Supplement education: you may explain well-studied, legal supplements (e.g., whey protein, creatine monohydrate, omega-3, electrolytes) but always include a clear caution — users should confirm dosage and suitability with a certified nutritionist or doctor.
• Medical or health context: when discussing pain, fatigue, or conditions, only describe what reputable public sources (WHO, ICMR, NIH, Mayo Clinic) say. Never diagnose or give personalized medical advice.
• Behavior and discipline: consistency, rest, hygiene, and gym etiquette.

Personal questions are allowed, but respond with general, non-personalized education and options. Do not request private health data. If personalization is necessary, state what factors usually matter and suggest seeing a professional.

Keep replies concise and structured. Prefer bullets. End every reply with 3 short follow-up prompts the user can ask next.
Always prioritize safety, sustainability, and realistic long-term progress.
"""

# ---------- Redis-safe helpers ----------
def is_paid(num: str) -> bool:
    try: return bool(r.sismember("paid_users", num))
    except: return False

def get_count(num: str) -> int:
    try: return int(r.get(f"count:{num}") or 0)
    except: return 0

def add_count(num: str) -> None:
    try:
        key = f"count:{num}"
        pipe = r.pipeline(); pipe.incr(key); pipe.expire(key, 86400); pipe.execute()
    except: pass

def _hist_key(num): return f"hist:{num}"

def get_history(num):
    try:
        raw = r.lrange(_hist_key(num), 0, MAX_HISTORY*2-1)  # newest first
        return [json.loads(x) for x in reversed(raw)]
    except: return []

def add_history(num, role, content):
    try:
        item = json.dumps({"role": role, "content": content})
        pipe = r.pipeline()
        pipe.lpush(_hist_key(num), item)
        pipe.ltrim(_hist_key(num), 0, MAX_HISTORY*2-1)
        pipe.expire(_hist_key(num), 86400)
        pipe.execute()
    except: pass

def with_suggestions(answer: str) -> str:
    tips = "Next you can ask:\n- " + "\n- ".join(SUGGESTIONS[:3])
    return f"{answer}\n\n{tips}\n(Type 'reset' to clear context.)"

def _reply(text: str):
    msg = MessagingResponse()
    msg.message(text)
    return msg

# -------------- routes --------------
@app.get("/")
def health():
    return "Fitness AI WhatsApp Bot is running."

# optional echo for Twilio testing
@app.post("/echo")
def echo():
    rmsg = MessagingResponse(); rmsg.message("pong"); return str(rmsg)

@app.post("/whatsapp")
def whatsapp_webhook():
    user_msg = (request.form.get("Body", "") or "").strip()
    user_num = request.form.get("From", "")  # e.g., whatsapp:+91XXXXXXXXXX
    if not user_msg:
        return str(_reply("Send a fitness question to begin."))

    # commands
    if user_msg.lower() == "reset":
        try: r.delete(_hist_key(user_num))
        except: pass
        return str(_reply("Context cleared. Ask your next question."))

    # paywall gate
    cnt = get_count(user_num)
    paid = is_paid(user_num)
    if not paid and cnt >= FREE_LIMIT:
        return str(_reply(PAYWALL_TEXT))
    add_count(user_num)

    # assemble messages with memory
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in get_history(user_num):
        if m.get("role") in ("user","assistant"):
            msgs.append(m)
    msgs.append({"role": "user", "content": user_msg})

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msgs,
            temperature=0.4,
            max_tokens=700,
        )
        text = (resp.choices[0].message.content or "").strip()

        # persist turn
        add_history(user_num, "user", user_msg)
        add_history(user_num, "assistant", text)

        return str(_reply(with_suggestions(text)))
    except Exception as e:
        print("OpenAI error:", e, file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return str(_reply("Temporary issue. Try again shortly."))

# Razorpay webhook (simple; add signature verification for production)
@app.post("/razorpay_webhook")
def razorpay_webhook():
    data = request.json or {}
    try:
        if data.get("event") == "payment.captured":
            phone = (
                data.get("payload", {})
                .get("payment", {})
                .get("entity", {})
                .get("notes", {})
                .get("phone")
            )
            if phone:
                try: r.sadd("paid_users", phone)
                except: pass
    except Exception as e:
        print("Webhook error:", e, file=sys.stderr, flush=True)
    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
