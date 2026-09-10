"""Uploaded media and documents attached to a property.

Split out of the original database.DatabaseManager; the method bodies are
unchanged and are recomposed into a single class in __init__.py.
"""

import psycopg2
import psycopg2.extras
import logging
from typing import Dict, List


class DocumentsMixin:
    """Uploaded media and documents attached to a property."""


    def add_property_document(self, property_id: str, doc_type: str, file_name: str, file_url: str, user_id: int, notes: str = None) -> Dict:
        """Add a media/document record for a property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            cursor.execute("SELECT image_filename FROM properties WHERE id = %s", (property_id,))
            prop = cursor.fetchone()
            if not prop:
                cursor.close()
                return {'success': False, 'error': 'Property not found'}
                
            insert_sql = """
                INSERT INTO property_documents (
                    property_id, document_type, file_name, file_url, uploaded_by, uploaded_at, notes
                ) VALUES (%s, %s, %s, %s, %s, now(), %s)
                RETURNING id
            """
            cursor.execute(insert_sql, (property_id, doc_type or 'Image', file_name, file_url, user_id, notes))
            doc_id = cursor.fetchone()['id']
            
            if doc_type == 'Image' or not doc_type or not prop.get('image_filename'):
                cursor.execute("UPDATE properties SET image_filename = %s WHERE id = %s", (file_url, property_id))
                
            cursor.close()
            return {'success': True, 'doc_id': doc_id, 'file_url': file_url, 'file_name': file_name}
            
        except Exception as e:
            logging.error(f"Error adding property document: {e}")
            return {'success': False, 'error': str(e)}

    def get_property_documents(self, property_id: str) -> List[Dict]:
        """Get all uploaded documents/media for a property."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return []
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM property_documents WHERE property_id = %s ORDER BY uploaded_at DESC", (property_id,))
            docs = cursor.fetchall()
            cursor.close()
            return [dict(d) for d in docs]
        except Exception as e:
            logging.error(f"Error fetching property documents for {property_id}: {e}")
            return []

    def delete_property_document(self, doc_id: int) -> Dict:
        """Delete a property document record."""
        if not self.connection or self.connection.closed:
            if not self.connect():
                return {'success': False, 'error': 'Database connection failed'}
                
        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("SELECT * FROM property_documents WHERE id = %s", (doc_id,))
            doc = cursor.fetchone()
            if not doc:
                cursor.close()
                return {'success': False, 'error': 'Document not found'}
                
            cursor.execute("DELETE FROM property_documents WHERE id = %s", (doc_id,))
            cursor.close()
            return {'success': True, 'document': dict(doc)}
        except Exception as e:
            logging.error(f"Error deleting property document {doc_id}: {e}")
            return {'success': False, 'error': str(e)}
