"""Strict structural fingerprint used only for known legacy SQLite baselines."""
import json

def schema(connection):
    con=connection
    objects=list(con.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version' AND type IN ('table','view','trigger') ORDER BY type,name"))
    result={}
    for kind,name in objects:
        if kind!='table':
            raise ValueError(f'Unexpected {kind}: {name}')
        quoted='"'+name.replace('"','""')+'"'
        columns=[list(x[1:6]) for x in con.execute(f'PRAGMA table_info({quoted})')]
        foreign_keys=sorted([list(x[2:8]) for x in con.execute(f'PRAGMA foreign_key_list({quoted})')])
        indexes=[]
        for row in con.execute(f'PRAGMA index_list({quoted})'):
            _,ix,unique,origin,partial=row
            ixq='"'+ix.replace('"','""')+'"'
            cols=[x[2] for x in con.execute(f'PRAGMA index_info({ixq})')]
            indexes.append([unique,origin,partial,cols])
        indexes.sort(key=lambda x:json.dumps(x))
        table_sql=con.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone()[0]
        # Preserve CHECK clauses and other constraints that PRAGMA table_info omits.
        table_sql=' '.join(table_sql.split())
        named_index_sql=sorted(' '.join(r[0].split()) for r in con.execute('SELECT sql FROM sqlite_master WHERE type="index" AND tbl_name=? AND sql IS NOT NULL',(name,)))
        result[name]={'columns':columns,'foreign_keys':foreign_keys,'indexes':indexes,'table_sql':table_sql,'named_index_sql':named_index_sql}
    return result
