"""Property listings: search, lookup, statistics and manual off-market records.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras
import logging
import datetime
import uuid
from typing import Dict, List, Optional
from app.config import Config


class PropertiesMixin:
    """Property listings: search, lookup, statistics and manual off-market records."""

    
    def get_locations(self) -> List[str]:
        """
        Get all unique locations from the database for the location selector
        
        Returns:
            List of unique location strings
        """
        cached = self._get_cached('locations')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
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

        if not self.connection or self.connection.closed:
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

    def get_properties(self, filters: Dict, limit: int = None, offset: int = None) -> Dict:
        """
        Get properties based on filters with pagination support
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'properties': [], 'total_count': 0}

        try:
            base_query, params = self._build_filter_query(filters)
            
            stock_mode = filters.get('stock_mode', 'active')
            # Get the dynamic stats for the current filters
            count_query = "SELECT COUNT(*) as active_properties, COUNT(*) FILTER (WHERE p.member_id IS NULL OR p.is_representative = TRUE) as unique_properties " + base_query
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(count_query, params)
            stats_row = cursor.fetchone()
            
            active_properties = stats_row['active_properties'] if stats_row else 0
            unique_properties = stats_row['unique_properties'] if stats_row else 0
            
            # Now append stock mode for the actual paginated query
            if stock_mode == 'unique':
                base_query += " AND (p.member_id IS NULL OR p.is_representative = TRUE)"
                
            total_count = unique_properties if stock_mode == 'unique' else active_properties
            
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
                    image_filename_2,
                    image_filename_3,
                    map_filename,
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at,
                    sardo_reference,
                    group_id,
                    group_code,
                    group_match_type,
                    has_manual_link,
                    auto_matched,
                    is_representative,
                    COALESCE(duplicate_count, 1) as duplicate_count,
                    COALESCE(tags, '{}') as tags,
                    source_type,
                    market_visibility,
                    resort_area,
                    sub_area,
                    address,
                    coordinates,
                    construction_year,
                    renovation_year,
                    energy_rating,
                    source_contact_name,
                    source_contact_email,
                    source_contact_phone,
                    source_agent,
                    introduced_by,
                    date_introduced,
                    notes
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
                'website_source': 'source',
                'property_status': 'property_status',
                'first_seen_at': 'first_seen_at',
                'last_seen_at': 'last_seen_at',
                'status_last_changed_at': 'status_last_changed_at',
                'created_at': 'created_at'
            }
            
            # Default to created_at if invalid sort column
            db_sort_col = sort_column_map.get(sort_by, 'created_at')
            if sort_dir not in ['ASC', 'DESC']:
                sort_dir = 'DESC'
                
            if db_sort_col == 'created_at':
                query += f" ORDER BY {db_sort_col} {sort_dir}, price ASC"
            elif db_sort_col == 'price':
                # Push P.O.A. prices (-1, 0, NULL) to the bottom regardless of direction
                query += f" ORDER BY CASE WHEN price IS NULL OR price <= 0 THEN 1 ELSE 0 END ASC, price {sort_dir}, created_at DESC"
            else:
                # Push nulls to the bottom regardless of direction
                query += f" ORDER BY {db_sort_col} {sort_dir} NULLS LAST, created_at DESC"
            
            # Add secondary sort by id for consistent pagination
            query += ", id DESC"
            
            # Add pagination
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
                
            if offset is not None:
                query += " OFFSET %s"
                params.append(offset)
                
            cursor.execute(query, params)
            records = cursor.fetchall()
            cursor.close()
            
            return {
                'properties': [dict(record) for record in records],
                'total_count': total_count,
                'stats': {
                    'active_properties': active_properties,
                    'unique_properties': unique_properties,
                    'duplicate_listings': max(0, active_properties - unique_properties)
                }
            }
            
        except Exception as e:
            logging.error(f"Error fetching properties: {e}")
            return {'properties': [], 'total_count': 0}
    
    def get_property_by_id(self, property_id: str) -> Optional[Dict]:
        """
        Get a single property by its ID
        
        Args:
            property_id: ID of the property
            
        Returns:
            Property dictionary or None if not found
        """
        if not self.connection or self.connection.closed:
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
                    image_filename_2,
                    image_filename_3,
                    map_filename,
                    reference,
                    property_url,
                    property_status,
                    previous_status,
                    first_seen_at,
                    last_seen_at,
                    status_last_changed_at,
                    created_at,
                    updated_at,
                    source_type,
                    market_visibility,
                    resort_area,
                    sub_area,
                    address,
                    coordinates,
                    construction_year,
                    renovation_year,
                    energy_rating,
                    source_contact_name,
                    source_contact_email,
                    source_contact_phone,
                    source_agent,
                    introduced_by,
                    date_introduced,
                    COALESCE(tags, '{}') as tags,
                    notes
                FROM properties
                WHERE id = %s
            """
            
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, (property_id,))
            property_data = cursor.fetchone()
            cursor.close()
            
            if not property_data:
                return None
            data = dict(property_data)
            data['documents'] = self.get_property_documents(property_id)
            return data
            
        except Exception as e:
            logging.error(f"Error fetching property {property_id}: {e}")
            return None

    def update_property_scraped_details(self, property_id: str, construction_year: str, energy_rating: str) -> bool:
        """Update construction year and energy rating in the database for a property"""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE properties 
                SET construction_year = %s, energy_rating = %s, updated_at = NOW()
                WHERE id = %s
            """, (construction_year, energy_rating, property_id))
            cursor.close()
            return True
        except Exception as e:
            logging.error(f"Error updating scraped details for property {property_id}: {e}")
            return False
    
    def get_statistics(self) -> Dict:
        """Get basic statistics about the property database"""
        cached = self._get_cached('statistics')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
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

            # Properties by status
            cursor.execute("SELECT property_status, COUNT(*) FROM properties GROUP BY property_status")
            stats['by_status'] = {k if k is not None else 'Unknown': v for k, v in cursor.fetchall()}

            # Active stock excludes Sold and Delisted listings
            cursor.execute(
                "SELECT COUNT(*) FROM properties WHERE property_status <> ALL(%s)",
                (Config.INACTIVE_STATUSES,)
            )
            stats['active_properties'] = cursor.fetchone()[0]

            # Unique stock calculation (active stock minus duplicate surplus)
            cursor.execute("""
                SELECT COALESCE(COUNT(m.id) - COUNT(DISTINCT m.group_id), 0)
                FROM property_group_members m
                JOIN properties p ON p.id = m.property_id
                WHERE p.property_status <> ALL(%s);
            """, (Config.INACTIVE_STATUSES,))
            duplicate_surplus = cursor.fetchone()[0] or 0
            stats['unique_properties'] = max(0, stats['active_properties'] - duplicate_surplus)
            stats['duplicate_listings'] = duplicate_surplus

            cursor.close()
            self._set_cache('statistics', stats)
            return stats

        except Exception as e:
            logging.error(f"Error fetching statistics: {e}")
            return {}

    def get_property_group_info(self, property_id: str) -> Optional[Dict]:
        """Get duplicate group metadata and all agency listings for a property."""
        from app.services.grouping_service import GroupingEngine
        engine = GroupingEngine(self.connection)
        return engine.get_property_group_info(property_id)

    def recalculate_unique_property_groups(self) -> Dict:
        """Run the grouping engine to refresh all duplicate groups."""
        from app.services.grouping_service import GroupingEngine
        # The rebuild is one transaction; give it its own connection so it can't
        # swallow (or be rolled back by) other requests on the shared one.
        try:
            conn = self._open_connection()
        except Exception as e:
            logging.error(f"Error opening connection for grouping: {e}")
            return {'success': False, 'error': 'Database connection failed'}
        try:
            res = GroupingEngine(conn).run_grouping()
        finally:
            conn.close()
        self._cache.pop('statistics', None)
        return res

    def mark_properties_as_duplicates(self, property_ids: List[str], created_by: str = None) -> Dict:
        """Manually link properties as the same physical property, then regroup.

        Every pair among the selected properties is stored, so removing one of
        them later keeps the rest linked.
        """
        clean_ids = []
        for pid in property_ids or []:
            pid = str(pid).strip()
            if pid and pid not in clean_ids:
                clean_ids.append(pid)
        if len(clean_ids) < 2:
            return {'success': False, 'error': 'Select at least two properties to mark as duplicates'}

        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id::text FROM properties WHERE id::text = ANY(%s::text[])", (clean_ids,))
            found = {row[0] for row in cursor.fetchall()}
            missing = [pid for pid in clean_ids if pid not in found]
            if missing:
                cursor.close()
                return {'success': False, 'error': f'Property not found: {", ".join(missing)}'}

            pairs = [(a, b, created_by) for i, a in enumerate(clean_ids) for b in clean_ids[i + 1:]]
            links_created = 0
            for a, b, user in pairs:
                cursor.execute("""
                    INSERT INTO manual_duplicate_links (property_id_a, property_id_b, created_by)
                    VALUES (LEAST(%s::uuid, %s::uuid), GREATEST(%s::uuid, %s::uuid), %s)
                    ON CONFLICT (property_id_a, property_id_b) DO NOTHING
                """, (a, b, a, b, user))
                links_created += cursor.rowcount
            cursor.close()
        except Exception as e:
            logging.error(f"Error marking properties as duplicates: {e}")
            return {'success': False, 'error': str(e)}

        regroup = self.recalculate_unique_property_groups()
        return {
            'success': True,
            'properties_linked': len(clean_ids),
            'links_created': links_created,
            'regrouped': bool(regroup.get('success')),
            'warning': None if regroup.get('success')
                       else f"Listings linked, but the duplicate groups could not be rebuilt: {regroup.get('error')}"
        }

    def remove_manual_duplicate_links(self, property_id: str) -> Dict:
        """Remove every manual duplicate link involving a property, then regroup."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                DELETE FROM manual_duplicate_links
                WHERE property_id_a::text = %s OR property_id_b::text = %s
            """, (property_id, property_id))
            links_removed = cursor.rowcount
            cursor.close()
        except Exception as e:
            logging.error(f"Error removing manual duplicate links for {property_id}: {e}")
            return {'success': False, 'error': str(e)}

        if links_removed == 0:
            return {'success': False, 'error': 'This property has no manual duplicate links'}

        regroup = self.recalculate_unique_property_groups()

        # It can still be grouped if it also matches automatically (same price, plot and beds).
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1 FROM property_group_members WHERE property_id::text = %s", (property_id,))
        still_grouped = cursor.fetchone() is not None
        cursor.close()
        return {'success': True, 'links_removed': links_removed, 'still_grouped': still_grouped}

    def get_sources(self) -> List[str]:
        """Get the distinct agent/source values, for the source filter."""
        cached = self._get_cached('sources')
        if cached is not None:
            return cached

        if not self.connection or self.connection.closed:
            if not self.connect():
                return []

        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT DISTINCT source FROM properties
                WHERE source IS NOT NULL AND source != '' AND source != 'N/A'
                ORDER BY source
            """)
            sources = [row[0] for row in cursor.fetchall()]
            cursor.close()
            self._set_cache('sources', sources)
            return sources
        except Exception as e:
            logging.error(f"Error fetching sources: {e}")
            return []

    def create_manual_property(self, data: Dict, user_id: int, force: bool = False) -> Dict:
        """Create a new manual off-market property with duplicate detection."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            property_type = data.get('property_type', 'Villa')
            bedrooms = data.get('bedrooms')
            try:
                bedrooms_int = int(bedrooms) if bedrooms is not None and str(bedrooms).strip() != '' else None
            except ValueError:
                bedrooms_int = None
                
            price = data.get('price')
            try:
                price = int(float(price)) if price is not None and str(price).strip() != '' else None
            except ValueError:
                price = None

            location = data.get('location', '').strip()
            coordinates = data.get('coordinates', '').strip()

            # Duplicate listing detection (spec section 5)
            if not force and not data.get('confirm_duplicate'):
                dup_conditions = ["property_type = %s", "source_type = 'scraped'"]
                dup_params = [property_type]
                
                if bedrooms_int is not None:
                    dup_conditions.append("bedrooms::varchar = %s")
                    dup_params.append(str(bedrooms_int))
                    
                if price is not None and price > 0:
                    dup_conditions.append("price >= %s AND price <= %s")
                    dup_params.extend([int(price * 0.95), int(price * 1.05)])
                    
                loc_conds = []
                if location:
                    loc_conds.append("location ILIKE %s")
                    dup_params.append(f"%{location}%")
                if coordinates:
                    loc_conds.append("coordinates = %s")
                    dup_params.append(coordinates)
                if loc_conds:
                    dup_conditions.append(f"({' OR '.join(loc_conds)})")
                    
                if len(dup_conditions) > 2:  # Ensure we have more than just type + source
                    dup_query = f"SELECT id, title, location, price, property_url FROM properties WHERE {' AND '.join(dup_conditions)} LIMIT 5"
                    cursor.execute(dup_query, dup_params)
                    matches = cursor.fetchall()
                    if matches:
                        cursor.close()
                        return {
                            'success': False,
                            'duplicate_warning': True,
                            'matches': [dict(m) for m in matches],
                            'message': f"Notice: {len(matches)} similar public listing(s) exist in this area. Proceed with creation?"
                        }

            # Generate synthetic URL and unique reference
            prop_uuid = str(uuid.uuid4())
            property_url = f"sardo://manual/{prop_uuid}"
            
            reference = data.get('reference', '').strip()
            if not reference:
                reference = f"SARDO-OM-{prop_uuid[:8].upper()}"

            # Helper for numeric conversion
            def to_int(val):
                try: return int(float(val)) if val is not None and str(val).strip() != '' else None
                except: return None

            def to_str(val):
                if val is None: return None
                s = str(val).strip()
                if s == '' or s == 'None': return None
                try:
                    f = float(s)
                    if f == int(f): return str(int(f))
                except:
                    pass
                return s

            now_dt = datetime.datetime.now()
            status = data.get('property_status', 'Off Market')
            sold_at = now_dt if status == 'Sold' else None
            
            insert_query = """
                INSERT INTO properties (
                    id, title, property_type, location, price, bedrooms, bathrooms,
                    living_area, land_area, source, reference, property_url,
                    property_status, raw_status_text, source_type, market_visibility,
                    resort_area, sub_area, address, coordinates, construction_year,
                    renovation_year, energy_rating, source_contact_name,
                    source_contact_email, source_contact_phone, source_agent,
                    introduced_by, date_introduced, notes, created_at, updated_at,
                    first_seen_at, last_seen_at, status_last_changed_at, sold_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                ) RETURNING id;
            """
            
            params = (
                prop_uuid,
                data.get('title', 'Untitled Off-Market Opportunity'),
                property_type,
                location,
                to_int(price),
                to_str(bedrooms),
                to_str(data.get('bathrooms')),
                to_str(data.get('living_area') or data.get('build_size')),
                to_str(data.get('land_area') or data.get('plot_size')),
                'Manual / Off-Market',
                reference,
                property_url,
                status,
                'Manual Off-Market Creation',
                'manual',
                data.get('market_visibility', 'off_market'),
                data.get('resort_area'),
                data.get('sub_area'),
                data.get('address'),
                coordinates,
                str(data.get('construction_year')) if data.get('construction_year') else None,
                str(data.get('renovation_year')) if data.get('renovation_year') else None,
                str(data.get('energy_rating')) if data.get('energy_rating') else None,
                data.get('source_contact_name'),
                data.get('source_contact_email'),
                data.get('source_contact_phone'),
                data.get('source_agent'),
                data.get('introduced_by'),
                data.get('date_introduced') or now_dt,
                data.get('notes'),
                now_dt, now_dt, now_dt, now_dt, now_dt, sold_at
            )
            
            cursor.execute(insert_query, params)
            ret_id = cursor.fetchone()['id']
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Created manual property {ret_id} ({reference}) by user {user_id}")
            return {'success': True, 'property_id': str(ret_id), 'reference': reference}
            
        except Exception as e:
            logging.error(f"Error creating manual property: {e}")
            return {'success': False, 'error': str(e)}

    def update_manual_property(self, property_id: str, data: Dict, user_id: int) -> Dict:
        """Update an existing manual property and audit status/price changes."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            existing = cursor.fetchone()
            if not existing:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            if existing.get('source_type') != 'manual':
                cursor.close()
                return {'success': False, 'error': 'Only manual properties can be updated via this endpoint'}
                
            old_status = existing.get('property_status')
            new_status = data.get('property_status', old_status)
            
            old_price = existing.get('price')
            try:
                new_price = float(data.get('price')) if data.get('price') is not None and str(data.get('price')).strip() != '' else None
            except ValueError:
                new_price = old_price

            now_dt = datetime.datetime.now()
            
            status_changed = (old_status != new_status)
            price_changed = (old_price != new_price)
            
            if status_changed or price_changed:
                audit_text = 'Manual Admin Update'
                if price_changed:
                    audit_text += f" (Price: {old_price} -> {new_price})"
                if status_changed:
                    audit_text += f" (Status: {old_status} -> {new_status})"
                    
                audit_sql = """
                    INSERT INTO property_status_history (
                        property_id, previous_status, new_status, changed_at, raw_status_text, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(audit_sql, (property_id, old_status, new_status, now_dt, audit_text, now_dt))

            def to_int(val):
                try: return int(float(val)) if val is not None and str(val).strip() != '' else None
                except: return None

            def to_str(val):
                if val is None: return None
                s = str(val).strip()
                if s == '' or s == 'None': return None
                try:
                    f = float(s)
                    if f == int(f): return str(int(f))
                except:
                    pass
                return s

            update_sql = """
                UPDATE properties SET
                    title = %s,
                    property_type = %s,
                    location = %s,
                    price = %s,
                    bedrooms = %s,
                    bathrooms = %s,
                    living_area = %s,
                    land_area = %s,
                    property_status = %s,
                    previous_status = CASE WHEN %s THEN %s ELSE previous_status END,
                    status_last_changed_at = CASE WHEN %s THEN %s ELSE status_last_changed_at END,
                    sold_at = CASE WHEN %s THEN %s ELSE sold_at END,
                    market_visibility = %s,
                    resort_area = %s,
                    sub_area = %s,
                    address = %s,
                    coordinates = %s,
                    construction_year = %s,
                    renovation_year = %s,
                    energy_rating = %s,
                    source_contact_name = %s,
                    source_contact_email = %s,
                    source_contact_phone = %s,
                    source_agent = %s,
                    introduced_by = %s,
                    notes = %s,
                    updated_at = %s
                WHERE id = %s
            """
            
            params = (
                data.get('title', existing.get('title')),
                data.get('property_type', existing.get('property_type')),
                data.get('location', existing.get('location')),
                new_price,
                to_str(data.get('bedrooms', existing.get('bedrooms'))),
                to_str(data.get('bathrooms', existing.get('bathrooms'))),
                to_str(data.get('living_area', existing.get('living_area')) or data.get('build_size')),
                to_str(data.get('land_area', existing.get('land_area')) or data.get('plot_size')),
                new_status,
                status_changed, old_status,
                status_changed, now_dt,
                status_changed and new_status == 'Sold' and not existing.get('sold_at'), now_dt,
                data.get('market_visibility', existing.get('market_visibility') or 'off_market'),
                data.get('resort_area', existing.get('resort_area')),
                data.get('sub_area', existing.get('sub_area')),
                data.get('address', existing.get('address')),
                data.get('coordinates', existing.get('coordinates')),
                str(data.get('construction_year')) if data.get('construction_year') else existing.get('construction_year'),
                str(data.get('renovation_year')) if data.get('renovation_year') else existing.get('renovation_year'),
                str(data.get('energy_rating')) if data.get('energy_rating') else existing.get('energy_rating'),
                data.get('source_contact_name', existing.get('source_contact_name')),
                data.get('source_contact_email', existing.get('source_contact_email')),
                data.get('source_contact_phone', existing.get('source_contact_phone')),
                data.get('source_agent', existing.get('source_agent')),
                data.get('introduced_by', existing.get('introduced_by')),
                data.get('notes', existing.get('notes')),
                now_dt,
                property_id
            )
            
            cursor.execute(update_sql, params)
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Updated manual property {property_id} by user {user_id}")
            return {'success': True, 'property_id': property_id}
            
        except Exception as e:
            logging.error(f"Error updating manual property {property_id}: {e}")
            return {'success': False, 'error': str(e)}

    def delete_manual_property(self, property_id: str) -> Dict:
        """Delete a manual off-market property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM properties WHERE id = %s", (property_id,))
            existing = cursor.fetchone()
            if not existing:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            if existing.get('source_type') != 'manual':
                cursor.close()
                return {'success': False, 'error': 'Cannot delete scraped listings manually'}
                
            cursor.execute("DELETE FROM properties WHERE id = %s AND source_type = 'manual'", (property_id,))
            cursor.close()
            
            self._cache.pop('locations', None)
            self._cache.pop('property_types', None)
            self._cache.pop('statistics', None)
            
            logging.info(f"Deleted manual property {property_id}")
            return {'success': True}
            
        except Exception as e:
            logging.error(f"Error deleting manual property {property_id}: {e}")
            return {'success': False, 'error': str(e)}
