from datetime import datetime
import pytz
import os
import logging
import requests
import mysql.connector
from flask import (
    Flask, request, render_template,
    redirect, url_for, abort, flash
)
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
from decimal import Decimal
tz_mx = pytz.timezone('America/Mexico_City')

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "cualquier-cosa")
app.logger.setLevel(logging.INFO)

# ——— Env vars ———
VERIFY_TOKEN   = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_HOST        = os.getenv("DB_HOST")
DB_USER        = os.getenv("DB_USER")
DB_PASSWORD    = os.getenv("DB_PASSWORD")
DB_NAME        = os.getenv("DB_NAME")
MI_NUMERO_BOT  = os.getenv("MI_NUMERO_BOT")
ALERT_NUMBER   = os.getenv("ALERT_NUMBER", "524491182201")

client = OpenAI(api_key=OPENAI_API_KEY)
IA_ESTADOS = {}

# ——— Función auxiliar para descargar y guardar el avatar ———
def fetch_and_save_avatar(numero):
    """
    Llama a Graph API para obtener profile_pic de WhatsApp y
    lo inserta o actualiza en la tabla contactos.
    """
    url = f"https://graph.facebook.com/v19.0/{numero}"
    params = {'fields': 'profile_pic'}
    headers = {'Authorization': f'Bearer {WHATSAPP_TOKEN}'}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        data = r.json()
        app.logger.info(f"[Avatar] Respuesta de la API para {numero}: {data}")
        pic = data.get('profile_pic')
        app.logger.info(f"[Avatar] URL obtenida para {numero}: {pic}")
    except Exception as e:
        app.logger.error(f"Error obteniendo avatar de {numero}: {e}")
        pic = None

    conn   = get_db_connection()
    cursor = conn.cursor()
    if pic:
        cursor.execute("""
            INSERT INTO contactos (numero_telefono, imagen_url, plataforma)
            VALUES (%s, %s, 'whatsapp')
            ON DUPLICATE KEY UPDATE imagen_url = VALUES(imagen_url);
        """, (numero, pic))
    else:
        cursor.execute("""
            INSERT IGNORE INTO contactos (numero_telefono, imagen_url, plataforma)
            VALUES (%s, '/static/icons/default-avatar.png', 'whatsapp');
        """, (numero,))
    conn.commit()
    cursor.close()
    conn.close()


# ——— Subpestañas válidas ———
SUBTABS = ['negocio', 'personalizacion', 'precios']

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        ssl_ca="/etc/ssl/certs/ca-certificates.crt"
    )

