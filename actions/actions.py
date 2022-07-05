#!/usr/bin/env python3
#
# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess
import sys
import uuid

sys.path.append('hooks/')

import multisite

from charmhelpers.core.hookenv import (
    action_fail,
    config,
    is_leader,
    leader_set,
    action_set,
    action_get,
    log,
    ERROR,
    DEBUG,
)
from charmhelpers.contrib.openstack.ip import (
    canonical_url,
    PUBLIC,
)
from utils import (
    pause_unit_helper,
    resume_unit_helper,
    register_configs,
    listen_port,
    service_name,
)
from charmhelpers.core.host import (
    service_restart,
)


def pause(args):
    """Pause the Ceilometer services.
    @raises Exception should the service fail to stop.
    """
    pause_unit_helper(register_configs())


def resume(args):
    """Resume the Ceilometer services.
    @raises Exception should the service fail to start."""
    resume_unit_helper(register_configs())


def promote(args):
    """Promote zone associated with local RGW units to master/default"""
    zone = config('zone')
    zonegroup = config('zonegroup')
    if not is_leader():
        action_fail('This action can only be executed on leader unit.')
        return
    if not zone:
        action_fail('No zone configuration set, not promoting')
        return
    try:
        multisite.modify_zone(zone,
                              default=True, master=True)
        multisite.update_period(zonegroup=zonegroup, zone=zone)
        leader_set(restart_nonce=str(uuid.uuid4()))
        service_restart(service_name())
        action_set(
            values={'message': 'zone:{} promoted to '
                    'master/default'.format(zone)}
        )
    except subprocess.CalledProcessError as cpe:
        action_fail('Unable to promote zone:{} '
                    'to master: {}'.format(zone, cpe.output))


def readonly(args):
    """Mark zone associated with local RGW units as read only"""
    zone = config('zone')
    if not zone:
        action_fail('No zone configuration set, not marking read only')
        return
    try:
        multisite.modify_zone(zone, readonly=True)
        multisite.update_period()
        action_set(
            values={
                'message': 'zone:{} marked as read only'.format(zone)
            }
        )
    except subprocess.CalledProcessError as cpe:
        action_fail('Unable mark zone:{} '
                    'as read only: {}'.format(zone, cpe.output))


def readwrite(args):
    """Mark zone associated with local RGW units as read write"""
    zone = config('zone')
    if not zone:
        action_fail('No zone configuration set, not marking read write')
        return
    try:
        multisite.modify_zone(zone, readonly=False)
        multisite.update_period()
        action_set(
            values={
                'message': 'zone:{} marked as read write'.format(zone)
            }
        )
    except subprocess.CalledProcessError as cpe:
        action_fail('Unable mark zone:{} '
                    'as read write: {}'.format(zone, cpe.output))


def tidydefaults(args):
    """Delete default zone and zonegroup metadata"""
    zone = config('zone')
    if not zone:
        action_fail('No zone configuration set, not deleting defaults')
        return
    try:
        multisite.tidy_defaults()
        action_set(
            values={
                'message': 'default zone and zonegroup deleted'
            }
        )
    except subprocess.CalledProcessError as cpe:
        action_fail('Unable delete default zone and zonegroup'
                    ': {} - {}'.format(zone, cpe.output))


def force_enable_multisite(args):
    """Configure provided zone and zonegroup according to Multisite Config

    In a situation when multiple zone or zonegroups are configured on the
    primary site, the decision for which pair to use in multisite system
    is taken through this action. It takes provided parameters (zone name
    and zonegroup name) and rename/ modify them appropriately.
    """
    public_url = '{}:{}'.format(
        canonical_url(register_configs(), PUBLIC),
        listen_port(),
    )
    current_zone = action_get("zone")
    current_zonegroup = action_get("zonegroup")
    endpoints = [public_url]
    realm = config('realm')
    new_zone = config('zone')
    new_zonegroup = config('zonegroup')

    log("zone:{}, zonegroup:{}, endpoints:{}, realm:{}, new_zone:{}, "
        "new_zonegroup:{}".format(
            current_zone, current_zonegroup, endpoints,
            realm, new_zone, new_zonegroup
        ), level=DEBUG)

    if not is_leader():
        action_fail('This action can only be executed on leader unit.')
        return

    if not all((realm, new_zonegroup, new_zone)):
        action_fail("Missing required charm configurations realm({}), "
                    "zonegroup({}) and zone({}).".format(
                        realm, new_zonegroup, new_zone
                    ))
        return

    if current_zone not in multisite.list_zones():
        action_fail('Provided zone {} does not exist.'.format(current_zone))
        return

    if current_zonegroup not in multisite.list_zonegroups():
        action_fail('Provided zone {} does not exist.'
                    .format(current_zonegroup))
        return

    try:
        # Rename chosen zonegroup/zone as per charm config value.
        rename_result = multisite.rename_multisite_config(
            [current_zonegroup],
            new_zonegroup,
            [current_zone], new_zone
        )
        if rename_result is None:
            action_fail('Failed to rename zone {} or zonegroup {}.'
                        .format(current_zone, current_zonegroup))
            return

        # Configure zonegroup/zone as master for multisite.
        modify_result = multisite.modify_multisite_config(
            new_zone, new_zonegroup,
            realm=realm,
            endpoints=endpoints
        )
        if modify_result is None:
            action_fail('Failed to configure zone {} or zonegroup {}.'
                        .format(new_zonegroup, new_zone))
            return

        leader_set(restart_nonce=str(uuid.uuid4()))
        service_restart(service_name())
        action_set(
            values={
                'message': 'Multisite Configuration Resolved'
            }
        )
    except subprocess.CalledProcessError as cpe:
        message = "Failed to configure zone ({}) and zonegroup ({})".format(
            current_zone, current_zonegroup
        )
        log(message, level=ERROR)
        action_fail(message + " : {}".format(cpe.output))


# A dictionary of all the defined actions to callables (which take
# parsed arguments).
ACTIONS = {
    "pause": pause,
    "resume": resume,
    "promote": promote,
    "readonly": readonly,
    "readwrite": readwrite,
    "tidydefaults": tidydefaults,
    "force-enable-multisite": force_enable_multisite,
}


def main(args):
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        return "Action %s undefined" % action_name
    else:
        try:
            action(args)
        except Exception as e:
            action_fail(str(e))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
