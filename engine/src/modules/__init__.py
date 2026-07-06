"""Registry & factory worker modul."""
from .. import config
from .pedestrian import PedestrianWorker
from .waste import WasteWorker
from .water import WaterWorker
from .parking import ParkingWorker

_REGISTRY = {
    "pedestrian": PedestrianWorker,
    "waste": WasteWorker,
    "water": WaterWorker,
    "parking": ParkingWorker,
}


def build_enabled_workers(mqtt_io):
    """Instansiasi worker untuk modul yang diaktifkan via ENGINE_MODULES."""
    workers = []
    for code in config.ENABLED_MODULES:
        cls = _REGISTRY.get(code)
        if cls is None:
            continue
        workers.append(cls(mqtt_io))
    return workers
