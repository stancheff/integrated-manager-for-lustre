#
# INTEL CONFIDENTIAL
#
# Copyright 2013 Intel Corporation All Rights Reserved.
#
# The source code contained or described herein and all documents related
# to the source code ("Material") are owned by Intel Corporation or its
# suppliers or licensors. Title to the Material remains with Intel Corporation
# or its suppliers and licensors. The Material contains trade secrets and
# proprietary and confidential information of Intel or its suppliers and
# licensors. The Material is protected by worldwide copyright and trade secret
# laws and treaty provisions. No part of the Material may be used, copied,
# reproduced, modified, published, uploaded, posted, transmitted, distributed,
# or disclosed in any way without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be
# express and approved by Intel in writing.


import logging

import settings
from django.db import models
from django.db.models.signals import post_save, post_delete, pre_delete
from south.signals import post_migrate
from django.dispatch import receiver
from django.core.exceptions import ValidationError

from chroma_core.models.alert import AlertState
from chroma_core.models.event import AlertEvent
from chroma_core.models.host import ManagedHost
from chroma_core.models.jobs import Job, AdvertisedJob
from chroma_core.models.utils import DeletableMetaclass

from chroma_core.lib.job import Step, DependOn


class DeletablePowerControlModel(models.Model):
    __metaclass__ = DeletableMetaclass

    class Meta:
        abstract = True
        app_label = 'chroma_core'


class PowerControlType(DeletablePowerControlModel):
    agent = models.CharField(null = False, blank = False, max_length = 255,
            choices = [(a, a) for a in settings.SUPPORTED_FENCE_AGENTS],
            help_text = "Fencing agent (e.g. fence_apc, fence_ipmilan, etc.)")
    make = models.CharField(null = True, blank = True, max_length = 50,
            help_text = "Device manufacturer string")
    model = models.CharField(null = True, blank = True, max_length = 50,
            help_text = "Device model string")
    max_outlets = models.PositiveIntegerField(default = 0, blank = True,
            help_text = "The maximum number of outlets which may be associated with an instance of this device type (0 is unlimited)")
    default_port = models.PositiveIntegerField(default = 23, blank = True,
            help_text = "Network port used to access power control device")
    default_username = models.CharField(null = True, blank = True,
            max_length = 128, help_text = "Factory-set admin username")
    default_password = models.CharField(null = True, blank = True,
            max_length = 128, help_text = "Factory-set admin password")
    default_options = models.CharField(null = True, blank = True, max_length = 255,
            help_text = "Default set of options to be passed when invoking fence agent")
    # These defaults have been verified with fence_apc, but should work with
    # most fence agents. Some adjustments may be required (e.g. fence_xvm
    # wants -H <domain> rather than -n).
    poweron_template = models.CharField(blank = True, max_length = 512, help_text = "Command template for switching an outlet on", default = "%(agent)s %(options)s -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o on -n %(identifier)s")
    powercycle_template = models.CharField(blank = True, max_length = 512, help_text = "Command template for cycling an outlet", default = "%(agent)s %(options)s  -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o reboot -n %(identifier)s")
    poweroff_template = models.CharField(blank = True, max_length = 512, help_text = "Command template for switching an outlet off", default = "%(agent)s %(options)s -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o off -n %(identifier)s")
    monitor_template = models.CharField(blank = True, max_length = 512, help_text = "Command template for checking that a PDU is responding", default = "%(agent)s %(options)s -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o monitor")
    outlet_query_template = models.CharField(blank = True, max_length = 512, help_text = "Command template for querying an individual outlet's state", default = "%(agent)s %(options)s -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o status -n %(identifier)s")
    outlet_list_template = models.CharField(null = True, blank = True, max_length = 512, help_text = "Command template for listing all outlets on a PDU", default = "%(agent)s %(options)s -a %(address)s -u %(port)s -l %(username)s -p %(password)s -o list")

    def display_name(self):
        make = self.make if self.make != "" else "Unknown Make"
        model = self.model if self.model != "" else "Unknown Model"
        count = self.max_outlets if self.max_outlets > 0 else "IPMI"
        return "%s %s (%s)" % (make, model, count)

    def __str__(self):
        return self.display_name()

    class Meta:
        app_label = 'chroma_core'
        unique_together = ('agent', 'make', 'model')


