"""
S3-compatible storage uploader (MinIO, AWS S3, etc.)
"""

import os
import asyncio
from typing import Optional, List
import boto3
from botocore.exceptions import ClientError
from src.config import settings


class StorageUploader:
    """Upload files to S3-compatible storage (MinIO, AWS S3, etc.)"""

    def __init__(self):
        self.s3_region = settings.s3_region
        self.s3_endpoint = settings.s3_endpoint
        self.s3_bucket = settings.s3_bucket
        self.s3_access_key = settings.s3_access_key
        self.s3_secret_key = settings.s3_secret_key
        self.s3_public_url = settings.s3_public_url
        self.export_dir = settings.export_dir

        # Initialize boto3 S3 client for S3-compatible storage
        # Works with MinIO, AWS S3, or any S3-compatible service
        self.s3_client = boto3.client(
            "s3",
            region_name=self.s3_region,
            endpoint_url=self.s3_endpoint,
            aws_access_key_id=self.s3_access_key,
            aws_secret_access_key=self.s3_secret_key,
        )

        # Check if bucket exists and create if needed
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Ensure the bucket exists, create if it doesn't"""
        try:
            self.s3_client.head_bucket(Bucket=self.s3_bucket)
            print(f"Using existing bucket: {self.s3_bucket}")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "404":
                # Bucket doesn't exist, create it
                try:
                    print(f"Creating bucket: {self.s3_bucket}")
                    self.s3_client.create_bucket(Bucket=self.s3_bucket)
                    # Set bucket policy to public read
                    self._set_public_read_policy()
                    print(f"✓ Bucket created: {self.s3_bucket}")
                except Exception as create_error:
                    print(f"Warning: Could not create bucket: {create_error}")
            else:
                print(f"Warning: Could not check bucket: {e}")

    def _set_public_read_policy(self):
        """Set bucket policy to allow public read access"""
        try:
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "PublicRead",
                        "Effect": "Allow",
                        "Principal": "*",
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.s3_bucket}/*"],
                    }
                ],
            }
            import json
            self.s3_client.put_bucket_policy(
                Bucket=self.s3_bucket, Policy=json.dumps(policy)
            )
            print("✓ Bucket policy set to public read")
        except Exception as e:
            print(f"Warning: Could not set bucket policy: {e}")

    async def upload_file(
        self, local_path: str, remote_path: Optional[str] = None
    ) -> bool:
        """Upload a file to S3-compatible storage"""

        if not os.path.exists(local_path):
            print(f"File not found: {local_path}")
            return False

        if remote_path is None:
            remote_path = os.path.basename(local_path)

        print(f"Uploading {local_path} to {remote_path}...")

        try:
            # Determine content type
            if local_path.endswith(".json"):
                content_type = "application/json"
            else:
                content_type = "application/octet-stream"

            # Upload to S3-compatible storage
            # Run the synchronous boto3 upload in a thread pool
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.upload_file(
                    local_path,
                    self.s3_bucket,
                    remote_path,
                    ExtraArgs={
                        "ContentType": content_type,
                        "ACL": "public-read",  # Make file publicly accessible
                        "CacheControl": "public, max-age=3600",  # 1 hour cache
                    },
                ),
            )

            # Generate public URL
            public_url = self.get_public_url(remote_path)
            print("  ✓ Uploaded successfully")
            print(f"  URL: {public_url}")
            return True

        except ClientError as e:
            print(f"  ✗ Upload failed: {e}")
            return False
        except Exception as e:
            print(f"  ✗ Error uploading file: {e}")
            return False

    async def upload_exports(self, export_dir: Optional[str] = None) -> int:
        """Upload all JSON files from export directory"""
        if export_dir is None:
            export_dir = self.export_dir

        if not os.path.exists(export_dir):
            print(f"Export directory not found: {export_dir}")
            return 0

        print("\n" + "=" * 60)
        print(f"Uploading exports to S3 storage ({self.s3_endpoint})...")
        print("=" * 60 + "\n")

        uploaded_count = 0
        json_files = [f for f in os.listdir(export_dir) if f.endswith(".json")]

        if not json_files:
            print("No JSON files found to upload")
            return 0

        for filename in json_files:
            local_path = os.path.join(export_dir, filename)
            remote_path = filename  # Store in bucket root

            if await self.upload_file(local_path, remote_path):
                uploaded_count += 1

            # Small delay between uploads
            await asyncio.sleep(0.5)

        print("\n" + "=" * 60)
        msg = f"Uploaded {uploaded_count}/{len(json_files)} files"
        print(f"{msg} to S3 storage")
        print("=" * 60 + "\n")

        return uploaded_count

    async def list_files(self) -> List[str]:
        """List files in S3-compatible storage bucket"""
        try:
            # Run the synchronous boto3 list in a thread pool
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.list_objects_v2(Bucket=self.s3_bucket),
            )

            if "Contents" in response:
                return [obj["Key"] for obj in response["Contents"]]
            else:
                return []

        except ClientError as e:
            print(f"Error listing files: {e}")
            return []
        except Exception as e:
            print(f"Error listing files: {e}")
            return []

    async def delete_file(self, remote_path: str) -> bool:
        """Delete a file from S3-compatible storage"""
        try:
            # Run the synchronous boto3 delete in a thread pool
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.s3_client.delete_object(
                    Bucket=self.s3_bucket, Key=remote_path
                ),
            )

            print(f"Deleted: {remote_path}")
            return True

        except ClientError as e:
            print(f"Error deleting {remote_path}: {e}")
            return False
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False

    def get_public_url(self, remote_path: str) -> str:
        """Get the public URL for a file in S3-compatible storage"""
        # If a custom public URL is configured, use it (e.g., CDN)
        if self.s3_public_url:
            base_url = self.s3_public_url.rstrip("/")
            return f"{base_url}/{remote_path}"

        # Default: endpoint/bucket/key format (works with MinIO)
        # Format: http://localhost:9000/{bucket}/{key}
        endpoint = self.s3_endpoint.rstrip("/")
        return f"{endpoint}/{self.s3_bucket}/{remote_path}"
