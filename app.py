from flask import Flask, request, render_template
import requests
import json
import os
from openai import OpenAI
from datetime import datetime

app = Flask(__name__)

# ===== CONFIGURACIÓN desde entorno =====
VERIFY_TOKEN = os.environ.get('VERIFICATION')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

client = OpenAI(api_key=OPENAI_API_KEY)

# Ruta al archivo de conversaciones (en Render usar /tmp/)
CONVERSACIONES_FILE = "/tmp/conversaciones.json"

@app.route('/')
def home():
    return "Plataforma IA CIEA activa en Render."

@app.route('/webhook', methods=['GET'])
def verificar_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verificación fallida", 403

@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    data = request.get_json()
    print("Mensaje recibido:", json.dumps(data, indent=2))
    try:
        entry = data['entry'][0]
        message = entry['changes'][0]['value']['messages'][0]
        texto = message['text']['body']
        numero = message['from']

        # 1. Generar respuesta IA
        respuesta = generar_respuesta_ia(texto)

        # 2. Enviar a WhatsApp
        enviar_respuesta_whatsapp(numero, respuesta)

        # 3. Guardar en historial
        guardar_conversacion(numero, texto, respuesta)

    except Exception as e:
        print("❌ Error procesando el mensaje:", e)
    return "OK", 200

@app.route('/chats')
def chats():
    try:
        if os.path.exists(CONVERSACIONES_FILE):
            with open(CONVERSACIONES_FILE, "r", encoding="utf-8") as f:
                datos = json.load(f)
        else:
            datos = []
    except Exception as e:
        datos = []
        print("❌ Error al cargar chats:", e)

    return render_template("chats.html", conversaciones=datos)

def generar_respuesta_ia(mensaje_usuario):
    try:
        respuesta = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "Actúa como un experto ejecutivo de ventas de CIEA Design Solutions, especializado en diseño y fabricación de soluciones electrónicas, mecánicas y de software. Responde con profesionalismo, claridad y empatía."
                },
                {
                    "role": "user",
                    "content": mensaje_usuario
                }
            ]
        )
        return respuesta.choices[0].message.content.strip()
    except Exception as e:
        print("❌ Error al conectar con ChatGPT:", e)
        return "Error al procesar tu mensaje con IA."

def enviar_respuesta_whatsapp(numero, mensaje):
    url = 'https://graph.facebook.com/v19.0/638096866063629/messages'
    headers = {
        'Authorization': f'Bearer {WHATSAPP_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': numero,
        'type': 'text',
        'text': {'body': mensaje}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print("✅ Mensaje enviado a WhatsApp:", numero)
    except requests.exceptions.RequestException as e:
        print("❌ Error al enviar mensaje a WhatsApp:", e)

def guardar_conversacion(numero, mensaje, respuesta):
    conversacion = {
        "numero": numero,
        "mensaje": mensaje,
        "respuesta": respuesta,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        if os.path.exists(CONVERSACIONES_FILE):
            with open(CONVERSACIONES_FILE, "r", encoding="utf-8") as f:
                datos = json.load(f)
        else:
            datos = []

        datos.append(conversacion)

        with open(CONVERSACIONES_FILE, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)

        print("💾 Conversación guardada.")
    except Exception as e:
        print("❌ Error al guardar la conversación:", e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
