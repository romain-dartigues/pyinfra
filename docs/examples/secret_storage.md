# Using Secrets in pyinfra

Encrypting sensitive information can be achieved using Python packages such as [privy](https://pypi.org/project/privy/).

```py
# group_data/all.py

from getpass import getpass

import privy

def get_secret(encrypted_secret):
    password = getpass('Please provide the secret password: ')
    return privy.peek(encrypted_secret, password)

my_secret = get_secret('encrypted-secret-value')
```

An alternative might use an environment variable for the password:

```py
import os

import privy

def get_secret(encrypted_secret):
    password = os.environ['TOP_SECRET_PASSWORD']
    return privy.peek(encrypted_secret, password)
```

## Using FreeDesktop.org Secret Service standard

The [FreeDesktop.org Secret Service standard] is supported by, at least, [GNOME Keyring], [KWallet] and [KeePassXC].


https://pypi.org/project/keyring/


https://pypi.org/project/SecretStorage/
https://secretstorage.readthedocs.io/en/latest/collection.html#secretstorage.collection.search_items


https://gnome.pages.gitlab.gnome.org/libsecret/libsecret-python-examples.html

[FreeDesktop.org Secret Service standard]: https://specifications.freedesktop.org/secret-service/
[GNOME Keyring]: https://gitlab.gnome.org/GNOME/gnome-keyring
[KWallet]: https://github.com/KDE/kwallet
[KeePassXC]: https://keepassxc.org/