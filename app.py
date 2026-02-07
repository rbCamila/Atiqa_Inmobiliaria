from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import mysql.connector
from mysql.connector import Error
import os
from flasgger import Swagger
import datetime

app = Flask(__name__)
app.secret_key = 'SUPER_SECRET_KEY_CAMBIAR_EN_PROD' # Necesario para sesiones
swagger = Swagger(app, template={
    "info": {
        "title": "API Inmobiliaria Atiqa",
        "description": "API para gestión de propiedades, ventas y agentes.",
        "version": "1.0.0"
    }
})

# Configuración de la Base de Datos
# En producción, usa variables de entorno (os.getenv)
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root', 
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
# RUTAS DE INTERFAZ DE USUARIO (FRONTEND)
# ==========================================

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard_view'))
    return redirect(url_for('login_view'))

@app.route('/login', methods=['GET', 'POST'])
def login_view():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        sql = "SELECT id, fullName, role, photoUrl FROM Users WHERE email = %s AND password = %s AND isActive = 1"
        user, error = execute_query(sql, (email, password))
        
        if user:
            session['user'] = user[0]
            return redirect(url_for('dashboard_view'))
        else:
            flash('Credenciales inválidas')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_view'))

@app.route('/dashboard')
def dashboard_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    
    # Reutilizamos la lógica del endpoint de dashboard
    # Nota: En un entorno real, refactorizaríamos la lógica a una función separada
    # para no llamar a la ruta API, pero aquí duplicaré la lógica de consulta por simplicidad.
    stats = {}
    res_prop, _ = execute_query("SELECT status, COUNT(*) as count FROM Properties GROUP BY status")
    stats['inventory_status'] = res_prop or []
    res_users, _ = execute_query("SELECT COUNT(*) as count FROM Users WHERE isActive=1")
    stats['active_agents'] = res_users[0]['count'] if res_users else 0
    sql_sales = """SELECT SUM(totalCommission) as total_income, COUNT(*) as sales_count 
                   FROM Sales WHERE MONTH(closedAt) = MONTH(CURRENT_DATE()) 
                   AND YEAR(closedAt) = YEAR(CURRENT_DATE()) AND status = 'APROBADO'"""
    res_sales, _ = execute_query(sql_sales)
    stats['monthly_sales'] = res_sales[0] if res_sales else {}
    res_pending, _ = execute_query("SELECT COUNT(*) as count FROM Sales WHERE status = 'PENDIENTE'")
    stats['pending_approvals'] = res_pending[0]['count'] if res_pending else 0
    
    return render_template('dashboard.html', stats=stats)

@app.route('/ui/properties')
def properties_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    status = request.args.get('status')
    
    # Llamada al SP con datos de sesión
    data, error = execute_procedure('sp_Property_List', (status, None, session['user']['role'], session['user']['id']))
    
    if error:
        flash(f"Error al cargar propiedades: {error}", 'error')
        data = []
        
    return render_template('properties.html', properties=data or [])

@app.route('/ui/properties/new', methods=['GET', 'POST'])
def property_create_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    
    if request.method == 'POST':
        f = request.form
        args = (
            f.get('title'), f.get('description'), f.get('address'), 'Ilo',
            f.get('price'), f.get('currency'), f.get('commissionPct'),
            f.get('operation'), session['user']['id'], f.get('ownerId'), f.get('exclusive', 0)
        )
        _, error = execute_procedure('sp_Property_Create', args)
        if error:
            flash(f"Error: {error}", 'error')
        else:
            flash("Propiedad creada exitosamente", 'success')
            return redirect(url_for('properties_view'))
            
    return render_template('property_form.html')

