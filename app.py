from flask import Flask, request, jsonify, render_template, redirect, url_for
import requests
import os
import mysql.connector
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ========= Configuración =========
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
DB_HOST = os.environ.get('DB_HOST')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME')
MI_NUMERO_BOT = os.environ.get('MI_NUMERO_BOT') or '638096866063629'

IA_ESTADO = {'activa': True}  # Estado en memoria

client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca='/etc/ssl/certs/ca-certificates.crt'
    )

@app.route('/')
def inicio():
    return redirect(url_for('ver_panel_chats'))

@app.route('/webhook', methods=['GET'])
def verificar_token():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403

@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    data = request.get_json()
    print("\U0001f4e5 Recibido:", data)
    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        mensajes = value.get('messages')
        if not mensajes:
            return "No hay mensajes", 200

        message = mensajes[0]
        numero = message['from']
        texto_usuario = message['text']['body']

        if numero == MI_NUMERO_BOT:
            print("⛔ Mensaje del mismo bot, ignorado.")
            return "OK", 200

        respuesta = ""
        if IA_ESTADO['activa']:
            respuesta = responder_con_ia(texto_usuario)
            enviar_mensaje(numero, respuesta)
        guardar_conversacion(numero, texto_usuario, respuesta)
    except Exception as e:
        print("❌ Error en webhook:", e)
    return "OK", 200

@app.route('/chats')
def ver_panel_chats():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT DISTINCT numero FROM conversaciones ORDER BY timestamp DESC")
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("chats.html", chats=chats, mensajes=None, ia_activa=IA_ESTADO['activa'], numero=None)

@app.route('/chats/<telefono>')
def ver_chat(telefono):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM conversaciones WHERE numero = %s ORDER BY timestamp", (telefono,))
    mensajes = cursor.fetchall()
    cursor.execute("SELECT DISTINCT numero FROM conversaciones ORDER BY timestamp DESC")
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("chats.html", chats=chats, mensajes=mensajes, ia_activa=IA_ESTADO['activa'], numero=telefono)

@app.route('/toggle_ai', methods=['POST'])
def toggle_ai():
    IA_ESTADO['activa'] = not IA_ESTADO['activa']
    return redirect(url_for('ver_panel_chats'))

def responder_con_ia(mensaje):
    try:
        completion = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Eres un asistente útil que responde por WhatsApp."},
                {"role": "user", "content": mensaje}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Error en OpenAI:", e)
        return "Lo siento, hubo un error."

def enviar_mensaje(numero, texto):
    url = f"https://graph.facebook.com/v19.0/{MI_NUMERO_BOT}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": texto}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        print("\U0001f4e4 Enviado:", response.status_code, response.text)
    except Exception as e:
        print("❌ Error al enviar WhatsApp:", e)

def guardar_conversacion(numero, mensaje, respuesta):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversaciones (
                id INT AUTO_INCREMENT PRIMARY KEY,
                numero VARCHAR(20),
                mensaje TEXT,
                respuesta TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("INSERT INTO conversaciones (numero, mensaje, respuesta) VALUES (%s, %s, %s)",
                       (numero, mensaje, respuesta))
        conn.commit()
        cursor.close()
        conn.close()
        print("\U0001f4be Conversación guardada.")
    except Exception as e:
        print("❌ Error al guardar en MySQL:", e)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
