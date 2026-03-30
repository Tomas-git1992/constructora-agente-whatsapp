-- ============================================================
-- SCHEMA: Agente Financiero - Empresa Constructora
-- Base de datos: Supabase (PostgreSQL)
-- ============================================================

-- Habilitar extensión para UUIDs
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- OBRAS (proyectos de construcción)
-- ============================================================
CREATE TABLE obras (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    direccion   TEXT,
    fecha_inicio DATE,
    estado      TEXT NOT NULL DEFAULT 'activa'
                    CHECK (estado IN ('activa', 'finalizada', 'suspendida')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INVERSORES
-- ============================================================
CREATE TABLE inversores (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre      TEXT NOT NULL,
    telefono    TEXT,
    email       TEXT,
    notas       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- PARTICIPACIÓN INVERSOR-OBRA (cuenta corriente por obra)
-- ============================================================
CREATE TABLE obra_inversores (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obra_id                 UUID NOT NULL REFERENCES obras(id) ON DELETE CASCADE,
    inversor_id             UUID NOT NULL REFERENCES inversores(id) ON DELETE CASCADE,
    porcentaje_participacion DECIMAL(5,2) CHECK (porcentaje_participacion BETWEEN 0 AND 100),
    notas                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(obra_id, inversor_id)
);

-- ============================================================
-- RUBROS (categorías de trabajo: mano de obra, materiales, etc.)
-- ============================================================
CREATE TABLE rubros (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre      TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Rubros predeterminados para construcción
INSERT INTO rubros (nombre, descripcion) VALUES
    ('Mano de Obra',        'Pagos a personal y subcontratistas'),
    ('Materiales',          'Compra de materiales de construcción'),
    ('Equipos y Herramientas', 'Alquiler o compra de maquinaria y herramientas'),
    ('Honorarios Profesionales', 'Arquitectos, ingenieros, gestores'),
    ('Servicios',           'Agua, electricidad, gas, internet en obra'),
    ('Transporte y Logística', 'Fletes, traslados, combustible'),
    ('Administrativos',     'Gastos de oficina, seguros, impuestos'),
    ('Varios',              'Gastos no clasificados en otras categorías');

-- ============================================================
-- PROVEEDORES
-- ============================================================
CREATE TABLE proveedores (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre      TEXT NOT NULL,
    telefono    TEXT,
    email       TEXT,
    rubro_id    UUID REFERENCES rubros(id),
    cuit        TEXT,
    notas       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- MOVIMIENTOS (ingresos y egresos por obra)
-- ============================================================
CREATE TABLE movimientos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obra_id         UUID NOT NULL REFERENCES obras(id) ON DELETE CASCADE,
    tipo            TEXT NOT NULL CHECK (tipo IN ('ingreso', 'egreso')),
    monto           DECIMAL(15,2) NOT NULL CHECK (monto > 0),
    moneda          TEXT NOT NULL CHECK (moneda IN ('ARS', 'USD', 'digital')),
    rubro_id        UUID REFERENCES rubros(id),
    proveedor_id    UUID REFERENCES proveedores(id),
    descripcion     TEXT NOT NULL,
    fecha           DATE NOT NULL DEFAULT CURRENT_DATE,
    registrado_por  TEXT,
    comprobante_url TEXT,
    notas           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para consultas frecuentes
CREATE INDEX idx_movimientos_obra    ON movimientos(obra_id);
CREATE INDEX idx_movimientos_fecha   ON movimientos(fecha);
CREATE INDEX idx_movimientos_moneda  ON movimientos(moneda);
CREATE INDEX idx_movimientos_tipo    ON movimientos(tipo);
CREATE INDEX idx_movimientos_rubro   ON movimientos(rubro_id);

-- ============================================================
-- APORTES DE INVERSORES
-- ============================================================
CREATE TABLE aportes_inversores (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obra_id     UUID NOT NULL REFERENCES obras(id) ON DELETE CASCADE,
    inversor_id UUID NOT NULL REFERENCES inversores(id) ON DELETE CASCADE,
    monto       DECIMAL(15,2) NOT NULL CHECK (monto > 0),
    moneda      TEXT NOT NULL CHECK (moneda IN ('ARS', 'USD', 'digital')),
    tipo        TEXT NOT NULL DEFAULT 'aporte'
                    CHECK (tipo IN ('aporte', 'retiro', 'prestamo', 'devolucion')),
    descripcion TEXT,
    fecha       DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_aportes_obra     ON aportes_inversores(obra_id);
CREATE INDEX idx_aportes_inversor ON aportes_inversores(inversor_id);

-- ============================================================
-- PRESUPUESTOS (comparación por rubro y proveedor)
-- ============================================================
CREATE TABLE presupuestos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    obra_id         UUID NOT NULL REFERENCES obras(id) ON DELETE CASCADE,
    rubro_id        UUID REFERENCES rubros(id),
    proveedor_id    UUID REFERENCES proveedores(id),
    descripcion     TEXT NOT NULL,
    monto           DECIMAL(15,2) NOT NULL CHECK (monto > 0),
    moneda          TEXT NOT NULL CHECK (moneda IN ('ARS', 'USD')),
    fecha           DATE NOT NULL DEFAULT CURRENT_DATE,
    validez_dias    INTEGER,
    estado          TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente', 'aprobado', 'rechazado')),
    notas           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_presupuestos_obra    ON presupuestos(obra_id);
CREATE INDEX idx_presupuestos_rubro   ON presupuestos(rubro_id);
CREATE INDEX idx_presupuestos_estado  ON presupuestos(estado);

-- ============================================================
-- CONVERSACIONES (historial de mensajes por usuario)
-- ============================================================
CREATE TABLE conversaciones (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telefono_usuario TEXT NOT NULL,
    rol             TEXT NOT NULL CHECK (rol IN ('user', 'assistant')),
    contenido       TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conv_telefono ON conversaciones(telefono_usuario);
CREATE INDEX idx_conv_created  ON conversaciones(created_at);

-- ============================================================
-- VISTAS ÚTILES
-- ============================================================

-- Vista: saldo de caja por obra y moneda
CREATE OR REPLACE VIEW vista_saldo_cajas AS
SELECT
    o.nombre AS obra,
    m.moneda,
    SUM(CASE WHEN m.tipo = 'ingreso' THEN m.monto ELSE -m.monto END) AS saldo,
    SUM(CASE WHEN m.tipo = 'ingreso' THEN m.monto ELSE 0 END)        AS total_ingresos,
    SUM(CASE WHEN m.tipo = 'egreso'  THEN m.monto ELSE 0 END)        AS total_egresos
FROM movimientos m
JOIN obras o ON o.id = m.obra_id
GROUP BY o.nombre, m.moneda
ORDER BY o.nombre, m.moneda;

-- Vista: cuenta corriente de inversores por obra
CREATE OR REPLACE VIEW vista_cuenta_corriente_inversores AS
SELECT
    o.nombre        AS obra,
    i.nombre        AS inversor,
    a.moneda,
    SUM(CASE WHEN a.tipo IN ('aporte', 'prestamo') THEN a.monto
             WHEN a.tipo IN ('retiro', 'devolucion') THEN -a.monto
             ELSE 0 END) AS saldo_neto,
    SUM(CASE WHEN a.tipo IN ('aporte', 'prestamo')   THEN a.monto ELSE 0 END) AS total_aportes,
    SUM(CASE WHEN a.tipo IN ('retiro', 'devolucion') THEN a.monto ELSE 0 END) AS total_retiros
FROM aportes_inversores a
JOIN obras     o ON o.id = a.obra_id
JOIN inversores i ON i.id = a.inversor_id
GROUP BY o.nombre, i.nombre, a.moneda
ORDER BY o.nombre, i.nombre, a.moneda;

-- Vista: gastos por rubro y obra
CREATE OR REPLACE VIEW vista_gastos_por_rubro AS
SELECT
    o.nombre  AS obra,
    r.nombre  AS rubro,
    m.moneda,
    SUM(m.monto) AS total_gastado,
    COUNT(*)     AS cantidad_movimientos
FROM movimientos m
JOIN obras  o ON o.id = m.obra_id
JOIN rubros r ON r.id = m.rubro_id
WHERE m.tipo = 'egreso'
GROUP BY o.nombre, r.nombre, m.moneda
ORDER BY o.nombre, total_gastado DESC;
