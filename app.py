
from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Inicializa base de datos
def init_db():
    with sqlite3.connect("db.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS conversaciones (id INTEGER PRIMARY KEY, telefono TEXT, nombre TEXT, ia_activa BOOLEAN, notas TEXT, ultima_fecha TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS mensajes (id INTEGER PRIMARY KEY, telefono TEXT, contenido TEXT, tipo TEXT, fecha TEXT)")
        conn.commit()

@app.route("/")
def index():
    return redirect(url_for("chats"))

@app.route("/chats")
def chats():
    with sqlite3.connect("db.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversaciones ORDER BY ultima_fecha DESC")
        chats = cursor.fetchall()
    return render_template("chats.html", chats=chats)

@app.route("/chat/<telefono>")
def chat(telefono):
    with sqlite3.connect("db.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mensajes WHERE telefono = ? ORDER BY fecha ASC", (telefono,))
        mensajes = cursor.fetchall()
        cursor.execute("SELECT * FROM conversaciones WHERE telefono = ?", (telefono,))
        chat_info = cursor.fetchone()
    return render_template("chat_view.html", mensajes=mensajes, chat=chat_info)

@app.route("/toggle_ia/<telefono>", methods=["POST"])
def toggle_ia(telefono):
    with sqlite3.connect("db.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ia_activa FROM conversaciones WHERE telefono = ?", (telefono,))
        estado = cursor.fetchone()
        nuevo_estado = not estado[0]
        cursor.execute("UPDATE conversaciones SET ia_activa = ? WHERE telefono = ?", (nuevo_estado, telefono))
        conn.commit()
    return jsonify({"success": True, "ia_activa": nuevo_estado})

@app.route("/guardar_nota/<telefono>", methods=["POST"])
def guardar_nota(telefono):
    nota = request.form.get("nota")
    with sqlite3.connect("db.sqlite3") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE conversaciones SET notas = ? WHERE telefono = ?", (nota, telefono))
        conn.commit()
    return redirect(url_for("chat", telefono=telefono))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
