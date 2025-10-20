"""Reconstruct thread structure from flat Parquet message data

Converts flat message lists (where threads are indicated by flags and IDs)
into nested structures with replies grouped under parent messages.
"""

from typing import List, Dict, Any
from collections import defaultdict


class ThreadReconstructor:
    """Rebuild thread structure from flat message data

    Takes flat message list from Parquet (where thread relationship is
    indicated by thread_ts, is_thread_parent, is_thread_reply flags)
    and reconstructs nested structure with replies under parents.

    Handles:
    - Grouping replies under parents
    - Orphaned replies (parent outside dataset)
    - Clipped threads (some replies outside dataset)
    - Chronological sorting of replies

    Example:
        >>> reconstructor = ThreadReconstructor()
        >>> flat_messages = [
        ...     {"message_id": "111", "thread_ts": "111", "is_thread_parent": True, ...},
        ...     {"message_id": "112", "thread_ts": "111", "is_thread_reply": True, ...},
        ... ]
        >>> structured = reconstructor.reconstruct(flat_messages)
        >>> print(len(structured[0]["replies"]))  # 1 reply nested under parent
    """

    def reconstruct(self, flat_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reconstruct thread structure from flat message list

        Args:
            flat_messages: List of flat message dicts from Parquet

        Returns:
            List of message dicts with threads nested:
            - Standalone messages remain as-is
            - Thread parents have "replies" list added
            - Orphaned replies are marked with "is_clipped_thread" or "is_orphaned_reply"
            - All sorted chronologically

        Example:
            Input:  [parent, reply1, reply2, standalone]
            Output: [parent{replies: [reply1, reply2]}, standalone]
        """
        if not flat_messages:
            return []

        # Group messages by thread_ts
        threads: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        standalone: List[Dict[str, Any]] = []
        thread_parents: Dict[str, Dict[str, Any]] = {}

        for msg in flat_messages:
            thread_ts = msg.get("thread_ts")
            is_parent = msg.get("is_thread_parent")
            is_reply = msg.get("is_thread_reply")

            if not thread_ts:
                # Standalone message (not part of any thread)
                standalone.append(msg)
            elif is_parent:
                # Thread parent
                thread_parents[thread_ts] = msg
                threads[thread_ts].append(msg)
            elif is_reply:
                # Thread reply
                threads[thread_ts].append(msg)
            else:
                # Has thread_ts but is neither parent nor reply -> treat as standalone
                # This can happen when Slack sets thread_ts on standalone messages
                standalone.append(msg)

        # Build result list
        result = []

        # Process thread parents with their replies
        for thread_ts, messages in threads.items():
            parent = thread_parents.get(thread_ts)

            if parent:
                # Parent exists - nest replies under it
                replies = [m for m in messages if m.get("is_thread_reply")]

                # Sort replies chronologically
                replies.sort(key=lambda m: m.get("timestamp", ""))

                # Add replies to parent
                parent["replies"] = replies

                # Check if thread is clipped (expected more replies than present)
                expected_replies = parent.get("reply_count", 0)
                actual_replies = len(replies)

                if expected_replies > 0 and actual_replies == 0:
                    # Parent says it has replies, but none present
                    parent["is_clipped_thread"] = True
                    parent["has_clipped_replies"] = True
                elif expected_replies > actual_replies:
                    # Some replies missing
                    parent["has_clipped_replies"] = True

                result.append(parent)
            else:
                # Parent missing - these are orphaned replies
                orphaned_replies = [m for m in messages if m.get("is_thread_reply")]

                for reply in orphaned_replies:
                    # Mark as orphaned/clipped
                    reply["is_clipped_thread"] = True
                    reply["is_orphaned_reply"] = True
                    result.append(reply)

        # Add standalone messages
        result.extend(standalone)

        # Sort entire result chronologically by timestamp
        result.sort(key=lambda m: m.get("timestamp", ""))

        return result
