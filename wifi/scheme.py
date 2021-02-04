import re
import itertools
import logging
from os import listdir, remove
from os.path import join, isfile, exists

import wifi.subprocess_compat as subprocess
from pbkdf2 import PBKDF2
from wifi.utils import ensure_file_exists
from wifi.exceptions import *


def configuration(cell, passkey=None):
    """
    Returns a dictionary of configuration options for cell

    Asks for a password if necessary
    """
    if not cell.encrypted:
        return {
            'wireless-essid': cell.ssid,
            'wireless-channel': 'auto',
        }
    else:
        if cell.encryption_type.startswith('wpa'):
            if len(passkey) != 64:
                passkey = PBKDF2(passkey, cell.ssid, 4096).hexread(32)

            return {
                'wpa-ssid': cell.ssid,
                'wpa-psk': passkey,
                'wireless-channel': 'auto',
            }
        elif cell.encryption_type == 'wep':
            # Pass key lengths in bytes for WEP depend on type of key and key length:
            #
            #       64bit   128bit   152bit   256bit
            # hex     10      26       32       58
            # ASCII    5      13       16       29
            #
            # (source: https://en.wikipedia.org/wiki/Wired_Equivalent_Privacy)
            #
            # ASCII keys need to be prefixed with an s: in the interfaces file in order to work with linux' wireless
            # tools

            ascii_lengths = (5, 13, 16, 29)
            if len(passkey) in ascii_lengths:
                # we got an ASCII passkey here (otherwise the key length wouldn't match), we'll need to prefix that
                # with s: in our config for the wireless tools to pick it up properly
                passkey = "s:" + passkey

            return {
                'wireless-essid': cell.ssid,
                'wireless-key': passkey,
            }
        else:
            raise NotImplementedError


bound_ip_re = re.compile(r'^bound to (?P<ip_address>\S+)', flags=re.MULTILINE)


