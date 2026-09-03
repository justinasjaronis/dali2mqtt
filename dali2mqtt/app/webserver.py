"""Small web UI (a DALI cockpit) served over Home Assistant Ingress.

Runs inside the bridge's asyncio loop and shares its python-dali driver via
:class:`~app.dali_config.DaliConfig`.
"""
import json
import logging
import os

from aiohttp import web

from .dali_config import DaliConfig

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _json(data, status=200):
    return web.json_response(data, status=status)


class DaliWebServer:
    def __init__(self, driver, config, reinit=None, busy=None, port=8099):
        self.cfg = DaliConfig(driver, busy=busy)
        self.config = config
        self.reinit = reinit  # async callable to refresh MQTT discovery
        self.port = port
        self._runner = None

    # --------------------------------------------------------------- routes
    def _app(self):
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/api/scan", self.api_scan)
        app.router.add_post("/api/gear/{addr}/level", self.api_level)
        app.router.add_post("/api/gear/{addr}/set", self.api_set)
        app.router.add_post("/api/gear/{addr}/identify", self.api_identify)
        app.router.add_post("/api/gear/{addr}/address", self.api_address)
        app.router.add_post("/api/gear/{addr}/group", self.api_group)
        app.router.add_get("/api/gear/{addr}/scenes", self.api_get_scenes)
        app.router.add_post("/api/gear/{addr}/scene", self.api_set_scene)
        app.router.add_post("/api/commission", self.api_commission)
        app.router.add_post("/api/reinit", self.api_reinit)
        # Control devices (DALI-2 buttons/sensors)
        app.router.add_get("/api/scan_devices", self.api_scan_devices)
        app.router.add_get("/api/device/{addr}", self.api_device_info)
        app.router.add_post("/api/device/{addr}/identify", self.api_device_identify)
        app.router.add_post("/api/device/{addr}/address", self.api_device_address)
        app.router.add_static("/static/", STATIC_DIR)
        return app

    async def start(self):
        self._runner = web.AppRunner(self._app())
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()
        logger.info("DALI config web UI listening on :%s", self.port)

    # -------------------------------------------------------------- handlers
    async def index(self, request):
        return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))

    async def api_scan(self, request):
        try:
            gear = await self.cfg.scan_gear()
            return _json({"gear": gear})
        except Exception as err:  # noqa: BLE001
            logger.exception("scan failed")
            return _json({"error": str(err)}, 500)

    async def _body(self, request):
        try:
            return await request.json()
        except Exception:
            return {}

    def _addr(self, request):
        return int(request.match_info["addr"])

    async def api_level(self, request):
        body = await self._body(request)
        return _json(await self.cfg.set_level(self._addr(request), body["level"]))

    async def api_set(self, request):
        body = await self._body(request)
        field = body.get("field")
        value = body.get("value")
        addr = self._addr(request)
        setters = {
            "min_level": self.cfg.set_min_level,
            "max_level": self.cfg.set_max_level,
            "power_on_level": self.cfg.set_power_on_level,
            "system_failure_level": self.cfg.set_system_failure_level,
            "fade_time": self.cfg.set_fade_time,
            "fade_rate": self.cfg.set_fade_rate,
        }
        if field not in setters:
            return _json({"error": f"unknown field {field}"}, 400)
        return _json(await setters[field](addr, value))

    async def api_identify(self, request):
        return _json(await self.cfg.identify(self._addr(request)))

    async def api_address(self, request):
        body = await self._body(request)
        try:
            res = await self.cfg.change_address(self._addr(request), int(body["new"]))
        except ValueError as err:
            return _json({"error": str(err)}, 400)
        if self.reinit:
            await self.reinit()
        return _json(res)

    async def api_group(self, request):
        body = await self._body(request)
        addr = self._addr(request)
        group = int(body["group"])
        if body.get("action") == "remove":
            return _json(await self.cfg.remove_from_group(addr, group))
        return _json(await self.cfg.add_to_group(addr, group))

    async def api_get_scenes(self, request):
        return _json(await self.cfg.get_scenes(self._addr(request)))

    async def api_set_scene(self, request):
        body = await self._body(request)
        addr = self._addr(request)
        scene = int(body["scene"])
        if body.get("clear"):
            return _json(await self.cfg.clear_scene(addr, scene))
        return _json(await self.cfg.set_scene(addr, scene, int(body["level"])))

    async def api_commission(self, request):
        body = await self._body(request)
        readdress = bool(body.get("readdress", False))
        res = await self.cfg.commission(readdress=readdress)
        if self.reinit:
            await self.reinit()
        return _json(res)

    async def api_reinit(self, request):
        if self.reinit:
            await self.reinit()
        return _json({"ok": True})

    # ------------------------------------------------- control device handlers
    async def api_scan_devices(self, request):
        try:
            devices = await self.cfg.scan_devices()
            return _json({"devices": devices, "supported": self.cfg.devices_supported()})
        except Exception as err:  # noqa: BLE001
            logger.exception("device scan failed")
            return _json({"error": str(err)}, 500)

    async def api_device_info(self, request):
        return _json(await self.cfg.read_device(self._addr(request)))

    async def api_device_identify(self, request):
        return _json(await self.cfg.identify_device(self._addr(request)))

    async def api_device_address(self, request):
        body = await self._body(request)
        try:
            res = await self.cfg.change_device_address(
                self._addr(request), int(body["new"])
            )
        except ValueError as err:
            return _json({"error": str(err)}, 400)
        return _json(res)
