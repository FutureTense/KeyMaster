""" Fixtures for keymaster tests. """
import pytest
from unittest.mock import patch

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture()
def mock_get_entities():
    """Mock email data update class values."""
    with patch(
        "custom_components.keymaster.config_flow._get_entities", autospec=True
    ) as mock_get_entities:

        mock_get_entities.return_value = [
            "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
            "binary_sensor.frontdoor",
        ]
        yield mock_get_entities


@pytest.fixture()
def mock_get_entities_to_remove():
    """Mock email data update class values."""
    with patch(
        "custom_components.keymaster.helpers._get_entities_to_remove", autospec=True
    ) as mock_get_entities_to_remove:
        mock_get_entities_to_remove.return_value = []
        yield mock_get_entities_to_remove


@pytest.fixture
def mock_listdir():
    """Fixture to mock listdir."""
    with patch(
        "os.listdir",
        return_value=[
            "testfile.gif",
            "anotherfakefile.mp4",
            "lastfile.txt",
        ],
    ):
        yield


@pytest.fixture
def mock_osremove():
    """Fixture to mock remove file."""
    with patch("os.remove", return_value=True):
        yield


@pytest.fixture
def mock_osrmdir():
    """Fixture to mock remove directory."""
    with patch("os.rmdir", return_value=True):
        yield


@pytest.fixture
def mock_osmakedir():
    """Fixture to mock makedirs."""
    with patch("os.makedirs", return_value=True):
        yield


@pytest.fixture
def mock_delete_folder():
    """Fixture to mock delete_folder helper function."""
    with patch("custom_components.keymaster.delete_folder"):
        yield


@pytest.fixture
def mock_delete_lock_and_base_folder():
    """Fixture to mock delete_lock_and_base_folder helper function."""
    with patch("custom_components.keymaster.delete_lock_and_base_folder"):
        yield
