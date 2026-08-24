#!/usr/bin/env python3
"""
Migration 008: Global Tags Library Schema & Seeding
Creates the global_tags table and pre-seeds it with curated real estate tags.
"""
import sys
import os
import logging
import psycopg2

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

INITIAL_GLOBAL_TAGS = [
    # Views & Location
    {"name": "Sea View", "category": "Views & Location", "color": "#0284c7", "description": "Unobstructed or panoramic sea/ocean views"},
    {"name": "Golf Course Views", "category": "Views & Location", "color": "#059669", "description": "Frontline or overlooking golf fairway/greens"},
    {"name": "Beachfront", "category": "Views & Location", "color": "#0ea5e9", "description": "Direct access or frontline to the beach"},
    {"name": "Panoramic Views", "category": "Views & Location", "color": "#6366f1", "description": "Wide elevated scenic views of countryside/coast"},
    {"name": "Micro Location", "category": "Views & Location", "color": "#8b5cf6", "description": "Specific desirable enclave, street or cul-de-sac"},
    {"name": "Macro Location", "category": "Views & Location", "color": "#a855f7", "description": "Prime broader region (e.g. Golden Triangle, Quinta do Lago, Vale do Lobo)"},
    {"name": "Resort Frontline", "category": "Views & Location", "color": "#10b981", "description": "Located within premier luxury resort boundaries"},
    {"name": "Walking to Amenities", "category": "Views & Location", "color": "#14b8a6", "description": "Short walking distance to restaurants, shops, beach"},
    {"name": "South Facing", "category": "Views & Location", "color": "#f59e0b", "description": "Optimal sun exposure throughout the day"},
    
    # Features & Amenities
    {"name": "Private Pool", "category": "Features & Amenities", "color": "#3b82f6", "description": "Private swimming pool on property"},
    {"name": "Heated Pool", "category": "Features & Amenities", "color": "#2563eb", "description": "Pool equipped with heating system"},
    {"name": "Tennis / Padel Court", "category": "Features & Amenities", "color": "#16a34a", "description": "On-site private tennis or padel court"},
    {"name": "Gated Community", "category": "Features & Amenities", "color": "#475569", "description": "Secured private development with restricted entry"},
    {"name": "High Privacy", "category": "Features & Amenities", "color": "#64748b", "description": "Not overlooked, secluded grounds"},
    {"name": "Smart Home", "category": "Features & Amenities", "color": "#6366f1", "description": "Automated lighting, climate, security & audio systems"},
    {"name": "Landscaped Gardens", "category": "Features & Amenities", "color": "#15803d", "description": "Professionally landscaped grounds with irrigation"},
    
    # Investment & Legal
    {"name": "Rental License (AL)", "category": "Investment & Legal", "color": "#d97706", "description": "Alojamento Local touristic rental license in place"},
    {"name": "High Yield Investment", "category": "Investment & Legal", "color": "#b45309", "description": "Proven or projected strong rental yield"},
    {"name": "Renovation Project", "category": "Investment & Legal", "color": "#ea580c", "description": "Existing property suitable for complete modernization or rebuild"},
    {"name": "Plot with Approved Project", "category": "Investment & Legal", "color": "#c2410c", "description": "Land plot sold with architectural licenses/permits"},
    {"name": "Turnkey / New Build", "category": "Investment & Legal", "color": "#059669", "description": "Newly completed luxury construction with warranties"},
    
    # Style & Quality
    {"name": "Modern / Contemporary", "category": "Style & Quality", "color": "#4f46e5", "description": "Clean lines, floor-to-ceiling glass, open plan"},
    {"name": "Traditional Quinta", "category": "Style & Quality", "color": "#78350f", "description": "Authentic Portuguese country estate / rustic charm"},
    {"name": "Luxury Finish", "category": "Style & Quality", "color": "#7c3aed", "description": "High-end bespoke materials, marble, top appliances"},
    {"name": "Energy Efficient (A+)", "category": "Style & Quality", "color": "#16a34a", "description": "Solar panels, high insulation, A or A+ energy rating"}
]

def run_migration():
    config = Config()
    logging.info(f"Connecting to Database {config.DB_NAME} at {config.DB_HOST}:{config.DB_PORT} as {config.DB_USER}...")
    
    try:
        conn = psycopg2.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            connect_timeout=10
        )
        conn.autocommit = False
        cursor = conn.cursor()

        # 1. Create global_tags table
        logging.info("Creating global_tags table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_tags (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) UNIQUE NOT NULL,
                category VARCHAR(50) DEFAULT 'General',
                color VARCHAR(30) DEFAULT '#4f46e5',
                description TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_global_tags_name ON global_tags (LOWER(name));
            CREATE INDEX IF NOT EXISTS idx_global_tags_category ON global_tags (category);
        """)
        logging.info("global_tags table and indexes created successfully.")

        # 2. Insert seeded global tags
        logging.info(f"Seeding {len(INITIAL_GLOBAL_TAGS)} standard global tags...")
        for tag in INITIAL_GLOBAL_TAGS:
            cursor.execute("""
                INSERT INTO global_tags (name, category, color, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE 
                SET category = EXCLUDED.category,
                    color = EXCLUDED.color,
                    description = EXCLUDED.description;
            """, (tag["name"], tag["category"], tag["color"], tag["description"]))

        # 3. Also import any existing tags in the properties table into global_tags
        logging.info("Scanning properties table for any existing custom tags to import into global_tags...")
        cursor.execute("""
            INSERT INTO global_tags (name, category, color)
            SELECT DISTINCT unnest(tags) as name, 'Custom' as category, '#6366f1' as color
            FROM properties
            WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
            ON CONFLICT (name) DO NOTHING;
        """)

        conn.commit()
        
        # Verify count
        cursor.execute("SELECT COUNT(*) FROM global_tags;")
        total_count = cursor.fetchone()[0]
        logging.info(f"Migration completed successfully! Total global tags in library: {total_count}")
        
        cursor.close()
        conn.close()
        return True

    except Exception as e:
        logging.error(f"Migration 008 failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