@app.route('/ui/properties/<int:id>')
def property_detail_view(id):
    if 'user' not in session: return redirect(url_for('login_view'))
    # Reutilizar lógica de get property
    sql_prop = """SELECT p.*, u.fullName as AgentName, c.fullName as OwnerName 
                  FROM Properties p 
                  JOIN Users u ON p.agentId = u.id 
                  JOIN Clients c ON p.ownerId = c.id 
                  WHERE p.id = %s"""
    prop, _ = execute_query(sql_prop, (id,))
    if not prop: return "Propiedad no encontrada", 404
    return render_template('property_form.html', property=prop[0]) # Podrías hacer un template de detalle solo lectura

@app.route('/ui/clients', methods=['GET'])
def clients_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    data, error = execute_query("SELECT * FROM Clients ORDER BY createdAt DESC")
    
    if error:
        flash(f"Error al cargar clientes: {error}", 'error')
        data = []
        
    return render_template('clients.html', clients=data or [])

@app.route('/ui/clients/create', methods=['POST'])
def clients_create_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    f = request.form
    sql = "INSERT INTO Clients (fullName, dniRuc, phone, email, isOwner) VALUES (%s, %s, %s, %s, 1)"
    execute_query(sql, (f.get('fullName'), f.get('dniRuc'), f.get('phone'), f.get('email')), commit=True)
    return redirect(url_for('clients_view'))

@app.route('/ui/users')
def users_view():
    if 'user' not in session or session['user']['role'] != 'ADMIN': return redirect(url_for('dashboard_view'))
    data, error = execute_procedure('sp_User_List')
    
    if error:
        flash(f"Error al cargar usuarios: {error}", 'error')
        data = []
        
    return render_template('users.html', users=data or [])

@app.route('/ui/sales')
def sales_view():
    if 'user' not in session: return redirect(url_for('login_view'))
    start = request.args.get('startDate', datetime.date.today().replace(day=1))
    end = request.args.get('endDate', datetime.date.today())
    
    data, error = execute_procedure('sp_Report_Sales', (start, end))
    
    if error:
        flash(f"Error al cargar reporte de ventas: {error}", 'error')
        data = []
        
    return render_template('sales.html', sales=data or [])


