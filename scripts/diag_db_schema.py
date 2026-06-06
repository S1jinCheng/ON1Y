import sqlite3

c = sqlite3.connect(r"D:\On1y\data\on1y.db")
print("schema_version", c.execute("select max(version) from schema_migrations").fetchone())
for name in ("raw_items", "pending_urls", "distilled_items"):
    row = c.execute(
        "select sql from sqlite_master where type='table' and name=?", (name,)
    ).fetchone()
    print(f"\n=== {name} ===")
    print(row[0] if row else "MISSING")
print("\npending user2", c.execute(
    "select status, count(*) from pending_urls where user_id=2 group by status"
).fetchall())
print("raw user2", c.execute(
    "select count(*) from raw_items where user_id=2"
).fetchone())
print("\nindexes raw_items")
for r in c.execute(
    "select name, sql from sqlite_master where tbl_name='raw_items'"
).fetchall():
    print(r)
