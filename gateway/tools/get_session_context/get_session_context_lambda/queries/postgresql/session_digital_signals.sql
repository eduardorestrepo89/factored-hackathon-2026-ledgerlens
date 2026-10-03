-- session_digital_signals (PostgreSQL dialect, runs on Aurora DSQL)
--
-- App/web events from the 24 hours up to as_of that carry a signal, newest first.
-- Used by GetSessionContextUseCase; a failure here only makes the digital_signals
-- section unavailable.
--
-- Parameters (psycopg named placeholders):
--   customer_id  text       required (the use case strips and uppercases it)
--   as_of        timestamp  "now" as naive UTC (the AS_OF env var, or the real time)
--   limit        integer    max rows plus one (the extra row marks the section truncated)
--
-- The rules are checked in order and the first match wins, so an error on any
-- page is FAILED_ACTION. Matching on action as well keeps the signal when
-- page_title is NULL. Every other page (Inicio, Iniciar Sesión, Cerrar Sesión,
-- Préstamos, Cuenta de Ahorro, Pagar Servicios, Transferir, Mis Cuentas,
-- Productos) has no signal and is filtered out here, so the cap counts real
-- signals. event_id is selected only as a stable tie-break; the use case doesn't
-- map it.
--
-- TODO(ledgerlens): R3 - not yet run against a real Aurora DSQL cluster. Column
--   names follow docs/LATAM_Bank_ERD.md. The event_type, page_title and action
--   values are confirmed in the dataset (risk C1, 2026-10-01).
-- TODO(ledgerlens): R8 - digital_events isn't deduplicated; a duplicate event only
--   repeats a signal.
SELECT signals.*
FROM (
    SELECT e.event_date,
           CASE
             WHEN e.event_type = 'Error'                                             THEN 'FAILED_ACTION'
             WHEN e.page_title = 'Mis Movimientos' OR e.action = 'view_transactions' THEN 'REVIEWING_TRANSACTIONS'
             WHEN e.page_title = 'Tarjeta de Crédito'                                THEN 'VIEWING_CREDIT_CARD'
             WHEN e.page_title = 'Ayuda' OR e.action = 'view_help'                   THEN 'SEEKING_HELP'
           END AS signal,
           e.page_title,
           e.ip_country,
           e.ip_city,
           e.event_id
    FROM digital_events AS e
    WHERE e.customer_id = %(customer_id)s
      AND e.process_date >= (%(as_of)s::date - 1)
      AND e.event_date >  %(as_of)s - INTERVAL '24 hours'
      AND e.event_date <= %(as_of)s
) AS signals
WHERE signals.signal IS NOT NULL
ORDER BY signals.event_date DESC NULLS LAST, signals.event_id
LIMIT %(limit)s
