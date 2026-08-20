import sqlite3
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd
import pytz

app = Flask(__name__)
DB_NAME = "database.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS personas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_completo TEXT NOT NULL,
                matricula TEXT UNIQUE NOT NULL,
                rol TEXT NOT NULL DEFAULT 'Alumno',
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                fotografia TEXT NOT NULL,
                descriptor TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS clases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                maestro TEXT NOT NULL,
                materia TEXT NOT NULL,
                grado TEXT NOT NULL,
                grupo TEXT NOT NULL,
                hora_entrada TEXT NOT NULL,
                hora_salida TEXT NOT NULL,
                tolerancia_minutos INTEGER DEFAULT 10,
                fecha TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS asistencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clase_id INTEGER NOT NULL,
                persona_id INTEGER NOT NULL,
                estatus TEXT NOT NULL,
                foto_verificacion TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                FOREIGN KEY (clase_id) REFERENCES clases (id),
                FOREIGN KEY (persona_id) REFERENCES personas (id)
            )
        ''')
        conn.commit()

init_db()

def get_mexico_time():
    tz = pytz.timezone('America/Mexico_City')
    ahora = datetime.now(tz)
    return ahora.strftime('%Y-%m-%d'), ahora.strftime('%H:%M:%S'), ahora

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/metricas', methods=['GET'])
def obtener_metricas():
    fecha_hoy, _, _ = get_mexico_time()
    with get_db() as conn:
        total_personas = conn.execute('SELECT COUNT(*) FROM personas').fetchone()[0]
        total_clases = conn.execute('SELECT COUNT(*) FROM clases').fetchone()[0]
        asistencias_hoy = conn.execute('SELECT COUNT(*) FROM asistencias WHERE fecha = ?', (fecha_hoy,)).fetchone()[0]
    return jsonify({
        'total_personas': total_personas,
        'total_clases': total_clases,
        'asistencias_hoy': asistencias_hoy
    })

@app.route('/api/registrar_persona', methods=['POST'])
def registrar_persona():
    try:
        data = request.json
        fecha, hora, _ = get_mexico_time()
        with get_db() as conn:
            conn.execute('''
                INSERT INTO personas (nombre_completo, matricula, rol, fecha, hora, fotografia, descriptor)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (data['nombre_completo'], data['matricula'], data.get('rol', 'Alumno'), fecha, hora, data['fotografia'], data['descriptor']))
            conn.commit()
        return jsonify({'status': 'ok', 'message': 'Persona registrada exitosamente.'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'La matrícula ingresada ya se encuentra registrada.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/obtener_personas', methods=['GET'])
def obtener_personas():
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM personas')
            filas = cursor.fetchall()
            
            resultado = []
            for fila in filas:
                d = dict(fila)
                resultado.append({
                    'id': d.get('id', 0),
                    'nombre_completo': d.get('nombre_completo', ''),
                    'matricula': str(d.get('matricula', '')),
                    'rol': d.get('rol', 'Alumno'),
                    'fotografia': d.get('fotografia', ''),
                    'descriptor': d.get('descriptor', '')
                })
            return jsonify(resultado)
    except Exception as e:
        print(f"Error en backend: {e}")
        return jsonify([]), 500

@app.route('/api/eliminar_persona/<int:persona_id>', methods=['DELETE'])
def eliminar_persona(persona_id):
    with get_db() as conn:
        conn.execute('DELETE FROM personas WHERE id = ?', (persona_id,))
        conn.execute('DELETE FROM asistencias WHERE persona_id = ?', (persona_id,))
        conn.commit()
    return jsonify({'status': 'ok', 'message': 'Persona eliminada correctamente.'})

@app.route('/api/registrar_clase', methods=['POST'])
def registrar_clase():
    data = request.json
    fecha, _, _ = get_mexico_time()
    with get_db() as conn:
        conn.execute('''
            INSERT INTO clases (maestro, materia, grado, grupo, hora_entrada, hora_salida, tolerancia_minutos, fecha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (data['maestro'], data['materia'], data['grado'], data['grupo'], data['hora_entrada'], data['hora_salida'], data.get('tolerancia', 10), fecha))
        conn.commit()
    return jsonify({'status': 'ok', 'message': 'Clase registrada exitosamente.'})

@app.route('/api/obtener_clases', methods=['GET'])
def obtener_clases():
    with get_db() as conn:
        clases = conn.execute('SELECT * FROM clases').fetchall()
        return jsonify([dict(c) for c in clases])

@app.route('/api/tomar_asistencia', methods=['POST'])
def tomar_asistencia():
    data = request.json
    fecha_hoy, hora_actual_str, ahora_dt = get_mexico_time()
    clase_id = data['clase_id']
    persona_id = data['persona_id']

    with get_db() as conn:
        duplicado = conn.execute('''
            SELECT id FROM asistencias 
            WHERE clase_id = ? AND persona_id = ? AND fecha = ?
        ''', (clase_id, persona_id, fecha_hoy)).fetchone()

        if duplicado:
            return jsonify({'status': 'warning', 'message': 'Atención: Ya registraste tu asistencia en esta clase el día de hoy.'})

        clase = conn.execute('SELECT hora_entrada, tolerancia_minutos FROM clases WHERE id = ?', (clase_id,)).fetchone()
        
        estatus = "A tiempo"
        if clase and clase['hora_entrada']:
            hora_entrada_dt = datetime.strptime(f"{fecha_hoy} {clase['hora_entrada']}", "%Y-%m-%d %H:%M")
            tz = pytz.timezone('America/Mexico_City')
            hora_entrada_dt = tz.localize(hora_entrada_dt)
            limite_tolerancia = hora_entrada_dt + timedelta(minutes=int(clase['tolerancia_minutos']))

            if ahora_dt > limite_tolerancia:
                estatus = "Retardo"

        conn.execute('''
            INSERT INTO asistencias (clase_id, persona_id, estatus, foto_verificacion, fecha, hora)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (clase_id, persona_id, estatus, data['foto_verificacion'], fecha_hoy, hora_actual_str))
        conn.commit()

    return jsonify({'status': 'ok', 'message': f'Asistencia marcada con éxito. Estatus: [{estatus}]'})

@app.route('/api/exportar_excel', methods=['GET'])
def exportar_excel():
    query = '''
        SELECT 
            c.materia AS "Materia",
            c.maestro AS "Maestro",
            c.grado AS "Grado",
            c.grupo AS "Grupo",
            p.nombre_completo AS "Nombre",
            p.matricula AS "Matrícula",
            p.rol AS "Rol",
            a.estatus AS "Estatus",
            a.fecha AS "Fecha",
            a.hora AS "Hora de Registro"
        FROM asistencias a
        JOIN clases c ON a.clase_id = c.id
        JOIN personas p ON a.persona_id = p.id
        ORDER BY a.fecha DESC, a.hora DESC
    '''
    with get_db() as conn:
        df = pd.read_sql_query(query, conn)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Asistencias')
    output.seek(0)
    return send_file(output, download_name="Respaldo_Asistencias.xlsx", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)