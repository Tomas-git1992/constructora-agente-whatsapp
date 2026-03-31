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
                "forzar_registro": {
                    "type": "boolean",
                    "description": "Si es true, registra aunque exista un duplicado reciente. Usar solo cuando el usuario confirmó explícitamente.",
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
        "name": "generar_informe",
        "description": (
            "Genera un informe financiero de una obra con totales por moneda, "
            "desglose de egresos por rubro con porcentajes y comparativas. "
            "Usá esta herramienta cuando el usuario pida un resumen, informe o reporte."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha inicio en formato YYYY-MM-DD. Opcional.",
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha fin en formato YYYY-MM-DD. Opcional.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
    {
        "name": "exportar_movimientos",
        "description": (
            "Genera un link de descarga CSV con todos los movimientos de una obra. "
            "El link puede abrirse desde el celular para descargar el archivo y abrirlo en Excel o Google Sheets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "fecha_desde": {
                    "type": "string",
                    "description": "Fecha inicio en formato YYYY-MM-DD. Opcional.",
                },
                "fecha_hasta": {
                    "type": "string",
                    "description": "Fecha fin en formato YYYY-MM-DD. Opcional.",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD", "digital"],
                    "description": "Filtrar por moneda. Opcional.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
    {
        "name": "crear_obra",
        "description": (
            "Crea una nueva obra (proyecto de construcción) en el sistema. "
            "Usá esta herramienta cuando el usuario quiera dar de alta una obra nueva. "
            "Pedí confirmación antes de crear si no tenés todos los datos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {
                    "type": "string",
                    "description": "Nombre de la obra. Requerido.",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción breve de la obra. Opcional.",
                },
                "direccion": {
                    "type": "string",
                    "description": "Dirección física de la obra. Opcional.",
                },
                "fecha_inicio": {
                    "type": "string",
                    "description": "Fecha de inicio en formato YYYY-MM-DD. Default: hoy.",
                },
            },
            "required": ["nombre"],
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
    {
        "name": "actualizar_presupuesto",
        "description": (
            "Establece o actualiza el presupuesto total de una obra. "
            "Usá esta herramienta cuando el usuario quiera definir cuánto se puede gastar en la obra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "presupuesto_total": {
                    "type": "number",
                    "description": "Monto total del presupuesto de la obra.",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD"],
                    "description": "Moneda del presupuesto. Default: ARS.",
                },
            },
            "required": ["nombre_obra", "presupuesto_total"],
        },
    },
    {
        "name": "cerrar_obra",
        "description": (
            "Cierra una obra y genera un informe de cierre detallado con desglose por rubro, "
            "separación entre materiales y mano de obra, y comparación presupuesto vs ejecutado. "
            "Pedí siempre confirmación del usuario antes de cerrar una obra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "solo_informe": {
                    "type": "boolean",
                    "description": "Si es true, genera el informe de cierre SIN cerrar la obra. Útil para previsualizar.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
    {
        "name": "suscribir_informe_semanal",
        "description": (
            "Suscribe un número de WhatsApp para recibir el informe financiero semanal "
            "de una obra (todos los lunes a las 8am). "
            "También puede usarse para que el usuario actual se suscriba a sus propias obras."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
                "telefono": {
                    "type": "string",
                    "description": (
                        "Número de WhatsApp a suscribir (con código de país, ej: +5491122334455). "
                        "Si se omite, se usa el número del usuario que está chateando."
                    ),
                },
                "nombre_contacto": {
                    "type": "string",
                    "description": "Nombre de la persona (para identificarla). Opcional.",
                },
                "rol": {
                    "type": "string",
                    "description": "Rol: 'propietario', 'inversor', 'operador'. Default: operador.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
    {
        "name": "registrar_comprobante_materiales",
        "description": (
            "Registra un comprobante de compra de materiales. "
            "Crea el movimiento de egreso con el total y guarda cada ítem del ticket "
            "(nombre, cantidad, unidad, precio unitario, precio total) en la tabla de materiales. "
            "Usar SOLO después de mostrar el resumen al usuario y recibir su confirmación."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra a la que se asigna el comprobante.",
                },
                "proveedor": {
                    "type": "string",
                    "description": "Nombre del proveedor / ferretería. Opcional.",
                },
                "total": {
                    "type": "number",
                    "description": "Monto total del comprobante (siempre positivo).",
                },
                "moneda": {
                    "type": "string",
                    "enum": ["ARS", "USD", "digital"],
                    "description": "Moneda del comprobante.",
                },
                "fecha": {
                    "type": "string",
                    "description": "Fecha del comprobante en formato YYYY-MM-DD. Si no figura, usar hoy.",
                },
                "items": {
                    "type": "array",
                    "description": "Lista completa de ítems del comprobante.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nombre":          {"type": "string",  "description": "Nombre del material."},
                            "cantidad":        {"type": "number",  "description": "Cantidad comprada."},
                            "unidad":          {"type": "string",  "description": "Unidad: bolsa, m2, m3, kg, litro, unidad, etc."},
                            "precio_unitario": {"type": "number",  "description": "Precio por unidad."},
                            "precio_total":    {"type": "number",  "description": "Precio total del ítem."},
                        },
                        "required": ["nombre"],
                    },
                },
                "notas": {
                    "type": "string",
                    "description": "Notas adicionales sobre el comprobante. Opcional.",
                },
            },
            "required": ["nombre_obra", "total", "moneda", "items"],
        },
    },
    {
        "name": "listar_materiales_obra",
        "description": (
            "Lista todos los materiales comprados para una obra, "
            "extraídos de comprobantes procesados. "
            "Muestra nombre, cantidad, unidad y precios por ítem."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_obra": {
                    "type": "string",
                    "description": "Nombre (o parte del nombre) de la obra.",
                },
            },
            "required": ["nombre_obra"],
        },
    },
]

