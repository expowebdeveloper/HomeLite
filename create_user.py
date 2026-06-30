#!/usr/bin/env python3
import sys
import psycopg2
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

def create_user(username, password):
    load_dotenv()
    
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    password_hash = generate_password_hash(password)
    
    try:
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        # Ensure table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Insert user
        cursor.execute("""
            INSERT INTO users (username, password_hash)
            VALUES (%s, %s)
            ON CONFLICT (username) 
            DO UPDATE SET password_hash = EXCLUDED.password_hash;
        """, (username, password_hash))
        
        conn.commit()
        print(f"✅ User '{username}' created/updated successfully!")
        
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"❌ Database error: {e}")

if __name__ == "__main__":
    import getpass
    
    print("--- SARDO360 User Creation ---")
    username = input("Enter username: ").strip()
    
    if not username:
        print("Username cannot be empty!")
        sys.exit(1)
        
    password = getpass.getpass("Enter password: ")
    
    if not password:
        print("Password cannot be empty!")
        sys.exit(1)
        
    confirm_password = getpass.getpass("Confirm password: ")
    
    if password != confirm_password:
        print("Passwords do not match!")
        sys.exit(1)
    
    create_user(username, password)
