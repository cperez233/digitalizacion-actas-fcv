#!/usr/bin/env python3
"""
Servidor HTTP Local Seguro para Buscador de Actas FCV.
Desarrollado para entornos de producción, auditoría y análisis de vulnerabilidades (OWASP Top 10 / CWE).

Arquitectura de Seguridad:
- Broken Access Control (CWE-306): Protección estricta de data.js y PDFs de actas mediante sesiones validadas por Cookie HttpOnly.
- Directory Listing Deshabilitado (CWE-548): Bloqueo 403 para exploración de carpetas.
- Fuga de Archivos Ocultos (CWE-538): Bloqueo total de .git, .env, .htaccess, .gitignore.
- Bypass de Extensiones Mitigado (CWE-22 / CWE-552): Normalización de URLs con urllib.parse contra query strings y encodings.
- Prevención de Fuerza Bruta (CWE-307): Doble capa de rate limiting (por usuario y por IP).
- Anti-Caché para Información Sensible (CWE-524): Directivas Cache-Control: no-store para PDFs y datos de pacientes.
- Content Security Policy Estricto (CWE-693): style-src 'self' (sin 'unsafe-inline'), frame-ancestors 'self'.
- Anti-Clickjacking (CWE-1021): X-Frame-Options: SAMEORIGIN.
- Ofuscación de Servidor (CWE-497): Server: FCV-SecureServer.
- Cero dependencias externas: 100% autónomo con librería estándar de Python.
"""

import http.server
from http.cookies import SimpleCookie
import socketserver
import sqlite3
import hashlib
import secrets
import time
import json
import sys
import os
import urllib.parse

DEFAULT_PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIRECTORY, 'database', 'fcv_auth.db')

SESSION_MAX_INACTIVITY = 1800  # 30 minutos de inactividad máxima

# Rate limiting por IP en memoria para /api/login
IP_LOGIN_ATTEMPTS = {}
IP_RATE_LIMIT = 10  # máximo 10 intentos por minuto por IP
IP_RATE_WINDOW = 60  # segundos

FORBIDDEN_EXTENSIONS = (
    '.py', '.db', '.sqlite', '.sqlite3', '.sh', '.bat', '.ps1',
    '.xlsx', '.xls', '.log', '.bak', '.conf', '.ini', '.env', '.sql', '.tmp'
)