def create_default_power_types(app, **kwargs):
    if app != 'chroma_core':
        return

    import os
    import json
    import chroma_core
    chroma_core = os.path.abspath(os.path.dirname(chroma_core.__file__))
    with open(os.path.join(chroma_core, "fixtures/default_power_types.json")) as f:
        default_types = json.load(f)

    for power_type in default_types:
        try:
            PowerControlType.objects.get(agent = power_type['agent'],
                                         make = power_type['make'],
                                         model = power_type['model'])
        except PowerControlType.DoesNotExist:
            PowerControlType.objects.create(**power_type)

    print "Loaded %d default power device types." % len(default_types)

post_migrate.connect(create_default_power_types)


@receiver(pre_delete, sender = PowerControlType)
def delete_power_control_units(sender, instance, **kwargs):
    [d.mark_deleted() for d in instance.instances.all()]


class PowerControlDeviceUnavailableAlert(AlertState):
    # This is WARNING because if a power control device is out
    # of touch it may be behaving in an undefined way, therefore
    # may be unable to participate in a failover operation, resulting
    # in a reduced level of filesystem availability.
    default_severity = logging.WARNING

    class Meta:
        app_label = 'chroma_core'

    def message(self):
        return "Unable to monitor power control device %s" % self.alert_item

    def end_event(self):
        return AlertEvent(
            message_str = "Monitoring resumed for power control device %s" % self.alert_item,
            alert = self,
            severity = logging.INFO)


class PowerControlDevice(DeletablePowerControlModel):
    device_type = models.ForeignKey('PowerControlType', related_name = 'instances')
    name = models.CharField(null = False, blank = True, max_length = 50,
            help_text = "Optional human-friendly display name (defaults to address)")
    # We need to work with a stable IP address, not a hostname. STONITH must
    # work even if DNS doesn't!
    address = models.IPAddressField(null = False, blank = False,
            help_text = "IP address of power control device")
    port = models.PositiveIntegerField(default = 23, blank = True,
            help_text = "Network port used to access power control device")
    username = models.CharField(null = False, blank = True,
            max_length= 64, help_text = "Username for device administration")
    # FIXME: (HYD-1913) Don't store these passwords in plaintext!
    password = models.CharField(null = False, blank = True,
            max_length= 64, help_text = "Password for device administration")
    options = models.CharField(null = True, blank = True, max_length = 255,
            help_text = "Custom options to be passed when invoking fence agent")

    def __str__(self):
        return self.name

    class Meta:
        app_label = 'chroma_core'
        unique_together = ('address', 'port')

    def clean(self):
        # Allow the device_type to set defaults for unsupplied fields.
        type_defaults = ["username", "password", "options", "port"]
        for default in type_defaults:
            if getattr(self, default) in ["", None]:
                setattr(self, default,
                        getattr(self.device_type, "default_%s" % default))

        if self.address in ["", None]:
            raise ValidationError("Address may not be blank")

        import socket
        try:
            self.address = socket.gethostbyname(self.address)
        except socket.gaierror, e:
            raise ValidationError("Unable to resolve %s: %s" % (self.address, e))

        if self.name in ["", None]:
            self.name = self.address

    def save(self, *args, **kwargs):
        self.full_clean()
        super(PowerControlDevice, self).save(*args, **kwargs)

    @property
    def all_outlets_known(self):
        return all([True if o.has_power in [True, False] else False
                   for o in self.outlets.all()])

    @property
    def sockaddr(self):
        "Convenience method for getting at (self.address, self.port)"
        return (self.address, self.port)

    def _template_to_command(self, template, identifier = None):
        import re
        from os.path import expanduser

        cmd_str = getattr(self.device_type, "%s_template" % template) % {
                'agent': self.device_type.agent,
                'address': self.address,
                'port': self.port,
                'username': self.username,
                'password': self.password,
                'identifier': identifier,
                'options': self.options,
                'home': expanduser("~")
            }
        return re.split(r'\s+', cmd_str)

    def poweron_command(self, identifier):
        return self._template_to_command('poweron', identifier)

    def poweroff_command(self, identifier):
        return self._template_to_command('poweroff', identifier)

    def powercycle_command(self, identifier):
        return self._template_to_command('powercycle', identifier)

    def monitor_command(self):
        return self._template_to_command('monitor')

    def outlet_query_command(self, identifier):
        return self._template_to_command('outlet_query', identifier)

    def outlet_list_command(self):
        return self._template_to_command('outlet_list')


@receiver(post_save, sender = PowerControlDevice)
def prepopulate_outlets(sender, instance, created, **kwargs):
    # Prepopulate outlets for real PDUs. IPMI "PDUs" don't have a
    # fixed number of outlets
    if created and instance.device_type.max_outlets > 0:
        for i in xrange(1, instance.device_type.max_outlets + 1):
            instance.outlets.create(identifier = i)


