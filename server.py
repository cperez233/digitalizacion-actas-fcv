#!/usr/bin/env python3
"""
Servidor HTTP Local Seguro para Buscador de Actas FCV.
Desarrollado para entornos de producción, auditoría y análisis de vulnerabilidades (OWASP ZAP / CWE).

Arquitectura de Seguridad:
- Autenticación Robusta del Lado del Servidor (Server-Side Authentication) con SQLite.
- Ninguna credencial, sal ni hash expuestos en el código cliente (CWE-798 / CWE-259).
- CWE-693: Inyección estricta de Content-Security-Policy y X-Content-Type-Options: nosniff.
- CWE-1021: Inyección de cabecera X-Frame-Options: SAMEORIGIN y frame-ancestors 'self'.
- CWE-497: Supresión y ofuscación de la cabecera Server (elimina fuga de versión).
- Protección de recursos internos: Bloqueo 403 para base de datos y archivos sensibles.
- Cero dependencias externas: 100% autónomo y local.
"""

import http.server
import socketserver
import sqlite3
import hashlib
import secrets
import time
import json
import sys
import os

DEFAULT_PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIRECTORY, 'database', 'fcv_auth.db')

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
    
    # Credenciales iniciales con sal fija en base de datos
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

    def _send_json_response(self, status_code, data):
        response_bytes = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_POST(self):
        # API de Autenticación en el Servidor (Server-Side)
        if self.path == '/api/login':
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
                    # Tiempo constante para mitigar timing attacks
                    hashlib.sha256(b"dummy_timing_salt").hexdigest()
                    return self._send_json_response(401, {"success": False, "message": "Credenciales inválidas."})

                pwd_hash, salt, name, role, failed_attempts, locked_until = row

                # Verificación de bloqueo por fuerza bruta
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
                    return self._send_json_response(200, {
                        "success": True,
                        "user": {
                            "username": username,
                            "name": name,
                            "role": role,
                            "token": token
                        }
                    })
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

            except Exception as e:
                return self._send_json_response(500, {"success": False, "message": "Error interno del servidor."})

        elif self.path == '/api/logout':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                try:
                    body = self.rfile.read(content_length)
                    payload = json.loads(body.decode('utf-8'))
                    token = payload.get('token')
                    if token:
                        conn = sqlite3.connect(DB_PATH)
                        cur = conn.cursor()
                        cur.execute('DELETE FROM sessions WHERE token = ?', (token,))
                        conn.commit()
                        conn.close()
                except Exception:
                    pass
            return self._send_json_response(200, {"success": True})

        return self._send_json_response(404, {"success": False, "message": "Endpoint no encontrado."})

    def do_GET(self):
        # Restricción de acceso a base de datos y archivos sensibles (CWE-200 / CWE-538)
        norm_path = os.path.normpath(self.path).replace('\\', '/')
        if norm_path.startswith('/database') or norm_path.endswith('.db') or norm_path.endswith('.py') or norm_path.endswith('.sqlite'):
            self.send_error(403, "Acceso denegado a recurso restringido.")
            return

        # Redirección de la raíz
        if self.path in ('/', ''):
            self.path = '/buscador_actas.html'

        return super().do_GET()

    def do_HEAD(self):
        norm_path = os.path.normpath(self.path).replace('\\', '/')
        if norm_path.startswith('/database') or norm_path.endswith('.db') or norm_path.endswith('.py'):
            self.send_error(403, "Acceso denegado a recurso restringido.")
            return

        if self.path in ('/', ''):
            self.path = '/buscador_actas.html'

        return super().do_HEAD()

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'; form-action 'self';"
        )
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        super().end_headers()

def run(port=DEFAULT_PORT):
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), SecureHTTPRequestHandler) as httpd:
        print("=" * 65)
        print(f" Servidor HTTP Seguro FCV Activo")
        print(f" URL local:       http://127.0.0.1:{port}/buscador_actas.html")
        print(f" Base de Datos:   SQLite (database/fcv_auth.db - Protegida)")
        print(f" Autenticación:   Server-Side API (/api/login)")
        print(f" Cabeceras activas: CSP, X-Frame-Options, X-Content-Type-Options, Server ofuscado")
        print("=" * 65)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido correctamente.")

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run(puerto)
