import psycopg2
import psycopg2.extras
from typing import List, Dict, Optional, Tuple
import logging
import time
from config import Config

class DatabaseManager:
    def __init__(self):
        self.config = Config()
        self.connection = None
        self._cache = {}
        self._cache_ttl = 300 # 5 minutes

    def _get_cached(self, key):
        if key in self._cache:
            if time.time() - self._cache[key]['time'] < self._cache_ttl:
                return self._cache[key]['data']
        return None

    def _set_cache(self, key, data):
        self._cache[key] = {'time': time.time(), 'data': data}
        
    def connect(self):
        """Establish connection to PostgreSQL database"""
        try:
            self.connection = psycopg2.connect(
                host=self.config.DB_HOST,
                port=self.config.DB_PORT,
                database=self.config.DB_NAME,
                user=self.config.DB_USER,
                password=self.config.DB_PASSWORD
            )
            logging.info("Database connection established successfully")
            return True
        except Exception as e:
            logging.error(f"Database connection failed: {e}")
            return False
    
    def disconnect(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logging.info("Database connection closed")
    
    def get_locations(self) -> List[str]:
        """
        Get all unique locations from the database for the location selector
        
        Returns:
            List of unique location strings
        """
        cached = self._get_cached('locations')
        if cached is not None:
            return cached

        if not self.connection:
            if not self.connect():
                return []
        
        try:
            query = """
                SELECT DISTINCT location 
                FROM properties 
                WHERE location IS NOT NULL AND location != '' AND location != 'N/A'
                ORDER BY location
            """
            
            cursor = self.connection.cursor()
            cursor.execute(query)
            locations = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            self._set_cache('locations', locations)
            return locations
            
        except Exception as e:
            logging.error(f"Error fetching locations: {e}")
            return []
    
    def get_property_types(self) -> List[str]:
        """
        Get all unique property types from the database for the property type selector
        
        Returns:
            List of unique property type strings
        """
        cached = self._get_cached('property_types')
        if cached is not None:
            return cached

        if not self.connection:
            if not self.connect():
                return []
        
        try:
            query = """
                SELECT DISTINCT property_type 
                FROM properties 
                WHERE property_type IS NOT NULL AND property_type != '' AND property_type != 'N/A'
                ORDER BY property_type
            """
            
            cursor = self.connection.cursor()
            cursor.execute(query)
            property_types = [row[0] for row in cursor.fetchall()]
            cursor.close()
            
            self._set_cache('property_types', property_types)
            return property_types
            
        except Exception as e:
            logging.error(f"Error fetching property types: {e}")
            return []
    

    
        if not self.connection:
            if not self.connect():
                return None
        
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except Exception as e:
            logging.error(f"Error fetching user: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Fetch a user by their username"""
        if not self.connection:
            if not self.connect():
                return None
        
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            cursor.close()
            return dict(user) if user else None
        except Exception as e:
            logging.error(f"Error fetching user: {e}")
            return None

    def get_properties(self, filters: Dict, limit: int = None, offset: int = None) -> Dict:
        """
        Get properties based on filters with pagination support
        
        Args:
            filters: Dictionary containing filter criteria
            limit: Maximum number of records to return
            offset: Number of records to skip
            
        Returns:
            Dictionary containing 'properties' list and 'total_count' int
        """
        if not self.connection:
            if not self.connect():
                return {'properties': [], 'total_count': 0}
        
        try:
            base_query = """
                FROM properties 
                WHERE 1=1
            """
            params = []
            
            # Price range filtering with NULL handling
            if filters.get('min_price') is not None:
                # If min_price is provided, exclude NULL prices and include properties with price >= min_price
                base_query += " AND price >= %s AND price IS NOT NULL"
                params.append(filters['min_price'])
            
            if filters.get('max_price') is not None:
                # If max_price is provided, exclude NULL prices and include properties with price <= max_price
                base_query += " AND price <= %s AND price IS NOT NULL"
                params.append(filters['max_price'])
            
            # Location filtering - handle both single location and multiple locations
            if filters.get('location'):
                # Single location (backward compatibility)
                location = filters['location'].strip()
                base_query += " AND (LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))"
                params.append(f"%{location}%")
                params.append(f"{location}%")
            elif filters.get('locations'):
                # Multiple locations
                locations = filters['locations']
                if locations:
                    location_conditions = []
                    for location in locations:
                        location_conditions.append("(LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))")
                        params.append(f"%{location.strip()}%")
                        params.append(f"{location.strip()}%")
                    base_query += f" AND ({' OR '.join(location_conditions)})"
            
            # Property type filtering
            if filters.get('property_type'):
                base_query += " AND property_type = %s"
                params.append(filters['property_type'])
            
            # Bedrooms filtering with NULL handling
            if filters.get('min_beds') is not None:
                # If min_beds is provided, exclude NULL bedrooms and include properties with bedrooms >= min_beds
                base_query += " AND bedrooms >= %s AND bedrooms IS NOT NULL"
                params.append(filters['min_beds'])
            
            if filters.get('max_beds') is not None:
                # If max_beds is provided, exclude NULL bedrooms and include properties with bedrooms <= max_beds
                base_query += " AND bedrooms <= %s AND bedrooms IS NOT NULL"
                params.append(filters['max_beds'])
            
            # Bathrooms filtering with NULL handling
            if filters.get('min_baths') is not None:
                # If min_baths is provided, exclude NULL bathrooms and include properties with bathrooms >= min_baths
                base_query += " AND bathrooms >= %s AND bathrooms IS NOT NULL"
                params.append(filters['min_baths'])
            
            if filters.get('max_baths') is not None:
                # If max_baths is provided, exclude NULL bathrooms and include properties with bathrooms <= max_baths
                base_query += " AND bathrooms <= %s AND bathrooms IS NOT NULL"
                params.append(filters['max_baths'])
            
            # First, get the total count for pagination
            count_query = "SELECT COUNT(*) " + base_query
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(count_query, params)
            total_count_row = cursor.fetchone()
            total_count = list(total_count_row.values())[0] if total_count_row else 0
            
            # Then get the actual paginated records
            query = """
                SELECT 
                    id,
                    title,
                    property_type,
                    location,
                    price as property_price,
                    bedrooms as num_beds,
                    bathrooms as num_baths,
                    living_area,
                    land_area,
                    source as website_source,
                    image_filename,
                    reference,
                    property_url,
                    created_at,
                    updated_at
            """ + base_query
            
            # Add sorting with multiple criteria
            sort_by = filters.get('sort_by', 'created_at')
            sort_dir = filters.get('sort_dir', 'DESC').upper()
            
            # Map frontend columns to db columns
            sort_column_map = {
                'price': 'price',
                'location': 'location',
                'property_type': 'property_type',
                'bedrooms': 'bedrooms',
                'bathrooms': 'bathrooms',
                'living_area': 'living_area',
                'land_area': 'land_area',
                'source': 'source',
                'created_at': 'created_at'
            }
            
            db_sort_col = sort_column_map.get(sort_by, 'created_at')
            if sort_dir not in ['ASC', 'DESC']:
                sort_dir = 'DESC'
                
            if db_sort_col == 'created_at':
                query += f" ORDER BY {db_sort_col} {sort_dir}, price ASC"
            else:
                # Push nulls to the bottom regardless of direction
                query += f" ORDER BY {db_sort_col} {sort_dir} NULLS LAST, created_at DESC"
            
            # Add pagination
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            if offset is not None:
                query += " OFFSET %s"
                params.append(offset)
            
            cursor.execute(query, params)
            properties = cursor.fetchall()
            cursor.close()
            
            # Log the search for debugging
            logging.info(f"Search executed with {len(params)} params, found {len(properties)} properties out of {total_count} total")
            
            return {
                'properties': [dict(prop) for prop in properties],
                'total_count': total_count
            }
            
        except Exception as e:
            logging.error(f"Error fetching properties: {e}")
            return {'properties': [], 'total_count': 0}
    
    def get_property_by_id(self, property_id: str) -> Optional[Dict]:
        """Get a specific property by ID"""
        if not self.connection:
            if not self.connect():
                return None
        
        try:
            query = """
                SELECT 
                    id,
                    title,
                    property_type,
                    location,
                    price as property_price,
                    bedrooms as num_beds,
                    bathrooms as num_baths,
                    living_area,
                    land_area,
                    source as website_source,
                    image_filename,
                    reference,
                    property_url,
                    created_at,
                    updated_at
                FROM properties 
                WHERE id = %s
            """
            
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, (property_id,))
            property_data = cursor.fetchone()
            cursor.close()
            
            return dict(property_data) if property_data else None
            
        except Exception as e:
            logging.error(f"Error fetching property {property_id}: {e}")
            return None
    
    def get_statistics(self) -> Dict:
        """Get basic statistics about the property database"""
        cached = self._get_cached('statistics')
        if cached is not None:
            return cached

        if not self.connection:
            if not self.connect():
                return {}
        
        try:
            stats = {}
            cursor = self.connection.cursor()
            
            # Combine total, avg, min, and max into a single query to reduce network latency
            cursor.execute("""
                SELECT 
                    COUNT(*),
                    AVG(CASE WHEN price > 0 THEN price ELSE NULL END),
                    MIN(CASE WHEN price > 0 THEN price ELSE NULL END),
                    MAX(CASE WHEN price > 0 THEN price ELSE NULL END)
                FROM properties
            """)
            total, avg_price, min_price, max_price = cursor.fetchone()
            
            stats['total_properties'] = total
            stats['avg_price'] = avg_price or 0
            stats['price_range'] = (min_price or 0, max_price or 0)
            
            # Properties by type
            cursor.execute("SELECT property_type, COUNT(*) FROM properties GROUP BY property_type")
            stats['by_type'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}
            
            # Properties by source
            cursor.execute("SELECT source, COUNT(*) FROM properties GROUP BY source")
            stats['by_source'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}
            
            cursor.close()
            self._set_cache('statistics', stats)
            return stats
            
        except Exception as e:
            logging.error(f"Error fetching statistics: {e}")
            return {}
