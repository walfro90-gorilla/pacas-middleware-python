import os
import xmlrpc.client

from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Config: TODO por env vars en Vercel (nada de secretos en el codigo) ---
# URL no es secreto -> default OK. DB/USER/API_KEY -> obligatorios.
ODOO_URL = os.environ.get("ODOO_URL", "https://odoo.distribuidoragarza.com")
ODOO_DB = os.environ.get("ODOO_DB")
ODOO_USER = os.environ.get("ODOO_USER")
ODOO_API_KEY = os.environ.get("ODOO_API_KEY")

# Sucursal -> campo de existencia en Odoo
BRANCH_STOCK_FIELD = {
    "Jhon": "x_existencia_garza",
    "Eli": "x_existencia_regiomontano",
}


def odoo_connect():
    """Autentica en Odoo y devuelve (uid, models). Lanza si falla."""
    if not (ODOO_DB and ODOO_USER and ODOO_API_KEY):
        raise RuntimeError("Faltan env vars: ODOO_DB / ODOO_USER / ODOO_API_KEY")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
    if not uid:
        raise RuntimeError("Autenticacion Odoo fallida: revisa DB / usuario / API key")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return uid, models


def execute(models, uid, model, method, *args, **kwargs):
    return models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, model, method, list(args), kwargs)


def num(v):
    """Odoo devuelve False para campos vacios. Normaliza a numero."""
    return v if isinstance(v, (int, float)) else 0


def err(mensaje):
    """Error siempre HTTP 200 para que GHL no suspenda el webhook."""
    return jsonify({"status": "error", "mensaje": str(mensaje)}), 200


@app.route("/api/ghl/consultar_inventario", methods=["POST"])
def consultar_inventario():
    try:
        data = request.get_json(force=True, silent=True) or {}
        producto = (data.get("producto_interes") or "").strip()
        sucursal = (data.get("sucursal_asignada") or "").strip()
        if not producto:
            return err("Falta 'producto_interes'")

        uid, models = odoo_connect()
        rows = execute(
            models, uid, "product.product", "search_read",
            [["name", "ilike", producto]],
            fields=["name", "x_precio_real", "x_existencia_garza", "x_existencia_regiomontano"],
            limit=1,
        )

        if not rows:
            return jsonify({
                "status": "success",
                "producto_encontrado": False,
                "nombre_producto_odoo": "",
                "precio_real": 0.0,
                "stock_disponible": 0,
            }), 200

        p = rows[0]
        stock_field = BRANCH_STOCK_FIELD.get(sucursal, "x_existencia_garza")
        return jsonify({
            "status": "success",
            "producto_encontrado": True,
            "nombre_producto_odoo": p.get("name") or "",
            "precio_real": float(num(p.get("x_precio_real"))),
            "stock_disponible": int(num(p.get(stock_field))),
        }), 200
    except Exception as e:
        return err(e)


@app.route("/api/ghl/crear_pedido", methods=["POST"])
def crear_pedido():
    try:
        data = request.get_json(force=True, silent=True) or {}
        telefono = (data.get("telefono") or "").strip()
        nombre = (data.get("nombre_cliente") or "").strip()
        producto = (data.get("producto_interes") or "").strip()
        if not telefono or not producto:
            return err("Faltan 'telefono' y/o 'producto_interes'")

        uid, models = odoo_connect()

        # 1. Partner por phone o mobile; crear si no existe.
        partners = execute(
            models, uid, "res.partner", "search",
            ["|", ["phone", "=", telefono], ["mobile", "=", telefono]],
            limit=1,
        )
        partner_id = partners[0] if partners else execute(
            models, uid, "res.partner", "create",
            {"name": nombre or telefono, "phone": telefono},
        )

        # 2. Producto por nombre.
        prods = execute(
            models, uid, "product.product", "search",
            [["name", "ilike", producto]],
            limit=1,
        )
        if not prods:
            return err(f"Producto no encontrado en Odoo: {producto}")
        product_id = prods[0]

        # 3. Crear sale.order con una linea.
        order_id = execute(
            models, uid, "sale.order", "create",
            {
                "partner_id": partner_id,
                "order_line": [(0, 0, {"product_id": product_id, "product_uom_qty": 1})],
            },
        )
        order = execute(models, uid, "sale.order", "read", [order_id], fields=["name"])
        numero_orden = order[0].get("name") if order else str(order_id)

        return jsonify({
            "status": "success",
            "pedido_creado": True,
            "numero_orden": numero_orden,
            "mensaje": "Orden creada con exito",
        }), 200
    except Exception as e:
        return err(e)


# ponytail: self-check de la unica logica ramificada (mapeo sucursal->stock), sin Odoo.
if __name__ == "__main__":
    rec = {"x_existencia_garza": 15, "x_existencia_regiomontano": 7, "x_precio_real": False}
    assert int(num(rec[BRANCH_STOCK_FIELD["Jhon"]])) == 15
    assert int(num(rec[BRANCH_STOCK_FIELD["Eli"]])) == 7
    assert float(num(rec["x_precio_real"])) == 0.0  # campo vacio -> 0
    print("ok")
