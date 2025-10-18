from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os, sys, traceback, redis

app = Flask(__name__)

# --- config via env ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
FREE_LIMIT = int(os.environ.get("FREE_LIMIT", "10"))           # e.g., 10
PAYMENT_LINK = os.environ.get("PAYMENT_LINK", "https://rzp.io/i/your-link")
PAYWALL_TEXT = (
    "You’ve reached your free limit. Unlock unlimited chat for 30 days: " + PAYMENT_LINK
)

# --- clients ---
client = OpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)

SYSTEM_PROMPT = """
You are a comprehensive fitness and nutrition coach for everyday Indians training at home or in the gym.

Provide detailed, actionable guidance on:
• Workout planning: full-body, push–pull–legs, upper/lower, cardio, and home-based routines using bodyweight or minimal equipment.
• Form correction and injury prevention: explain movement mechanics, tempo, range of motion, and warm-up requirements.
• Diet and nutrition: share balanced Indian meal ideas, macronutrient basics, hydration, and recovery foods.
• Supplement education: you may explain well-studied, legal supplements (e.g., whey protein, creatine monohydrate, omega-3, electrolytes) but must always include a clear caution — users should confirm dosage and suitability with a certified nutritionist or doctor.
• Medical or health context: when discussing pain, fatigue, or conditions, only describe what verified sources (WHO, ICMR, NIH, Mayo Clinic) say publicly. Never diagnose or give personalized medical advice.
• Behavior and discipline: include practical guidance on consistency, rest, hygiene, and gym etiquette.

Cite reputable public health or research sources where possible.
Never ask for or infer private health data.
Maintain a professional, factual, motivating tone — precise and encouraging but never emotional.
Always prioritize user safety, sustainability, and realistic long-term progress.
"""

# -------- Redis-safe helpers --------
def is_paid(num: str) -> bool:
    try:
        return bool(r.sismember("paid_users", num))
    except Exception:
        return False

def get_count(num: str) -> int:
    try:
        val = r.get(f"count:{num}")
        return int(val or 0)
    except Exception:
        return 0

def add_count(num: str) -> None:
    try:
        key = f"count:{num}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)  # 24h rolling window
        pipe.execute()
    except Exception:
        pass

# -------------- routes --------------
@app.get("/")
def health():
    return "Fitness AI WhatsApp Bot is running."

# Optional: quick Twilio connectivity check
@app.post("/echo")
def echo():
    resp = MessagingResponse()
    resp.message("pong")
    return str(resp)

@app.post("/whatsapp")
def whatsapp_webhook():
    user_msg = (request.form.get("Body", "") or "").strip()
    user_num = request.form.get("From", "")  # format: whatsapp:+91XXXXXXXXXX
    if not user_msg:
        return str(_reply("Send a fitness question to begin."))

    # paywall gate with resilient Redis
    cnt = get_count(user_num)
    paid = is_paid(user_num)
    if not paid and cnt >= FREE_LIMIT:
        return str(_reply(PAYWALL_TEXT))
    add_count(user_num)

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.5,
            max_tokens=400,
        )
        text = resp.choices[0].message.content.strip()
        return str(_reply(text))
    except Exception as e:
        print("OpenAI error:", e, file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        return str(_reply("Temporary issue. Try again shortly."))

# Razorpay webhook (simple; add signature verification for prod)
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
                try:
                    r.sadd("paid_users", phone)
                except Exception:
                    pass
    except Exception as e:
        print("Webhook error:", e, file=sys.stderr, flush=True)
    return "", 200

def _reply(text: str):
    msg = MessagingResponse()
    msg.message(text)
    return msg

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
