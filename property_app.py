import tkinter as tk
from tkinter import ttk, messagebox
import threading
import logging
from typing import List, Dict
import os
from datetime import datetime
import pandas as pd
from tkinter import filedialog
from openpyxl.styles import Font

from config import Config
from database import DatabaseManager
from s3_manager import S3Manager
from pdf_generator import PDFGenerator

class PropertyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.config = Config()
        self.db_manager = DatabaseManager()
        self.s3_manager = S3Manager()
        self.pdf_generator = PDFGenerator()
        
        # Data storage
        self.current_properties = []
        self.property_images = {}  # Cache for images
        self.current_photo_image = None  # Keep reference to current image
        self.current_property_url = None  # Store current property URL for hyperlink
        self.locations = []  # Dynamic locations from database
        self.property_types = []  # Dynamic property types from database
        self.selected_properties = set()  # Set to store selected property IDs
        
        # SARDO reference ID counter
        self.sardo_ref_counter = 1100
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        
        self.setup_ui()
        self.load_dynamic_data()
        self.load_statistics()
        self.load_all_properties()
           
    def setup_ui(self):
        """Setup the main user interface"""
        self.root.title(self.config.APP_TITLE)
        self.root.geometry(f"{self.config.APP_WIDTH}x{self.config.APP_HEIGHT}")
        self.root.configure(bg='#f0f0f0')
        
        # Create main frames
        self.create_header_frame()
        self.create_filter_frame()
        self.create_content_frame()
        self.create_status_frame()
        
        
        # Configure grid weights
        self.root.grid_rowconfigure(2, weight=1)  # Content frame gets the weight
        self.root.grid_columnconfigure(0, weight=1)
    
    def create_header_frame(self):
        """Create the header frame with header image, title and statistics"""
        header_frame = tk.Frame(self.root, bg='#2c3e50', height=100)
        header_frame.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        header_frame.grid_propagate(False)
        
        # Load and display header image
        self.header_image_label = tk.Label(
            header_frame,
            text="Loading header image...",
            bg='#2c3e50',
            fg='white'
        )
        self.header_image_label.pack(pady=(10, 5))
        
        # Load header image
        self.load_header_image()
        
        # Statistics frame
        stats_frame = tk.Frame(header_frame, bg='#2c3e50')
        stats_frame.pack(fill='x', padx=20, pady=(5, 10))
        
        self.total_label = tk.Label(
            stats_frame,
            text="Total Properties: Loading...",
            font=('Arial', 10),
            fg='white',
            bg='#2c3e50'
        )
        self.total_label.pack(side='left', padx=10)
        
        self.avg_price_label = tk.Label(
            stats_frame,
            text="Avg Price: Loading...",
            font=('Arial', 10),
            fg='white',
            bg='#2c3e50'
        )
        self.avg_price_label.pack(side='left', padx=10)
    
    def create_filter_frame(self):
        """Create the filter frame with all filter controls"""
        filter_frame = tk.LabelFrame(self.root, text="🔍 Property Search Filters", font=('Arial', 12, 'bold'), bg='#ecf0f1', height=200)
        filter_frame.grid(row=1, column=0, sticky='ew', padx=5, pady=5)
        filter_frame.grid_propagate(False)  # Prevent the frame from being compressed
        
        # Main filter container with left filters and right search button
        main_filter_container = tk.Frame(filter_frame, bg='#ecf0f1')
        main_filter_container.pack(fill='x', padx=10, pady=10)
        
        # Left side - Filter controls
        left_filters = tk.Frame(main_filter_container, bg='#ecf0f1')
        left_filters.pack(side='left', fill='both', expand=True)
        
        # Right side - Search button
        right_search = tk.Frame(main_filter_container, bg='#ecf0f1')
        right_search.pack(side='right', padx=(20, 0))
        
        # Search button on the right
        self.search_button = tk.Button(
            right_search,
            text="🔍 SEARCH",
            command=self.search_properties,
            bg='#3498db',
            fg='white',
            font=('Arial', 12, 'bold'),
            padx=25,
            pady=10,
            relief='raised',
            borderwidth=2
        )
        self.search_button.pack()
        
        # PDF Export section with client name and export button side by side
        pdf_frame = tk.Frame(right_search, bg='#ecf0f1')
        pdf_frame.pack(pady=(10, 0))
        
        # Client name input on the left
        client_frame = tk.Frame(pdf_frame, bg='#ecf0f1')
        client_frame.pack(side='left', padx=(0, 10))
        
        tk.Label(client_frame, text="Client Name:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack()
        self.client_name_var = tk.StringVar(value="Smith")  # Default value
        self.client_name_entry = tk.Entry(
            client_frame, 
            textvariable=self.client_name_var, 
            width=15,
            font=('Arial', 10),
            justify='center'
        )
        self.client_name_entry.pack(pady=(5, 0))
        
        # PDF Export button on the right
        self.pdf_export_button = tk.Button(
            pdf_frame,
            text="📄 EXPORT PDF",
            command=self.export_pdf,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 12, 'bold'),
            padx=25,
            pady=10,
            relief='raised',
            borderwidth=2,
            state='disabled'  # Initially disabled
        )
        self.pdf_export_button.pack(side='right')
        
        # Excel Export button on the right
        self.excel_export_button = tk.Button(
            pdf_frame,
            text="📊 EXPORT EXCEL",
            command=self.export_excel,
            bg='#27ae60',
            fg='white',
            font=('Arial', 12, 'bold'),
            padx=25,
            pady=10,
            relief='raised',
            borderwidth=2,
            state='disabled'  # Initially disabled
        )
        self.excel_export_button.pack(side='right', padx=(10, 0))
        
        # Price range frame
        price_frame = tk.Frame(left_filters, bg='#ecf0f1')
        price_frame.pack(fill='x', pady=5)
        
        tk.Label(price_frame, text="Price Range:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side='left')
        
        tk.Label(price_frame, text="Min:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.min_price_var = tk.StringVar()
        self.min_price_entry = tk.Entry(price_frame, textvariable=self.min_price_var, width=10)
        self.min_price_entry.pack(side='left', padx=5)
        
        tk.Label(price_frame, text="Max:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.max_price_var = tk.StringVar()
        self.max_price_entry = tk.Entry(price_frame, textvariable=self.max_price_var, width=10)
        self.max_price_entry.pack(side='left', padx=5)
        
        # Location frame
        location_frame = tk.Frame(left_filters, bg='#ecf0f1')
        location_frame.pack(fill='x', pady=5)
        
        tk.Label(location_frame, text="Location:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side='left')
        
        # Create a frame for the listbox and scrollbar
        location_list_frame = tk.Frame(location_frame, bg='#ecf0f1')
        location_list_frame.pack(side='left', padx=(10, 0))
        
        # Create listbox for multiple location selection
        self.location_listbox = tk.Listbox(
            location_list_frame,
            selectmode=tk.MULTIPLE,
            height=4,
            width=30,
            font=('Arial', 9)
        )
        self.location_listbox.pack(side='left')
        
        # Add scrollbar for the listbox
        location_scrollbar = tk.Scrollbar(location_list_frame, orient='vertical')
        location_scrollbar.pack(side='right', fill='y')
        
        # Configure the listbox and scrollbar
        self.location_listbox.config(yscrollcommand=location_scrollbar.set)
        location_scrollbar.config(command=self.location_listbox.yview)
        
        # Property type frame
        type_frame = tk.Frame(left_filters, bg='#ecf0f1')
        type_frame.pack(fill='x', pady=5)
        
        tk.Label(type_frame, text="Property Type:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side='left')
        self.property_type_var = tk.StringVar()
        self.property_type_combo = ttk.Combobox(
            type_frame, 
            textvariable=self.property_type_var,
            values=[''],  # Will be populated dynamically
            width=30,
            state='readonly'
        )
        self.property_type_combo.pack(side='left', padx=(10, 0))
        
        # Bedrooms frame
        beds_frame = tk.Frame(left_filters, bg='#ecf0f1')
        beds_frame.pack(fill='x', pady=5)
        
        tk.Label(beds_frame, text="Bedrooms:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side='left')
        
        tk.Label(beds_frame, text="Min:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.min_beds_var = tk.StringVar()
        self.min_beds_entry = tk.Entry(beds_frame, textvariable=self.min_beds_var, width=5)
        self.min_beds_entry.pack(side='left', padx=5)
        
        tk.Label(beds_frame, text="Max:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.max_beds_var = tk.StringVar()
        self.max_beds_entry = tk.Entry(beds_frame, textvariable=self.max_beds_var, width=5)
        self.max_beds_entry.pack(side='left', padx=5)
        
        # Bathrooms frame
        baths_frame = tk.Frame(left_filters, bg='#ecf0f1')
        baths_frame.pack(fill='x', pady=5)
        
        tk.Label(baths_frame, text="Bathrooms:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side='left')
        
        tk.Label(baths_frame, text="Min:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.min_baths_var = tk.StringVar()
        self.min_baths_entry = tk.Entry(baths_frame, textvariable=self.min_baths_var, width=5)
        self.min_baths_entry.pack(side='left', padx=5)
        
        tk.Label(baths_frame, text="Max:", bg='#ecf0f1').pack(side='left', padx=(10, 5))
        self.max_baths_var = tk.StringVar()
        self.max_baths_entry = tk.Entry(baths_frame, textvariable=self.max_baths_var, width=5)
        self.max_baths_entry.pack(side='left', padx=5)
        
        # Clear filters button
        self.clear_filters_button = tk.Button(
            baths_frame,
            text="🗑️ CLEAR",
            command=self.clear_filters,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 10, 'bold'),
            padx=15,
            pady=5,
            relief='raised',
            borderwidth=2
        )
        self.clear_filters_button.pack(side='right', padx=(20, 0))
        

        

    
    def create_content_frame(self):
        """Create the main content frame with property list and details"""
        content_frame = tk.Frame(self.root, bg='white')
        content_frame.grid(row=2, column=0, sticky='nsew', padx=5, pady=5)
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)
        
        # Property list frame
        list_frame = tk.LabelFrame(content_frame, text="Property List", font=('Arial', 12, 'bold'))
        list_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        
        # Create treeview for property list
        columns = ('Select', 'Price', 'Location', 'Type', 'Beds', 'Baths', 'Build (m²)', 'Plot (m²)', 'Source', 'SARDO Ref', 'Reference')
        self.property_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15)
        
        # Configure columns
        for col in columns:
            if col == 'Select':
                self.property_tree.heading(col, text='☐', command=lambda: self.toggle_all_selections())
                self.property_tree.column(col, width=50, anchor='center')
            else:
                self.property_tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c))
                if col == 'Source':
                    self.property_tree.column(col, width=150, anchor='w')  # Source gets more width and left alignment
                elif col == 'Reference':
                    self.property_tree.column(col, width=150, anchor='w')  # Reference gets medium width
                elif col == 'SARDO Ref':
                    self.property_tree.column(col, width=100, anchor='center')  # SARDO Ref gets medium width
                elif col in ['Build (m²)', 'Plot (m²)']:
                    self.property_tree.column(col, width=80, anchor='center')  # Size columns get medium width
                else:
                    self.property_tree.column(col, width=100, anchor='center')
        

        
        # Scrollbar for treeview
        tree_scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=self.property_tree.yview)
        self.property_tree.configure(yscrollcommand=tree_scrollbar.set)
        
        self.property_tree.grid(row=0, column=0, sticky='nsew')
        tree_scrollbar.grid(row=0, column=1, sticky='ns')
        
        # Bind selection event
        self.property_tree.bind('<<TreeviewSelect>>', self.on_property_select)
        
        # Bind single-click event for reference column to open URL
        self.property_tree.bind('<Button-1>', self.on_reference_click)
        
        # Bind mouse motion to show hand cursor over reference column
        self.property_tree.bind('<Motion>', self.on_treeview_motion)
        
        # Bind checkbox click event
        self.property_tree.bind('<ButtonRelease-1>', self.on_checkbox_click)
        
        # Property details frame
        details_frame = tk.LabelFrame(content_frame, text="Property Image", font=('Arial', 12, 'bold'))
        details_frame.grid(row=0, column=1, sticky='nsew', padx=(5, 0))
        details_frame.grid_rowconfigure(0, weight=1)
        details_frame.grid_columnconfigure(0, weight=1)
        
        # Property image - use fixed pixel dimensions
        self.image_label = tk.Label(
            details_frame, 
            text="No image available", 
            bg='lightgray', 
            relief='solid', 
            borderwidth=1,
            cursor='hand2'  # Show hand cursor to indicate clickable
        )
        self.image_label.grid(row=0, column=0, padx=10, pady=(10, 0), sticky='nsew')
        
        # Bind click event to image label
        self.image_label.bind('<Button-1>', self.on_image_click)
        
        # URL indicator label
        self.url_indicator = tk.Label(
            details_frame,
            text="",
            font=('Arial', 9),
            fg='#2980b9',
            bg='white'
        )
        self.url_indicator.grid(row=1, column=0, padx=10, pady=(5, 10), sticky='ew')
        
        # Set minimum size for the image area
        details_frame.grid_rowconfigure(0, minsize=300)
        details_frame.grid_columnconfigure(0, minsize=400)
    
    def create_status_frame(self):
        """Create the status frame at the bottom"""
        self.status_frame = tk.Frame(self.root, bg='#34495e', height=30)
        self.status_frame.grid(row=3, column=0, sticky='ew', padx=5, pady=5)
        self.status_frame.grid_propagate(False)
        
        self.status_label = tk.Label(
            self.status_frame,
            text="Ready",
            fg='white',
            bg='#34495e',
            font=('Arial', 9)
        )
        self.status_label.pack(side='left', padx=10, pady=5)
    
    def load_dynamic_data(self):
        """Load dynamic data from database (locations, property types, sources)"""
        def load_data():
            try:
                self.update_status("Loading dynamic data...")
                
                # Load locations and property types from database
                locations = self.db_manager.get_locations()
                property_types = self.db_manager.get_property_types()
                
                # Update UI in main thread
                self.root.after(0, lambda: self.update_dynamic_data(locations, property_types))
                
            except Exception as e:
                self.root.after(0, lambda: self.update_status(f"Error loading dynamic data: {e}"))
        
        # Run in background thread
        threading.Thread(target=load_data, daemon=True).start()
    
    def update_dynamic_data(self, locations, property_types):
        """Update the UI with dynamic data from database"""
        # Store the data
        self.locations = locations
        self.property_types = property_types
        
        # Update listbox and combobox
        self.location_listbox.delete(0, tk.END)  # Clear existing items
        for location in locations:
            self.location_listbox.insert(tk.END, location)
        self.property_type_combo['values'] = [''] + property_types
        
        self.update_status(f"Loaded {len(locations)} locations, {len(property_types)} property types")
    
    def generate_sardo_reference_id(self):
        """Generate the next SARDO reference ID"""
        ref_id = f"SARDO{self.sardo_ref_counter}"
        self.sardo_ref_counter += 1
        return ref_id
    
    def assign_sardo_references(self, properties):
        """Assign SARDO reference IDs to properties based on source and image filename"""
        # Reset counter for new assignment
        self.sardo_ref_counter = 1100
        
        # Create a list of tuples (source, image_filename, property_index) for sorting
        property_info = []
        for i, prop in enumerate(properties):
            source = prop.get('website_source', '') or ''
            image_filename = prop.get('image_filename', '') or ''
            property_info.append((source, image_filename, i))
        
        # Sort by source name, then by image filename (alphabetical)
        # Handle None values by converting them to empty strings for sorting
        property_info.sort(key=lambda x: (x[0] or '', x[1] or ''))
        
        # Assign SARDO reference IDs
        for _, _, prop_index in property_info:
            properties[prop_index]['sardo_reference'] = self.generate_sardo_reference_id()
        
        return properties

    
    def load_statistics(self):
        """Load and display database statistics"""
        def load_stats():
            try:
                self.update_status("Loading statistics...")
                stats = self.db_manager.get_statistics()
                
                # Update UI in main thread
                self.root.after(0, lambda: self.update_statistics_display(stats))
                
            except Exception as e:
                self.root.after(0, lambda: self.update_status(f"Error loading statistics: {e}"))
        
        # Run in background thread
        threading.Thread(target=load_stats, daemon=True).start()
    
    def update_statistics_display(self, stats):
        """Update the statistics display in the header"""
        total = stats.get('total_properties', 0)
        avg_price = stats.get('avg_price', 0)
        
        self.total_label.config(text=f"Total Properties: {total:,}")
        self.avg_price_label.config(text=f"Avg Price: €{avg_price:,.0f}")
        
        self.update_status("Statistics loaded successfully")
    
    def search_properties(self):
        """Search properties based on current filters"""
        # Visual feedback - change button appearance
        self.search_button.config(text="🔍 SEARCHING...", bg='#f39c12', state='disabled')
        self.root.update_idletasks()
        
        def search():
            try:
                self.update_status("Searching properties...")
                
                # Get filter values with validation
                filters = {}
                validation_errors = []
                
                # Price range validation
                if self.min_price_var.get().strip():
                    try:
                        min_price = float(self.min_price_var.get().strip())
                        if min_price < 0:
                            validation_errors.append("Minimum price cannot be negative")
                        else:
                            filters['min_price'] = min_price
                    except ValueError:
                        validation_errors.append("Invalid minimum price format")
                
                if self.max_price_var.get().strip():
                    try:
                        max_price = float(self.max_price_var.get().strip())
                        if max_price < 0:
                            validation_errors.append("Maximum price cannot be negative")
                        else:
                            filters['max_price'] = max_price
                    except ValueError:
                        validation_errors.append("Invalid maximum price format")
                
                # Check if min price > max price
                if filters.get('min_price') and filters.get('max_price'):
                    if filters['min_price'] > filters['max_price']:
                        validation_errors.append("Minimum price cannot be greater than maximum price")
                
                # Location validation
                selected_locations = [self.location_listbox.get(i) for i in self.location_listbox.curselection()]
                if selected_locations:
                    # Validate each selected location
                    for location in selected_locations:
                        if len(location.strip()) < 2:
                            validation_errors.append(f"Location '{location}' must be at least 2 characters")
                    
                    if not validation_errors:  # Only add to filters if no validation errors
                        filters['locations'] = selected_locations
                # If no locations are selected, that's fine - no location filter will be applied
                
                # Property type validation
                if self.property_type_var.get().strip():
                    property_type = self.property_type_var.get().strip()
                    if property_type not in self.property_types:
                        validation_errors.append("Invalid property type selected")
                    else:
                        filters['property_type'] = property_type
                
                # Bedrooms validation
                if self.min_beds_var.get().strip():
                    try:
                        min_beds = int(self.min_beds_var.get().strip())
                        if min_beds < 0:
                            validation_errors.append("Minimum bedrooms cannot be negative")
                        else:
                            filters['min_beds'] = min_beds
                    except ValueError:
                        validation_errors.append("Invalid minimum bedrooms format")
                
                if self.max_beds_var.get().strip():
                    try:
                        max_beds = int(self.max_beds_var.get().strip())
                        if max_beds < 0:
                            validation_errors.append("Maximum bedrooms cannot be negative")
                        else:
                            filters['max_beds'] = max_beds
                    except ValueError:
                        validation_errors.append("Invalid maximum bedrooms format")
                
                # Check if min beds > max beds
                if filters.get('min_beds') and filters.get('max_beds'):
                    if filters['min_beds'] > filters['max_beds']:
                        validation_errors.append("Minimum bedrooms cannot be greater than maximum bedrooms")
                
                # Bathrooms validation
                if self.min_baths_var.get().strip():
                    try:
                        min_baths = int(self.min_baths_var.get().strip())
                        if min_baths < 0:
                            validation_errors.append("Minimum bathrooms cannot be negative")
                        else:
                            filters['min_baths'] = min_baths
                    except ValueError:
                        validation_errors.append("Invalid minimum bathrooms format")
                
                if self.max_baths_var.get().strip():
                    try:
                        max_baths = int(self.max_baths_var.get().strip())
                        if max_baths < 0:
                            validation_errors.append("Maximum bathrooms cannot be negative")
                        else:
                            filters['max_baths'] = max_baths
                    except ValueError:
                        validation_errors.append("Invalid maximum bathrooms format")
                
                # Check if min baths > max baths
                if filters.get('min_baths') and filters.get('max_baths'):
                    if filters['min_baths'] > filters['max_baths']:
                        validation_errors.append("Minimum bathrooms cannot be greater than maximum bathrooms")
                

                
                # Show validation errors if any
                if validation_errors:
                    error_message = "Validation errors:\n" + "\n".join(f"• {error}" for error in validation_errors)
                    self.root.after(0, lambda: messagebox.showerror("Validation Error", error_message))
                    self.root.after(0, lambda: self.update_status("Search cancelled due to validation errors"))
                    return
                
                # Show active filters
                active_filters = []
                if filters.get('min_price') or filters.get('max_price'):
                    price_range = []
                    if filters.get('min_price'):
                        price_range.append(f"Min: €{filters['min_price']:,.0f}")
                    if filters.get('max_price'):
                        price_range.append(f"Max: €{filters['max_price']:,.0f}")
                    active_filters.append(f"Price: {' - '.join(price_range)}")
                
                if filters.get('locations'):
                    active_filters.append(f"Location: {', '.join(filters['locations'])}")
                
                if filters.get('property_type'):
                    active_filters.append(f"Type: {filters['property_type']}")
                
                if filters.get('min_beds') or filters.get('max_beds'):
                    beds_range = []
                    if filters.get('min_beds'):
                        beds_range.append(f"Min: {filters['min_beds']}")
                    if filters.get('max_beds'):
                        beds_range.append(f"Max: {filters['max_beds']}")
                    active_filters.append(f"Bedrooms: {' - '.join(beds_range)}")
                
                if filters.get('min_baths') or filters.get('max_baths'):
                    baths_range = []
                    if filters.get('min_baths'):
                        baths_range.append(f"Min: {filters['min_baths']}")
                    if filters.get('max_baths'):
                        baths_range.append(f"Max: {filters['max_baths']}")
                    active_filters.append(f"Bathrooms: {' - '.join(baths_range)}")
                
                filter_summary = " | ".join(active_filters) if active_filters else "No filters applied"
                self.root.after(0, lambda: self.update_status(f"Searching with filters: {filter_summary}"))
                
                # Get properties from database
                properties = self.db_manager.get_properties(filters)
                
                # Update UI in main thread
                self.root.after(0, lambda: self.display_properties(properties, filters))
                self.root.after(0, lambda: self.reset_search_button())
                
            except Exception as e:
                self.root.after(0, lambda: self.update_status(f"Error searching properties: {e}"))
                self.root.after(0, lambda: messagebox.showerror("Search Error", f"An error occurred while searching:\n{str(e)}"))
                self.root.after(0, lambda: self.reset_search_button())
        
        # Run in background thread
        threading.Thread(target=search, daemon=True).start()
    
    def reset_search_button(self):
        """Reset the search button to its original state"""
        self.search_button.config(text="🔍 SEARCH", bg='#3498db', state='normal')
    
    def load_header_image(self):
        """Load and display the header image"""
        def load_image():
            try:
                from PIL import Image, ImageTk
                
                # Try to load the header image
                image_path = "static/images/logo.png"
                if os.path.exists(image_path):
                    # Load and resize the image
                    original_image = Image.open(image_path)
                    
                    # Calculate dimensions to fit in header (max width 800px, maintain aspect ratio)
                    max_width = 500
                    max_height = 60
                    
                    # Calculate new dimensions
                    width, height = original_image.size
                    aspect_ratio = width / height
                    
                    if width > max_width:
                        new_width = max_width
                        new_height = int(max_width / aspect_ratio)
                    else:
                        new_width = width
                        new_height = height
                    
                    # Ensure height doesn't exceed max_height
                    if new_height > max_height:
                        new_height = max_height
                        new_width = int(max_height * aspect_ratio)
                    
                    # Resize image
                    resized_image = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Convert to PhotoImage
                    photo_image = ImageTk.PhotoImage(resized_image)
                    
                    # Update UI in main thread
                    self.root.after(0, lambda: self._display_header_image(photo_image))
                else:
                    # If image not found, show text title instead
                    self.root.after(0, lambda: self._display_header_text())
                    
            except Exception as e:
                logging.error(f"Error loading header image: {e}")
                # Fallback to text title
                self.root.after(0, lambda: self._display_header_text())
        
        # Run in background thread
        threading.Thread(target=load_image, daemon=True).start()
    
    def _display_header_image(self, photo_image):
        """Display the header image"""
        self.header_photo_image = photo_image  # Keep reference to prevent garbage collection
        self.header_image_label.config(image=photo_image, text="")
    
    def _display_header_text(self):
        """Display text title as fallback when image is not available"""
        self.header_image_label.config(
            text="SARDO360 - PROPERTY INSIGHT",
            font=('Arial', 20, 'bold'),
            fg='white',
            bg='#2c3e50'
        )
    
    def load_all_properties(self):
        """Load all properties when the app starts"""
        def load_all():
            try:
                self.update_status("Loading all properties...")
                
                # Get all properties from database (no filters)
                properties = self.db_manager.get_properties({})
                
                # Update UI in main thread
                self.root.after(0, lambda: self.display_properties(properties, {}))
                
            except Exception as e:
                self.root.after(0, lambda: self.update_status(f"Error loading all properties: {e}"))
                self.root.after(0, lambda: messagebox.showerror("Load Error", f"An error occurred while loading all properties:\n{str(e)}"))
        
        # Run in background thread
        threading.Thread(target=load_all, daemon=True).start()
    

    
    def display_properties(self, properties, filters=None):
        """Display properties in the treeview"""
        if filters is None:
            filters = {}
        # Clear existing items
        for item in self.property_tree.get_children():
            self.property_tree.delete(item)
        
        # Assign SARDO reference IDs to properties
        properties = self.assign_sardo_references(properties)
        
        # Store current properties
        self.current_properties = properties
        
        # Add properties to treeview with alternating row colors
        for i, prop in enumerate(properties):
            # Safely format price for display
            price = prop.get('property_price')
            if price is not None:
                price_str = f"€{price:,}"
            else:
                price_str = 'N/A'
            
            # Get reference field and title
            reference = prop.get('reference', 'N/A')
            title = prop.get('title', 'N/A')
            
            # Check if this is WaratahpropertiesScraper BEFORE processing the source name
            original_source = prop.get('website_source', 'N/A')
            is_waratah = original_source == 'WaratahpropertiesScraper'
            
            # Debug logging for Waratah properties
            if is_waratah:
                logging.info(f"Waratah property - reference: {reference}, title: {title}, type: {type(title)}")
                if title is None:
                    logging.warning(f"Waratah property has None title, using reference: {reference}")
            
            # Debug logging for area fields
            living_area = prop.get('living_area')
            land_area = prop.get('land_area')
            if living_area is not None or land_area is not None:
                logging.info(f"Property {prop.get('id')} - living_area: {living_area} (type: {type(living_area)}), land_area: {land_area} (type: {type(land_area)})")
            
            # Process source field - use mapping or remove 'Scraper' suffix
            source = original_source
            if source and source != 'N/A':
                # First check if there's a mapping for this source
                if source in Config.SOURCE_NAME_MAPPING:
                    source = Config.SOURCE_NAME_MAPPING[source]
                elif source.endswith('Scraper'):
                    source = source[:-7]  # Remove 'Scraper' suffix (7 characters)
            
            # For WaratahpropertiesScraper, use title as the reference field
            if is_waratah and title and title != 'N/A' and title is not None and title.strip():
                # Use title as the reference for Waratah properties
                display_reference = title
            else:
                display_reference = reference
            
            values = (
                '☐',  # Checkbox column
                price_str,
                prop.get('location', 'N/A'),
                prop.get('property_type', 'N/A'),
                str(prop.get('num_beds', 'N/A')) if prop.get('num_beds') is not None else 'N/A',
                str(prop.get('num_baths', 'N/A')) if prop.get('num_baths') is not None else 'N/A',
                self._format_area_value(prop.get('living_area')),  # Build size
                self._format_area_value(prop.get('land_area')),    # Plot size
                source,
                prop.get('sardo_reference', 'N/A'),  # SARDO reference
                display_reference  # Original reference
            )
            
            # Insert item with property ID tag only
            item = self.property_tree.insert('', 'end', values=values, tags=(prop.get('id'),))
            
            # Apply visual indicator for clickable reference if property has URL
            if prop.get('property_url'):
                # Modify only the Reference column to show it's clickable
                # Use a visual indicator like adding a link symbol
                clickable_reference = f"🔗 {display_reference}"
                self.property_tree.set(item, 'Reference', clickable_reference)
        
        # Apply alternating row colors after all items are inserted
        self._apply_alternating_colors()
        
        # Update status with detailed information
        if properties:
            total_value = sum(prop.get('property_price', 0) for prop in properties if prop.get('property_price'))
            avg_price = total_value / len(properties) if properties else 0
            
            # Check if this is the initial load (no filters applied)
            if not any([filters.get('min_price'), filters.get('max_price'), filters.get('location'), 
                       filters.get('property_type'), filters.get('min_beds'), filters.get('max_beds'),
                       filters.get('min_baths'), filters.get('max_baths')]):
                status_msg = f"Loaded {len(properties)} properties | Avg Price: €{avg_price:,.0f} | Click Reference to open URL"
            else:
                status_msg = f"Found {len(properties)} properties | Avg Price: €{avg_price:,.0f} | Click Reference to open URL"
            
            self.update_status(status_msg)
            
            # Show a brief notification about the results only for search results, not initial load
            if len(properties) > 0 and any([filters.get('min_price'), filters.get('max_price'), filters.get('location'), 
                                          filters.get('property_type'), filters.get('min_beds'), filters.get('max_beds'),
                                          filters.get('min_baths'), filters.get('max_baths')]):
                self.root.after(1000, lambda: self.show_results_notification(len(properties), avg_price))
        else:
            self.update_status("No properties found matching your criteria")
    

    
    def show_results_notification(self, count, avg_price):
        """Show a brief notification about search results"""
        notification = tk.Toplevel(self.root)
        notification.title("Search Results")
        notification.geometry("300x150")
        notification.configure(bg='#2ecc71')
        
        # Center the notification
        notification.transient(self.root)
        notification.grab_set()
        
        # Add notification content
        title_label = tk.Label(
            notification,
            text="Search Completed!",
            font=('Arial', 14, 'bold'),
            fg='white',
            bg='#2ecc71'
        )
        title_label.pack(pady=(20, 10))
        
        result_label = tk.Label(
            notification,
            text=f"Found {count} properties\nAverage Price: €{avg_price:,.0f}",
            font=('Arial', 11),
            fg='white',
            bg='#2ecc71'
        )
        result_label.pack(pady=10)
        
        # Auto-close after 3 seconds
        notification.after(3000, notification.destroy)
    
    def on_property_select(self, event):
        """Handle property selection in treeview"""
        selection = self.property_tree.selection()
        if not selection:
            return
        
        # Get selected property ID
        item = selection[0]
        tags = self.property_tree.item(item, 'tags')
        
        # Find the property ID tag (it should be the first tag that's not 'evenrow')
        property_id = None
        for tag in tags:
            if tag != 'evenrow':
                property_id = tag
                break
        
        if not property_id:
            logging.warning("No property ID found in tags")
            return
        
        # Find property data
        property_data = None
        for prop in self.current_properties:
            if prop.get('id') == property_id:
                property_data = prop
                break
        
        if property_data:
            try:
                # Debug: Print property data structure
                logging.info(f"Property data: {property_data}")
                # Store the property URL for hyperlink functionality
                self.current_property_url = property_data.get('property_url')
                # Load and display image only
                self.load_property_image(property_data.get('image_filename'), property_data.get('website_source'))
            except Exception as e:
                logging.error(f"Error displaying property details: {e}")
                messagebox.showerror("Error", f"Error displaying property details: {e}")
        else:
            logging.warning(f"Property data not found for ID: {property_id}")
            messagebox.showwarning("Warning", f"Property data not found for ID: {property_id}")
    

    
    def load_property_image(self, image_filename, source=None):
        """Load and display property image"""
        # Clear any existing image and set consistent dimensions
        self.image_label.config(image='', text="Loading image...")
        
        if not image_filename or image_filename == 'N/A' or image_filename == '':
            self.image_label.config(text="No image available")
            self.url_indicator.config(text="")
            return
        
        def load_image():
            try:
                logging.info(f"Loading image: {image_filename} from source: {source}")
                photo_image = self.s3_manager.download_image(image_filename, source)
                if photo_image:
                    logging.info(f"Image loaded successfully: {image_filename}")
                    # Store reference to prevent garbage collection
                    self.root.after(0, lambda: self._display_image(photo_image))
                else:
                    logging.warning(f"Image not available: {image_filename}")
                    self.root.after(0, lambda: self.image_label.config(text="Image not available"))
                    self.root.after(0, lambda: self.url_indicator.config(text=""))
            except Exception as e:
                logging.error(f"Error loading image {image_filename}: {e}")
                self.root.after(0, lambda: self.image_label.config(text="Error loading image"))
                self.root.after(0, lambda: self.url_indicator.config(text=""))
        
        # Run in background thread
        threading.Thread(target=load_image, daemon=True).start()
    
    def _display_image(self, photo_image):
        """Display image and keep reference to prevent garbage collection"""
        self.current_photo_image = photo_image  # Keep reference
        logging.info(f"Displaying image: {photo_image.width()}x{photo_image.height()}")
        
        # Configure image label with visual feedback for clickable state
        if self.current_property_url and self.current_property_url.strip():
            # URL available - show clickable styling
            self.image_label.config(
                image=photo_image, 
                relief='solid',
                borderwidth=2,
                bg='#e8f4fd'  # Light blue background to indicate clickable
            )
            # Update URL indicator
            self.url_indicator.config(text="🔗 Click image or Reference to open property URL", fg='#2980b9')
        else:
            # No URL available - normal styling
            self.image_label.config(
                image=photo_image, 
                relief='solid',
                borderwidth=1,
                bg='white'
            )
            # Clear URL indicator
        
            self.url_indicator.config(text="", fg='#2980b9')
        
        logging.info("Image configured to label")
    
    def clear_filters(self):
        """Clear all filter fields and reload all properties"""
        self.min_price_var.set('')
        self.max_price_var.set('')
        self.location_listbox.selection_clear(0, tk.END)  # Clear listbox selections
        self.property_type_var.set('')
        self.min_beds_var.set('')
        self.max_beds_var.set('')
        self.min_baths_var.set('')
        self.max_baths_var.set('')
        
        # Clear selected properties for PDF export
        self.selected_properties.clear()
        self.update_pdf_export_button()
        
        # Reload all properties (this will refill the table)
        self.load_all_properties()
        
        self.update_status("Filters cleared - showing all properties")
    
    def _format_area_value(self, value):
        """Format area values for display"""
        if value is None or value == '' or value == 'N/A':
            return 'N/A'
        
        try:
            # Convert to float and format
            float_value = float(value)
            if float_value > 0:
                return f"{float_value:,.0f}"
            else:
                return 'N/A'
        except (ValueError, TypeError):
            # If it's already a string, try to clean it
            if isinstance(value, str):
                # Remove common suffixes and clean
                cleaned = value.replace('m²', '').replace('m2', '').replace(',', '').strip()
                try:
                    float_value = float(cleaned)
                    if float_value > 0:
                        return f"{float_value:,.0f}"
                except ValueError:
                    pass
            return 'N/A'
    
    def sort_treeview(self, col):
        """Sort treeview by column with proper numeric sorting"""
        # Get all items
        items = [(self.property_tree.set(item, col), item) for item in self.property_tree.get_children('')]
        
        # Sort items based on column type
        if col in ['Price', 'Beds', 'Baths']:
            # Numeric sorting for Price, Beds, Baths
            def numeric_key(item):
                val = item[0]
                if val == 'N/A':
                    return float('inf')  # Put N/A values at the end
                try:
                    # Remove currency symbol and commas for price
                    if col == 'Price':
                        clean_val = val.replace('€', '').replace(',', '')
                        return float(clean_val)
                    else:
                        return int(val)
                except (ValueError, TypeError):
                    return float('inf')  # Put invalid values at the end
            
            items.sort(key=numeric_key)
        else:
            # Text sorting for other columns
            items.sort()
        
        # Rearrange items in sorted positions
        for index, (val, item) in enumerate(items):
            self.property_tree.move(item, '', index)
        
        # Reapply alternating row colors after sorting
        self._apply_alternating_colors()
    
    def _apply_alternating_colors(self):
        """Apply alternating row colors to the treeview"""
        # Configure the even row color
        self.property_tree.tag_configure('evenrow', background='#f0f0f0')
        
        # Get all items in current order
        items = self.property_tree.get_children('')
        
        # Apply alternating colors while preserving property ID tags
        for i, item in enumerate(items):
            # Get existing tags (property ID)
            existing_tags = self.property_tree.item(item, 'tags')
            property_id = None
            
            # Find the property ID tag
            for tag in existing_tags:
                if tag != 'evenrow':
                    property_id = tag
                    break
            
            # Build new tags list
            new_tags = []
            if property_id:
                new_tags.append(property_id)
            
            if i % 2 == 0:
                # Even rows (0, 2, 4, ...) - light grey
                new_tags.append('evenrow')
            
            self.property_tree.item(item, tags=tuple(new_tags))
    
    def update_status(self, message):
        """Update the status bar message"""
        self.status_label.config(text=message)
        self.root.update_idletasks()
    
    def on_image_click(self, event):
        """Handle click on property image to open URL"""
        if self.current_property_url and self.current_property_url.strip():
            try:
                import webbrowser
                webbrowser.open(self.current_property_url)
                self.update_status(f"Opening property URL: {self.current_property_url}")
            except Exception as e:
                logging.error(f"Error opening URL {self.current_property_url}: {e}")
                messagebox.showerror("Error", f"Could not open URL: {str(e)}")
        else:
            messagebox.showinfo("Info", "No URL available for this property")
    
    def on_reference_click(self, event):
        """Handle single-click on reference field to open URL"""
        # Get the clicked item and column
        item = self.property_tree.identify_row(event.y)
        column = self.property_tree.identify_column(event.x)
        
        if not item or column != '#11':  # #11 is the Reference column (0-indexed, now the last column after SARDO Ref)
            return
        
        # Get the property ID from the item tags
        tags = self.property_tree.item(item, 'tags')
        property_id = None
        for tag in tags:
            if tag != 'evenrow':
                property_id = tag
                break
        
        if not property_id:
            return
        
        # Find the property data to get the URL
        property_data = None
        for prop in self.current_properties:
            if prop.get('id') == property_id:
                property_data = prop
                break
        
        if property_data and property_data.get('property_url'):
            try:
                import webbrowser
                webbrowser.open(property_data['property_url'])
                self.update_status(f"Opening property URL: {property_data['property_url']}")
            except Exception as e:
                logging.error(f"Error opening URL {property_data['property_url']}: {e}")
                messagebox.showerror("Error", f"Could not open URL: {str(e)}")
        else:
            messagebox.showinfo("Info", "No URL available for this property")
    
    def on_treeview_motion(self, event):
        """Handle mouse motion to show hand cursor over reference column"""
        # Get the column under the mouse
        column = self.property_tree.identify_column(event.x)
        
        if column == '#11':  # Reference column (0-indexed, now the last column at index 10 = #11)
            self.property_tree.config(cursor='hand2')
        else:
            self.property_tree.config(cursor='')
    
    def on_checkbox_click(self, event):
        """Handle checkbox clicks in the Select column"""
        # Get the clicked item and column
        item = self.property_tree.identify_row(event.y)
        column = self.property_tree.identify_column(event.x)
        
        if not item or column != '#1':  # #1 is the Select column (0-indexed)
            return
        
        # Get the property ID from the item tags
        tags = self.property_tree.item(item, 'tags')
        property_id = None
        for tag in tags:
            if tag != 'evenrow':
                property_id = tag
                break
        
        if not property_id:
            return
        
        # Toggle the checkbox
        current_value = self.property_tree.set(item, 'Select')
        if current_value == '☐':
            # Check the box
            self.property_tree.set(item, 'Select', '☑')
            self.selected_properties.add(property_id)
        else:
            # Uncheck the box
            self.property_tree.set(item, 'Select', '☐')
            self.selected_properties.discard(property_id)
        
        # Update export buttons state
        self.update_export_buttons()
    
    def toggle_all_selections(self):
        """Toggle all checkboxes when clicking the header"""
        all_items = self.property_tree.get_children()
        if not all_items:
            return
        
        # Check if all are selected
        all_selected = all(
            self.property_tree.set(item, 'Select') == '☑' 
            for item in all_items
        )
        
        # Toggle all items
        for item in all_items:
            tags = self.property_tree.item(item, 'tags')
            property_id = None
            for tag in tags:
                if tag != 'evenrow':
                    property_id = tag
                    break
            
            if property_id:
                if all_selected:
                    # Uncheck all
                    self.property_tree.set(item, 'Select', '☐')
                    self.selected_properties.discard(property_id)
                else:
                    # Check all
                    self.property_tree.set(item, 'Select', '☑')
                    self.selected_properties.add(property_id)
        
        # Update export buttons state
        self.update_export_buttons()
    
    def update_export_buttons(self):
        """Update the export buttons state based on selections"""
        if self.selected_properties:
            self.pdf_export_button.config(state='normal', bg='#e74c3c')
            self.excel_export_button.config(state='normal', bg='#27ae60')
        else:
            self.pdf_export_button.config(state='disabled', bg='#95a5a6')
            self.excel_export_button.config(state='disabled', bg='#95a5a6')
    
    def export_excel(self):
        """Export selected properties to Excel"""
        if not self.selected_properties:
            messagebox.showwarning("Warning", "Please select at least one property to export.")
            return
        
        # Get selected property data
        selected_property_data = []
        for prop in self.current_properties:
            if prop.get('id') in self.selected_properties:
                # Get the mapped source name
                original_source = prop.get('website_source', 'N/A')
                source = original_source
                if source and source != 'N/A':
                    if source in Config.SOURCE_NAME_MAPPING:
                        source = Config.SOURCE_NAME_MAPPING[source]
                    elif source.endswith('Scraper'):
                        source = source[:-7]
                
                # Use title as reference for Waratah properties if available
                is_waratah = original_source == 'WaratahpropertiesScraper'
                title = prop.get('title')
                reference = prop.get('reference', 'N/A')
                display_reference = title if is_waratah and title and title.strip() else reference
                
                # Prepare row data
                row = {
                    'Price': prop.get('property_price'),
                    'Location': prop.get('location', 'N/A'),
                    'Type': prop.get('property_type', 'N/A'),
                    'Beds': prop.get('num_beds'),
                    'Baths': prop.get('num_baths'),
                    'Build (m²)': self._format_area_value(prop.get('living_area')),
                    'Plot (m²)': self._format_area_value(prop.get('land_area')),
                    'Source': source,
                    'SARDO Ref': prop.get('sardo_reference', 'N/A'),
                    'Reference (with link to page source)': display_reference,
                    'property_url': prop.get('property_url', '')
                }
                selected_property_data.append(row)
        
        if not selected_property_data:
            messagebox.showwarning("Warning", "No valid property data found for selected items.")
            return
        
        try:
            # Get save file path
            client_name = self.client_name_var.get().strip() or "Client"
            date_str = datetime.now().strftime("%Y%m%d")
            default_filename = f"Property_Selection_{client_name}_{date_str}.xlsx"
            
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                initialfile=default_filename,
                title="Save Excel Export"
            )
            
            if not file_path:
                return
            
            self.update_status("Generating Excel report...")
            
            # Create DataFrame
            df = pd.DataFrame(selected_property_data)
            
            # Reorder columns to match the screenshot requirements
            columns_order = [
                'Price', 'Location', 'Type', 'Beds', 'Baths', 
                'Build (m²)', 'Plot (m²)', 'Source', 'SARDO Ref', 
                'Reference (with link to page source)'
            ]
            
            # Save to Excel with hyperlinks
            with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                # Filter to only requested columns for the final output
                df_export = df[columns_order]
                df_export.to_excel(writer, index=False, sheet_name='Properties')
                
                # Get the workbook and worksheet to add hyperlinks
                workbook = writer.book
                worksheet = writer.sheets['Properties']
                
                # Iterate through the rows and add hyperlinks to the 'Reference' column
                # Reference column is the last one in columns_order (index 9, which is column J)
                # Header is row 1, data starts from row 2
                for idx, row_data in enumerate(selected_property_data):
                    url = row_data.get('property_url')
                    if url:
                        cell = worksheet.cell(row=idx + 2, column=10) # Column J is index 10
                        cell.hyperlink = url
                        cell.font = Font(color="0000FF", underline="single")
                
                # Adjust column widths
                for i, column in enumerate(columns_order):
                    max_length = max(
                        df_export[column].astype(str).map(len).max(),
                        len(column)
                    ) + 2
                    worksheet.column_dimensions[chr(65 + i)].width = min(max_length, 50)

            self.update_status(f"Excel report generated successfully: {os.path.basename(file_path)}")
            messagebox.showinfo("Success", f"Excel report generated successfully!\n\nFile saved to:\n{file_path}")
            
        except Exception as e:
            logging.error(f"Error generating Excel: {e}")
            self.update_status(f"Error generating Excel: {e}")
            messagebox.showerror("Error", f"Failed to generate Excel report:\n{str(e)}")
            
    def export_pdf(self):
        """Export selected properties to PDF"""
        if not self.selected_properties:
            messagebox.showwarning("Warning", "Please select at least one property to export.")
            return
        
        # Get selected property data
        selected_property_data = []
        for prop in self.current_properties:
            if prop.get('id') in self.selected_properties:
                selected_property_data.append(prop)
        
        if not selected_property_data:
            messagebox.showwarning("Warning", "No valid property data found for selected items.")
            return
        
        try:
            # Generate PDF
            self.update_status("Generating PDF report...")
            
            # Get client name
            client_name = self.client_name_var.get().strip()
            if not client_name:
                client_name = "Smith"  # Fallback to default
            
            # Calculate statistics for the report
            total_properties = len(selected_property_data)
            prices = [prop.get('property_price', 0) for prop in selected_property_data if prop.get('property_price')]
            avg_price = sum(prices) / len(prices) if prices else 0
            median_price = sorted(prices)[len(prices)//2] if prices else 0
            min_price = min(prices) if prices else 0
            max_price = max(prices) if prices else 0
            
            # Generate the PDF
            pdf_path = self.pdf_generator.generate_property_report(
                selected_property_data,
                total_properties,
                avg_price,
                median_price,
                min_price,
                max_price,
                client_name
            )
            
            self.update_status(f"PDF report generated successfully: {pdf_path}")
            messagebox.showinfo("Success", f"PDF report generated successfully!\n\nFile saved to:\n{pdf_path}")
            
        except Exception as e:
            logging.error(f"Error generating PDF: {e}")
            self.update_status(f"Error generating PDF: {e}")
            messagebox.showerror("Error", f"Failed to generate PDF report:\n{str(e)}")
    
    def run(self):
        """Start the application"""
        self.root.mainloop()

if __name__ == "__main__":
    app = PropertyApp()
    app.run()
