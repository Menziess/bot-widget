"""python -m botwidget starts the widget."""

import sys

if "--instances" in sys.argv[1:]:
    from botwidget.instance import instances_main

    sys.exit(instances_main())

from botwidget.qt_ui.app import main

main()
