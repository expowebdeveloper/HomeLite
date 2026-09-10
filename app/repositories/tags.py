"""Per-property tags and the global tag catalogue.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras
import logging
import time
import re
from typing import List


class TagsMixin:
    """Per-property tags and the global tag catalogue."""


    def get_all_tags(self) -> List[Dict]:
        """Get all distinct tags in use across all properties, sorted with counts."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT tag, COUNT(*) as count
                FROM (
                    SELECT unnest(tags) as tag FROM properties WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                ) t
                WHERE tag IS NOT NULL AND tag != ''
                GROUP BY tag
                ORDER BY count DESC, tag ASC;
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [{'tag': row[0], 'count': row[1]} for row in rows]
        except Exception as e:
            logging.error(f"Error fetching tags: {e}")
            return []

    def get_global_tags(self) -> List[Dict]:
        """Get all curated global tags with real-time property usage counts."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT 
                    gt.id,
                    gt.name,
                    gt.category,
                    gt.color,
                    gt.description,
                    COALESCE(u.usage_count, 0) as usage_count
                FROM global_tags gt
                LEFT JOIN (
                    SELECT unnest(tags) as tag_name, COUNT(*) as usage_count
                    FROM properties
                    WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                    GROUP BY unnest(tags)
                ) u ON LOWER(gt.name) = LOWER(u.tag_name)
                ORDER BY 
                    CASE 
                        WHEN gt.category = 'Views & Location' THEN 1
                        WHEN gt.category = 'Features & Amenities' THEN 2
                        WHEN gt.category = 'Investment & Legal' THEN 3
                        WHEN gt.category = 'Style & Quality' THEN 4
                        ELSE 5
                    END,
                    u.usage_count DESC,
                    gt.name ASC;
            """)
            rows = cursor.fetchall()
            cursor.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logging.error(f"Error fetching global tags: {e}")
            return []

    def create_global_tag(self, name: str, category: str = 'General', color: str = '#4f46e5', description: str = '') -> Dict:
        """Create a new global tag in the library."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        clean_name = str(name).strip()
        if not clean_name:
            return {'success': False, 'error': 'Tag name cannot be empty'}
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                INSERT INTO global_tags (name, category, color, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                SET category = EXCLUDED.category,
                    color = EXCLUDED.color,
                    description = EXCLUDED.description
                RETURNING id, name, category, color, description;
            """, (clean_name, category.strip() or 'General', color.strip() or '#4f46e5', description.strip()))
            row = cursor.fetchone()
            self.connection.commit()
            cursor.close()
            return {'success': True, 'tag': dict(row)}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error creating global tag {name}: {e}")
            return {'success': False, 'error': str(e)}

    def delete_global_tag(self, name: str) -> Dict:
        """Delete a global tag from the library."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        clean_name = str(name).strip()
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM global_tags WHERE LOWER(name) = LOWER(%s);", (clean_name,))
            self.connection.commit()
            cursor.close()
            return {'success': True}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error deleting global tag {name}: {e}")
            return {'success': False, 'error': str(e)}

    def bulk_assign_tag_to_properties(self, property_ids: List[str], tag: str, action: str = 'add') -> Dict:
        """
        Add or remove a tag from multiple properties simultaneously.
        
        Args:
            property_ids: List of property IDs.
            tag: Tag name to add/remove.
            action: 'add' to append tag, 'remove' to remove tag.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}

        clean_tag = str(tag).strip()
        if not clean_tag:
            return {'success': False, 'error': 'Tag cannot be empty'}
        if not property_ids:
            return {'success': False, 'error': 'No properties selected'}

        try:
            cursor = self.connection.cursor()
            
            # If adding, ensure it exists in global_tags library
            if action == 'add':
                cursor.execute("""
                    INSERT INTO global_tags (name, category, color)
                    VALUES (%s, 'Custom', '#6366f1')
                    ON CONFLICT (name) DO NOTHING;
                """, (clean_tag,))

            # Fetch current tags of target properties
            cursor.execute("""
                SELECT id::text, COALESCE(tags, '{}') as tags 
                FROM properties 
                WHERE id::text = ANY(%s::text[]);
            """, (property_ids,))
            rows = cursor.fetchall()

            updates = []
            for row in rows:
                p_id, cur_tags = row[0], row[1]
                cur_tags = list(cur_tags or [])
                
                if action == 'add':
                    # Add if not already present
                    if not any(t.lower() == clean_tag.lower() for t in cur_tags):
                        cur_tags.append(clean_tag)
                        updates.append((cur_tags, p_id))
                elif action == 'remove':
                    # Remove if present
                    new_tags = [t for t in cur_tags if t.lower() != clean_tag.lower()]
                    if len(new_tags) != len(cur_tags):
                        updates.append((new_tags, p_id))

            if updates:
                psycopg2.extras.execute_batch(
                    cursor,
                    "UPDATE properties SET tags = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    updates
                )
                self.connection.commit()

            cursor.close()
            self._cache.pop('statistics', None)
            return {
                'success': True,
                'action': action,
                'tag': clean_tag,
                'updated_count': len(updates),
                'total_selected': len(property_ids)
            }
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error in bulk_assign_tag_to_properties: {e}")
            return {'success': False, 'error': str(e)}

    def update_property_tags(self, property_id: str, tags: List[str]) -> Dict:
        """Update tags array for a single property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
        try:
            clean_tags = []
            seen_lower = set()
            for t in (tags or []):
                t_clean = str(t).strip()
                if t_clean and t_clean.lower() not in seen_lower:
                    clean_tags.append(t_clean)
                    seen_lower.add(t_clean.lower())

            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE properties 
                SET tags = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s;
            """, (clean_tags, property_id))
            self.connection.commit()
            cursor.close()
            self._cache.pop('statistics', None)
            return {'success': True, 'tags': clean_tags}
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error updating property tags for {property_id}: {e}")
            return {'success': False, 'error': str(e)}

    def bulk_update_tags_from_csv(self, csv_rows: List[Dict], mode: str = 'replace') -> Dict:
        """
        Bulk update property tags from parsed CSV rows.
        
        Args:
            csv_rows: List of dicts with property identifier and tags.
            mode: 'replace' to overwrite existing tags, 'append' to merge with existing tags.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}

        if not csv_rows:
            return {'success': False, 'error': 'CSV file is empty or contains no rows'}

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Build an in-memory lookup map of all active properties
            cursor.execute("""
                SELECT 
                    id, 
                    reference, 
                    'SARDO' || (1099 + ROW_NUMBER() OVER(ORDER BY COALESCE(source, ''), COALESCE(image_filename, ''))) as sardo_reference,
                    COALESCE(tags, '{}') as current_tags
                FROM properties;
            """)
            all_props = cursor.fetchall()
            
            id_map = {}
            ref_map = {}
            sardo_map = {}
            numeric_sardo_map = {}
            
            for p in all_props:
                p_id = str(p['id'])
                id_map[p_id.lower()] = p
                
                if p.get('reference'):
                    ref_map[str(p['reference']).strip().lower()] = p
                    
                sardo_ref = str(p.get('sardo_reference', '')).strip().lower()
                if sardo_ref:
                    sardo_map[sardo_ref] = p
                    digits = ''.join(c for c in sardo_ref if c.isdigit())
                    if digits:
                        numeric_sardo_map[digits] = p

            matched_count = 0
            updated_count = 0
            unmatched_rows = []
            all_distinct_tags = set()
            updates_to_perform = []

            for row_idx, row in enumerate(csv_rows, start=1):
                prop_key = None
                for candidate in ['property_id', 'property id', 'id', 'sardo_reference', 'sardo ref', 'reference', 'ref']:
                    for k in row.keys():
                        if k and k.strip().lower() == candidate and row[k] is not None:
                            prop_key = str(row[k]).strip()
                            break
                    if prop_key:
                        break
                
                if not prop_key and len(row) > 0:
                    first_val = list(row.values())[0]
                    if first_val:
                        prop_key = str(first_val).strip()

                if not prop_key:
                    unmatched_rows.append({'row': row_idx, 'identifier': '(empty)', 'reason': 'Missing Property ID'})
                    continue

                raw_tags_str = None
                for candidate in ['tags', 'tag', 'property_tags', 'property tags', 'categories']:
                    for k in row.keys():
                        if k and k.strip().lower() == candidate and row[k] is not None:
                            raw_tags_str = str(row[k]).strip()
                            break
                    if raw_tags_str is not None:
                        break

                if raw_tags_str is None and len(row) > 1:
                    second_val = list(row.values())[1]
                    if second_val is not None:
                        raw_tags_str = str(second_val).strip()

                if raw_tags_str is None:
                    raw_tags_str = ''

                norm_key = prop_key.lower()
                matched_prop = (
                    id_map.get(norm_key) or 
                    sardo_map.get(norm_key) or 
                    ref_map.get(norm_key) or 
                    numeric_sardo_map.get(norm_key)
                )

                if not matched_prop:
                    unmatched_rows.append({'row': row_idx, 'identifier': prop_key, 'reason': f"No property found matching ID '{prop_key}'"})
                    continue

                matched_count += 1

                parsed_tags = []
                for part in re.split(r'[,;\n\r]+', raw_tags_str):
                    t = part.strip().strip('"').strip("'")
                    if t:
                        parsed_tags.append(t)

                new_tags = []
                seen_lower = set()
                
                if mode == 'append':
                    for existing_t in matched_prop.get('current_tags', []):
                        if existing_t and existing_t.lower() not in seen_lower:
                            new_tags.append(existing_t)
                            seen_lower.add(existing_t.lower())

                for t in parsed_tags:
                    if t.lower() not in seen_lower:
                        new_tags.append(t)
                        seen_lower.add(t.lower())
                        all_distinct_tags.add(t)

                updates_to_perform.append((new_tags, matched_prop['id']))

            if updates_to_perform:
                psycopg2.extras.execute_batch(
                    cursor,
                    "UPDATE properties SET tags = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    updates_to_perform
                )
                self.connection.commit()
                updated_count = len(updates_to_perform)

            cursor.close()
            self._cache.pop('statistics', None)

            return {
                'success': True,
                'total_rows': len(csv_rows),
                'matched_count': matched_count,
                'updated_count': updated_count,
                'unmatched_rows': unmatched_rows,
                'distinct_tags_count': len(all_distinct_tags)
            }
        except Exception as e:
            if self.connection:
                self.connection.rollback()
            logging.error(f"Error in bulk_update_tags_from_csv: {e}")
            return {'success': False, 'error': str(e)}