class Scheme(object):
    """
    Saved configuration for connecting to a wireless network.  This
    class provides a Python interface to the /etc/network/interfaces
    file.
    """

    interfaces = join('/etc', 'network', 'interfaces')
    interfaces_d = join('/etc', 'network', 'interfaces.d')

    @classmethod
    def for_file(cls, interfaces, interfaces_d):
        """
        A class factory for providing a nice way to specify the interfaces file
        that you want to use.  Use this instead of directly overwriting the
        interfaces Class attribute if you care about thread safety.
        """
        return type(cls)(cls.__name__, (cls,), {
            'interfaces': interfaces,
            'interfaces_d': interfaces_d,
        })

    def __init__(self, interface, name, type="dhcp", options=None):
        self.interface = interface
        self.name = name
        self.type = type

        if options:
            for k, v in options.items():
                if not isinstance(v, (list, tuple)):
                    options[k] = [v]
        self.options = options or {}

        self.logger = logging.getLogger(__name__)

    def __str__(self):
        """
        Returns the representation of a scheme that you would need
        in the /etc/network/interfaces file.
        """
        iface = "iface {interface}-{name} inet {type}".format(**vars(self))
        options = ''.join("\n    {k} {v}".format(k=k, v=v) for k in self.options.keys() for v in self.options[k])
        return iface + options + '\n'

    def __repr__(self):
        return 'Scheme(interface={interface!r}, name={name!r}, options={options!r}'.format(**vars(self))

    @classmethod
    def all(cls):
        """
        Returns an generator of saved schemes.
        """
        ensure_file_exists(cls.interfaces)
        schemes = []
        with open(cls.interfaces, 'r') as f:
            schemes.extend(extract_schemes(f.read(), scheme_class=cls))
        for iface_file in [f for f in listdir(cls.interfaces_d) 
            if isfile(join(cls.interfaces_d, f))]:
                with open(join(cls.interfaces_d, iface_file), 'r') as f:
                    schemes.extend(extract_schemes(f.read(), scheme_class=cls))

        print(schemes)
        for scheme in schemes:
            yield scheme


    @classmethod
    def where(cls, fn):
        return list(filter(fn, cls.all()))

    @classmethod
    def find(cls, interface, name):
        """
        Returns a :class:`Scheme` or `None` based on interface and
        name.
        """
        try:
            return cls.where(lambda s: s.interface == interface and s.name == name)[0]
        except IndexError:
            return None

    @classmethod
    def for_cell(cls, interface, name, cell, passkey=None):
        """
        Intuits the configuration needed for a specific
        :class:`Cell` and creates a :class:`Scheme` for it.
        """
        return cls(interface, name, options=configuration(cell, passkey))

    def save(self, allow_overwrite=False):
        """
        Writes the configuration to the :attr:`interfaces` file.
        """
        existing_scheme = self.find(self.interface, self.name)
        if existing_scheme:
            if not allow_overwrite:
                raise RuntimeError("Scheme for interface %s named %s already exists and overwrite is forbidden" % (self.interface, self.name))
            existing_scheme.delete()

        iface_file = join(self.interfaces_d,
            "%s-%s" % (self.interface, self.name))
        with open(iface_file, 'w') as f:
            f.write(str(self))

    def delete(self):
        """
        Deletes the configuration from the :attr:`interfaces` file.
        Also deletes a corresponding file in /etc/network/interfaces.d
        """
        iface = "iface %s-%s inet %s" % (self.interface, self.name, self.type)
        content = ''
        with open(self.interfaces, 'r') as f:
            skip = False
            for line in f:
                if not line.strip():
                    skip = False
                elif line.strip().startswith(iface):
                    skip = True
                if not skip:
                    content += line
        with open(self.interfaces, 'w') as f:
            f.write(content)
        iface_file = join(self.interfaces_d,
            "%s-%s" % (self.interface, self.name))
        if exists(iface_file):
            remove(iface_file)


    @property
    def iface(self):
        return '{0}-{1}'.format(self.interface, self.name)

    def as_args(self):
        args = list(itertools.chain.from_iterable(
            ('-o', '{k}={v}'.format(k=k, v=v)) for k in self.options.keys() for v in self.options[k]))

        return [self.interface + '=' + self.iface] + args

    def activate(self):
        """
        Connects to the network as configured in this scheme.
        """

        try:
            self.deactivate()
        except subprocess.CalledProcessError:
            # TODO: check error message to see whether to ignore
            pass
        try:
            ifup_output = subprocess.check_output(['/sbin/ifup'] + self.as_args(), stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            self.logger.exception("Error while trying to connect to %s" % self.iface)
            self.logger.error("Output: %s" % e.output)
            raise InterfaceError("Failed to connect to %r: %s" % (self, e.message))
        ifup_output = ifup_output.decode('utf-8')

        return self.parse_ifup_output(ifup_output)

    def deactivate(self):
        """
        Disconnects from the network as configured in this scheme.
        """

        subprocess.check_output(['/sbin/ifdown', self.interface], stderr=subprocess.STDOUT)

    def parse_ifup_output(self, output):
        if self.type == "dhcp":
            matches = bound_ip_re.search(output)
            if matches:
                return Connection(scheme=self, ip_address=matches.group('ip_address'))
            else:
                raise ConnectionError("Failed to connect to %r" % self)
        else:
            return Connection(scheme=self, ip_address=self.options["address"][0])


class Connection(object):
    """
    The connection object returned when connecting to a Scheme.
    """
    def __init__(self, scheme, ip_address):
        self.scheme = scheme
        self.ip_address = ip_address


# TODO: support other interfaces
scheme_re = re.compile(r'iface\s+(?P<interface>wlan\d?)(?:-(?P<name>\w+))?\s+inet\s+(?P<type>\w+)')


def extract_schemes(interfaces, scheme_class=Scheme):
    schemes = []
    lines = interfaces.splitlines()
    while lines:
        line = lines.pop(0)

        if line.startswith('#') or not line:
            continue

        match = scheme_re.match(line)
        if match:
            options = {}
            interface, scheme, type = match.groups()

            if not scheme or not interface:
                continue

            while lines and lines[0].startswith(' '):
                key, value = re.sub(r'\s{2,}', ' ', lines.pop(0).strip()).split(' ', 1)
                if not key in options:
                    options[key] = []
                options[key].append(value)

            schemes.append(scheme_class(interface, scheme, type=type,
                options=options))

    return schemes
