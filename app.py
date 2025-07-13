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
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")  # ej. "524491182201"

# Estado de IA por chat en memoria (clave: numero)
IA_ESTADOS = {}

client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# ——— Webhook de verificación ———
@app.route('/webhook', methods=['GET'])
def webhook_verification():
    token     = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == VERIFY_TOKEN:
        return challenge
    return 'Token inválido', 403

# ——— Recepción de mensajes ———
@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    payload = request.get_json()
    app.logger.info(f"📥 Payload: {payload}")
    try:
        entry    = payload['entry'][0]
        change   = entry['changes'][0]['value']
        mensajes = change.get('messages')
        if not mensajes:
            return 'OK', 200

        msg       = mensajes[0]
        numero    = msg['from']
        texto_usr = msg['text']['body']

        if numero == MI_NUMERO_BOT:
            return 'OK', 200

        # define default ON
        if numero not in IA_ESTADOS:
            IA_ESTADOS[numero] = True

        respuesta = ''
        if IA_ESTADOS[numero]:
            respuesta = responder_con_ia(texto_usr)
            enviar_mensaje(numero, respuesta)

        guardar_conversacion(numero, texto_usr, respuesta)

    except Exception as e:
        app.logger.error(f"🔴 Error en webhook: {e}")
        return 'Error interno', 500

    return 'OK', 200

# ——— Panel de chats ———
@app.route('/')
def inicio():
    return redirect(url_for('ver_chats'))

@app.route('/chats')
def ver_chats():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT numero, MAX(timestamp) AS ultima "
        "FROM conversaciones GROUP BY numero "
        "ORDER BY ultima DESC"
    )
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'chats.html',
        chats=chats,
        mensajes=None,
        selected=None,
        IA_ESTADOS=IA_ESTADOS
    )

@app.route('/chats/<numero>')
def ver_chat(numero):
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM conversaciones WHERE numero=%s ORDER BY timestamp ASC",
        (numero,)
    )
    msgs = cursor.fetchall()
    cursor.execute(
        "SELECT numero, MAX(timestamp) AS ultima "
        "FROM conversaciones GROUP BY numero "
        "ORDER BY ultima DESC"
    )
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template(
        'chats.html',
        chats=chats,
        mensajes=msgs,
        selected=numero,
        IA_ESTADOS=IA_ESTADOS
    )

@app.route('/toggle_ai/<numero>', methods=['POST'])
def toggle_ai(numero):
    IA_ESTADOS[numero] = not IA_ESTADOS.get(numero, True)
    return redirect(url_for('ver_chat', numero=numero))

# ——— Envío manual desde el formulario ———
@app.route('/send-manual', methods=['POST'])
def enviar_manual():
    numero    = request.form.get('numero')
    texto     = request.form.get('texto')
    respuesta = ''

    if IA_ESTADOS.get(numero, True):
        respuesta = responder_con_ia(texto)
        enviar_mensaje(numero, respuesta)

    guardar_conversacion(numero, texto, respuesta)
    return redirect(url_for('ver_chat', numero=numero))

# ——— Eliminar un chat completo ———
@app.route('/chats/<numero>/eliminar', methods=['POST'])
def eliminar_chat(numero):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM conversaciones WHERE numero = %s",
        (numero,)
    )
    conn.commit()
    cursor.close()
    conn.close()
    IA_ESTADOS.pop(numero, None)
    return redirect(url_for('ver_chats'))

# ——— Funciones utilitarias ———
def responder_con_ia(mensaje):
    try:
        resp = client.chat.completions.create(
            model='gpt-4',
            messages=[
                {'role':'system','content':'Eres un asistente útil para WhatsApp.'},
                {'role':'user','content':mensaje}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"🔴 OpenAI error: {e}")
        return 'Lo siento, hubo un error con la IA.'

def enviar_mensaje(numero, texto):
    url = f"https://graph.facebook.com/v17.0/{MI_NUMERO_BOT}/messages"
    headers = {
        'Authorization': f'Bearer {WHATSAPP_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'messaging_product': 'whatsapp',
        'to': numero,
        'type': 'text',
        'text': {'body': texto}
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        app.logger.info(f"📤 WhatsApp API: {r.status_code} {r.text}")
    except Exception as e:
        app.logger.error(f"🔴 Error enviando WhatsApp: {e}")

def guardar_conversacion(numero, mensaje, respuesta):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversaciones (
          id INT AUTO_INCREMENT PRIMARY KEY,
          numero VARCHAR(20),
          mensaje TEXT,
          respuesta TEXT,
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
    ''')
    cursor.execute(
        "INSERT INTO conversaciones (numero, mensaje, respuesta) VALUES (%s, %s, %s)",
        (numero, mensaje, respuesta)
    )
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')))
