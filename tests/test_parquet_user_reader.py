"""Tests for ParquetUserReader

Tests user cache reading functionality.
"""

import pytest
import tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from src.slack_intel.parquet_user_reader import ParquetUserReader


class TestParquetUserReader:
    """Test ParquetUserReader basic functionality"""

    def test_read_users_returns_empty_dict_when_cache_missing(self):
        """Test that read_users returns empty dict when cache file doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = ParquetUserReader(base_path=tmpdir)
            users = reader.read_users()

            assert users == {}
            assert isinstance(users, dict)

    def test_read_users_loads_cached_users(self):
        """Test that read_users successfully loads users from cache file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock users.parquet file
            users_data = [
                {
                    'user_id': 'U001',
                    'user_name': 'alice',
                    'user_real_name': 'Alice Chen',
                    'user_email': 'alice@example.com',
                    'is_bot': False,
                    'cached_at': '2025-10-20T10:00:00'
                },
                {
                    'user_id': 'U002',
                    'user_name': 'bob',
                    'user_real_name': 'Bob Smith',
                    'user_email': 'bob@example.com',
                    'is_bot': False,
                    'cached_at': '2025-10-20T10:00:00'
                }
            ]

            table = pa.Table.from_pylist(users_data)
            users_path = Path(tmpdir) / 'users.parquet'
            pq.write_table(table, str(users_path))

            # Read users
            reader = ParquetUserReader(base_path=tmpdir)
            users = reader.read_users()

            # Verify
            assert len(users) == 2
            assert 'U001' in users
            assert 'U002' in users
            assert users['U001']['user_real_name'] == 'Alice Chen'
            assert users['U002']['user_real_name'] == 'Bob Smith'
            assert users['U001']['user_email'] == 'alice@example.com'

    def test_get_user_returns_user_data(self):
        """Test get_user returns correct user data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache
            users_data = [
                {
                    'user_id': 'U001',
                    'user_name': 'alice',
                    'user_real_name': 'Alice Chen',
                    'user_email': 'alice@example.com',
                    'is_bot': False,
                    'cached_at': '2025-10-20T10:00:00'
                }
            ]

            table = pa.Table.from_pylist(users_data)
            users_path = Path(tmpdir) / 'users.parquet'
            pq.write_table(table, str(users_path))

            # Get user
            reader = ParquetUserReader(base_path=tmpdir)
            user = reader.get_user('U001')

            assert user is not None
            assert user['user_id'] == 'U001'
            assert user['user_real_name'] == 'Alice Chen'

    def test_get_user_returns_none_for_missing_user(self):
        """Test get_user returns None for non-existent user"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache with one user
            users_data = [
                {
                    'user_id': 'U001',
                    'user_name': 'alice',
                    'user_real_name': 'Alice Chen',
                    'user_email': None,
                    'is_bot': False,
                    'cached_at': '2025-10-20T10:00:00'
                }
            ]

            table = pa.Table.from_pylist(users_data)
            users_path = Path(tmpdir) / 'users.parquet'
            pq.write_table(table, str(users_path))

            # Try to get non-existent user
            reader = ParquetUserReader(base_path=tmpdir)
            user = reader.get_user('U999')

            assert user is None

    def test_cache_exists_returns_true_when_file_exists(self):
        """Test cache_exists returns True when cache file exists"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create empty cache file
            users_path = Path(tmpdir) / 'users.parquet'
            users_path.touch()

            reader = ParquetUserReader(base_path=tmpdir)
            assert reader.cache_exists() is True

    def test_cache_exists_returns_false_when_file_missing(self):
        """Test cache_exists returns False when cache file doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = ParquetUserReader(base_path=tmpdir)
            assert reader.cache_exists() is False

    def test_get_user_count_returns_correct_count(self):
        """Test get_user_count returns correct number of users"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache with 3 users
            users_data = [
                {'user_id': 'U001', 'user_name': 'alice', 'user_real_name': 'Alice', 'user_email': None, 'is_bot': False, 'cached_at': '2025-10-20T10:00:00'},
                {'user_id': 'U002', 'user_name': 'bob', 'user_real_name': 'Bob', 'user_email': None, 'is_bot': False, 'cached_at': '2025-10-20T10:00:00'},
                {'user_id': 'U003', 'user_name': 'carol', 'user_real_name': 'Carol', 'user_email': None, 'is_bot': False, 'cached_at': '2025-10-20T10:00:00'}
            ]

            table = pa.Table.from_pylist(users_data)
            users_path = Path(tmpdir) / 'users.parquet'
            pq.write_table(table, str(users_path))

            reader = ParquetUserReader(base_path=tmpdir)
            assert reader.get_user_count() == 3

    def test_get_user_count_returns_zero_for_missing_cache(self):
        """Test get_user_count returns 0 when cache doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = ParquetUserReader(base_path=tmpdir)
            assert reader.get_user_count() == 0

    def test_read_users_handles_malformed_cache_gracefully(self):
        """Test that read_users returns empty dict on error"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a malformed file
            users_path = Path(tmpdir) / 'users.parquet'
            users_path.write_text("not a parquet file")

            reader = ParquetUserReader(base_path=tmpdir)
            users = reader.read_users()

            # Should return empty dict, not crash
            assert users == {}

    def test_read_users_handles_missing_columns(self):
        """Test read_users handles cache files with missing optional columns"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create cache with only required fields
            users_data = [
                {'user_id': 'U001'}
            ]

            table = pa.Table.from_pylist(users_data)
            users_path = Path(tmpdir) / 'users.parquet'
            pq.write_table(table, str(users_path))

            reader = ParquetUserReader(base_path=tmpdir)
            users = reader.read_users()

            # Should still work, with None for missing fields
            assert len(users) == 1
            assert users['U001']['user_id'] == 'U001'
            assert users['U001']['user_name'] is None
            assert users['U001']['user_real_name'] is None
