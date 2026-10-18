# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataexplorer.app import main

if __name__ == "__main__":
    sys.exit(main())
