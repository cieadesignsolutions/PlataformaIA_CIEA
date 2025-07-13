from flask import Flask, request, jsonify
import requests
import os
import mysql.connector
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# ========= Configuración general =========
VERIFY_TOKEN = os.environ.get('VERIFICATION')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

# ========= Datos de Railway =========
DB_HOST = os.environ.get('DB_HOST') or 'interchange.proxy.rlwy.net'
DB_USER = os.environ.get('DB_USER') or 'root'
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_NAME = os.environ.get('DB_NAME') or 'railway'

client = OpenAI(api_key=OPENAI_API_KEY)

# ========= Conexión a MySQL =========
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

# ========= Rutas =========
@app.route('/')
def home():
    return '✅ Plataforma WhatsApp IA conectada a Railway correctamente.'

@app.route('/webhook', methods=['GET'])
def verificar_token():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == VERIFY_TOKEN:
        print("🔐 Verificación exitosa")
        return challenge
    print("🚫 Token de verificación inválido")
    return "Token inválido", 403

@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    data = request.get_json()
    print("📥 Datos recibidos:", data)

    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]['value']

        # Verificamos que haya mensajes
        if 'messages' not in changes:
            print("⚠️ No hay mensajes nuevos.")
            return "No hay mensajes", 200

        message = changes['messages'][0]
        numero = message['from']
        texto_usuario = message['text']['body']

        # 🔁 Evitar loop infinito (si el bot se responde a sí mismo)
        MI_NUMERO_BOT = os.environ.get('MI_NUMERO_BOT') or '15556652659'
	if numero == MI_NUMERO_BOT:
    		print("🔁 Mensaje del bot (propio número), ignorado.")
    		return "Ignorado", 200

        print(f"🟢 Mensaje de {numero}: {texto_usuario}")

        respuesta = responder_con_ia(texto_usuario)
        print(f"🤖 Respuesta generada: {respuesta}")

        enviar_mensaje(numero, respuesta)
        print("📤 Mensaje enviado")

        guardar_conversacion(numero, texto_usuario, respuesta)
        print("💾 Conversación guardada en MySQL")

    except Exception as e:
        print("❌ ERROR al procesar webhook:", e)

    return "OK", 200

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
        print("❌ ERROR al consultar chats:", e)
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
        print("❌ ERROR en OpenAI:", e)
        return "Lo siento, hubo un error."

def enviar_mensaje(numero, texto):
    url = "https://graph.facebook.com/v19.0/638096866063629/messages"
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
        print("📨 Respuesta de WhatsApp API:", response.status_code, response.text)
    except Exception as e:
        print("❌ ERROR al enviar mensaje a WhatsApp:", e)

def guardar_conversacion(numero, mensaje, respuesta):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS conversaciones (id INT AUTO_INCREMENT PRIMARY KEY, numero VARCHAR(20), mensaje TEXT, respuesta TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        cursor.execute(
            "INSERT INTO conversaciones (numero, mensaje, respuesta) VALUES (%s, %s, %s)",
            (numero, mensaje, respuesta)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("❌ ERROR al guardar conversación en MySQL:", e)

# ========= Ejecutar (Render ready) =========
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
