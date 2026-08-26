import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, request, jsonify

from lib.auth import require_secret, err
from lib.odoo import (
    odoo_connect, execute, BRANCH_STOCK_FIELD, MAX_OPCIONES, formatear_opciones,
    texto_opciones, terminos_busqueda, domain_ilike_or, domain_orden_duplicada,
    nombre_orden,
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

        # 3. Dedup: si el contacto ya tiene un borrador con ese mismo producto,
        # devolvemos ese numero en vez de escribir otra orden. GHL puede repetir el
        # trigger (o alguien le da Test Request, que escribe de verdad en Odoo) y
        # sin esta guarda cada disparo deja una orden extra.
        # ponytail: no cubre dos requests simultaneos — ambos pasarian el search
        # antes de que cualquiera cree. Cubre el caso real, que son disparos
        # repetidos con segundos de diferencia; un lock no vale la complejidad.
        previas = execute(
            models, uid, "sale.order", "search",
            domain_orden_duplicada(partner_id, product_id),
            limit=1,
        )
        if previas:
            # Mismos 4 campos que la rama de exito: el nodo webhook de GHL congela
            # el schema de merge tags al crearse y no puede tener campos distintos
            # segun la rama.
            return jsonify({
                "status": "success",
                "pedido_creado": False,
                "numero_orden": nombre_orden(models, uid, previas[0]),
                "mensaje": "Ya existe una orden en borrador con ese producto",
            }), 200

        # 4. Crear sale.order con una linea.
        order_id = execute(
            models, uid, "sale.order", "create",
            {
                "partner_id": partner_id,
                "order_line": [(0, 0, {"product_id": product_id, "product_uom_qty": 1})],
            },
        )

        return jsonify({
            "status": "success",
            "pedido_creado": True,
            "numero_orden": nombre_orden(models, uid, order_id),
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

    # --- Dedup de crear_pedido, con un Odoo falso ---
    # Lo unico que importa verificar: con un borrador previo NO se llama create.
    # nombre_orden vive en lib.odoo y usa el execute de ese modulo, asi que hay que
    # parchar los dos bindings (aqui esta importado por valor).
    from lib import odoo as _odoo

    _llamadas = []
    _borrador_previo = []

    def _fake_execute(models, uid, model, method, *args, **kwargs):
        _llamadas.append((model, method))
        if model == "res.partner":
            return [7]
        if model == "product.product":
            return [42]
        if model == "sale.order" and method == "search":
            return _borrador_previo
        if model == "sale.order" and method == "create":
            return 123
        if model == "sale.order" and method == "read":
            return [{"name": "S00042" if args[0] == [99] else "S00123"}]
        raise AssertionError(f"llamada inesperada: {model}.{method}")

    globals()["execute"] = _fake_execute
    globals()["odoo_connect"] = lambda: (1, None)
    _odoo.execute = _fake_execute
    _pedido = {"telefono": "5215500000000", "producto_interes": "ACCESORIOS / AGUILA"}
    _post = lambda: c.post(
        "/api/ghl/crear_pedido", headers={"X-API-Secret": "s3cr3t"}, json=_pedido
    ).get_json()

    # Ya hay borrador con ese producto: devuelve el existente y no escribe.
    _borrador_previo = [99]
    r = _post()
    assert r["pedido_creado"] is False and r["numero_orden"] == "S00042", r
    assert ("sale.order", "create") not in _llamadas, _llamadas

    # Sin borrador previo: crea normal.
    _llamadas.clear()
    _borrador_previo = []
    r = _post()
    assert r["pedido_creado"] is True and r["numero_orden"] == "S00123", r
    assert ("sale.order", "create") in _llamadas, _llamadas

    # Las dos ramas exponen los mismos campos (GHL congela el schema del webhook).
    assert set(r) == {"status", "pedido_creado", "numero_orden", "mensaje"}, r

    print("ok")
