import logging
import uuid
import datetime
from typing import Dict, List, Optional
import psycopg2.extras

class GroupingEngine:
    """
    Engine to identify and group probable duplicate properties based on:
    - Identical PRICE (property_price)
    - Identical PLOT M2 (land_area)
    - Identical BEDS (bedrooms)
    - DIFFERENT SOURCE (source)
    
    Creates logical groupings in property_groups and property_group_members.
    """

    def __init__(self, connection):
        self.conn = connection
        self.logger = logging.getLogger('GroupingEngine')

    def run_grouping(self) -> Dict:
        """
        Executes the grouping algorithm over all active listings.
        """
        try:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Clear existing groups to do a fresh recalculation
            # Since property_group_members cascades from property_groups,
            # deleting groups deletes the members.
            cursor.execute("DELETE FROM property_group_members")
            cursor.execute("DELETE FROM property_groups")
            
            # Grouping Logic
            # We want to find sets of properties where price, land_area, and bedrooms are identical
            # AND there is more than 1 distinct source in the group.
            
            find_duplicates_query = """
                SELECT 
                    price as property_price, 
                    land_area, 
                    bedrooms as num_beds, 
                    COUNT(DISTINCT source) as distinct_sources,
                    array_agg(id) as property_ids
                FROM properties
                WHERE price IS NOT NULL 
                  AND land_area IS NOT NULL 
                  AND bedrooms IS NOT NULL
                  -- Only consider active/visible listings (not sold/delisted)
                  AND property_status NOT IN ('Sold', 'Delisted', 'Withdrawn')
                GROUP BY price, land_area, bedrooms
                HAVING COUNT(DISTINCT source) > 1
            """
            
            cursor.execute(find_duplicates_query)
            duplicate_groups = cursor.fetchall()
            
            total_groups = 0
            total_properties_grouped = 0
            
            for group in duplicate_groups:
                p_ids = group['property_ids']
                if isinstance(p_ids, str):
                    property_ids = p_ids.strip('{}').split(',')
                else:
                    property_ids = list(p_ids)
                
                # Create a new property group
                group_code = f"UPG-{uuid.uuid4().hex[:6].upper()}"
                
                cursor.execute(
                    "INSERT INTO property_groups (group_code) VALUES (%s) RETURNING id",
                    (group_code,)
                )
                group_id = cursor.fetchone()['id']
                total_groups += 1
                
                # Fetch full property details to determine the representative listing
                cursor.execute("""
                    SELECT id, image_filename, image_filename_2, image_filename_3, last_seen_at, updated_at
                    FROM properties
                    WHERE id = ANY(%s::uuid[])
                """, (property_ids,))
                
                props = cursor.fetchall()
                
                # Determine representative
                # Hierarchy:
                # 1. Most complete property data (hard to measure perfectly, we will use image count)
                # 2. Greatest number of images
                # 3. Most recently updated
                
                def score_property(p):
                    # Count images
                    img_count = sum(1 for k in ('image_filename', 'image_filename_2', 'image_filename_3') if p.get(k))
                    
                    # Use last_seen_at or updated_at for recency
                    recency = p.get('last_seen_at') or p.get('updated_at')
                    recency_ts = recency.timestamp() if isinstance(recency, datetime.datetime) else 0
                    
                    return (img_count, recency_ts)
                
                representative_id = None
                best_score = (-1, -1)
                
                for p in props:
                    score = score_property(p)
                    if score > best_score:
                        best_score = score
                        representative_id = p['id']
                
                # Insert members
                for pid in property_ids:
                    is_rep = (pid == representative_id)
                    cursor.execute("""
                        INSERT INTO property_group_members (group_id, property_id, is_representative)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (group_id, property_id) DO NOTHING
                    """, (group_id, pid, is_rep))
                    total_properties_grouped += 1
            
            self.conn.commit()
            cursor.close()
            
            return {
                'success': True,
                'groups_created': total_groups,
                'properties_grouped': total_properties_grouped
            }
            
        except Exception as e:
            self.logger.error(f"Failed to run grouping engine: {e}")
            try:
                self.conn.rollback()
            except:
                pass
            return {'success': False, 'error': str(e)}

    def get_property_group_info(self, property_id: str) -> Optional[Dict]:
        """
        Returns all properties in the same group as the given property.
        Used by the frontend modal to show all agency listings for a physical property.
        """
        try:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Find which group this property belongs to
            cursor.execute("""
                SELECT group_id FROM property_group_members WHERE property_id = %s
            """, (property_id,))
            row = cursor.fetchone()
            
            if not row:
                cursor.close()
                return {'has_group': False, 'message': 'No duplicate group found for this property'}
                
            group_id = row['group_id']
            
            # Get group code
            cursor.execute("SELECT group_code FROM property_groups WHERE id = %s", (group_id,))
            group_code = cursor.fetchone()['group_code']
            
            # Get all properties in this group
            cursor.execute("""
                SELECT p.*, m.is_representative 
                FROM property_group_members m
                JOIN properties p ON p.id = m.property_id
                WHERE m.group_id = %s
                ORDER BY m.is_representative DESC, p.price ASC
            """, (group_id,))
            
            members = [dict(r) for r in cursor.fetchall()]
            cursor.close()
            
            return {
                'has_group': True,
                'group_code': group_code,
                'total_agency_listings': len(members),
                'listings': members
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching group info for {property_id}: {e}")
            return {'has_group': False, 'error': str(e)}
