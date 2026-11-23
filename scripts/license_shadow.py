#!/usr/bin/env python3
"""Read-only classification and shadow comparison. Never migrates or assigns rights."""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from sqlalchemy import create_engine, inspect, text

REVISIONS={'f60e00000001','4dbfc4c29581'}

def as_utc(value):
    if value is None:return None
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:return None
    if not isinstance(value,datetime):return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def report(conn):
    required={'users':{'id'},'account_access':{'user_id','disabled'},'licenses':{'id','user_id','active','expires_at'},'license_grants':{'id','user_id','activated_at','expires_at','revoked_at'},'license_entitlements':{'grant_id','platform','device_limit'},'alembic_version':{'version_num'}}
    inspector=inspect(conn)
    for table,columns in required.items():
        if not inspector.has_table(table) or not columns <= {x['name'] for x in inspector.get_columns(table)}:raise ValueError('Unsupported schema; no migration performed')
    versions=conn.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    if len(versions)!=1 or versions[0] not in REVISIONS:raise ValueError('Unsupported database revision')
    rows=lambda sql:conn.execute(text(sql)).mappings().all()
    users={r['id'] for r in rows('SELECT id FROM users')}
    disabled={r['user_id'] for r in rows('SELECT user_id, disabled FROM account_access') if r['disabled']}
    old=rows('SELECT id,user_id,active,expires_at FROM licenses ORDER BY id')
    grants=rows('SELECT id,user_id,activated_at,expires_at,revoked_at FROM license_grants ORDER BY id')
    snaps={r['grant_id']:r for r in rows('SELECT grant_id,platform,device_limit FROM license_entitlements')}
    now=datetime.now(timezone.utc)
    result={'mode':'read-only dry-run and shadow; no records transferred','revision':versions[0],'evaluated_at':now.isoformat(),'legacy':[],'grants':[],'shadow':[]}
    for x in old:
        exp=as_utc(x['expires_at']); reasons=[]
        if x['user_id'] not in users:reasons.append('OWNER_MISSING')
        if not x['active']:reasons.append('INACTIVE')
        if x['expires_at'] is not None and exp is None:reasons.append('EXPIRY_INVALID')
        if exp and exp<=now:reasons.append('EXPIRED')
        if x['active'] and x['expires_at'] is None:reasons.append('EXPIRY_UNKNOWN')
        # legacy table contains no platform, device limit, activation time or proven mapping.
        reasons.append('PLATFORM_LIMIT_PROVENANCE_UNKNOWN')
        category='invalid' if 'INACTIVE' in reasons or 'EXPIRED' in reasons else 'ambiguous'
        result['legacy'].append({'id':x['id'],'user_id':x['user_id'],'classification':category,'action':'skipped','reasons':reasons})
    for g in grants:
        snap=snaps.get(g['id']);start=as_utc(g['activated_at']);end=as_utc(g['expires_at']);reason=None
        if g['user_id'] not in users:reason='ACCOUNT_UNAVAILABLE'
        elif g['user_id'] in disabled:reason='ACCOUNT_BLOCKED'
        elif g['revoked_at'] is not None:reason='LICENSE_REVOKED'
        elif not start or start>now:reason='LICENSE_NOT_ACTIVE'
        elif not end or end<=now:reason='LICENSE_EXPIRED'
        elif not snap or snap['platform'] not in ('both','hassle','radmir') or not isinstance(snap['device_limit'],int) or snap['device_limit']<1:reason='ENTITLEMENT_UNAVAILABLE'
        category='existing_canonical' if reason is None else ('ambiguous' if reason in ('ACCOUNT_UNAVAILABLE','ENTITLEMENT_UNAVAILABLE') else 'invalid_or_inactive')
        result['grants'].append({'id':g['id'],'user_id':g['user_id'],'classification':category,'action':'preserved','v2_allowed':reason is None,'reason':reason})
    # Actual old v0.6 account endpoint selected latest legacy row and returned raw active;
    # this is not a historical proof of entitlement enforcement or platform/device access.
    latest={x['user_id']:x for x in old}
    for user in sorted(users):
        x=latest.get(user); old_flag=bool(x['active']) if x else None
        allowed=any(g['user_id']==user and g['v2_allowed'] for g in result['grants'])
        result['shadow'].append({'user_id':user,'legacy_latest_active_flag':old_flag,'v2_any_grant_allowed':allowed,'difference':old_flag is not None and old_flag!=allowed,'note':'legacy raw display flag versus v2 grant/account predicate; not device or platform access'})
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--sqlite',type=Path);g.add_argument('--postgres-url-env',metavar='ENV_NAME');p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.sqlite:
        path=a.sqlite.resolve(strict=True)
        if not path.is_file():raise ValueError('SQLite source must be an existing file')
        engine=create_engine('sqlite:///file:'+quote(str(path),safe='/')+'?mode=ro&uri=true',hide_parameters=True)
    else:
        url=os.environ.get(a.postgres_url_env,'')
        if not url.startswith(('postgresql://','postgresql+psycopg://')):raise ValueError('Environment variable must contain a PostgreSQL URL')
        engine=create_engine(url,hide_parameters=True)
    try:
        with engine.connect() as conn:
            if engine.dialect.name=='postgresql':conn.exec_driver_sql('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            elif engine.dialect.name=='sqlite':conn.exec_driver_sql('PRAGMA query_only=ON');conn.exec_driver_sql('BEGIN')
            else:raise ValueError('Unsupported database')
            data=report(conn)
        # Exclusive creation; report contains user and record IDs: keep private.
        fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
        print('Read-only report written; no rights changed.')
    finally:engine.dispose()
if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Do not print connection URL, SQL or driver details; they may contain secrets.
        print('Shadow scan failed; check path, connectivity, revision and schema.',file=sys.stderr);sys.exit(1)
