document.addEventListener('DOMContentLoaded', () => {
    // State
    let currentProperties = [];
    let selectedPropertyIds = new Set();
    let currentViewMode = 'table'; // 'grid' or 'table'
    let currentPage = 1;
    let itemsPerPage = 10;
    let totalPropertiesCount = 0;
    // Default view: most expensive properties first (client request).
    // The backend pushes P.O.A. listings (price NULL or <= 0) to the bottom for
    // either direction, so "High to Low" starts at the top of the market.
    let currentSortBy = 'price';
    let currentSortDir = 'DESC';


    // DOM Elements
    const statTotal = document.getElementById('stat-total');
    const statAvg = document.getElementById('stat-avg');
    const filterLocations = document.getElementById('filter-locations');
    const filterType = document.getElementById('filter-type');
    const resultsCount = document.getElementById('results-count');
    const selectAllCheckbox = document.getElementById('select-all');
    const btnSearch = document.getElementById('btn-search');
    const btnClear = document.getElementById('btn-clear');
    const btnExportPdf = document.getElementById('btn-export-pdf');
    const btnExportExcel = document.getElementById('btn-export-excel');
    const filterRef = document.getElementById('filter-ref');
    const filterStatuses = document.getElementById('filter-statuses');
    const filterSources = document.getElementById('filter-sources');
    const filterHideDelisted = document.getElementById('filter-hide-delisted');


    // Property status badge. "Under Offer" -> class "status-under-offer" (see style.css)
    const statusBadge = (status) => {
        const value = status || 'Unknown';
        const cls = 'status-badge status-' + value.toLowerCase().replace(/\s+/g, '-');
        return `<span class="${cls}">${value}</span>`;
    };

    // Sold / Delisted listings are no longer live stock
    const isInactiveStatus = (status) => status === 'Sold' || status === 'Delisted';
    const statusText = document.getElementById('status-text');
    const loadingOverlay = document.getElementById('loading-overlay');

    // Escape text destined for an HTML attribute (e.g. the Location title tooltip),
    // so a quote or angle bracket in the data can't break out of the attribute.
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // Utility: Format Currency
    const formatCurrency = (value) => {
        if (!value) return 'N/A';
        return new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
    };

    // Utility: Format a property price for display.
    // Non-positive or missing prices (-1 sentinel, 0, null/undefined/empty)
    // mean the price is not published, so we show "P.O.A." (Price on Application).
    const formatPrice = (value) => {
        if (value === null || value === undefined || value === '' || Number(value) <= 0) {
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
                    <div class="checkbox-container" onclick="event.stopPropagation();">
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
                    <div class="card-footer" style="flex-direction: column; align-items: stretch; gap: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span class="card-source">${prop.display_source || 'Unknown'}</span>
                            ${statusBadge(prop.property_status)}
                        </div>
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

            // Card click to show modal
            const viewBtn = card.querySelector('.btn-view-details');
            viewBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                showModal(prop);
            });

            card.addEventListener('click', () => {
                // Clicking the card opens the details modal
                showModal(prop);
            });

            // Checkbox logic
            const checkbox = card.querySelector('.card-checkbox');
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
        const visibleProperties = getVisibleProperties();
        if (visibleProperties.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = `<td colspan="12" style="text-align: center; padding: 30px;">No properties found matching your criteria.</td>`;
            tableBody.appendChild(row);
            return;
        }

        visibleProperties.forEach((prop, index) => {
            const row = document.createElement('tr');
            if (selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id)) {
                row.classList.add('selected-row');
            }
            if (isInactiveStatus(prop.property_status)) {
                row.classList.add('row-inactive');
            }

            // Format values
            const price = formatPrice(prop.property_price);
            const livingArea = prop.living_area ? parseFloat(prop.living_area).toFixed(0) : '—';
            const landArea = prop.land_area ? parseFloat(prop.land_area).toFixed(0) : '—';
            const isOffMarket = prop.market_visibility === 'off_market' || prop.source_type === 'manual' || prop.website_source === 'Manual / Off-Market' || (prop.property_url && prop.property_url.startsWith('sardo://'));
            const offMarketTag = isOffMarket ? '<span style="background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; margin-left: 6px;"><i class="fas fa-user-secret"></i> VIP OFF-MARKET</span>' : '';

            row.innerHTML = `
                <td onclick="event.stopPropagation();">
                    <input type="checkbox" class="row-checkbox" value="${prop.id}" ${selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id) ? 'checked' : ''}>
                </td>
                <td style="font-weight: 600; color: var(--primary-color);">${price}</td>
                <td title="${esc(prop.location || 'N/A')}">${prop.location || 'N/A'} ${offMarketTag}</td>
                <td>${prop.property_type || 'N/A'}</td>
                <td>${prop.num_beds || '-'}</td>
                <td>${prop.num_baths || '-'}</td>
                <td>${livingArea}</td>
                <td>${landArea}</td>
                <td><span class="source-badge">${prop.display_source || 'N/A'}</span></td>
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
            <p><strong>Construction / Renovation:</strong> ${prop.construction_year || 'N/A'} / ${prop.renovation_year || 'N/A'}</p>
            <p><strong>Energy Rating:</strong> ${prop.energy_rating || 'N/A'}</p>
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
                        ${extraManualFields}
                    </div>
                </div>
            </div>
        `;
        propertyModal.style.display = 'flex';
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

        // Agent / source (multi-select)
        const selectedSources = filterSources
            ? Array.from(filterSources.selectedOptions).map(opt => opt.value)
            : [];
        if (selectedSources.length > 0) filters.sources = selectedSources;

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

        filters.sort_by = currentSortBy;
        filters.sort_dir = currentSortDir;

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

    // Load Metadata on Startup
    const loadMetadata = async () => {
        try {
            showLoading('Loading configuration...');
            const response = await fetch('/api/metadata');
            const data = await response.json();

            // Populate Locations
            data.locations.forEach(loc => {
                const option = document.createElement('option');
                option.value = loc;
                option.textContent = loc;
                filterLocations.appendChild(option);
            });

            // Populate Types
            data.property_types.forEach(type => {
                const option = document.createElement('option');
                option.value = type;
                option.textContent = type;
                filterType.appendChild(option);
            });

            // Populate Statuses (canonical vocabulary from the server)
            if (filterStatuses && Array.isArray(data.statuses)) {
                data.statuses.forEach(status => {
                    const option = document.createElement('option');
                    option.value = status;
                    option.textContent = status;
                    filterStatuses.appendChild(option);
                });
            }

            // Populate Agents / Sources (raw value for filtering, friendly label for display)
            if (filterSources && Array.isArray(data.sources)) {
                data.sources.forEach(src => {
                    const option = document.createElement('option');
                    option.value = src.value;
                    option.textContent = src.label;
                    filterSources.appendChild(option);
                });
            }

            // Set Stats — headline count is live stock, not sold/delisted
            const headlineTotal = (data.stats.active_properties !== undefined)
                ? data.stats.active_properties
                : data.stats.total_properties;
            statTotal.innerText = headlineTotal.toLocaleString();
            statAvg.innerText = formatCurrency(data.stats.avg_price);

            // Document Title
            document.title = data.app_title || 'SARDO360';

            // Initial Property Load (honours the default "hide delisted" filter)
            fetchProperties(getFilters());
        } catch (error) {
            console.error('Error loading metadata:', error);
            if (statusText) statusText.innerText = 'Error loading metadata';
            hideLoading();
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
            const data = await response.json();
            currentProperties = data.properties;
            totalPropertiesCount = data.total_count;

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

    // Initialize
    loadMetadata();
});
