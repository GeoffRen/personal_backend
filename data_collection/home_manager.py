import signal
import time
from openzwave.command import ZWaveNodeSensor
from openzwave.network import ZWaveNetwork
from openzwave.option import ZWaveOption
from pydispatch import dispatcher
from influxdb import InfluxDBClient
from threading import Timer


DATABASE = 'sterling_ranch'  # The InfluxDB database name to write data to.
TIME_INTERVAL = 15  # The polling interval in seconds.
# One of many config numbers in the Aeotec Multisensor 6. This number controls Group 1's poll interval. Group 1
# contains references to the actual sensors on the Multisensor. This seems to be different from sensor to sensor.
CONFIG_NUMBER = 72057594098484979


def ozw_debug(logger, network):
    """Custom debug log.
    :param logger: Logger to use.
    :param network: Network to use.
    """
    logger.info("------------------------------------------------------------")
    logger.info("Use openzwave library : {}".format(network.controller.ozw_library_version))
    logger.info("Use python library : {}".format(network.controller.python_library_version))
    logger.info("Use ZWave library : {}".format(network.controller.library_description))
    logger.info("Network home id : {}".format(network.home_id_str))
    logger.info("Controller node id : {}".format(network.controller.node.node_id))
    logger.info("Controller node version : {}".format(network.controller.node.version))
    logger.info("Nodes in network : {}".format(network.nodes_count))
    logger.info("------------------------------------------------------------")


def value_refresh_to_influxdb_json(node, val):
    """Converts node and val to a format that can be written to Influx with (JSON).
    :param node: Contains identifying information of the sensor.
    :param val: Contains information about the sensor reading.
    :return: JSON containing information about the sensor and the sensor's reading.
    """
    return [{
        "measurement": "value_refresh",
        "tags": {
            'id_on_network': val.id_on_network,
            'home_id': node.home_id,
            'node_id': node.node_id,
            'value_id': val.value_id,
            'manufacturer_id': node.manufacturer_id,
            'product_id': node.product_id,
            'label': str(val.label),
        },
        "time": time.asctime(time.localtime()),
        "fields": {
            'data': float(val.data),
            'units': str(val.units),
            'type': 'none',
            'type_val': 0
        }
    }]


class HomeManager(object):
    """Contains capabilities to periodically poll and write data from the sensor to an Influx instance."""
    def __init__(self, device_path, ozw_log_level, logger):
        """Initializes a HomeManager."""
        self.logger = logger

        options = ZWaveOption(device_path,
                              config_path="../venv/lib/python3.6/site-packages/python_openzwave/ozw_config",
                              user_path=".", cmd_line="")
        options.set_log_file("OZW.log")
        options.set_append_log_file(False)
        options.set_save_log_level(ozw_log_level)
        options.set_console_output(False)
        options.set_logging(True)
        options.lock()
        self.options = options
        self.network = ZWaveNetwork(options, log=None, autostart=False)
        self.client = InfluxDBClient(database=DATABASE)

    def start(self):
        """Starts the network."""
        self.logger.info("Starting network...")
        self.network.start()

    def stop_signal(self, signum, frame):
        """Callback for when a SIGINT is received. Calls stop() which stops the network."""
        self.stop()

    def stop(self):
        """Stops the network (so stops the polling)."""
        self.logger.info("Stopping network...")
        self.network.nodes[3].values[CONFIG_NUMBER].data = 3600  # Stop the actual sensor from polling.
        self.network.stop()
        self.logger.info("Stopped")

    def connect_signals(self):
        """Sets the SIGNAL_NETWORK_READY callback."""
        dispatcher.connect(self.signal_network_ready, self.network.SIGNAL_NETWORK_READY)
        signal.signal(signal.SIGINT, self.stop_signal)

    def signal_network_ready(self, network):
        """Callback for when the network is ready. Logs that the network is ready and then starts polling the sensors.
        Note -- the name of the network parameter must not change!
        :param network: Network to use.
        """
        if self.network is not network:
            return
        else:
            del network
        ozw_debug(self.logger, self.network)
        self.logger.info("Network is ready!")
        self.network.nodes[3].values[CONFIG_NUMBER].data = 15  # Make the actual sensor start polling.
        self.start_polling()

    @staticmethod
    def is_sensor(node):
        """Determines if node is a sensor or not.
        :param node: The node in the network.
        :return: True if node is a sensor, else False.
        """
        return isinstance(node, ZWaveNodeSensor) and not len(node.get_sensors()) is 0

    def start_polling(self):
        """Polls sensors in the network every TIME_INTERVAL seconds for luminance, relative humidity, temperature,
        ultraviolet, alarm level, and burglar data.
        """
        Timer(TIME_INTERVAL, self.start_polling).start()
        labels_to_be_polled = {'Luminance', 'Relative Humidity', 'Temperature', 'Ultraviolet', 'Alarm Level', 'Burglar'}
        for node_id, node in self.network.nodes.items():
            if self.is_sensor(node):
                for val_id in self.network.nodes[node_id].values:
                    val = self.network.nodes[node_id].values[val_id]
                    if val.label in labels_to_be_polled:
                        self.logger.info("Received value refresh %s: %s", val.id_on_network, val)
                        self.client.write_points(value_refresh_to_influxdb_json(node, val))
