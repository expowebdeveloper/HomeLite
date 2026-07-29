import boto3
from typing import Optional
import logging
import io
from config import Config

class S3Manager:
    def __init__(self):
        self.config = Config()
        self.s3_client = None
        self._initialize_s3_client()
    
    def _initialize_s3_client(self):
        """Initialize S3 client with AWS credentials"""
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=self.config.AWS_SECRET_ACCESS_KEY,
                region_name=self.config.AWS_REGION
            )
            logging.info("S3 client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize S3 client: {e}")
            self.s3_client = None
    
    def download_image_data(self, image_filename: str, source: str = None) -> Optional[bytes]:
        """
        Download raw image data from S3
        
        Args:
            image_filename: Filename of the image
            source: Source name (scraper name) for constructing S3 key
            
        Returns:
            bytes of image data or None if failed
        """
        if not self.s3_client:
            logging.error("S3 client not initialized")
            return None
        
        # Construct S3 key based on EstateHarvester structure
        if source:
            s3_key = f"properties/{source}/{image_filename}"
        else:
            # Fallback: try to extract source from filename or use direct filename
            s3_key = image_filename
        
        try:
            # Download image from S3
            response = self.s3_client.get_object(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=s3_key
            )
            
            # Read image data
            image_data = response['Body'].read()
            return image_data
            
        except Exception as e:
            logging.error(f"Error downloading image {s3_key}: {e}")
            return None
    
    def get_image_url(self, image_key: str) -> str:
        """Generate a presigned URL for the image"""
        if not self.s3_client:
            return ""
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.config.S3_BUCKET_NAME,
                    'Key': image_key
                },
                ExpiresIn=3600  # URL expires in 1 hour
            )
            return url
        except Exception as e:
            logging.error(f"Error generating presigned URL for {image_key}: {e}")
            return ""
    
    def upload_image(self, file_path: str, image_key: str) -> bool:
        """
        Upload image to S3
        
        Args:
            file_path: Local path to the image file
            image_key: S3 key for the image
            
        Returns:
            True if successful, False otherwise
        """
        if not self.s3_client:
            return False
        
        try:
            self.s3_client.upload_file(
                file_path,
                self.config.S3_BUCKET_NAME,
                image_key
            )
            logging.info(f"Image uploaded successfully: {image_key}")
            return True
        except Exception as e:
            logging.error(f"Error uploading image {image_key}: {e}")
            return False
            
    def upload_file_object(self, file_obj, image_key: str, content_type: str = None) -> bool:
        """Upload file-like object (e.g. Flask FileStorage) to S3"""
        if not self.s3_client:
            return False
        try:
            extra_args = {'ContentType': content_type} if content_type else {}
            self.s3_client.upload_fileobj(
                file_obj,
                self.config.S3_BUCKET_NAME,
                image_key,
                ExtraArgs=extra_args
            )
            logging.info(f"File object uploaded successfully: {image_key}")
            return True
        except Exception as e:
            logging.error(f"Error uploading file object {image_key}: {e}")
            return False
    
    def delete_image(self, image_key: str) -> bool:
        """
        Delete image from S3
        
        Args:
            image_key: S3 key of the image to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self.s3_client:
            return False
        
        try:
            self.s3_client.delete_object(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=image_key
            )
            logging.info(f"Image deleted successfully: {image_key}")
            return True
        except Exception as e:
            logging.error(f"Error deleting image {image_key}: {e}")
            return False
