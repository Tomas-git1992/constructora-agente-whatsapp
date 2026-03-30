"""
agent.py
Agente Claude con herramientas (tool use) para gestión financiera de obras.
"""

import json
import os
from typing import Optional

import anthropic
import database as db

# ──────────────────────────────────────────────
# DEFINICIÓN DE HERRAMIENTAS (TOOLS)
# ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "listar_obras",
        "description": (
            "Lista las obras (proyectos de construcción) disponibles. "
            "Usá esta herramienta cuando el usuario pregunte qué obras existen o "
            "antes de cualquier operación que requiera conocer el ID de una obra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "solo_activas": {
                    "type": "boolean",
                    "description": "Si es true, solo devuelve obras activas. Default: true.",
                }
            },
        },
    },
    {
        "name": "registrar_movimiento",
        "description": (
            "Registra un ingreso o egreso (gasto) en la caja de una obra. "
            "Siempre confirmá el nombre de la obra con el usuario antes de registrar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "tipo": {
                    "type": "string",
                    "enum": ["ingreso", "egreso"],
                    "description": "Tipo de movimiento: ingreso o egreso.",
                },
                "monto": {
                    "type": "number",
                    "description": "Monto del movimiento (siempre positivo).",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD", "digital"],
                    "description": "Moneda: ARS (pesos), USD (dólares), digital (transferencia/mercadopago).",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción breve del movimiento.",
                },
                "rubro": {
                    "type": "string",
                    "description": "Categoría del gasto (ej: Mano de Obra, Materiales, Servicios). Opcional.",
                },
                "proveedor": {
                    "type": "string",
                    "description": "Nombre del proveedor o persona relacionada. Opcional.",
                },
                "fecha": {
                    "type": "string",
                    "description": "Fecha del movimiento en formato YYYY-MM-DD. Si no se indica, se usa hoy.",
                },
                "registrado_por": {
                    "type": "string",
                    "description": "Nombre o teléfono de quien registra. Opcional.",
                },
            },
            "required": ["nombre_obra", "tipo", "monto", "moneda", "descripcion"],
        },
    },
    {
        "name": "consultar_saldo_caja",
        "description": (
            "Consulta el saldo actual de la caja de una obra, separado por moneda "
            "(ARS, USD, digital). Muestra ingresos, egresos y saldo neto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra. Si se omite, devuelve todas.",
                }
            },
        },
    },
    {
        "name": "listar_movimientos",
        "description": (
            "Lista los últimos movimientos (ingresos/egresos) de una obra, "
            "con filtros opcionales por fecha, tipo, moneda o rubro."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "tipo": {
                    "type": "string",
                    "enum": ["ingreso", "egreso"],
                    "description": "Filtrar solo ingresos o solo egresos. Opcional.",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD", "digital"],
                    "description": "Filtrar por moneda. Opcional.",
                },
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha inicio en formato YYYY-MM-DD. Opcional.",
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha fin en formato YYYY-MM-DD. Opcional.",
                },
                "rubro": {
                    "type": "string",
                    "description": "Filtrar por categoría (ej: Materiales). Opcional.",
                },
                "cantidad": {
                    "type": "integer",
                    "description": "Cantidad máxima de resultados. Default: 10.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
    {
        "name": "registrar_aporte_inversor",
        "description": (
            "Registra un aporte, retiro, préstamo o devolución de un inversor en una obra. "
            "Mantiene la cuenta corriente de cada inversor por obra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "nombre_inversor": {
                    "type": "string",
                    "description": "Nombre del inversor.",
                },
                "monto": {
                    "type": "number",
                    "description": "Monto (siempre positivo).",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD", "digital"],
                },
                "tipo": {
                    "type": "string",
                    "enum": ["aporte", "retiro", "prestamo", "devolucion"],
                    "description": "Tipo de movimiento del inversor.",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción opcional.",
                },
                "fecha": {
                    "type": "string",
                    "description": "Fecha en formato YYYY-MM-DD. Default: hoy.",
                },
            },
            "required": ["nombre_obra", "nombre_inversor", "monto", "moneda", "tipo"],
        },
    },
    {
        "name": "consultar_cuenta_corriente_inversor",
        "description": (
            "Consulta la cuenta corriente de un inversor: cuánto aportó, cuánto retiró "
            "y su saldo neto por obra y moneda."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_inversor": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) del inversor.",
                },
                "nombre_obra": {
                    "type": "string",
                    "description": "Filtrar por obra específica. Opcional.",
                },
            },
            "required": ["nombre_inversor"],
        },
    },
    {
        "name": "registrar_presupuesto",
        "description": (
            "Registra un presupuesto recibido de un proveedor para una obra. "
            "Permite comparar múltiples presupuestos para el mismo rubro."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción del trabajo o ítem presupuestado.",
                },
                "monto": {"type": "number", "description": "Monto del presupuesto."},
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD"],
                },
                "proveedor": {
                    "type": "string",
                    "description": "Nombre del proveedor que cotizó.",
                },
                "rubro": {
                    "type": "string",
                    "description": "Categoría del trabajo (ej: Mano de Obra, Materiales).",
                },
                "validez_dias": {
                    "type": "integer",
                    "description": "Días de validez del presupuesto. Opcional.",
                },
                "notas": {
                    "type": "string",
                    "description": "Notas adicionales sobre el presupuesto. Opcional.",
                },
            },
            "required": ["nombre_obra", "descripcion", "monto", "moneda"],
        },
    },
    {
        "name": "comparar_presupuestos",
        "description": (
            "Compara presupuestos de distintos proveedores para una obra y/o rubro. "
            "Devuelve los presupuestos ordenados de menor a mayor precio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra. Opcional.",
                },
                "rubro": {
                    "type": "string",
                    "description": "Categoría para comparar (ej: Materiales). Opcional.",
                },
                "estado": {
                    "type": "string",
                    "enum": ["pendiente", "aprobado", "rechazado"],
                    "description": "Filtrar por estado del presupuesto. Default: todos.",
                },
            },
        },
    },
]

