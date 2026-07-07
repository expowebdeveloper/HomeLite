document.addEventListener('DOMContentLoaded', () => {
    // State
    let currentProperties = [];
    let selectedPropertyIds = new Set();
    let currentViewMode = 'table'; // 'grid' or 'table'
    let currentPage = 1;
    let itemsPerPage = 10;
    let totalPropertiesCount = 0;
    let currentSortBy = 'created_at';
    let currentSortDir = 'DESC';
    let refQuery = ''; // Client-side SARDO Ref / Reference filter over loaded results

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
    const statusText = document.getElementById('status-text');
    const loadingOverlay = document.getElementById('loading-overlay');

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

    // Client-side SARDO Ref / Reference filter over the currently loaded results.
    // Matches against the SARDO reference, the displayed reference, the raw
    // reference and the title (Waratah listings show the title as the reference).
    const getVisibleProperties = () => {
        if (!refQuery) return currentProperties;
        const q = refQuery.toLowerCase();
        return currentProperties.filter(p =>
            (p.sardo_reference || '').toLowerCase().includes(q) ||
            (p.display_reference || '').toLowerCase().includes(q) ||
            (p.reference || '').toLowerCase().includes(q) ||
            (p.title || '').toLowerCase().includes(q)
        );
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

            // Image handling
            const imgHtml = prop.image_url
                ? `<img src="${prop.image_url}" alt="Property" onerror="this.src=''; this.onerror=null; this.parentElement.innerHTML='<div class=\\'no-image\\'><i class=\\'fas fa-image-slash\\'></i></div>';">`
                : `<div class="no-image"><i class="fas fa-image"></i></div>`;

            card.innerHTML = `
                <div class="card-image-container">
                    ${imgHtml}
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
                            <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-secondary);">Ref: ${prop.sardo_reference || 'N/A'}</span>
                        </div>
                        <button class="btn-view-details" style="width: 100%;">View Details</button>
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
            row.innerHTML = `<td colspan="11" style="text-align: center; padding: 30px;">No properties found matching your criteria.</td>`;
            tableBody.appendChild(row);
            return;
        }

        visibleProperties.forEach((prop, index) => {
            const row = document.createElement('tr');
            if (selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id)) {
                row.classList.add('selected-row');
            }

            // Format values
            const price = formatPrice(prop.property_price);
            const livingArea = prop.living_area ? parseFloat(prop.living_area).toFixed(0) : '—';
            const landArea = prop.land_area ? parseFloat(prop.land_area).toFixed(0) : '—';

            row.innerHTML = `
                <td onclick="event.stopPropagation();">
                    <input type="checkbox" class="row-checkbox" value="${prop.id}" ${selectedPropertyIds.has(prop.id.toString()) || selectedPropertyIds.has(prop.id) ? 'checked' : ''}>
                </td>
                <td style="font-weight: 600; color: var(--primary-color);">${price}</td>
                <td>${prop.location || 'N/A'}</td>
                <td>${prop.property_type || 'N/A'}</td>
                <td>${prop.num_beds || '-'}</td>
                <td>${prop.num_baths || '-'}</td>
                <td>${livingArea}</td>
                <td>${landArea}</td>
                <td><span class="source-badge">${prop.display_source || 'N/A'}</span></td>
                <td>${prop.sardo_reference || 'N/A'}</td>
                <td>${prop.property_url ? `<a href="${prop.property_url}" target="_blank" class="ref-link" onclick="event.stopPropagation();">${prop.display_reference || 'Link'}</a>` : (prop.display_reference || 'N/A')}</td>
            `;

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
                <p><strong>SARDO Ref:</strong> ${prop.sardo_reference || 'N/A'}</p>
            </div>
        `;
    };

    // Show Modal Details
    const showModal = (prop) => {
        const price = formatPrice(prop.property_price);
        const imgHtml = prop.image_url
            ? `<img src="${prop.image_url}" class="modal-main-img" alt="Property" onerror="this.src=''; this.onerror=null; this.parentElement.innerHTML='<div class=\\'no-image-placeholder\\'><i class=\\'fas fa-image-slash\\'></i></div>';">`
            : `<div class="no-image-placeholder"><i class="fas fa-image"></i></div>`;

        const referenceHtml = prop.property_url
            ? `<a href="${prop.property_url}" target="_blank" class="preview-link"><i class="fas fa-external-link-alt"></i> View Original Listing</a>`
            : ``;

        modalBody.innerHTML = `
            <div class="modal-grid">
                <div class="modal-image-col">
                    ${imgHtml}
                    <div class="modal-actions">
                        ${referenceHtml}
                    </div>
                </div>
                <div class="modal-details-col">
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
                        <p><strong>SARDO Ref:</strong> ${prop.sardo_reference || 'N/A'}</p>
                        <p><strong>Original Ref:</strong> ${prop.display_reference || 'N/A'}</p>
                    </div>
                </div>
            </div>
        `;
        propertyModal.style.display = 'flex';
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
        refQuery = '';

        fetchProperties({});
    });

    // Client-side SARDO Ref / Reference filter (operates on loaded results)
    const updateResultsInfo = () => {
        if (!resultsCount) return;
        if (refQuery) {
            resultsCount.innerText = `${getVisibleProperties().length} of ${totalPropertiesCount} shown`;
        } else {
            resultsCount.innerText = `${totalPropertiesCount} Properties Found`;
        }
    };

    if (filterRef) {
        filterRef.addEventListener('input', (e) => {
            refQuery = e.target.value.trim();
            renderGrid();
            renderTable();
            updateResultsInfo();
        });
    }

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

            // Set Stats
            statTotal.innerText = data.stats.total_properties.toLocaleString();
            statAvg.innerText = formatCurrency(data.stats.avg_price);

            // Document Title
            document.title = data.app_title || 'SARDO360';

            // Initial Property Load
            fetchProperties({});
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

    // Initialize
    loadMetadata();
});