@receiver(post_save, sender = PowerControlDevice)
def register_power_device(sender, instance, created, **kwargs):
    from chroma_core.services.power_control.rpc import PowerControlRpc
    if instance.not_deleted is None:
        return

    if not created:
        PowerControlRpc().reregister_device(instance.id)
    else:
        PowerControlRpc().register_device(instance.id)


@receiver(post_delete, sender = PowerControlDevice)
def unregister_power_device(sender, instance, **kwargs):
    from chroma_core.services.power_control.rpc import PowerControlRpc
    PowerControlRpc().unregister_device(instance.sockaddr)


@receiver(pre_delete, sender = PowerControlDevice)
def delete_outlets(sender, instance, **kwargs):
    [o.mark_deleted() for o in instance.outlets.all()]


class PowerControlDeviceOutlet(DeletablePowerControlModel):
    device = models.ForeignKey('PowerControlDevice', related_name = 'outlets')
    # http://www.freesoft.org/CIE/RFC/1035/9.htm (max dns name == 255 octets)
    identifier = models.CharField(null = False, blank = False,
            max_length = 254, help_text = "A string by which the associated device can identify the controlled resource (e.g. PDU outlet number, libvirt domain name, ipmi mgmt address, etc.)")
    host = models.ForeignKey('ManagedHost', related_name = 'outlets',
            null = True, blank = True, help_text = "Optional association with a ManagedHost instance")
    has_power = models.NullBooleanField(help_text = "Outlet power status (On, Off, Unknown)")

    def clean(self):
        try:
            # Irritating. There is no way to tell from the constructed instance
            # if the validation is for a new object or one being updated.
            PowerControlDeviceOutlet.objects.get(identifier = self.identifier, device = self.device)
            is_update = True
        except PowerControlDeviceOutlet.DoesNotExist:
            is_update = False

        if not is_update:
            max_device_outlets = self.device.device_type.max_outlets
            if max_device_outlets > 0:
                if self.device.outlets.count() >= max_device_outlets:
                    raise ValidationError("Device %s is already at maximum number of outlets: %d" % (self.device.name, max_device_outlets))

        super(PowerControlDeviceOutlet, self).clean()

    def save(self, *args, **kwargs):
        skip_reconfigure = kwargs.pop('skip_reconfigure', False)

        if not skip_reconfigure:
            self.full_clean()

            # Grab a copy of the outlet pre-save so that we can determine
            # which hosts need to have their fencing reconfigured.
            try:
                old_self = PowerControlDeviceOutlet.objects.get(pk = self.pk)
            except PowerControlDeviceOutlet.DoesNotExist:
                old_self = None

        super(PowerControlDeviceOutlet, self).save(*args, **kwargs)

        if skip_reconfigure:
            return

        from chroma_core.services.job_scheduler.job_scheduler_client import JobSchedulerClient
        from django.utils.timezone import now
        reconfigure = {'needs_fence_reconfiguration': True}
        if self.host is not None:
            if old_self and old_self.host and old_self.host != self.host:
                JobSchedulerClient.notify(old_self.host, now(), reconfigure)
            JobSchedulerClient.notify(self.host, now(), reconfigure)
        elif self.host is None and old_self is not None:
            if old_self.host is not None:
                JobSchedulerClient.notify(old_self.host, now(), reconfigure)

    def force_host_disassociation(self):
        """
        Override save() signals which could result in undesirable async
        behavior on a forcibly-removed host (don't mess with STONITH, etc.)
        """
        self.host = None
        self.save(skip_reconfigure = True)

    @property
    def power_state(self):
        if self.has_power is None:
            return "Unknown"
        else:
            return "ON" if self.has_power else "OFF"

    def __str__(self):
        return "%s: %s" % (self.identifier, self.power_state)

    class Meta:
        app_label = 'chroma_core'
        unique_together = ('device', 'identifier', 'host')


class PoweronHostJob(AdvertisedJob):
    host = models.ForeignKey(ManagedHost)
    requires_confirmation = True
    classes = ['ManagedHost']
    verb = "Power On"

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    @classmethod
    def get_args(cls, host):
        return {'host_id': host.id}

    @classmethod
    def can_run(cls, host):
        # We should only be able to issue a Poweron if:
        # 1. The host is associated with >= 1 outlet
        # 2. All associated outlets are in a known state (On or Off)
        # 3. None of the associated outlets are On
        return (host.outlets.count()
                and all([True if o.has_power in [True, False] else False
                            for o in host.outlets.all()])
                and not any([o.has_power for o in host.outlets.all()]))

    @classmethod
    def get_confirmation(cls, instance):
        return "Switch on power to this server."

    def description(self):
        return "Restore power for server %s" % self.host

    def get_steps(self):
        return [(TogglePduOutletStateStep, {'outlets': self.host.outlets.all(), 'toggle_state': 'on'})]


