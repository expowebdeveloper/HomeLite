"""Scraper run history, live activity and log streaming.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras
import logging
import datetime
from typing import List
from app.config import Config


class ScrapersMixin:
    """Scraper run history, live activity and log streaming."""


    def get_status_report(self, date_from: str = None, date_to: str = None) -> Dict:
        """Build the property status report (spec section 6).

        Current-state figures (active stock, status breakdown) always reflect
        "right now". Movement figures (new listings, sold, delisted) are scoped
        to the supplied date range when one is given.

        `property_status_history` is written by the scraper; until it runs, the
        movement figures are legitimately zero.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {}

        # Build a reusable date-range predicate for the history table
        history_clause = ""
        history_params = []
        if date_from:
            history_clause += " AND h.changed_at >= %s::timestamp"
            history_params.append(date_from)
        if date_to:
            history_clause += " AND h.changed_at < (%s::date + INTERVAL '1 day')"
            history_params.append(date_to)

        seen_clause = ""
        seen_params = []
        if date_from:
            seen_clause += " AND first_seen_at >= %s::timestamp"
            seen_params.append(date_from)
        if date_to:
            seen_clause += " AND first_seen_at < (%s::date + INTERVAL '1 day')"
            seen_params.append(date_to)

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            report = {'date_from': date_from, 'date_to': date_to}

            # Current status counts per source
            cursor.execute("""
                SELECT source, property_status, COUNT(*) AS n
                FROM properties GROUP BY source, property_status
            """)
            per_source = {}
            for row in cursor.fetchall():
                src = row['source'] or 'Unknown'
                per_source.setdefault(src, {})[row['property_status']] = row['n']

            # New listings per source (by first_seen_at, within range)
            cursor.execute(f"""
                SELECT source, COUNT(*) AS n FROM properties
                WHERE 1=1 {seen_clause}
                GROUP BY source
            """, seen_params)
            new_by_source = {(r['source'] or 'Unknown'): r['n'] for r in cursor.fetchall()}

            # Status movements per source, from the history table (within range)
            cursor.execute(f"""
                SELECT p.source, h.new_status, COUNT(*) AS n
                FROM property_status_history h
                JOIN properties p ON p.id = h.property_id
                WHERE 1=1 {history_clause}
                GROUP BY p.source, h.new_status
            """, history_params)
            moves = {}
            for row in cursor.fetchall():
                src = row['source'] or 'Unknown'
                moves.setdefault(src, {})[row['new_status']] = row['n']

            # Assemble the per-agent rows
            inactive = set(Config.INACTIVE_STATUSES)
            rows = []
            for src in sorted(set(per_source) | set(new_by_source) | set(moves)):
                statuses = per_source.get(src, {})
                moved = moves.get(src, {})
                rows.append({
                    'source': src,
                    'active_stock': sum(n for s, n in statuses.items() if s not in inactive),
                    'total_stock': sum(statuses.values()),
                    'new_listings': new_by_source.get(src, 0),
                    'reserved': statuses.get('Reserved', 0),
                    'under_offer': statuses.get('Under Offer', 0),
                    'exclusive': statuses.get('Exclusive', 0),
                    'sold': statuses.get('Sold', 0),
                    'delisted': statuses.get('Delisted', 0),
                    'moved_to_sold': moved.get('Sold', 0),
                    'moved_to_delisted': moved.get('Delisted', 0),
                    'moved_to_reserved': moved.get('Reserved', 0),
                    'moved_to_under_offer': moved.get('Under Offer', 0),
                })
            report['by_source'] = rows

            # Overall status breakdown (current)
            cursor.execute("SELECT property_status, COUNT(*) AS n FROM properties GROUP BY property_status")
            report['by_status'] = {r['property_status']: r['n'] for r in cursor.fetchall()}

            # Average days from first_seen_at to Sold / Delisted
            for target, key in (('Sold', 'avg_days_to_sold'), ('Delisted', 'avg_days_to_delisted')):
                cursor.execute(f"""
                    SELECT AVG(EXTRACT(EPOCH FROM (h.changed_at - p.first_seen_at)) / 86400.0) AS days
                    FROM property_status_history h
                    JOIN properties p ON p.id = h.property_id
                    WHERE h.new_status = %s AND p.first_seen_at IS NOT NULL {history_clause}
                """, [target] + history_params)
                value = cursor.fetchone()['days']
                report[key] = round(float(value), 1) if value is not None else None

            # Recent status changes (most recent first)
            cursor.execute(f"""
                SELECT h.changed_at, h.previous_status, h.new_status,
                       p.source, p.location, p.reference, p.property_url
                FROM property_status_history h
                JOIN properties p ON p.id = h.property_id
                WHERE 1=1 {history_clause}
                ORDER BY h.changed_at DESC
                LIMIT 100
            """, history_params)
            report['recent_changes'] = [dict(r) for r in cursor.fetchall()]

            # Properties sold within date range (client reporting requirement)
            sold_clause = ""
            sold_params = []
            if date_from:
                sold_clause += " AND sold_at >= %s::timestamp"
                sold_params.append(date_from)
            if date_to:
                sold_clause += " AND sold_at < (%s::date + INTERVAL '1 day')"
                sold_params.append(date_to)

            try:
                cursor.execute(f"""
                    SELECT reference, title, price, location, source, sold_at, property_url
                    FROM properties
                    WHERE property_status = 'Sold' AND sold_at IS NOT NULL {sold_clause}
                    ORDER BY sold_at DESC
                    LIMIT 500
                """, sold_params)
                report['sold_properties'] = [dict(r) for r in cursor.fetchall()]
            except Exception as ex:
                logging.warning(f"Could not query sold_properties: {ex}")
                report['sold_properties'] = []

            cursor.close()
            return report

        except Exception as e:
            logging.error(f"Error building status report: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {}

    def get_scrape_runs(self, limit: int = 20) -> List[Dict]:
        """Recent scrape runs, for the audit view."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, source_name, started_at, completed_at, run_status,
                       properties_found, new_properties, updated_properties,
                       status_changes, delisted_properties, errors_count, notes
                FROM scrape_runs
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cursor.fetchall()]
            cursor.close()
            return rows
        except Exception as e:
            logging.error(f"Error fetching scrape runs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return []

    # ------------------------------------------------------------------
    # Live scraper activity (Scraper Logs page)
    # ------------------------------------------------------------------

    # A run flagged 'running' whose heartbeat has gone quiet for longer than this
    # is treated as dead, not live. Without this a crashed scraper would show as
    # "running" forever �€� which is exactly what happened to runs #1 and #2.
    STALE_HEARTBEAT_SECONDS = 180

    def get_scraper_activity(self, limit: int = 25) -> Dict:
        """Current state of every scraper, plus the most recent runs.

        Returns {'runs': [...], 'active_count': int, 'server_time': datetime}.

        Each run carries a derived `live_status`:
            running   - flagged running and heart still beating
            stalled   - flagged running but the heartbeat went quiet (crashed)
            completed / failed / suspect - terminal states as recorded
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'runs': [], 'active_count': 0, 'server_time': None}

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT
                    r.id, r.source_name, r.run_status, r.started_at, r.completed_at,
                    r.last_heartbeat_at, r.progress_current, r.progress_total,
                    r.triggered_by, r.properties_found, r.new_properties,
                    r.updated_properties, r.status_changes, r.delisted_properties,
                    r.errors_count, r.notes,
                    EXTRACT(EPOCH FROM (
                        now() - COALESCE(r.last_heartbeat_at, r.started_at)
                    )) AS seconds_since_heartbeat,
                    EXTRACT(EPOCH FROM (
                        COALESCE(r.completed_at, now()) - r.started_at
                    )) AS duration_seconds,
                    (SELECT COUNT(*) FROM scrape_logs l WHERE l.scrape_run_id = r.id) AS log_count,
                    (SELECT COUNT(*) FROM scrape_logs l
                      WHERE l.scrape_run_id = r.id AND l.level = 'ERROR') AS error_log_count
                FROM scrape_runs r
                ORDER BY r.started_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT now() AS now;")
            server_time = cursor.fetchone()['now']
            cursor.close()

            active = 0
            for r in rows:
                quiet = r.get('seconds_since_heartbeat') or 0
                if r['run_status'] == 'running':
                    if quiet > self.STALE_HEARTBEAT_SECONDS:
                        r['live_status'] = 'stalled'
                        r['stale_reason'] = (
                            f"No heartbeat for {int(quiet)}s �€� the scraper most likely "
                            f"crashed or was killed."
                        )
                    else:
                        r['live_status'] = 'running'
                        active += 1
                else:
                    r['live_status'] = r['run_status']

                # Progress bar. Be defensive: NEVER render a half-filled bar for a run
                # that has already finished. Scrapers routinely forget to set
                # progress_current = progress_total on the final update (run #18 finished
                # having only ever written 1/2), and a 50% bar on a completed run reads
                # as "stuck" to the user. The run_status is the source of truth for
                # whether work is still happening; progress_* is only a hint.
                total = r.get('progress_total') or 0
                current = r.get('progress_current') or 0
                raw_pct = round(min(current / total * 100, 100), 1) if total > 0 else None

                if r['live_status'] == 'completed':
                    r['progress_percent'] = 100.0     # finished == 100% by definition
                    r['progress_state'] = 'done'
                elif r['live_status'] == 'running':
                    r['progress_percent'] = raw_pct
                    r['progress_state'] = 'active'
                elif r['live_status'] == 'suspect':
                    # A 'suspect' run did NOT crash. It scraped fine and then deliberately
                    # SKIPPED the delist sweep because the safety guard tripped. Rendering
                    # it like a failure ("Stopped at�€�", red) makes a healthy run look broken.
                    # It's a warning, not an error �€� and `notes` says exactly why.
                    r['progress_percent'] = 100.0 if r['run_status'] == 'suspect' else raw_pct
                    r['progress_state'] = 'warning'
                else:
                    # failed / stalled �€� genuinely died partway.
                    r['progress_percent'] = raw_pct
                    r['progress_state'] = 'stopped'

                # Surface the discrepancy where a run clearly did work (it has progress and
                # log output) but reported zero counters �€� that means the uploader never
                # wrote its totals back, not that the scrape found nothing.
                r['counters_missing'] = bool(
                    (r.get('properties_found') or 0) == 0
                    and ((r.get('progress_current') or 0) > 0 or (r.get('log_count') or 0) > 0)
                    and r['live_status'] in ('completed', 'suspect')
                )

            return {'runs': rows, 'active_count': active, 'server_time': server_time}

        except Exception as e:
            logging.error(f"Error fetching scraper activity: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return {'runs': [], 'active_count': 0, 'server_time': None}

    def get_scrape_logs(self, run_id: int, after_id: int = 0, before_id: int = None,
                        level: str = None, limit: int = 500) -> Dict:
        """Fetch log lines for one run.

        Three modes, mirroring how a real terminal behaves:

        * `after_id > 0`  -> incremental poll: only lines newer than what we already
                             have. Used while a scrape is streaming.
        * `before_id`     -> "load earlier": the chunk immediately preceding a line
                             we already have (scrolling back up).
        * neither         -> **tail**: the MOST RECENT `limit` lines.

        The tail default matters. A run can have thousands of lines (run #26 had
        1,985); loading the *first* 500 would leave the user staring at the start of
        the scrape and never showing the "Scraping completed" line at the end �€� which
        looks like the scrape is stuck partway.
        """
        empty = {'logs': [], 'total': 0, 'first_id': None, 'last_id': after_id, 'has_more_before': False}
        if not self.connection or self.connection.closed:
            if not self.connect():
                return empty
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            level_sql, level_params = "", []
            if level and level.upper() in ('INFO', 'WARNING', 'ERROR', 'DEBUG'):
                level_sql = " AND level = %s"
                level_params = [level.upper()]

            # Total matching lines, so the UI can say "showing last 500 of 1985"
            cursor.execute(
                f"SELECT COUNT(*) AS n FROM scrape_logs WHERE scrape_run_id = %s{level_sql}",
                [run_id] + level_params)
            total = cursor.fetchone()['n']

            if after_id and after_id > 0:
                # Incremental: new lines only, oldest-first.
                cursor.execute(f"""
                    SELECT id, scrape_run_id, source_name, level, message, created_at
                    FROM scrape_logs
                    WHERE scrape_run_id = %s AND id > %s{level_sql}
                    ORDER BY id ASC LIMIT %s
                """, [run_id, after_id] + level_params + [limit])
                rows = [dict(r) for r in cursor.fetchall()]
            else:
                # Tail (or "load earlier" when before_id is given): take the newest
                # `limit` rows with DESC, then flip back to chronological order.
                bound_sql, bound_params = "", []
                if before_id:
                    bound_sql = " AND id < %s"
                    bound_params = [before_id]
                cursor.execute(f"""
                    SELECT id, scrape_run_id, source_name, level, message, created_at
                    FROM scrape_logs
                    WHERE scrape_run_id = %s{bound_sql}{level_sql}
                    ORDER BY id DESC LIMIT %s
                """, [run_id] + bound_params + level_params + [limit])
                rows = [dict(r) for r in cursor.fetchall()][::-1]   # back to ASC

            cursor.close()

            first_id = rows[0]['id'] if rows else None
            last_id = rows[-1]['id'] if rows else after_id
            return {
                'logs': rows,
                'total': total,
                'first_id': first_id,
                'last_id': last_id,
                # Are there older lines above what we just returned?
                'has_more_before': bool(first_id) and len(rows) == limit,
            }
        except Exception as e:
            logging.error(f"Error fetching scrape logs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return empty

    def mark_stalled_runs_failed(self) -> int:
        """Close out runs whose scraper died without finalising them.

        A crashed scraper leaves its row at 'running' forever, which poisons the
        delist guard's "last successful run" baseline. Returns rows updated.
        """
        if not self.connection or self.connection.closed:
            if not self.connect():
                return 0
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE scrape_runs
                   SET run_status = 'failed',
                       completed_at = COALESCE(completed_at, now()),
                       notes = COALESCE(notes, '') ||
                               ' [auto-closed: no heartbeat, scraper presumed dead]'
                 WHERE run_status = 'running'
                   AND now() - COALESCE(last_heartbeat_at, started_at)
                       > (%s * INTERVAL '1 second')
            """, (self.STALE_HEARTBEAT_SECONDS,))
            n = cursor.rowcount
            self.connection.commit()
            cursor.close()
            if n:
                logging.warning(f"Auto-closed {n} stalled scrape run(s) as failed")
            return n
        except Exception as e:
            logging.error(f"Error closing stalled runs: {e}")
            try:
                self.connection.rollback()
            except Exception:
                pass
            return 0
