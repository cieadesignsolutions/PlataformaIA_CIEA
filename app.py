import os
import requests
import mysql.connector
from flask import (
    Flask, request, jsonify,
    render_template, redirect, url_for
)
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

# ——— Carga de entorno ———
load_dotenv()
app = Flask(__name__)

# ——— Configuración ———
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_HOST        = os.getenv("DB_HOST")
DB_USER        = os.getenv("DB_USER")
DB_PASSWORD    = os.getenv("DB_PASSWORD")
DB_NAME        = os.getenv("DB_NAME")
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")  # ej. "638096866063629"

client = OpenAI(api_key=OPENAI_API_KEY)

# ——— Conexión MySQL ———
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# ——— Lógica IA ———
def responder_con_ia(mensaje: str) -> str:
    try:
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un asistente útil que responde por WhatsApp."},
                {"role": "user",   "content": mensaje}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"🔴 Error en OpenAI: {e}")
        return "Lo siento, hubo un error."

# ——— Guardar conversación ———
def guardar_conversacion(numero: str, mensaje: str, respuesta: str):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversaciones (
              id INT AUTO_INCREMENT PRIMARY KEY,
              numero VARCHAR(20),
              mensaje TEXT,
              respuesta TEXT,
              timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """
        )
        cursor.execute(
            "INSERT INTO conversaciones (numero,mensaje,respuesta) VALUES (%s,%s,%s)",
            (numero, mensaje, respuesta)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"🔴 Error guardando en BD: {e}")

# ——— Enviar WhatsApp ———
def enviar_mensaje(numero: str, texto: str):
    url = f"https://graph.facebook.com/v17.0/{MI_NUMERO_BOT}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type":  "application/json"
    }
    body = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": texto}
    }
    try:
        r = requests.post(url, headers=headers, json=body)
        app.logger.info(f"📤 WhatsApp API: {r.status_code} {r.text}")
    except Exception as e:
        app.logger.error(f"🔴 Error enviando WhatsApp: {e}")

# ——— Webhook de verificación ———
@app.route("/webhook", methods=["GET"])
def webhook_verification():
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403

# ——— Webhook de mensajes ———
@app.route("/webhook", methods=["POST"])
def recibir_mensaje():
    payload = request.get_json()
    app.logger.info(f"📥 Payload: {payload}")
    try:
        entry    = payload["entry"][0]
        change   = entry["changes"][0]["value"]
        mensajes = change.get("messages")
        if not mensajes:
            return "No hay mensajes", 200

        msg       = mensajes[0]
        numero    = msg["from"]
        texto     = msg["text"]["body"]
        if numero == MI_NUMERO_BOT:
            return "OK", 200

        respuesta = responder_con_ia(texto)
        enviar_mensaje(numero, respuesta)
        guardar_conversacion(numero, texto, respuesta)

    except Exception as e:
        app.logger.error(f"🔴 Error webhook: {e}")
        return "Error interno", 500
    return "OK", 200

# ——— Panel web de chats ———
@app.route("/", methods=["GET"])
def inicio():
    return redirect(url_for('ver_panel_chats'))

@app.route("/chats", methods=["GET"])
def ver_panel_chats():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT numero, MAX(timestamp) AS ultima FROM conversaciones GROUP BY numero ORDER BY ultima DESC"
    )
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        "chats.html",
        chats=chats, mensajes=None,
        ia_activa=True,
        seleccionado=None
    )

@app.route("/chats/<telefono>", methods=["GET"])
def ver_chat(telefono):
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM conversaciones WHERE numero=%s ORDER BY timestamp",
        (telefono,)
    )
    msgs = cursor.fetchall()
    cursor.execute(
        "SELECT numero, MAX(timestamp) AS ultima FROM conversaciones GROUP BY numero ORDER BY ultima DESC"
    )
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        "chats.html",
        chats=chats,
        mensajes=msgs,
        ia_activa=True,
        seleccionado=telefono
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)