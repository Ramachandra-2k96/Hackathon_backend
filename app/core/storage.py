import shutil
import uuid
import os
from fastapi import UploadFile
from app.core.config import settings

class StorageManager:
    def __init__(self):
        self.provider = settings.STORAGE_PROVIDER
        if self.provider == "s3":
            import boto3
            # Support local S3 emulators (Localstack / GCP Storage emulators) if an ENDPOINT is provided
            endpoint = settings.AWS_ENDPOINT_URL if settings.AWS_ENDPOINT_URL else None
            self.s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            self.bucket = settings.S3_BUCKET_NAME
        else:
            self.upload_dir = "uploads"
            os.makedirs(self.upload_dir, exist_ok=True)

    def save_file(self, file: UploadFile) -> str:
        """
        Saves a FastAPI UploadFile either to Local Disk or to an S3/GCP bucket via boto3 
        depending on the .env config. Returns the final public URL/path.
        """
        ext = file.filename.split('.')[-1] if '.' in file.filename else ''
        safe_filename = f"{uuid.uuid4().hex}.{ext}" if ext else f"{uuid.uuid4().hex}"

        if self.provider == "s3":
            # boto3 S3 saving mechanism
            self.s3.upload_fileobj(
                file.file, 
                self.bucket, 
                safe_filename,
                ExtraArgs={'ContentType': file.content_type}
            )
            
            # If using a custom local endpoint (e.g. localstack) construct URL based on it
            if settings.AWS_ENDPOINT_URL:
                return f"{settings.AWS_ENDPOINT_URL}/{self.bucket}/{safe_filename}"
            # Standard AWS S3 URL Format
            return f"https://{self.bucket}.s3.{settings.AWS_REGION}.amazonaws.com/{safe_filename}"
            
        else:
            # Local Disk saving mechanism
            file_path = os.path.join(self.upload_dir, safe_filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # Return uniform local path (Assuming FastAPI mounts /uploads to serve statics)
            return f"/uploads/{safe_filename}"

# Create a singleton instance to be used across the app
storage = StorageManager()
