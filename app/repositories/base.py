"""Connection handling, the query cache, and the shared property filter builder.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras

import logging
import time
from typing import Tuple
from app.config import Config


class BaseRepository:
    """Connection handling, the query cache, and the shared property filter builder."""

    def __init__(self):
        self.config = Config()
        self.connection = None
        self._cache = {}
        self._cache_ttl = 300 # 5 minutes
        self.connect()
        # NOTE: schema bootstrap (ensure_login_activity_table / ensure_security_columns /
        # ensure_user_sessions_table) deliberately does NOT run here. Issuing DDL on every
        # app start takes an ACCESS EXCLUSIVE lock on `users`; if any connection is sitting
        # idle-in-transaction, the ALTER blocks forever and every later `users` query queues
        # behind it, which hangs login. Run migrations/005_ensure_auth_schema.py instead.

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
                password=self.config.DB_PASSWORD,
                # Detect connections dropped by RDS/network instead of letting them
                # linger as half-open sockets that only fail on the next query.
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
            # This manager holds one long-lived connection and is overwhelmingly
            # read-only. Without autocommit, psycopg2 opens a transaction on the
            # first SELECT and never closes it, so the connection sits
            # "idle in transaction" holding locks indefinitely �€� which blocks any
            # later ALTER TABLE (and therefore login). Explicit commit()/rollback()
            # calls elsewhere in this class become harmless no-ops.
            self.connection.autocommit = True
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

    def _build_filter_query(self, filters: Dict) -> Tuple[str, List]:
        """
        Build the base WHERE clause and parameters from a filters dictionary.
        Returns (base_query, params).
        """
        base_query = """
                FROM (
                    SELECT p_inner.*,
                           'SARDO' || (1099 + ROW_NUMBER() OVER(ORDER BY COALESCE(p_inner.source, ''), COALESCE(p_inner.image_filename, ''))) as sardo_reference,
                           pgm.id as member_id,
                           pgm.group_id,
                           pgm.is_representative,
                           pg.group_code,
                           (SELECT COUNT(*) FROM property_group_members WHERE group_id = pgm.group_id) as duplicate_count
                    FROM properties p_inner
                    LEFT JOIN property_group_members pgm ON pgm.property_id = p_inner.id
                    LEFT JOIN property_groups pg ON pg.id = pgm.group_id
                ) as p
                WHERE 1=1
            """
        params = []

        if filters.get('min_price') is not None:
            base_query += " AND price >= %s AND price IS NOT NULL"
            params.append(filters['min_price'])
        
        if filters.get('max_price') is not None:
            base_query += " AND price <= %s AND price IS NOT NULL"
            params.append(filters['max_price'])

        if filters.get('reference'):
            ref_query = f"%{filters['reference'].strip()}%"
            base_query += " AND (reference ILIKE %s OR sardo_reference ILIKE %s OR title ILIKE %s)"
            params.extend([ref_query, ref_query, ref_query])
        
        if filters.get('location'):
            location = filters['location'].strip()
            base_query += " AND (LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))"
            params.append(f"%{location}%")
            params.append(f"{location}%")
        elif filters.get('locations'):
            locations = filters['locations']
            if locations:
                location_conditions = []
                for location in locations:
                    location_conditions.append("(LOWER(location) LIKE LOWER(%s) OR LOWER(location) LIKE LOWER(%s))")
                    params.append(f"%{location.strip()}%")
                    params.append(f"{location.strip()}%")
                base_query += f" AND ({' OR '.join(location_conditions)})"
        
        if filters.get('property_type'):
            base_query += " AND property_type = %s"
            params.append(filters['property_type'])
        
        if filters.get('na_beds'):
            base_query += " AND (bedrooms IS NULL OR TRIM(bedrooms) IN ('', 'N/A', 'None'))"
        else:
            if filters.get('min_beds') is not None:
                base_query += " AND CAST(NULLIF(regexp_replace(bedrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) >= %s AND bedrooms IS NOT NULL"
                params.append(filters['min_beds'])
            if filters.get('max_beds') is not None:
                base_query += " AND CAST(NULLIF(regexp_replace(bedrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) <= %s AND bedrooms IS NOT NULL"
                params.append(filters['max_beds'])
        
        if filters.get('na_baths'):
            base_query += " AND (bathrooms IS NULL OR TRIM(bathrooms) IN ('', 'N/A', 'None'))"
        else:
            if filters.get('min_baths') is not None:
                base_query += " AND CAST(NULLIF(regexp_replace(bathrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) >= %s AND bathrooms IS NOT NULL"
                params.append(filters['min_baths'])
            if filters.get('max_baths') is not None:
                base_query += " AND CAST(NULLIF(regexp_replace(bathrooms::text, '[^0-9.]', '', 'g'), '') AS numeric) <= %s AND bathrooms IS NOT NULL"
                params.append(filters['max_baths'])

        statuses = filters.get('statuses') or filters.get('property_status')
        if statuses:
            if isinstance(statuses, str):
                statuses = [statuses]
            statuses = [s for s in statuses if s in Config.PROPERTY_STATUSES]
            if statuses:
                query_statuses = list(statuses)
                if 'For Sale' in query_statuses and 'Unknown' not in query_statuses:
                    query_statuses.append('Unknown')
                placeholders = ', '.join(['%s'] * len(query_statuses))
                base_query += f" AND (property_status IN ({placeholders})"
                if 'For Sale' in query_statuses:
                    base_query += " OR property_status IS NULL)"
                else:
                    base_query += ")"
                params.extend(query_statuses)

        if filters.get('exclude_delisted'):
            base_query += " AND (property_status IS NULL OR property_status <> 'Delisted')"

        if filters.get('exclude_sold'):
            base_query += " AND (property_status IS NULL OR property_status <> 'Sold')"

        vis = filters.get('market_visibility')
        if vis and str(vis).strip().lower() in ('public', 'off_market'):
            base_query += " AND market_visibility = %s"
            params.append(str(vis).strip().lower())

        stype = filters.get('source_type')
        if stype and str(stype).strip().lower() in ('scraped', 'manual'):
            base_query += " AND source_type = %s"
            params.append(str(stype).strip().lower())

        sources = filters.get('sources') or filters.get('source')
        if sources:
            if isinstance(sources, str):
                sources = [sources]
            sources = [s.strip() for s in sources if s and s.strip()]
            if sources:
                expanded_sources = []
                for s in sources:
                    expanded_sources.append(s)
                    for raw_key, friendly_name in Config.SOURCE_NAME_MAPPING.items():
                        if friendly_name == s:
                            expanded_sources.append(raw_key)
                    if not s.endswith("Scraper"):
                        expanded_sources.append(s + "Scraper")
                expanded_sources = list(set(expanded_sources))
                placeholders = ', '.join(['%s'] * len(expanded_sources))
                base_query += f" AND source IN ({placeholders})"
                params.extend(expanded_sources)

        tags = filters.get('tags')
        if tags:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',') if t.strip()]
            tags = [t.strip() for t in tags if t and t.strip()]
            if tags:
                base_query += " AND tags && %s::text[]"
                params.append(tags)

        if filters.get('first_seen_from'):
            base_query += " AND first_seen_at >= %s::timestamp"
            params.append(filters['first_seen_from'])
        if filters.get('first_seen_to'):
            base_query += " AND first_seen_at < (%s::date + INTERVAL '1 day')"
            params.append(filters['first_seen_to'])

        if filters.get('status_changed_from'):
            base_query += " AND status_last_changed_at >= %s::timestamp"
            params.append(filters['status_changed_from'])
        if filters.get('status_changed_to'):
            base_query += " AND status_last_changed_at < (%s::date + INTERVAL '1 day')"
            params.append(filters['status_changed_to'])

        return base_query, params
