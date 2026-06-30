from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import os
import tempfile
from typing import List, Dict
from datetime import datetime
from s3_manager import S3Manager

# Register the font  
pdfmetrics.registerFont(TTFont('Trajan Pro', 'fonts/TrajanPro-Regular.ttf'))
pdfmetrics.registerFont(TTFont('Isidora Sans', 'fonts/IsidoraSans-Regular.ttf'))

class PDFGenerator:
    def __init__(self):
        self.s3_manager = S3Manager()
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles for the report"""
        # Title style
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        # Subtitle style
        self.subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=self.styles['Heading2'],
            fontSize=16,
            spaceAfter=20,
            textColor=colors.darkblue
        )
        
        # Property title style
        self.property_title_style = ParagraphStyle(
            'PropertyTitle',
            parent=self.styles['Heading3'],
            fontSize=14,
            spaceAfter=10,
            textColor=colors.darkgreen
        )
        
        # Normal text style
        self.normal_style = ParagraphStyle(
            'CustomNormal',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=6
        )
    
    def generate_property_listing_report(self, properties: List[Dict], output_path: str, title: str = "Property Report"):
        """
        Generate a PDF report with property listings and images
        
        Args:
            properties: List of property dictionaries
            output_path: Path where to save the PDF
            title: Title of the report
        """
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        
        # Add title
        story.append(Paragraph(title, self.title_style))
        story.append(Spacer(1, 20))
        
        # Add generation date
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", self.normal_style))
        story.append(Spacer(1, 20))
        
        # Add summary
        story.append(Paragraph(f"Total Properties: {len(properties)}", self.subtitle_style))
        story.append(Spacer(1, 20))
        
        # Process each property
        for i, property_data in enumerate(properties, 1):
            story.extend(self._create_property_section(property_data, i))
            story.append(Spacer(1, 20))
        
        # Build PDF
        doc.build(story)
    
    def _create_property_section(self, property_data: Dict, index: int) -> List:
        """Create a section for a single property"""
        elements = []
        
        # Property title
        title = f"{index}. {property_data.get('property_type', 'Property')} - {property_data.get('property_location', 'Unknown Location')}"
        elements.append(Paragraph(title, self.property_title_style))
        
        # Property details table
        details_data = [
            ['Price:', self._format_price_value(property_data.get('property_price'))],
            ['Location:', property_data.get('property_location', 'N/A')],
            ['Type:', property_data.get('property_type', 'N/A')],
            ['Bedrooms:', str(property_data.get('num_beds', 'N/A'))],
            ['Bathrooms:', str(property_data.get('num_baths', 'N/A'))],
            ['Source:', property_data.get('website_source', 'N/A')],
            ['Listed:', property_data.get('created_at', 'N/A')]
        ]
        
        details_table = Table(details_data, colWidths=[1.5*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(details_table)
        elements.append(Spacer(1, 10))
        
        # Add property image if available
        image_url = property_data.get('image_url')
        if image_url:
            try:
                # Download image data from S3
                image_data = self.s3_manager.download_image_data(image_url)
                if image_data:
                    # Save temporary image file
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                        temp_file.write(image_data)
                        temp_path = temp_file.name
                    
                    # Add image to PDF
                    img = Image(temp_path, width=3*inch, height=2*inch)
                    elements.append(img)
                    
                    # Clean up temporary file
                    os.unlink(temp_path)
                else:
                    elements.append(Paragraph("Image not available", self.normal_style))
            except Exception as e:
                elements.append(Paragraph(f"Error loading image: {str(e)}", self.normal_style))
        else:
            elements.append(Paragraph("No image available", self.normal_style))
        
        return elements
    
    def generate_summary_report(self, statistics: Dict, output_path: str):
        """
        Generate a summary report with database statistics
        
        Args:
            statistics: Dictionary containing database statistics
            output_path: Path where to save the PDF
        """
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        
        # Add title
        story.append(Paragraph("Property Database Summary Report", self.title_style))
        story.append(Spacer(1, 20))
        
        # Add generation date
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", self.normal_style))
        story.append(Spacer(1, 20))
        
        # Overall statistics
        story.append(Paragraph("Overall Statistics", self.subtitle_style))
        
        overall_data = [
            ['Total Properties:', str(statistics.get('total_properties', 0))],
            ['Average Price:', self._format_price_value(statistics.get('avg_price'))],
            ['Price Range:', f"{self._format_price_value(statistics.get('price_range', (None, None))[0])} - {self._format_price_value(statistics.get('price_range', (None, None))[1])}"]
        ]
        
        overall_table = Table(overall_data, colWidths=[2*inch, 3*inch])
        overall_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(overall_table)
        story.append(Spacer(1, 20))
        
        # Properties by type
        if statistics.get('by_type'):
            story.append(Paragraph("Properties by Type", self.subtitle_style))
            
            type_data = [['Property Type', 'Count']]
            for prop_type, count in statistics['by_type'].items():
                type_data.append([prop_type, str(count)])
            
            type_table = Table(type_data, colWidths=[2.5*inch, 1*inch])
            type_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgreen),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(type_table)
            story.append(Spacer(1, 20))
        
        # Properties by source
        if statistics.get('by_source'):
            story.append(Paragraph("Properties by Source", self.subtitle_style))
            
            source_data = [['Website Source', 'Count']]
            for source, count in statistics['by_source'].items():
                source_data.append([source, str(count)])
            
            source_table = Table(source_data, colWidths=[2.5*inch, 1*inch])
            source_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightyellow),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(source_table)
        
        # Build PDF
        doc.build(story)
    
    def generate_property_report(self, properties: List[Dict], total_properties: int, avg_price: float, 
                                median_price: float, min_price: float, max_price: float, client_name: str = "Smith") -> str:
        """
        Generate a SARDO property report with cover page and executive summary
        
        Args:
            properties: List of selected property dictionaries
            total_properties: Total number of selected properties
            avg_price: Average price of selected properties
            median_price: Median price of selected properties
            min_price: Minimum price of selected properties
            max_price: Maximum price of selected properties
            client_name: Name of the client for the report
            
        Returns:
            Path to the generated PDF file
        """
        # Create output filename with client name and date
        today_date = datetime.now().strftime("%Y%m%d")
        client_name_upper = client_name.upper().replace(" ", "_")  # Convert to uppercase and replace spaces with underscores
        output_path = f"sardo_property_report_{today_date}_{client_name_upper}.pdf"
        
        doc = SimpleDocTemplate(output_path, pagesize=A4, 
                              leftMargin=0.5*inch, rightMargin=0.5*inch, 
                              topMargin=0.3*inch, bottomMargin=0.5*inch)
        story = []
        
        # Initialize temporary files list for cleanup
        self._temp_files = []
        
        # Page 1: Cover Page
        story.extend(self._create_cover_page(client_name))
        story.append(PageBreak())
        
        # Generate individual property pages only
        for i, property_data in enumerate(properties, 1):
            story.extend(self._create_property_page(property_data, i))
            if i < len(properties):  # Don't add page break after the last property
                story.append(PageBreak())
        
        # Build PDF
        doc.build(story)
        
        # Clean up temporary files after PDF generation
        self._cleanup_temp_files()
        
        return output_path
    
    def _create_cover_page(self, client_name: str = "Smith") -> List:
        """Create the cover page with SARDO branding"""
        elements = []
        
        # Add SARDO logo image at the top with adjusted dimensions
        logo_path = "static/images/Sardo.png"  # Logo file as specified
        if os.path.exists(logo_path):
            try:
                logo = Image(logo_path, width=3.2*inch, height=2*inch)  # Wider, shorter
                elements.append(logo)
                elements.append(Spacer(1, 50))  # Further reduced gap to bring text closer to logo
            except Exception as e:
                print(f"Error loading logo: {e}")
        
        # MIDDLE SECTION: Main title + subtitle (grouped together)
        # Main report title (centered, dark red/maroon, larger, changed font style)
        main_title_style = ParagraphStyle(
            'Main_Title',
            parent=self.styles['Heading1'],
            fontSize=32,
            spaceAfter=20,  # Smaller gap between title and subtitle
            alignment=TA_CENTER,
            textColor=colors.darkred,
            fontName='Trajan Pro'  # Trajan Pro
        )
        elements.append(Paragraph("SARDO360 Client Report", main_title_style))
        
        # Subtitle (centered, grey, smaller)
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=self.styles['Normal'],
            fontSize=12,  # Reduced font size
            spaceAfter=200,  # Increased gap to push confidentiality to center height
            alignment=TA_CENTER,
            textColor=colors.grey,  # Changed to grey color
            fontName='Isidora Sans' # Isidora Sans
        )
        elements.append(Paragraph(f"Curated Properties for {client_name}", subtitle_style))
        
        # BOTTOM SECTION: Confidentiality statement (center height, left-aligned)
        # Add flexible space to position confidentiality at center height
        elements.append(Spacer(1, 50))
        
        # Confidentiality statement (left-aligned, at center height)
        conf_style = ParagraphStyle(
            'Confidential',
            parent=self.styles['Normal'],
            fontSize=11,
            alignment=TA_LEFT,  # Left-aligned as requested
            textColor=colors.black,
            fontName='Helvetica'
        )
        elements.append(Paragraph("Confidential – Prepared by SARDO Property Buying Agency", conf_style))
        
        return elements
    
    def _create_property_page(self, property_data: Dict, index: int) -> List:
        """Create a page for a single property"""
        elements = []
        
        # Property title (large, prominent)
        title_style = ParagraphStyle(
            'Property_Title',
            parent=self.styles['Heading1'],
            fontSize=20,
            spaceAfter=15,
            alignment=TA_LEFT,
            textColor=colors.darkred,
            fontName='Trajan Pro'
        )
        # Use the full title instead of just property_type for a more descriptive header
        property_title = property_data.get('title', property_data.get('property_type', 'Property'))
        elements.append(Paragraph(property_title, title_style))
        
        # Location, type, and reference with bullet separators
        subtitle_style = ParagraphStyle(
            'Property_Subtitle',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=5,
            alignment=TA_LEFT,
            textColor=colors.black,
            fontName='Helvetica'
        )
        
        location = property_data.get('location', 'N/A')
        prop_type = property_data.get('property_type', 'N/A')
        reference = property_data.get('reference', 'N/A')
        title = property_data.get('title', 'N/A')
        source = property_data.get('website_source', 'N/A')
        
        # For WaratahpropertiesScraper, use title as the reference field (same logic as UI)
        is_waratah = source == 'WaratahpropertiesScraper'
        if is_waratah and title and title != 'N/A' and title is not None and title.strip():
            display_reference = title
        else:
            display_reference = reference
        
        # Get SARDO reference
        sardo_reference = property_data.get('sardo_reference', 'N/A')
        
        subtitle_text = f"{location} • {prop_type} • Ref: {sardo_reference}"
        elements.append(Paragraph(subtitle_text, subtitle_style))
        
        # Property image
        image_filename = property_data.get('image_filename')
        source = property_data.get('website_source')
        if image_filename:
            try:
                print(f"Downloading image {image_filename} from {source}")
                image_data = self.s3_manager.download_image_data(image_filename, source)
                
                if image_data:
                    try:
                        # Save temporary image file in project directory
                        import uuid
                        temp_filename = f"temp_image_{uuid.uuid4().hex[:8]}.png"
                        temp_path = os.path.join(os.getcwd(), temp_filename)
                        
                        print(f"Creating temporary image file: {temp_filename}")
                        with open(temp_path, 'wb') as temp_file:
                            temp_file.write(image_data)
                        
                        # Add image to PDF (adjusted size for property page)
                        img = Image(temp_path, width=6.5*inch, height=3.5*inch)
                        elements.append(img)
                        elements.append(Spacer(1, 5))
                        
                        # Store temp path for cleanup after PDF generation
                        if not hasattr(self, '_temp_files'):
                            self._temp_files = []
                        self._temp_files.append(temp_path)
                        
                    except Exception as e:
                        print(f"Error processing image for PDF {image_filename}: {str(e)}")
                        elements.append(Paragraph("Image not available", self.normal_style))
                        elements.append(Spacer(1, 5))
                else:
                    elements.append(Paragraph("Image not available", self.normal_style))
                    elements.append(Spacer(1, 5))
            except Exception as e:
                # Log the error but don't show it in PDF to keep it clean
                print(f"Error loading image {image_filename}: {str(e)}")
                elements.append(Paragraph("Image not available", self.normal_style))
                elements.append(Spacer(1, 5))
        else:
            elements.append(Paragraph("No image available", self.normal_style))
            elements.append(Spacer(1, 5))
        
        # Property details table
        price = property_data.get('property_price')
        bedrooms = property_data.get('num_beds', 'N/A')
        bathrooms = property_data.get('num_baths', 'N/A')
        build_size = property_data.get('living_area', 'N/A')  # Use living_area from database
        plot_size = property_data.get('land_area', 'N/A')    # Use land_area from database
        
        details_data = [
            ['Price', self._format_price_value(price)],
            ['Bedrooms', str(bedrooms)],
            ['Bathrooms', str(bathrooms)],
            ['Build (m²)', self._format_area_value(build_size)],
            ['Plot (m²)', self._format_area_value(plot_size)]
        ]
        
        details_table = Table(details_data, colWidths=[2*inch, 4*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('LINEAFTER', (0, 0), (0, -1), 1, colors.black)
        ]))
        
        elements.append(details_table)
        
        return elements
    
    def _cleanup_temp_files(self):
        """Clean up temporary image files after PDF generation"""
        if hasattr(self, '_temp_files'):
            for temp_path in self._temp_files:
                try:
                    if os.path.exists(temp_path):
                        # Get just the filename for cleaner output
                        filename = os.path.basename(temp_path)
                        os.unlink(temp_path)
                        print(f"Cleaned up temporary file: {filename}")
                except Exception as e:
                    print(f"Error cleaning up temporary file {temp_path}: {e}")
            self._temp_files = []
    
    def _format_price_value(self, value):
        """Format price values for display in PDF"""
        if value is None or value == '' or value == 'N/A' or value == 'None':
            return '—'
        
        try:
            # Convert to float and format
            float_value = float(value)
            if float_value > 0:
                return f"€{float_value:,.0f}"
            else:
                return '—'
        except (ValueError, TypeError):
            return '—'
    
    def _format_area_value(self, value):
        """Format area values for display in PDF"""
        if value is None or value == '' or value == 'N/A' or value == 'None':
            return '—'
        
        try:
            # Convert to float and format
            float_value = float(value)
            if float_value > 0:
                return f"{float_value:.0f}"  # No comma separator
            else:
                return '—'
        except (ValueError, TypeError):
            # If it's already a string, try to clean it
            if isinstance(value, str):
                # Remove common suffixes and clean
                cleaned = value.replace('m²', '').replace('m2', '').replace(',', '').strip()
                try:
                    float_value = float(cleaned)
                    if float_value > 0:
                        return f"{float_value:.0f}"  # No comma separator
                except ValueError:
                    pass
            return '—'
    
    def _create_executive_summary(self, total_properties: int, avg_price: float, median_price: float,
                                 min_price: float, max_price: float, properties: List[Dict]) -> List:
        """Create the executive summary page"""
        elements = []
        
        # Executive Summary title
        exec_title_style = ParagraphStyle(
            'Exec_Title',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=20,
            alignment=TA_LEFT,
            textColor=colors.darkred
        )
        elements.append(Paragraph("Executive Summary", exec_title_style))
        
        # Summary table
        summary_data = [
            ['Total Matches', str(total_properties)],
            ['Average Price', self._format_price_value(avg_price)],
            ['Median Price', self._format_price_value(median_price)],
            ['Lowest / Highest', f"{self._format_price_value(min_price)} / {self._format_price_value(max_price)}"]
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 30))
        
        # Price comparison chart title
        chart_title_style = ParagraphStyle(
            'Chart_Title',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=15,
            alignment=TA_CENTER,
            textColor=colors.black
        )
        elements.append(Paragraph("Filtered Properties - Price Comparison", chart_title_style))
        
        # Create price comparison table with visual bars
        if properties:
            max_price = max(prop.get('property_price', 0) for prop in properties)
            chart_data = [['Property', 'Price (€)', 'Visual']]
            
            for i, prop in enumerate(properties, 1):
                price = prop.get('property_price', 0)
                reference = prop.get('reference', 'N/A')
                title = prop.get('title', 'N/A')
                source = prop.get('website_source', 'N/A')
                
                # For WaratahpropertiesScraper, use title as the reference field (same logic as UI)
                is_waratah = source == 'WaratahpropertiesScraper'
                if is_waratah and title and title != 'N/A' and title is not None and title.strip():
                    property_reference = title
                else:
                    property_reference = reference
                
                # Create a visual bar representation
                if max_price > 0:
                    bar_length = int((price / max_price) * 20)  # Scale to 20 characters
                    bar = "█" * bar_length
                else:
                    bar = ""
                
                chart_data.append([property_reference, self._format_price_value(price), bar])
            
            chart_table = Table(chart_data, colWidths=[1.2*inch, 1.5*inch, 2*inch])
            chart_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (1, -1), 'CENTER'),
                ('ALIGN', (2, 0), (2, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(chart_table)
        
        return elements
