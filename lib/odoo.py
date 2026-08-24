import os
import xmlrpc.client

# --- Config: TODO por env vars en Vercel (nada de secretos en el codigo) ---
# Las cuatro son obligatorias. ODOO_URL sin default a proposito: un default se queda
# viejo cuando cambia la instancia y termina apuntando en silencio al servidor
# equivocado. Mejor reventar.
ODOO_URL = os.environ.get("ODOO_URL")
ODOO_DB = os.environ.get("ODOO_DB")
ODOO_USER = os.environ.get("ODOO_USER")
ODOO_API_KEY = os.environ.get("ODOO_API_KEY")

# Sucursal -> campo de existencia en Odoo
BRANCH_STOCK_FIELD = {
    "Jhon": "x_existencia_garza",
    "Eli": "x_existencia_regiomontano",
}

# Cuantas opciones como maximo manda consultar_inventario cuando el nombre
# matchea varios productos (categorias tipo "hombre" matchean decenas).
MAX_OPCIONES = 5


def odoo_connect():
    """Autentica en Odoo y devuelve (uid, models). Lanza si falla."""
    if not (ODOO_URL and ODOO_DB and ODOO_USER and ODOO_API_KEY):
        raise RuntimeError("Faltan env vars: ODOO_URL / ODOO_DB / ODOO_USER / ODOO_API_KEY")
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


def formatear_opciones(rows, stock_field):
    """rows de product.product -> (opciones ordenadas por stock desc, texto listo
    para el mensaje del bot). Con mas stock primero: al cliente le sirve ver
    primero lo que si hay, no lo agotado."""
    opciones = sorted(
        (
            {
                "nombre": p.get("name") or "",
                "precio_real": float(num(p.get("x_precio_real"))),
                "stock_disponible": int(num(p.get(stock_field))),
            }
            for p in rows
        ),
        key=lambda o: o["stock_disponible"],
        reverse=True,
    )
    texto = "\n".join(
        f"{i}. {o['nombre']} — ${o['precio_real']:.0f} ({o['stock_disponible']} disponibles)"
        for i, o in enumerate(opciones, 1)
    )
    return opciones, texto


# ponytail: self-check de la logica de conexion, sin Odoo real.
if __name__ == "__main__":
    # Sin la env var, ODOO_URL queda vacia: nadie volvio a meter un default que apunte
    # en silencio al servidor equivocado. (Se salta si la env var si esta puesta.)
    assert os.environ.get("ODOO_URL") or ODOO_URL is None, "ODOO_URL no debe tener default"

    # odoo_connect revienta si falta. Las otras tres se llenan para que el unico
    # motivo posible del fallo sea la URL.
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY = None, "db", "user", "key"
    try:
        odoo_connect()
        raise AssertionError("odoo_connect deberia exigir ODOO_URL")
    except RuntimeError as e:
        assert "Faltan env vars" in str(e), e
    print("ok")
