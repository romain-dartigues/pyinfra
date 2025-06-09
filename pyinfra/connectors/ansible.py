"""
The `@ansible` connector can be used to parse Ansible inventory files.

.. code:: python

    # Load an Ansible inventory relative to the current directory
    pyinfra @ansible/path/to/inventory

    # Load using an absolute path
    pyinfra @ansible//absolute/path/to/inventory
"""

from os import path
from typing import TYPE_CHECKING, Optional

from pyinfra import local
from pyinfra.api.exceptions import InventoryError
from pyinfra.progress import progress_spinner

from .base import BaseConnector

if TYPE_CHECKING:
    pass

# dependencies
from typing_extensions import override


class AnsibleInventoryConnector(BaseConnector):
    @classmethod
    def _parse_inventory_tree(
        cls, inventory_tree: dict, host_to_groups: dict = None, group_stack: set = None
    ) -> dict:
        if host_to_groups is None:
            host_to_groups = {}

        if group_stack is None:
            group_stack = set()

        for group in inventory_tree:
            # set logic adds tolerance for duplicate group names
            groups = group_stack.union({group})

            if "hosts" in inventory_tree[group]:
                for host in inventory_tree[group]["hosts"]:
                    if host in host_to_groups:
                        # set logic handles de-duplication
                        host_to_groups[host] = host_to_groups[host].union(groups)
                    else:
                        host_to_groups[host] = groups

            if "children" in inventory_tree[group]:
                # recursively parse inventory tree
                cls._parse_inventory_tree(
                    inventory_tree[group]["children"], host_to_groups, groups
                )

        return host_to_groups

    @classmethod
    @override
    def make_names_data(cls, inventory_filename: Optional[str] = None):
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
            output = local.shell(" ".join(command))
            progress_spinner("ansible-inventory --list...")

        host_to_groups = cls._parse_inventory_tree(output)

        return [
            (host, {}, sorted(list(host_to_groups.get(host, []))))
            for host in host_to_groups
        ]
