import sqlite3

conn = sqlite3.connect(":memory:")
conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
conn.execute(
    "INSERT INTO test_fts VALUES (?)",
    ("QXDM 2026 Oct 27 10:00:00.123 [00] 0x1FE7 Test",)
)

res = conn.execute(
    """
    SELECT rowid, snippet(test_fts, 0, '[', ']', '...', 10)
    FROM test_fts
    WHERE test_fts MATCH ?
    """,
    ("QXDM",)
).fetchone()

print("✅ FTS5 is available and working." if res else "❌ FTS5 test failed.")
print(res)