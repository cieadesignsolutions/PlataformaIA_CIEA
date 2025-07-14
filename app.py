import os
import json
import requests
import mysql.connector
from flask import Flask, request, render_template, redirect, url_for, abort
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

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
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")

# Estado de IA por chat en memoria (clave: numero)
IA_ESTADOS = {}
client     = OpenAI(api_key=OPENAI_API_KEY)

# Archivo de configuración JSON
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "configuracion.json")
# Subpestañas válidas
SUBTABS = ['negocio', 'personalizacion']

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
        ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# ——— Webhook de verificación & recepción ———
@app.route('/webhook', methods=['GET'])
def webhook_verification():
    if request.args.get('hub.verify_token') == VERIFY_TOKEN:
        return request.args.get('hub.challenge')
    return 'Token inválido', 403

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

        msg    = mensajes[0]
        numero = msg['from']
        texto  = msg['text']['body']
        if numero == MI_NUMERO_BOT: 
            return 'OK', 200

        IA_ESTADOS.setdefault(numero, True)
        respuesta = ""
        if IA_ESTADOS[numero]:
            respuesta = responder_con_ia(texto)
            enviar_mensaje(numero, respuesta)
        guardar_conversacion(numero, texto, respuesta)

    except Exception as e:
        app.logger.error(f"🔴 Error en webhook: {e}")
        return 'Error interno', 500

    return 'OK', 200

# ——— Ruta raíz: Home = Dashboard interno ———
@app.route('/')
def inicio():
    return redirect(url_for('home'))

# ——— Dashboard interno (/home) ———
@app.route('/home')
def home():
    period = request.args.get('period', 'week')
    now    = datetime.now()
    start  = now - timedelta(days=30) if period=='month' else now - timedelta(days=7)

    conn   = get_db_connection()
    cursor = conn.cursor()

    # 1) Cantidad de chats diferentes
    cursor.execute(
        "SELECT COUNT(DISTINCT numero) FROM conversaciones WHERE timestamp >= %s",
        (start,)
    )
    chat_counts = cursor.fetchone()[0]

    # 2) Mensajes por chat
    cursor.execute(
        "SELECT numero, COUNT(*) FROM conversaciones WHERE timestamp >= %s GROUP BY numero",
        (start,)
    )
    messages_per_chat = cursor.fetchall()

    # 3) Total de mensajes respondidos
    cursor.execute(
        "SELECT COUNT(*) FROM conversaciones WHERE respuesta<>'' AND timestamp >= %s",
        (start,)
    )
    total_responded = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return render_template(
        'dashboard.html',
        chat_counts=chat_counts,
        messages_per_chat=messages_per_chat,
        total_responded=total_responded,
        period=period
    )

# ——— Chats ———
@app.route('/chats')
def ver_chats():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT numero, MAX(timestamp) AS ultima "
        "FROM conversaciones GROUP BY numero ORDER BY ultima DESC"
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
        "FROM conversaciones GROUP BY numero ORDER BY ultima DESC"
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

@app.route('/send-manual', methods=['POST'])
def enviar_manual():
    numero    = request.form['numero']
    texto     = request.form['texto']
    respuesta = ""
    if IA_ESTADOS.get(numero, True):
        respuesta = responder_con_ia(texto)
        enviar_mensaje(numero, respuesta)
    guardar_conversacion(numero, texto, respuesta)
    return redirect(url_for('ver_chat', numero=numero))

@app.route('/chats/<numero>/eliminar', methods=['POST'])
def eliminar_chat(numero):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversaciones WHERE numero = %s", (numero,))
    conn.commit()
    cursor.close()
    conn.close()
    IA_ESTADOS.pop(numero, None)
    return redirect(url_for('ver_chats'))

# ——— Configuración con subpestañas ———
@app.route('/configuracion/<tab>', methods=['GET','POST'])
def configuracion_tab(tab):
    if tab not in SUBTABS:
        abort(404)

    cfg      = load_config()
    guardado = False

    if request.method == 'POST':
        if tab == 'negocio':
            cfg['negocio'] = {
                'ia_nombre':      request.form['ia_nombre'],
                'negocio_nombre': request.form['negocio_nombre'],
                'descripcion':    request.form['descripcion'],
                'url':            request.form['url'],
                'direccion':      request.form['direccion'],
                'telefono':       request.form['telefono'],
                'correo':         request.form['correo'],
                'que_hace':       request.form['que_hace']
            }
        elif tab == 'personalizacion':
            cfg['personalizacion'] = {
                'tono':     request.form['tono'],
                'lenguaje': request.form['lenguaje']
            }
        save_config(cfg)
        guardado = True

    datos = cfg.get(tab, {})
    return render_template(
        'configuracion.html',
        tabs=SUBTABS,
        active=tab,
        datos=datos,
        guardado=guardado
    )

# ——— Función de IA ahora personalizada desde el JSON ———
def responder_con_ia(mensaje_usuario):
    # Cargo datos de la sección "negocio"
    cfg = load_config().get('negocio', {})
    ia_nombre      = cfg.get('ia_nombre', 'Asistente')
    negocio_nombre = cfg.get('negocio_nombre', '')
    descripcion    = cfg.get('descripcion', '')
    que_hace       = cfg.get('que_hace', '')

    # Armo el prompt de sistema
    system_prompt = f"""
Eres **{ia_nombre}**, asistente virtual de **{negocio_nombre}**.
Descripción del negocio:
{descripcion}

Tus responsabilidades:
{que_hace}

Mantén siempre un tono profesional y conciso.
""".strip()

    try:
        resp = client.chat.completions.create(
            model='gpt-4',
            messages=[
                {'role':'system', 'content': system_prompt},
                {'role':'user',   'content': mensaje_usuario}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"🔴 OpenAI error: {e}")
        return 'Lo siento, hubo un error con la IA.'

def enviar_mensaje(numero, texto):
    url     = f"https://graph.facebook.com/v17.0/{MI_NUMERO_BOT}/messages"
    headers = {'Authorization':f'Bearer {WHATSAPP_TOKEN}','Content-Type':'application/json'}
    payload = {'messaging_product':'whatsapp','to':numero,'type':'text','text':{'body':texto}}
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
        "INSERT INTO conversaciones (numero, mensaje, respuesta) VALUES (%s,%s,%s)",
        (numero, mensaje, respuesta)
    )
    conn.commit()
    cursor.close()
    conn.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5000')))
