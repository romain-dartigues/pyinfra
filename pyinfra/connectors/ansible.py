"""
The `@ansible` connector can be used to parse Ansible inventory files.

.. code:: python

    # Let ansible guess it's inventories
    pyinfra @ansible fact server.LinuxName

    # Load an Ansible inventory relative to the current directory
    pyinfra @ansible/path/to/inventory

    # Load using an absolute path
    pyinfra @ansible//absolute/path/to/inventory
"""

from os import path
from typing import Optional
import json

from pyinfra import local
from pyinfra.api.exceptions import InventoryError
from pyinfra.progress import progress_spinner

from .base import BaseConnector

# dependencies
from typing_extensions import override


class AnsibleInventoryConnector(BaseConnector):
    @override
    @staticmethod
    def make_names_data(inventory_filename: Optional[str] = None):
        # why running an external command ヽ( ﾟДﾟ)ﾉ‽
        # well, it turns out *I* think it's the easiest way to get a relatively stable input format
        command = ["ansible-inventory --list"]
        if inventory_filename:
            if path.exists(inventory_filename):
                command += ["-i", inventory_filename]
            else:
                raise InventoryError(
                    f"Could not find Ansible inventory file: {inventory_filename}"
                )

        with progress_spinner({"ansible-inventory --list..."}):
            ansible_inventory_output_raw = local.shell(" ".join(command))
            progress_spinner("ansible-inventory --list...")

        ansible_inventory_output = json.loads(ansible_inventory_output_raw)

        ansible_all = ansible_inventory_output.pop("all", dict)
        ansible_groups = {
            key: row
            for key, row in ansible_inventory_output.items()
            if isinstance(row, dict) and "hosts" in row
        }

        for hostname, data in ansible_inventory_output.get("_meta",{}).get("hostvars",{}).items():
            groups = {
                group_name: group_values
                for group_name, group_values in ansible_groups.items()
                if hostname in group_values["hosts"]
            }
            data = ansible_all.get("vars", {}) | data
            """
            :inventory_hostname: an arbitrary name used as an ID in the Ansible inventory file
            :ansible_hostname: discovered as fact by Ansible
            :ansible_host: when set, override :var:`inventory_hostname` in order to connect to the host
            """
            if isinstance(data, dict):
                if ansible_become_user := data.pop("ansible_become_user", None):
                    data.setdefault("_sudo_user", ansible_become_user)
                if ansible_user := data.pop("ansible_user", None):
                    data.setdefault("ssh_user", ansible_user)
                if data.get("_sudo_user") != data.get("ssh_user") and data.get("ssh_user") is not None:
                    data.setdefault("_sudo", True)
                data.setdefault(
                    "ssh_hostname",
                    data.pop("ansible_host", hostname)
                )
            yield f"@ansible/{hostname}", data, ["@ansible"] + list(groups)
