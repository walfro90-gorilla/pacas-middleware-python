import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import odoo_connect, execute

app = Flask(__name__)
app.before_request(require_secret)


# Ruta comodin: ver comentario equivalente en api/ghl/consultar_inventario.py.
@app.route("/", defaults={"_path": ""}, methods=["POST"])
@app.route("/<path:_path>", methods=["POST"])
def crear_pedido(_path):
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


# ponytail: self-check del guard, sin tocar Odoo.
if __name__ == "__main__":
    from lib import auth as _auth

    c = app.test_client()
    _auth.API_SECRET = None
    assert c.post("/api/ghl/crear_pedido").status_code == 500  # sin configurar
    _auth.API_SECRET = "s3cr3t"
    assert c.post("/api/ghl/crear_pedido").status_code == 401  # sin header
    assert c.post("/api/ghl/crear_pedido", headers={"X-API-Secret": "otro"}).status_code == 401
    assert not _auth.secret_ok(None) and not _auth.secret_ok("")  # ausente != vacio

    ok = c.post("/cualquier/otro/path", headers={"X-API-Secret": "s3cr3t"}, json={})
    assert ok.status_code == 200 and ok.get_json()["mensaje"].startswith("Faltan")
    print("ok")
