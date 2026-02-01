from flask import Flask, request, jsonify
import mysql.connector
from mysql.connector import Error
import os

app = Flask(__name__)

# Configuración de la Base de Datos
# En producción, usa variables de entorno (os.getenv)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '', 
    'database': 'arteca'
}

def get_db_connection():
    """Crea y retorna una conexión a la base de datos."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"Error conectando a MySQL: {e}")
    return None

def execute_procedure(proc_name, args=()):
    """
    Helper para ejecutar procedimientos almacenados.
    Maneja tanto consultas (SELECT) como acciones (INSERT/DELETE).
    """
    conn = get_db_connection()
    if conn is None:
        return None, "No se pudo conectar a la base de datos"
    
    cursor = conn.cursor(dictionary=True)
    result = None
    error = None
    
    try:
        # callproc retorna los argumentos modificados, no el resultado directo
        cursor.callproc(proc_name, args)
        
        # Iterar sobre los resultados almacenados (para SELECTs dentro de SPs)
        stored_results = list(cursor.stored_results())
        
        if stored_results:
            # Si el SP devuelve datos (ej: sp_User_List), los tomamos
            result = stored_results[0].fetchall()
        else:
            # Si no devuelve datos (ej: sp_User_Create), hacemos commit
            conn.commit()
            result = {"message": "Operación realizada con éxito"}
            
    except Error as e:
        error = str(e)
    finally:
        cursor.close()
        conn.close()
        
    return result, error

def execute_query(query, params=(), commit=False):
    """
    Helper para ejecutar consultas SQL directas (cuando no hay SP).
    Útil para operaciones CRUD simples que no requieren lógica compleja de BD.
    """
    conn = get_db_connection()
    if conn is None:
        return None, "No se pudo conectar a la base de datos"
    
    cursor = conn.cursor(dictionary=True)
    result = None
    error = None
    
    try:
        cursor.execute(query, params)
        if commit:
            conn.commit()
            result = {"affected_rows": cursor.rowcount, "last_id": cursor.lastrowid}
        else:
            result = cursor.fetchall()
    except Error as e:
        error = str(e)
    finally:
        cursor.close()
        conn.close()
        
    return result, error

# ==========================================
# RUTAS: AUTENTICACIÓN
# ==========================================

@app.route('/api/auth/login', methods=['POST'])
def login():
    req = request.json
    email = req.get('email')
    password = req.get('password') # En producción, comparar hash
    
    # Consulta directa para verificar credenciales
    sql = "SELECT id, fullName, role, photoUrl FROM Users WHERE email = %s AND password = %s AND isActive = 1"
    user, error = execute_query(sql, (email, password))
    
    if error: return jsonify({"error": error}), 500
    if not user: return jsonify({"error": "Credenciales inválidas"}), 401
    
    return jsonify({"message": "Login exitoso", "user": user[0]})

# ==========================================
# RUTAS: USUARIOS (Agentes/Admin)
# ==========================================

@app.route('/api/users', methods=['GET'])
def list_users():
    data, error = execute_procedure('sp_User_List')
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/users', methods=['POST'])
def create_user():
    req = request.json
    # Args: p_email, p_password, p_fullName, p_phone, p_role
    args = (req.get('email'), req.get('password'), req.get('fullName'), req.get('phone'), req.get('role', 'AGENTE'))
    data, error = execute_procedure('sp_User_Create', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/users/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def manage_user(id):
    if request.method == 'GET':
        sql = "SELECT id, email, fullName, phone, role, photoUrl, isActive, createdAt FROM Users WHERE id = %s"
        data, error = execute_query(sql, (id,))
        if error: return jsonify({"error": error}), 500
        return jsonify(data[0] if data else {})

    if request.method == 'PUT':
        req = request.json
        # Actualización parcial
        sql = """UPDATE Users SET fullName = %s, phone = %s, role = %s, photoUrl = %s 
                 WHERE id = %s"""
        vals = (req.get('fullName'), req.get('phone'), req.get('role'), req.get('photoUrl'), id)
        data, error = execute_query(sql, vals, commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify({"message": "Usuario actualizado"})

    if request.method == 'DELETE':
        # Soft Delete (Desactivar)
        sql = "UPDATE Users SET isActive = 0 WHERE id = %s"
        data, error = execute_query(sql, (id,), commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify({"message": "Usuario desactivado"})

# ==========================================
# RUTAS: PROPIEDADES (Inventario)
# ==========================================

@app.route('/api/properties', methods=['GET'])
def list_properties():
    # Filtros opcionales: ?status=DISPONIBLE&agentId=1
    status = request.args.get('status') 
    agent_id = request.args.get('agentId')
    
    data, error = execute_procedure('sp_Property_List', (status, agent_id))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/properties', methods=['POST'])
def create_property():
    req = request.json
    # Args: title, description, address, city, price, currency, commissionPct, operation, agentId, ownerId
    args = (
        req.get('title'), req.get('description'), req.get('address'), req.get('city', 'Ilo'),
        req.get('price'), req.get('currency', 'USD'), req.get('commissionPct', 3.00),
        req.get('operation'), req.get('agentId'), req.get('ownerId')
    )
    data, error = execute_procedure('sp_Property_Create', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/properties/<int:id>', methods=['GET', 'PUT'])
def manage_property(id):
    if request.method == 'GET':
        # Obtener propiedad + documentos
        sql_prop = """SELECT p.*, u.fullName as AgentName, c.fullName as OwnerName 
                      FROM Properties p 
                      JOIN Users u ON p.agentId = u.id 
                      JOIN Clients c ON p.ownerId = c.id 
                      WHERE p.id = %s"""
        prop, error = execute_query(sql_prop, (id,))
        if error: return jsonify({"error": error}), 500
        if not prop: return jsonify({"error": "Propiedad no encontrada"}), 404
        
        sql_docs = "SELECT * FROM Documents WHERE propertyId = %s"
        docs, _ = execute_query(sql_docs, (id,))
        
        result = prop[0]
        result['documents'] = docs
        return jsonify(result)

    if request.method == 'PUT':
        req = request.json
        sql = """UPDATE Properties SET title=%s, description=%s, price=%s, status=%s, commissionPct=%s 
                 WHERE id=%s"""
        vals = (req.get('title'), req.get('description'), req.get('price'), req.get('status'), req.get('commissionPct'), id)
        data, error = execute_query(sql, vals, commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify({"message": "Propiedad actualizada"})

@app.route('/api/properties/<int:id>', methods=['DELETE'])
def delete_property(id):
    # Este SP maneja la transacción y borrado en cascada de documentos y ventas
    data, error = execute_procedure('sp_Property_Delete', (id,))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

# ==========================================
# RUTAS: DOCUMENTOS
# ==========================================

@app.route('/api/documents', methods=['POST'])
def add_document():
    req = request.json
    # Args: name, url, type, propertyId
    args = (req.get('name'), req.get('url'), req.get('type'), req.get('propertyId'))
    data, error = execute_procedure('sp_Document_Add', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/documents', methods=['GET'])
def list_documents():
    prop_id = request.args.get('propertyId')
    if not prop_id: return jsonify({"error": "Falta propertyId"}), 400
    sql = "SELECT * FROM Documents WHERE propertyId = %s"
    data, error = execute_query(sql, (prop_id,))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/documents/<int:id>', methods=['DELETE'])
def delete_document(id):
    data, error = execute_query("DELETE FROM Documents WHERE id = %s", (id,), commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify({"message": "Documento eliminado"})

# ==========================================
# RUTAS: VENTAS Y REPORTES (Trigger implícito)
# ==========================================

@app.route('/api/sales', methods=['POST'])
def register_sale():
    # Al insertar aquí, el TRIGGER 'trg_UpdateStatusOnSale' actualizará la propiedad automáticamente
    req = request.json
    args = (
        req.get('propertyId'), req.get('finalPrice'), req.get('totalCommission'),
        req.get('listingAgentId'), req.get('isShared', False), req.get('externalAgency'),
        req.get('sharedPct', 50.00), req.get('sellingAgentId')
    )
    data, error = execute_procedure('sp_Sale_Register', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/reports/sales', methods=['GET'])
def report_sales():
    start = request.args.get('startDate')
    end = request.args.get('endDate')
    if not start or not end:
        return jsonify({"error": "Faltan parámetros startDate y endDate"}), 400
        
    data, error = execute_procedure('sp_Report_Sales', (start, end))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

# ==========================================
# RUTAS: CLIENTES (CRUD Directo - Sin SPs)
# ==========================================

@app.route('/api/clients', methods=['GET'])
def list_clients():
    data, error = execute_query("SELECT * FROM Clients ORDER BY createdAt DESC")
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/clients', methods=['POST'])
def create_client():
    req = request.json
    sql = """INSERT INTO Clients (fullName, dniRuc, phone, email, isOwner, notes) 
             VALUES (%s, %s, %s, %s, %s, %s)"""
    val = (req.get('fullName'), req.get('dniRuc'), req.get('phone'), 
           req.get('email'), req.get('isOwner', 1), req.get('notes'))
    
    data, error = execute_query(sql, val, commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/clients/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def manage_client(id):
    if request.method == 'GET':
        data, error = execute_query("SELECT * FROM Clients WHERE id = %s", (id,))
        if error: return jsonify({"error": error}), 500
        return jsonify(data[0] if data else {})

    if request.method == 'PUT':
        req = request.json
        sql = "UPDATE Clients SET fullName=%s, phone=%s, email=%s, notes=%s WHERE id=%s"
        vals = (req.get('fullName'), req.get('phone'), req.get('email'), req.get('notes'), id)
        data, error = execute_query(sql, vals, commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify({"message": "Cliente actualizado"})

    if request.method == 'DELETE':
        # Verificar si tiene propiedades antes de borrar
        check, _ = execute_query("SELECT id FROM Properties WHERE ownerId = %s", (id,))
        if check: return jsonify({"error": "No se puede borrar: El cliente tiene propiedades asociadas"}), 400
        
        data, error = execute_query("DELETE FROM Clients WHERE id = %s", (id,), commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify({"message": "Cliente eliminado"})

# ==========================================
# RUTAS: PUBLICACIONES INTERNAS (Noticias)
# ==========================================

@app.route('/api/posts', methods=['GET', 'POST'])
def manage_posts():
    if request.method == 'GET':
        sql = """SELECT p.*, u.fullName as AuthorName FROM InternalPosts p 
                 JOIN Users u ON p.authorId = u.id ORDER BY p.createdAt DESC"""
        data, error = execute_query(sql)
        if error: return jsonify({"error": error}), 500
        return jsonify(data)
    
    if request.method == 'POST':
        req = request.json
        sql = "INSERT INTO InternalPosts (title, body, category, authorId) VALUES (%s, %s, %s, %s)"
        vals = (req.get('title'), req.get('body'), req.get('category', 'NOTICIA'), req.get('authorId'))
        data, error = execute_query(sql, vals, commit=True)
        if error: return jsonify({"error": error}), 500
        return jsonify(data), 201

@app.route('/api/posts/<int:id>', methods=['DELETE'])
def delete_post(id):
    data, error = execute_query("DELETE FROM InternalPosts WHERE id = %s", (id,), commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify({"message": "Publicación eliminada"})

# ==========================================
# RUTAS: DASHBOARD (Resumen)
# ==========================================

@app.route('/api/dashboard/summary', methods=['GET'])
def dashboard_summary():
    # Contadores rápidos para la home
    stats = {}
    
    res_prop, _ = execute_query("SELECT status, COUNT(*) as count FROM Properties GROUP BY status")
    stats['properties'] = res_prop
    
    res_users, _ = execute_query("SELECT COUNT(*) as count FROM Users WHERE isActive=1")
    stats['active_agents'] = res_users[0]['count'] if res_users else 0
    
    # Ventas del mes actual
    sql_sales = """SELECT SUM(totalCommission) as total_income, COUNT(*) as sales_count 
                   FROM Sales WHERE MONTH(closedAt) = MONTH(CURRENT_DATE()) 
                   AND YEAR(closedAt) = YEAR(CURRENT_DATE())"""
    res_sales, _ = execute_query(sql_sales)
    stats['monthly_sales'] = res_sales[0] if res_sales else {}
    
    return jsonify(stats)

if __name__ == '__main__':
    app.run(debug=True, port=5000)