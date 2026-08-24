import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import odoo_connect, execute, BRANCH_STOCK_FIELD, MAX_OPCIONES, formatear_opciones

app = Flask(__name__)
app.before_request(require_secret)


# Ruta comodin: bajo el rewrite de vercel.json a veces Vercel entrega a Flask un
# PATH_INFO distinto al solicitado (ver commit que separo este endpoint de
# api/index.py). No importa que path llegue, esta funcion es la unica que Vercel
# invoca para /api/ghl/consultar_inventario, asi que aceptamos cualquier path.
@app.route("/", defaults={"_path": ""}, methods=["POST"])
@app.route("/<path:_path>", methods=["POST"])
def consultar_inventario(_path):
    try:
        data = request.get_json(force=True, silent=True) or {}
        producto = (data.get("producto_interes") or "").strip()
        sucursal = (data.get("sucursal_asignada") or "").strip()
        if not producto:
            return err("Falta 'producto_interes'")

        uid, models = odoo_connect()
        stock_field = BRANCH_STOCK_FIELD.get(sucursal, "x_existencia_garza")
        rows = execute(
            models, uid, "product.product", "search_read",
            [["name", "ilike", producto]],
            fields=["name", "x_precio_real", "x_existencia_garza", "x_existencia_regiomontano"],
            limit=MAX_OPCIONES,
            order=f"{stock_field} desc",
        )

        if not rows:
            return jsonify({
                "status": "success",
                "producto_encontrado": False,
                "nombre_producto_odoo": "",
                "precio_real": 0.0,
                "stock_disponible": 0,
                "opciones": [],
                "opciones_texto": "",
            }), 200

        opciones, opciones_texto = formatear_opciones(rows, stock_field)
        mejor = opciones[0]
        return jsonify({
            "status": "success",
            "producto_encontrado": True,
            "nombre_producto_odoo": mejor["nombre"],
            "precio_real": mejor["precio_real"],
            "stock_disponible": mejor["stock_disponible"],
            "opciones": opciones,
            "opciones_texto": opciones_texto,
        }), 200
    except Exception as e:
        return err(e)


# ponytail: self-check del guard y del formateo de opciones, sin tocar Odoo.
if __name__ == "__main__":
    from lib import auth as _auth

    rows_fake = [
        {"name": "HOMBRE FRIO / VENADO ROSA", "x_precio_real": 4200.0, "x_existencia_garza": 2},
        {"name": "CAMISA MIX / AGUILA", "x_precio_real": 2600.0, "x_existencia_garza": 10},
        {"name": "AGOTADO / SIN STOCK", "x_precio_real": 3000.0, "x_existencia_garza": 0},
    ]
    opciones, texto = formatear_opciones(rows_fake, "x_existencia_garza")
    assert [o["stock_disponible"] for o in opciones] == [10, 2, 0]  # mas stock primero
    assert opciones[0]["nombre"] == "CAMISA MIX / AGUILA"
    assert texto.startswith("1. CAMISA MIX / AGUILA — $2600 (10 disponibles)")
    assert formatear_opciones([], "x_existencia_garza") == ([], "")

    c = app.test_client()
    _auth.API_SECRET = None
    assert c.post("/api/ghl/consultar_inventario").status_code == 500  # sin configurar
    _auth.API_SECRET = "s3cr3t"
    assert c.post("/api/ghl/consultar_inventario").status_code == 401  # sin header
    assert c.post("/cualquier/otro/path", headers={"X-API-Secret": "s3cr3t"}, json={}).status_code == 200
    print("ok")
