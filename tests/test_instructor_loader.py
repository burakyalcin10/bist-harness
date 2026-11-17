"""The instructor's scripts are not distributed with the repository."""

import pytest

from . import instructor


def test_a_parity_test_is_skipped_when_the_instructor_script_is_absent(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="reference/instructor"):
        instructor._load("absent_script", tmp_path / "absent_script.py")
