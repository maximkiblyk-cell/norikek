from app.game.adapters import adapter_status

def test_real_game_adapters_are_disabled_until_authorized_source_exists():
    statuses = adapter_status()["adapters"]
    assert len(statuses) == 2
    assert all(item["enabled"] is False for item in statuses)

def test_disabled_adapters_refuse_events_and_commands():
    import asyncio
    import pytest
    from app.game.adapters import HassleAdapter, RadmirAdapter
    from app.game.contracts import AdapterUnavailable
    for adapter in (HassleAdapter, RadmirAdapter):
        with pytest.raises(AdapterUnavailable): adapter.events()
        with pytest.raises(AdapterUnavailable): asyncio.run(adapter.execute(None))