# ──────────────────────────────────────────────
# EJECUCIÓN DE HERRAMIENTAS
# ──────────────────────────────────────────────

def ejecutar_herramienta(nombre: str, params: dict) -> str:
    """Ejecuta la herramienta solicitada por el agente y devuelve el resultado como string."""
    try:
        if nombre == "listar_obras":
            obras = db.listar_obras(params.get("solo_activas", True))
            if not obras:
                return "No hay obras registradas."
            lineas = [f"• {o['nombre']} (ID: {o['id']}, Estado: {o['estado']})" for o in obras]
            return "Obras activas:\n" + "\n".join(lineas)

        elif nombre == "registrar_movimiento":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré ninguna obra con el nombre '{params['nombre_obra']}'. ¿Podés verificar el nombre?"
            resultado = db.registrar_movimiento(
                obra_id=obra["id"],
                tipo=params["tipo"],
                monto=params["monto"],
                moneda=params["moneda"],
                descripcion=params["descripcion"],
                rubro_nombre=params.get("rubro"),
                proveedor_nombre=params.get("proveedor"),
                fecha=params.get("fecha"),
                registrado_por=params.get("registrado_por"),
            )
            tipo_str = "✅ Ingreso" if params["tipo"] == "ingreso" else "💸 Egreso"
            moneda_sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(params["moneda"], "")
            return (
                f"{tipo_str} registrado en *{obra['nombre']}*\n"
                f"Monto: {moneda_sym} {params['monto']:,.2f} {params['moneda']}\n"
                f"Concepto: {params['descripcion']}\n"
                f"Fecha: {resultado.get('fecha', 'hoy')}"
            )

        elif nombre == "consultar_saldo_caja":
            obra_id = None
            obra_nombre = "todas las obras"
            if params.get("nombre_obra"):
                obra = db.buscar_obra_por_nombre(params["nombre_obra"])
                if not obra:
                    return f"❌ No encontré la obra '{params['nombre_obra']}'."
                obra_id = obra["id"]
                obra_nombre = obra["nombre"]

            saldos = db.consultar_saldo_caja(obra_id)
            if not saldos:
                return f"No hay movimientos registrados para {obra_nombre}."

            lineas = [f"💰 *Saldo de caja — {obra_nombre}*\n"]
            for s in saldos:
                moneda_sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(s["moneda"], "")
                lineas.append(
                    f"*{s['moneda']}*\n"
                    f"  Ingresos:  {moneda_sym} {s['total_ingresos']:,.2f}\n"
                    f"  Egresos:   {moneda_sym} {s['total_egresos']:,.2f}\n"
                    f"  *Saldo:    {moneda_sym} {s['saldo']:,.2f}*"
                )
            return "\n\n".join(lineas)

        elif nombre == "listar_movimientos":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."
            movs = db.consultar_movimientos(
                obra_id=obra["id"],
                tipo=params.get("tipo"),
                moneda=params.get("moneda"),
                fecha_desde=params.get("fecha_desde"),
                fecha_hasta=params.get("fecha_hasta"),
                rubro_nombre=params.get("rubro"),
                limit=params.get("cantidad", 10),
            )
            if not movs:
                return f"No encontré movimientos con esos filtros en *{obra['nombre']}*."
            lineas = [f"📋 *Últimos movimientos — {obra['nombre']}*\n"]
            for m in movs:
                emoji = "⬆️" if m["tipo"] == "ingreso" else "⬇️"
                moneda_sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(m["moneda"], "")
                rubro_str = f" [{m['rubros']['nombre']}]" if m.get("rubros") else ""
                lineas.append(
                    f"{emoji} {m['fecha']} — {moneda_sym} {m['monto']:,.2f} {m['moneda']}{rubro_str}\n"
                    f"   {m['descripcion']}"
                )
            return "\n".join(lineas)

        elif nombre == "registrar_aporte_inversor":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."

            inversor = db.buscar_inversor_por_nombre(params["nombre_inversor"])
            if not inversor:
                inversor = db.crear_inversor(params["nombre_inversor"])

            resultado = db.registrar_aporte(
                obra_id=obra["id"],
                inversor_id=inversor["id"],
                monto=params["monto"],
                moneda=params["moneda"],
                tipo=params["tipo"],
                descripcion=params.get("descripcion", ""),
                fecha=params.get("fecha"),
            )
            tipo_emoji = {"aporte": "💼", "retiro": "💸", "prestamo": "🤝", "devolucion": "↩️"}.get(params["tipo"], "•")
            moneda_sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(params["moneda"], "")
            return (
                f"{tipo_emoji} *{params['tipo'].capitalize()}* registrado\n"
                f"Inversor: {inversor['nombre']}\n"
                f"Obra: {obra['nombre']}\n"
                f"Monto: {moneda_sym} {params['monto']:,.2f} {params['moneda']}\n"
                f"Fecha: {resultado.get('fecha', 'hoy')}"
            )

        elif nombre == "consultar_cuenta_corriente_inversor":
            inversor = db.buscar_inversor_por_nombre(params["nombre_inversor"])
            if not inversor:
                return f"❌ No encontré ningún inversor con el nombre '{params['nombre_inversor']}'."
            obra_id = None
            if params.get("nombre_obra"):
                obra = db.buscar_obra_por_nombre(params["nombre_obra"])
                if obra:
                    obra_id = obra["id"]

            registros = db.consultar_cuenta_corriente(
                inversor_id=inversor["id"], obra_id=obra_id
            )
            if not registros:
                return f"No hay movimientos registrados para *{inversor['nombre']}*."

            lineas = [f"📊 *Cuenta corriente — {inversor['nombre']}*\n"]
            for r in registros:
                moneda_sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(r["moneda"], "")
                lineas.append(
                    f"*{r['obra']}* ({r['moneda']})\n"
                    f"  Aportes:  {moneda_sym} {r['total_aportes']:,.2f}\n"
                    f"  Retiros:  {moneda_sym} {r['total_retiros']:,.2f}\n"
                    f"  *Saldo:   {moneda_sym} {r['saldo_neto']:,.2f}*"
                )
            return "\n\n".join(lineas)

        elif nombre == "registrar_presupuesto":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."
            resultado = db.registrar_presupuesto(
                obra_id=obra["id"],
                descripcion=params["descripcion"],
                monto=params["monto"],
                moneda=params["moneda"],
                proveedor_nombre=params.get("proveedor"),
                rubro_nombre=params.get("rubro"),
                validez_dias=params.get("validez_dias"),
                notas=params.get("notas"),
            )
            moneda_sym = {"ARS": "$", "USD": "U$S"}.get(params["moneda"], "")
            return (
                f"📝 *Presupuesto registrado*\n"
                f"Obra: {obra['nombre']}\n"
                f"Concepto: {params['descripcion']}\n"
                f"Proveedor: {params.get('proveedor', 'No indicado')}\n"
                f"Monto: {moneda_sym} {params['monto']:,.2f} {params['moneda']}"
            )

        elif nombre == "comparar_presupuestos":
            obra_id = None
            if params.get("nombre_obra"):
                obra = db.buscar_obra_por_nombre(params["nombre_obra"])
                if obra:
                    obra_id = obra["id"]

            presupuestos = db.comparar_presupuestos(
                obra_id=obra_id,
                rubro_nombre=params.get("rubro"),
                estado=params.get("estado"),
            )
            if not presupuestos:
                return "No encontré presupuestos con esos filtros."

            lineas = ["🔍 *Comparación de presupuestos* (orden: menor a mayor)\n"]
            for i, p in enumerate(presupuestos, 1):
                moneda_sym = {"ARS": "$", "USD": "U$S"}.get(p["moneda"], "")
                prov_str = p["proveedores"]["nombre"] if p.get("proveedores") else "Sin proveedor"
                obra_str = p["obras"]["nombre"] if p.get("obras") else ""
                rubro_str = p["rubros"]["nombre"] if p.get("rubros") else ""
                lineas.append(
                    f"{i}. *{moneda_sym} {p['monto']:,.2f}* — {prov_str}\n"
                    f"   {p['descripcion']}\n"
                    f"   Obra: {obra_str} | Rubro: {rubro_str} | Estado: {p['estado']}"
                )
            return "\n\n".join(lineas)

        else:
            return f"Herramienta desconocida: {nombre}"

    except Exception as e:
        return f"❌ Error al ejecutar {nombre}: {str(e)}"


