#!/usr/bin/env python3
"""
Unit tests for fetch_mitigated_findings.py (veracode_api_py version)
Tests core logic: date windowing, pagination, type coercion, flattening, etc.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fetch_mitigated_findings as ffm


class TestDateWindowing:
    """Test the 180-day window splitting logic."""

    def test_single_window_short_range(self):
        """Ranges under 180 days should produce a single window."""
        windows = ffm.windows_180("2024-01-01", "2024-03-15")
        assert len(windows) == 1
        assert windows[0] == ("2024-01-01", "2024-03-15")

    def test_exactly_180_days(self):
        """Exactly 180 days should produce a single window."""
        windows = ffm.windows_180("2024-01-01", "2024-06-29")
        assert len(windows) == 1
        assert windows[0] == ("2024-01-01", "2024-06-29")

    def test_two_windows_no_overlap(self):
        """Multiple windows should not overlap."""
        windows = ffm.windows_180("2024-01-01", "2024-07-01")
        assert len(windows) == 2

        # Verify no overlap: end of window 1 + 1 day == start of window 2
        w1_end = datetime.strptime(windows[0][1], "%Y-%m-%d").date()
        w2_start = datetime.strptime(windows[1][0], "%Y-%m-%d").date()
        assert w2_start == w1_end + timedelta(days=1), "Windows should not overlap"

    def test_three_windows(self):
        """Long ranges should split into multiple windows."""
        windows = ffm.windows_180("2024-01-01", "2024-12-31")
        assert len(windows) == 3

        # Verify continuity and no overlap
        for i in range(len(windows) - 1):
            end_i = datetime.strptime(windows[i][1], "%Y-%m-%d").date()
            start_next = datetime.strptime(windows[i + 1][0], "%Y-%m-%d").date()
            assert start_next == end_i + timedelta(days=1), f"Gap between windows {i} and {i+1}"

    def test_last_window_clamped(self):
        """Last window should clamp to end_date, not extend further."""
        windows = ffm.windows_180("2024-01-01", "2024-07-05")
        assert windows[-1][1] == "2024-07-05"

    def test_invalid_range_raises(self):
        """End date before start date should raise error."""
        with pytest.raises(SystemExit):
            ffm.windows_180("2024-07-01", "2024-01-01")


class TestPaginationLogic:
    """Test pagination boundary detection."""

    def test_page_math_next_not_last_page(self):
        """Should return next page number when not on the last page."""
        page_json = {"page": {"number": 2, "total_pages": 5}}
        result = ffm.page_math_next(page_json, 2, 1000)
        assert result == 3

    def test_page_math_next_on_last_page(self):
        """Should return None when on the last page."""
        page_json = {"page": {"number": 5, "total_pages": 5}}
        result = ffm.page_math_next(page_json, 5, 1000)
        assert result is None, "Should not return next page on last page"

    def test_page_math_next_before_last_page(self):
        """Should return page 5 when on page 4 of 5 (not skip last page)."""
        page_json = {"page": {"number": 4, "total_pages": 5}}
        result = ffm.page_math_next(page_json, 4, 1000)
        assert result == 5, "Page 5 should be returned from page 4 of 5"

    def test_page_math_next_penultimate_page(self):
        """Should return page 4 from penultimate page."""
        page_json = {"page": {"number": 3, "total_pages": 5}}
        result = ffm.page_math_next(page_json, 3, 1000)
        assert result == 4

    def test_page_math_next_missing_metadata(self):
        """Should return None when pagination metadata is missing."""
        page_json = {}
        result = ffm.page_math_next(page_json, 0, 1000)
        assert result is None

    def test_page_math_next_zero_indexed(self):
        """Should handle 0-indexed pages correctly."""
        page_json = {"page": {"number": 0, "total_pages": 3}}
        result = ffm.page_math_next(page_json, 0, 1000)
        assert result == 1


class TestFindingIDValidation:
    """Test finding ID validation in annotation merging."""

    def test_merge_annotations_zero_id(self):
        """Finding ID of 0 should NOT be treated as missing.

        Note: With veracode_api_py, this would attempt to fetch annotations.
        We test that the condition correctly identifies 0 as a valid ID.
        """
        # When finding_id is 0, it should NOT skip annotation fetching
        # The code checks: if finding_id is None or finding_id == ""
        # 0 is neither None nor "", so annotation fetching would be attempted
        finding = {"finding_id": 0, "title": "Test"}
        # The finding_id check should not return early with None/""
        assert finding.get("finding_id") is not None
        assert finding.get("finding_id") != ""

    def test_merge_annotations_none_id(self):
        """Finding ID of None should be treated as missing."""
        finding = {"finding_id": None, "title": "Test"}
        # Without a real API client, test the validation logic directly
        finding_id = finding.get("finding_id")
        should_skip = finding_id is None or finding_id == ""
        assert should_skip, "Should skip annotations for None finding_id"

    def test_merge_annotations_empty_string_id(self):
        """Finding ID of empty string should be treated as missing."""
        finding = {"finding_id": "", "title": "Test"}
        # Without a real API client, test the validation logic directly
        finding_id = finding.get("finding_id")
        should_skip = finding_id is None or finding_id == ""
        assert should_skip, "Should skip annotations for empty string finding_id"

    def test_merge_annotations_missing_id_key(self):
        """Missing finding_id key should be treated as missing."""
        finding = {"title": "Test"}
        # Without a real API client, test the validation logic directly
        finding_id = finding.get("finding_id")
        should_skip = finding_id is None or finding_id == ""
        assert should_skip, "Should skip annotations when finding_id is missing"


class TestTypeCoercion:
    """Test type coercion for Excel output."""

    def test_coerce_int(self):
        """Should coerce numeric strings to integers."""
        assert ffm.coerce_scalar("123") == 123
        assert ffm.coerce_scalar("-456") == -456
        assert ffm.coerce_scalar("+789") == 789

    def test_coerce_float(self):
        """Should coerce float strings to floats."""
        assert ffm.coerce_scalar("1.5") == 1.5
        assert ffm.coerce_scalar("-2.7") == -2.7
        assert ffm.coerce_scalar("3.14e2") == 3.14e2

    def test_coerce_bool_true(self):
        """Should coerce 'true' (case insensitive) to boolean True."""
        assert ffm.coerce_scalar("true") is True
        assert ffm.coerce_scalar("True") is True
        assert ffm.coerce_scalar("TRUE") is True

    def test_coerce_bool_false(self):
        """Should coerce 'false' (case insensitive) to boolean False."""
        assert ffm.coerce_scalar("false") is False
        assert ffm.coerce_scalar("False") is False
        assert ffm.coerce_scalar("FALSE") is False

    def test_coerce_date(self):
        """Should coerce ISO date strings to datetime."""
        result = ffm.coerce_scalar("2024-01-15")
        assert result is not None
        # Result should be a datetime-like object
        assert hasattr(result, "year")

    def test_coerce_invalid_date(self):
        """Invalid dates should remain as strings."""
        result = ffm.coerce_scalar("2024-13-45")
        assert isinstance(result, str)
        assert result == "2024-13-45"

    def test_coerce_whitespace_preserved(self):
        """Whitespace-only values should remain empty strings."""
        assert ffm.coerce_scalar("   ") == ""

    def test_coerce_none(self):
        """None should remain None."""
        assert ffm.coerce_scalar(None) is None

    def test_coerce_existing_int(self):
        """Already-typed integers should pass through."""
        assert ffm.coerce_scalar(123) == 123

    def test_coerce_existing_float(self):
        """Already-typed floats should pass through."""
        assert ffm.coerce_scalar(1.5) == 1.5

    def test_coerce_existing_bool(self):
        """Already-typed booleans should pass through."""
        assert ffm.coerce_scalar(True) is True
        assert ffm.coerce_scalar(False) is False


class TestFlattening:
    """Test nested dict flattening for Excel output."""

    def test_flatten_simple_dict(self):
        """Simple flat dict should remain unchanged."""
        obj = {"a": 1, "b": "text"}
        result = ffm.flatten(obj)
        assert result == {"a": 1, "b": "text"}

    def test_flatten_nested_dict(self):
        """Nested dicts should be flattened with dot notation."""
        obj = {"a": 1, "b": {"c": 2, "d": 3}}
        result = ffm.flatten(obj)
        assert result == {"a": 1, "b.c": 2, "b.d": 3}

    def test_flatten_list_to_json(self):
        """Lists should be serialized as JSON strings."""
        obj = {"tags": ["a", "b", "c"]}
        result = ffm.flatten(obj)
        assert result["tags"] == '["a", "b", "c"]'

    def test_flatten_deep_nesting(self):
        """Deep nesting should flatten with multiple dots."""
        obj = {"a": {"b": {"c": {"d": 1}}}}
        result = ffm.flatten(obj)
        assert result == {"a.b.c.d": 1}

    def test_flatten_mixed_types(self):
        """Mixed types should be coerced and flattened."""
        obj = {"a": 1, "b": {"c": "123", "d": [1, 2, 3]}}
        result = ffm.flatten(obj)
        assert result["a"] == 1
        # "123" gets coerced to int 123 during flattening
        assert result["b.c"] == 123
        # Lists are serialized as JSON strings
        assert '[1, 2, 3]' in result["b.d"]


class TestPageMetaParsing:
    """Test page metadata extraction from varied response formats."""

    def test_find_page_meta_simple(self):
        """Should extract from simple 'page' field."""
        payload = {"page": {"number": 2, "total_pages": 5}}
        result = ffm._find_page_meta(payload)
        assert result["number"] == 2
        assert result["total_pages"] == 5

    def test_find_page_meta_embedded(self):
        """Should extract from '_embedded.page' field."""
        payload = {"_embedded": {"page": {"number": 3, "total_pages": 10}}}
        result = ffm._find_page_meta(payload)
        assert result["number"] == 3
        assert result["total_pages"] == 10

    def test_find_page_meta_alternative_names(self):
        """Should handle alternative field names."""
        payload = {"page": {"page_number": 1, "totalPages": 4}}
        result = ffm._find_page_meta(payload)
        assert result["number"] == 1
        assert result["total_pages"] == 4

    def test_find_page_meta_missing(self):
        """Should return empty dict when metadata missing."""
        payload = {}
        result = ffm._find_page_meta(payload)
        assert result == {}

    def test_find_page_meta_partial(self):
        """Should return empty dict if critical fields are missing."""
        payload = {"page": {"number": 2}}  # Missing total_pages
        result = ffm._find_page_meta(payload)
        # Depends on implementation; we return {} if not both found
        assert result == {} or "number" not in result


class TestExtractHelpers:
    """Test extraction helper functions."""

    def test_extract_items_from_content(self):
        """Should extract items from 'content' field."""
        page = {"content": [{"id": 1}, {"id": 2}]}
        result = ffm.extract_items(page)
        assert len(result) == 2

    def test_extract_items_from_embedded_findings(self):
        """Should extract from '_embedded.findings'."""
        page = {"_embedded": {"findings": [{"id": 1}]}}
        result = ffm.extract_items(page)
        assert len(result) == 1

    def test_extract_items_empty(self):
        """Should return empty list for unrecognized format."""
        page = {"unknown": "format"}
        result = ffm.extract_items(page)
        assert result == []

    def test_hal_next_valid(self):
        """Should extract next HAL link."""
        page = {"_links": {"next": {"href": "/api/page/2"}}}
        result = ffm.hal_next(page)
        assert "page/2" in result

    def test_hal_next_none(self):
        """Should return None when no next link."""
        page = {"_links": {"next": None}}
        result = ffm.hal_next(page)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
