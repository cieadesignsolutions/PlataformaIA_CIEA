import os
import requests
import mysql.connector
from flask import Flask, request, jsonify, render_template, redirect, url_for
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# — Configuración env vars —
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_HOST        = os.getenv("DB_HOST")
DB_USER        = os.getenv("DB_USER")
DB_PASSWORD    = os.getenv("DB_PASSWORD")
DB_NAME        = os.getenv("DB_NAME")
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")

# Estado IA en memoria
IA_ON = {"on": True}
client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# — Webhook verificación —
@app.route("/webhook", methods=["GET"])
def webhook_verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Token inválido", 403

# — Webhook recepción mensajes —
@app.route("/webhook", methods=["POST"])
def webhook_receive():
    data = request.get_json()
    try:
        msgs = data["entry"][0]["changes"][0]["value"].get("messages")
        if not msgs: return "OK", 200
        m = msgs[0]
        num, text = m["from"], m["text"]["body"]
        if num == MI_NUMERO_BOT: return "OK", 200

        resp = ""
        if IA_ON["on"]:
            resp = responder_con_ia(text)
            enviar_mensaje(num, resp)

        guardar_conversacion(num, text, resp)
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return "Error", 500
    return "OK", 200

# — Panel chats —
@app.route("/")
def inicio():
    return redirect(url_for("ver_chats"))

@app.route("/chats")
def ver_chats():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT numero, MAX(timestamp) AS ultima "
      "FROM conversaciones GROUP BY numero "
      "ORDER BY ultima DESC"
    )
    chats = cur.fetchall()
    cur.close(); conn.close()
    return render_template("chats.html",
        chats=chats, mensajes=None,
        ia_on=IA_ON["on"], selected=None
    )

@app.route("/chats/<numero>")
def ver_chat(numero):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
      "SELECT * FROM conversaciones WHERE numero=%s ORDER BY timestamp",
      (numero,)
    )
    msgs = cur.fetchall()
    cur.execute(
      "SELECT numero, MAX(timestamp) AS ultima "
      "FROM conversaciones GROUP BY numero "
      "ORDER BY ultima DESC"
    )
    chats = cur.fetchall()
    cur.close(); conn.close()
    return render_template("chats.html",
        chats=chats, mensajes=msgs,
        ia_on=IA_ON["on"], selected=numero
    )

@app.route("/toggle_ai", methods=["POST"])
def toggle_ai():
    IA_ON["on"] = not IA_ON["on"]
    return redirect(url_for("ver_chats"))

# — IA/OpenAI —
def responder_con_ia(texto: str) -> str:
    try:
        r = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role":"system","content":"Eres asistente IA para WhatsApp."},
                {"role":"user","content":texto}
            ]
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"OpenAI error: {e}")
        return "Lo siento, error."

# — Envío WhatsApp API —
def enviar_mensaje(num: str, txt: str):
    url = f"https://graph.facebook.com/v17.0/{MI_NUMERO_BOT}/messages"
    h = {"Authorization":f"Bearer {WHATSAPP_TOKEN}",
         "Content-Type":"application/json"}
    body = {"messaging_product":"whatsapp","to":num,
            "type":"text","text":{"body":txt}}
    r = requests.post(url, headers=h, json=body)
    app.logger.info(f"WhatsApp API: {r.status_code} {r.text}")

# — Guardar en MySQL —
def guardar_conversacion(num, msg, resp):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS conversaciones (
        id INT AUTO_INCREMENT PRIMARY KEY,
        numero VARCHAR(20),
        mensaje TEXT,
        respuesta TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
      ) ENGINE=InnoDB;
    """)
    cur.execute(
      "INSERT INTO conversaciones (numero,mensaje,respuesta) VALUES (%s,%s,%s)",
      (num,msg,resp)
    )
    conn.commit(); cur.close(); conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