# ──────────────────────────────────────────────
# EJECUCIÓN DE HERRAMIENTAS
# ──────────────────────────────────────────────

def ejecutar_herramienta(nombre: str, params: dict, telefono_usuario: str = "") -> str:
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

            # Detección de duplicados (salvo que el usuario ya confirmó)
            if not params.get("forzar_registro"):
                duplicados = db.detectar_duplicado(
                    obra_id=obra["id"],
                    monto=params["monto"],
                    moneda=params["moneda"],
                    tipo=params["tipo"],
                )
                if duplicados:
                    dup = duplicados[0]
                    registrado_por = dup.get("registrado_por") or "alguien del equipo"
                    return (
                        f"⚠️ *Posible duplicado detectado*\n"
                        f"Hay un movimiento similar registrado hace menos de 2 horas:\n"
                        f"  • {dup['tipo'].capitalize()} de {dup['monto']} {dup['moneda']}\n"
                        f"  • Concepto: {dup.get('descripcion', '—')}\n"
                        f"  • Registrado por: {registrado_por}\n\n"
                        f"¿Es un movimiento nuevo o es el mismo? "
                        f"Respondé *'sí, registralo igual'* para confirmarlo."
                    )

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
            msg = (
                f"{tipo_str} registrado en *{obra['nombre']}*\n"
                f"Monto: {moneda_sym} {params['monto']:,.2f} {params['moneda']}\n"
                f"Concepto: {params['descripcion']}\n"
                f"Fecha: {resultado.get('fecha', 'hoy')}"
            )

            # Alerta de presupuesto si el movimiento es un egreso
            if params["tipo"] == "egreso":
                try:
                    ppto = db.obtener_presupuesto_obra(obra["id"])
                    if ppto.get("presupuesto_total", 0) > 0 and ppto.get("moneda") == params["moneda"]:
                        pct = ppto["porcentaje_ejecutado"]
                        sym = {"ARS": "$", "USD": "U$S"}.get(ppto["moneda"], "")
                        if pct >= 100:
                            msg += (
                                f"\n\n🚨 *PRESUPUESTO SUPERADO*\n"
                                f"Ejecutado: {sym} {ppto['gastado']:,.0f} de {sym} {ppto['presupuesto_total']:,.0f} "
                                f"({pct}%)"
                            )
                        elif pct >= 80:
                            msg += (
                                f"\n\n⚠️ *Alerta presupuesto: {pct}% ejecutado*\n"
                                f"Disponible: {sym} {ppto['disponible']:,.0f} {ppto['moneda']}"
                            )
                except Exception:
                    pass  # No interrumpir el flujo si falla la verificación

            return msg

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

        elif nombre == "crear_obra":
            from datetime import date
            obra_existente = db.buscar_obra_por_nombre(params["nombre"])
            if obra_existente:
                return (
                    f"⚠️ Ya existe una obra llamada *{obra_existente['nombre']}* "
                    f"(estado: {obra_existente['estado']}). ¿Querés crear una con nombre diferente?"
                )
            nueva_obra = db.crear_obra(
                nombre=params["nombre"],
                descripcion=params.get("descripcion", ""),
                direccion=params.get("direccion", ""),
                fecha_inicio=params.get("fecha_inicio", date.today().isoformat()),
            )
            return (
                f"🏗️ *Obra creada exitosamente*\n"
                f"Nombre: {nueva_obra['nombre']}\n"
                f"Dirección: {nueva_obra.get('direccion') or 'No indicada'}\n"
                f"Estado: {nueva_obra.get('estado', 'activa')}"
            )

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

        elif nombre == "generar_informe":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."
            informe = db.generar_informe_financiero(
                obra_id=obra["id"],
                fecha_desde=params.get("fecha_desde"),
                fecha_hasta=params.get("fecha_hasta"),
            )
            if informe["total_movimientos"] == 0:
                return f"No hay movimientos registrados en *{obra['nombre']}*."

            lineas = [f"📊 *Informe financiero — {obra['nombre']}*"]
            periodo = ""
            if informe.get("fecha_desde") or informe.get("fecha_hasta"):
                desde = informe.get("fecha_desde", "inicio")
                hasta = informe.get("fecha_hasta", "hoy")
                periodo = f" ({desde} → {hasta})"
            lineas[0] += periodo + "\n"

            # Totales por moneda
            for moneda, datos in informe["por_moneda"].items():
                sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(moneda, "")
                lineas.append(
                    f"*{moneda}*\n"
                    f"  Ingresos: {sym} {datos['ingresos']:,.2f}\n"
                    f"  Egresos:  {sym} {datos['egresos']:,.2f}\n"
                    f"  Saldo:    {sym} {datos['saldo']:,.2f}"
                )

            # Desglose de egresos por rubro (con barra visual y porcentaje)
            if informe["por_rubro"]:
                lineas.append("\n📂 *Egresos por rubro:*")
                for moneda in informe["por_moneda"]:
                    sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(moneda, "")
                    total_egresos = informe["por_moneda"][moneda]["egresos"]
                    if total_egresos == 0:
                        continue
                    rubros_moneda = [
                        (rubro, montos[moneda])
                        for rubro, montos in informe["por_rubro"].items()
                        if moneda in montos
                    ]
                    rubros_moneda.sort(key=lambda x: x[1], reverse=True)
                    if rubros_moneda:
                        lineas.append(f"_{moneda}_")
                        for rubro, monto in rubros_moneda:
                            pct = (monto / total_egresos) * 100
                            barras = int(pct / 10)
                            barra_str = "█" * barras + "░" * (10 - barras)
                            lineas.append(
                                f"  {rubro[:18]:<18} {barra_str} {pct:.0f}%\n"
                                f"  {' '*18} {sym} {monto:,.2f}"
                            )

            lineas.append(f"\n_Total: {informe['total_movimientos']} movimientos_")
            return "\n".join(lineas)

        elif nombre == "exportar_movimientos":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."

            base_url = os.environ.get(
                "RAILWAY_PUBLIC_DOMAIN",
                "web-production-73e40.up.railway.app"
            )
            if not base_url.startswith("http"):
                base_url = f"https://{base_url}"

            import urllib.parse
            query: dict = {"obra": obra["nombre"]}
            if params.get("fecha_desde"):
                query["desde"] = params["fecha_desde"]
            if params.get("fecha_hasta"):
                query["hasta"] = params["fecha_hasta"]
            if params.get("moneda"):
                query["moneda"] = params["moneda"]

            url = f"{base_url}/export/movimientos?{urllib.parse.urlencode(query)}"

            filtros = []
            if params.get("fecha_desde") or params.get("fecha_hasta"):
                filtros.append(f"{params.get('fecha_desde','inicio')} → {params.get('fecha_hasta','hoy')}")
            if params.get("moneda"):
                filtros.append(params["moneda"])
            filtros_str = " · ".join(filtros) if filtros else "todos los movimientos"

            return (
                f"📥 *Exportar movimientos — {obra['nombre']}*\n"
                f"Filtros: {filtros_str}\n\n"
                f"Abrí este link desde tu celular o computadora para descargar el CSV:\n"
                f"{url}\n\n"
                f"_El archivo se puede abrir en Excel o Google Sheets._"
            )

        elif nombre == "actualizar_presupuesto":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."
            moneda = params.get("moneda", "ARS")
            db.actualizar_presupuesto_obra(obra["id"], params["presupuesto_total"], moneda)
            sym = {"ARS": "$", "USD": "U$S"}.get(moneda, "")
            # Calcular estado actual vs presupuesto
            ppto = db.obtener_presupuesto_obra(obra["id"])
            return (
                f"✅ *Presupuesto actualizado — {obra['nombre']}*\n"
                f"Presupuesto total: {sym} {params['presupuesto_total']:,.2f} {moneda}\n"
                f"Gastado hasta ahora: {sym} {ppto.get('gastado', 0):,.2f} ({ppto.get('porcentaje_ejecutado', 0)}%)\n"
                f"Disponible: {sym} {ppto.get('disponible', params['presupuesto_total']):,.2f}"
            )

        elif nombre == "cerrar_obra":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."

            informe = db.generar_informe_cierre(obra["id"])
            if not informe:
                return f"❌ No se pudo generar el informe para '{params['nombre_obra']}'."

            # Solo informe sin cerrar
            solo_informe = params.get("solo_informe", False)
            if not solo_informe:
                db.cerrar_obra(obra["id"])

            # Formatear informe
            o = informe["obra"]
            lineas = [
                f"{'📊' if solo_informe else '🏁'} *{'Informe de cierre' if solo_informe else 'OBRA CERRADA'} — {o['nombre']}*",
                f"Inicio: {o.get('fecha_inicio', '—')} | Cierre: {o.get('fecha_cierre') or 'hoy'}",
                "",
            ]

            # Totales
            for moneda, datos in informe["totales"].items():
                sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(moneda, "")
                lineas.append(
                    f"*{moneda}*\n"
                    f"  Ingresos: {sym} {datos['ingresos']:,.0f}\n"
                    f"  Egresos:  {sym} {datos['egresos']:,.0f}\n"
                    f"  Saldo:    {sym} {datos['saldo']:,.0f}"
                )

            # Desglose por rubro
            if informe["por_rubro"]:
                lineas.append("\n📂 *Desglose por rubro:*")
                for r in informe["por_rubro"]:
                    sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(r["moneda"], "")
                    lineas.append(f"  • {r['rubro']}: {sym} {r['monto']:,.0f} ({r['porcentaje']}%)")

            # Materiales vs Mano de obra
            clf = informe["clasificacion"]
            if clf["materiales"] or clf["mano_de_obra"]:
                lineas.append("\n🔨 *Materiales vs Mano de obra:*")
                for moneda, monto in clf["materiales"].items():
                    sym = {"ARS": "$", "USD": "U$S"}.get(moneda, "")
                    lineas.append(f"  Materiales ({moneda}): {sym} {monto:,.0f}")
                for moneda, monto in clf["mano_de_obra"].items():
                    sym = {"ARS": "$", "USD": "U$S"}.get(moneda, "")
                    lineas.append(f"  Mano de obra ({moneda}): {sym} {monto:,.0f}")

            # Presupuesto vs ejecutado
            if informe.get("presupuesto"):
                p = informe["presupuesto"]
                sym = {"ARS": "$", "USD": "U$S"}.get(p["moneda"], "")
                desvio = p["desvio_porcentaje"]
                desvio_str = (
                    f"✅ {abs(desvio)}% bajo presupuesto" if desvio < 0
                    else f"⚠️ {desvio}% sobre presupuesto" if desvio > 0
                    else "✅ Exacto al presupuesto"
                ) if desvio is not None else "—"
                lineas.append(
                    f"\n📋 *Presupuesto vs Ejecutado ({p['moneda']}):*\n"
                    f"  Presupuesto: {sym} {p['presupuesto_total']:,.0f}\n"
                    f"  Ejecutado:   {sym} {p['ejecutado']:,.0f}\n"
                    f"  {desvio_str}"
                )

            lineas.append(f"\n_Total: {informe['total_movimientos']} movimientos registrados_")
            return "\n".join(lineas)

        elif nombre == "registrar_comprobante_materiales":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."

            items    = params.get("items", [])
            total    = params["total"]
            moneda   = params["moneda"]
            proveedor = params.get("proveedor", "")
            fecha    = params.get("fecha")
            notas    = params.get("notas", "")

            # Descripción del movimiento
            items_resumidos = ", ".join(
                it.get("nombre", "?") for it in items[:4]
            )
            if len(items) > 4:
                items_resumidos += f" y {len(items) - 4} más"
            descripcion = f"Comprobante materiales: {items_resumidos}"
            if notas:
                descripcion += f" — {notas}"

            # Registrar el egreso
            mov = db.registrar_movimiento(
                obra_id=obra["id"],
                tipo="egreso",
                monto=total,
                moneda=moneda,
                descripcion=descripcion,
                rubro_nombre="Materiales",
                proveedor_nombre=proveedor or None,
                fecha=fecha,
                registrado_por=telefono_usuario,
            )

            # Registrar cada ítem
            db.registrar_materiales_compra(mov["id"], obra["id"], items)

            sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(moneda, "")
            lineas = [
                f"✅ *Comprobante registrado — {obra['nombre']}*",
                f"Proveedor: {proveedor or '—'} | Fecha: {fecha or 'hoy'}",
                f"Total: {sym} {total:,.2f} {moneda}",
                "",
                f"📦 *{len(items)} ítem{'s' if len(items) != 1 else ''} guardado{'s' if len(items) != 1 else ''}:*",
            ]
            for it in items:
                nombre_it  = it.get("nombre", "?")
                cant       = it.get("cantidad")
                unidad     = it.get("unidad", "")
                precio_t   = it.get("precio_total")
                precio_u   = it.get("precio_unitario")
                cant_str   = f"{cant} {unidad}".strip() if cant is not None else ""
                if precio_t is not None:
                    precio_str = f"{sym} {precio_t:,.2f}"
                elif precio_u is not None:
                    precio_str = f"{sym} {precio_u:,.2f}/u"
                else:
                    precio_str = ""
                linea = f"  • {nombre_it}"
                if cant_str:
                    linea += f" ({cant_str})"
                if precio_str:
                    linea += f": {precio_str}"
                lineas.append(linea)

            return "\n".join(lineas)

        elif nombre == "listar_materiales_obra":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."
            materiales = db.listar_materiales_compra(obra_id=obra["id"])
            if not materiales:
                return f"No hay materiales registrados para *{obra['nombre']}*."

            lineas = [f"📦 *Materiales comprados — {obra['nombre']}*\n"]
            for m in materiales:
                cant   = m.get("cantidad")
                unidad = m.get("unidad", "")
                pt     = m.get("precio_total")
                pu     = m.get("precio_unitario")
                fecha_mov = ""
                moneda_mov = ""
                if m.get("movimientos"):
                    fecha_mov  = m["movimientos"].get("fecha", "")
                    moneda_mov = m["movimientos"].get("moneda", "ARS")
                sym = {"ARS": "$", "USD": "U$S", "digital": "🔵"}.get(moneda_mov, "$")

                cant_str = f"{cant} {unidad}".strip() if cant is not None else ""
                if pt is not None:
                    precio_str = f"{sym} {pt:,.2f}"
                elif pu is not None:
                    precio_str = f"{sym} {pu:,.2f}/u"
                else:
                    precio_str = ""

                linea = f"• *{m['nombre']}*"
                if cant_str:
                    linea += f" ({cant_str})"
                if precio_str:
                    linea += f": {precio_str}"
                if fecha_mov:
                    linea += f"  _{fecha_mov}_"
                lineas.append(linea)

            return "\n".join(lineas)

        elif nombre == "suscribir_informe_semanal":
            obra = db.buscar_obra_por_nombre(params["nombre_obra"])
            if not obra:
                return f"❌ No encontré la obra '{params['nombre_obra']}'."

            # Usar teléfono del usuario actual si no se especifica otro
            telefono = params.get("telefono", "").strip() or telefono_usuario
            if not telefono:
                return "❌ No pude obtener el número de teléfono. Por favor indicalo manualmente (ej: +5491122334455)."

            contacto = db.agregar_contacto_obra(
                obra_id=obra["id"],
                telefono=telefono,
                nombre=params.get("nombre_contacto", ""),
                rol=params.get("rol", "operador"),
            )
            nombre_str = contacto.get("nombre") or telefono
            return (
                f"✅ *Suscripción activada*\n"
                f"*{nombre_str}* recibirá el informe semanal de *{obra['nombre']}*\n"
                f"Día: Lunes a las 8:00am 📅"
            )

        else:
            return f"Herramienta desconocida: {nombre}"

    except Exception as e:
        return f"❌ Error al ejecutar {nombre}: {str(e)}"


