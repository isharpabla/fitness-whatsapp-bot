# Fitness AI WhatsApp Bot

WhatsApp-based AI assistant for gym-goers and home trainees in India.
Built with Flask, Twilio, OpenAI, and Redis.

## Setup
1. Create repo on GitHub, push these files.
2. Create a web service on Render.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python whatsapp_bot_ai.py`
   - Add environment variables:
     - OPENAI_API_KEY = <your OpenAI key>
     - REDIS_URL = <your Redis instance URL>
3. In Twilio Console:
   - Join WhatsApp Sandbox.
   - Set webhook URL to: `https://<your-app>.onrender.com/whatsapp`
4. Test by messaging the Sandbox number.
5. Optional: connect Razorpay webhook to: `https://<your-app>.onrender.com/razorpay_webhook`
