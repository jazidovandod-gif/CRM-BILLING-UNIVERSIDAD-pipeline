import pandas as pd
from pathlib import Path

RAW = Path('/home/jovyan/data/raw')
if not RAW.exists():
    RAW = Path('data/raw')

FILES = {
    'university': ['semesters', 'professors', 'students', 'courses', 'enrollments', 'grades'],
    'billing':    ['customers', 'products', 'subscriptions', 'invoices', 'invoice_items', 'payments'],
    'crm':        ['accounts', 'contacts', 'leads', 'opportunities', 'opportunity_contacts', 'activities'],
}

def load(domain, table):
    return pd.read_csv(RAW / domain / f'{table}.csv', dtype=str, keep_default_na=False, na_values=[''])

data = {(d, t): load(d, t) for d, tables in FILES.items() for t in tables}

# LAS 18 RELACIONES DE FOREIGN KEYS COMPLETAS
ALL_18_FKS = [
    # University (5)
    ('university', 'enrollments',          'student_id',     'university', 'students',     'student_id'),
    ('university', 'enrollments',          'course_id',      'university', 'courses',      'course_id'),
    ('university', 'enrollments',          'semester_id',    'university', 'semesters',    'semester_id'),
    ('university', 'courses',              'professor_id',   'university', 'professors',   'professor_id'),
    ('university', 'grades',               'enrollment_id',  'university', 'enrollments',  'enrollment_id'),
    
    # Billing (6)
    ('billing',    'subscriptions',        'customer_id',    'billing',    'customers',    'customer_id'),
    ('billing',    'subscriptions',        'product_id',     'billing',    'products',     'product_id'),
    ('billing',    'invoices',             'customer_id',    'billing',    'customers',    'customer_id'),
    ('billing',    'invoice_items',        'invoice_id',     'billing',    'invoices',     'invoice_id'),
    ('billing',    'invoice_items',        'product_id',     'billing',    'products',     'product_id'),
    ('billing',    'payments',             'invoice_id',     'billing',    'invoices',     'invoice_id'),
    
    # Cross-domain (1)
    ('billing',    'customers',            'external_ref',   'university', 'students',     'student_id'),
    
    # CRM (6)
    ('crm',        'contacts',             'account_id',     'crm',        'accounts',     'account_id'),
    ('crm',        'opportunities',        'account_id',     'crm',        'accounts',     'account_id'),
    ('crm',        'opportunity_contacts', 'opportunity_id', 'crm',        'opportunities','opportunity_id'),
    ('crm',        'opportunity_contacts', 'contact_id',     'crm',        'contacts',     'contact_id'),
    ('crm',        'activities',           'contact_id',     'crm',        'contacts',     'contact_id'),
    ('crm',        'activities',           'opportunity_id', 'crm',        'opportunities','opportunity_id'),
]

rows = []
for cd, ct, ccol, parent_domain, pt, pcol in ALL_18_FKS:
    child_series = data[(cd, ct)][ccol].dropna()
    child_series = child_series[child_series != '']
    parent_set = set(data[(parent_domain, pt)][pcol].dropna())
    
    orphans = (~child_series.isin(parent_set)).sum()
    rows.append({
        '#': len(rows) + 1,
        'Tabla Hija (FK)': f"{ct}.{ccol}",
        'Tabla Padre (PK)': f"{pt}.{pcol}",
        'Registros No Nulos': len(child_series),
        'Registros Huérfanos': orphans,
        'Estado': '🟢 0 Huérfanos' if orphans == 0 else f'🔴 {orphans} Huérfanos'
    })

df_fks = pd.DataFrame(rows)
print("\n" + "="*85)
print("AUDITORÍA DE INTEGRIDAD REFERENCIAL DE LAS 18 FOREIGN KEYS COMPLETAS")
print("="*85)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
print(df_fks.to_string(index=False))

