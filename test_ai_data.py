import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

data = [
#ID ,Quantity Sold, Sale Date  
(1,20,"2026-03-01"),
(1,25,"2026-03-02"),
(1,30,"2026-03-03"),
(1,28,"2026-03-04"),
(1,35,"2026-03-05"),
(1,40,"2026-03-06"),
(1,38,"2026-03-07"),
(1,45,"2026-03-08"),
(2,50,"2026-03-09"),
(2,48,"2026-03-10"),
(2,55,"2026-03-11"),
(2,60,"2026-03-12"),
(2,58,"2026-03-13"),
(2,65,"2026-03-14"),
(2,65,"2026-03-15"),
(2,65,"2026-03-16"),
(2,63,"2026-03-17"),
(2,70,"2026-03-18")
]

# Optional cleanup: remove old test sales for these product IDs
product_ids = sorted({row[0] for row in data})
placeholders = ",".join(["?"] * len(product_ids))
cursor.execute(
    f"DELETE FROM sales WHERE product_id IN ({placeholders})",
    product_ids
)

cursor.executemany(
"INSERT INTO sales(product_id,quantity_sold,sale_date) VALUES(?,?,?)",
data
)

conn.commit()
conn.close()

print("Test sales data inserted")