# ──────────────────────────────────────────────
# AGENTE PRINCIPAL
# ──────────────────────────────────────────────

_SYSTEM_PROMPT_BASE = """Sos el asistente financiero de una empresa constructora argentina.
Tu rol es ayudar al equipo a registrar y consultar información financiera de las obras de forma
rápida y simple a través de WhatsApp.

Podés ayudar con:
- Crear nuevas obras (proyectos de construcción)
- Registrar ingresos y egresos en la caja de cada obra (en pesos, dólares o medios digitales)
- Consultar saldos y movimientos por obra
- Registrar aportes y retiros de inversores
- Ver la cuenta corriente de cada inversor
- Registrar y comparar presupuestos de proveedores
- Generar informes financieros con totales por moneda, desglose por rubro y porcentajes
- Exportar movimientos como CSV descargable (link de descarga para Excel o Google Sheets)
- Definir y controlar el presupuesto total de una obra (con alertas automáticas al 80% y 100%)
- Cerrar obras y generar un informe de cierre detallado (por rubro, materiales vs mano de obra)
- Suscribir números a informes semanales automáticos (todos los lunes 8am)
- Procesar fotos de comprobantes/tickets de compra de materiales: extraer cada ítem con cantidad, unidad, precio unitario y precio total, y registrarlos en la base de datos
- Listar el historial de materiales comprados por obra (con cantidades y precios)

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
9. Detección de duplicados: si el sistema detecta un movimiento similar reciente, informá al usuario
   y esperá su confirmación antes de registrar. Si el usuario confirma con "sí registralo" o similar,
   volvé a llamar registrar_movimiento con forzar_registro=true.
10. Para cerrar una obra: primero generá el informe (solo_informe=true) para mostrárselo al usuario,
    esperá confirmación, y luego cerrá con solo_informe=false.
11. Para suscribir al informe semanal: el parámetro "telefono" ya viene pre-cargado con el número
    del usuario. Si quiere suscribir a otro número, pedile que lo indique.
12. Cuando el usuario envía una foto de un comprobante/ticket de compra:
    a) Analizá la imagen completa y extraé: proveedor, fecha (si figura), y la lista de ítems
       (nombre del material, cantidad, unidad de medida, precio unitario, precio total).
    b) Si no reconocés algún campo, omitilo — no inventes datos.
    c) Mostrá el resumen extraído al usuario con formato claro.
    d) Preguntá a qué obra asignarlo. Si hay una sola obra activa, usala directamente.
    e) Confirmá el total y esperá un "sí" o confirmación antes de registrar.
    f) Al confirmar, llamá a registrar_comprobante_materiales con todos los ítems.
    g) Si la imagen no es un ticket/comprobante de materiales, informalo amablemente.
"""


