"""Genera el mapa completo de la base GeoCattle en PlantUML a partir del catálogo de PostgreSQL.

Lee solo el catálogo (sin datos de negocio). Usa DATABASE_URL o, si falta, la base del prototipo
nativo de Windows (`.env.academic`). Escribe `modelo_bd_completo.puml` junto a este script.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# Agrupación por dominio. Toda tabla nueva sin dominio cae en «Otros» y debe clasificarse aquí.
DOMAINS = {
    'Identidad y acceso': ['users', 'owner_accounts', 'platform_admins', 'roles', 'permissions', 'role_permissions',
                           'farm_memberships', 'login_sessions', 'auth_challenges', 'mfa_factors',
                           'mfa_recovery_codes', 'account_tokens', 'invitations', 'invitation_mail',
                           'trust_grants', 'support_requests'],
    'Predio y configuración': ['farms', 'features', 'farm_features', 'sectors', 'geofences', 'geofence_sectors',
                               'rule_settings', 'pasture_assignments'],
    'Ganado y movimientos': ['animals', 'animal_holdings', 'animal_states', 'animal_measurements', 'animal_reports',
                             'sag_movements', 'movement_animals', 'movement_status_events'],
    'Salud': ['health_events', 'health_schedules', 'health_treatments'],
    'Dispositivos y captura': ['devices', 'device_configs', 'device_candidates', 'device_candidate_captures',
                               'assignments', 'gateways', 'gateway_candidates', 'gateway_bus_receipts', 'maintenance'],
    'Telemetría, eventos y avisos': ['telemetry', 'telemetry_receptions', 'events', 'event_actions', 'notifications',
                                     'notification_attempts'],
    'Cambios, auditoría y operación': ['change_requests', 'change_decisions', 'change_applications', 'audit_log',
                                       'request_metrics', 'schema_migrations'],
}
COLORS = ['#E8F3EC', '#EAF1F8', '#FBF3E4', '#F8E9EC', '#EFEAF8', '#E6F4F4', '#F1F1F1']
# Las FK hacia farms y las de autoría hacia users se marcan en la columna pero no se dibujan como línea.
IDENTITY_USER_COLUMNS = {'user_id', 'owner_user_id', 'accepted_user_id'}

COLUMNS = """
select c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull
from pg_class c join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
where n.nspname = 'public' and c.relkind in ('r', 'p') and a.attnum > 0 and not a.attisdropped
  and c.relname <> 'spatial_ref_sys'
order by c.relname, a.attnum
"""
CONSTRAINTS = """
select c.relname, con.contype,
  array(select a.attname from unnest(con.conkey) with ordinality k(n, i)
        join pg_attribute a on a.attrelid = con.conrelid and a.attnum = k.n order by k.i),
  f.relname
