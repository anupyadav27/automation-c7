import json
import os
import psycopg2
from datetime import datetime, timezone

def seed():
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="threat_engine_inventory",
        user="postgres",
        password="password"
    )
    cur = conn.cursor()
    
    tenant_id = "local"
    scan_run_id = "mock-scan-real-setup"
    
    # Ensure tenant
    cur.execute("INSERT INTO tenants (tenant_id, tenant_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tenant_id, tenant_id))
    
    # Ensure scan report
    cur.execute("""
        INSERT INTO inventory_report (scan_run_id, tenant_id, started_at, completed_at, status, total_assets)
        VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
    """, (scan_run_id, tenant_id, datetime.now(timezone.utc), datetime.now(timezone.utc), "completed", 12))
    
    with open("test_assets_real.json", "r") as f:
        assets = json.load(f)
        if isinstance(assets, dict): assets = assets.get("assets", [])
        
    for asset in assets:
        asset_id = asset.get("asset_id", f"asset-{asset['resource_id']}")
        cur.execute("""
            INSERT INTO inventory_findings (
                asset_id, tenant_id, resource_uid, provider, account_id,
                region, resource_type, resource_id, name, tags,
                scan_run_id, latest_scan_run_id, updated_at, properties, configuration
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_id) DO UPDATE SET updated_at = EXCLUDED.updated_at
        """, (
            asset_id, tenant_id, asset["resource_uid"], asset["provider"], asset["account_id"],
            asset["region"], asset["resource_type"], asset["resource_id"], asset.get("name"),
            json.dumps(asset.get("tags", {})),
            scan_run_id, scan_run_id, datetime.now(timezone.utc),
            json.dumps(asset.get("metadata", {})),
            json.dumps(asset.get("metadata", {}).get("configuration", {}))
        ))
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully seeded {len(assets)} assets into the database.")

if __name__ == "__main__":
    seed()
