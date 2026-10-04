"""Windows-specific cloud placeholder safety checks."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from on1y.folder_sync.files import available


def file_with_attributes(**attributes: int) -> Mock:
    path = Mock(spec=Path)
    path.is_file.return_value = True
    path.stat.return_value = SimpleNamespace(**attributes)
    return path


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param(0x1000, id="offline"),
        pytest.param(0x40000, id="recall-on-open"),
        pytest.param(0x400000, id="recall-on-data-access"),
        pytest.param(0x1000 | 0x40000 | 0x400000, id="combined"),
    ],
)
def test_windows_cloud_placeholders_are_unavailable(attributes: int) -> None:
    path = file_with_attributes(st_file_attributes=attributes)

    assert not available(path)


def test_materialized_windows_cloud_file_is_available() -> None:
    path = file_with_attributes(st_file_attributes=0x400)

    assert available(path)


def test_macos_dataless_file_remains_unavailable() -> None:
    path = file_with_attributes(st_flags=0x40000000)

    assert not available(path)


def test_regular_file_without_platform_attributes_is_available() -> None:
    path = file_with_attributes()

    assert available(path)
