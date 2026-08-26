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

# Grupos de palabras que el cliente/LLM usa indistintamente pero que Odoo trata
# como substrings distintos (ilike es literal): "caballero" nunca hace match con
# productos nombrados "HOMBRE" y viceversa. Confirmado 2026-08-24 contra el
# catalogo real: "caballero" trae 1 producto (agotado), "hombre" trae 30 (con
# stock). Solo se agregan pares verificados contra el catalogo real, no adivinados.
GRUPOS_SINONIMOS = [
    {"hombre", "caballero"},
    {"mujer", "dama"},
]


def terminos_busqueda(producto):
    """Expande producto_interes con sinonimos conocidos si es exactamente una
    palabra de un grupo (ej. "caballero" -> tambien busca "hombre"). Frases mas
    largas se buscan tal cual, sin expandir."""
    clave = producto.strip().lower()
    for grupo in GRUPOS_SINONIMOS:
        if clave in grupo:
            return sorted(grupo)
    return [producto]


def domain_ilike_or(campo, terminos):
    """Domain de Odoo para "campo ilike t1 OR campo ilike t2 OR ...". Notacion
    polaca: N terminos necesitan N-1 operadores '|' antes de las condiciones."""
    condiciones = [[campo, "ilike", t] for t in terminos]
    return ["|"] * (len(condiciones) - 1) + condiciones


def domain_orden_duplicada(partner_id, product_id):
    """Domain del borrador que ese contacto ya levanto con ese mismo producto.
    Odoo atraviesa la one2many con punto (order_line.product_id), y una lista de
    condiciones sin operadores es AND implicito."""
    return [
        ["partner_id", "=", partner_id],
        ["state", "=", "draft"],
        ["order_line.product_id", "=", product_id],
    ]


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


def nombre_orden(models, uid, order_id):
    """Numero visible de la orden (S00042). Cae al id si Odoo no devuelve name."""
    order = execute(models, uid, "sale.order", "read", [order_id], fields=["name"])
    return order[0].get("name") if order else str(order_id)


def num(v):
    """Odoo devuelve False para campos vacios. Normaliza a numero."""
    return v if isinstance(v, (int, float)) else 0


def texto_opciones(opciones):
    """Lista numerada lista para el mensaje del bot (renumera desde 1)."""
    return "\n".join(
        f"{i}. {o['nombre']} — ${o['precio_real']:.0f} ({o['stock_disponible']} disponibles)"
        for i, o in enumerate(opciones, 1)
    )


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
    return opciones, texto_opciones(opciones)


# ponytail: self-check de la logica de conexion, sin Odoo real.
if __name__ == "__main__":
    # terminos_busqueda: expande solo si es EXACTAMENTE una palabra de un grupo.
    assert terminos_busqueda("caballero") == ["caballero", "hombre"]
    assert terminos_busqueda("Caballero") == ["caballero", "hombre"]  # case-insensitive
    assert terminos_busqueda("dama") == ["dama", "mujer"]
    assert terminos_busqueda("hombre") == ["caballero", "hombre"]  # cualquier lado del grupo
    assert terminos_busqueda("ropa para caballero") == ["ropa para caballero"]  # frase: sin expandir
    assert terminos_busqueda("niño") == ["niño"]  # sin grupo conocido: tal cual

    # domain_ilike_or: notacion polaca de Odoo (N terminos -> N-1 '|').
    assert domain_ilike_or("name", ["x"]) == [["name", "ilike", "x"]]
    assert domain_ilike_or("name", ["x", "y"]) == ["|", ["name", "ilike", "x"], ["name", "ilike", "y"]]

    # domain_orden_duplicada: AND implicito; acota a borrador y al mismo producto,
    # no a cualquier orden del contacto (pedir otro producto si es orden nueva).
    assert domain_orden_duplicada(7, 42) == [
        ["partner_id", "=", 7],
        ["state", "=", "draft"],
        ["order_line.product_id", "=", 42],
    ]

    # texto_opciones: numera desde 1, precio sin decimales, una linea por opcion.
    _ops = [
        {"nombre": "CAMISA HOMBRE", "precio_real": 250.0, "stock_disponible": 12},
        {"nombre": "PLAYERA HOMBRE", "precio_real": 180.0, "stock_disponible": 8},
    ]
    assert texto_opciones(_ops) == (
        "1. CAMISA HOMBRE — $250 (12 disponibles)\n"
        "2. PLAYERA HOMBRE — $180 (8 disponibles)"
    )
    assert texto_opciones([]) == ""

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
