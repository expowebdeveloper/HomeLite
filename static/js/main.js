document.addEventListener('DOMContentLoaded', () => {
    // State
    let currentProperties = [];
    let selectedPropertyIds = new Set();
    let currentViewMode = 'table'; // 'grid' or 'table'
    let currentStockMode = 'active'; // 'active' or 'unique'
    let currentPage = 1;
    let itemsPerPage = 10;
    let totalPropertiesCount = 0;
    // Default view: most expensive properties first (client request).
    // The backend pushes P.O.A. listings (price NULL or <= 0) to the bottom for
    // either direction, so "High to Low" starts at the top of the market.
    let currentSortBy = 'price';
    let currentSortDir = 'DESC';


    // DOM Elements
    const cardActiveStock = document.getElementById('card-active-stock');
    const cardUniqueStock = document.getElementById('card-unique-stock');
    const statTotal = document.getElementById('stat-total');
    const statUnique = document.getElementById('stat-unique');
    const badgeDuplicatesCount = document.getElementById('badge-duplicates-count');
    const statAvg = document.getElementById('stat-avg');
    const filterLocations = document.getElementById('filter-locations');
    const filterType = document.getElementById('filter-type');
    const resultsCount = document.getElementById('results-count');
    const selectAllCheckbox = document.getElementById('select-all');
    const btnSearch = document.getElementById('btn-search');
    const btnClear = document.getElementById('btn-clear');
    const btnExportPdf = document.getElementById('btn-export-pdf');
    const btnExportExcel = document.getElementById('btn-export-excel');
    const btnDownloadCsvTemplate = document.getElementById('btn-download-csv-template');
    const filterRef = document.getElementById('filter-ref');
    const filterStatuses = document.getElementById('filter-statuses');
    const filterSources = document.getElementById('filter-sources');
    const filterTags = document.getElementById('filter-tags');
    const filterHideDelisted = document.getElementById('filter-hide-delisted');


    // Property status badge. "Under Offer" -> class "status-under-offer" (see style.css)
    // NULL / missing property_status from DB defaults to 'For Sale' (not 'Unknown')
    // because a property with no badge set by the scraper is still an active listing.
    const STATUS_ICONS = {
        'For Sale':     'fa-tag',
        'New Listing':  'fa-star',
        'Reserved':     'fa-clock',
        'Under Offer':  'fa-handshake',
        'Sold':         'fa-check-circle',
        'Exclusive':    'fa-gem',
        'Delisted':     'fa-ban',
        'Unknown':      'fa-question-circle',
        'Off Market':   'fa-lock',
        'Withdrawn':    'fa-times-circle',
    };

function energyBadge(rating) {
    if (!rating || rating === '—' || rating === 'N/A') return '—';
    let bg = '#e2e8f0';
    let color = '#475569';
    const r = String(rating).toUpperCase();
    if (r.startsWith('A')) { bg = '#16a34a'; color = '#fff'; }
    else if (r.startsWith('B')) { bg = '#65a30d'; color = '#fff'; }
    else if (r.startsWith('C')) { bg = '#ca8a04'; color = '#fff'; }
    else if (r.startsWith('D')) { bg = '#d97706'; color = '#fff'; }
    else if (r.startsWith('E')) { bg = '#ea580c'; color = '#fff'; }
    else if (r.startsWith('F')) { bg = '#dc2626'; color = '#fff'; }
    else if (r.startsWith('G')) { bg = '#991b1b'; color = '#fff'; }
    else if (r === 'ELECTRIC') { bg = '#0284c7'; color = '#fff'; }
    else if (r === 'SOLAR') { bg = '#fbbf24'; color = '#000'; }
    else if (r.startsWith('IN PROGRESS')) { bg = '#fef3c7'; color = '#b45309'; }
    else if (r === 'EXEMPT' || r === 'ISENTO') { bg = '#94a3b8'; color = '#fff'; }
    else { bg = '#334155'; color = '#fff'; }
    
    return `<span style="background: ${bg}; color: ${color}; padding: 3px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; display: inline-block; min-width: 24px; text-align: center;">${rating}</span>`;
}

    const statusBadge = (status) => {
        const canonical = (!status || status === 'Unknown') ? 'For Sale' : status;
        const cls = 'status-badge status-' + canonical.toLowerCase().replace(/\s+/g, '-');
        const icon = STATUS_ICONS[canonical] || 'fa-tag';
        return `<span class="badge ${cls}"><i class="fas ${icon}"></i> ${canonical}</span>`;
    };

    // Helper: Render custom property tags badges
    const renderTagsBadges = (tags) => {
        if (!tags || !Array.isArray(tags) || tags.length === 0) return '';
        return `<div class="tags-cloud-container" style="margin-top: 6px;">` +
            tags.map(t => `<span class="property-tag-badge" title="Tag: ${esc(t)}"><i class="fas fa-tag" style="font-size: 9px; opacity: 0.8;"></i> ${esc(t)}</span>`).join('') +
            `</div>`;
    };

    // Sold / Delisted / Withdrawn listings are no longer live stock
    const isInactiveStatus = (status) => status === 'Sold' || status === 'Delisted' || status === 'Withdrawn';
    const statusText = document.getElementById('status-text');
    const loadingOverlay = document.getElementById('loading-overlay');

    // Escape text destined for an HTML attribute (e.g. the Location title tooltip),
    // so a quote or angle bracket in the data can't break out of the attribute.
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // Utility: Format Currency
    const formatCurrency = (value) => {
        if (value === null || value === undefined || value === '' || isNaN(Number(value))) return 'N/A';
        const num = Number(value);
        return new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(num);
    };

    // Utility: Format a property price for display.
    const formatPrice = (value) => {
        if (value === null || value === undefined || value === '' || isNaN(Number(value)) || Number(value) <= 0) {
            return 'P.O.A.';
        }
        return formatCurrency(value);
    };

    // Utility: Show Loading
    const showLoading = (text = 'Loading...') => {
        document.getElementById('loading-text').innerText = text;
        loadingOverlay.style.display = 'flex';
        if (statusText) statusText.innerText = text;
    };

    const hideLoading = () => {
        loadingOverlay.style.display = 'none';
        if (statusText) statusText.innerText = 'Ready';
    };

    // DOM Elements specific to Views
    const propertiesGrid = document.getElementById('properties-grid');
    const tableArea = document.getElementById('table-area');
    const tableBody = document.getElementById('table-body');
    const previewPanel = document.getElementById('preview-panel');
    const previewImageContainer = document.getElementById('preview-image-container');
    const previewDetails = document.getElementById('preview-details');

    const btnViewGrid = document.getElementById('btn-view-grid');
    const btnViewTable = document.getElementById('btn-view-table');

    const propertyModal = document.getElementById('property-modal');
    const modalBody = document.getElementById('modal-body');
    const closeModal = document.querySelector('.close-modal');

    const gridSortContainer = document.getElementById('grid-sort-container');

    // Stock Mode Toggle (Active Stock vs Unique Stock)
    if (cardActiveStock && cardUniqueStock) {
        cardActiveStock.addEventListener('click', () => {
            if (currentStockMode === 'active') return;
            currentStockMode = 'active';
            cardActiveStock.classList.add('active');
            cardUniqueStock.classList.remove('active');
            currentPage = 1;
            fetchProperties(getFilters());
        });

        cardUniqueStock.addEventListener('click', () => {
            if (currentStockMode === 'unique') return;
            currentStockMode = 'unique';
            cardUniqueStock.classList.add('active');
            cardActiveStock.classList.remove('active');
            currentPage = 1;
            fetchProperties(getFilters());
        });
    }

    // View Toggle Logic
    const setViewMode = (mode) => {
        currentViewMode = mode;
        if (mode === 'grid') {
            btnViewGrid.classList.add('active');
            btnViewTable.classList.remove('active');
            propertiesGrid.classList.remove('d-none');
            tableArea.classList.add('d-none');
            previewPanel.classList.add('d-none');
            if (gridSortContainer) gridSortContainer.classList.remove('d-none');
        } else {
            btnViewTable.classList.add('active');
            btnViewGrid.classList.remove('active');
            tableArea.classList.remove('d-none');
            propertiesGrid.classList.add('d-none');
            previewPanel.classList.remove('d-none');
            if (gridSortContainer) gridSortContainer.classList.add('d-none');
        }
    };

    btnViewGrid.addEventListener('click', () => setViewMode('grid'));
    btnViewTable.addEventListener('click', () => setViewMode('table'));

    // Close Modal Logic
    closeModal.addEventListener('click', () => {
        propertyModal.style.display = 'none';
    });

    window.addEventListener('click', (event) => {
        if (event.target == propertyModal) {
            propertyModal.style.display = 'none';
        }
    });

    // Results are now returned directly from the backend based on our search criteria.
    const getVisibleProperties = () => {
        return currentProperties;
    };

    // Render Grid
    const renderGrid = () => {
        propertiesGrid.innerHTML = '';
        const visibleProperties = getVisibleProperties();
        if (visibleProperties.length === 0) {
            propertiesGrid.innerHTML = '<div class="no-results">No properties found matching your criteria.</div>';
            return;
        }

        visibleProperties.forEach((prop, index) => {
            const card = document.createElement('div');
            card.className = 'property-card';
            if (selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id)) {
                card.classList.add('selected');
            }

            // Price formatted
            const price = formatPrice(prop.property_price);

            const isOffMarket = prop.market_visibility === 'off_market' || prop.source_type === 'manual' || prop.website_source === 'Manual / Off-Market' || (prop.property_url && prop.property_url.startsWith('sardo://'));

            // Image handling
            const imgHtml = prop.image_url && prop.image_url !== 'null' && prop.image_url !== 'undefined'
                ? `<img src="${prop.image_url}" alt="Property" onerror="this.onerror=null; this.outerHTML='<div class=\\'no-image\\' style=\\'background: #0f172a; color: #64748b; display: flex; align-items: center; justify-content: center;\\'><i class=\\'fas fa-image-slash\\' style=\\'font-size: 2rem;\\'></i></div>';">`
                : (isOffMarket 
                    ? `<div class="no-image" style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #f59e0b; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 8px;"><i class="fas fa-user-secret" style="font-size: 2.5rem; opacity: 0.9;"></i><span style="font-size: 0.75rem; font-weight: 700; color: #cbd5e1; letter-spacing: 0.5px;">VIP ASSET</span></div>`
                    : `<div class="no-image"><i class="fas fa-image"></i></div>`);

            const offMarketBadge = isOffMarket
                ? `<div style="position: absolute; top: 10px; right: 10px; background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; z-index: 5; box-shadow: 0 4px 6px rgba(0,0,0,0.3); letter-spacing: 0.5px;"><i class="fas fa-user-secret"></i> VIP OFF-MARKET</div>`
                : '';

            card.innerHTML = `
                <div class="card-image-container" style="position: relative;">
                    ${imgHtml}
                    ${offMarketBadge}
                    <div class="checkbox-container">
                        <input type="checkbox" class="card-checkbox" value="${prop.id}" ${selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id) ? 'checked' : ''}>
                    </div>
                    <div class="card-price-badge">${price}</div>
                </div>
                <div class="card-content">
                    <h4 class="card-title">${prop.title && prop.title !== 'N/A' ? prop.title : (prop.property_type || 'Property')} in ${prop.location || 'Unknown'}</h4>
                    <div class="card-features">
                        <span title="Bedrooms"><i class="fas fa-bed"></i> ${prop.num_beds || '-'}</span>
                        <span title="Bathrooms"><i class="fas fa-bath"></i> ${prop.num_baths || '-'}</span>
                        <span title="Build Area"><i class="fas fa-ruler-combined"></i> ${prop.living_area ? parseFloat(prop.living_area).toFixed(0) + ' m²' : '-'}</span>
                    </div>
                    ${renderTagsBadges(prop.tags)}
                    <div class="card-footer" style="flex-direction: column; align-items: stretch; gap: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="display: flex; align-items: center; gap: 4px;">
                                <span class="card-source">${prop.display_source || 'Unknown'}</span>
                            </div>
                            ${statusBadge(prop.property_status)}
                        </div>
                        ${prop.duplicate_count > 1 ? `<button class="btn-duplicate-card" onclick="event.stopPropagation(); window.openDuplicateGroupModal('${prop.id}')"><i class="fas fa-copy"></i> +${prop.duplicate_count - 1}</button>` : ''}
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary);">Ref: ${prop.sardo_reference || 'N/A'}</span>
                            ${isOffMarket ? `<span style="color: #f59e0b; font-size: 0.8rem; font-weight: 700;"><i class="fas fa-lock"></i> Confidential</span>` : ''}
                        </div>
                        <div style="width: 100%;">
                            <button class="btn-view-details" style="width: 100%;">View Details</button>
                        </div>
                        ${isOffMarket ? `
                            <div style="display: flex; gap: 8px; width: 100%; margin-top: 2px;">
                                <button onclick="event.stopPropagation(); openEditManualModal('${prop.id}')" style="flex: 1; background: #3b82f6; color: white; border: none; padding: 8px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(59,130,246,0.2); transition: all 0.2s;" title="Edit Off-Market Property"><i class="fas fa-edit"></i> Edit</button>
                                <button onclick="event.stopPropagation(); deleteManualPropertyConfirm('${prop.id}')" style="flex: 1; background: #ef4444; color: white; border: none; padding: 8px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; box-shadow: 0 2px 4px rgba(239,68,68,0.2); transition: all 0.2s;" title="Delete Property"><i class="fas fa-trash-alt"></i> Delete</button>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;

            // View Details button opens the modal
            const viewBtn = card.querySelector('.btn-view-details');
            if (viewBtn) {
                viewBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showModal(prop);
                });
            }

            // Clicking the card toggles selection (same as table rows)
            card.addEventListener('click', (e) => {
                if (e.target.closest('button') || e.target.closest('a') || e.target.closest('.card-checkbox')) {
                    return;
                }
                const checkbox = card.querySelector('.card-checkbox');
                if (checkbox) {
                    checkbox.checked = !checkbox.checked;
                    checkbox.dispatchEvent(new Event('change'));
                }
            });

            // Checkbox logic
            const checkbox = card.querySelector('.card-checkbox');
            const checkboxContainer = card.querySelector('.checkbox-container');
            if (checkboxContainer) {
                checkboxContainer.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (e.target !== checkbox) {
                        checkbox.checked = !checkbox.checked;
                        checkbox.dispatchEvent(new Event('change'));
                    }
                });
            }

            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                if (e.target.checked) {
                    selectedPropertyIds.add(prop.id.toString());
                    card.classList.add('selected');
                } else {
                    selectedPropertyIds.delete(prop.id.toString());
                    selectedPropertyIds.delete(prop.id); // in case it was stored as int
                    card.classList.remove('selected');
                }
                // Sync table row if it exists
                const rowCb = tableBody.querySelector(`.row-checkbox[value="${prop.id}"]`);
                if (rowCb) {
                    rowCb.checked = e.target.checked;
                    if (e.target.checked) rowCb.closest('tr').classList.add('selected-row');
                    else rowCb.closest('tr').classList.remove('selected-row');
                }
                updateExportButtons();
            });

            propertiesGrid.appendChild(card);
        });
    };

    // Render Table
    const renderTable = () => {
        tableBody.innerHTML = '';
        if (previewImageContainer) previewImageContainer.innerHTML = `<div class="no-image-placeholder"><i class="fas fa-mouse-pointer" style="font-size: 24px; margin-bottom: 10px;"></i><p>Hover over a property to preview</p></div>`;
        if (previewDetails) previewDetails.innerHTML = `<div style="text-align: center; color: var(--text-secondary); margin-top: 20px;"><p>No property selected.</p></div>`;
        const visibleProperties = getVisibleProperties();
        if (visibleProperties.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = `<td colspan="12" style="text-align: center; padding: 30px;">No properties found matching your criteria.</td>`;
            tableBody.appendChild(row);
            return;
        }

        visibleProperties.forEach((prop, index) => {
            const row = document.createElement('tr');
            const propIdStr = String(prop.id ?? index);
            if (selectedPropertyIds.has(propIdStr) || selectedPropertyIds.has(prop.id)) {
                row.classList.add('selected-row');
            }
            if (isInactiveStatus(prop.property_status)) {
                row.classList.add('row-inactive');
            }

            // Format values safely
            const price = formatPrice(prop.property_price);
            const livingArea = (prop.living_area && !isNaN(parseFloat(prop.living_area))) ? parseFloat(prop.living_area).toFixed(0) : '—';
            const landArea = (prop.land_area && !isNaN(parseFloat(prop.land_area))) ? parseFloat(prop.land_area).toFixed(0) : '—';
            const isOffMarket = prop.market_visibility === 'off_market' || prop.source_type === 'manual' || prop.website_source === 'Manual / Off-Market' || (prop.property_url && prop.property_url.startsWith('sardo://'));
            const offMarketTag = isOffMarket ? '<span style="background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; margin-left: 6px;"><i class="fas fa-user-secret"></i> VIP OFF-MARKET</span>' : '';

            row.innerHTML = `
                <td onclick="event.stopPropagation();">
                    <input type="checkbox" class="row-checkbox" value="${propIdStr}" ${selectedPropertyIds.has(propIdStr) || selectedPropertyIds.has(prop.id) ? 'checked' : ''}>
                </td>
                <td style="font-weight: 600; color: var(--primary-color);">${price}</td>
                <td title="${esc(prop.location || 'N/A')}">${prop.location || 'N/A'} ${offMarketTag} ${renderTagsBadges(prop.tags)}</td>
                <td>${prop.property_type || 'N/A'}</td>
                <td>${prop.num_beds || '-'}</td>
                <td>${prop.num_baths || '-'}</td>
                <td>${livingArea}</td>
                <td>${landArea}</td>
                <td>${prop.construction_year || '—'}</td>
                <td>${energyBadge(prop.energy_rating)}</td>
                <td><span class="source-badge">${prop.display_source || 'N/A'}</span> ${prop.duplicate_count > 1 ? `<button class="btn-duplicate" onclick="event.stopPropagation(); window.openDuplicateGroupModal('${prop.id}')"><i class="fas fa-copy"></i> +${prop.duplicate_count - 1}</button>` : ''}</td>
                <td>${statusBadge(prop.property_status)}</td>
                <td>${prop.sardo_reference || 'N/A'}</td>
                <td>
                    ${prop.property_url && !isOffMarket 
                        ? `<a href="${prop.property_url}" target="_blank" class="ref-link" onclick="event.stopPropagation();">${prop.display_reference || 'Link'}</a>` 
                        : `<a href="javascript:void(0)" class="off-market-ref-link" style="color: #3b82f6; font-weight: 700; text-decoration: underline; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;" title="Click to open details card"><i class="fas fa-id-card"></i> ${prop.display_reference || prop.sardo_reference || 'N/A'}</a>`}
                </td>
            `;

            const offRefBtn = row.querySelector('.off-market-ref-link');
            if (offRefBtn) {
                offRefBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    showModal(prop);
                });
            }

            row.addEventListener('click', () => {
                const checkbox = row.querySelector('.row-checkbox');
                checkbox.checked = !checkbox.checked;
                checkbox.dispatchEvent(new Event('change'));
            });

            row.addEventListener('mouseenter', () => {
                showPreview(prop);
            });

            const checkbox = row.querySelector('.row-checkbox');
            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                if (e.target.checked) {
                    selectedPropertyIds.add(prop.id.toString());
                    row.classList.add('selected-row');
                } else {
                    selectedPropertyIds.delete(prop.id.toString());
                    selectedPropertyIds.delete(prop.id);
                    row.classList.remove('selected-row');
                }
                // Sync grid card if it exists
                const cardCb = propertiesGrid.querySelector(`.card-checkbox[value="${prop.id}"]`);
                if (cardCb) {
                    cardCb.checked = e.target.checked;
                    if (e.target.checked) cardCb.closest('.property-card').classList.add('selected');
                    else cardCb.closest('.property-card').classList.remove('selected');
                }
                updateExportButtons();
            });

            tableBody.appendChild(row);
        });
    };

    // Show Right Sidebar Preview
    const showPreview = (prop) => {
        const price = formatPrice(prop.property_price);
        const imgHtml = prop.image_url
            ? `<img src="${prop.image_url}" alt="Property" onerror="this.src=''; this.onerror=null; this.parentElement.innerHTML='<div class=\\'no-image-placeholder\\'><i class=\\'fas fa-image-slash\\'></i><p>Image not found</p></div>';">`
            : `<div class="no-image-placeholder"><i class="fas fa-image"></i><p>No image available</p></div>`;

        previewImageContainer.innerHTML = imgHtml;

        previewDetails.innerHTML = `
            <h4 style="font-size: 1.1rem; color: var(--primary-color); margin-bottom: 10px; line-height: 1.3;">
                ${prop.title && prop.title !== 'N/A' ? prop.title : (prop.property_type || 'Property')}
            </h4>
            <div style="font-size: 1.4rem; font-weight: 700; color: var(--accent-color); margin-bottom: 15px;">
                ${price}
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.95rem; color: var(--text-secondary);">
                <p><i class="fas fa-map-marker-alt" style="width: 20px; color: var(--accent-color);"></i> <strong>Location:</strong> ${prop.location || 'N/A'}</p>
                <p><i class="fas fa-bed" style="width: 20px; color: var(--accent-color);"></i> <strong>Beds:</strong> ${prop.num_beds || '-'}</p>
                <p><i class="fas fa-bath" style="width: 20px; color: var(--accent-color);"></i> <strong>Baths:</strong> ${prop.num_baths || '-'}</p>
                <p><i class="fas fa-ruler-combined" style="width: 20px; color: var(--accent-color);"></i> <strong>Build:</strong> ${prop.living_area ? parseFloat(prop.living_area).toFixed(0) + ' m²' : '-'}</p>
                <p><i class="fas fa-tree" style="width: 20px; color: var(--accent-color);"></i> <strong>Plot:</strong> ${prop.land_area ? parseFloat(prop.land_area).toFixed(0) + ' m²' : '-'}</p>
                <hr style="border:none; border-top: 1px solid var(--border-color); margin: 10px 0;">
                <p><strong>Type:</strong> ${prop.property_type || 'N/A'}</p>
                <p><strong>Source:</strong> ${prop.display_source || 'N/A'}</p>
                <p><strong>Status:</strong> ${statusBadge(prop.property_status)}</p>
                <p><strong>SARDO Ref:</strong> ${prop.sardo_reference || 'N/A'}</p>
                <p><strong>Year Built:</strong> ${prop.construction_year || '—'}</p>
                <p><strong>Energy Rating:</strong> ${energyBadge(prop.energy_rating)}</p>
                
                <!-- Interactive Quick Preview Tag Editor -->
                <div class="preview-tag-editor-box">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--text-secondary);"><i class="fas fa-tags" style="color: #6366f1;"></i> Custom Tags</span>
                        <span style="font-size: 10px; color: #94a3b8;">Click ✕ to remove</span>
                    </div>
                    <div id="preview-tags-cloud-${prop.id}" class="tags-cloud-container" style="min-height: 24px; margin-bottom: 8px;">
                        ${(prop.tags && Array.isArray(prop.tags) && prop.tags.length > 0)
                            ? prop.tags.map(t => `<span class="property-tag-chip" style="font-size: 11px; padding: 2px 8px;">${esc(t)} <i class="fas fa-times remove-preview-tag-btn" data-property-id="${prop.id}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('')
                            : '<span style="color: #94a3b8; font-size: 11px; font-style: italic;">No tags assigned</span>'}
                    </div>
                    <div style="display: flex; gap: 6px; position: relative;">
                        <input type="text" id="preview-new-tag-input-${prop.id}" list="global-tags-datalist" placeholder="Add tag (e.g. Sea View)..." style="flex: 1; padding: 5px 8px; font-size: 11px; border: 1px solid #cbd5e1; border-radius: 6px; outline: none; background: white;" onkeypress="if(event.key==='Enter'){event.preventDefault(); handleAddPreviewTag('${prop.id}');}">
                        <button type="button" onclick="handleAddPreviewTag('${prop.id}')" style="background: var(--primary-color); color: white; border: none; padding: 5px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer;" title="Add Tag">
                            <i class="fas fa-plus"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    };

    // Show Modal Details
    const showModal = (prop) => {
        const price = formatPrice(prop.property_price);
        const isOffMarket = prop.market_visibility === 'off_market' || prop.source_type === 'manual' || prop.website_source === 'Manual / Off-Market' || (prop.property_url && prop.property_url.startsWith('sardo://'));

        const imgHtml = prop.image_url && prop.image_url !== 'null' && prop.image_url !== 'undefined'
            ? `<img src="${prop.image_url}" class="modal-main-img" alt="Property" style="height: 400px; width: 100%; object-fit: cover;" onerror="this.onerror=null; this.outerHTML='<div style=\\'height:400px; width:100%; background:#0f172a; display:flex; flex-direction:column; justify-content:center; align-items:center; color:#64748b; gap:12px;\\'><i class=\\'fas fa-image-slash\\' style=\\'font-size:3rem;\\'></i><span>Image Unavailable</span></div>';">`
            : (isOffMarket
                ? `<div style="height: 400px; width: 100%; background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); display: flex; flex-direction: column; justify-content: center; align-items: center; color: #f59e0b; gap: 16px; border-bottom: 1px solid #334155; position: relative;"><div style="width:80px; height:80px; border-radius:50%; background:rgba(245, 158, 11, 0.1); display:flex; align-items:center; justify-content:center; border:1px solid rgba(245, 158, 11, 0.3); box-shadow: 0 4px 12px rgba(0,0,0,0.3);"><i class="fas fa-user-secret" style="font-size: 2.5rem;"></i></div><div style="text-align:center;"><h3 style="margin:0; font-size:1.3rem; font-weight:700; color:#f8fafc; letter-spacing:0.5px;">VIP Confidential Opportunity</h3><p style="margin:6px 0 0; font-size:0.85rem; color:#94a3b8;">Private asset details & restricted viewing</p></div></div>`
                : `<div style="height: 400px; width: 100%; background: #0f172a; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #64748b; gap: 12px;"><i class="fas fa-image" style="font-size: 3.5rem; opacity: 0.5;"></i><span>No Photos Available</span></div>`);

        const actionsHtml = isOffMarket ? `
            <div style="width: 100%; display: flex; flex-direction: column; gap: 12px;">
                <div style="background: #1e293b; color: #f59e0b; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 600; text-align: center; border: 1px solid #334155;"><i class="fas fa-lock"></i> VIP Confidential Opportunity</div>
                <div style="display: flex; gap: 10px; width: 100%;">
                    <button onclick="openEditManualModal('${prop.id}')" style="flex: 1; background: #3b82f6; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 14px; box-shadow: 0 2px 4px rgba(59,130,246,0.3); transition: all 0.2s;"><i class="fas fa-edit"></i> Edit Property</button>
                    <button onclick="deleteManualPropertyConfirm('${prop.id}')" style="flex: 1; background: #ef4444; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: 600; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; font-size: 14px; box-shadow: 0 2px 4px rgba(239,68,68,0.3); transition: all 0.2s;"><i class="fas fa-trash-alt"></i> Delete Property</button>
                </div>
            </div>
        ` : (prop.property_url ? `<a href="${prop.property_url}" target="_blank" class="preview-link" style="width: 100%; justify-content: center;"><i class="fas fa-external-link-alt"></i> View Original Listing</a>` : '');

        const offMarketBadgeModal = isOffMarket
            ? `<div style="background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 700; display: inline-block; margin-bottom: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);"><i class="fas fa-user-secret"></i> VIP Off-Market Property</div>`
            : '';

        const extraManualFields = isOffMarket ? `
            <hr style="border:none; border-top: 1px solid var(--border-color); margin: 12px 0;">
            <p><strong>Resort Area:</strong> ${prop.resort_area || 'N/A'}</p>
            <p><strong>Sub Area:</strong> ${prop.sub_area || 'N/A'}</p>
            <p><strong>Address:</strong> ${prop.address || 'Confidential'}</p>
            <p><strong>Coordinates:</strong> ${prop.coordinates || 'N/A'}</p>
            <hr style="border:none; border-top: 1px solid var(--border-color); margin: 12px 0;">
            <p><strong>Contact Name:</strong> ${prop.source_contact_name || 'N/A'}</p>
            <p><strong>Contact Email:</strong> ${prop.source_contact_email || 'N/A'}</p>
            <p><strong>Contact Phone:</strong> ${prop.source_contact_phone || 'N/A'}</p>
            <p><strong>Source Agent:</strong> ${prop.source_agent || 'N/A'}</p>
            <p><strong>Introduced By:</strong> ${prop.introduced_by || 'N/A'}</p>
            <p><strong>Notes:</strong> <span style="color:#64748b; font-style:italic;">${prop.notes || 'No confidential notes'}</span></p>
            <div id="modal-docs-container" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--border-color);">
                <h4 style="font-size:14px; margin-bottom:10px; color:var(--text-primary);"><i class="fas fa-folder-open"></i> Attached Documents</h4>
                <div id="modal-docs-list" style="display:flex; flex-wrap:wrap; gap:8px;">Loading documents...</div>
            </div>
        ` : '';

        modalBody.innerHTML = `
            <div class="modal-grid">
                <div class="modal-image-col">
                    ${imgHtml}
                    <div class="modal-actions" style="padding: 20px; background: var(--bg-color); display: flex; justify-content: center;">
                        ${actionsHtml}
                    </div>
                </div>
                <div class="modal-details-col">
                    ${offMarketBadgeModal}
                    <h2>${prop.title && prop.title !== 'N/A' ? prop.title : (prop.property_type || 'Property')}</h2>
                    <h3 class="modal-price">${price}</h3>
                    <p class="modal-location"><i class="fas fa-map-marker-alt"></i> ${prop.location || 'Unknown Location'}</p>
                    
                    <div class="modal-features">
                        <div class="feature"><i class="fas fa-bed"></i> <strong>${prop.num_beds || '-'}</strong> Beds</div>
                        <div class="feature"><i class="fas fa-bath"></i> <strong>${prop.num_baths || '-'}</strong> Baths</div>
                        <div class="feature"><i class="fas fa-home"></i> <strong>${prop.living_area ? parseFloat(prop.living_area).toFixed(0) : '-'} m²</strong> Build</div>
                        <div class="feature"><i class="fas fa-tree"></i> <strong>${prop.land_area ? parseFloat(prop.land_area).toFixed(0) : '-'} m²</strong> Plot</div>
                    </div>
                    
                    <div class="modal-meta">
                        <p><strong>Property Type:</strong> ${prop.property_type || 'N/A'}</p>
                        <p><strong>Source:</strong> ${prop.display_source || 'N/A'}</p>
                        <p><strong>Status:</strong> ${statusBadge(prop.property_status)}</p>
                        <p><strong>SARDO Ref:</strong> ${prop.sardo_reference || 'N/A'}</p>
                        <p><strong>Original Ref:</strong> ${prop.display_reference || 'N/A'}</p>
                        <p><strong>Construction / Renovation:</strong> ${prop.construction_year || 'N/A'} / ${prop.renovation_year || 'N/A'}</p>
                        <p><strong>Energy Rating:</strong> ${energyBadge(prop.energy_rating)}</p>
                        
                        <!-- Interactive Tags Section in Property Modal -->
                        <div class="modal-tags-section" style="margin-top: 16px; padding: 14px; background: #f8fafc; border: 1px solid var(--border-color); border-radius: 10px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <label style="font-size: 12px; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.5px;"><i class="fas fa-tags" style="color: #6366f1;"></i> Custom Tags</label>
                                <span style="font-size: 11px; color: var(--text-secondary);">Click (✕) to remove</span>
                            </div>
                            <div id="modal-tags-list" class="tags-cloud-container" style="min-height: 28px; margin-bottom: 10px;">
                                ${(prop.tags && Array.isArray(prop.tags) && prop.tags.length > 0)
                                    ? prop.tags.map(t => `<span class="property-tag-chip">${esc(t)} <i class="fas fa-times remove-modal-tag-btn" data-property-id="${prop.id}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('')
                                    : '<span style="color: #94a3b8; font-size: 12px; font-style: italic;">No tags assigned yet</span>'}
                            </div>
                            <div style="display: flex; gap: 8px;">
                                <input type="text" id="modal-new-tag-input" list="global-tags-datalist" placeholder="Add tag (e.g. Sea View, Golf Course Views)..." style="flex: 1; padding: 7px 12px; font-size: 12px; border: 1px solid #cbd5e1; border-radius: 6px; outline: none; background: white;" onkeypress="if(event.key==='Enter'){event.preventDefault(); handleAddModalTag('${prop.id}');}">
                                <button type="button" onclick="handleAddModalTag('${prop.id}')" style="background: var(--primary-color); color: white; border: none; padding: 7px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 4px;">
                                    <i class="fas fa-plus"></i> Add Tag
                                </button>
                            </div>
                        </div>

                        ${extraManualFields}
                    </div>
                </div>
            </div>
        `;
        propertyModal.style.display = 'flex';
        updateGlobalTagsDatalist();
        if (isOffMarket && typeof loadPropertyDocumentsForModal === 'function') {
            loadPropertyDocumentsForModal(prop.id);
        }
    };

    // Build Filters Object
    const getFilters = () => {
        const filters = {};

        const minPrice = document.getElementById('filter-min-price').value;
        if (minPrice) filters.min_price = parseFloat(minPrice);

        const maxPrice = document.getElementById('filter-max-price').value;
        if (maxPrice) filters.max_price = parseFloat(maxPrice);

        const selectedLocations = Array.from(filterLocations.selectedOptions).map(opt => opt.value);
        if (selectedLocations.length > 0) filters.locations = selectedLocations;

        const type = filterType.value;
        if (type) filters.property_type = type;

        const minBeds = document.getElementById('filter-min-beds').value;
        if (minBeds) filters.min_beds = parseInt(minBeds);

        const maxBeds = document.getElementById('filter-max-beds').value;
        if (maxBeds) filters.max_beds = parseInt(maxBeds);

        const minBaths = document.getElementById('filter-min-baths').value;
        if (minBaths) filters.min_baths = parseInt(minBaths);

        const maxBaths = document.getElementById('filter-max-baths').value;
        if (maxBaths) filters.max_baths = parseInt(maxBaths);

        // Property status (multi-select)
        const selectedStatuses = filterStatuses
            ? Array.from(filterStatuses.selectedOptions).map(opt => opt.value)
            : [];
        if (selectedStatuses.length > 0) filters.statuses = selectedStatuses;

        // Hide delisted stock. Skipped when the user explicitly asked for Delisted,
        // otherwise the two filters would contradict each other and return nothing.
        if (filterHideDelisted && filterHideDelisted.checked && !selectedStatuses.includes('Delisted')) {
            filters.exclude_delisted = true;
        }

        // Agent / Sources Filter
        const selectedSources = filterSources ? Array.from(filterSources.selectedOptions).map(opt => opt.value) : [];
        if (selectedSources.length > 0) filters.sources = selectedSources;

        // Tags Filter
        const selectedTags = filterTags ? Array.from(filterTags.selectedOptions).map(opt => opt.value) : [];
        if (selectedTags.length > 0) filters.tags = selectedTags;

        // Global reference search
        if (filterRef && filterRef.value.trim()) {
            filters.reference = filterRef.value.trim();
        }

        const vis = document.getElementById('filter-visibility');
        if (vis && vis.value && vis.value !== 'all') {
            filters.market_visibility = vis.value;
        }

        const stype = document.getElementById('filter-source-type');
        if (stype && stype.value && stype.value !== 'all') {
            filters.source_type = stype.value;
        }

        if (currentSortBy) {
            filters.sort_by = currentSortBy;
            filters.sort_dir = currentSortDir;
        }

        // Pass current stock mode ('active' or 'unique')
        filters.stock_mode = currentStockMode;

        return filters;
    };

    // Event Listeners
    btnSearch.addEventListener('click', () => {
        currentPage = 1; // Reset to first page on new search
        const filters = getFilters();
        fetchProperties(filters);
    });

    btnClear.addEventListener('click', () => {
        document.getElementById('filter-min-price').value = '';
        document.getElementById('filter-max-price').value = '';
        filterLocations.selectedIndex = -1;
        filterType.value = '';
        document.getElementById('filter-min-beds').value = '';
        document.getElementById('filter-max-beds').value = '';
        document.getElementById('filter-min-baths').value = '';
        document.getElementById('filter-max-baths').value = '';
        if (filterRef) filterRef.value = '';
        if (filterStatuses) filterStatuses.selectedIndex = -1;
        if (filterSources) filterSources.selectedIndex = -1;
        if (filterTags) filterTags.selectedIndex = -1;
        if (filterHideDelisted) filterHideDelisted.checked = true;
        const vis = document.getElementById('filter-visibility');
        if (vis) vis.value = 'all';
        const stype = document.getElementById('filter-source-type');
        if (stype) stype.value = 'all';

        // Clear resets to the default view, which still hides delisted stock
        currentPage = 1;
        fetchProperties(getFilters());
    });

    const updateResultsInfo = () => {
        if (!resultsCount) return;
        resultsCount.innerText = `${totalPropertiesCount} Properties Found`;
    };

    // Auto-search logic: when user stops typing for 1 second, OR presses Enter, OR clicks away
    if (filterRef) {
        let debounceTimer;

        // Auto-search after user stops typing for 1 second
        filterRef.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                btnSearch.click();
            }, 1000); // 1 full second delay
        });

        // Search immediately if they click outside the box
        filterRef.addEventListener('blur', () => {
            clearTimeout(debounceTimer);
            btnSearch.click();
        });
        
        // Search immediately if they press Enter
        filterRef.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                clearTimeout(debounceTimer);
                btnSearch.click();
            }
        });
    }

    const visFilter = document.getElementById('filter-visibility');
    if (visFilter) visFilter.addEventListener('change', () => btnSearch.click());
    const stypeFilter = document.getElementById('filter-source-type');
    if (stypeFilter) stypeFilter.addEventListener('change', () => btnSearch.click());

    selectAllCheckbox.addEventListener('change', (e) => {
        const isChecked = e.target.checked;
        const checkboxes = document.querySelectorAll('.card-checkbox, .row-checkbox');

        checkboxes.forEach(cb => {
            cb.checked = isChecked;
        });

        getVisibleProperties().forEach(prop => {
            if (isChecked) {
                selectedPropertyIds.add(prop.id.toString());
            } else {
                selectedPropertyIds.clear();
            }
        });

        // Update DOM classes
        document.querySelectorAll('.property-card').forEach(c => isChecked ? c.classList.add('selected') : c.classList.remove('selected'));
        document.querySelectorAll('tbody tr').forEach(r => isChecked ? r.classList.add('selected-row') : r.classList.remove('selected-row'));

        updateExportButtons();
    });

    // Handle Exports
    const updateExportButtons = () => {
        const hasSelection = selectedPropertyIds.size > 0;
        btnExportPdf.disabled = !hasSelection;
        btnExportExcel.disabled = !hasSelection;
    };

    // Utility: Toast Notification
    const showToast = (message, type = 'success') => {
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        const icon = type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle';

        toast.innerHTML = `
            <i class="fas ${icon}"></i>
            <span class="toast-message">${message}</span>
        `;

        toastContainer.appendChild(toast);

        // Trigger reflow for animation
        setTimeout(() => {
            toast.classList.add('show');
        }, 10);

        // Remove after 3 seconds
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => {
                toast.remove();
            }, 400); // Wait for transition
        }, 3000);
    };

    const downloadExport = async (endpoint, filenameExtension) => {
        if (selectedPropertyIds.size === 0) {
            showToast('Please select at least one property to export.', 'error');
            return;
        }

        const clientName = document.getElementById('export-client').value || 'Client';
        // Get the full property objects for the selected IDs
        const propertiesToExport = currentProperties.filter(p => selectedPropertyIds.has(p.id.toString()) || selectedPropertyIds.has(p.id));

        showLoading(`Generating ${filenameExtension.toUpperCase()}...`);
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    client_name: clientName,
                    properties: propertiesToExport
                })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || 'Export failed');
            }

            // Handle file download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;

            // Try to extract filename from Content-Disposition header
            let filename = `export.${filenameExtension}`;
            const disposition = response.headers.get('content-disposition');
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }

            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);

            hideLoading();
            statusText.innerText = `${filenameExtension.toUpperCase()} Exported Successfully`;
            showToast(`${filenameExtension.toUpperCase()} downloaded successfully!`, 'success');
        } catch (error) {
            console.error('Export error:', error);
            showToast(`Export failed: ${error.message}`, 'error');
            hideLoading();
            statusText.innerText = `Export Failed`;
        }
    };

    btnExportPdf.addEventListener('click', () => downloadExport('/api/export/pdf', 'pdf'));
    btnExportExcel.addEventListener('click', () => downloadExport('/api/export/excel', 'xlsx'));

    if (btnDownloadCsvTemplate) {
        btnDownloadCsvTemplate.addEventListener('click', async (e) => {
            e.preventDefault();
            showLoading('Generating CSV Template...');
            try {
                const response = await fetch('/api/properties/tags/sample-csv', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(getFilters())
                });
                if (!response.ok) throw new Error('Failed to generate template');
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = 'sardo_property_tags_template.csv';
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                showToast('CSV Template downloaded successfully!', 'success');
            } catch (error) {
                console.error('CSV template error:', error);
                showToast(`Failed to download template: ${error.message}`, 'error');
            } finally {
                hideLoading();
            }
        });
    }

    // Load Metadata on Startup
    const loadMetadata = async () => {
        try {
            showLoading('Loading configuration...');
            const response = await fetch('/api/metadata');
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            if (!response.ok) {
                console.error(`Server returned HTTP ${response.status}`);
            } else {
                const data = await response.json();

                // Populate Locations
                if (filterLocations && Array.isArray(data.locations)) {
                    filterLocations.innerHTML = '';
                    data.locations.forEach(loc => {
                        if (loc) {
                            const option = document.createElement('option');
                            option.value = loc;
                            option.textContent = loc;
                            filterLocations.appendChild(option);
                        }
                    });
                }

                // Populate Types
                if (filterType && Array.isArray(data.property_types)) {
                    data.property_types.forEach(type => {
                        if (type) {
                            const option = document.createElement('option');
                            option.value = type;
                            option.textContent = type;
                            filterType.appendChild(option);
                        }
                    });
                }

                // Populate Statuses (canonical vocabulary from the server)
                if (filterStatuses && Array.isArray(data.statuses)) {
                    filterStatuses.innerHTML = '';
                    data.statuses.forEach(status => {
                        if (status) {
                            const option = document.createElement('option');
                            option.value = status;
                            option.textContent = status;
                            filterStatuses.appendChild(option);
                        }
                    });
                }

                // Populate Agents / Sources (raw value for filtering, friendly label for display)
                if (filterSources && Array.isArray(data.sources)) {
                    filterSources.innerHTML = '';
                    data.sources.forEach(src => {
                        if (src && src.value) {
                            const option = document.createElement('option');
                            option.value = src.value;
                            option.textContent = src.label || src.value;
                            filterSources.appendChild(option);
                        }
                    });
                }

                // Populate Custom Tags
                if (filterTags && Array.isArray(data.tags)) {
                    filterTags.innerHTML = '';
                    data.tags.forEach(t => {
                        if (t && t.tag) {
                            const option = document.createElement('option');
                            option.value = t.tag;
                            option.textContent = `${t.tag} (${t.count})`;
                            filterTags.appendChild(option);
                        }
                    });
                }

                // Set Stats safely
                if (data.stats) {
                    const activeCount = (data.stats.active_properties !== undefined)
                        ? data.stats.active_properties
                        : (data.stats.total_properties || 0);

                    if (statTotal) statTotal.innerText = Number(activeCount).toLocaleString();
                    
                    if (statUnique && data.stats.unique_properties !== undefined) {
                        statUnique.innerText = Number(data.stats.unique_properties).toLocaleString();
                    }
                    
                    const statDuplicates = document.getElementById('stat-duplicates');
                    if (statDuplicates && data.stats.duplicate_listings !== undefined) {
                        statDuplicates.innerText = `Identified Duplicates: ${Number(data.stats.duplicate_listings).toLocaleString()}`;
                    }

                    if (statAvg) statAvg.innerText = formatCurrency(data.stats.avg_price);
                }

                // Document Title
                if (data.app_title) document.title = data.app_title;
            }
        } catch (error) {
            console.error('Error loading metadata:', error);
            if (statusText) statusText.innerText = 'Error loading metadata';
        } finally {
            // Always fetch properties even if metadata loading had non-fatal warnings
            fetchProperties(getFilters());
        }
    };

    // Fetch Properties
    const fetchProperties = async (filters) => {
        try {
            filters.page = currentPage;
            filters.limit = itemsPerPage;

            showLoading('Searching properties...');
            const response = await fetch('/api/properties', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(filters)
            });
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            if (!response.ok) {
                throw new Error(`Server returned HTTP ${response.status}`);
            }
            const data = await response.json();
            currentProperties = data.properties;
            totalPropertiesCount = data.total_count;
            
            // Set Stats dynamically from search results
            if (data.stats) {
                const activeCount = (data.stats.active_properties !== undefined)
                    ? data.stats.active_properties
                    : (data.stats.total_properties || 0);

                if (statTotal) statTotal.innerText = Number(activeCount).toLocaleString();
                
                if (statUnique && data.stats.unique_properties !== undefined) {
                    statUnique.innerText = Number(data.stats.unique_properties).toLocaleString();
                }
                
                const statDuplicates = document.getElementById('stat-duplicates');
                if (statDuplicates && data.stats.duplicate_listings !== undefined) {
                    statDuplicates.innerText = `Identified Duplicates: ${Number(data.stats.duplicate_listings).toLocaleString()}`;
                }
            }

            // Clear selections
            selectedPropertyIds.clear();
            updateExportButtons();
            if (selectAllCheckbox) selectAllCheckbox.checked = false;

            renderGrid();
            renderTable();
            renderPagination();

            hideLoading();
            if (statusText) statusText.innerText = `Found ${totalPropertiesCount} properties`;
            updateResultsInfo();
        } catch (error) {
            console.error('Error fetching properties:', error);
            if (statusText) statusText.innerText = 'Error fetching properties';
            hideLoading();
        }
    };

    // Pagination Logic
    const perPageSelect = document.getElementById('per-page-select');
    const paginationButtons = document.getElementById('pagination-buttons');
    const paginationInfo = document.getElementById('pagination-info');

    if (perPageSelect) {
        perPageSelect.addEventListener('change', (e) => {
            itemsPerPage = e.target.value;
            currentPage = 1;
            fetchProperties(getFilters());
        });
    }

    const renderPagination = () => {
        if (!paginationButtons || !paginationInfo) return;

        paginationButtons.innerHTML = '';

        if (itemsPerPage === 'All' || itemsPerPage === 'all') {
            paginationInfo.innerText = `Showing all ${totalPropertiesCount} properties`;
            return;
        }

        const limit = parseInt(itemsPerPage);
        const totalPages = Math.ceil(totalPropertiesCount / limit);

        if (totalPropertiesCount === 0) {
            paginationInfo.innerText = `Showing 0 to 0 of 0 properties`;
            return;
        }

        const startIdx = ((currentPage - 1) * limit) + 1;
        const endIdx = Math.min(currentPage * limit, totalPropertiesCount);
        paginationInfo.innerText = `Showing ${startIdx} to ${endIdx} of ${totalPropertiesCount} properties`;

        // Prev Button
        const btnPrev = document.createElement('button');
        btnPrev.className = 'btn-page';
        btnPrev.innerText = 'Previous';
        btnPrev.disabled = currentPage === 1;
        btnPrev.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                fetchProperties(getFilters());
            }
        });
        paginationButtons.appendChild(btnPrev);

        // Page Numbers
        const maxPagesToShow = 5;
        let startPage = Math.max(1, currentPage - Math.floor(maxPagesToShow / 2));
        let endPage = Math.min(totalPages, startPage + maxPagesToShow - 1);

        if (endPage - startPage + 1 < maxPagesToShow) {
            startPage = Math.max(1, endPage - maxPagesToShow + 1);
        }

        if (startPage > 1) {
            const btnFirst = document.createElement('button');
            btnFirst.className = 'btn-page';
            btnFirst.innerText = '1';
            btnFirst.addEventListener('click', () => { currentPage = 1; fetchProperties(getFilters()); });
            paginationButtons.appendChild(btnFirst);

            if (startPage > 2) {
                const ellipsis = document.createElement('span');
                ellipsis.innerText = '...';
                ellipsis.style.padding = '6px';
                paginationButtons.appendChild(ellipsis);
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            const btn = document.createElement('button');
            btn.className = `btn-page ${i === currentPage ? 'active' : ''}`;
            btn.innerText = i;
            btn.addEventListener('click', () => {
                currentPage = i;
                fetchProperties(getFilters());
            });
            paginationButtons.appendChild(btn);
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                const ellipsis = document.createElement('span');
                ellipsis.innerText = '...';
                ellipsis.style.padding = '6px';
                paginationButtons.appendChild(ellipsis);
            }
            const btnLast = document.createElement('button');
            btnLast.className = 'btn-page';
            btnLast.innerText = totalPages;
            btnLast.addEventListener('click', () => { currentPage = totalPages; fetchProperties(getFilters()); });
            paginationButtons.appendChild(btnLast);
        }

        // Next Button
        const btnNext = document.createElement('button');
        btnNext.className = 'btn-page';
        btnNext.innerText = 'Next';
        btnNext.disabled = currentPage === totalPages;
        btnNext.addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                fetchProperties(getFilters());
            }
        });
        paginationButtons.appendChild(btnNext);
    };

    // Location Search Logic
    const locationSearch = document.getElementById('location-search');
    if (locationSearch && filterLocations) {
        locationSearch.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            const options = filterLocations.options;
            for (let i = 0; i < options.length; i++) {
                const opt = options[i];
                if (opt.text.toLowerCase().includes(query)) {
                    opt.style.display = '';
                } else {
                    opt.style.display = 'none';
                }
            }
        });
    }

    // Grid Sort Dropdown Logic
    if (gridSortContainer) {
        const gridSortSelect = document.getElementById('grid-sort');
        if (gridSortSelect) {
            gridSortSelect.addEventListener('change', (e) => {
                const parts = e.target.value.split('-');
                if (parts.length === 2) {
                    currentSortBy = parts[0];
                    currentSortDir = parts[1];
                    updateTableSortUI();
                    currentPage = 1;
                    fetchProperties(getFilters());
                }
            });
        }
    }

    // Table Column Sorting Logic
    const updateTableSortUI = () => {
        document.querySelectorAll('th.sortable').forEach(th => {
            th.classList.remove('active-asc', 'active-desc');
            if (th.dataset.sort === currentSortBy) {
                th.classList.add(currentSortDir === 'ASC' ? 'active-asc' : 'active-desc');
            }
        });
    };

    document.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const sortBy = th.dataset.sort;
            if (currentSortBy === sortBy) {
                currentSortDir = currentSortDir === 'ASC' ? 'DESC' : 'ASC';
            } else {
                currentSortBy = sortBy;
                currentSortDir = 'ASC';
                if (sortBy === 'price' || sortBy === 'living_area' || sortBy === 'land_area' || sortBy === 'bedrooms' || sortBy === 'bathrooms') {
                    currentSortDir = 'DESC'; // Default to DESC for high values first
                }
            }
            updateTableSortUI();

            // Sync grid dropdown if it matches
            const gridSortSelect = document.getElementById('grid-sort');
            if (gridSortSelect) {
                const val = `${currentSortBy}-${currentSortDir}`;
                let found = false;
                for (let i = 0; i < gridSortSelect.options.length; i++) {
                    if (gridSortSelect.options[i].value === val) {
                        gridSortSelect.selectedIndex = i;
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    gridSortSelect.selectedIndex = 0; // Default to first if custom sort not in dropdown
                }
            }

            currentPage = 1;
            fetchProperties(getFilters());
        });
    });

    updateTableSortUI(); // initial state

    // Mobile Sidebar Toggle
    const mobileFilterToggle = document.getElementById('mobile-filter-toggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const sidebarClose = document.getElementById('sidebar-close');

    const openSidebar = () => {
        if (sidebar) sidebar.classList.add('open');
        if (sidebarOverlay) sidebarOverlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    };

    const closeSidebar = () => {
        if (sidebar) sidebar.classList.remove('open');
        if (sidebarOverlay) sidebarOverlay.classList.remove('active');
        document.body.style.overflow = '';
    };

    if (mobileFilterToggle) mobileFilterToggle.addEventListener('click', openSidebar);
    if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);
    if (sidebarClose) sidebarClose.addEventListener('click', closeSidebar);

    // Close sidebar after search on mobile
    const origBtnSearchClick = btnSearch.onclick;
    btnSearch.addEventListener('click', () => {
        if (window.innerWidth <= 1100) closeSidebar();
    });

    // Live indicator on the "Scraper Logs" button: green dot while a scrape is running.
    // Reads the same activity feed as the Scraper Logs page.
    const scraperLiveDot = document.getElementById('scraper-live-dot');
    const pollScraperActivity = async () => {
        if (!scraperLiveDot) return;
        try {
            const res = await fetch('/api/scrapers/activity?limit=5');
            if (!res.ok) return;
            const data = await res.json();
            const running = (data.active_count || 0) > 0;
            scraperLiveDot.style.display = running ? 'inline-block' : 'none';
            scraperLiveDot.title = running
                ? `${data.active_count} scraper(s) running`
                : '';
        } catch (_) {
            // Non-critical: the dot just stays hidden.
        }
    };
    pollScraperActivity();
    setInterval(pollScraperActivity, 15000);

    // Duplicate Group Modal Comparison
    window.closeDuplicateModal = () => {
        const modal = document.getElementById('duplicate-modal');
        if (modal) modal.style.display = 'none';
    };

    window.openDuplicateGroupModal = async (propertyId) => {
        const modal = document.getElementById('duplicate-modal');
        const titleEl = document.getElementById('duplicate-modal-title');
        const subtitleEl = document.getElementById('duplicate-modal-subtitle');
        const bodyEl = document.getElementById('duplicate-modal-body');

        if (!modal || !bodyEl) return;
        modal.style.display = 'flex';
        bodyEl.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-secondary);"><i class="fas fa-circle-notch fa-spin" style="font-size: 28px; margin-bottom: 12px; color: var(--primary-color);"></i><p>Loading multi-agency duplicate comparison...</p></div>';

        try {
            const res = await fetch(`/api/properties/${propertyId}/group`);
            if (!res.ok) throw new Error('Failed to load duplicate group');
            const data = await res.json();
            if (!data.has_group || !data.group || !data.group.listings || data.group.listings.length === 0) {
                bodyEl.innerHTML = '<div style="text-align: center; padding: 30px; color: var(--text-secondary);">No duplicate group records found for this property.</div>';
                return;
            }

            const group = data.group;
            titleEl.textContent = `Duplicate Cluster (${group.total_agency_listings} Agencies)`;
            subtitleEl.textContent = `Group Code: ${group.group_code} • Matched on Price, Plot Area & Bedrooms`;

            let html = `
                <div style="margin-bottom: 18px; background: #e0e7ff; border-left: 4px solid #4f46e5; padding: 12px 16px; border-radius: 8px; font-size: 13px; color: #312e81; line-height: 1.5;">
                    <i class="fas fa-info-circle" style="color: #4f46e5;"></i> <strong>SARDO360 Deduplication Engine:</strong> The following <strong>${group.total_agency_listings} agency listings</strong> represent the exact same physical property based on identical pricing, plot size (${group.listings[0]?.land_area || '—'} m²), and bedrooms (${group.listings[0]?.bedrooms || '—'}).
                </div>
                <div style="display: flex; flex-direction: column; gap: 14px;">
            `;

            group.listings.forEach((item) => {
                const isRep = item.is_representative;
                const repBadge = isRep
                    ? `<span style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 2px 4px rgba(16,185,129,0.3);"><i class="fas fa-star"></i> ⭐ Primary Representative</span>`
                    : `<span style="background: #f1f5f9; color: #64748b; border: 1px solid #cbd5e1; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 600;">Alternate Agency Listing</span>`;

                const priceStr = formatPrice(item.price);
                const buildStr = (item.living_area && !isNaN(parseFloat(item.living_area))) ? `${parseFloat(item.living_area).toFixed(0)} m²` : '—';
                const plotStr = (item.land_area && !isNaN(parseFloat(item.land_area))) ? `${parseFloat(item.land_area).toFixed(0)} m²` : '—';

                html += `
                    <div style="background: white; border: 1.5px solid ${isRep ? '#6366f1' : '#e2e8f0'}; border-radius: 10px; padding: 16px 20px; box-shadow: ${isRep ? '0 4px 12px rgba(99, 102, 241, 0.12)' : '0 1px 3px rgba(0,0,0,0.04)'}; display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;">
                        <div style="flex: 1; min-width: 260px;">
                            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
                                <span style="font-weight: 700; font-size: 15px; color: var(--text-primary);"><i class="fas fa-building" style="color: #6366f1;"></i> ${item.display_source || item.source}</span>
                                ${repBadge}
                                ${statusBadge(item.property_status)}
                            </div>
                            <div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">
                                <strong>Ref:</strong> ${item.reference || 'N/A'} • <strong>Title:</strong> ${item.title || 'Property Listing'}
                            </div>
                            <div style="display: flex; gap: 16px; font-size: 12px; color: var(--text-secondary); flex-wrap: wrap;">
                                <span><i class="fas fa-bed" style="color: #6366f1;"></i> ${item.bedrooms || '-'} Beds</span>
                                <span><i class="fas fa-bath" style="color: #6366f1;"></i> ${item.bathrooms || '-'} Baths</span>
                                <span><i class="fas fa-ruler-combined" style="color: #6366f1;"></i> Build: ${buildStr}</span>
                                <span><i class="fas fa-tree" style="color: #6366f1;"></i> Plot: ${plotStr}</span>
                                <span><i class="fas fa-award" style="color: #f59e0b;"></i> Score: <strong>${Math.round(item.completeness_score || 0)}</strong></span>
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 8px;">
                            <span style="font-size: 1.25rem; font-weight: 700; color: var(--accent-color);">${priceStr}</span>
                            ${item.property_url ? `
                                <a href="${item.property_url}" target="_blank" style="background: #4f46e5; color: white; padding: 7px 14px; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 2px 4px rgba(79, 70, 229, 0.25); transition: opacity 0.2s;" onmouseover="this.style.opacity='0.9'" onmouseout="this.style.opacity='1'">
                                    <i class="fas fa-external-link-alt"></i> View on Agency Site
                                </a>
                            ` : ''}
                        </div>
                    </div>
                `;
            });

            html += '</div>';
            bodyEl.innerHTML = html;
        } catch (err) {
            bodyEl.innerHTML = `<div style="text-align: center; padding: 30px; color: #ef4444;"><i class="fas fa-exclamation-circle" style="font-size: 24px; margin-bottom: 8px;"></i><p>Error loading duplicate group: ${err.message}</p></div>`;
        }
    };

    // Close duplicate modal when clicking outside
    window.addEventListener('click', (event) => {
        const dupModal = document.getElementById('duplicate-modal');
        if (event.target === dupModal) {
            dupModal.style.display = 'none';
        }

        // Event delegation for Modal tag deletion
        const modalRemoveBtn = event.target.closest('.remove-modal-tag-btn');
        if (modalRemoveBtn) {
            event.stopPropagation();
            const propertyId = modalRemoveBtn.dataset.propertyId;
            const tag = modalRemoveBtn.dataset.tag;
            handleRemoveModalTag(propertyId, tag);
            return;
        }

        // Event delegation for Preview tag deletion
        const previewRemoveBtn = event.target.closest('.remove-preview-tag-btn');
        if (previewRemoveBtn) {
            event.stopPropagation();
            const propertyId = previewRemoveBtn.dataset.propertyId;
            const tag = previewRemoveBtn.dataset.tag;
            handleRemovePreviewTag(propertyId, tag);
            return;
        }

        // Event delegation for Global tag deletion
        const globalDeleteBtn = event.target.closest('.global-tag-delete-icon');
        if (globalDeleteBtn) {
            event.stopPropagation();
            const tagName = globalDeleteBtn.dataset.tagName;
            handleDeleteGlobalTag(event, tagName);
            return;
        }

        // Event delegation for Global tag click
        const globalTagChip = event.target.closest('.global-tag-card-chip');
        if (globalTagChip) {
            event.stopPropagation();
            const tagName = globalTagChip.dataset.tagName;
            handleGlobalTagClick(tagName);
            return;
        }
    });

    // Modal Tag Editing Functions
    window.handleAddModalTag = async (propertyId) => {
        const input = document.getElementById('modal-new-tag-input');
        if (!input) return;
        const newTag = input.value.trim();
        if (!newTag) return;

        const prop = currentProperties.find(p => String(p.id).toLowerCase() === String(propertyId).toLowerCase());
        const currentTags = (prop && Array.isArray(prop.tags)) ? [...prop.tags] : [];

        if (currentTags.some(t => t.toLowerCase() === newTag.toLowerCase())) {
            showToast('Tag already exists on this property', 'info');
            input.value = '';
            return;
        }

        currentTags.push(newTag);

        try {
            const res = await fetch(`/api/properties/${propertyId}/tags`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: currentTags })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to update tags');

            if (prop) prop.tags = data.tags;
            input.value = '';
            showToast(`Tag "${newTag}" added successfully!`, 'success');

            // Refresh tags in modal
            const tagsListEl = document.getElementById('modal-tags-list');
            if (tagsListEl) {
                tagsListEl.innerHTML = data.tags.map(t => `<span class="property-tag-chip">${esc(t)} <i class="fas fa-times remove-modal-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('');
            }

            // Refresh Quick Preview if open
            const previewCloudEl = document.getElementById(`preview-tags-cloud-${propertyId}`);
            if (previewCloudEl) {
                previewCloudEl.innerHTML = data.tags.map(t => `<span class="property-tag-chip" style="font-size: 11px; padding: 2px 8px;">${esc(t)} <i class="fas fa-times remove-preview-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('');
            }

            // Refresh cards and table in background
            renderGrid();
            renderTable();
            refreshTagsFilter();
            updateGlobalTagsDatalist();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    window.handleRemoveModalTag = async (propertyId, tagToRemove) => {
        const prop = currentProperties.find(p => String(p.id).toLowerCase() === String(propertyId).toLowerCase());
        const currentTags = (prop && Array.isArray(prop.tags))
            ? prop.tags.filter(t => t.toLowerCase() !== tagToRemove.toLowerCase())
            : [];

        try {
            const res = await fetch(`/api/properties/${propertyId}/tags`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: currentTags })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to update tags');

            if (prop) prop.tags = data.tags;
            showToast(`Tag "${tagToRemove}" removed`, 'info');

            // Refresh tags in modal
            const tagsListEl = document.getElementById('modal-tags-list');
            if (tagsListEl) {
                tagsListEl.innerHTML = data.tags.length > 0
                    ? data.tags.map(t => `<span class="property-tag-chip">${esc(t)} <i class="fas fa-times remove-modal-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('')
                    : '<span style="color: #94a3b8; font-size: 12px; font-style: italic;">No tags assigned yet</span>';
            }

            // Refresh Quick Preview if open
            const previewCloudEl = document.getElementById(`preview-tags-cloud-${propertyId}`);
            if (previewCloudEl) {
                previewCloudEl.innerHTML = data.tags.length > 0
                    ? data.tags.map(t => `<span class="property-tag-chip" style="font-size: 11px; padding: 2px 8px;">${esc(t)} <i class="fas fa-times remove-preview-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('')
                    : '<span style="color: #94a3b8; font-size: 11px; font-style: italic;">No tags assigned</span>';
            }

            renderGrid();
            renderTable();
            refreshTagsFilter();
            updateGlobalTagsDatalist();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    const refreshTagsFilter = async () => {
        try {
            const res = await fetch('/api/tags');
            if (!res.ok) return;
            const data = await res.json();
            if (filterTags && Array.isArray(data.tags)) {
                const currentSelected = Array.from(filterTags.selectedOptions).map(o => o.value);
                filterTags.innerHTML = '';
                data.tags.forEach(t => {
                    if (t && t.tag) {
                        const opt = document.createElement('option');
                        opt.value = t.tag;
                        opt.textContent = `${t.tag} (${t.count})`;
                        if (currentSelected.includes(t.tag)) opt.selected = true;
                        filterTags.appendChild(opt);
                    }
                });
            }
        } catch (_) {}
    };

    // CSV Tag Upload Modal Functions
    window.openTagUploadModal = () => {
        const modal = document.getElementById('tags-modal');
        const resultsEl = document.getElementById('tags-upload-results');
        const fileInput = document.getElementById('tags-csv-file');
        const fileNameEl = document.getElementById('tags-file-name');
        
        if (fileInput) fileInput.value = '';
        if (fileNameEl) fileNameEl.innerText = 'Click or drag & drop CSV file here';
        if (resultsEl) {
            resultsEl.style.display = 'none';
            resultsEl.innerHTML = '';
        }
        if (modal) modal.style.display = 'flex';
    };

    window.closeTagUploadModal = () => {
        const modal = document.getElementById('tags-modal');
        if (modal) modal.style.display = 'none';
    };

    window.handleTagFileSelect = (event) => {
        const file = event.target.files[0];
        const fileNameEl = document.getElementById('tags-file-name');
        if (file && fileNameEl) {
            fileNameEl.innerHTML = `<strong>Selected:</strong> ${esc(file.name)} <span style="color:#64748b; font-size:12px;">(${(file.size / 1024).toFixed(1)} KB)</span>`;
        }
    };

    window.handleTagFileDrop = (event) => {
        event.preventDefault();
        const dropzone = document.getElementById('tags-dropzone');
        if (dropzone) {
            dropzone.style.borderColor = '#cbd5e1';
            dropzone.style.background = '#fdfdfd';
        }
        if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
            const fileInput = document.getElementById('tags-csv-file');
            if (fileInput) {
                fileInput.files = event.dataTransfer.files;
                window.handleTagFileSelect({ target: fileInput });
            }
        }
    };

    window.submitTagUploadForm = async (event) => {
        event.preventDefault();
        const fileInput = document.getElementById('tags-csv-file');
        const resultsEl = document.getElementById('tags-upload-results');
        const submitBtn = document.getElementById('btn-submit-tags-upload');

        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            showToast('Please select a CSV file first', 'error');
            return;
        }

        const modeRadios = document.getElementsByName('tag_upload_mode');
        let selectedMode = 'replace';
        for (const r of modeRadios) {
            if (r.checked) {
                selectedMode = r.value;
                break;
            }
        }

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('mode', selectedMode);

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Uploading & Tagging...';

        try {
            const res = await fetch('/api/properties/tags/upload-csv', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (!data.success) {
                throw new Error(data.error || 'Failed to upload tags');
            }

            let reportHtml = `
                <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-bottom: 12px; color: #166534;">
                    <div style="font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                        <i class="fas fa-check-circle" style="color: #16a34a; font-size: 16px;"></i> Tags Applied Successfully!
                    </div>
                    <div style="font-size: 13px;">
                        • Total CSV rows processed: <strong>${data.total_rows}</strong><br>
                        • Properties matched and tagged: <strong>${data.matched_count}</strong><br>
                        • Total distinct tags in CSV: <strong>${data.distinct_tags_count}</strong>
                    </div>
                </div>
            `;

            if (data.unmatched_rows && data.unmatched_rows.length > 0) {
                reportHtml += `
                    <div style="background: #fffbeb; border: 1px solid #fef3c7; border-radius: 8px; padding: 12px; color: #92400e; font-size: 12px; max-height: 140px; overflow-y: auto;">
                        <div style="font-weight: 700; margin-bottom: 4px;"><i class="fas fa-exclamation-triangle"></i> Unmatched Rows (${data.unmatched_rows.length}):</div>
                        ${data.unmatched_rows.map(u => `<div>Row ${u.row}: <code>${esc(u.identifier)}</code> — ${esc(u.reason)}</div>`).join('')}
                    </div>
                `;
            }

            if (resultsEl) {
                resultsEl.innerHTML = reportHtml;
                resultsEl.style.display = 'block';
            }

            showToast(`Successfully updated tags for ${data.matched_count} properties!`, 'success');

            // Refresh data and tag filters
            refreshTagsFilter();
            fetchProperties(getFilters());
        } catch (err) {
            console.error('Upload Error:', err);
            if (resultsEl) {
                resultsEl.innerHTML = `
                    <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 14px; color: #991b1b; font-size: 13px;">
                        <i class="fas fa-times-circle" style="color: #dc2626;"></i> <strong>Upload Failed:</strong> ${esc(err.message)}
                    </div>
                `;
                resultsEl.style.display = 'block';
            }
            showToast(`Error: ${err.message}`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-upload"></i> Upload & Apply Tags';
        }
    };

    const tagsUploadFormEl = document.getElementById('tags-upload-form');
    if (tagsUploadFormEl) {
        tagsUploadFormEl.addEventListener('submit', window.submitTagUploadForm);
    }

    // Close tag modal when clicking outside
    window.addEventListener('click', (event) => {
        const tModal = document.getElementById('tags-modal');
        if (event.target === tModal) {
            tModal.style.display = 'none';
        }
    });

    // Quick Preview Tag Editor Handlers
    window.handleAddPreviewTag = async (propertyId) => {
        const input = document.getElementById(`preview-new-tag-input-${propertyId}`);
        if (!input) return;
        const newTag = input.value.trim();
        if (!newTag) return;

        const prop = currentProperties.find(p => String(p.id) === String(propertyId));
        const currentTags = (prop && Array.isArray(prop.tags)) ? [...prop.tags] : [];

        if (currentTags.some(t => t.toLowerCase() === newTag.toLowerCase())) {
            showToast('Tag already exists on this property', 'info');
            input.value = '';
            return;
        }

        currentTags.push(newTag);

        try {
            const res = await fetch(`/api/properties/${propertyId}/tags`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: currentTags })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to update tags');

            if (prop) prop.tags = data.tags;
            input.value = '';
            showToast(`Tag "${newTag}" added!`, 'success');

            // Refresh preview chips
            const cloudEl = document.getElementById(`preview-tags-cloud-${propertyId}`);
            if (cloudEl) {
                cloudEl.innerHTML = data.tags.map(t => `<span class="property-tag-chip" style="font-size: 11px; padding: 2px 8px;">${esc(t)} <i class="fas fa-times remove-preview-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('');
            }

            renderGrid();
            renderTable();
            refreshTagsFilter();
            updateGlobalTagsDatalist();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    window.handleRemovePreviewTag = async (propertyId, tagToRemove) => {
        const prop = currentProperties.find(p => String(p.id) === String(propertyId));
        const currentTags = (prop && Array.isArray(prop.tags))
            ? prop.tags.filter(t => t.toLowerCase() !== tagToRemove.toLowerCase())
            : [];

        try {
            const res = await fetch(`/api/properties/${propertyId}/tags`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: currentTags })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to update tags');

            if (prop) prop.tags = data.tags;
            showToast(`Tag "${tagToRemove}" removed`, 'info');

            // Refresh preview chips
            const cloudEl = document.getElementById(`preview-tags-cloud-${propertyId}`);
            if (cloudEl) {
                cloudEl.innerHTML = data.tags.length > 0
                    ? data.tags.map(t => `<span class="property-tag-chip" style="font-size: 11px; padding: 2px 8px;">${esc(t)} <i class="fas fa-times remove-preview-tag-btn" data-property-id="${propertyId}" data-tag="${esc(t)}" title="Remove tag"></i></span>`).join('')
                    : '<span style="color: #94a3b8; font-size: 11px; font-style: italic;">No tags assigned</span>';
            }

            renderGrid();
            renderTable();
            refreshTagsFilter();
            updateGlobalTagsDatalist();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    // Global Tags Library Management
    let globalTagsLibraryCache = [];

    const updateGlobalTagsDatalist = async () => {
        try {
            let datalist = document.getElementById('global-tags-datalist');
            if (!datalist) {
                datalist = document.createElement('datalist');
                datalist.id = 'global-tags-datalist';
                document.body.appendChild(datalist);
            }
            if (globalTagsLibraryCache.length === 0) {
                const res = await fetch('/api/tags/global');
                if (res.ok) {
                    const data = await res.json();
                    globalTagsLibraryCache = data.global_tags || [];
                }
            }
            datalist.innerHTML = globalTagsLibraryCache.map(t => `<option value="${esc(t.name)}">${esc(t.category || '')}</option>`).join('');
        } catch (_) {}
    };

    window.switchTagsModalTab = (tabName) => {
        const tabGlobal = document.getElementById('tags-tab-global');
        const tabCsv = document.getElementById('tags-tab-csv');
        const btnGlobal = document.getElementById('tab-btn-global-tags');
        const btnCsv = document.getElementById('tab-btn-csv-upload');

        if (tabName === 'global') {
            if (tabGlobal) tabGlobal.style.display = 'block';
            if (tabCsv) tabCsv.style.display = 'none';
            if (btnGlobal) {
                btnGlobal.style.color = '#4f46e5';
                btnGlobal.style.borderBottom = '3px solid #4f46e5';
                btnGlobal.style.fontWeight = '700';
            }
            if (btnCsv) {
                btnCsv.style.color = '#64748b';
                btnCsv.style.borderBottom = '3px solid transparent';
                btnCsv.style.fontWeight = '600';
            }
            window.loadGlobalTagsLibrary();
        } else {
            if (tabGlobal) tabGlobal.style.display = 'none';
            if (tabCsv) tabCsv.style.display = 'block';
            if (btnCsv) {
                btnCsv.style.color = '#4f46e5';
                btnCsv.style.borderBottom = '3px solid #4f46e5';
                btnCsv.style.fontWeight = '700';
            }
            if (btnGlobal) {
                btnGlobal.style.color = '#64748b';
                btnGlobal.style.borderBottom = '3px solid transparent';
                btnGlobal.style.fontWeight = '600';
            }
        }
    };

    window.loadGlobalTagsLibrary = async () => {
        const listEl = document.getElementById('global-tags-categories-list');
        const selectionBanner = document.getElementById('global-tags-selection-banner');
        const selectedCountEl = document.getElementById('global-tags-selected-count');

        if (selectedPropertyIds.size > 0) {
            if (selectionBanner) selectionBanner.style.display = 'flex';
            if (selectedCountEl) selectedCountEl.innerText = selectedPropertyIds.size;
        } else {
            if (selectionBanner) selectionBanner.style.display = 'none';
        }

        try {
            const res = await fetch('/api/tags/global');
            if (!res.ok) throw new Error('Failed to load global tags');
            const data = await res.json();
            globalTagsLibraryCache = data.global_tags || [];
            window.renderGlobalTagsLibrary(globalTagsLibraryCache);
            updateGlobalTagsDatalist();
        } catch (err) {
            if (listEl) listEl.innerHTML = `<div style="text-align: center; color: #ef4444; padding: 20px;">Error loading global tags: ${esc(err.message)}</div>`;
        }
    };

    window.renderGlobalTagsLibrary = (tagsList) => {
        const listEl = document.getElementById('global-tags-categories-list');
        if (!listEl) return;

        if (!tagsList || tagsList.length === 0) {
            listEl.innerHTML = '<div style="text-align: center; color: #94a3b8; padding: 30px;">No tags found in library.</div>';
            return;
        }

        // Group by category
        const groups = {};
        tagsList.forEach(t => {
            const cat = t.category || 'General';
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(t);
        });

        const hasSelection = selectedPropertyIds.size > 0;

        let html = '';
        for (const [catName, tags] of Object.entries(groups)) {
            html += `
                <div class="global-category-block">
                    <div class="global-category-title">
                        <span><i class="fas fa-folder-open" style="color: #6366f1; margin-right: 6px;"></i> ${esc(catName)}</span>
                        <span style="font-size: 11px; color: #94a3b8;">${tags.length} tags</span>
                    </div>
                    <div class="tags-cloud-container">
                        ${tags.map(t => `
                            <div class="global-tag-card-chip" data-tag-name="${esc(t.name)}" title="${esc(t.description || t.name)} ${hasSelection ? '(Click to toggle on ' + selectedPropertyIds.size + ' selected properties)' : '(Click to filter)'}">
                                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${t.color || '#4f46e5'};"></span>
                                <span>${esc(t.name)}</span>
                                <span class="tag-count-badge">${t.usage_count || 0}</span>
                                <span class="global-tag-delete-icon" data-tag-name="${esc(t.name)}" title="Delete '${esc(t.name)}' from library"><i class="fas fa-times"></i></span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        listEl.innerHTML = html;
    };

    window.handleDeleteGlobalTag = async (event, tagName) => {
        if (event) event.stopPropagation();
        
        const confirmed = await sardoConfirm({
            title: 'Delete Global Tag',
            body: `Are you sure you want to remove the tag "<strong>${esc(tagName)}</strong>" from the Global Tags Library?`,
            confirmText: 'Delete Tag',
            type: 'danger'
        });

        if (!confirmed) return;

        try {
            const res = await fetch(`/api/tags/global/${encodeURIComponent(tagName)}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to delete tag');

            showToast(`Tag "${tagName}" deleted from library`, 'info');
            window.loadGlobalTagsLibrary();
            refreshTagsFilter();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    window.filterGlobalTagsLibrary = (query) => {
        const q = (query || '').toLowerCase().trim();
        if (!q) {
            window.renderGlobalTagsLibrary(globalTagsLibraryCache);
            return;
        }
        const filtered = globalTagsLibraryCache.filter(t => 
            t.name.toLowerCase().includes(q) || (t.category && t.category.toLowerCase().includes(q))
        );
        window.renderGlobalTagsLibrary(filtered);
    };

    window.toggleCreateGlobalTagForm = (forceState) => {
        const panel = document.getElementById('create-global-tag-panel');
        const nameInput = document.getElementById('new-global-tag-name');
        if (!panel) return;
        
        if (typeof forceState === 'boolean') {
            panel.style.display = forceState ? 'block' : 'none';
        } else {
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }

        if (panel.style.display === 'block') {
            if (nameInput) {
                nameInput.value = '';
                nameInput.focus();
            }
        } else {
            if (nameInput) nameInput.value = '';
        }
    };

    window.submitCreateGlobalTag = async () => {
        const nameInput = document.getElementById('new-global-tag-name');
        const catSelect = document.getElementById('new-global-tag-category');
        const colorInput = document.getElementById('new-global-tag-color');

        const name = nameInput ? nameInput.value.trim() : '';
        const category = catSelect ? catSelect.value : 'General';
        const color = colorInput ? colorInput.value : '#4f46e5';

        if (!name) {
            showToast('Tag name is required', 'error');
            return;
        }

        try {
            const res = await fetch('/api/tags/global', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, category, color })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error || 'Failed to create global tag');

            showToast(`Global Tag "${name}" created!`, 'success');
            if (nameInput) nameInput.value = '';
            window.toggleCreateGlobalTagForm();
            window.loadGlobalTagsLibrary();
            refreshTagsFilter();
        } catch (err) {
            showToast(`Error: ${err.message}`, 'error');
        }
    };

    window.handleGlobalTagClick = async (tagName) => {
        if (selectedPropertyIds.size > 0) {
            const propIds = Array.from(selectedPropertyIds);
            try {
                showLoading(`Applying tag "${tagName}" to ${propIds.length} properties...`);
                const res = await fetch('/api/properties/bulk-tags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ property_ids: propIds, tag: tagName, action: 'add' })
                });
                const data = await res.json();
                hideLoading();
                if (!data.success) throw new Error(data.error || 'Failed to bulk assign tag');

                showToast(`Tag "${tagName}" assigned to ${data.updated_count} properties!`, 'success');
                window.loadGlobalTagsLibrary();
                refreshTagsFilter();
                fetchProperties(getFilters());
            } catch (err) {
                hideLoading();
                showToast(`Error: ${err.message}`, 'error');
            }
        } else {
            // Filter by this tag
            if (filterTags) {
                let found = false;
                Array.from(filterTags.options).forEach(opt => {
                    if (opt.value.toLowerCase() === tagName.toLowerCase()) {
                        opt.selected = true;
                        found = true;
                    }
                });
                if (!found) {
                    const opt = document.createElement('option');
                    opt.value = tagName;
                    opt.textContent = `${tagName}`;
                    opt.selected = true;
                    filterTags.appendChild(opt);
                }
                closeTagUploadModal();
                btnSearch.click();
            }
        }
    };

    // Update openTagUploadModal to initialize Global Tags Library
    const originalOpenTagUploadModal = window.openTagUploadModal;
    window.openTagUploadModal = () => {
        originalOpenTagUploadModal();
        window.switchTagsModalTab('global');
    };

    // Initialize Global Tags datalist on startup
    updateGlobalTagsDatalist();

    // Initialize
    loadMetadata();
});