# ──────────────────────────────────────────────
# AGENTE PRINCIPAL
# ──────────────────────────────────────────────

SYSTEM_PROMPT = """Sos el asistente financiero de una empresa constructora argentina.
Tu rol es ayudar al equipo a registrar y consultar información financiera de las obras de forma
rápida y simple a través de WhatsApp.

Podés ayudar con:
- Registrar ingresos y egresos en la caja de cada obra (en pesos, dólares o medios digitales)
- Consultar saldos y movimientos por obra
- Registrar aportes y retiros de inversores
- Ver la cuenta corriente de cada inversor
- Registrar y comparar presupuestos de proveedores

Reglas importantes:
1. Siempre respondé en español argentino, de forma amigable y concisa (esto es WhatsApp).
2. Cuando el usuario mencione un monto, si no indica la moneda, preguntá si es pesos (ARS),
   dólares (USD) o digital (transferencia/MercadoPago).
3. Antes de registrar algo importante (movimiento > $100.000 o > U$S 500), confirmá con el usuario.
4. Si falta información necesaria, preguntá de forma clara y específica.
5. Usá emojis con moderación para hacer la lectura más fácil.
6. Nunca inventes datos que no tenés. Si no encontrás algo en la base de datos, decilo claramente.
7. Los montos siempre con separador de miles (punto) y dos decimales cuando corresponda.
8. Las fechas en formato día/mes/año para mostrar al usuario.
"""

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def procesar_mensaje(telefono: str, mensaje_usuario: str) -> str:
    """
    Procesa un mensaje de WhatsApp y devuelve la respuesta del agente.
    Mantiene el historial de conversación por usuario.
    """
    # Guardar mensaje del usuario
    db.guardar_mensaje(telefono, "user", mensaje_usuario)

    # Construir historial de mensajes
    historial = db.obtener_historial(telefono, limite=10)
    messages = [{"role": m["rol"], "content": m["contenido"]} for m in historial]

    # Si el historial ya incluye el mensaje actual (por el guardado previo), no lo duplicamos
    # (esto depende de si obtener_historial incluye el último guardado)
    # Por seguridad, nos aseguramos que el último mensaje sea del usuario
    if not messages or messages[-1]["content"] != mensaje_usuario:
        messages.append({"role": "user", "content": mensaje_usuario})

    # Bucle agentico: el agente puede llamar herramientas varias veces
    max_iterations = 5
    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Añadir respuesta del asistente al historial temporal
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Extraer texto de la respuesta
            texto = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            db.guardar_mensaje(telefono, "assistant", texto)
            return texto

        elif response.stop_reason == "tool_use":
            # Ejecutar todas las herramientas solicitadas
            resultados_tools = []
            for block in response.content:
                if block.type == "tool_use":
                    resultado = ejecutar_herramienta(block.name, block.input)
                    resultados_tools.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado,
                    })

            # Agregar resultados al historial
            messages.append({"role": "user", "content": resultados_tools})

        else:
            break

    respuesta_fallback = "Hubo un problema procesando tu mensaje. Por favor intentá de nuevo."
    db.guardar_mensaje(telefono, "assistant", respuesta_fallback)
    return respuesta_fallback
