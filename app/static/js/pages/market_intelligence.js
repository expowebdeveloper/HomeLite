/* ==========================================================================
   SARDO360 — Market Intelligence Dashboard
   --------------------------------------------------------------------------
   Loads after main.js, which owns the filter sidebar and exposes
   window.getFilters(). The dashboard shares that filter state rather than
   keeping its own, so Property Search and Market Intelligence always describe
   the same slice of stock.
   ========================================================================== */

(function () {
    'use strict';

    // ---------------------------------------------------------------- palette
    const C = {
        navy900: '#071A33',
        navy800: '#0B2545',
        navy700: '#163A63',
        blue500: '#4F7196',
        blue300: '#8299B2',
        blue200: '#B7C3D0',
        blue100: '#DDE5EE',
        gold500: '#D3A24A',
        gold200: '#F1E3C4',
        grey600: '#69727D',
        grey400: '#A8AFB5',
        grey200: '#E3E6E8',
        success: '#2E8B67',
        danger: '#B84A4A'
    };

    // Donut slices run dark -> light so the largest band reads first.
    const DONUT_COLORS = [C.navy800, C.blue500, C.gold500, C.gold200, C.blue200, C.blue100];

    const BEDROOM_ORDER = ['<=2', '3', '4', '5', '6', '7', '8', '9+', 'Unknown'];

    // The API returns ASCII bucket keys so the labels never depend on the
    // database connection encoding.
    const PRICE_BAND_LABELS = {
        'lt2m': 'Under €2M',
        '2m-5m': '€2M – €5M',
        '5m-10m': '€5M – €10M',
        '10m-15m': '€10M – €15M',
        '15m+': '€15M+',
        'poa': 'POA'
    };
    const priceBandLabel = (key) => PRICE_BAND_LABELS[key] || key;

    // ------------------------------------------------------------ formatting
    const nf = new Intl.NumberFormat('en-IE');
    const money = new Intl.NumberFormat('en-IE', {
        style: 'currency', currency: 'EUR', maximumFractionDigits: 0
    });

    const num = (v) => (v === null || v === undefined || isNaN(v) ? 0 : Number(v));

    /** €4.45B / €19.95M / €845K / €14,252 — the compact form the KPI tiles use. */
    function fmtMoneyCompact(v) {
        const n = num(v);
        if (!n) return '—';
        // Total stock value runs into the billions, so it needs its own step;
        // without it the tile would read '€4454.31M'.
        // Billions get three decimals: at two, the stock value tile rounds away
        // up to €10M. Trailing zeros are trimmed so €4.000B reads as €4B.
        if (n >= 1e9) return '€' + (n / 1e9).toFixed(3).replace(/\.?0+$/, '') + 'B';
        if (n >= 1e6) return '€' + (n / 1e6).toFixed(2).replace(/\.00$/, '') + 'M';
        if (n >= 1e5) return '€' + Math.round(n / 1e3) + 'K';
        return money.format(Math.round(n));
    }

    function fmtMoneyExact(v) {
        const n = num(v);
        return n ? money.format(Math.round(n)) : '—';
    }

    function fmtArea(v, suffix = ' m²') {
        const n = num(v);
        return n ? nf.format(Math.round(n)) + suffix : '—';
    }

    /** '4' / 'N/A' / '9+ beds' -> '4 Bed', or '' when no count was published. */
    function fmtBedroomCount(raw) {
        const digits = String(raw === null || raw === undefined ? '' : raw).match(/\d+\+?/);
        return digits ? digits[0] + ' Bed' : '';
    }

    function fmtBedroomLabel(bucket) {
        if (bucket === '<=2') return '≤2 Bed';
        if (bucket === 'Unknown') return 'N/A';
        return bucket + ' Bed';
    }

    function escHtml(str) {
        return String(str === null || str === undefined ? '' : str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    // ------------------------------------------------------------ chart setup
    /**
     * Draws the value at the end of every bar, the way the approved design
     * shows them. Chart.js has no built-in data labels and the plugin bundle
     * is not loaded, so this stays local to the dashboard.
     */
    const barValueLabels = {
        id: 'miBarValueLabels',
        afterDatasetsDraw(chart, args, opts) {
            const fmt = (opts && opts.formatter) || ((v) => nf.format(v));
            const ctx = chart.ctx;
            ctx.save();
            ctx.fillStyle = C.grey600;
            ctx.font = '600 11px Outfit, Inter, sans-serif';
            chart.data.datasets.forEach((ds, di) => {
                const meta = chart.getDatasetMeta(di);
                if (meta.hidden) return;
                meta.data.forEach((bar, i) => {
                    const value = ds.data[i];
                    if (value === null || value === undefined || value === 0) return;
                    if (chart.options.indexAxis === 'y') {
                        ctx.textAlign = 'left';
                        ctx.textBaseline = 'middle';
                        ctx.fillText(fmt(value), bar.x + 7, bar.y);
                    } else {
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'bottom';
                        ctx.fillText(fmt(value), bar.x, bar.y - 5);
                    }
                });
            });
            ctx.restore();
        }
    };

    /**
     * Writes the total inside a doughnut's hole.
     *
     * This has to be drawn on the canvas rather than overlaid in HTML: the
     * legend takes up the right-hand side of the chart box, so the doughnut's
     * centre is not the box's centre. Chart.js gives us the arc's real centre
     * and inner radius, so the text lands correctly and shrinks to fit however
     * small the hole gets.
     */
    const donutCenterLabel = {
        id: 'miDonutCenter',
        afterDatasetsDraw(chart, args, opts) {
            if (!opts || !opts.value) return;
            const arc = chart.getDatasetMeta(0).data[0];
            if (!arc) return;

            const inner = arc.innerRadius || 0;
            if (inner < 16) return;                 // hole too small to letter

            const ctx = chart.ctx;
            const maxWidth = inner * 1.6;           // keep clear of the ring
            ctx.save();
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            let size = Math.min(26, Math.floor(inner * 0.62));
            while (size > 9) {
                ctx.font = '700 ' + size + 'px Outfit, Inter, sans-serif';
                if (ctx.measureText(opts.value).width <= maxWidth) break;
                size -= 1;
            }

            const caption = opts.label || '';
            const small = Math.max(9, Math.round(size * 0.44));
            const gap = caption ? size * 0.30 : 0;

            ctx.fillStyle = C.navy900;
            ctx.fillText(opts.value, arc.x, arc.y - gap);

            if (caption) {
                ctx.font = '500 ' + small + 'px Outfit, Inter, sans-serif';
                ctx.fillStyle = C.grey600;
                ctx.fillText(caption, arc.x, arc.y + size * 0.62);
            }
            ctx.restore();
        }
    };

    const gridStyle = { color: 'rgba(227,230,232,0.7)', drawBorder: false };
    const tickStyle = { color: C.grey600, font: { size: 11, family: 'Outfit, Inter, sans-serif' } };

    const tooltipStyle = {
        backgroundColor: C.navy900,
        titleColor: '#fff',
        bodyColor: C.blue200,
        padding: 10,
        cornerRadius: 8,
        displayColors: false
    };

    const charts = {};

    function makeChart(canvasId, config) {
        const el = document.getElementById(canvasId);
        if (!el) {
            console.warn('[MI] canvas #' + canvasId + ' not found');
            return null;
        }
        if (charts[canvasId]) charts[canvasId].destroy();
        charts[canvasId] = new Chart(el, config);
        return charts[canvasId];
    }

    function verticalBar(canvasId, labels, values, color) {
        return makeChart(canvasId, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: color,
                    borderRadius: 3,
                    maxBarThickness: 34
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                layout: { padding: { top: 18 } },
                plugins: { legend: { display: false }, tooltip: tooltipStyle },
                scales: {
                    y: { beginAtZero: true, ticks: tickStyle, grid: gridStyle },
                    x: { ticks: tickStyle, grid: { display: false } }
                }
            },
            plugins: [barValueLabels]
        });
    }

    function horizontalBar(canvasId, labels, values, color, formatter, axisTitle) {
        return makeChart(canvasId, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: color,
                    borderRadius: 3,
                    maxBarThickness: 20
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                layout: { padding: { right: 54 } },
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, tooltipStyle, {
                        callbacks: { label: (ctx) => formatter(ctx.parsed.x) }
                    }),
                    miBarValueLabels: { formatter }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: Object.assign({}, tickStyle, { callback: (v) => formatter(v) }),
                        grid: gridStyle,
                        title: axisTitle
                            ? { display: true, text: axisTitle, color: C.grey600, font: { size: 11 } }
                            : { display: false }
                    },
                    y: { ticks: tickStyle, grid: { display: false } }
                }
            },
            plugins: [barValueLabels]
        });
    }

    // ------------------------------------------------------------ state
    let latest = null;              // last payload from /api/market-intelligence
    let bedroomMode = 'active';     // 'active' | 'unique'
    let heatmapOn = true;
    let isMIActive = false;
    let inFlight = null;

    // =========================================================================
    // Data
    // =========================================================================
    function collectFilters() {
        const filters = (typeof window.getFilters === 'function') ? window.getFilters() : {};
        ['page', 'limit', 'sort_by', 'sort_dir', 'stock_mode'].forEach((k) => delete filters[k]);
        return filters;
    }

    /**
     * Toggle the dashboard's skeleton state.
     *
     * The endpoint runs seven aggregate queries, so a first load takes a
     * noticeable moment. Cards keep their size and shimmer in place, which
     * avoids both an empty-looking dashboard and any reflow when data lands.
     */
    function setLoading(on) {
        const wrapper = document.getElementById('view-mi-container');
        if (wrapper) wrapper.classList.toggle('is-loading', on);

        const stamp = document.getElementById('mi-last-updated');
        if (stamp) {
            if (on) stamp.textContent = 'Loading dashboard…';
            if (stamp.parentElement) stamp.parentElement.classList.toggle('is-loading', on);
        }

        const refreshBtn = document.getElementById('mi-refresh');
        if (refreshBtn) refreshBtn.classList.toggle('spinning', on);
    }

    async function fetchMarketIntelligence() {
        setLoading(true);

        const controller = new AbortController();
        if (inFlight) inFlight.abort();
        inFlight = controller;

        try {
            const response = await fetch('/api/market-intelligence', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(collectFilters()),
                signal: controller.signal
            });

            if (response.status === 401 || response.redirected) {
                window.location.href = '/login';
                return;
            }
            if (!response.ok) throw new Error('HTTP ' + response.status);

            latest = await response.json();
            render(latest);
        } catch (err) {
            if (err.name === 'AbortError') return;
            console.error('[MI] fetch failed:', err);
            // Leave whatever is on screen in place rather than blanking a tile.
            if (typeof showToast === 'function') {
                showToast('Market Intelligence', 'Could not load dashboard data: ' + err.message, 'error');
            }
        } finally {
            // A superseded request must not switch the skeleton off while its
            // replacement is still running.
            if (inFlight === controller) {
                inFlight = null;
                setLoading(false);
            }
        }
    }

    // =========================================================================
    // Rendering
    // =========================================================================
    const RENDERERS = [
        ['KPIs', renderKpis],
        ['bedroom chart', renderBedroomChart],
        ['source chart', renderSourceChart],
        ['bedroom matrix', renderMatrix],
        ['price distribution', renderPriceDistribution],
        ['source pricing', renderSourcePricing],
        ['composition', renderComposition],
        ['duplicates', renderDuplicates],
        ['single source', renderSingleSource],
        ['outliers', renderOutliers],
        ['timestamp', renderTimestamp]
    ];

    /**
     * Each card renders independently: a failure in one (a missing chart
     * library, an unexpected shape in one aggregate) must not leave the rest
     * of the dashboard blank.
     */
    function render(data) {
        if (typeof Chart === 'undefined') showChartError();
        RENDERERS.forEach(([name, fn]) => {
            try {
                fn(data);
            } catch (err) {
                console.error('[MI] failed to render ' + name + ':', err);
            }
        });
    }

    /** Replaces empty canvases with a readable message when Chart.js is absent. */
    function showChartError() {
        document.querySelectorAll('#view-mi-container .mi-chart-box').forEach((box) => {
            if (box.querySelector('.mi-empty')) return;
            const note = document.createElement('div');
            note.className = 'mi-empty';
            note.style.position = 'absolute';
            note.style.inset = '0';
            note.textContent = 'Charts unavailable — chart library failed to load.';
            box.appendChild(note);
        });
    }

    function renderTimestamp(data) {
        const stamp = data.generated_at ? new Date(data.generated_at) : new Date();
        setText('mi-last-updated', 'Last updated: ' + stamp.toLocaleString('en-GB', {
            day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
        }));
    }

    function renderKpis(data) {
        const k = data.kpis || {};
        const sources = (data.listings_by_source || []).length;

        setText('kpi-active-count', nf.format(num(k.active_properties)));
        setText('kpi-active-sub', 'Across ' + sources + (sources === 1 ? ' source' : ' sources'));

        setText('kpi-unique-count', nf.format(num(k.unique_properties)));
        setText('kpi-unique-sub', nf.format(num(k.duplicate_groups)) + ' duplicate groups');

        setText('kpi-avg-price', fmtMoneyCompact(k.avg_price));
        setText('kpi-median-price', 'Median ' + fmtMoneyCompact(k.median_price));

        setText('kpi-avg-sqm', fmtMoneyExact(k.avg_price_per_sqm));
        setText('kpi-median-sqm', 'Median ' + fmtMoneyExact(k.median_price_per_sqm));

        setText('kpi-max-price', fmtMoneyCompact(k.max_price));
        const top = k.highest_priced_property || {};
        const bits = [];
        const topBeds = fmtBedroomCount(top.bedrooms);
        if (topBeds) bits.push(topBeds);
        if (num(top.plot_area)) bits.push(fmtArea(top.plot_area) + ' Plot');
        else if (num(top.build_area)) bits.push(fmtArea(top.build_area) + ' Build');
        setText('kpi-max-price-sub', bits.length ? bits.join(' • ') : '—');

        // Total Property Stock Value: the sum of every unique property's asking
        // price. POA listings carry no price, so they are excluded from the sum
        // and called out underneath rather than silently dropped.
        setText('kpi-stock-value', fmtMoneyCompact(k.total_stock_value));
        const valueEl = document.getElementById('kpi-stock-value');
        if (valueEl) valueEl.title = fmtMoneyExact(k.total_stock_value);
        const priced = Math.max(0, num(k.unique_properties) - num(k.poa_count));
        const poa = num(k.poa_count);
        // .kpi-sub is a single ellipsised line, so keep the visible text short
        // and put the full wording in the tooltip.
        setText('kpi-stock-value-sub',
            nf.format(priced) + ' priced' + (poa ? ' • ' + nf.format(poa) + ' POA' : ''));
        const sub = document.getElementById('kpi-stock-value-sub');
        if (sub) {
            sub.title = 'Sum of ' + nf.format(priced) + ' unique property asking prices'
                + (poa ? '. ' + nf.format(poa) + ' POA listings excluded.' : '.');
        }
    }

    function sortedBedrooms(data) {
        return (data.stock_by_bedroom || [])
            .slice()
            .sort((a, b) => BEDROOM_ORDER.indexOf(a.bedroom_bucket) - BEDROOM_ORDER.indexOf(b.bedroom_bucket));
    }

    function renderBedroomChart(data) {
        const rows = sortedBedrooms(data);
        const key = bedroomMode === 'unique' ? 'unique_count' : 'active_count';
        const total = rows.reduce((sum, r) => sum + num(r[key]), 0);

        verticalBar(
            'chart-bedrooms',
            rows.map((r) => fmtBedroomLabel(r.bedroom_bucket)),
            rows.map((r) => num(r[key])),
            C.navy900
        );

        setText('mi-bedroom-note', 'Total ' + nf.format(total) + ' ' +
            (bedroomMode === 'unique' ? 'unique properties' : 'listings'));

        const btn = document.getElementById('mi-bedroom-mode');
        if (btn) btn.textContent = bedroomMode === 'unique' ? 'Showing: Unique' : 'Showing: Active';
    }

    function sourceLabel(row) {
        return row.display_source || row.source || 'Unknown';
    }

    function renderSourceChart(data) {
        const rows = (data.listings_by_source || []).slice(0, 10);
        horizontalBar(
            'chart-sources',
            rows.map(sourceLabel),
            rows.map((r) => num(r.active_count)),
            C.gold500,
            (v) => nf.format(Math.round(v)),
            'Listings'
        );

        fillDetails('details-sources', ['Source', 'Listings', 'Unique'], rows.map((r) => [
            sourceLabel(r), nf.format(num(r.active_count)), nf.format(num(r.unique_count))
        ]));
    }

    function renderMatrix(data) {
        const header = document.getElementById('matrix-header');
        const body = document.getElementById('matrix-body');
        const footer = document.getElementById('matrix-footer');
        if (!header || !body || !footer) return;

        const buckets = sortedBedrooms(data).map((r) => r.bedroom_bucket);
        const sources = (data.listings_by_source || []).slice(0, 8);

        if (!buckets.length || !sources.length) {
            header.innerHTML = '';
            body.innerHTML = '<tr><td class="mi-empty">No stock matches the current filters.</td></tr>';
            footer.innerHTML = '';
            return;
        }

        // { "Source|bucket": count }
        const cells = {};
        (data.bedroom_by_source || []).forEach((row) => {
            const key = (row.display_source || row.source) + '|' + row.bedroom_bucket;
            cells[key] = (cells[key] || 0) + num(row.count);
        });
        const peak = Math.max(1, ...Object.values(cells));

        header.innerHTML = '<th>Source</th>' +
            buckets.map((b) => '<th>' + escHtml(fmtBedroomLabel(b)) + '</th>').join('') +
            '<th>Total</th>';

        body.innerHTML = sources.map((src) => {
            const label = sourceLabel(src);
            const tds = buckets.map((bucket) => {
                const value = cells[label + '|' + bucket] || 0;
                if (!value) return '<td class="heat-0">0</td>';
                // Floor the tint so a count of 1 is still visible against white.
                const alpha = heatmapOn ? (0.12 + 0.62 * (value / peak)) : 0;
                const style = heatmapOn
                    ? ' style="background: rgba(79,113,150,' + alpha.toFixed(2) + ');' +
                      (alpha > 0.45 ? ' color:#fff; font-weight:600;' : '') + '"'
                    : '';
                return '<td' + style + '>' + nf.format(value) + '</td>';
            }).join('');
            return '<tr><td>' + escHtml(label) + '</td>' + tds +
                '<td style="font-weight:700;">' + nf.format(num(src.active_count)) + '</td></tr>';
        }).join('');

        const columnTotals = buckets.map((bucket) =>
            sources.reduce((sum, src) => sum + (cells[sourceLabel(src) + '|' + bucket] || 0), 0));
        const grandTotal = sources.reduce((sum, src) => sum + num(src.active_count), 0);
        footer.innerHTML = '<td>Total</td>' +
            columnTotals.map((t) => '<td>' + nf.format(t) + '</td>').join('') +
            '<td>' + nf.format(grandTotal) + '</td>';
    }

    function renderPriceDistribution(data) {
        // POA rows carry no price, so they cannot sit on a price axis.
        const rows = (data.price_distribution || []).filter((r) => r.price_bucket !== 'poa');
        const values = rows.map((r) => num(r.active_count));
        const total = values.reduce((a, b) => a + b, 0);

        makeChart('chart-price-dist', {
            type: 'doughnut',
            data: {
                labels: rows.map((r) => priceBandLabel(r.price_bucket)),
                datasets: [{
                    data: values,
                    backgroundColor: DONUT_COLORS.slice(0, rows.length),
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '68%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: C.grey600,
                            boxWidth: 10,
                            boxHeight: 10,
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 12,
                            font: { size: 11, family: 'Outfit, Inter, sans-serif' },
                            generateLabels(chart) {
                                const ds = chart.data.datasets[0];
                                return chart.data.labels.map((label, i) => {
                                    const value = ds.data[i];
                                    const pct = total ? Math.round((value / total) * 100) : 0;
                                    return {
                                        text: label + '  ' + value + ' (' + pct + '%)',
                                        fillStyle: ds.backgroundColor[i],
                                        strokeStyle: ds.backgroundColor[i],
                                        index: i
                                    };
                                });
                            }
                        }
                    },
                    tooltip: Object.assign({}, tooltipStyle, {
                        callbacks: {
                            label: (ctx) => {
                                const pct = total ? Math.round((ctx.parsed / total) * 100) : 0;
                                return nf.format(ctx.parsed) + ' listings (' + pct + '%)';
                            }
                        }
                    }),
                    miDonutCenter: { value: nf.format(total), label: 'Listings' }
                }
            },
            plugins: [donutCenterLabel]
        });


        fillDetails('details-price', ['Band', 'Listings', 'Share'], rows.map((r) => [
            priceBandLabel(r.price_bucket),
            nf.format(num(r.active_count)),
            total ? Math.round((num(r.active_count) / total) * 100) + '%' : '0%'
        ]));
    }

    function renderSourcePricing(data) {
        const byPrice = (data.listings_by_source || [])
            .filter((r) => num(r.avg_price) > 0)
            .sort((a, b) => num(b.avg_price) - num(a.avg_price))
            .slice(0, 8);

        horizontalBar(
            'chart-avg-price-source',
            byPrice.map(sourceLabel),
            byPrice.map((r) => Math.round(num(r.avg_price))),
            C.navy800,
            fmtMoneyCompact
        );

        fillDetails('details-avg-price', ['Source', 'Average', 'Median'], byPrice.map((r) => [
            sourceLabel(r), fmtMoneyCompact(r.avg_price), fmtMoneyCompact(r.median_price)
        ]));

        const bySqm = (data.listings_by_source || [])
            .filter((r) => num(r.avg_price_per_sqm) > 0)
            .sort((a, b) => num(b.avg_price_per_sqm) - num(a.avg_price_per_sqm))
            .slice(0, 8);

        horizontalBar(
            'chart-avg-sqm-source',
            bySqm.map(sourceLabel),
            bySqm.map((r) => Math.round(num(r.avg_price_per_sqm))),
            C.gold500,
            (v) => '€' + nf.format(Math.round(v))
        );

        fillDetails('details-avg-sqm', ['Source', '€/m²', 'Listings'], bySqm.map((r) => [
            sourceLabel(r), fmtMoneyExact(r.avg_price_per_sqm), nf.format(num(r.active_count))
        ]));
    }

    function renderComposition(data) {
        const k = data.kpis || {};
        const beds = sortedBedrooms(data);
        const topBed = beds.slice().sort((a, b) => num(b.active_count) - num(a.active_count))[0];

        const bands = (data.price_distribution || []).filter((r) => r.price_bucket !== 'poa');
        const topBand = bands.slice().sort((a, b) => num(b.active_count) - num(a.active_count))[0];

        const priceRange = (num(k.min_price) && num(k.max_price))
            ? fmtMoneyCompact(k.min_price) + ' – ' + fmtMoneyCompact(k.max_price)
            : '—';

        renderList('mi-composition', [
            ['fa-bed', 'Most Common Bedroom', topBed ? fmtBedroomLabel(topBed.bedroom_bucket) : '—'],
            ['fa-chart-simple', 'Largest Price Segment', topBand ? priceBandLabel(topBand.price_bucket) : '—'],
            ['fa-vector-square', 'Average Build Size', fmtArea(k.avg_build_area)],
            ['fa-map', 'Average Plot Size', fmtArea(k.avg_plot_area)],
            ['fa-tags', 'Price Range', priceRange],
            ['fa-store', 'Sources', nf.format((data.listings_by_source || []).length)]
        ]);
    }

    function renderOutliers(data) {
        const o = data.outliers || {};
        renderList('mi-outliers', [
            ['fa-arrow-up', 'Highest €/m²', num(o.highest_price_per_sqm) ? fmtMoneyExact(o.highest_price_per_sqm) + ' /m²' : '—', 'up'],
            ['fa-arrow-down', 'Lowest €/m²', num(o.lowest_price_per_sqm) ? fmtMoneyExact(o.lowest_price_per_sqm) + ' /m²' : '—', 'down'],
            ['fa-expand', 'Largest Plot', fmtArea(o.largest_plot)],
            ['fa-building', 'Largest Build', fmtArea(o.largest_build)]
        ]);
    }

    function renderList(containerId, rows) {
        const el = document.getElementById(containerId);
        if (!el) return;
        el.innerHTML = rows.map(([icon, label, value, mod]) => `
            <div class="mi-list-row${mod ? ' ' + mod : ''}">
                <i class="fas ${icon}"></i>
                <span class="mi-list-label">${escHtml(label)}</span>
                <span class="mi-list-value">${escHtml(value)}</span>
            </div>`).join('');
    }

    function renderDuplicates(data) {
        const d = data.duplicate_intelligence || {};
        setText('dup-active', nf.format(num(d.active_listings)));
        setText('dup-unique', nf.format(num(d.unique_properties)));
        setText('dup-listings', nf.format(num(d.duplicate_listings)));
        setText('dup-groups', nf.format(num(d.total_duplicate_groups)));

        const list = document.getElementById('mi-rank-list');
        if (!list) return;

        const items = d.top_widely_listed || [];
        if (!items.length) {
            list.innerHTML = '<div class="mi-empty">No property in this selection is listed by more than one agency.</div>';
            return;
        }

        list.innerHTML = items.map((item, i) => {
            const meta = [];
            const beds = fmtBedroomCount(item.bedrooms);
            if (beds) meta.push(beds);
            if (num(item.plot_area)) meta.push(fmtArea(item.plot_area) + ' Plot');
            else if (num(item.build_area)) meta.push(fmtArea(item.build_area) + ' Build');
            if (item.location) meta.push(item.location);

            const price = num(item.price) ? fmtMoneyCompact(item.price) : 'POA';
            return `
                <div class="mi-rank-row">
                    <span class="mi-rank-badge">${i + 1}</span>
                    <div class="mi-rank-body">
                        <div class="mi-rank-title">${escHtml(price)}${meta.length ? ' • ' + escHtml(meta.join(' • ')) : ''}</div>
                        <div class="mi-rank-meta">${escHtml((item.agencies || []).join(', '))}</div>
                    </div>
                    <span class="mi-rank-count">${num(item.agency_count)} Sources</span>
                </div>`;
        }).join('');
    }

    function renderSingleSource(data) {
        const d = data.duplicate_intelligence || {};
        const single = num(d.single_source_count);
        const pct = num(d.single_source_pct);

        setText('single-source-count', nf.format(single));
        setText('single-source-pct', Math.round(pct) + '%');

        makeChart('chart-single-source', {
            type: 'doughnut',
            data: {
                labels: ['Single source', 'Multiple sources'],
                datasets: [{
                    data: [single, Math.max(0, num(d.estimated_unique) - single)],
                    backgroundColor: [C.gold500, C.grey200],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '76%',
                plugins: {
                    legend: { display: false },
                    tooltip: Object.assign({}, tooltipStyle, {
                        callbacks: { label: (ctx) => ctx.label + ': ' + nf.format(ctx.parsed) }
                    })
                }
            }
        });
    }

    /** Populates the expandable table behind a card's "View Details" button. */
    function fillDetails(containerId, headers, rows) {
        const el = document.getElementById(containerId);
        if (!el) return;
        if (!rows.length) {
            el.innerHTML = '<div class="mi-empty">No data for the current filters.</div>';
            return;
        }
        el.innerHTML =
            '<table class="mi-matrix"><thead><tr>' +
            headers.map((h, i) => '<th' + (i === 0 ? '' : ' style="text-align:right"') + '>' + escHtml(h) + '</th>').join('') +
            '</tr></thead><tbody>' +
            rows.map((r) => '<tr>' + r.map((c, i) =>
                '<td' + (i === 0 ? '' : ' style="text-align:right"') + '>' + escHtml(c) + '</td>').join('') + '</tr>').join('') +
            '</tbody></table>';
    }

    // =========================================================================
    // View / navigation
    // =========================================================================
    function setViewParam(value) {
        const params = new URLSearchParams(window.location.search);
        if (value) params.set('view', value);
        else params.delete('view');
        const query = params.toString();
        window.history.replaceState(null, '', window.location.pathname + (query ? '?' + query : ''));
    }

    function setToggleState(active) {
        const listings = document.getElementById('btn-mode-listings');
        const mi = document.getElementById('btn-mode-mi');
        [[listings, active === 'listings'], [mi, active === 'mi']].forEach(([btn, on]) => {
            if (!btn) return;
            btn.classList.toggle('active', on);
            btn.classList.toggle('btn-primary', on);
            btn.classList.toggle('btn-secondary', !on);
        });
    }

    /**
     * The Quick Preview panel belongs to the property table, so it is hidden
     * while the dashboard is open. A dedicated class keeps this independent of
     * the `d-none` that main.js toggles for grid/table view, so returning to
     * Listings restores whichever state that view mode had.
     */
    function setPreviewHidden(hidden) {
        const panel = document.getElementById('preview-panel');
        if (panel) panel.classList.toggle('mi-hidden', hidden);
    }

    function showListings() {
        isMIActive = false;
        setViewParam(null);
        setToggleState('listings');
        setPreviewHidden(false);
        document.getElementById('view-listings-container').style.display = '';
        document.getElementById('view-mi-container').style.display = 'none';
    }

    function showMI() {
        const wasActive = isMIActive;
        isMIActive = true;
        setViewParam('mi');
        setToggleState('mi');
        setPreviewHidden(true);
        document.getElementById('view-listings-container').style.display = 'none';
        document.getElementById('view-mi-container').style.display = '';

        syncFromSidebar();

        if (!wasActive || !latest) {
            // Skeleton goes up immediately; the fetch waits a beat so the panel
            // is laid out before Chart.js measures its canvases.
            setLoading(true);
            setTimeout(fetchMarketIntelligence, 60);
        } else {
            // Charts must be redrawn: they were sized while hidden.
            setTimeout(() => render(latest), 30);
        }
    }

    function setupViewToggle() {
        const listings = document.getElementById('btn-mode-listings');
        const mi = document.getElementById('btn-mode-mi');
        if (listings) listings.addEventListener('click', showListings);
        if (mi) mi.addEventListener('click', showMI);
    }

    // =========================================================================
    // Filter bar — writes through to the Property Search sidebar
    // =========================================================================
    const el = (id) => document.getElementById(id);

    function fillSelect(select, options, placeholder) {
        if (!select) return;
        const current = select.value;
        select.innerHTML = '<option value="">' + placeholder + '</option>' +
            options.map((o) => '<option value="' + escHtml(o.value) + '">' + escHtml(o.label) + '</option>').join('');
        if (current) select.value = current;
    }

    async function loadFilterOptions() {
        try {
            const res = await fetch('/api/metadata');
            if (!res.ok) return;
            const meta = await res.json();
            fillSelect(el('mi-filter-location'),
                (meta.locations || []).map((l) => ({ value: l, label: l })), 'All Locations');
            fillSelect(el('mi-filter-type'),
                (meta.property_types || []).map((t) => ({ value: t, label: t })), 'All Types');
            // The sidebar's source options carry the FRIENDLY name as their value
            // (main.js sets option.value = src.label), and applyFilterBar() matches
            // against those options. Using the raw scraper key here would never
            // match, so the filter would silently do nothing. The API accepts the
            // friendly name and expands it to the raw keys server-side.
            fillSelect(el('mi-filter-source'),
                (meta.sources || []).map((s) => ({ value: s.label, label: s.label })), 'All Sources');
            syncFromSidebar();
        } catch (err) {
            console.error('[MI] could not load filter options:', err);
        }
    }

    /** Reflect whatever the sidebar currently holds in the dashboard's own bar. */
    function syncFromSidebar() {
        const locations = el('filter-locations');
        if (locations && el('mi-filter-location')) {
            const chosen = Array.from(locations.selectedOptions).map((o) => o.value);
            el('mi-filter-location').value = chosen.length === 1 ? chosen[0] : '';
        }
        if (el('filter-type') && el('mi-filter-type')) el('mi-filter-type').value = el('filter-type').value || '';

        const sources = el('filter-sources');
        if (sources && el('mi-filter-source')) {
            const chosen = Array.from(sources.selectedOptions).map((o) => o.value);
            el('mi-filter-source').value = chosen.length === 1 ? chosen[0] : '';
        }
    }

    function selectSingle(multi, value) {
        if (!multi) return;
        let matched = false;
        Array.from(multi.options).forEach((o) => {
            o.selected = value ? o.value === value : false;
            matched = matched || o.selected;
        });
        // A value that matches no option means the two controls disagree about
        // what an option's value is, and the filter would quietly do nothing.
        if (value && !matched) {
            console.warn('[MI] "' + value + '" matches no option in #' + multi.id +
                        ' - filter not applied');
        }
    }

    function applyFilterBar() {
        selectSingle(el('filter-locations'), el('mi-filter-location').value);
        selectSingle(el('filter-sources'), el('mi-filter-source').value);
        if (el('filter-type')) el('filter-type').value = el('mi-filter-type').value;

        const beds = el('mi-filter-beds').value;
        const minBeds = el('filter-min-beds');
        const maxBeds = el('filter-max-beds');
        if (minBeds && maxBeds) {
            if (!beds) {
                minBeds.value = '';
                maxBeds.value = '';
            } else if (beds === '9+') {
                minBeds.value = '9';
                maxBeds.value = '';
            } else {
                minBeds.value = beds;
                maxBeds.value = beds;
            }
        }

        const [min, max] = (el('mi-filter-price').value || '-').split('-');
        if (el('filter-min-price')) el('filter-min-price').value = min || '';
        if (el('filter-max-price')) el('filter-max-price').value = max || '';

        // Refreshing Property Search keeps both views on the same stock, and
        // main.js calls back into fetchMarketIntelligence() when it finishes.
        const search = el('btn-search');
        if (search) search.click();
        else fetchMarketIntelligence();
    }

    function setupFilterBar() {
        ['mi-filter-location', 'mi-filter-type', 'mi-filter-beds', 'mi-filter-price', 'mi-filter-source']
            .forEach((id) => {
                const select = el(id);
                if (select) select.addEventListener('change', applyFilterBar);
            });

        // The sidebar holds the full filter set; this just brings it forward
        // (and opens it on the mobile off-canvas layout).
        const openFilters = el('mi-open-filters');
        if (openFilters) {
            openFilters.addEventListener('click', () => {
                const sidebar = el('sidebar');
                if (!sidebar) return;
                sidebar.classList.add('active');
                const overlay = el('sidebar-overlay');
                if (overlay) overlay.classList.add('active');
                sidebar.scrollTop = 0;
            });
        }

        const reset = el('mi-reset-filters');
        if (reset) {
            reset.addEventListener('click', () => {
                ['mi-filter-location', 'mi-filter-type', 'mi-filter-beds', 'mi-filter-price', 'mi-filter-source']
                    .forEach((id) => { if (el(id)) el(id).value = ''; });
                const clear = el('btn-clear');
                if (clear) clear.click();       // resets every sidebar control, then refetches
                else fetchMarketIntelligence();
            });
        }
    }

    // =========================================================================
    // Card actions
    // =========================================================================
    function setupCardActions() {
        const bedroomBtn = el('mi-bedroom-mode');
        if (bedroomBtn) {
            bedroomBtn.addEventListener('click', () => {
                bedroomMode = bedroomMode === 'active' ? 'unique' : 'active';
                if (latest) renderBedroomChart(latest);
            });
        }

        const heatBtn = el('mi-matrix-heat');
        if (heatBtn) {
            heatBtn.addEventListener('click', () => {
                heatmapOn = !heatmapOn;
                heatBtn.textContent = 'Heatmap: ' + (heatmapOn ? 'On' : 'Off');
                if (latest) renderMatrix(latest);
            });
        }

        document.querySelectorAll('#view-mi-container [data-details]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const panel = el(btn.dataset.details);
                if (!panel) return;
                panel.hidden = !panel.hidden;
                btn.textContent = panel.hidden ? 'View Details' : 'Hide Details';
            });
        });

        const viewDuplicates = el('mi-view-duplicates');
        if (viewDuplicates) {
            viewDuplicates.addEventListener('click', () => {
                showListings();
                const uniqueStock = el('card-unique-stock');
                if (uniqueStock) uniqueStock.click();
            });
        }

        const refresh = el('mi-refresh');
        if (refresh) refresh.addEventListener('click', fetchMarketIntelligence);
    }

    // =========================================================================
    // Save view / share / export
    // =========================================================================
    function setupToolbar() {
        const save = el('mi-save-view');
        if (save) {
            save.addEventListener('click', () => {
                const view = { url: window.location.search, savedAt: Date.now() };
                const saved = JSON.parse(localStorage.getItem('sardo-mi-views') || '[]');
                saved.unshift(view);
                localStorage.setItem('sardo-mi-views', JSON.stringify(saved.slice(0, 10)));
                if (typeof showToast === 'function') {
                    showToast('View saved', 'This filter set is stored in this browser.', 'success');
                }
            });
        }

        const share = el('mi-share');
        if (share) {
            share.addEventListener('click', async () => {
                const url = window.location.origin + window.location.pathname + window.location.search;
                try {
                    await navigator.clipboard.writeText(url);
                    if (typeof showToast === 'function') {
                        showToast('Link copied', 'The filtered dashboard link is on your clipboard.', 'success');
                    }
                } catch (err) {
                    window.prompt('Copy this link:', url);
                }
            });
        }

        const exportBtn = el('mi-export-report');
        if (exportBtn) exportBtn.addEventListener('click', exportCsv);
    }

    /** Exports the aggregates currently on screen as a CSV. */
    function exportCsv() {
        if (!latest) {
            if (typeof showToast === 'function') {
                showToast('Nothing to export', 'Open the Market Intelligence dashboard first.', 'warning');
            }
            return;
        }
        const k = latest.kpis || {};
        const o = latest.outliers || {};
        const d = latest.duplicate_intelligence || {};
        const rows = [
            ['SARDO360 Market Intelligence', new Date().toLocaleString('en-GB')],
            [],
            ['Metric', 'Value'],
            ['Active listings', num(k.active_properties)],
            ['Estimated unique properties', num(k.unique_properties)],
            ['Duplicate listings', num(d.duplicate_listings)],
            ['Duplicate groups', num(k.duplicate_groups)],
            ['Single-source properties', num(d.single_source_count)],
            ['Total property stock value', Math.round(num(k.total_stock_value))],
            ['Priced unique properties', Math.max(0, num(k.unique_properties) - num(k.poa_count))],
            ['POA (no published price)', num(k.poa_count)],
            ['Average asking price', Math.round(num(k.avg_price))],
            ['Median asking price', Math.round(num(k.median_price))],
            ['Highest asking price', Math.round(num(k.max_price))],
            ['Lowest asking price', Math.round(num(k.min_price))],
            ['Average €/m² (build)', Math.round(num(k.avg_price_per_sqm))],
            ['Total build area (m²)', Math.round(num(k.total_build_area))],
            ['Average build area (m²)', Math.round(num(k.avg_build_area))],
            ['Average plot area (m²)', Math.round(num(k.avg_plot_area))],
            ['Highest €/m²', Math.round(num(o.highest_price_per_sqm))],
            ['Lowest €/m²', Math.round(num(o.lowest_price_per_sqm))],
            ['Largest plot (m²)', Math.round(num(o.largest_plot))],
            ['Largest build (m²)', Math.round(num(o.largest_build))],
            [],
            ['Source', 'Listings', 'Unique', 'Avg price', 'Avg €/m²']
        ];
        (latest.listings_by_source || []).forEach((r) => rows.push([
            sourceLabel(r), num(r.active_count), num(r.unique_count),
            Math.round(num(r.avg_price)), Math.round(num(r.avg_price_per_sqm))
        ]));
        rows.push([], ['Bedrooms', 'Listings', 'Unique']);
        sortedBedrooms(latest).forEach((r) => rows.push([
            fmtBedroomLabel(r.bedroom_bucket), num(r.active_count), num(r.unique_count)
        ]));
        rows.push([], ['Price band', 'Listings']);
        (latest.price_distribution || []).forEach((r) =>
            rows.push([priceBandLabel(r.price_bucket), num(r.active_count)]));

        const csv = rows.map((r) => r.map((c) => {
            const s = String(c === null || c === undefined ? '' : c);
            return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        }).join(',')).join('\n');

        const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'sardo360-market-intelligence-' +
            new Date().toISOString().slice(0, 10) + '.csv';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    }

    // =========================================================================
    // Boot
    // =========================================================================
    function init() {
        if (typeof Chart === 'undefined') {
            console.error('[MI] Chart.js did not load — check that ' +
                '/static/js/vendor/chart.umd.min.js is being served.');
        }
        setupViewToggle();
        setupFilterBar();
        setupCardActions();
        setupToolbar();
        loadFilterOptions();

        // Deep link: /?view=mi opens straight onto the dashboard.
        const params = new URLSearchParams(window.location.search);
        if (params.get('view') === 'mi') showMI();

        window.addEventListener('resize', () => {
            if (isMIActive) Object.values(charts).forEach((c) => c && c.resize());
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Let main.js refresh the dashboard whenever the sidebar filters change.
    window.fetchMarketIntelligence = fetchMarketIntelligence;
    window.isMIViewActive = () => isMIActive;
})();
