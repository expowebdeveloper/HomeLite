#!/usr/bin/env python3
"""
Database Setup Script for Property Insight

This script helps set up the required database schema for the Property Insight application.
"""

import psycopg2
import sys
import os
from dotenv import load_dotenv

def create_database_schema():
    """Create the required database schema"""
    
    # Load environment variables
    load_dotenv()
    
    # Database connection parameters
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    # SQL to create the properties table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS properties (
        id SERIAL PRIMARY KEY,
        property_price DECIMAL(12,2),
        property_location VARCHAR(255),
        property_type VARCHAR(100),
        num_beds INTEGER,
        num_baths INTEGER,
        website_source VARCHAR(100),
        image_url VARCHAR(500),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # SQL to create indexes for better performance
    create_indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(property_price);",
        "CREATE INDEX IF NOT EXISTS idx_properties_location ON properties(property_location);",
        "CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(property_type);",
        "CREATE INDEX IF NOT EXISTS idx_properties_beds ON properties(num_beds);",
        "CREATE INDEX IF NOT EXISTS idx_properties_baths ON properties(num_baths);",
        "CREATE INDEX IF NOT EXISTS idx_properties_source ON properties(website_source);",
        "CREATE INDEX IF NOT EXISTS idx_properties_created_at ON properties(created_at);"
    ]
    
    try:
        # Connect to database
        print("🔌 Connecting to database...")
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        # Create table
        print("📋 Creating properties table...")
        cursor.execute(create_table_sql)
        
        # Create indexes
        print("🔍 Creating database indexes...")
        for index_sql in create_indexes_sql:
            cursor.execute(index_sql)
        
        # Commit changes
        conn.commit()
        print("✅ Database schema created successfully!")
        
        # Check if table exists and show some info
        cursor.execute("SELECT COUNT(*) FROM properties;")
        count = cursor.fetchone()[0]
        print(f"📊 Current property count: {count}")
        
        # Show table structure
        cursor.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'properties' 
            ORDER BY ordinal_position;
        """)
        
        print("\n📋 Table structure:")
        print("-" * 50)
        for row in cursor.fetchall():
            print(f"{row[0]:<20} {row[1]:<15} {'NULL' if row[2] == 'YES' else 'NOT NULL'}")
        
        cursor.close()
        conn.close()
        
        print("\n🎉 Database setup completed successfully!")
        print("You can now run the Property Insight application.")
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def insert_sample_data():
    """Insert sample data for testing"""
    
    # Load environment variables
    load_dotenv()
    
    # Database connection parameters
    db_params = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT', '5432'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    # Sample data
    sample_properties = [
        (750000, 'Sydney CBD', 'Apartment', 2, 2, 'Domain', 'sample_images/sydney_apt_1.jpg'),
        (1200000, 'Bondi Beach', 'Villa', 3, 2, 'RealEstate', 'sample_images/bondi_villa_1.jpg'),
        (850000, 'Manly', 'Townhouse', 3, 2, 'AllHomes', 'sample_images/manly_townhouse_1.jpg'),
        (950000, 'North Sydney', 'Apartment', 2, 1, 'Domain', 'sample_images/north_sydney_apt_1.jpg'),
        (1500000, 'Mosman', 'House', 4, 3, 'RealEstate', 'sample_images/mosman_house_1.jpg'),
        (650000, 'Parramatta', 'Apartment', 1, 1, 'AllHomes', 'sample_images/parramatta_apt_1.jpg'),
        (1800000, 'Double Bay', 'Penthouse', 3, 3, 'Domain', 'sample_images/double_bay_penthouse_1.jpg'),
        (1100000, 'Surry Hills', 'Townhouse', 2, 2, 'RealEstate', 'sample_images/surry_hills_townhouse_1.jpg'),
    ]
    
    insert_sql = """
    INSERT INTO properties 
    (property_price, property_location, property_type, num_beds, num_baths, website_source, image_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    
    try:
        # Connect to database
        print("🔌 Connecting to database...")
        conn = psycopg2.connect(**db_params)
        cursor = conn.cursor()
        
        # Insert sample data
        print("📝 Inserting sample data...")
        for property_data in sample_properties:
            cursor.execute(insert_sql, property_data)
        
        # Commit changes
        conn.commit()
        
        # Show inserted data
        cursor.execute("SELECT COUNT(*) FROM properties;")
        count = cursor.fetchone()[0]
        print(f"✅ Sample data inserted! Total properties: {count}")
        
        cursor.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

def main():
    """Main function"""
    print("🏠 Property Insight - Database Setup")
    print("=" * 50)
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ Error: .env file not found!")
        print("Please create a .env file with your database configuration.")
        print("See env_example.txt for the required format.")
        sys.exit(1)
    
    # Check required environment variables
    required_vars = ['DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("❌ Error: Missing required database environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        sys.exit(1)
    
    print("✅ Environment variables loaded")
    
    # Create schema
    create_database_schema()
    
    # Ask if user wants to insert sample data
    print("\n" + "=" * 50)
    response = input("Would you like to insert sample data for testing? (y/n): ").lower().strip()
    
    if response in ['y', 'yes']:
        insert_sample_data()
    
    print("\n🎉 Setup completed! You can now run the application with:")
    print("   python app.py")

if __name__ == "__main__":
    main()
