import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

username = input("Enter username: ")
email = input("Enter email: ")
password = input("Enter password: ")

print("Select role")
print("1. admin")
print("2. staff")

choice = input("Enter choice: ")

if choice == "1":
    role = "admin"
else:
    role = "staff"

cursor.execute("""
INSERT INTO users(username,email,password,role,approved)
VALUES(?,?,?,?,?)
""",(username,email,password,role,1))

conn.commit()
conn.close()

print("User added successfully")