# ==========================================
# RUTAS: AUTENTICACIÓN
# ==========================================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """
    Inicia sesión de usuario (Agente o Admin)
    ---
    tags:
      - Auth
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            email: {type: string, example: "admin@sistema.com"}
            password: {type: string, example: "123456"}
    responses:
      200:
        description: Login exitoso, retorna usuario
    """
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
    """
    Listar todos los usuarios activos
    ---
    tags:
      - Users
    responses:
      200:
        description: Lista de usuarios
    """
    data, error = execute_procedure('sp_User_List')
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/users', methods=['POST'])
def create_user():
    """
    Crear un nuevo usuario
    ---
    tags:
      - Users
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [email, password, fullName]
          properties:
            email: {type: string}
            password: {type: string}
            fullName: {type: string}
            phone: {type: string}
            role: {type: string, enum: ['ADMIN', 'AGENTE']}
    responses:
      201:
        description: Usuario creado
    """
    req = request.json
    # Args: p_email, p_password, p_fullName, p_phone, p_role
    args = (req.get('email'), req.get('password'), req.get('fullName'), req.get('phone'), req.get('role', 'AGENTE'))
    data, error = execute_procedure('sp_User_Create', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/users/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def manage_user(id):
    """
    Gestionar un usuario específico (Ver, Editar, Eliminar)
    ---
    tags:
      - Users
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    get:
      summary: Obtener detalles de un usuario
      responses:
        200: {description: Objeto usuario}
    put:
      summary: Actualizar datos de usuario
      parameters:
        - name: body
          in: body
          schema:
            type: object
            properties:
              fullName: {type: string}
              phone: {type: string}
              role: {type: string}
              photoUrl: {type: string}
      responses:
        200: {description: Usuario actualizado}
    delete:
      summary: Desactivar usuario (Soft Delete)
      responses:
        200: {description: Usuario desactivado}
    """
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
    """
    Listar propiedades con filtros
    ---
    tags:
      - Properties
    parameters:
      - name: status
        in: query
        type: string
        enum: ['DISPONIBLE', 'RESERVADO', 'VENDIDO', 'ALQUILADO']
      - name: agentId
        in: query
        type: integer
    responses:
      200:
        description: Lista de propiedades
    """
    # Filtros opcionales: ?status=DISPONIBLE&agentId=1
    status = request.args.get('status') 
    agent_id = request.args.get('agentId')
    # Simulamos obtener el usuario actual de la sesión/token (Hardcodeado para ejemplo)
    current_user_role = request.headers.get('X-Role', 'AGENTE') 
    current_user_id = request.headers.get('X-User-Id', 0)
    
    data, error = execute_procedure('sp_Property_List', (status, agent_id, current_user_role, current_user_id))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/properties', methods=['POST'])
def create_property():
    """
    Crear una nueva propiedad
    ---
    tags:
      - Properties
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            title: {type: string}
            description: {type: string}
            address: {type: string}
            city: {type: string}
            price: {type: number}
            operation: {type: string, enum: ['VENTA', 'ALQUILER']}
            agentId: {type: integer}
            ownerId: {type: integer}
    responses:
      201:
        description: Propiedad creada
    """
    req = request.json
    # Args: title, description, address, city, price, currency, commissionPct, operation, agentId, ownerId, exclusive
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
    """
    Gestionar una propiedad específica
    ---
    tags:
      - Properties
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    get:
      summary: Obtener detalle de propiedad y documentos
      responses:
        200: {description: Detalle de propiedad}
    put:
      summary: Actualizar propiedad
      parameters:
        - name: body
          in: body
          schema:
            type: object
            properties:
              title: {type: string}
              price: {type: number}
              status: {type: string}
      responses:
        200: {description: Propiedad actualizada}
    """
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
    """
    Eliminar propiedad (Cascada: Docs y Ventas)
    ---
    tags:
      - Properties
    parameters:
      - name: id
        in: path
        type: integer
    responses:
      200: {description: Propiedad eliminada}
    """
    # Este SP maneja la transacción y borrado en cascada de documentos y ventas
    data, error = execute_procedure('sp_Property_Delete', (id,))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

# ==========================================
# RUTAS: GENERACIÓN DE CONTRATOS (Nuevo)
# ==========================================

@app.route('/api/properties/<int:id>/contract-data', methods=['GET'])
def get_contract_data(id):
    """
    Obtener datos para generar contrato PDF
    ---
    tags:
      - Properties
    parameters:
      - name: id
        in: path
        type: integer
    responses:
      200: {description: Datos del contrato}
    """
    """
    Obtiene los datos necesarios para llenar el PDF del contrato.
    Solo accesible por ADMIN (validar en frontend/middleware).
    """
    sql = """SELECT p.address, p.price, p.commissionPct, p.exclusive,
             c.fullName as OwnerName, c.dniRuc as OwnerDNI,
             u.fullName as AgentName
             FROM Properties p
             JOIN Clients c ON p.ownerId = c.id
             JOIN Users u ON p.agentId = u.id
             WHERE p.id = %s"""
    data, error = execute_query(sql, (id,))
    if error: return jsonify({"error": error}), 500
    if not data: return jsonify({"error": "Propiedad no encontrada"}), 404
    
    # Aquí se retornaría la estructura para llenar el PDF
    contract_info = data[0]
    contract_info['contract_text'] = f"CONTRATO DE CORRETAJE {'EXCLUSIVO' if contract_info['exclusive'] else ''}..."
    
    return jsonify(contract_info)

# ==========================================
# RUTAS: DOCUMENTOS
# ==========================================

@app.route('/api/documents', methods=['POST'])
def add_document():
    """
    Subir/Registrar un documento
    ---
    tags:
      - Documents
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            name: {type: string}
            url: {type: string}
            type: {type: string}
            propertyId: {type: integer}
    responses:
      201: {description: Documento registrado}
    """
    req = request.json
    # Args: name, url, type, propertyId
    args = (req.get('name'), req.get('url'), req.get('type'), req.get('propertyId'))
    data, error = execute_procedure('sp_Document_Add', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/documents', methods=['GET'])
def list_documents():
    """
    Listar documentos de una propiedad
    ---
    tags:
      - Documents
    parameters:
      - name: propertyId
        in: query
        type: integer
    responses:
      200: {description: Lista de documentos}
    """
    prop_id = request.args.get('propertyId')
    if not prop_id: return jsonify({"error": "Falta propertyId"}), 400
    sql = "SELECT * FROM Documents WHERE propertyId = %s"
    data, error = execute_query(sql, (prop_id,))
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/documents/<int:id>', methods=['DELETE'])
def delete_document(id):
    """
    Eliminar un documento
    ---
    tags:
      - Documents
    parameters:
      - name: id
        in: path
        type: integer
    responses:
      200: {description: Documento eliminado}
    """
    data, error = execute_query("DELETE FROM Documents WHERE id = %s", (id,), commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify({"message": "Documento eliminado"})

# ==========================================
# RUTAS: VENTAS Y CIERRES (Flujo de Aprobación)
# ==========================================

@app.route('/api/sales', methods=['POST'])
def register_sale():
    """
    Registrar un cierre de venta (Estado PENDIENTE)
    ---
    tags:
      - Sales
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            propertyId: {type: integer}
            finalPrice: {type: number}
            totalCommission: {type: number}
            listingAgentId: {type: integer}
    responses:
      201: {description: Venta registrada}
    """
    # El agente registra el cierre. Entra como PENDIENTE.
    req = request.json
    args = (
        req.get('propertyId'), req.get('finalPrice'), req.get('totalCommission'),
        req.get('listingAgentId'), req.get('isShared', False), req.get('externalAgency'),
        req.get('sharedPct', 50.00), req.get('sellingAgentId'),
        'PENDIENTE' # Estado inicial
    )
    data, error = execute_procedure('sp_Sale_Register', args)
    if error: return jsonify({"error": error}), 500
    return jsonify(data), 201

@app.route('/api/sales/<int:id>/approve', methods=['PUT'])
def approve_sale(id):
    """
    Aprobar un cierre de venta (Admin)
    ---
    tags:
      - Sales
    parameters:
      - name: id
        in: path
        type: integer
    responses:
      200: {description: Venta aprobada}
    """
    # Solo ADMIN. Cambia estado a APROBADO. El Trigger actualizará la propiedad a VENDIDO.
    sql = "UPDATE Sales SET status = 'APROBADO' WHERE id = %s"
    data, error = execute_query(sql, (id,), commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify({"message": "Cierre aprobado y propiedad actualizada"})

@app.route('/api/reports/sales', methods=['GET'])
def report_sales():
    """
    Reporte de ventas por rango de fechas
    ---
    tags:
      - Sales
    parameters:
      - name: startDate
        in: query
        type: string
      - name: endDate
        in: query
        type: string
    responses:
      200: {description: Reporte de ventas}
    """
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
    """
    Listar todos los clientes
    ---
    tags:
      - Clients
    responses:
      200: {description: Lista de clientes}
    """
    data, error = execute_query("SELECT * FROM Clients ORDER BY createdAt DESC")
    if error: return jsonify({"error": error}), 500
    return jsonify(data)

@app.route('/api/clients', methods=['POST'])
def create_client():
    """
    Crear un nuevo cliente
    ---
    tags:
      - Clients
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            fullName: {type: string}
            phone: {type: string}
            isOwner: {type: boolean}
    responses:
      201: {description: Cliente creado}
    """
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
    """
    Gestionar cliente (Ver, Editar, Eliminar)
    ---
    tags:
      - Clients
    parameters:
      - name: id
        in: path
        type: integer
    get:
      summary: Obtener cliente
      responses:
        200: {description: Datos del cliente}
    put:
      summary: Actualizar cliente
      parameters:
        - name: body
          in: body
          schema:
            type: object
            properties:
              fullName: {type: string}
              phone: {type: string}
              email: {type: string}
      responses:
        200: {description: Cliente actualizado}
    delete:
      summary: Eliminar cliente
      responses:
        200: {description: Cliente eliminado}
    """
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
# RUTAS: REDES SOCIALES (Auto-Publicación Mock)
# ==========================================

@app.route('/api/social/publish', methods=['POST'])
def publish_social():
    """
    Publicar propiedad en redes sociales (Mock)
    ---
    tags:
      - Social
    parameters:
      - name: body
        in: body
        schema:
          type: object
          properties:
            propertyId: {type: integer}
            networks: {type: array, items: {type: string}}
    """
    req = request.json
    prop_id = req.get('propertyId')
    networks = req.get('networks') # ['FACEBOOK', 'INSTAGRAM']
    
    # Aquí iría la lógica de conexión con APIs de Meta/TikTok
    # Por ahora, registramos el log en la BD
    for net in networks:
        sql = "INSERT INTO SocialMediaLogs (propertyId, network, postUrl) VALUES (%s, %s, %s)"
        # URL simulada
        execute_query(sql, (prop_id, net, f"https://{net.lower()}.com/post/mock123"), commit=True)
        
    return jsonify({"message": "Publicado exitosamente en redes seleccionadas"})

# ==========================================
# RUTAS: PUBLICACIONES INTERNAS (Noticias)
# ==========================================

@app.route('/api/posts', methods=['GET', 'POST'])
def manage_posts():
    """
    Gestionar publicaciones internas (Muro)
    ---
    tags:
      - Posts
    get:
      summary: Listar noticias internas
      responses:
        200: {description: Lista de posts}
    post:
      summary: Crear noticia interna
      parameters:
        - name: body
          in: body
          schema:
            type: object
            properties:
              title: {type: string}
              body: {type: string}
              authorId: {type: integer}
    """
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
    """
    Eliminar noticia interna
    ---
    tags:
      - Posts
    parameters:
      - name: id
        in: path
        type: integer
    responses:
      200: {description: Post eliminado}
    """
    data, error = execute_query("DELETE FROM InternalPosts WHERE id = %s", (id,), commit=True)
    if error: return jsonify({"error": error}), 500
    return jsonify({"message": "Publicación eliminada"})

# ==========================================
# RUTAS: DASHBOARD (Resumen)
# ==========================================

@app.route('/api/dashboard/summary', methods=['GET'])
def dashboard_summary():
    """
    Resumen estadístico para el Dashboard
    ---
    tags:
      - Dashboard
    responses:
      200: {description: Estadísticas generales}
    """
    # Contadores rápidos para la home
    stats = {}
    
    res_prop, _ = execute_query("SELECT status, COUNT(*) as count FROM Properties GROUP BY status")
    stats['inventory_status'] = res_prop
    
    res_users, _ = execute_query("SELECT COUNT(*) as count FROM Users WHERE isActive=1")
    stats['active_agents'] = res_users[0]['count'] if res_users else 0
    
    # Ventas del mes actual (Solo APROBADAS)
    sql_sales = """SELECT SUM(totalCommission) as total_income, COUNT(*) as sales_count 
                   FROM Sales WHERE MONTH(closedAt) = MONTH(CURRENT_DATE()) 
                   AND YEAR(closedAt) = YEAR(CURRENT_DATE())
                   AND status = 'APROBADO'"""
    res_sales, _ = execute_query(sql_sales)
    stats['monthly_sales'] = res_sales[0] if res_sales else {}
    
    # Cierres pendientes de aprobación
    res_pending, _ = execute_query("SELECT COUNT(*) as count FROM Sales WHERE status = 'PENDIENTE'")
    stats['pending_approvals'] = res_pending[0]['count'] if res_pending else 0
    
    return jsonify(stats)

if __name__ == '__main__':
    app.run(debug=True, port=5000)