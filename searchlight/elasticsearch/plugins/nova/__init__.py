# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import json
import logging
import novaclient.exceptions
import six

from searchlight.elasticsearch.plugins import openstack_clients
from searchlight.elasticsearch.plugins import utils
from searchlight.i18n import _LW

LOG = logging.getLogger(__name__)


# All 'links' will also be removed
BLACKLISTED_FIELDS = set((u'progress', u'links'))
FLAVOR_ACCESS_FIELD = 'tenant_access'


def _get_flavor_access(flavor):
    if flavor.is_public:
        return None
    try:
        n_client = openstack_clients.get_novaclient()
        return [access.tenant_id for access in
                n_client.flavor_access.list(flavor=flavor)] or None
    except novaclient.exceptions.Unauthorized:
        LOG.warning(_LW("Could not return tenant for %s; forbidden") %
                    flavor)
        return None


def serialize_nova_server(server):
    nc_client = openstack_clients.get_novaclient()
    if isinstance(server, six.text_type):
        server = nc_client.servers.get(server)

    LOG.debug("Serializing server %s for project %s",
              server.id, server.tenant_id)
    serialized = {k: v for k, v in six.iteritems(server.to_dict())
                  if k not in BLACKLISTED_FIELDS}

    # Some enhancements
    serialized[u'owner'] = server.tenant_id
    serialized[u'project_id'] = server.tenant_id
    # Image is empty when the instance is booted from volume
    if isinstance(serialized[u'image'], dict):
        serialized[u'image'].pop(u'links', None)
    else:
        serialized.pop(u'image')
    serialized[u'flavor'].pop(u'links', None)

    sec_groups = serialized.pop(u'security_groups', [])
    serialized['security_groups'] = [s[u'name'] for s in sec_groups]

    _format_networks(server, serialized)

    utils.normalize_date_fields(serialized)

    return serialized


def serialize_nova_hypervisor(hypervisor, updated_at=None):
    serialized = hypervisor.to_dict()
    # The id for hypervisor is an integer, should be changed to
    # string.
    serialized['id'] = str(serialized['id'])
    # The 'cpu_info' field of hypervisor has changed from string
    # to JSON object in microversion 2.28, we should be able to
    # deal with JSON object here.
    if not isinstance(serialized['cpu_info'], dict):
        serialized['cpu_info'] = json.loads(serialized['cpu_info'])
    if not getattr(hypervisor, 'updated_at', None):
        serialized['updated_at'] = updated_at or utils.get_now_str()
    # TODO(lyj): Remove this once hypervisor notifications supported.
    for key in ['running_vms', 'vcpus_used', 'memory_mb_used', 'free_ram_mb',
                'free_disk_gb', 'local_gb_used', 'current_workload']:
        if key in serialized:
            serialized.pop(key)
    return serialized


def serialize_nova_flavor(flavor, updated_at=None):
    serialized = {k: v for k, v in six.iteritems(flavor.to_dict())
                  if k not in ("links")}
    serialized["extra_specs"] = flavor.get_keys()

    serialized[FLAVOR_ACCESS_FIELD] = _get_flavor_access(flavor)

    if not getattr(flavor, 'updated_at', None):
        serialized['updated_at'] = updated_at or utils.get_now_str()
    return serialized


def serialize_nova_servergroup(servergroup, updated_at=None):
    serialized = servergroup.to_dict()
    if not getattr(servergroup, 'updated_at', None):
        serialized['updated_at'] = updated_at or utils.get_now_str()
    return serialized


def _format_networks(server, serialized):
    networks = []

    # Keep the original as well
    addresses = copy.deepcopy(server.addresses)

    for net_name, ports in six.iteritems(addresses):
        for port in ports:

            LOG.debug("Transforming net %s port %s for server %s",
                      net_name, port, server)
            addr = {u"name": net_name}
            port_address = port.pop(u'addr')
            if port[u'version'] == 4:
                port[u'ipv4_addr'] = port_address
            elif port[u'version'] == 6:
                port[u'ipv6_addr'] = port_address
            addr.update(port)
            networks.append(addr)
    serialized[u'networks'] = networks
