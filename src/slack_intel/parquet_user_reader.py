"""Read user profiles from Parquet user cache

Provides simple access to cached user profiles stored in users.parquet
"""

from pathlib import Path
from typing import Dict, Any, Optional
import pyarrow.parquet as pq


class ParquetUserReader:
    """Read cached user profiles from Parquet

    Loads user profiles from the global users.parquet cache file,
    providing a mapping of user_id to user data for mention resolution.

    Example:
        >>> reader = ParquetUserReader(base_path="cache")
        >>> users = reader.read_users()
        >>> print(users.get("U02JRGK9TCG"))
        {'user_id': 'U02JRGK9TCG', 'user_real_name': 'Alice Chen', ...}
    """

    def __init__(self, base_path: str = "cache"):
        """Initialize reader

        Args:
            base_path: Base cache directory (default: "cache")
                      Users file expected at {base_path}/users.parquet
        """
        self.base_path = Path(base_path)
        self.users_file = self.base_path / "users.parquet"

    def read_users(self) -> Dict[str, Dict[str, Any]]:
        """Read all cached users

        Returns:
            Dictionary mapping user_id to user data dict.
            Returns empty dict if cache file doesn't exist.

        Example:
            >>> reader = ParquetUserReader()
            >>> users = reader.read_users()
            >>> len(users)
            42
            >>> users['U123']['user_real_name']
            'Alice Chen'
        """
        if not self.users_file.exists():
            return {}

        try:
            # Read Parquet file
            table = pq.read_table(str(self.users_file))

            # Convert to dict of dicts
            users_dict = {}
            data = table.to_pydict()

            # Build mapping: user_id -> {user_name, user_real_name, ...}
            for i in range(len(data['user_id'])):
                user_id = data['user_id'][i]
                users_dict[user_id] = {
                    'user_id': user_id,
                    'user_name': data.get('user_name', [None] * len(data['user_id']))[i],
                    'user_real_name': data.get('user_real_name', [None] * len(data['user_id']))[i],
                    'user_email': data.get('user_email', [None] * len(data['user_id']))[i],
                    'is_bot': data.get('is_bot', [False] * len(data['user_id']))[i],
                    'cached_at': data.get('cached_at', [None] * len(data['user_id']))[i]
                }

            return users_dict

        except Exception as e:
            # Return empty dict on error, don't fail the view generation
            print(f"Warning: Could not read user cache: {e}")
            return {}

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get a single user by ID

        Args:
            user_id: Slack user ID (e.g., "U02JRGK9TCG")

        Returns:
            User data dict if found, None otherwise

        Example:
            >>> reader = ParquetUserReader()
            >>> user = reader.get_user("U123")
            >>> user['user_real_name']
            'Alice Chen'
        """
        users = self.read_users()
        return users.get(user_id)

    def cache_exists(self) -> bool:
        """Check if user cache file exists

        Returns:
            True if users.parquet exists, False otherwise
        """
        return self.users_file.exists()

    def get_cache_size(self) -> int:
        """Get size of user cache file in bytes

        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        if not self.users_file.exists():
            return 0
        return self.users_file.stat().st_size

    def get_user_count(self) -> int:
        """Get total number of cached users

        Returns:
            Number of users in cache, or 0 if cache doesn't exist
        """
        return len(self.read_users())

    def find_user_by_name(self, username: str) -> Optional[str]:
        """Find user_id by matching username (fuzzy)

        Searches for username in both user_name and user_real_name fields.
        Case-insensitive partial matching.

        Args:
            username: Username to search for (e.g., "zeebee" or "Tarun")

        Returns:
            user_id if found, None otherwise

        Example:
            >>> reader = ParquetUserReader()
            >>> reader.find_user_by_name("zeebee")
            'U02JRGK9TCG'
            >>> reader.find_user_by_name("Tarun Katial")
            'U01234ABCD'
        """
        users = self.read_users()
        username_lower = username.lower()

        # First pass: exact match on user_name
        for user_id, user_data in users.items():
            user_name = user_data.get('user_name', '')
            if user_name and user_name.lower() == username_lower:
                return user_id

        # Second pass: partial match on user_name
        for user_id, user_data in users.items():
            user_name = user_data.get('user_name', '')
            if user_name and username_lower in user_name.lower():
                return user_id

        # Third pass: partial match on user_real_name
        for user_id, user_data in users.items():
            real_name = user_data.get('user_real_name', '')
            if real_name and username_lower in real_name.lower():
                return user_id

        return None