def init_db():
    os.makedirs(os.path.join(DIRECTORY, 'database'), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        failed_attempts INTEGER DEFAULT 0,
        locked_until REAL DEFAULT 0
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        created_at REAL NOT NULL,
        last_activity REAL NOT NULL
    )
    ''')
    
    salt_base = 'FCV_ACTAS_SALT_v1_2026'
    initial_users = [
        ('ciberseguridad', 'Actas2026*FCV', 'Equipo Ciberseguridad', 'Oficial Ciberseguridad'),
        ('admin', 'AdminFCV.2026!', 'Administrador FCV', 'Administrador'),
        ('auditor', 'Auditoria.2026*', 'Auditor de Calidad', 'Auditor')
    ]
    for u, p, n, r in initial_users:
        h = hashlib.sha256(f"{p}:{salt_base}".encode('utf-8')).hexdigest()
        cur.execute('''
            INSERT INTO users (username, password_hash, salt, name, role, failed_attempts, locked_until)
            VALUES (?, ?, ?, ?, ?, 0, 0)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                name=excluded.name,
                role=excluded.role
        ''', (u, h, salt_base, n, r))
        
    conn.commit()
    conn.close()

def check_ip_rate_limit(ip):
    now = time.time()
    history = IP_LOGIN_ATTEMPTS.get(ip, [])
    history = [t for t in history if now - t < IP_RATE_WINDOW]
    if len(history) >= IP_RATE_LIMIT:
        IP_LOGIN_ATTEMPTS[ip] = history
        return False
    history.append(now)
    IP_LOGIN_ATTEMPTS[ip] = history
    return True

def is_valid_session(token):
    if not token or not isinstance(token, str) or len(token) != 48:
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        now = time.time()
        cur.execute('SELECT username, last_activity FROM sessions WHERE token = ?', (token,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False
        username, last_activity = row
        if now - last_activity > SESSION_MAX_INACTIVITY:
            cur.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            conn.close()
            return False
        # Actualizar último instante de actividad para mantener sesión activa
        cur.execute('UPDATE sessions SET last_activity = ? WHERE token = ?', (now, token))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def clean_url_path(raw_path):
    parsed = urllib.parse.urlparse(raw_path)
    unquoted = urllib.parse.unquote(parsed.path)
    norm = os.path.normpath(unquoted).replace('\\', '/')
    if not norm.startswith('/'):
        norm = '/' + norm
    return norm

def is_forbidden_path(clean_path):
    # 1. Componentes ocultos (.*) como .git, .env, .htaccess, .gitignore
    parts = [p for p in clean_path.strip('/').split('/') if p]
    for part in parts:
        if part.startswith('.'):
            return True, "Acceso a archivo o directorio oculto denegado."

    # 2. Directorios internos restringidos
    lower = clean_path.lower()
    if lower.startswith('/database') or lower.startswith('/__pycache__'):
        return True, "Acceso a recurso restringido denegado."

    # 3. Extensiones prohibidas de scripts, bases de datos o código fuente
    ext = os.path.splitext(clean_path)[1].lower()
    if ext in FORBIDDEN_EXTENSIONS:
        return True, "Tipo de archivo restringido."

    return False, ""

def is_protected_resource(clean_path):
    lower = clean_path.lower()
    if lower == '/data.js' or lower.startswith('/actas_organizadas/'):
        return True
    return False

class SecureHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "FCV-SecureServer"
    sys_version = ""

    extensions_map = http.server.SimpleHTTPRequestHandler.extensions_map.copy()
    extensions_map.update({
        '.woff2': 'font/woff2',
        '.woff': 'font/woff',
        '.ttf': 'font/ttf',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
        '.ico': 'image/x-icon',
        '.pdf': 'application/pdf',
        '.css': 'text/css; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8',
        '.html': 'text/html; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.txt': 'text/plain; charset=utf-8'
    })

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def version_string(self):
        return "FCV-SecureServer"

    def list_directory(self, path):
        # Mitigación CWE-548: Deshabilitar listado de directorios
        self.send_error(403, "Listado de directorio deshabilitado por seguridad.")
        return None

    def get_session_token(self):
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookie = SimpleCookie()
            try:
                cookie.load(cookie_header)
                if 'fcv_session' in cookie:
                    return cookie['fcv_session'].value
            except Exception:
                pass
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:].strip()
        return None

    def _send_json_response(self, status_code, data, extra_headers=None):
        response_bytes = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_POST(self):
        clean_path = clean_url_path(self.path)

        if clean_path == '/api/login':
            client_ip = self.client_address[0]
            if not check_ip_rate_limit(client_ip):
                return self._send_json_response(429, {
                    "success": False,
                    "message": "Demasiadas peticiones desde su dirección IP. Espere 1 minuto."
                })

            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0 or content_length > 8192:
                return self._send_json_response(400, {"success": False, "message": "Petición inválida."})

            try:
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode('utf-8'))
                username = (payload.get('username') or '').strip().lower()
                password = (payload.get('password') or '').strip()

                if not username or not password:
                    return self._send_json_response(400, {"success": False, "message": "Campos incompletos."})

                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute('SELECT password_hash, salt, name, role, failed_attempts, locked_until FROM users WHERE username = ?', (username,))
                row = cur.fetchone()

                now = time.time()
                if not row:
                    conn.close()
                    # Tiempo constante para mitigar timing attacks (CWE-208)
                    hashlib.sha256(b"dummy_timing_salt_fcv").hexdigest()
                    return self._send_json_response(401, {"success": False, "message": "Credenciales inválidas."})

                pwd_hash, salt, name, role, failed_attempts, locked_until = row

                # Verificación de bloqueo por fuerza bruta por usuario
                if failed_attempts >= 5 and now < locked_until:
                    remaining = int(locked_until - now)
                    conn.close()
                    return self._send_json_response(429, {
                        "success": False,
                        "locked": True,
                        "message": f"Demasiados intentos fallidos. Intente de nuevo en {remaining} segundos."
                    })

                input_hash = hashlib.sha256(f"{password}:{salt}".encode('utf-8')).hexdigest()
                if secrets.compare_digest(input_hash, pwd_hash):
                    # Éxito: restablecer intentos y emitir token seguro
                    cur.execute('UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE username = ?', (username,))
                    token = secrets.token_hex(24)
                    cur.execute('INSERT OR REPLACE INTO sessions (token, username, created_at, last_activity) VALUES (?, ?, ?, ?)',
                                (token, username, now, now))
                    conn.commit()
                    conn.close()

                    cookie_header = f"fcv_session={token}; Path=/; SameSite=Strict; HttpOnly"
                    return self._send_json_response(200, {
                        "success": True,
                        "user": {
                            "username": username,
                            "name": name,
                            "role": role,
                            "token": token
                        }
                    }, extra_headers={"Set-Cookie": cookie_header})
                else:
                    new_failed = failed_attempts + 1
                    new_lock = now + 30 if new_failed >= 5 else 0
                    cur.execute('UPDATE users SET failed_attempts = ?, locked_until = ? WHERE username = ?', (new_failed, new_lock, username))
                    conn.commit()
                    conn.close()
                    if new_failed >= 5:
                        return self._send_json_response(429, {
                            "success": False,
                            "locked": True,
                            "message": "Demasiados intentos fallidos. Por seguridad, intente en 30 segundos."
                        })
                    return self._send_json_response(401, {"success": False, "message": "Credenciales inválidas."})

            except Exception:
                return self._send_json_response(500, {"success": False, "message": "Error interno del servidor."})

        elif clean_path == '/api/logout':
            token = self.get_session_token()
            if not token:
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length > 0:
                        body = self.rfile.read(content_length)
                        payload = json.loads(body.decode('utf-8'))
                        token = payload.get('token')
                except Exception:
                    pass

            if token:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    cur.execute('DELETE FROM sessions WHERE token = ?', (token,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

            cookie_clear = "fcv_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; SameSite=Strict; HttpOnly"
            return self._send_json_response(200, {"success": True}, extra_headers={"Set-Cookie": cookie_clear})

        return self._send_json_response(404, {"success": False, "message": "Endpoint no encontrado."})

    def do_GET(self):
        clean_path = clean_url_path(self.path)

        # 1. Bloqueo de rutas y archivos prohibidos
        forbidden, motivo = is_forbidden_path(clean_path)
        if forbidden:
            self.send_error(403, motivo)
            return

        # 2. Control de acceso para recursos protegidos (data.js y PDFs de actas)
        if is_protected_resource(clean_path):
            token = self.get_session_token()
            if not is_valid_session(token):
                self.send_error(401, "Acceso no autorizado. Inicie sesión para ver o descargar este documento.")
                return

        # 3. Redirección de la raíz al buscador
        if clean_path in ('/', ''):
            self.path = '/buscador_actas.html'

        return super().do_GET()

    def do_HEAD(self):
        clean_path = clean_url_path(self.path)

        forbidden, motivo = is_forbidden_path(clean_path)
        if forbidden:
            self.send_error(403, motivo)
            return

        if is_protected_resource(clean_path):
            token = self.get_session_token()
            if not is_valid_session(token):
                self.send_error(401, "Acceso no autorizado.")
                return

        if clean_path in ('/', ''):
            self.path = '/buscador_actas.html'

        return super().do_HEAD()

    def end_headers(self):
        clean_path = clean_url_path(self.path)

        # Cabeceras globales de endurecimiento
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'; form-action 'self';"
        )
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

        # Anti-Caché estricto para datos sensibles y PDFs médicos (CWE-524)
        if is_protected_resource(clean_path) or clean_path.startswith('/api/'):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")

        super().end_headers()

def run(port=DEFAULT_PORT):
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), SecureHTTPRequestHandler) as httpd:
        print("=" * 65)
        print(f" Servidor HTTP Blindado FCV Activo")
        print(f" URL local:       http://127.0.0.1:{port}/buscador_actas.html")
        print(f" Base de Datos:   SQLite (database/fcv_auth.db - Protegida)")
        print(f" Autenticación:   Server-Side RBAC (/api/login)")
        print(f" Protección Actas: Sesión requerida para data.js y actas_organizadas/")
        print(f" Directory Listing: Deshabilitado (403 Forbidden)")
        print(f" Archivos Ocultos: Bloqueados (.git, .env, .htaccess, etc.)")
        print("=" * 65)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido correctamente.")

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run(puerto)
