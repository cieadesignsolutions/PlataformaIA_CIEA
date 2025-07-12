from flask import Flask, request, jsonify
import requests
import os
import mysql.connector
from openai import OpenAI
from datetime import datetime

app = Flask(__name__)

# ===== CONFIGURACIÓN =====
VERIFY_TOKEN = os.environ.get('VERIFICATION')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

DB_HOST = os.environ.get('DB_HOST')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME')

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# CONEXIÓN A BASE DE DATOS
# =========================
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

# =========================
# IA
# =========================
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
        print("Error en OpenAI:", e)
        return "Hubo un error al responder."

# =========================
# RUTAS FLASK
# =========================
@app.route('/', methods=['GET'])
def home():
    return '✅ Plataforma WhatsApp IA corriendo correctamente.'

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
    try:
        entry = data['entry'][0]
        message = entry['changes'][0]['value']['messages'][0]
        numero = message['from']
        texto_usuario = message['text']['body']

        respuesta = responder_con_ia(texto_usuario)
        enviar_mensaje(numero, respuesta)
        guardar_conversacion(numero, texto_usuario, respuesta)

    except Exception as e:
        print("Error al procesar el mensaje:", e)
    return "OK", 200

@app.route('/chats', methods=['GET'])
def ver_chats():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM conversaciones ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(rows)
    except Exception as e:
        print("Error al consultar:", e)
        return jsonify([])

# =========================
# ENVÍO Y GUARDADO
# =========================
def enviar_mensaje(numero, texto):
    url = "https://graph.facebook.com/v19.0/15556652659/messages"
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
    requests.post(url, headers=headers, json=payload)

def guardar_conversacion(numero, mensaje, respuesta):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversaciones (numero, mensaje, respuesta) VALUES (%s, %s, %s)",
            (numero, mensaje, respuesta)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("Error al guardar conversación:", e)

# =========================
# RUN FLASK (Render ready)
# =========================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