def build_system_prompt(telefono_usuario: str) -> str:
    """Construye el system prompt incluyendo el teléfono del usuario actual."""
    return _SYSTEM_PROMPT_BASE + f"\nEl número de WhatsApp del usuario actual es: {telefono_usuario}\n"


# Mantener compatibilidad con código existente
SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE

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

    # System prompt dinámico con teléfono del usuario (para suscripción a informes)
    system_prompt = build_system_prompt(telefono)

    # Bucle agentico: el agente puede llamar herramientas varias veces
    max_iterations = 5
    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
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
                    resultado = ejecutar_herramienta(block.name, block.input, telefono_usuario=telefono)
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


def procesar_mensaje_con_imagen(
    telefono: str,
    mensaje_usuario: str,
    imagen_base64: str,
    imagen_media_type: str,
) -> str:
    """
    Procesa un mensaje de WhatsApp que incluye una imagen (comprobante de compra).
    Construye un mensaje multimodal con la imagen y el texto, luego corre el mismo
    bucle agéntico que procesar_mensaje.
    """
    # Guardar el texto del usuario en historial (sin imagen, para no saturar la BD)
    db.guardar_mensaje(telefono, "user", mensaje_usuario or "📷 Comprobante de compra")

    # Construir historial previo (últimas 10 interacciones, excluyendo el mensaje actual)
    historial = db.obtener_historial(telefono, limite=10)
    # Excluir el último mensaje que acabamos de guardar
    messages = [{"role": m["rol"], "content": m["contenido"]} for m in historial[:-1]]

    # Construir el mensaje multimodal con imagen + texto
    contenido_multimodal = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": imagen_media_type,
                "data": imagen_base64,
            },
        },
        {
            "type": "text",
            "text": mensaje_usuario or "Adjunté un comprobante de compra.",
        },
    ]
    messages.append({"role": "user", "content": contenido_multimodal})

    system_prompt = build_system_prompt(telefono)

    # Bucle agéntico (igual que procesar_mensaje)
    max_iterations = 5
    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            texto = " ".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            db.guardar_mensaje(telefono, "assistant", texto)
            return texto

        elif response.stop_reason == "tool_use":
            resultados_tools = []
            for block in response.content:
                if block.type == "tool_use":
                    resultado = ejecutar_herramienta(block.name, block.input, telefono_usuario=telefono)
                    resultados_tools.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": resultado,
                    })
            messages.append({"role": "user", "content": resultados_tools})

        else:
            break

    respuesta_fallback = "Hubo un problema procesando la imagen. Por favor intentá de nuevo."
    db.guardar_mensaje(telefono, "assistant", respuesta_fallback)
    return respuesta_fallback
