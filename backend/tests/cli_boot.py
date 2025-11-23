import asyncio
import websockets
import sys

# Shim for ocpp's legacy jsonschema import
import jsonschema
try:
    import jsonschema._validators  # type: ignore
except Exception:
    import jsonschema.validators as _v  # type: ignore
    sys.modules['jsonschema._validators'] = _v

from ocpp.v16 import ChargePoint as cp
from ocpp.v16 import call


class TestCP(cp):
    async def send_boot(self):
        payload_cls = getattr(call, 'BootNotification', None) or getattr(call, 'BootNotificationPayload')
        req = payload_cls(charge_point_model='CLI', charge_point_vendor='UNIEV')
        return await self.call(req)


async def main():
    async with websockets.connect('ws://localhost:9000/TEST-CLI', subprotocols=['ocpp1.6']) as ws:
        c = TestCP('TEST-CLI', ws)
        res = await c.send_boot()
        print(res)


if __name__ == '__main__':
    asyncio.run(main())