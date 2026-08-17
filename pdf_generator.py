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
from pypdf import PdfReader, PdfWriter

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
        Generate a SARDO property report structure.
        Uses pypdf to merge template Page 1 (Cover), Page 9 (Strategic Advice), Page 10 (Contact)
        from /home/aviox/Downloads/Property Portfolio Template (DEV).pdf, while dynamically 
        generating Page 2 (Executive Summary), Page 3 (Scope), and all repeatable property overview/analysis pages.
        """
        today_date = datetime.now().strftime("%Y%m%d")
        client_name_upper = client_name.upper().replace(" ", "_")
        final_output_path = f"sardo_property_report_{today_date}_{client_name_upper}.pdf"
        
        # Initialize temporary files list for cleanup
        self._temp_files = []
        
        # Build dynamic section in a temporary PDF file first
        temp_fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(temp_fd)
        self._temp_files.append(temp_pdf_path)
        
        doc = SimpleDocTemplate(temp_pdf_path, pagesize=A4, 
                              leftMargin=0.5*inch, rightMargin=0.5*inch, 
                              topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        
        # Page 2: Dynamic Executive Summary
        story.extend(self._create_dynamic_executive_summary_page(client_name, total_properties, avg_price, median_price, min_price, max_price))
        story.append(PageBreak())
        
        # Page 3: Dynamic Scope of Property Search
        story.extend(self._create_dynamic_scope_page())
        story.append(PageBreak())
        
        # Dynamic Repeatable Property Pages
        for i, property_data in enumerate(properties, 1):
            story.extend(self._create_property_overview_page(property_data, i))
            story.append(PageBreak())
            
            story.extend(self._create_property_analysis_page(property_data, i))
            if i < len(properties):
                story.append(PageBreak())
                
        doc.build(story)
        
        # Merge phase using pypdf
        template_path = "/home/aviox/Downloads/Property Portfolio Template (DEV).pdf"
        
        writer = PdfWriter()
        
        # Try to load template PDF and merge static pages
        template_loaded = False
        if os.path.exists(template_path):
            try:
                template_reader = PdfReader(template_path)
                template_loaded = True
            except Exception as e:
                print(f"Error reading template PDF: {e}")
                
        # 1. Page 1: Template Cover
        if template_loaded and len(template_reader.pages) >= 1:
            writer.add_page(template_reader.pages[0])
            
        # 2. Add all dynamic pages (Executive Summary, Scope, and Property sections)
        try:
            dynamic_reader = PdfReader(temp_pdf_path)
            for page in dynamic_reader.pages:
                writer.add_page(page)
        except Exception as e:
            print(f"Error loading dynamic pages: {e}")
            
        # 3. Last 2 pages: Template Page 9 & 10 (indices 8 and 9)
        if template_loaded and len(template_reader.pages) >= 10:
            writer.add_page(template_reader.pages[8])
            writer.add_page(template_reader.pages[9])
            
        # Save to final path
        with open(final_output_path, "wb") as out_file:
            writer.write(out_file)
            
        # Clean up temp files
        self._cleanup_temp_files()
        
        return final_output_path

    def _create_dynamic_executive_summary_page(self, client_name: str, total_properties: int, avg_price: float, median_price: float, min_price: float, max_price: float) -> List:
        """Dynamically render the Executive Summary matching Page 2 template format"""
        elements = []
        
        title_style = ParagraphStyle(
            'ExecSummaryTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=5,
            alignment=TA_LEFT,
            textColor=colors.black,
            fontName='Trajan Pro'
        )
        elements.append(Paragraph("EXECUTIVE SUMMARY", title_style))
        
        # Add the red block under header
        red_bar_data = [['']]
        red_bar = Table(red_bar_data, colWidths=[0.3*inch], rowHeights=[0.05*inch])
        red_bar.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.darkred),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(red_bar)
        elements.append(Spacer(1, 20))
        
        meta_style = ParagraphStyle(
            'ExecMeta',
            parent=self.styles['Normal'],
            fontSize=11,
            leading=16,
            textColor=colors.black,
            fontName='Helvetica'
        )
        
        today_str = datetime.now().strftime("%dth %B %Y")
        elements.append(Paragraph(f"<b>Client Name(s)</b> {client_name}", meta_style))
        elements.append(Paragraph(f"<b>Date</b> {today_str}", meta_style))
        elements.append(Paragraph("<b>Assigned Advisor/Contact Details</b> Mario Sardo", meta_style))
        elements.append(Spacer(1, 15))
        
        section_style = ParagraphStyle(
            'ExecSectionTitle',
            parent=self.styles['Heading2'],
            fontSize=12,
            spaceAfter=8,
            textColor=colors.darkred,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("CLIENT BRIEF", section_style))
        
        body_style = ParagraphStyle(
            'ExecBody',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=14,
            spaceAfter=6,
            textColor=colors.black,
            fontName='Helvetica'
        )
        elements.append(Paragraph(f"<b>Location:</b> Algarve, Portugal", body_style))
        elements.append(Paragraph(f"<b>Bedrooms:</b> {total_properties}+", body_style))
        elements.append(Paragraph(f"<b>Objectives:</b> Select premium high-value investment assets for review.", body_style))
        elements.append(Paragraph(f"<b>Budget Range:</b> €{min_price:,.0f} - €{max_price:,.0f}", body_style))
        elements.append(Paragraph(f"<b>Average Selected Price:</b> €{avg_price:,.0f}", body_style))
        elements.append(Paragraph(f"<b>Timeline:</b> Immediate", body_style))
        elements.append(Paragraph(f"<b>Overview:</b> Client requested portfolio analysis for the top {total_properties} target items.", body_style))
        elements.append(Spacer(1, 15))
        
        elements.append(Paragraph("KEY INSIGHTS", section_style))
        elements.append(Paragraph(
            "Lorem ipsum dolor sit amet, consectetuer adipiscing elit, sed diam nonummy nibh euismod "
            "tincidunt ut laoreet dolore magna aliquam erat volutpat. Ut wisi enim ad minim veniam, quis nostrud "
            "erxi tation ullamcorper suscipit lobortis nisl ut aliquip ex ea commodo consequat.",
            body_style
        ))
        elements.append(Spacer(1, 10))
        
        elements.append(Paragraph("MARKET OBSERVATIONS", section_style))
        elements.append(Paragraph(
            "Lorem ipsum dolor sit amet, consectetuer adipiscing elit, sed diam nonummy nibh euismod "
            "tincidunt ut laoreet dolore magna aliquam erat volutpat. Ut wisi enim ad minim veniam, quis nostrud "
            "erxi tation ullamcorper suscipit lobortis nisl ut aliquip ex ea commodo consequat.",
            body_style
        ))
        
        return elements

    def _create_dynamic_scope_page(self) -> List:
        """Dynamically render the Scope of Property Search matching Page 3 template format"""
        elements = []
        
        title_style = ParagraphStyle(
            'ScopeTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=5,
            alignment=TA_LEFT,
            textColor=colors.black,
            fontName='Trajan Pro'
        )
        elements.append(Paragraph("EXECUTIVE SUMMARY", title_style))
        
        red_bar_data = [['']]
        red_bar = Table(red_bar_data, colWidths=[0.3*inch], rowHeights=[0.05*inch])
        red_bar.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.darkred),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(red_bar)
        elements.append(Spacer(1, 20))
        
        section_style = ParagraphStyle(
            'ScopeSectionTitle',
            parent=self.styles['Heading2'],
            fontSize=12,
            spaceAfter=8,
            textColor=colors.darkred,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("SCOPE OF PROPERTY SEARCH", section_style))
        
        body_style = ParagraphStyle(
            'ScopeBody',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=15,
            spaceAfter=12,
            textColor=colors.black,
            fontName='Helvetica'
        )
        elements.append(Paragraph(
            "Lorem ipsum dolor sit amet, consectetuer adipiscing elit, sed diam nonummy nibh "
            "euismod tincidunt ut laoreet dolore magna aliquam erat volutpat. Ut wisi enim ad minim "
            "veniam, quis nostrud exerci tation ullamcorper suscipit lobortis nisl ut aliquip ex ea "
            "commodo consequat.",
            body_style
        ))
        elements.append(Paragraph(
            "Duis autem vel eum iriure dolor in hendrerit in vulputate velit esse molestie consequat, "
            "vel illum dolore eu feugiat nulla facilisis at vero eros et accumsan et iusto odio dignissim "
            "qui blandit praesent luptatum zzril delenit augue duis dolore te feugait nulla facilisi.",
            body_style
        ))
        
        return elements

    def _create_property_overview_page(self, property_data: Dict, index: int) -> List:
        """Create the overview page (Page 1) of the property repeatable section.
        Matches the visual design in the client's PDF template:
        - Header block (Title + Reference)
        - 3-image layout: 1 large main hero, 2 supporting placeholders below
        - Clean vertical icon attributes column next to commentary
        - Map placeholder at the bottom right.
        """
        elements = []
        
        # 1. Header block: Title on Left, Reference on Right
        header_data = [
            [
                Paragraph(f"<b>{(property_data.get('title') or property_data.get('property_type') or 'PROPERTY').upper()}</b>", ParagraphStyle('PropTitleLeft', parent=self.styles['Normal'], fontName='Trajan Pro', fontSize=18, textColor=colors.darkred)),
                Paragraph(f"<b>REF {property_data.get('sardo_reference') or 'N/A'}</b>", ParagraphStyle('PropRefRight', parent=self.styles['Normal'], fontName='Trajan Pro', fontSize=12, alignment=2, textColor=colors.darkred))
            ]
        ]
        header_table = Table(header_data, colWidths=[5.0*inch, 2.2*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 10))
        
        # 2. Hero Image (Proportional 6.8 x 2.8 inches)
        image_filename = property_data.get('image_filename')
        source = property_data.get('website_source')
        
        hero_img_rendered = False
        if image_filename:
            try:
                image_data = self.s3_manager.download_image_data(image_filename, source)
                if image_data:
                    import uuid
                    temp_filename = f"temp_hero_{uuid.uuid4().hex[:8]}.png"
                    temp_path = os.path.join(os.getcwd(), temp_filename)
                    with open(temp_path, 'wb') as temp_file:
                        temp_file.write(image_data)
                    
                    img = Image(temp_path, width=7.2*inch, height=2.8*inch)
                    elements.append(img)
                    self._temp_files.append(temp_path)
                    hero_img_rendered = True
            except Exception as e:
                print(f"Error loading hero image {image_filename}: {str(e)}")
        
        if not hero_img_rendered:
            hero_placeholder = Table([['Hero Image Placeholder']], colWidths=[7.2*inch], rowHeights=[2.8*inch])
            hero_placeholder.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.gray)
            ]))
            elements.append(hero_placeholder)
            
        elements.append(Spacer(1, 8))
        
        # 3. Two smaller supporting image placeholders or actual images if they exist
        sub_images = []
        try:
            # 1. Try to fetch from image_filename_2 and image_filename_3 (S3 columns)
            source = property_data.get('website_source')
            for col in ('image_filename_2', 'image_filename_3'):
                val = property_data.get(col)
                if val and val != "N/A":
                    try:
                        img_data = self.s3_manager.download_image_data(val, source)
                        if img_data:
                            import uuid
                            temp_filename = f"temp_sub_{uuid.uuid4().hex[:8]}.png"
                            temp_path = os.path.join(os.getcwd(), temp_filename)
                            with open(temp_path, 'wb') as temp_file:
                                temp_file.write(img_data)
                            from reportlab.platypus import Image as RLImage
                            img = RLImage(temp_path, width=3.5*inch, height=1.4*inch)
                            sub_images.append(img)
                            self._temp_files.append(temp_path)
                    except Exception as s3_err:
                        print(f"Error loading S3 sub image {val}: {s3_err}")

            # 2. Fallback to property documents and crawling if less than 2 images
            if len(sub_images) < 2:
                import urllib.request
                from urllib.parse import urljoin
                from database import db_manager
                
                # Fetch documents
                docs = db_manager.get_property_documents(property_data.get('id'))
                image_docs = [d for d in docs if d.get('document_type') == 'Image']
                candidate_urls = [d.get('file_url', '') for d in image_docs if d.get('file_url')]
                
                # Fallback to crawling the property page live
                if len(candidate_urls) < 2 and property_data.get('property_url'):
                    prop_url = property_data.get('property_url')
                    main_img_url = property_data.get('image_filename') or ''
                    main_basename = os.path.basename(main_img_url).lower() if main_img_url else None
                    
                    try:
                        req = urllib.request.Request(
                            prop_url, 
                            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            html_content = resp.read().decode('utf-8', errors='ignore')
                            img_tags = re.findall(r'''<img[^>]+src=["']([^"']+)["']''', html_content)
                            
                            skipped_first = False
                            for img_url in img_tags:
                                img_url = urljoin(prop_url, img_url)
                                u_lower = img_url.lower()
                                if main_basename and main_basename in u_lower:
                                    continue
                                if any(x in u_lower for x in ["logo", "icon", "avatar", "agent", "profile", "marker", "map", "pin", "svg", "star", "social", "header", "footer", "sq.png", "facebook", "twitter", "instagram", "linkedin", "youtube"]):
                                    continue
                                if not any(ext in u_lower for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                                    continue
                                
                                # Skip the first valid image since it is the hero image
                                if not skipped_first:
                                    skipped_first = True
                                    continue
                                    
                                if img_url not in candidate_urls:
                                    candidate_urls.append(img_url)
                                    if len(candidate_urls) >= 5: # limit scan
                                        break
                    except Exception as crawl_err:
                        print(f"Error crawling live images: {crawl_err}")
                
                # Download and compile the crawled/document images
                for url in candidate_urls:
                    if len(sub_images) >= 2:
                        break
                    img_data = None
                    if url.startswith(('http://', 'https://')):
                        try:
                            req = urllib.request.Request(
                                url, 
                                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                            )
                            with urllib.request.urlopen(req, timeout=5) as r:
                                img_data = r.read()
                        except Exception as download_err:
                            print(f"Error downloading direct image {url}: {download_err}")
                    else:
                        s3_key = url
                        if "amazonaws.com/" in url:
                            s3_key = url.split("amazonaws.com/")[-1]
                        img_data = self.s3_manager.download_image_data(s3_key)
                    
                    if img_data:
                        import uuid
                        temp_filename = f"temp_sub_{uuid.uuid4().hex[:8]}.png"
                        temp_path = os.path.join(os.getcwd(), temp_filename)
                        with open(temp_path, 'wb') as temp_file:
                            temp_file.write(img_data)
                        
                        from reportlab.platypus import Image as RLImage
                        img = RLImage(temp_path, width=3.5*inch, height=1.4*inch)
                        sub_images.append(img)
                        self._temp_files.append(temp_path)
        except Exception as e:
            print(f"Error loading supporting images: {e}")
            
        placeholder1 = Table([['Supporting Image 1\n(Canva Placeholder)']], colWidths=[3.5*inch], rowHeights=[1.4*inch])
        placeholder2 = Table([['Supporting Image 2\n(Canva Placeholder)']], colWidths=[3.5*inch], rowHeights=[1.4*inch])
        
        img1 = sub_images[0] if len(sub_images) > 0 else placeholder1
        img2 = sub_images[1] if len(sub_images) > 1 else placeholder2
        
        sub_images_data = [[img1, img2]]
        
        for item in sub_images_data[0]:
            if isinstance(item, Table):
                item.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.gray)
                ]))
            
        sub_images_table = Table(sub_images_data, colWidths=[3.6*inch, 3.6*inch])
        sub_images_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(sub_images_table)
        elements.append(Spacer(1, 15))
        
        # 4. Clean attribute list next to commentary & map
        # Left column: metadata list (with inline block icons)
        # Right column: commentary block & Map Placeholder
        
        location = property_data.get('location') or 'N/A'
        beds = property_data.get('num_beds')
        beds_str = str(beds) if beds is not None else 'N/A'
        baths = property_data.get('num_baths')
        baths_str = str(baths) if baths is not None else 'N/A'
        build = self._format_area_value(property_data.get('living_area'))
        plot = self._format_area_value(property_data.get('land_area'))
        const_year = property_data.get('construction_year') or property_data.get('year_built') or 'N/A'
        energy = property_data.get('energy_rating') or property_data.get('energy_class') or 'N/A'
        price = self._format_price_value(property_data.get('property_price'))
        
        attr_style = ParagraphStyle(
            'AttrItem',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=18,
            textColor=colors.black,
            fontName='Helvetica'
        )
        
        # Compile attributes HTML column using clean character icons matching template layout
        attributes_list = [
            Paragraph(f"📍 &nbsp; {location}", attr_style),
            Paragraph(f"🛏 &nbsp; {beds_str} Beds", attr_style),
            Paragraph(f"🛁 &nbsp; {baths_str} Baths", attr_style),
            Paragraph(f"📐 &nbsp; {build} m² (Build)", attr_style),
            Paragraph(f"🌳 &nbsp; {plot} m² (Plot)", attr_style),
            Paragraph(f"📅 &nbsp; Built {const_year}", attr_style),
            Paragraph(f"⚡ &nbsp; Energy {energy}", attr_style),
            Paragraph(f"💶 &nbsp; <b>{price}</b>", attr_style),
        ]
        
        # Compile attributes table
        left_col_data = [[item] for item in attributes_list]
        left_col_table = Table(left_col_data, colWidths=[2.2*inch])
        left_col_table.setStyle(TableStyle([
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Right column: description & map placeholder
        right_elements = []
        desc_style = ParagraphStyle(
            'RightDesc',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=14,
            textColor=colors.black,
            fontName='Helvetica'
        )
        
        right_elements.append(Paragraph(
            "Lorem ipsum dolor sit amet, consectetuer adipiscing elit, sed diam nonummy nibh euismod "
            "tincidunt ut laoreet dolore magna aliquam erat volutpat. Ut wisi enim ad minim veniam, quis nostrud "
            "erxi tation ullamcorper suscipit.",
            desc_style
        ))
        right_elements.append(Spacer(1, 10))
        
        # Map placeholder or actual map image
        map_table = Table([['Map Placeholder\n(Canva Placeholder)']], colWidths=[4.6*inch], rowHeights=[1.2*inch])
        map_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.gray)
        ]))
        
        map_element = None
        map_filename = property_data.get('map_filename')
        source = property_data.get('website_source')
        if map_filename and map_filename != "N/A":
            try:
                map_data = self.s3_manager.download_image_data(map_filename, source)
                if map_data:
                    import uuid
                    temp_filename = f"temp_map_{uuid.uuid4().hex[:8]}.png"
                    temp_path = os.path.join(os.getcwd(), temp_filename)
                    with open(temp_path, 'wb') as temp_file:
                        temp_file.write(map_data)
                    
                    from reportlab.platypus import Image as RLImage
                    map_element = RLImage(temp_path, width=4.6*inch, height=1.2*inch)
                    self._temp_files.append(temp_path)
            except Exception as e:
                print(f"Error loading map image {map_filename}: {e}")
                
        if map_element:
            right_elements.append(map_element)
        else:
            right_elements.append(map_table)
        
        right_col_table = Table([[right_elements]], colWidths=[4.7*inch])
        right_col_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Main split table
        split_table = Table([[left_col_table, right_col_table]], colWidths=[2.4*inch, 4.8*inch])
        split_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        elements.append(split_table)
        
        return elements

    def _create_property_analysis_page(self, property_data: Dict, index: int) -> List:
        """Create the analysis page (Page 2) containing placeholder Lorem Ipsum commentary"""
        elements = []
        
        title_style = ParagraphStyle(
            'Analysis_Title',
            parent=self.styles['Heading1'],
            fontSize=20,
            spaceAfter=25,
            alignment=TA_LEFT,
            textColor=colors.darkred,
            fontName='Trajan Pro'
        )
        elements.append(Paragraph(f"{index}. Property Analysis & Commentary", title_style))
        
        lorem_title_style = ParagraphStyle(
            'Lorem_Title',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=10,
            textColor=colors.black,
            fontName='Helvetica-Bold'
        )
        
        lorem_body_style = ParagraphStyle(
            'Lorem_Body',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=15,
            leading=16,
            textColor=colors.black,
            fontName='Helvetica'
        )
        
        # Section 1
        elements.append(Paragraph("1. Market Context & Valuation Analysis", lorem_title_style))
        elements.append(Paragraph(
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Aliquam pulvinar vestibulum erat, "
            "ut dictum dolor. Duis et congue erat. Sed tempor lorem sed elit aliquam congue. "
            "Class aptent taciti sociosqu ad litora torquent per conubia nostra, per inceptos himenaeos. "
            "Integer at urna id leo commodo facilisis. Ut pellentesque elementum luctus. "
            "Praesent et diam in dui volutpat efficitur. Mauris vitae tellus nec elit gravida pellentesque nec vel nisl.",
            lorem_body_style
        ))
        elements.append(Spacer(1, 10))
        
        # Section 2
        elements.append(Paragraph("2. Strategic Fit & Investment Potential", lorem_title_style))
        elements.append(Paragraph(
            "Phasellus aliquet, elit vel rhoncus efficitur, ligula mauris porta augue, vitae eleifend "
            "lectus lectus sit amet erat. Integer facilisis eros quis congue lobortis. "
            "Aliquam eget leo et tellus tincidunt finibus. Ut sed felis nec eros gravida sodales porta vel metus. "
            "Curabitur rhoncus nunc sed eros feugiat, sit amet egestas mauris efficitur. "
            "Donec id pulvinar dolor. Sed facilisis, risus quis congue ultrices, arcu ligula porttitor "
            "mauris, sed sollicitudin nisl magna non purus. Aliquam nec arcu id mi varius finibus. "
            "Morbi elementum nunc convallis turpis vulputate sollicitudin.",
            lorem_body_style
        ))
        elements.append(Spacer(1, 10))
        
        # Section 3
        elements.append(Paragraph("3. Recommendations & Negotiation Position", lorem_title_style))
        elements.append(Paragraph(
            "Curabitur finibus hendrerit rhoncus. Suspendisse pretium felis mi, volutpat lacinia urna "
            "tincidunt et. Curabitur sed luctus diam. Etiam feugiat, nunc convallis laoreet "
            "scelerisque, justo ex finibus erat, ut feugiat metus sem pellentesque lorem. "
            "Sed interdum eleifend tellus, non convallis lacus faucibus in. Proin hendrerit "
            "dolor lorem, a eleifend magna hendrerit a. Proin cursus metus sit amet diam tristique sodales.",
            lorem_body_style
        ))
        
        return elements

    def _cleanup_temp_files(self):
        """Clean up temporary image files after PDF generation"""
        if hasattr(self, '_temp_files'):
            for temp_path in self._temp_files:
                try:
                    if os.path.exists(temp_path):
                        filename = os.path.basename(temp_path)
                        os.unlink(temp_path)
                        print(f"Cleaned up temporary file: {filename}")
                except Exception as e:
                    print(f"Error cleaning up temporary file {temp_path}: {e}")
            self._temp_files = []
    
    def _format_price_value(self, value):
        """Format price values for display in PDF.

        Non-positive or missing prices (-1 sentinel, 0, None) mean the price is
        not published, so we show 'P.O.A.' (Price on Application).
        """
        if value is None or value == '' or value == 'N/A' or value == 'None':
            return 'P.O.A.'

        try:
            float_value = float(value)
            if float_value > 0:
                return f"€{float_value:,.0f}"
            else:
                return 'P.O.A.'
        except (ValueError, TypeError):
            return 'P.O.A.'
    
    def _format_area_value(self, value):
        """Format area values for display in PDF"""
        if value is None or value == '' or value == 'N/A' or value == 'None':
            return '—'
        
        try:
            float_value = float(value)
            if float_value > 0:
                return f"{float_value:.0f}"
            else:
                return '—'
        except (ValueError, TypeError):
            if isinstance(value, str):
                cleaned = value.replace('m²', '').replace('m2', '').replace(',', '').strip()
                try:
                    float_value = float(cleaned)
                    if float_value > 0:
                        return f"{float_value:.0f}"
                except ValueError:
                    pass
            return '—'

