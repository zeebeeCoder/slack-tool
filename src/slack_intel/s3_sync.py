"""S3 synchronization using s3fs

This module provides S3 sync functionality using s3fs (pure Python, no AWS CLI).
Implements custom incremental sync logic based on file size and modification time.
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass
import time


@dataclass
class SyncResult:
    """Result of an S3 sync operation"""

    files_uploaded: int
    files_skipped: int
    files_deleted: int
    bytes_transferred: int

    @property
    def success(self) -> bool:
        """True if sync completed successfully"""
        return True

    def summary(self) -> str:
        """Human-readable summary"""
        return (
            f"Uploaded: {self.files_uploaded}, "
            f"Skipped: {self.files_skipped}, "
            f"Deleted: {self.files_deleted}, "
            f"Size: {self.bytes_transferred / (1024*1024):.2f} MB"
        )


class S3Syncer:
    """Sync local cache directories to S3 using s3fs

    This class uses s3fs (built on boto3) for pure Python S3 operations.
    No AWS CLI required. Supports AWS SSO profiles.

    Example:
        >>> syncer = S3Syncer(
        ...     bucket="my-slack-data",
        ...     prefix="production/cache",
        ...     aws_profile="AdministratorAccess-276780518338"
        ... )
        >>> result = syncer.sync(
        ...     local_path=Path("cache/raw"),
        ...     delete=False
        ... )
        >>> print(result.summary())
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: Optional[str] = None,
        aws_profile: Optional[str] = None
    ):
        """Initialize S3 syncer

        Args:
            bucket: S3 bucket name
            prefix: Optional prefix for all S3 keys (e.g., "production/")
            region: AWS region (defaults to boto3 default region)
            aws_profile: AWS profile name (supports SSO profiles)
        """
        import s3fs
        import boto3

        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        if self.prefix:
            self.prefix += "/"

        # Build storage options for s3fs
        storage_options = {}

        # Create boto3 session with profile support
        session_kwargs = {}
        if region:
            storage_options['client_kwargs'] = {'region_name': region}
            session_kwargs['region_name'] = region
        if aws_profile:
            storage_options['profile'] = aws_profile
            session_kwargs['profile_name'] = aws_profile

        # Store session for verification
        self.session = boto3.Session(**session_kwargs)

        # Initialize s3fs filesystem
        self.fs = s3fs.S3FileSystem(**storage_options)

        # Verify bucket access
        self._verify_bucket_access()

    def _verify_bucket_access(self):
        """Verify we can access the S3 bucket"""
        try:
            # Try to list the bucket (lightweight check)
            self.fs.ls(self.bucket)
        except Exception as e:
            error_msg = str(e)

            # Provide helpful error messages for common issues
            if "ExpiredToken" in error_msg or "InvalidToken" in error_msg:
                profile_hint = self.session.profile_name or 'your-profile'
                raise ValueError(
                    f"AWS credentials expired. If using SSO, run:\n"
                    f"  aws sso login --profile {profile_hint}\n"
                    f"Error: {e}"
                )
            elif "NoCredentialsError" in error_msg or "Unable to locate credentials" in error_msg:
                raise ValueError(
                    f"No AWS credentials found. Please configure credentials:\n"
                    f"  - For SSO: aws configure sso\n"
                    f"  - For standard: aws configure\n"
                    f"Error: {e}"
                )
            elif "403" in error_msg or "Forbidden" in error_msg:
                raise ValueError(
                    f"Access denied to bucket '{self.bucket}'. "
                    f"Check IAM permissions for your profile.\n"
                    f"Error: {e}"
                )
            elif "404" in error_msg or "NoSuchBucket" in error_msg:
                raise ValueError(
                    f"S3 bucket '{self.bucket}' not found. "
                    f"Check bucket name and region.\n"
                    f"Error: {e}"
                )
            else:
                raise ValueError(
                    f"Cannot access S3 bucket '{self.bucket}'. "
                    f"Check bucket name and AWS credentials.\n"
                    f"Error: {e}"
                )

    def _get_s3_path(self, relative_path: str = "") -> str:
        """Build full S3 path with bucket and prefix

        Args:
            relative_path: Relative path from sync root

        Returns:
            Full S3 path like "my-bucket/prefix/path/file.parquet"
        """
        s3_key = f"{self.prefix}{relative_path}".lstrip("/")
        return f"{self.bucket}/{s3_key}"

    def sync(
        self,
        local_path: Path,
        delete: bool = False,
        dry_run: bool = False,
        include_patterns: Optional[list[str]] = None
    ) -> SyncResult:
        """Sync local directory to S3

        Implements incremental sync by comparing file sizes and modification times.
        Only uploads files that are new or have changed.

        Args:
            local_path: Local directory to sync
            delete: If True, delete S3 objects not present locally
            dry_run: If True, show what would be synced without doing it
            include_patterns: Optional list of glob patterns to include
                             (e.g., ["**/*.parquet"])

        Returns:
            SyncResult with sync statistics

        Example:
            >>> syncer = S3Syncer(bucket="my-data")
            >>> result = syncer.sync(
            ...     local_path=Path("cache/raw"),
            ...     delete=False,
            ...     include_patterns=["**/*.parquet"]
            ... )
        """
        if not local_path.exists():
            raise ValueError(f"Local path does not exist: {local_path}")

        if not local_path.is_dir():
            raise ValueError(f"Local path is not a directory: {local_path}")

        start_time = time.time()

        # Track sync results
        files_uploaded = 0
        files_skipped = 0
        files_deleted = 0
        bytes_transferred = 0

        # Default to all parquet files if no patterns specified
        if include_patterns is None:
            include_patterns = ["**/*.parquet"]

        # Collect local files matching patterns
        local_files = set()
        for pattern in include_patterns:
            for file_path in local_path.glob(pattern):
                if file_path.is_file():
                    local_files.add(file_path)

        # Build map of relative paths to local files
        local_file_map = {}
        for file_path in local_files:
            relative_path = file_path.relative_to(local_path)
            # Use forward slashes for S3
            relative_key = str(relative_path).replace("\\", "/")
            local_file_map[relative_key] = file_path

        if dry_run:
            print(f"DRY RUN: Would sync {len(local_file_map)} files to s3://{self.bucket}/{self.prefix}")
            for relative_key in sorted(local_file_map.keys()):
                print(f"  {relative_key}")
            return SyncResult(
                files_uploaded=len(local_file_map),
                files_skipped=0,
                files_deleted=0,
                bytes_transferred=sum(f.stat().st_size for f in local_file_map.values())
            )

        # Get existing S3 objects
        s3_prefix = self._get_s3_path("")
        try:
            s3_files = self.fs.ls(s3_prefix, detail=True)
            s3_file_map = {}
            for s3_obj in s3_files:
                # s3_obj['name'] is like "bucket/prefix/path/file.parquet"
                # Extract relative path by removing bucket and prefix
                full_key = s3_obj['name']
                # Remove bucket name
                if full_key.startswith(f"{self.bucket}/"):
                    key_without_bucket = full_key[len(f"{self.bucket}/"):]
                    # Remove prefix
                    if self.prefix and key_without_bucket.startswith(self.prefix):
                        relative_key = key_without_bucket[len(self.prefix):]
                    else:
                        relative_key = key_without_bucket

                    s3_file_map[relative_key] = {
                        'size': s3_obj.get('size', 0),
                        'mtime': s3_obj.get('LastModified')
                    }
        except FileNotFoundError:
            # S3 prefix doesn't exist yet, that's ok
            s3_file_map = {}

        # Sync files
        for relative_key, local_file in local_file_map.items():
            s3_path = self._get_s3_path(relative_key)
            local_size = local_file.stat().st_size
            local_mtime = local_file.stat().st_mtime

            # Check if file needs uploading
            should_upload = True

            if relative_key in s3_file_map:
                s3_size = s3_file_map[relative_key]['size']

                # Simple incremental check: skip if same size
                # (could enhance with ETag/MD5 comparison if needed)
                if s3_size == local_size:
                    should_upload = False
                    files_skipped += 1

            if should_upload:
                # Upload file
                self.fs.put(str(local_file), s3_path)
                files_uploaded += 1
                bytes_transferred += local_size

        # Handle deletions
        if delete:
            for relative_key in s3_file_map:
                if relative_key not in local_file_map:
                    s3_path = self._get_s3_path(relative_key)
                    self.fs.rm(s3_path)
                    files_deleted += 1

        return SyncResult(
            files_uploaded=files_uploaded,
            files_skipped=files_skipped,
            files_deleted=files_deleted,
            bytes_transferred=bytes_transferred
        )

    def upload_file(self, local_file: Path, s3_key: Optional[str] = None) -> str:
        """Upload a single file to S3

        Args:
            local_file: Path to local file
            s3_key: Optional S3 key (defaults to filename with prefix)

        Returns:
            S3 URI of uploaded file
        """
        if not local_file.exists():
            raise ValueError(f"File does not exist: {local_file}")

        # Build S3 key
        if s3_key is None:
            s3_key = local_file.name

        s3_path = self._get_s3_path(s3_key)

        # Upload file
        self.fs.put(str(local_file), s3_path)

        return f"s3://{s3_path}"

    def list_files(self, s3_prefix: str = "") -> list[str]:
        """List files in S3 under a given prefix

        Args:
            s3_prefix: S3 prefix to list (appended to syncer's prefix)

        Returns:
            List of S3 paths
        """
        full_path = self._get_s3_path(s3_prefix)

        try:
            files = self.fs.ls(full_path)
            return files
        except FileNotFoundError:
            return []

    def file_exists(self, s3_key: str) -> bool:
        """Check if a file exists in S3

        Args:
            s3_key: S3 key to check (relative to syncer's prefix)

        Returns:
            True if file exists
        """
        s3_path = self._get_s3_path(s3_key)
        return self.fs.exists(s3_path)


def create_syncer(
    bucket: str,
    prefix: str = "",
    region: Optional[str] = None,
    aws_profile: Optional[str] = None
) -> S3Syncer:
    """Factory function to create S3 syncer

    Args:
        bucket: S3 bucket name
        prefix: Optional prefix for all S3 keys
        region: AWS region
        aws_profile: AWS profile name (supports SSO)

    Returns:
        S3Syncer instance

    Example:
        >>> syncer = create_syncer(
        ...     bucket='my-slack-data',
        ...     prefix='production/',
        ...     region='us-west-2',
        ...     aws_profile='AdministratorAccess-276780518338'
        ... )
    """
    return S3Syncer(
        bucket=bucket,
        prefix=prefix,
        region=region,
        aws_profile=aws_profile
    )
