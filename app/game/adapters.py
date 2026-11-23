"""Separate game adapters remain disabled until an authorized SDK is verified."""
from app.game.contracts import AdapterUnavailable, GameCommand

class DisabledAdapter:
    def __init__(self, platform: str):
        self.platform = platform

    @property
    def enabled(self) -> bool:
        return False

    def status(self):
        return {"platform": self.platform, "enabled": False,
                "reason": "No verified, authorized game event interface configured."}

    def events(self):
        raise AdapterUnavailable(f"{self.platform} SDK and permissions have not been verified")

    async def execute(self, command: GameCommand):
        raise AdapterUnavailable(f"{self.platform} command interface has not been verified")

class HassleGameAdapter(DisabledAdapter):
    def __init__(self): super().__init__('hassle')

class RadmirGameAdapter(DisabledAdapter):
    def __init__(self): super().__init__('radmir')

# Preserve the original public objects and status contract.
HassleAdapter = HassleGameAdapter()
RadmirAdapter = RadmirGameAdapter()

def adapter_status():
    return {"adapters": [HassleAdapter.status(), RadmirAdapter.status()]}