from pg_constraint con join pg_class c on c.oid = con.conrelid
join pg_namespace n on n.oid = c.relnamespace left join pg_class f on f.oid = con.confrelid
where n.nspname = 'public' and con.contype in ('p', 'f', 'u') and c.relname <> 'spatial_ref_sys'
"""


def database_url() -> str:
    url = os.environ.get('DATABASE_URL')
    if not url:
        sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
        import prototype_windows  # noqa: PLC0415
        url = prototype_windows.environment()['DATABASE_URL']
    return url.replace('postgresql+psycopg://', 'postgresql://')


def read_catalog():
    import psycopg  # noqa: PLC0415
    with psycopg.connect(database_url()) as connection:
        connection.read_only = True
        cursor = connection.cursor()
        cursor.execute(COLUMNS)
        columns = cursor.fetchall()
        cursor.execute(CONSTRAINTS)
        constraints = cursor.fetchall()
        cursor.execute('select max(version) from schema_migrations')
        migration = cursor.fetchone()[0]
    return columns, constraints, migration


def short_type(text: str) -> str:
    text = text.replace('timestamp with time zone', 'timestamptz').replace('character varying', 'varchar')
    return text.replace('geometry(Polygon,4326)', 'geometry(Polygon)').replace('geometry(Point,4326)', 'geometry(Point)')


def render(columns, constraints, migration) -> str:
    tables: dict[str, list] = defaultdict(list)
    for table, name, kind, not_null in columns:
        tables[table].append((name, short_type(kind), not_null))
    primary, unique, fks = defaultdict(set), defaultdict(list), defaultdict(list)
    for table, kind, cols, parent in constraints:
        if kind == 'p':
            primary[table] = set(cols)
        elif kind == 'u':
            unique[table].append(set(cols))
        else:
            fks[table].append((list(cols), parent))

    known = {t for names in DOMAINS.values() for t in names}
    domains = dict(DOMAINS)
    extra = sorted(set(tables) - known)
    if extra:
        domains['Otros'] = extra

    lines = ['@startuml modelo_bd_completo', 'hide circle', 'hide empty members', 'skinparam linetype ortho', 'skinparam shadowing false',
             'skinparam defaultFontName Arial', 'skinparam defaultFontSize 11', 'skinparam nodesep 40',
             'skinparam ranksep 70', 'skinparam class {', '  BorderColor #2F5D46', '  ArrowColor #4A6B5A',
             '  HeaderBackgroundColor #FFFFFF', '}',
             f'title Mapa completo de la base de datos GeoCattle (PostgreSQL/PostGIS, migración {migration})', '']
    for index, (domain, names) in enumerate(domains.items()):
        lines.append(f'package "{domain}" as dom{index} {COLORS[index % len(COLORS)]} {{')
        for table in names:
            if table not in tables:
                continue
            fk_columns = {}
            for cols, parent in fks[table]:
                for col in cols:
                    if col != 'farm_id' or parent == 'farms':
                        fk_columns.setdefault(col, parent)
            lines.append(f'  entity "{table}" as {table} {{')
            pk_rows = [c for c in tables[table] if c[0] in primary[table]]
            other = [c for c in tables[table] if c[0] not in primary[table]]
            for name, kind, not_null in pk_rows:
                ref = f' <<FK {fk_columns[name]}>>' if name in fk_columns else ''
                lines.append(f'    * <b>{name}</b> : {kind} <<PK>>{ref}')
            if pk_rows:
                lines.append('    --')
            for name, kind, not_null in other:
                ref = f' <<FK {fk_columns[name]}>>' if name in fk_columns else ''
                lines.append(f'    {"* " if not_null else ""}{name} : {kind}{ref}')
            lines.append('  }')
        lines.append('}')
        lines.append('')

    seen = set()
    for table in sorted(fks):
        nullable = {name: not not_null for name, _, not_null in tables[table]}
        for cols, parent in fks[table]:
            main = [c for c in cols if c != 'farm_id'] or cols
            key = (table, parent, main[0])
            if key in seen or parent == 'farms' or (parent == 'users' and main[0] not in IDENTITY_USER_COLUMNS):
                continue
            seen.add(key)
            optional = any(nullable.get(c, False) for c in main)
            one_to_one = set(cols) == primary[table] or set(cols) in unique[table] or set(main) in unique[table]
            parent_end = '|o' if optional else '||'
            child_end = 'o|' if one_to_one else 'o{'
            lines.append(f'{parent} {parent_end}--{child_end} {table} : {", ".join(main)}')
    lines += ['', 'legend right',
              '  <b>Notación</b> (pata de gallo / IE)',
              '  * columna NOT NULL · <<PK>> clave primaria · <<FK tabla>> clave foránea',
              '  ||--o{ uno a muchos obligatorio · |o--o{ opcional · o| uno a uno',
              '  Las FK hacia <b>farms</b> (aislamiento por predio) y las de autoría hacia <b>users</b>',
              '  (*_by, actor_id, recipient_id) se indican en la columna y no se dibujan como línea.',
              '  Las FK compuestas (farm_id, x) garantizan que la referencia pertenezca al mismo predio.',
              'endlegend', '@enduml', '']
    return '\n'.join(line for line in lines if line is not None)


def main() -> None:
    columns, constraints, migration = read_catalog()
    target = HERE / 'modelo_bd_completo.puml'
    target.write_text(render(columns, constraints, migration), encoding='utf-8')
    print(f'{target.name}: {len({c[0] for c in columns})} tablas, migración {migration}')


if __name__ == '__main__':
    main()