class PoweroffHostJob(AdvertisedJob):
    host = models.ForeignKey(ManagedHost)
    requires_confirmation = True
    classes = ['ManagedHost']
    verb = "Power Off"

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    @classmethod
    def get_args(cls, host):
        return {'host_id': host.id}

    @classmethod
    def can_run(cls, host):
        # We should only be able to issue a Poweroff if:
        # 1. The host is associated with >= 1 outlet
        # 2. All associated outlets are in a known state (On or Off)
        # 3. Any of the associated outlets are On
        return (host.outlets.count()
                and all([True if o.has_power in [True, False] else False
                            for o in host.outlets.all()])
                and any([o.has_power for o in host.outlets.all()]))

    @classmethod
    def get_confirmation(cls, instance):
        return "Switch off power to this server. Any HA-capable targets running on the server will be failed over to a peer. Non-HA-capable targets will be unavailable until the server is turned on again."

    def description(self):
        return "Kill power for server %s" % self.host

    def get_steps(self):
        return [(TogglePduOutletStateStep, {'outlets': self.host.outlets.all(), 'toggle_state': 'off'})]


class PowercycleHostJob(AdvertisedJob):
    host = models.ForeignKey(ManagedHost)
    requires_confirmation = True
    classes = ['ManagedHost']
    verb = "Power cycle"

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    @classmethod
    def get_args(cls, host):
        return {'host_id': host.id}

    @classmethod
    def can_run(cls, host):
        # We should be able to issue a Powercycle if:
        # 1. The host is associated with >= 1 outlet
        #
        # NB: Issuing a powercycle will always result in the outlet being
        # switched On, so we can rely on this to get into a known state.
        return host.outlets.count()

    @classmethod
    def get_confirmation(cls, instance):
        return "Switch the power to this server off and then back on again. Any HA-capable targets running on the server will be failed over to a peer. Non-HA-capable targets will be unavailable until the server has finished booting."

    def description(self):
        return "Cycle power for server %s" % self.host

    def get_steps(self):
        # We can't use the PDU 'reboot' action, because that's per-outlet, and
        # a multi-PSU server will survive the cycling of each outlet unless
        # they're done in unison.
        outlets = self.host.outlets.all()
        outlets_off_step = (TogglePduOutletStateStep, {'outlets': outlets, 'toggle_state': 'off'})
        outlets_on_step = (TogglePduOutletStateStep, {'outlets': outlets, 'toggle_state': 'on'})
        return [outlets_off_step, outlets_on_step]


class TogglePduOutletStateStep(Step):
    idempotent = True
    # FIXME: This is necessary in order to invoke RPCs (HYD-1912)
    database = True

    def run(self, args):
        from chroma_core.services.power_control.client import PowerControlClient
        PowerControlClient.toggle_device_outlets(args['toggle_state'], args['outlets'])


class ConfigureHostFencingJob(Job):
    host = models.ForeignKey(ManagedHost)
    requires_confirmation = False
    verb = "Configure Host Fencing"

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    @classmethod
    def get_args(cls, host):
        return {'host_id': host.id}

    def description(self):
        return "Configure fencing agent on %s" % self.host

    def get_steps(self):
        return [(ConfigureHostFencingStep, {'host': self.host})]

    def get_deps(self):
        return DependOn(self.host, 'configured', acceptable_states=self.host.not_state('removed'))

    def on_success(self):
        self.host.needs_fence_reconfiguration = False
        self.host.save()


class ConfigureHostFencingStep(Step):
    idempotent = True
    # Needs database in order to query host outlets
    database = True

    def run(self, kwargs):
        host = kwargs['host']
        if host.immutable_state:
            return

        agent_kwargs = []
        for outlet in host.outlets.select_related().all():
            agent_kwargs.append({'plug': outlet.identifier,
                                 'agent': outlet.device.device_type.agent,
                                 'login': outlet.device.username,
                                 'password': outlet.device.password,
                                 'ipaddr': outlet.device.address,
                                 'ipport': outlet.device.port})

        self.invoke_agent(host, "configure_fencing", {'agents': agent_kwargs})
