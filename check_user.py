#!/usr/bin/env python3

import sqlite3

# Connect to the database
conn = sqlite3.connect('reflex.db')
cursor = conn.cursor()

# Check if user table exists and has api_key column
cursor.execute("PRAGMA table_info(user)")
columns = cursor.fetchall()
print("User table columns:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

# Check if hkhatiri user exists and has API key
cursor.execute("SELECT username, api_key FROM user WHERE username = 'hkhatiri'")
user = cursor.fetchone()

if user:
    print(f"\nUser found: {user[0]}")
    print(f"API Key: {user[1]}")
    
    # If API key is None, set it
    if user[1] is None:
        print("API key is None, setting it to Hkhatiri1471...")
        cursor.execute("UPDATE user SET api_key = 'Hkhatiri1471' WHERE username = 'hkhatiri'")
        conn.commit()
        print("API key updated!")
else:
    print("User hkhatiri not found!")

conn.close() 