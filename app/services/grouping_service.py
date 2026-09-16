import hashlib
import logging
import re
import uuid
import datetime
from typing import Dict, List, Optional
import psycopg2.extras

INACTIVE_STATUSES = ('Sold', 'Delisted', 'Withdrawn')


class GroupingEngine:
    """
    Engine to identify and group probable duplicate properties.

    Automatic matches (active listings only):
    - Identical PRICE (property_price)
    - Identical PLOT M2 (land_area)
    - Identical BEDS (bedrooms)
    - DIFFERENT SOURCE (source)

    Manual matches: pairs a user marked in manual_duplicate_links, which catch
    duplicates the agents listed with different beds/plot. These count whatever
    the listing status. Automatic and manual matches that share a property are
    merged into one group.

    Creates logical groupings in property_groups and property_group_members.
    """

    def __init__(self, connection):
        self.conn = connection
        self.logger = logging.getLogger('GroupingEngine')

    def run_grouping(self) -> Dict:
        """
        Executes the grouping algorithm over all listings, rebuilding every group.
        """
        # One transaction for the whole rebuild, so readers never see the tables
        # half-deleted and a failure leaves the previous groups intact.
        previous_autocommit = self.conn.autocommit
        try:
            self.conn.autocommit = False
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # We want to find sets of properties where price, land_area, and bedrooms are identical
            # AND there is more than 1 distinct source in the group.
            cursor.execute("""
                SELECT array_agg(id::text) as property_ids
                FROM properties
                WHERE price IS NOT NULL
                  AND land_area IS NOT NULL
                  AND bedrooms IS NOT NULL
                  -- Only consider active/visible listings (not sold/delisted)
                  AND property_status NOT IN ('Sold', 'Delisted', 'Withdrawn')
                GROUP BY price, land_area, bedrooms
                HAVING COUNT(DISTINCT source) > 1
            """)
            auto_sets = [row['property_ids'] for row in cursor.fetchall()]

            cursor.execute("SELECT property_id_a::text AS a, property_id_b::text AS b FROM manual_duplicate_links")
            manual_pairs = [(row['a'], row['b']) for row in cursor.fetchall()]

            # Union-find over both kinds of match: anything connected is one physical property.
            parent = {}

            def find(x):
                parent.setdefault(x, x)
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a, b):
                parent[find(a)] = find(b)

            auto_ids = set()
            for ids in auto_sets:
                auto_ids.update(ids)
                for other in ids[1:]:
                    union(ids[0], other)

            manual_ids = set()
            for a, b in manual_pairs:
                manual_ids.update((a, b))
                union(a, b)

            components = {}
            for pid in parent:
                components.setdefault(find(pid), []).append(pid)
            groups = [members for members in components.values() if len(members) > 1]

            # Fetch details for every grouped property once, to pick representatives
            all_ids = [pid for members in groups for pid in members]
            props = {}
            if all_ids:
                cursor.execute("""
                    SELECT id::text AS id, property_status, image_filename, image_filename_2, image_filename_3,
                           last_seen_at, updated_at, price, land_area, bedrooms
                    FROM properties
                    WHERE id = ANY(%s::uuid[])
                """, (all_ids,))
                props = {row['id']: row for row in cursor.fetchall()}

            # Determine representative
            # Hierarchy:
            # 1. Live listing over Sold/Delisted, so a manually linked sold listing
            #    never hides the live one from Unique Stock
            # 2. Greatest number of images
            # 3. Most recently updated
            def score_property(p):
                is_live = 0 if p.get('property_status') in INACTIVE_STATUSES else 1

                # Count images
                img_count = sum(1 for k in ('image_filename', 'image_filename_2', 'image_filename_3') if p.get(k))

                # Use last_seen_at or updated_at for recency
                recency = p.get('last_seen_at') or p.get('updated_at')
                recency_ts = recency.timestamp() if isinstance(recency, datetime.datetime) else 0

                return (is_live, img_count, recency_ts)

            # Clear existing groups to do a fresh recalculation
            # Since property_group_members cascades from property_groups,
            # deleting groups deletes the members.
            cursor.execute("DELETE FROM property_group_members")
            cursor.execute("DELETE FROM property_groups")

            total_properties_grouped = 0
            match_type_counts = {'automatic': 0, 'manual': 0, 'mixed': 0}

            # Insert every group in ONE statement, then every member in one more.
            # A round trip per group took over a minute against a remote database,
            # which is longer than the web request is allowed to run.
            # property_groups has extra columns on some deployments (match_key is NOT
            # NULL there). Insert whichever of them this database actually has.
            cursor.execute("""
                SELECT column_name FROM information_schema.columns WHERE table_name = 'property_groups'
            """)
            group_columns = {row['column_name'] for row in cursor.fetchall()}
            optional_columns = [c for c in ('match_key', 'price', 'plot_area', 'bedrooms') if c in group_columns]

            def as_int(value):
                digits = re.sub(r'[^0-9]', '', str(value or ''))
                return int(digits) if digits else None

            group_rows = []
            representatives = []
            for property_ids in groups:
                has_auto = any(pid in auto_ids for pid in property_ids)
                has_manual = any(pid in manual_ids for pid in property_ids)
                match_type = 'mixed' if has_auto and has_manual else ('manual' if has_manual else 'automatic')
                match_type_counts[match_type] += 1

                known = [pid for pid in property_ids if pid in props]
                representative_id = max(known, key=lambda pid: score_property(props[pid])) if known else None
                representatives.append(representative_id)
                rep = props.get(representative_id) or {}

                row = [f"UPG-{uuid.uuid4().hex[:6].upper()}", match_type]
                for column in optional_columns:
                    if column == 'match_key':
                        # Stable and unique per group: a digest of its members.
                        row.append(hashlib.md5('|'.join(sorted(property_ids)).encode()).hexdigest())
                    elif column == 'price':
                        row.append(rep.get('price'))
                    elif column == 'plot_area':
                        row.append(as_int(rep.get('land_area')))
                    elif column == 'bedrooms':
                        row.append(as_int(rep.get('bedrooms')))
                group_rows.append(tuple(row))

            if group_rows:
                column_sql = ', '.join(['group_code', 'match_type'] + optional_columns)
                inserted = psycopg2.extras.execute_values(
                    cursor,
                    f"INSERT INTO property_groups ({column_sql}) VALUES %s RETURNING id",
                    group_rows,
                    fetch=True
                )
                group_ids = [row['id'] for row in inserted]

                member_rows = []
                for group_id, property_ids, representative_id in zip(group_ids, groups, representatives):
                    for pid in property_ids:
                        # is_auto_matched: matched on price/plot/beds, as opposed to
                        # being pulled into the group only by a manual link.
                        member_rows.append((group_id, pid, pid == representative_id, pid in auto_ids))
                total_properties_grouped = len(member_rows)

                cursor.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'property_group_members' AND column_name = 'is_auto_matched'
                """)
                if cursor.fetchone():
                    psycopg2.extras.execute_values(cursor, """
                        INSERT INTO property_group_members (group_id, property_id, is_representative, is_auto_matched)
                        VALUES %s
                        ON CONFLICT (group_id, property_id) DO NOTHING
                    """, member_rows, template="(%s, %s::uuid, %s, %s)", page_size=1000)
                else:
                    psycopg2.extras.execute_values(cursor, """
                        INSERT INTO property_group_members (group_id, property_id, is_representative)
                        VALUES %s
                        ON CONFLICT (group_id, property_id) DO NOTHING
                    """, [r[:3] for r in member_rows], template="(%s, %s::uuid, %s)", page_size=1000)

            self.conn.commit()
            cursor.close()

            return {
                'success': True,
                'groups_created': len(groups),
                'properties_grouped': total_properties_grouped,
                'groups_by_match_type': match_type_counts
            }

        except Exception as e:
            self.logger.error(f"Failed to run grouping engine: {e}")
            try:
                self.conn.rollback()
            except:
                pass
            return {'success': False, 'error': str(e)}
        finally:
            try:
                self.conn.autocommit = previous_autocommit
            except Exception:
                pass

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
            cursor.execute("SELECT group_code, match_type FROM property_groups WHERE id = %s", (group_id,))
            group_row = cursor.fetchone()

            # Get all properties in this group, with who first linked each one manually (if anyone)
            cursor.execute("""
                SELECT p.*, m.is_representative,
                       ml.created_by AS manual_linked_by,
                       ml.created_at AS manual_linked_at
                FROM property_group_members m
                JOIN properties p ON p.id = m.property_id
                LEFT JOIN LATERAL (
                    SELECT l.created_by, l.created_at
                    FROM manual_duplicate_links l
                    WHERE l.property_id_a = p.id OR l.property_id_b = p.id
                    ORDER BY l.created_at ASC
                    LIMIT 1
                ) ml ON TRUE
                WHERE m.group_id = %s
                ORDER BY m.is_representative DESC, p.price ASC
            """, (group_id,))

            members = [dict(r) for r in cursor.fetchall()]
            for member in members:
                member['is_manual'] = member['manual_linked_at'] is not None
            cursor.close()

            return {
                'has_group': True,
                'group_code': group_row['group_code'],
                'match_type': group_row['match_type'],
                'total_agency_listings': len(members),
                'listings': members
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching group info for {property_id}: {e}")
            return {'has_group': False, 'error': str(e)}
