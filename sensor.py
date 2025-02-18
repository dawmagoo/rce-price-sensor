from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import logging

SCAN_INTERVAL = timedelta(seconds=20)
_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the RCE Price Sensor platform."""
    async_add_entities([RCEPriceSensor()])

class RCEPriceSensor(SensorEntity):
    """Representation of the RCE price sensor."""

    def __init__(self) -> None:
        """Initialize the sensor."""
        _LOGGER.info("RCE price sensor initialized")
        super().__init__()
        self.ev = []  # List to store events (price changes)
        self.last_update = None  # Timestamp of the last update
        self.cloud_response = None  # Response from the API
        self.last_network_pull = datetime(year=2000, month=1, day=1, tzinfo=ZoneInfo("UTC"))  # Last time data was fetched
        self._attr_unique_id = "rce_price_sensor"  # Unique ID for the sensor
        self._attr_name = "RCE Price Sensor"  # Name of the sensor
        self._attr_state = None  # Current state (price)
        self._attr_unit_of_measurement = "PLN"  # Unit of measurement
        self._attr_icon = "mdi:currency-usd"  # Icon for the sensor

    def fetch_cloud_data(self, days_offset: int = 0) -> bool:
        """
        Fetch data from the cloud API for a specific day.
        
        Args:
            days_offset: Number of days to offset from today (0 for today, 1 for tomorrow, etc.).
        
        Returns:
            bool: True if data was fetched successfully, False otherwise.
        """
        now = datetime.now(ZoneInfo(self.hass.config.time_zone)) + timedelta(days=days_offset)
        url = f"https://api.raporty.pse.pl/api/rce-pln?$filter=doba eq '{now.strftime('%Y-%m-%d')}'"
        try:
            response = requests.get(url, timeout=10)
            response.encoding = 'ISO-8859-2'
            if response.status_code == 200:
                self.cloud_response = response.json()
                return True
            else:
                _LOGGER.error(f"Failed to fetch data: HTTP {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            _LOGGER.error(f"Failed to fetch cloud data: {e}")
            return False

    def json_to_events(self, json_data: dict, day: datetime) -> None:
        """
        Transform JSON data into events (price changes).
        
        Args:
            json_data: JSON data from the API.
            day: The day for which the data is being processed.
        """
        curr_price = None
        start_time = None
        end_time = None

        for entry in json_data.get('value', []):
            times = entry['udtczas_oreb'].split("-")
            try:
                ts = datetime.strptime(times[0].strip(), "%H:%M")
                ts = day.replace(hour=ts.hour, minute=ts.minute, second=0)
                if times[1].strip() == "24:00":
                    te = day.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                else:
                    te = datetime.strptime(times[1].strip(), "%H:%M")
                    te = day.replace(hour=te.hour, minute=te.minute, second=0)

                if entry['rce_pln'] != curr_price:
                    if curr_price is not None:
                        self.ev.append({
                            'start_time': start_time,
                            'end_time': end_time,
                            'price': curr_price,
                        })
                    curr_price = entry['rce_pln']
                    start_time = ts
                end_time = te
            except ValueError as e:
                _LOGGER.error(f"Error parsing time: {e}")

        if end_time is not None:
            self.ev.append({
                'start_time': start_time,
                'end_time': end_time,
                'price': curr_price,
            })

    async def async_update(self) -> None:
        """Update the sensor's state."""
        now = datetime.now(ZoneInfo(self.hass.config.time_zone))

        # Fetch data only if 30 minutes have passed since the last pull
        if now < self.last_network_pull + timedelta(minutes=30):
            return

        self.last_network_pull = now
        self.ev.clear()

        # Fetch today's data
        if not await self.hass.async_add_executor_job(self.fetch_cloud_data, 0):
            _LOGGER.error("Failed to fetch today's data")
            return

        today = now.replace(minute=0, second=0, microsecond=0)
        self.json_to_events(self.cloud_response, today)

        # Fetch tomorrow's data
        if not await self.hass.async_add_executor_job(self.fetch_cloud_data, 1):
            _LOGGER.error("Failed to fetch tomorrow's data")
            return

        tomorrow = today + timedelta(days=1)
        self.json_to_events(self.cloud_response, tomorrow)

        # Set the current price as the sensor's state
        if self.ev:
            self._attr_state = self.ev[0]['price']
        self.last_update = now

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes for the sensor."""
        return {
            "events": self.ev,
            "last_updated": self.last_update.isoformat() if self.last_update else None,
        }