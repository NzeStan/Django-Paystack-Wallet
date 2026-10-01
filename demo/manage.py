#!/usr/bin/env python
"""Demo project for django-paystack-wallet. See demo/README.md."""
import os
import sys
from pathlib import Path

# Use the wallet package from this repository (edits show up immediately)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'demo_project.settings')
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
