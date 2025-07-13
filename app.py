from flask import Flask, request, jsonify, render_template, redirect, url_for
import requests, os, mysql.connector
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

VERIFY_TOKEN   = os.getenv('VERIFY_TOKEN')
WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DB_HOST        = os.getenv('DB_HOST')
DB_USER        = os.getenv('DB_USER')
DB_PASSWORD    = os.getenv('DB_PASSWORD')
DB_NAME        = os.getenv('DB_NAME')
MI_NUMERO_BOT  = os.getenv('MI_NUMERO_BOT', '638096866063629')

IA_ESTADO = {'activa': True}
client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
        ssl_ca='/etc/ssl/certs/ca-certificates.crt'
    )

@app.route('/')
def inicio():
    return redirect(url_for('ver_panel_chats'))

@app.route('/webhook', methods=['GET'])
def verificar_token():
    if request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return "Token inválido", 403

@app.route('/webhook', methods=['POST'])
def recibir_mensaje():
    data = request.get_json()
    mensajes = data['entry'][0]['changes'][0]['value'].get('messages')
    if not mensajes: return "OK", 200

    msg = mensajes[0]
    numero = msg['from']
    texto  = msg['text']['body']

    if numero == MI_NUMERO_BOT:
        return "OK", 200

    respuesta = ""
    if IA_ESTADO['activa']:
        respuesta = responder_con_ia(texto)
        enviar_mensaje(numero, respuesta)
    guardar_conversacion(numero, texto, respuesta)
    return "OK", 200

@app.route('/chats')
def ver_panel_chats():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT numero, MAX(timestamp) AS ultima_fecha
        FROM conversaciones
        GROUP BY numero
        ORDER BY ultima_fecha DESC
    """)
    chats = cur.fetchall()
    cur.close(); conn.close()
    return render_template('chats.html',
                           chats=chats,
                           mensajes=None,
                           ia_activa=IA_ESTADO['activa'],
                           numero=None)

@app.route('/chats/<telefono>')
def ver_chat(telefono):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM conversaciones WHERE numero=%s ORDER BY timestamp", (telefono,))
    mensajes = cur.fetchall()
    cur.execute("""
        SELECT numero, MAX(timestamp) AS ultima_fecha
        FROM conversaciones
        GROUP BY numero
        ORDER BY ultima_fecha DESC
    """)
    chats = cur.fetchall()
    cur.close(); conn.close()
    return render_template('chats.html',
                           chats=chats,
                           mensajes=mensajes,
                           ia_activa=IA_ESTADO['activa'],
                           numero=telefono)

@app.route('/toggle_ai', methods=['POST'])
def toggle_ai():
    IA_ESTADO['activa'] = not IA_ESTADO['activa']
    return redirect(url_for('ver_panel_chats'))

# ... responder_con_ia(), enviar_mensaje(), guardar_conversacion() (igual que antes) ...

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',5000)))
