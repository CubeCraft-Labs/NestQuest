"""Behavior and wiring tests for the UniFi quest-access blueprint."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.blueprint_helpers import BlueprintInput, blueprint, render


def _blueprint() -> dict:
    return blueprint("unifi_quest_access")


def test_inputs_and_reconciliation_triggers() -> None:
    bp = _blueprint()
    inputs = bp["blueprint"]["input"]
    assert set(inputs) == {
        "remaining_sensor",
        "present_sensor",
        "client_switches",
        "weekday_cutoff",
        "weekend_cutoff",
    }
    assert inputs["weekday_cutoff"]["default"] == "18:25:00"
    assert inputs["weekend_cutoff"]["default"] == "14:00:00"
    assert inputs["remaining_sensor"]["selector"]["entity"]["filter"] == [
        {"integration": "nestquest", "domain": "sensor"}
    ]
    assert inputs["present_sensor"]["selector"]["entity"]["filter"] == [
        {"integration": "nestquest", "domain": "binary_sensor"}
    ]
    assert inputs["client_switches"]["selector"]["entity"] == {
        "multiple": True,
        "filter": [{"integration": "unifi", "domain": "switch"}],
    }
    assert bp["variables"]["remaining_sensor"] == BlueprintInput(
        "remaining_sensor"
    )
    assert bp["variables"]["present_sensor"] == BlueprintInput(
        "present_sensor"
    )
    assert bp["variables"]["client_switches"] == BlueprintInput(
        "client_switches"
    )
    assert bp["mode"] == "restart"

    triggers = bp["triggers"]
    assert {trigger["trigger"] for trigger in triggers} == {
        "state",
        "time",
        "homeassistant",
        "time_pattern",
    }
    assert {trigger["at"] for trigger in triggers if trigger["trigger"] == "time"} == {
        BlueprintInput("weekday_cutoff"),
        BlueprintInput("weekend_cutoff"),
        "00:00:00",
    }
    assert any(
        trigger.get("entity_id") == BlueprintInput("remaining_sensor")
        for trigger in triggers
    )
    assert any(
        trigger.get("entity_id") == BlueprintInput("present_sensor")
        for trigger in triggers
    )
    assert any(
        trigger.get("event") == "start" for trigger in triggers
    )
    assert any(
        trigger.get("minutes") == "/5" for trigger in triggers
    )


@pytest.mark.parametrize(
    ("when", "remaining", "presence", "should_block"),
    [
        (datetime(2026, 10, 19, 18, 24), "2", "on", False),  # Monday, pre-cutoff
        (datetime(2026, 10, 19, 18, 25), "2", "on", True),
        (datetime(2026, 10, 19, 19, 0), "0", "on", False),
        (datetime(2026, 10, 19, 19, 0), "unknown", "on", True),
        (datetime(2026, 10, 19, 19, 0), "2", "off", False),  # On travels
        (datetime(2026, 10, 19, 19, 0), "2", "unavailable", False),
        (datetime(2026, 10, 17, 13, 59), "1", "on", False),  # Saturday
        (datetime(2026, 10, 17, 14, 0), "1", "on", True),
        (datetime(2026, 10, 18, 14, 0), "0", "on", False),  # Sunday
        (datetime(2026, 10, 20, 0, 0), "1", "on", False),  # no carry-over
    ],
)
def test_access_decision(
    when: datetime, remaining: str, presence: str, should_block: bool
) -> None:
    decision = _blueprint()["actions"][0]["variables"]["should_block"]
    actual = render(
        decision,
        now=lambda: when,
        states=lambda entity_id: remaining,
        is_state=lambda entity_id, state: presence == state,
        remaining_sensor="sensor.selected_child",
        present_sensor="binary_sensor.selected_child_present_today",
        weekday_cutoff="18:25:00",
        weekend_cutoff="14:00:00",
    ).strip()
    assert actual == str(should_block)


def test_only_out_of_sync_clients_receive_commands() -> None:
    bp = _blueprint()
    loop = bp["actions"][1]["repeat"]
    assert loop["for_each"] == "{{ client_switches }}"
    choices = loop["sequence"][0]["choose"]
    assert len(choices) == 2
    block, allow = choices
    assert "is_state(repeat.item, 'on')" in block["conditions"][0]["value_template"]
    assert block["sequence"][0]["action"] == "switch.turn_off"
    assert "is_state(repeat.item, 'off')" in allow["conditions"][0]["value_template"]
    assert allow["sequence"][0]["action"] == "switch.turn_on"
    assert all(
        choice["sequence"][0]["target"]["entity_id"] == "{{ repeat.item }}"
        for choice in choices
    )
