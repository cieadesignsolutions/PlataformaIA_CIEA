from flask import Flask, request, jsonify
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

MI_NUMERO_BOT = os.environ.get('MI_NUMERO_BOT') or '638096866063629'  # Asegúrate de definir este

client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca='/etc/ssl/certs/ca-certificates.crt'
    )

# ========= Webhook de verificación =========
@app.route('/webhook', methods=['GET'])
def verificar_token():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == VERIFY_TOKEN:
        return challenge
    return "Token inválido", 403

# ========= Webhook de mensajes =========
@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    data = request.get_json()
    print("📥 Recibido:", data)
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

        # Evitar que el bot se responda a sí mismo
        if numero == MI_NUMERO_BOT:
            print("⛔ Mensaje del mismo bot, ignorado.")
            return "OK", 200

        respuesta = responder_con_ia(texto_usuario)
        enviar_mensaje(numero, respuesta)
        guardar_conversacion(numero, texto_usuario, respuesta)
    except Exception as e:
        print("❌ Error en webhook:", e)

    return "OK", 200

# ========= Ver chats =========
@app.route('/chats', methods=['GET'])
def ver_chats():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM conversaciones ORDER BY timestamp DESC")
        datos = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(datos)
    except Exception as e:
        print("❌ Error al obtener chats:", e)
        return jsonify([])

# ========= Utilidades =========
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
        print("📤 Enviado:", response.status_code, response.text)
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
        print("💾 Conversación guardada.")
    except Exception as e:
        print("❌ Error al guardar en MySQL:", e)

# ========= Inicio =========
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