# ——— Configuración en MySQL ———
def load_config():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
      CREATE TABLE IF NOT EXISTS configuracion (
        id INT PRIMARY KEY DEFAULT 1,
        ia_nombre      VARCHAR(100),
        negocio_nombre VARCHAR(100),
        descripcion    TEXT,
        url            VARCHAR(255),
        direccion      VARCHAR(255),
        telefono       VARCHAR(50),
        correo         VARCHAR(100),
        que_hace       TEXT,
        tono           VARCHAR(50),
        lenguaje       VARCHAR(50)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')
    cursor.execute("SELECT * FROM configuracion WHERE id = 1;")
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return {'negocio': {}, 'personalizacion': {}}

    negocio = {
        'ia_nombre':      row['ia_nombre'],
        'negocio_nombre': row['negocio_nombre'],
        'descripcion':    row['descripcion'],
        'url':            row['url'],
        'direccion':      row['direccion'],
        'telefono':       row['telefono'],
        'correo':         row['correo'],
        'que_hace':       row['que_hace'],
    }
    personalizacion = {
        'tono':     row['tono'],
        'lenguaje': row['lenguaje'],
    }
    return {'negocio': negocio, 'personalizacion': personalizacion}

def save_config(cfg_all):
    neg = cfg_all.get('negocio', {})
    per = cfg_all.get('personalizacion', {})

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
      INSERT INTO configuracion
        (id, ia_nombre, negocio_nombre, descripcion, url, direccion,
         telefono, correo, que_hace, tono, lenguaje)
      VALUES
        (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
      ON DUPLICATE KEY UPDATE
        ia_nombre      = VALUES(ia_nombre),
        negocio_nombre = VALUES(negocio_nombre),
        descripcion    = VALUES(descripcion),
        url            = VALUES(url),
        direccion      = VALUES(direccion),
        telefono       = VALUES(telefono),
        correo         = VALUES(correo),
        que_hace       = VALUES(que_hace),
        tono           = VALUES(tono),
        lenguaje       = VALUES(lenguaje);
    ''', (
        neg.get('ia_nombre'),
        neg.get('negocio_nombre'),
        neg.get('descripcion'),
        neg.get('url'),
        neg.get('direccion'),
        neg.get('telefono'),
        neg.get('correo'),
        neg.get('que_hace'),
        per.get('tono'),
        per.get('lenguaje'),
    ))
    conn.commit()
    cursor.close()
    conn.close()

# ——— CRUD y helpers para 'precios' ———
def obtener_todos_los_precios():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
      CREATE TABLE IF NOT EXISTS precios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        servicio VARCHAR(100) NOT NULL,
        descripcion TEXT,
        precio DECIMAL(10,2) NOT NULL,
        moneda CHAR(3) NOT NULL,
        UNIQUE(servicio)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    ''')
    cursor.execute("SELECT * FROM precios ORDER BY servicio;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def obtener_precio_por_id(pid):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM precios WHERE id=%s;", (pid,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def obtener_precio(servicio_nombre: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
      SELECT precio, moneda
        FROM precios
       WHERE LOWER(servicio)=LOWER(%s)
       LIMIT 1;
    """, (servicio_nombre,))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    if res:
        return Decimal(res[0]), res[1]
    return None

# ——— Memoria de conversación ———
def obtener_historial(numero, limite=10):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT mensaje, respuesta FROM conversaciones "
        "WHERE numero=%s ORDER BY timestamp DESC LIMIT %s;",
        (numero, limite)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return list(reversed(rows))

# ——— Función IA con contexto y precios ———
def responder_con_ia(mensaje_usuario, numero):
    cfg            = load_config()
    neg            = cfg['negocio']
    ia_nombre      = neg.get('ia_nombre', 'Asistente')
    negocio_nombre = neg.get('negocio_nombre', '')
    descripcion    = neg.get('descripcion', '')
    que_hace       = neg.get('que_hace', '')

    # Inyecto tabla de precios
    precios = obtener_todos_los_precios()
    lista_precios = "\n".join(
        f"- {p['servicio']}: {p['precio']} {p['moneda']}"
        for p in precios
    )

    system_prompt = f"""
Eres **{ia_nombre}**, asistente virtual de **{negocio_nombre}**.
Descripción del negocio:
{descripcion}

Tus responsabilidades:
{que_hace}

Servicios y tarifas actuales:
{lista_precios}

Mantén siempre un tono profesional y conciso.
""".strip()

    # Agrego historial
    historial = obtener_historial(numero)
    messages_chain = [{'role':'system', 'content': system_prompt}]
    for entry in historial:
        messages_chain.append({'role':'user',      'content': entry['mensaje']})
        messages_chain.append({'role':'assistant', 'content': entry['respuesta']})
    messages_chain.append({'role':'user', 'content': mensaje_usuario})

    try:
        resp = client.chat.completions.create(
            model='gpt-4',
            messages=messages_chain
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"🔴 OpenAI error: {e}")
        return 'Lo siento, hubo un error con la IA.'

# ——— Envío WhatsApp y guardado de conversación ———
def enviar_mensaje(numero, texto):
    PHONE_NUMBER_ID = MI_NUMERO_BOT  # asegúrate de que sea tu Phone Number ID
    url     = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"
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

    app.logger.info("➡️ [WA SEND] URL: %s", url)
    app.logger.info("➡️ [WA SEND] HEADERS: %s", headers)
    app.logger.info("➡️ [WA SEND] PAYLOAD: %s", payload)
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        app.logger.info("⬅️ [WA SEND] STATUS: %s", r.status_code)
        app.logger.info("⬅️ [WA SEND] RESPONSE: %s", r.text)
    except Exception as e:
        app.logger.error("🔴 [WA SEND] EXCEPTION: %s", e)


def guardar_conversacion(numero, mensaje, respuesta):
    conn   = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversaciones (
          id INT AUTO_INCREMENT PRIMARY KEY,
          numero VARCHAR(20),
          mensaje TEXT,
          respuesta TEXT,
          timestamp DATETIME
        ) ENGINE=InnoDB;
    ''')

    # Guardamos en UTC real
    timestamp_utc = datetime.utcnow()

    cursor.execute(
        "INSERT INTO conversaciones (numero, mensaje, respuesta, timestamp) VALUES (%s, %s, %s, %s);",
        (numero, mensaje, respuesta, timestamp_utc)
    )

    conn.commit()
    cursor.close()
    conn.close()

# ——— Detección y alerta ———
def detectar_intervencion_humana(mensaje_usuario, respuesta_ia):
    texto = mensaje_usuario.lower()
    if 'hablar con ' in texto or 'ponme con ' in texto:
        return True
    disparadores = [
        'hablar con persona', 'hablar con un asesor', 'hablar con un agente',
        'quiero un asesor', 'atención humana', 'soporte técnico',
        'es urgente', 'necesito ayuda humana'
    ]
    for frase in disparadores:
        if frase in texto:
            return True
    respuesta = respuesta_ia.lower()
    canalizaciones = [
        'te canalizaré', 'un asesor te contactará', 'te paso con'
    ]
    for tag in canalizaciones:
        if tag in respuesta:
            return True
    return False

def resumen_rafa(numero):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT mensaje, respuesta FROM conversaciones "
        "WHERE numero=%s ORDER BY timestamp DESC LIMIT 10;",
        (numero,)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    partes = []
    for row in reversed(rows):
        partes.append(f"Usuario: {row['mensaje']}")
        if row['respuesta']:
            partes.append(f"IA: {row['respuesta']}")
    conversa = "\n".join(partes)

    system = """
Eres un asistente que crea resúmenes estilo RAFA: muy completos pero concisos, 
capturando los puntos clave en un solo párrafo.
""".strip()
    user_prompt = f"Resumen de la siguiente conversación:\n\n{conversa}"
    try:
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"🔴 Error generando resumen RAFA: {e}")
        return "El cliente solicitó atención personalizada."

def enviar_template_alerta(nombre, numero_cliente, mensaje_clave, resumen):
    def sanitizar(texto):
        clean = texto.replace('\n',' ').replace('\r',' ').replace('\t',' ')
        return ' '.join(clean.split())
    payload = {
        "messaging_product": "whatsapp",
        "to": f"+{ALERT_NUMBER}",
        "type": "template",
        "template": {
            "name": "alerta_intervencion",
            "language": {"code": "es_MX"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type":"text","text":sanitizar(nombre)},
                    {"type":"text","text":sanitizar(numero_cliente)},
                    {"type":"text","text":sanitizar(mensaje_clave)},
                    {"type":"text","text":sanitizar(resumen)}
                ]
            }]
        }
    }
    try:
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{MI_NUMERO_BOT}/messages",
            headers={'Authorization':f'Bearer {WHATSAPP_TOKEN}','Content-Type':'application/json'},
            json=payload
        )
        app.logger.info(f"📤 Alerta enviada: {r.status_code} {r.text}")
    except Exception as e:
        app.logger.error(f"🔴 Error enviando alerta: {e}")

@app.route('/test-alerta')
def test_alerta():
    enviar_template_alerta("Prueba", "524491182201", "Mensaje clave", "Resumen de prueba.")
    return "🚀 Test alerta disparada."

# ——— Webhook ———
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
        
        # --- ACTUALIZA nombre y crea contacto si no existe ---
        contactos = change.get('contacts')
        if contactos and len(contactos) > 0:
            profile_name = contactos[0].get('profile', {}).get('name')
            wa_id = contactos[0].get('wa_id')
            if profile_name and wa_id:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO contactos (numero_telefono, nombre, plataforma)
                    VALUES (%s, %s, 'whatsapp')
                    ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);
                """, (wa_id, profile_name))
                conn.commit()
                cursor.close()
                conn.close()

        msg    = mensajes[0]
        numero = msg['from']
                ### ← Aquí justo, antes de leer el cuerpo del mensaje…
        fetch_and_save_avatar(numero)

        texto  = msg['text']['body']

        if numero == MI_NUMERO_BOT:
            return 'OK', 200

        # precio de ...
        if texto.lower().startswith('precio de '):
            servicio = texto[10:].strip()
            info = obtener_precio(servicio)
            if info:
                precio, moneda = info
                respuesta = f"El precio de *{servicio}* es {precio} {moneda}."
            else:
                respuesta = "No encontré tarifa para *{servicio}*."
            enviar_mensaje(numero, respuesta)
            guardar_conversacion(numero, texto, respuesta)
            return 'OK', 200

        # IA normal
        IA_ESTADOS.setdefault(numero, True)
        respuesta = ""
        if IA_ESTADOS[numero]:
            respuesta = responder_con_ia(texto, numero)
            enviar_mensaje(numero, respuesta)
            if detectar_intervencion_humana(texto, respuesta):
                resumen = resumen_rafa(numero)
                enviar_template_alerta("Sin nombre", numero, texto, resumen)

        guardar_conversacion(numero, texto, respuesta)

    except Exception as e:
        app.logger.error(f"🔴 Error en webhook: {e}")
        return 'Error interno', 500

    return 'OK', 200

# ——— UI ———
@app.route('/')
def inicio():
    return redirect(url_for('home'))

@app.route('/home')
def home():
    period = request.args.get('period', 'week')
    now    = datetime.now()
    start  = now - (timedelta(days=30) if period=='month' else timedelta(days=7))

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(DISTINCT numero) FROM conversaciones WHERE timestamp>= %s;",
        (start,)
    )
    chat_counts = cursor.fetchone()[0]

    cursor.execute(
        "SELECT numero, COUNT(*) FROM conversaciones WHERE timestamp>= %s GROUP BY numero;",
        (start,)
    )
    messages_per_chat = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM conversaciones WHERE respuesta<>'' AND timestamp>= %s;",
        (start,)
    )
    total_responded = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    labels = [num for num,_ in messages_per_chat]
    values = [cnt for _,cnt in messages_per_chat]

    return render_template('dashboard.html',
        chat_counts=chat_counts,
        messages_per_chat=messages_per_chat,
        total_responded=total_responded,
        period=period,
        labels=labels,
        values=values
    )

@app.route('/chats')
def ver_chats():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT
          c.numero,
          MAX(c.timestamp) AS ultima_fecha,
          cont.imagen_url,
          (SELECT mensaje FROM conversaciones cc WHERE cc.numero = c.numero ORDER BY cc.timestamp DESC LIMIT 1) AS ultimo_mensaje
        FROM conversaciones c
        LEFT JOIN contactos cont ON cont.numero_telefono = c.numero
        GROUP BY c.numero
        ORDER BY ultima_fecha DESC;
    """)
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('chats.html',
        chats=chats, mensajes=None,
        selected=None, IA_ESTADOS=IA_ESTADOS
    )

@app.route('/chats/<numero>')
def ver_chat(numero):
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM conversaciones WHERE numero=%s ORDER BY timestamp ASC;",
        (numero,)
    )
    msgs = cursor.fetchall()

    # ✅ Convertir a zona horaria de México (solo si hay timestamp)
    for msg in msgs:
        if msg.get('timestamp'):
            msg['timestamp'] = msg['timestamp'].replace(tzinfo=pytz.UTC).astimezone(tz_mx)

    cursor.execute("""
        SELECT
          c.numero,
          MAX(c.timestamp) AS ultima_fecha,
          cont.imagen_url,
          (SELECT mensaje FROM conversaciones cc WHERE cc.numero = c.numero ORDER BY cc.timestamp DESC LIMIT 1) AS ultimo_mensaje
        FROM conversaciones c
        LEFT JOIN contactos cont ON cont.numero_telefono = c.numero
        GROUP BY c.numero
        ORDER BY ultima_fecha DESC;
    """)
    chats = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('chats.html',
        chats=chats, mensajes=msgs,
        selected=numero, IA_ESTADOS=IA_ESTADOS
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
        respuesta = responder_con_ia(texto, numero)
        enviar_mensaje(numero, respuesta)
        if detectar_intervencion_humana(texto, respuesta):
            resumen = resumen_rafa(numero)
            enviar_template_alerta("Sin nombre", numero, texto, resumen)
    guardar_conversacion(numero, texto, respuesta)
    return redirect(url_for('ver_chat', numero=numero))

@app.route('/chats/<numero>/eliminar', methods=['POST'])
def eliminar_chat(numero):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM conversaciones WHERE numero=%s;", (numero,))
    conn.commit()
    cursor.close()
    conn.close()
    IA_ESTADOS.pop(numero, None)
    return redirect(url_for('ver_chats'))

# ——— Configuración ———
@app.route('/configuracion/<tab>', methods=['GET','POST'])
def configuracion_tab(tab):
    if tab not in ['negocio','personalizacion']:
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
        else:
            cfg['personalizacion'] = {
                'tono':     request.form['tono'],
                'lenguaje': request.form['lenguaje']
            }
        save_config(cfg)
        guardado = True

    datos = cfg.get(tab, {})
    return render_template('configuracion.html',
        tabs=SUBTABS, active=tab,
        datos=datos, guardado=guardado
    )

@app.route('/configuracion/precios', methods=['GET'])
def configuracion_precios():
    precios = obtener_todos_los_precios()
    return render_template('configuracion/precios.html',
        tabs=SUBTABS, active='precios',
        guardado=False,
        precios=precios,
        precio_edit=None
    )

@app.route('/configuracion/precios/editar/<int:pid>', methods=['GET'])
def configuracion_precio_editar(pid):
    precios     = obtener_todos_los_precios()
    precio_edit = obtener_precio_por_id(pid)
    return render_template('configuracion/precios.html',
        tabs=SUBTABS, active='precios',
        guardado=False,
        precios=precios,
        precio_edit=precio_edit
    )

@app.route('/configuracion/precios/guardar', methods=['POST'])
def configuracion_precio_guardar():
    data = request.form.to_dict()
    conn   = get_db_connection()
    cursor = conn.cursor()
    if data.get('id'):
        cursor.execute("""
            UPDATE precios
               SET servicio=%s, descripcion=%s, precio=%s, moneda=%s
             WHERE id=%s;
        """, (
            data['servicio'],
            data.get('descripcion',''),
            data['precio'],
            data['moneda'],
            data['id']
        ))
    else:
        cursor.execute("""
            INSERT INTO precios (servicio, descripcion, precio, moneda)
            VALUES (%s,%s,%s,%s);
        """, (
            data['servicio'],
            data.get('descripcion',''),
            data['precio'],
            data['moneda']
        ))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('configuracion_precios'))

@app.route('/configuracion/precios/borrar/<int:pid>', methods=['POST'])
def configuracion_precio_borrar(pid):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM precios WHERE id=%s;", (pid,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('configuracion_precios'))

@app.route('/kanban')
def ver_kanban():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1) Cargamos las columnas Kanban
    cursor.execute("SELECT * FROM kanban_columnas ORDER BY id;")
    columnas = cursor.fetchall()

    # 2) Cargamos los chats con avatar, canal, última fecha, último mensaje y sin leer
    cursor.execute("""
        SELECT
          cm.numero,
          cm.columna_id,
          c.ultima_fecha,
          c.ultimo_mensaje,
          cont.imagen_url    AS avatar,
          cont.plataforma    AS canal,
          IFNULL(unread.cnt, 0) AS sin_leer
        FROM chat_meta cm

        -- subconsulta para fecha y mensaje más reciente
        JOIN (
          SELECT
            numero,
            MAX(timestamp) AS ultima_fecha,
            (SELECT mensaje
               FROM conversaciones
              WHERE numero = t.numero
              ORDER BY timestamp DESC
              LIMIT 1
            ) AS ultimo_mensaje
          FROM conversaciones t
          GROUP BY numero
        ) AS c
          ON c.numero = cm.numero

        -- link al avatar y plataforma usando tu columna correcta
        LEFT JOIN contactos cont
          ON cont.numero_telefono = cm.numero

        -- contamos cuántos mensajes sin respuesta quedan
        LEFT JOIN (
          SELECT numero, COUNT(*) AS cnt
            FROM conversaciones
           WHERE respuesta IS NULL
           GROUP BY numero
        ) AS unread
          ON unread.numero = cm.numero

        ORDER BY c.ultima_fecha DESC;
    """)
    chats = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('kanban.html',
        columnas=columnas,
        chats=chats
    )

@app.route('/kanban/mover', methods=['POST'])
def kanban_mover():
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
      "UPDATE chat_meta SET columna_id=%s WHERE numero=%s;",
      (data['columna_id'], data['numero'])
    )
    conn.commit(); cursor.close(); conn.close()
    return '', 204

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html')
    
@app.route('/data-deletion')
def data_deletion():
    return render_template('data_deletion.html')
    
@app.route('/terms-of-service')
def terms_of_service():
    return render_template('terms_of_service.html')
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
