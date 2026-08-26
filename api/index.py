import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import (
    odoo_connect, execute, BRANCH_STOCK_FIELD, MAX_OPCIONES, formatear_opciones,
    texto_opciones, terminos_busqueda, domain_ilike_or,
)

app = Flask(__name__)
app.before_request(require_secret)


@app.route("/api/ghl/consultar_inventario", methods=["POST"])
def consultar_inventario():
    try:
        data = request.get_json(force=True, silent=True) or {}
        producto = (data.get("producto_interes") or "").strip()
        sucursal = (data.get("sucursal_asignada") or "").strip()
        if not producto:
            return err("Falta 'producto_interes'")

        uid, models = odoo_connect()
        stock_field = BRANCH_STOCK_FIELD.get(sucursal, "x_existencia_garza")
        domain = domain_ilike_or("name", terminos_busqueda(producto))
        rows = execute(
            models, uid, "product.product", "search_read",
            domain,
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

        # ponytail: GHL cachea el schema de merge tags del nodo webhook cuando se
        # crea y no expone campos nuevos (opciones_texto nunca aparece en el
        # picker). En vez de pelear el refresh, reusamos nombre_producto_odoo (ya
        # expuesto): en el caso con-stock lleva la lista de hasta 3 opciones con
        # existencia; en cualquier otro caso lleva el nombre unico, para no
        # ensuciar los nodos "Sin stock"/"No existe". El nodo "Responder con
        # stock" en GHL debe renderizar solo {{nombre_producto_odoo}}.
        en_stock = [o for o in opciones if o["stock_disponible"] > 0][:3]
        nombre_field = texto_opciones(en_stock) if en_stock else mejor["nombre"]

        return jsonify({
            "status": "success",
            "producto_encontrado": True,
            "nombre_producto_odoo": nombre_field,
            "precio_real": mejor["precio_real"],
            "stock_disponible": mejor["stock_disponible"],
            "opciones": opciones,
            "opciones_texto": opciones_texto,
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
            domain_ilike_or("name", terminos_busqueda(producto)),
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


# ponytail: self-check de la logica ramificada (guard, sin Odoo).
if __name__ == "__main__":
    from lib import auth as _auth

    c = app.test_client()
    _auth.API_SECRET = None
    assert c.post("/api/ghl/crear_pedido").status_code == 500  # sin configurar
    _auth.API_SECRET = "s3cr3t"
    assert c.post("/api/ghl/crear_pedido").status_code == 401  # sin header
    assert c.post("/api/ghl/crear_pedido", headers={"X-API-Secret": "otro"}).status_code == 401
    assert not _auth.secret_ok(None) and not _auth.secret_ok("")  # ausente != vacio

    ok = c.post("/api/ghl/crear_pedido", headers={"X-API-Secret": "s3cr3t"}, json={})
    assert ok.status_code == 200 and ok.get_json()["mensaje"].startswith("Faltan")
    print("ok")
