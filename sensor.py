from __future__ import annotations
import csv
from zoneinfo import ZoneInfo
import requests
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import datetime, timedelta, timezone

SCAN_INTERVAL = timedelta(seconds=20)
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Configure the sensor via config flow."""
    async_add_entities([RCEPriceSensor()])

class RCEPriceSensor(SensorEntity):
    """Representation of the RCE price sensor."""

    def __init__(self) -> None:
        _LOGGER.info("RCE price sensor initialized")
        super().__init__()
        self.ev = []
        self.cr_time = None
        self.last_update = None
        self.cloud_response = None
        self.last_network_pull = datetime(year=2000, month=1, day=1, tzinfo=timezone.utc)
        self._attr_unique_id = "rce_price_sensor"
        self._attr_name = "RCE Price Sensor"
        self._attr_state = None

    def fetch_cloud_data(self):
        """Fetch today's data from the cloud."""
        now = datetime.now(ZoneInfo(self.hass.config.time_zone))
        url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{now.strftime('%Y-%m-%d')}'"
        try:
            self.cloud_response = requests.get(url, timeout=10)
            self.cloud_response.encoding = 'ISO-8859-2'
        except requests.exceptions.ReadTimeout:
            self.cloud_response = ""

    def fetch_cloud_data_1(self):
        """Fetch tomorrow's data from the cloud."""
        now = datetime.now(ZoneInfo(self.hass.config.time_zone)) + timedelta(days=1)
        url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{now.strftime('%Y-%m-%d')}'"
        try:
            self.cloud_response = requests.get(url, timeout=10)
            self.cloud_response.encoding = 'ISO-8859-2'
        except requests.exceptions.ReadTimeout:
            self.cloud_response = ""

    def json_to_events(self, json, day: datetime):
        """Transform JSON to events."""
        curr_price = None
        start_time = None
        end_time = None
        for i in json['value']:
            times =  i['udtczas_oreb'].split("-")
            try:
                ts = datetime.strptime(times[0].strip(), "%H:%M")
                ts = day.replace(hour=ts.hour, minute=ts.minute, second=0)
                if times[1].strip() == "24:00":
                    te = day.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                else:
                    te = datetime.strptime(times[1].strip(), "%H:%M")
                    te = day.replace(hour=te.hour, minute=te.minute, second=0)
                if i['rce_pln'] != curr_price:
                    if curr_price:
                        self.ev.append({
                            'start_time': start_time,
                            'end_time': end_time,
                            'price': curr_price,
                        })
                    curr_price = i['rce_pln']
                    start_time = ts
                end_time = te
            except ValueError:
                pass
        if end_time is not None:
            self.ev.append({
                'start_time': start_time,
                'end_time': end_time,
                'price': curr_price,
            })

    async def async_update(self):
        """Update the sensor's state."""
        now = datetime.now(ZoneInfo(self.hass.config.time_zone))
        if now < self.last_network_pull + timedelta(minutes=30):
            return
        self.last_network_pull = now
        self.cloud_response = None
        await self.hass.async_add_executor_job(self.fetch_cloud_data)

        if self.cloud_response is None or self.cloud_response.status_code != 200:
            return False
        self.ev.clear()

        now = now.replace(minute=0).replace(second=0)
        self.json_to_events(self.cloud_response.json(), now)

        self.cloud_response = None
        await self.hass.async_add_executor_job(self.fetch_cloud_data_1)

        if self.cloud_response is None or self.cloud_response.status_code != 200:
            return False

        now = now.replace(minute=0).replace(second=0) + timedelta(days=1)
        self.json_to_events(self.cloud_response.json(), now)

        # Example: Set the state to the current price
        if self.ev:
            self._attr_state = self.ev[0]['price']  # Set current price as state

    @property
    def extra_state_attributes(self):
        """Return additional attributes for the sensor."""
        return {
            "events": self.ev,
            "last_updated": self.last_update,
        }
