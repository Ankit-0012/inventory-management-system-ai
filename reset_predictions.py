import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

cursor.execute("DELETE FROM predictions")

conn.commit()
conn.close()

print("Predictions reset done")