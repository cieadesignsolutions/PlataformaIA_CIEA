import os
import requests
import mysql.connector
from flask import Flask, request, jsonify, render_template, redirect, url_for
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ——— Configuración desde env vars ———
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_HOST        = os.getenv("DB_HOST")
DB_USER        = os.getenv("DB_USER")
DB_PASSWORD    = os.getenv("DB_PASSWORD")
DB_NAME        = os.getenv("DB_NAME")
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")  # ej. "638096866063629"

# Cliente OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Estado de la IA (On/Off)
IA_ON = {"value": True}

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# ——— Función IA ———
def responder_con_ia(texto: str) -> str:
    try:
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role":"system", "content":"Eres un asistente útil por WhatsApp."},
                {"role":"user",   "content":texto}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error("Error OpenAI: %s", e)
        return "Lo siento, algo falló."

# ——— Webhook verificación ———
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403

# ——— Webhook mensajes ———
@app.route("/webhook", methods=["POST"])
def webhook_receive():
    data = request.get_json()
    app.logger.info("📥 payload: %s", data)
    try:
        msgs = data["entry"][0]["changes"][0]["value"].get("messages")
        if not msgs:
            return "No messages", 200

        m = msgs[0]
        src = m["from"]
        text = m["text"]["body"]

        if src == MI_NUMERO_BOT:
            return "OK", 200

        # IA on?
        reply = ""
        if IA_ON["value"]:
            reply = responder_con_ia(text)
            enviar_mensaje(src, reply)

        guardar_conversacion(src, text, reply)
    except Exception as e:
        app.logger.error("Error procesando webhook: %s", e)
        return "Error interno", 500

    return "OK", 200

# ——— Envío WA ———
def enviar_mensaje(dest: str, texto: str):
    url = f"https://graph.facebook.com/v17.0/{MI_NUMERO_BOT}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":  "application/json"
    }
    body = {
        "messaging_product":"whatsapp",
        "to":dest,
        "type":"text",
        "text":{"body":texto}
    }
    try:
        r = requests.post(url, headers=headers, json=body)
        app.logger.info("📤 WA API: %s %s", r.status_code, r.text)
    except Exception as e:
        app.logger.error("Error enviando WA: %s", e)

# ——— Guardar en BD ———
def guardar_conversacion(num: str, msg: str, rsp: str):
    try:
        conn   = get_db_connection()
        cur    = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversaciones (
              id INT AUTO_INCREMENT PRIMARY KEY,
              numero VARCHAR(20),
              mensaje TEXT,
              respuesta TEXT,
              timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        """)
        cur.execute(
            "INSERT INTO conversaciones (numero,mensaje,respuesta) VALUES (%s,%s,%s)",
            (num, msg, rsp)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error("Error guardando BD: %s", e)

# ——— Panel de chats ———
@app.route("/chats")
def ver_chats():
    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT DISTINCT numero,
               MAX(timestamp) AS ultima
        FROM conversaciones
        GROUP BY numero
        ORDER BY ultima DESC
    """)
    chats = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("chats.html",
                           chats=chats,
                           mensajes=None,
                           ia_on=IA_ON["value"],
                           selected=None)

@app.route("/chats/<telefono>")
def ver_chat(telefono):
    conn = get_db_connection()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT numero, mensaje, respuesta, timestamp
        FROM conversaciones
        WHERE numero=%s
        ORDER BY timestamp
    """, (telefono,))
    msgs = cur.fetchall()
    cur.execute("""
        SELECT DISTINCT numero,
               MAX(timestamp) AS ultima
        FROM conversaciones
        GROUP BY numero
        ORDER BY ultima DESC
    """)
    chats = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("chats.html",
                           chats=chats,
                           mensajes=msgs,
                           ia_on=IA_ON["value"],
                           selected=telefono)

# ——— Toggle IA ———
@app.route("/toggle_ai", methods=["POST"])
def toggle_ai():
    IA_ON["value"] = not IA_ON["value"]
    return redirect(url_for("ver_chats"))

if __name__ == "__main__":
    p = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=p)
