
# TODO connection caching
from kombu import BrokerConnection, Exchange, Queue
import socket
import settings

from chroma_core.lib.storage_plugin.log import storage_plugin_log as log


def _drain_all(connection, queue, handler, timeout = 0.1):
    """Helper for draining all messages on a particular queue
    (kombo's inbuild drain_events generally just gives you one)"""
    with connection.Consumer([queue], callbacks=[handler]):
        # Loop until we get a call to drain_events which
        # does not result in a handler callback
        while True:
            exhausted = False
            try:
                connection.drain_events(timeout = timeout)
            except socket.timeout:
                exhausted = True
                pass

            if exhausted:
                break


def _amqp_connection():
    return BrokerConnection("amqp://%s:%s@%s:%s/%s" % (
        settings.BROKER_USER,
        settings.BROKER_PASSWORD,
        settings.BROKER_HOST,
        settings.BROKER_PORT,
        settings.BROKER_VHOST))


def _wait_for_host(host, timeout):
    #: How often to check the host to see if it has become available
    UNAVAILABLE_POLL_INTERVAL = 10
    unavailable_elapsed = 0
    while not host.is_available():
        # Polling delay
        import time
        time.sleep(UNAVAILABLE_POLL_INTERVAL)

        # Apply the timeout if one is set
        unavailable_elapsed += UNAVAILABLE_POLL_INTERVAL
        if timeout and unavailable_elapsed >= timeout:
            raise Timeout("Timed out waiting for host %s to become available" % (host))

        # Reload the ManagedHost from the database
        from django.db import transaction
        from chroma_core.models.host import ManagedHost
        with transaction.commit_manually():
            transaction.commit()
            host = ManagedHost.objects.get(pk=host.id)
            transaction.commit()


def plugin_rpc(plugin_name, host, request, timeout = 0):
    """
    :param plugin_name: String name of plugin
    :param host: ManagedHost instance
    :param request: JSON-serializable dict
    :param timeout: If None (default) then block until the Host is available for requests
    """

    # If the host is not available, don't submit a request until it is available
    if not host.is_available():
        log.info("Host %s is not available for plugin RPC, waiting" % host)
        _wait_for_host(host, timeout)
        log.info("Host %s is now available for plugin RPC" % host)

    request_id = PluginRequest.send(plugin_name, host.fqdn, {})
    try:
        return PluginResponse.receive(plugin_name, host.fqdn, request_id)
    except Timeout:
        # Revoke the request, we will never handle a response from it
        PluginRequest.revoke(plugin_name, host.fqdn, request_id)
        raise


class Timeout(Exception):
    pass


class PluginRequest(object):
    @classmethod
    def send(cls, plugin_name, resource_tag, request_dict, timeout = None):
        request_id = None
        with _amqp_connection() as conn:
            conn.connect()

            exchange = Exchange("plugin_data", "direct", durable = True)

            # Send a request for information from the plugin on this host
            request_routing_key = "plugin_data_request_%s_%s" % (plugin_name, resource_tag)

            # Compose the body
            import uuid
            request_id = uuid.uuid1().__str__()
            body = {'id': request_id}
            for k, v in request_dict.items():
                if k == 'id':
                    raise RuntimeError("Cannot use 'id' in PluginRequest body")
                body[k] = v

            with conn.Producer(exchange = exchange, serializer = 'json', routing_key = request_routing_key) as producer:
                producer.publish(body)
            log.info("Sent request for %s (%s)" % (request_routing_key, request_id))

        return request_id

    @classmethod
    def receive_all(cls, plugin_name, resource_tag):
        exchange = Exchange("plugin_data", "direct", durable = True)
        with _amqp_connection() as conn:
            conn.connect()
            # See if there are any requests for this agent plugin
            request_routing_key = "plugin_data_request_%s_%s" % (plugin_name, resource_tag)

            requests = []

            def handle_request(body, message):
                log.info("UpdateScan %s: Passing on request %s" % (resource_tag, body['id']))
                requests.append(body)
                message.ack()

            request_queue = Queue(request_routing_key, exchange = exchange, routing_key = request_routing_key)
            request_queue(conn.channel()).declare()

            _drain_all(conn, request_queue, handle_request)

        return requests

    @classmethod
    def revoke(cls, plugin_name, resource_tag, request_id):
        exchange = Exchange("plugin_data", "direct", durable = True)
        with _amqp_connection() as conn:
            conn.connect()
            # See if there are any requests for this agent plugin
            request_routing_key = "plugin_data_request_%s_%s" % (plugin_name, resource_tag)

            requests = []

            def handle_request(body, message):
                if body['id'] == request_id:
                    message.ack()

            request_queue = Queue(request_routing_key, exchange = exchange, routing_key = request_routing_key)
            request_queue(conn.channel()).declare()
            with conn.Consumer([request_queue], callbacks=[handle_request]):
                from socket import timeout
                try:
                    conn.drain_events(timeout = 0.1)
                except timeout:
                    pass
        return requests


# TODO: couple this timeout to the HTTP reporting interval
DEFAULT_RESPONSE_TIMEOUT = 30


class PluginResponse(object):
    @classmethod
    def send(cls, plugin_name, resource_tag, request_id, response_data):
        exchange = Exchange("plugin_data", "direct", durable = True)
        with _amqp_connection() as conn:
            conn.connect()
            response_routing_key = "plugin_data_response_%s_%s" % (plugin_name, resource_tag)
            with conn.Producer(exchange = exchange, serializer = 'json', routing_key = response_routing_key) as producer:
                producer.publish({'id': request_id, 'data': response_data})

    @classmethod
    def receive(cls, plugin_name, resource_tag, request_id, timeout = DEFAULT_RESPONSE_TIMEOUT):
        with _amqp_connection() as conn:
            conn.connect()

            exchange = Exchange("plugin_data", "direct", durable = True)

            log.info("Waiting for response for %s:%s:%s" % (plugin_name, resource_tag, request_id))
            exchange = Exchange("plugin_data", "direct", durable = True)
            response_routing_key = "plugin_data_response_%s_%s" % (plugin_name, resource_tag)
            response_queue = Queue(response_routing_key, exchange = exchange, routing_key = response_routing_key)
            response_queue(conn.channel()).declare()
            response_data = []

            def handle_response(body, message):
                try:
                    id = body['id']
                except KeyError:
                    import json
                    log.warning("Malformed response '%s' on %s" % (json.dumps(body), response_routing_key))
                else:
                    if id == request_id:
                        response_data.append(body['data'])
                        log.info("Got response for request %s" % request_id)
                    else:
                        log.warning("Dropping unexpected response %s on %s" % (id, response_routing_key))
                finally:
                    message.ack()

            RESPONSE_TIMEOUT = 30
            _drain_all(conn, response_queue, handle_response, timeout = RESPONSE_TIMEOUT)
            if len(response_data) > 0:
                return response_data[0]
            else:
                raise Timeout("Got no response for %s:%s:%s in %s seconds" % (plugin_name, resource_tag, request_id, RESPONSE_TIMEOUT))
