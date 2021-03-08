""" Test keymaster helpers """
from unittest.mock import Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event

from custom_components.keymaster.const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from custom_components.keymaster.helpers import delete_lock_and_base_folder
from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_STATE,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_LOCKED,
    STATE_UNLOCKED,
)

from .common import MQTTMessage, async_capture_events, process_fixture_data, setup_ozw

from tests.const import CONFIG_DATA, CONFIG_DATA_910, CONFIG_DATA_REAL

SCHLAGE_BE469_LOCK_ENTITY = "lock.touchscreen_deadbolt_current_lock_mode"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"


async def test_delete_lock_and_base_folder(
    hass,
    mock_osremove,
    mock_osrmdir,
):
    """Test delete_lock_and_base_folder"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    delete_lock_and_base_folder(hass, entry)

    assert mock_osrmdir.called
    assert mock_osremove.called

    with patch("custom_components.keymaster.helpers.os", autospec=True) as mock_os:
        mock_os.listdir.return_value = False
        delete_lock_and_base_folder(hass, entry)
        mock_os.rmdir.assert_called_once


async def test_handle_state_change(hass, lock_data, sent_messages):
    """Test handle_state_change"""
    receive_message, ozw_entry = await setup_ozw(hass, fixture=lock_data)
    events = async_capture_events(hass, EVENT_KEYMASTER_LOCK_STATE_CHANGED)

    # Load the integration
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Make sure the lock loaded
    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    registry = await hass.helpers.entity_registry.async_get_registry()
    entity_id = "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False

    entity_id = "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False
    await hass.async_block_till_done()

    with patch("homeassistant.components.mqtt.async_subscribe") as mock_subscribe:
        mock_subscribe.return_value = Mock()
        assert await hass.config_entries.async_reload(ozw_entry.entry_id)
        await hass.async_block_till_done()

    assert "ozw" in hass.config.components
    assert len(mock_subscribe.mock_calls) == 1
    receive_message = mock_subscribe.mock_calls[0][1][2]
    await process_fixture_data(hass, receive_message, lock_data)

    state = hass.states.get(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level"
    )
    assert state is not None
    assert state.state == "1"

    state = hass.states.get(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type"
    )
    assert state is not None
    assert state.state == "21"

    # Unlock the lock
    await hass.services.async_call(
        "lock",
        "unlock",
        {"entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg["topic"] == "OpenZWave/1/command/setvalue/"
    assert msg["payload"] == {"Value": False, "ValueIDKey": 240680976}

    # Mock lock state chanages
    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/98/value/240680976/",
        payload={
            "Label": "Locked",
            "Value": False,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 0,
            "Type": "Bool",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_DOOR_LOCK",
            "Index": 0,
            "Node": 14,
            "Genre": "User",
            "Help": "State of the Lock",
            "ValueIDKey": 240680976,
            "ReadOnly": False,
            "WriteOnly": False,
            "Event": "valueChanged",
            "TimeStamp": 1631042099,
        },
    )
    message.encode()
    receive_message(message)

    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/113/value/144115188316782609/",
        payload={
            "Label": "Alarm Type",
            "Value": 25,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 255,
            "Type": "Byte",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_NOTIFICATION",
            "Index": 512,
            "Node": 14,
            "Genre": "User",
            "Help": "Alarm Type Received",
            "ValueIDKey": 144115188316782609,
            "ReadOnly": True,
            "WriteOnly": False,
            "Event": "valueChanged",
            "TimeStamp": 1631042100,
        },
    )
    message.encode()
    receive_message(message)

    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/113/value/144396663293493265/",
        payload={
            "Label": "Alarm Level",
            "Value": 1,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 255,
            "Type": "Byte",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_NOTIFICATION",
            "Index": 513,
            "Node": 14,
            "Genre": "User",
            "Help": "Alarm Level Received",
            "ValueIDKey": 144396663293493265,
            "ReadOnly": True,
            "WriteOnly": False,
            "Event": "valueRefreshed",
            "TimeStamp": 1631042101,
        },
    )
    message.encode()
    receive_message(message)
    # process message
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data[ATTR_NAME] == "frontdoor"
    assert events[0].data[ATTR_STATE] == "unlocked"
    assert events[0].data[ATTR_ACTION_CODE] == 25
    assert events[0].data[ATTR_ACTION_TEXT] == "RF Unlock"
    assert events[0].data[ATTR_CODE_SLOT] == 1
    assert events[0].data[ATTR_CODE_SLOT_NAME] == ""


async def test_handle_state_change_zwave_js(
    hass, client, lock_kwikset_910, integration
):
    """Test handle_state_change with zwave_js"""
    # Make sure the lock loaded
    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == STATE_LOCKED

    events = async_capture_events(hass, EVENT_KEYMASTER_LOCK_STATE_CHANGED)
    events_js = async_capture_events(hass, "zwave_js_event")

    # Load the integration
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Enable the sensors we use
    registry = await hass.helpers.entity_registry.async_get_registry()
    entity_id = "sensor.smart_code_with_home_connect_technology_alarmlevel"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False

    registry = await hass.helpers.entity_registry.async_get_registry()
    entity_id = "sensor.smart_code_with_home_connect_technology_alarmtype"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False
    await hass.async_block_till_done()

    # Reload zwave_js
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    # Make sure the sensors updated the current values
    state = hass.states.get("sensor.smart_code_with_home_connect_technology_alarmtype")
    assert state is not None
    assert state.state == "21"

    state = hass.states.get("sensor.smart_code_with_home_connect_technology_alarmlevel")
    assert state is not None
    assert state.state == "1"

    # Test locked update from value updated event
    event = Event(
        type="value updated",
        data={
            "source": "node",
            "event": "value updated",
            "nodeId": 14,
            "args": {
                "commandClassName": "Notification",
                "commandClass": 113,
                "endpoint": 0,
                "property": "alarmType",
                "newValue": 19,
                "prevValue": 21,
                "propertyName": "alarmType",
            },
        },
    )
    node.receive_event(event)

    assert (
        hass.states.get(
            "sensor.smart_code_with_home_connect_technology_alarmtype"
        ).state
        == "19"
    )
    client.async_send_command.reset_mock()

    event = Event(
        type="value updated",
        data={
            "source": "node",
            "event": "value updated",
            "nodeId": 14,
            "args": {
                "commandClassName": "Notification",
                "commandClass": 113,
                "endpoint": 0,
                "property": "alarmLevel",
                "newValue": 3,
                "prevValue": 1,
                "propertyName": "alarmLevel",
            },
        },
    )
    node.receive_event(event)
    await hass.async_block_till_done()

    assert (
        hass.states.get(
            "sensor.smart_code_with_home_connect_technology_alarmlevel"
        ).state
        == "3"
    )
    client.async_send_command.reset_mock()

    event = Event(
        type="value updated",
        data={
            "source": "node",
            "event": "value updated",
            "nodeId": 14,
            "args": {
                "commandClassName": "Door Lock",
                "commandClass": 98,
                "endpoint": 0,
                "property": "currentMode",
                "newValue": 0,
                "prevValue": 255,
                "propertyName": "currentMode",
            },
        },
    )
    node.receive_event(event)
    assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == STATE_UNLOCKED
    client.async_send_command.reset_mock()

    # Fire zwave_js event
    event = Event(
        type="notification",
        data={
            "source": "node",
            "event": "notification",
            "nodeId": 14,
            "notificationLabel": "Keypad unlock operation",
            "parameters": {"userId": 3},
        },
    )
    node.receive_event(event)
    # wait for the event
    await hass.async_block_till_done()

    assert len(events) == 3
    assert len(events_js) == 2
    assert events[0].data[ATTR_NAME] == "frontdoor"
    assert events[0].data[ATTR_STATE] == "unlocked"
    assert events[0].data[ATTR_ACTION_TEXT] == "Keypad unlock operation"
    assert events[0].data[ATTR_CODE_SLOT] == 3
    assert events[0].data[ATTR_CODE_SLOT_NAME] == ""

    assert events_js[0].data["type"] == "notification"
    assert events_js[0].data["home_id"] == client.driver.controller.home_id
    assert events_js[0].data["node_id"] == 14
    assert events_js[0].data["label"] == "Keypad unlock operation"
    assert events_js[0].data["parameters"]["userId"] == 3
