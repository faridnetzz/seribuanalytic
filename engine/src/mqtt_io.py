"""Lapis MQTT: publish event final + subscribe metadata perception DeepStream."""
import json
import logging
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from . import config

log = logging.getLogger("engine.mqtt")


class MqttIO:
    def __init__(self):
        u = urlparse(config.MQTT_URL)
        self.host = u.hostname or "localhost"
        self.port = u.port or 1883
        self.client = mqtt.Client(client_id="sigap-engine",
                                  callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        # callback perception: dict topik -> fungsi(msg_dict)
        self._subscribers = []

    def connect(self):
        log.info("Menyambung MQTT %s:%s", self.host, self.port)
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT terhubung (rc=%s)", reason_code)
        if self._subscribers:
            client.subscribe(config.PERCEPTION_TOPIC)
            log.info("Subscribe perception: %s", config.PERCEPTION_TOPIC)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return
        for cb in self._subscribers:
            try:
                cb(msg.topic, payload)
            except Exception as e:
                log.exception("Subscriber error: %s", e)

    def on_perception(self, callback):
        """Daftarkan callback(topic, payload) untuk pesan perception."""
        self._subscribers.append(callback)

    def publish_event(self, envelope: dict):
        topic = f"{config.EVENT_TOPIC_PREFIX}/{envelope['module']}"
        self.client.publish(topic, json.dumps(envelope), qos=0)
