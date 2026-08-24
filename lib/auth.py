import hmac
import os

from flask import jsonify, request

# Secreto compartido con GHL. Unico control de acceso: Vercel Deployment Protection
# esta apagado a proposito para que GHL pueda POSTear sin login.
API_SECRET = os.environ.get("API_SECRET")


def secret_ok(recibido):
    """Comparacion en tiempo constante. encode() porque compare_digest revienta
    con str no-ASCII."""
    return bool(API_SECRET) and hmac.compare_digest(
        (recibido or "").encode(), API_SECRET.encode()
    )


def require_secret():
    """Guard para TODAS las rutas. A diferencia de los errores de negocio, esto si
    devuelve 4xx/5xx: es un fallo de configuracion y tiene que verse en los
    Execution Logs de GHL, no pasar como exito silencioso."""
    if not API_SECRET:
        return jsonify({"status": "error", "mensaje": "Falta env var API_SECRET"}), 500
    if not secret_ok(request.headers.get("X-API-Secret")):
        return jsonify({"status": "error", "mensaje": "No autorizado"}), 401


def err(mensaje):
    """Error siempre HTTP 200 para que GHL no suspenda el webhook."""
    return jsonify({"status": "error", "mensaje": str(mensaje)}), 200
