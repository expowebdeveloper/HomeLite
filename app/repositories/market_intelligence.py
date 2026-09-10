"""Aggregates powering the Market Intelligence dashboard.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

from typing import Dict

import psycopg2
import psycopg2.extras
import logging
import re
import decimal


class MarketIntelligenceMixin:
    """Aggregates powering the Market Intelligence dashboard."""


    # ==================================================================
    # Market Intelligence Dashboard
    # ==================================================================
    #
    # Shared SQL fragments. `_build_filter_query` wraps `properties` in a
    # sub-select aliased `p` that carries the duplicate-grouping columns
    # (member_id / group_id / is_representative), so every aggregate below can
    # switch between "active listings" (every agency row) and "unique
    # properties" (one row per duplicate group) with the same WHERE clause.

    # One row per real-world property: ungrouped listings, plus the
    # representative of each duplicate group.
    MI_UNIQUE = "(p.member_id IS NULL OR p.is_representative = TRUE)"

    # Scraped stock carries occasional junk: asking prices of a few euro and
    # build areas of 2 m² where the source published a typo. Those rows are
    # harmless in a count but wreck any average, so derived pricing metrics
    # (€/m², outliers, price range) only look at values in a plausible range.
    MI_SANE_PRICE_MIN = 10000
    MI_SANE_BUILD_MIN = 20
    MI_SANE_BUILD_MAX = 20000

    # Areas are stored as free text ('1,782 m²', '450', 'N/A'). Strip thousand
    # separators first, then anything that is not a digit or decimal point, and
    # only cast when what is left is actually a number.
    @staticmethod
    def _mi_numeric(column: str) -> str:
        cleaned = f"regexp_replace(replace(COALESCE({column}::text, ''), ',', ''), '[^0-9.]', '', 'g')"
        return f"(CASE WHEN {cleaned} ~ '^[0-9]+(\\.[0-9]+)?$' THEN CAST({cleaned} AS numeric) ELSE NULL END)"

    @staticmethod
    def _mi_bedroom_bucket(column: str = 'bedrooms') -> str:
        digits = f"regexp_replace(COALESCE({column}::text, ''), '[^0-9]', '', 'g')"
        return f"""
                        CASE
                            WHEN {digits} = '' THEN 'Unknown'
                            WHEN CAST({digits} AS integer) >= 9 THEN '9+'
                            WHEN CAST({digits} AS integer) <= 2 THEN '<=2'
                            ELSE CAST({digits} AS integer)::text
                        END"""

    @staticmethod
    def _mi_price_bucket(column: str = 'price') -> str:
        """ASCII bucket keys; the dashboard renders the '€2M - €5M' labels."""
        return f"""
                        CASE
                            WHEN {column} IS NULL OR {column} <= 0 THEN 'poa'
                            WHEN {column} < 2000000 THEN 'lt2m'
                            WHEN {column} < 5000000 THEN '2m-5m'
                            WHEN {column} < 10000000 THEN '5m-10m'
                            WHEN {column} < 15000000 THEN '10m-15m'
                            ELSE '15m+'
                        END"""

    @staticmethod
    def _mi_floats(row) -> Dict:
        """Cast Decimal/float aggregate results to plain floats for JSON."""
        out = {}
        for k, v in dict(row).items():
            if isinstance(v, decimal.Decimal):
                out[k] = float(v)
            elif isinstance(v, float):
                out[k] = float(v)
            else:
                out[k] = v
        return out

    def _mi_query(self, sql: str, params, many: bool = True):
        """Run one Market Intelligence aggregate, rolling back on failure."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return [] if many else {}
        cursor = None
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(sql, params)
            if many:
                rows = [self._mi_floats(r) for r in cursor.fetchall()]
            else:
                row = cursor.fetchone()
                rows = self._mi_floats(row) if row else {}
            cursor.close()
            return rows
        except Exception as e:
            logging.error(f"[MI] Query failed: {e}")
            try:
                if cursor:
                    cursor.close()
            except Exception:
                pass
            try:
                self.connection.rollback()
            except Exception:
                pass
            return [] if many else {}

    def get_market_intelligence_kpis(self, filters):
        """Headline KPI tiles: counts, pricing, €/m² and build-area totals.

        Money and €/m² figures deliberately ignore POA (price NULL or 0) rows so
        a listing without a published price cannot drag the averages down.
        """
        base_query, params = self._build_filter_query(filters)
        uniq = self.MI_UNIQUE
        build = self._mi_numeric('living_area')
        plot = self._mi_numeric('land_area')
        priced = f"{uniq} AND price > 0"
        # Rows a €/m² figure can legitimately be derived from.
        sane = (f"{uniq} AND price >= {self.MI_SANE_PRICE_MIN} "
                f"AND {build} BETWEEN {self.MI_SANE_BUILD_MIN} AND {self.MI_SANE_BUILD_MAX}")

        query = f"""
            SELECT
                COUNT(*) AS active_properties,
                COUNT(*) FILTER (WHERE {uniq}) AS unique_properties,
                COUNT(*) - COUNT(*) FILTER (WHERE {uniq}) AS duplicate_listings,
                COUNT(DISTINCT p.group_id) AS duplicate_groups,
                COUNT(DISTINCT p.source) AS source_count,
                COUNT(*) FILTER (WHERE {uniq} AND (price IS NULL OR price <= 0)) AS poa_count,

                SUM(price) FILTER (WHERE {priced}) AS total_stock_value,
                AVG(price) FILTER (WHERE {priced}) AS avg_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price)
                    FILTER (WHERE {priced}) AS median_price,
                MAX(price) FILTER (WHERE {priced}) AS max_price,
                MIN(price) FILTER (WHERE {priced} AND price >= {self.MI_SANE_PRICE_MIN}) AS min_price,

                AVG(price / {build}) FILTER (WHERE {sane}) AS avg_price_per_sqm,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price / NULLIF({build}, 0))
                    FILTER (WHERE {sane}) AS median_price_per_sqm,

                SUM({build}) FILTER (WHERE {uniq}) AS total_build_area,
                AVG({build}) FILTER (WHERE {uniq} AND {build} > 0) AS avg_build_area,
                AVG({plot}) FILTER (WHERE {uniq} AND {plot} > 0) AS avg_plot_area
            {base_query}
        """
        kpis = self._mi_query(query, params, many=False)
        if not kpis:
            return {}

        # The "Highest Asking Price" tile also shows that property's bedrooms
        # and plot size, so fetch the top-priced row itself.
        top_query = f"""
            SELECT bedrooms, {plot} AS plot_area, {build} AS build_area, source, title, location
            {base_query} AND {uniq} AND price > 0
            ORDER BY price DESC
            LIMIT 1
        """
        top = self._mi_query(top_query, params, many=False)
        kpis['highest_priced_property'] = top or {}
        return kpis

    def get_stock_by_bedroom_count(self, filters):
        """Bedroom histogram: '<=2', '3'…'8', '9+', 'Unknown'."""
        base_query, params = self._build_filter_query(filters)
        bucket = self._mi_bedroom_bucket()
        query = f"""
            SELECT * FROM (
                SELECT
                    {bucket} AS bedroom_bucket,
                    COUNT(*) AS active_count,
                    COUNT(*) FILTER (WHERE {self.MI_UNIQUE}) AS unique_count
                {base_query}
                GROUP BY {bucket}
            ) AS sub
            ORDER BY
                CASE bedroom_bucket
                    WHEN '<=2' THEN 1 WHEN '3' THEN 2 WHEN '4' THEN 3 WHEN '5' THEN 4
                    WHEN '6' THEN 5 WHEN '7' THEN 6 WHEN '8' THEN 7 WHEN '9+' THEN 8
                    ELSE 9 END
        """
        return self._mi_query(query, params)

    def get_listings_by_source(self, filters):
        """Per-agency stock counts plus their average asking price and €/m²."""
        base_query, params = self._build_filter_query(filters)
        build = self._mi_numeric('living_area')
        query = f"""
            SELECT
                source,
                COUNT(*) AS active_count,
                COUNT(*) FILTER (WHERE {self.MI_UNIQUE}) AS unique_count,
                SUM(price) FILTER (WHERE price > 0) AS total_value,
                AVG(price) FILTER (WHERE price > 0) AS avg_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price)
                    FILTER (WHERE price > 0) AS median_price,
                AVG(price / {build}) FILTER (
                    WHERE price >= {self.MI_SANE_PRICE_MIN}
                      AND {build} BETWEEN {self.MI_SANE_BUILD_MIN} AND {self.MI_SANE_BUILD_MAX}
                ) AS avg_price_per_sqm
            {base_query}
            GROUP BY source
            ORDER BY active_count DESC
        """
        return self._mi_query(query, params)

    def get_price_distribution(self, filters):
        """Asking-price bands for the donut chart."""
        base_query, params = self._build_filter_query(filters)
        bucket = self._mi_price_bucket()
        query = f"""
            SELECT * FROM (
                SELECT
                    {bucket} AS price_bucket,
                    COUNT(*) AS active_count,
                    COUNT(*) FILTER (WHERE {self.MI_UNIQUE}) AS unique_count
                {base_query}
                GROUP BY {bucket}
            ) AS sub
            ORDER BY
                CASE price_bucket
                    WHEN 'lt2m' THEN 1 WHEN '2m-5m' THEN 2 WHEN '5m-10m' THEN 3
                    WHEN '10m-15m' THEN 4 WHEN '15m+' THEN 5 ELSE 6 END
        """
        return self._mi_query(query, params)

    def get_bedroom_stock_by_source(self, filters):
        """Per-source, per-bedroom-bucket counts driving the heatmap matrix."""
        base_query, params = self._build_filter_query(filters)
        bucket = self._mi_bedroom_bucket()
        query = f"""
            SELECT source, {bucket} AS bedroom_bucket, COUNT(*) AS count
            {base_query}
            GROUP BY source, {bucket}
            ORDER BY source
        """
        return self._mi_query(query, params)

    def get_duplicate_intelligence(self, filters):
        """Duplicate groups, single-source share, and the most re-listed stock.

        'Single source' counts real-world properties advertised by exactly one
        agency — a duplicate group whose members all come from the same source
        still counts as single-source.
        """
        base_query, params = self._build_filter_query(filters)
        build = self._mi_numeric('living_area')
        plot = self._mi_numeric('land_area')

        counts_query = f"""
            SELECT
                COUNT(*) AS estimated_unique,
                COUNT(*) FILTER (WHERE source_count = 1) AS single_source_count,
                COUNT(*) FILTER (WHERE source_count > 1) AS multi_source_count
            FROM (
                SELECT
                    COALESCE(p.group_id::text, 'solo-' || p.id::text) AS grp,
                    COUNT(DISTINCT p.source) AS source_count
                {base_query}
                GROUP BY COALESCE(p.group_id::text, 'solo-' || p.id::text)
            ) AS grouped
        """
        counts = self._mi_query(counts_query, params, many=False) or {}

        totals_query = f"""
            SELECT
                COUNT(*) AS active_listings,
                COUNT(*) FILTER (WHERE {self.MI_UNIQUE}) AS unique_properties,
                COUNT(*) - COUNT(*) FILTER (WHERE {self.MI_UNIQUE}) AS duplicate_listings,
                COUNT(DISTINCT p.group_id) AS duplicate_groups
            {base_query}
        """
        totals = self._mi_query(totals_query, params, many=False) or {}

        top_query = f"""
            SELECT
                p.group_id,
                MAX(p.group_code) AS group_code,
                MAX(p.title) AS title,
                MAX(p.location) AS location,
                MAX(p.bedrooms) AS bedrooms,
                MAX(price) FILTER (WHERE price > 0) AS price,
                MAX({plot}) AS plot_area,
                MAX({build}) AS build_area,
                COUNT(DISTINCT p.source) AS agency_count,
                ARRAY_AGG(DISTINCT p.source) AS agencies
            {base_query} AND p.group_id IS NOT NULL
            GROUP BY p.group_id
            HAVING COUNT(DISTINCT p.source) > 1
            ORDER BY agency_count DESC, MAX(price) DESC NULLS LAST
            LIMIT 5
        """
        top_listed = self._mi_query(top_query, params)

        estimated_unique = counts.get('estimated_unique') or 0
        single_source = counts.get('single_source_count') or 0
        return {
            'active_listings': totals.get('active_listings') or 0,
            'unique_properties': totals.get('unique_properties') or 0,
            'duplicate_listings': totals.get('duplicate_listings') or 0,
            'total_duplicate_groups': totals.get('duplicate_groups') or 0,
            'estimated_unique': estimated_unique,
            'single_source_count': single_source,
            'multi_source_count': counts.get('multi_source_count') or 0,
            'single_source_pct': round(single_source * 100.0 / estimated_unique, 1) if estimated_unique else 0,
            'top_widely_listed': top_listed,
        }

    def get_market_outliers(self, filters):
        """Extremes of the filtered set: €/m² range, largest plot and build."""
        base_query, params = self._build_filter_query(filters)
        build = self._mi_numeric('living_area')
        plot = self._mi_numeric('land_area')
        uniq = self.MI_UNIQUE

        sane = (f"{uniq} AND price >= {self.MI_SANE_PRICE_MIN} "
                f"AND {build} BETWEEN {self.MI_SANE_BUILD_MIN} AND {self.MI_SANE_BUILD_MAX}")

        query = f"""
            SELECT
                MAX(price / {build}) FILTER (WHERE {sane}) AS highest_price_per_sqm,
                MIN(price / {build}) FILTER (WHERE {sane}) AS lowest_price_per_sqm,
                MAX({plot}) FILTER (WHERE {uniq}) AS largest_plot,
                MAX({build}) FILTER (WHERE {uniq} AND {build} <= {self.MI_SANE_BUILD_MAX})
                    AS largest_build,
                MIN({build}) FILTER (WHERE {uniq} AND {build} >= {self.MI_SANE_BUILD_MIN})
                    AS smallest_build
            {base_query}
        """
        return self._mi_query(query, params, many=False)
